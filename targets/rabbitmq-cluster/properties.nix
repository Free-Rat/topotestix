{ lib }:

{
  cluster_formed = {
    name = "rabbitmq-cluster-formed";
    setup = ''
def check_rabbitmq_cluster_formed(machine):
    machine.succeed(
        "su -s /bin/sh rabbitmq -c 'rabbitmqctl cluster_status' > /tmp/rabbitmq-cluster-status && "
        "grep -q 'rabbit@rabbit1' /tmp/rabbitmq-cluster-status && "
        "grep -q 'rabbit@rabbit2' /tmp/rabbitmq-cluster-status && "
        "grep -q 'rabbit@rabbit3' /tmp/rabbitmq-cluster-status"
    )
    '';
    check = ''
_check("rabbitmq-cluster-formed-rabbit1", check_rabbitmq_cluster_formed, rabbit1)
_check("rabbitmq-cluster-formed-rabbit2", check_rabbitmq_cluster_formed, rabbit2)
_check("rabbitmq-cluster-formed-rabbit3", check_rabbitmq_cluster_formed, rabbit3)
    '';
  };

  quorum_queue_roundtrip = {
    name = "rabbitmq-quorum-queue-roundtrip";
    setup = ''
def check_rabbitmq_quorum_roundtrip(declarer, writer, reader, queue, payload):
    declarer.succeed(f"""
python3 - <<'PY'
import pika

queue = {queue!r}
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
channel.queue_declare(
    queue=queue,
    durable=True,
    arguments={{"x-queue-type": "quorum", "x-quorum-initial-group-size": 3}},
)
connection.close()
PY
    """)

    writer.succeed(f"""
python3 - <<'PY'
import pika

queue = {queue!r}
payload = {payload!r}.encode()
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
channel.confirm_delivery()
channel.basic_publish(
    exchange="",
    routing_key=queue,
    body=payload,
    properties=pika.BasicProperties(delivery_mode=2),
    mandatory=True,
)
connection.close()
PY
    """)

    reader.succeed(f"""
python3 - <<'PY'
import pika
import sys
import time

queue = {queue!r}
expected = {payload!r}.encode()
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
for _ in range(20):
    method, properties, body = channel.basic_get(queue=queue, auto_ack=True)
    if method is not None:
        connection.close()
        if body != expected:
            print(f"unexpected payload: expected={{expected!r}} actual={{body!r}}")
            sys.exit(1)
        sys.exit(0)
    time.sleep(0.5)
connection.close()
print("message was not delivered before timeout")
sys.exit(1)
PY
    """)


    '';
    check = ''
_check("rabbitmq-quorum-roundtrip-r1-r2-r3", check_rabbitmq_quorum_roundtrip, rabbit1, rabbit2, rabbit3, "topotestix_roundtrip_123", "payload-from-rabbit2")
_check("rabbitmq-quorum-roundtrip-r2-r3-r1", check_rabbitmq_quorum_roundtrip, rabbit2, rabbit3, rabbit1, "topotestix_roundtrip_231", "payload-from-rabbit3")
_check("rabbitmq-quorum-roundtrip-r3-r1-r2", check_rabbitmq_quorum_roundtrip, rabbit3, rabbit1, rabbit2, "topotestix_roundtrip_312", "payload-from-rabbit1")
    '';
  };

  quorum_queue_roundtrip_non_durable = {
    name = "rabbitmq-quorum-queue-roundtrip-non-durable";
    setup = ''
def check_rabbitmq_quorum_roundtrip_non_durable(declarer, writer, reader, queue, payload):
    """Roundtrip with non-durable delivery mode and no publisher confirms."""
    declarer.succeed(f"""
python3 - <<'PY'
import pika

queue = {queue!r}
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
channel.queue_declare(
    queue=queue,
    durable=True,
    arguments={{"x-queue-type": "quorum", "x-quorum-initial-group-size": 3}},
)
connection.close()
PY
    """)

    writer.succeed(f"""
python3 - <<'PY'
import pika

queue = {queue!r}
payload = {payload!r}.encode()
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
# No confirm_delivery() — fire-and-forget publish
channel.basic_publish(
    exchange="",
    routing_key=queue,
    body=payload,
    properties=pika.BasicProperties(delivery_mode=1),
    mandatory=False,
)
connection.close()
PY
    """)

    reader.succeed(f"""
python3 - <<'PY'
import pika
import sys
import time

queue = {queue!r}
expected = {payload!r}.encode()
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
for _ in range(20):
    method, properties, body = channel.basic_get(queue=queue, auto_ack=True)
    if method is not None:
        connection.close()
        if body != expected:
            print(f"unexpected payload: expected={{expected!r}} actual={{body!r}}")
            sys.exit(1)
        sys.exit(0)
    time.sleep(0.5)
connection.close()
print("message was not delivered before timeout")
sys.exit(1)
PY
    """)
    '';
    check = ''
_check("rabbitmq-quorum-roundtrip-non-durable", check_rabbitmq_quorum_roundtrip_non_durable, rabbit1, rabbit2, rabbit3, "topotestix_roundtrip_nd", "payload-non-durable")
    '';
  };

  quorum_queue_roundtrip_multi = {
    name = "rabbitmq-quorum-queue-roundtrip-multi";
    setup = ''
def check_rabbitmq_quorum_roundtrip_multi(declarer, writer, reader, queue):
    """Roundtrip with multiple messages of varied sizes (durable + confirms)."""
    payloads = [
        "msg-1-small",
        "m" * 4096,
        "msg-3-medium",
        "L" * 8192,
        "msg-5-final",
    ]

    declarer.succeed(f"""
python3 - <<'PY'
import pika

queue = {queue!r}
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
channel.queue_declare(
    queue=queue,
    durable=True,
    arguments={{"x-queue-type": "quorum", "x-quorum-initial-group-size": 3}},
)
connection.close()
PY
    """)

    writer.succeed(f"""
python3 - <<'PY'
import pika

queue = {queue!r}
payloads = {payloads!r}
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
channel.confirm_delivery()
for i, p in enumerate(payloads):
    channel.basic_publish(
        exchange="",
        routing_key=queue,
        body=p.encode(),
        properties=pika.BasicProperties(
            delivery_mode=2,
            message_id=str(i),
        ),
        mandatory=True,
    )
connection.close()
PY
    """)

    reader.succeed(f"""
python3 - <<'PY'
import pika
import sys
import time

queue = {queue!r}
expected_payloads = {payloads!r}
expected = set(p.encode() for p in expected_payloads)
received = set()
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()

deadline = time.time() + 30
while len(received) < len(expected) and time.time() < deadline:
    method, properties, body = channel.basic_get(queue=queue, auto_ack=True)
    if method is not None:
        received.add(body)
    else:
        time.sleep(0.5)
connection.close()

missing = expected - received
extra = received - expected
if missing:
    print(f"missing messages: {{missing}}")
    sys.exit(1)
if extra:
    print(f"unexpected messages: {{extra}}")
    sys.exit(1)
print(f"all {{len(received)}} messages received correctly")
PY
    """)
    '';
    check = ''
_check("rabbitmq-quorum-roundtrip-multi", check_rabbitmq_quorum_roundtrip_multi, rabbit1, rabbit2, rabbit3, "topotestix_roundtrip_multi")
    '';
  };

  no_phantom_messages = {
    name = "rabbitmq-no-phantom-messages";
    setup = ''
def check_rabbitmq_no_phantom_messages(machine, queue):
    machine.succeed(f"""
python3 - <<'PY'
import pika
import sys

queue = {queue!r}
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
channel.queue_declare(
    queue=queue,
    durable=True,
    arguments={{"x-queue-type": "quorum", "x-quorum-initial-group-size": 3}},
)
method, properties, body = channel.basic_get(queue=queue, auto_ack=True)
connection.close()
if method is not None:
    print(f"phantom message observed: {{body!r}}")
    sys.exit(1)
PY
    """)
    '';
    check = ''
_check("rabbitmq-no-phantom-rabbit1", check_rabbitmq_no_phantom_messages, rabbit1, "topotestix_empty_rabbit1")
_check("rabbitmq-no-phantom-rabbit2", check_rabbitmq_no_phantom_messages, rabbit2, "topotestix_empty_rabbit2")
_check("rabbitmq-no-phantom-rabbit3", check_rabbitmq_no_phantom_messages, rabbit3, "topotestix_empty_rabbit3")
    '';
  };

  no_message_duplication = {
    name = "rabbitmq-no-message-duplication";
    setup = ''
def check_rabbitmq_no_message_duplication(declarer, writer, reader, queue, count):
    """Publish N distinct messages, consume all, verify no duplication or loss."""
    expected_payloads = [f"dedup-msg-{i:04d}" for i in range(count)]

    declarer.succeed(f"""
python3 - <<'PY'
import pika

queue = {queue!r}
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
channel.queue_declare(
    queue=queue,
    durable=True,
    arguments={{"x-queue-type": "quorum", "x-quorum-initial-group-size": 3}},
)
connection.close()
PY
    """)

    writer.succeed(f"""
python3 - <<'PY'
import pika

queue = {queue!r}
payloads = {expected_payloads!r}
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
channel.confirm_delivery()
for i, p in enumerate(payloads):
    channel.basic_publish(
        exchange="",
        routing_key=queue,
        body=p.encode(),
        properties=pika.BasicProperties(
            delivery_mode=2,
            message_id=str(i),
        ),
        mandatory=True,
    )
connection.close()
PY
    """)

    reader.succeed(f"""
python3 - <<'PY'
import pika
import sys
import time

queue = {queue!r}
expected_payloads = {expected_payloads!r}
expected = set(p.encode() for p in expected_payloads)
received = []
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()

deadline = time.time() + 30
while len(received) < len(expected) and time.time() < deadline:
    method, properties, body = channel.basic_get(queue=queue, auto_ack=True)
    if method is not None:
        received.append(body)
    else:
        time.sleep(0.5)
connection.close()

received_set = set(received)
missing = expected - received_set
extra = received_set - expected

if missing:
    print(f"missing messages: {{len(missing)}} of {{len(expected)}}")
    sys.exit(1)
if extra:
    print(f"unexpected (phantom) messages: {{len(extra)}}")
    sys.exit(1)

# Check no duplicates: each payload should appear exactly once
from collections import Counter
counts = Counter(received)
duplicated = {{k: v for k, v in counts.items() if v > 1}}
if duplicated:
    print(f"duplicated messages: {{duplicated}}")
    sys.exit(1)

print(f"all {{len(received)}} messages received exactly once")
PY
    """)
    '';
    check = ''
_check("rabbitmq-no-duplication", check_rabbitmq_no_message_duplication, rabbit1, rabbit2, rabbit3, "topotestix_dedup", 20)
    '';
  };

  service_still_up_after_delay = {
    name = "rabbitmq-still-up-after-delay";
    setup = ''
def check_rabbitmq_still_up(machine):
    machine.succeed("sleep 10 && systemctl is-active rabbitmq.service && su -s /bin/sh rabbitmq -c 'rabbitmq-diagnostics -q ping'")
    '';
    check = ''
_check("rabbitmq-still-up-rabbit1", check_rabbitmq_still_up, rabbit1)
_check("rabbitmq-still-up-rabbit2", check_rabbitmq_still_up, rabbit2)
_check("rabbitmq-still-up-rabbit3", check_rabbitmq_still_up, rabbit3)
    '';
  };
}
