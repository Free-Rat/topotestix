import re
import time

# `json` is already imported by the harness preamble; do not reimport it.

start_all()


def rabbitmqctl(machine, args):
    machine.succeed(f"su -s /bin/sh rabbitmq -c 'rabbitmqctl {args}'")


def wait_for_rabbit(machine):
    machine.wait_for_unit("rabbitmq.service")
    machine.wait_for_open_port(5672)
    machine.wait_for_open_port(15672)
    machine.wait_until_succeeds("su -s /bin/sh rabbitmq -c 'rabbitmq-diagnostics -q ping'")
    machine.wait_until_succeeds("curl -fsS -u guest:guest http://localhost:15672/api/overview >/dev/null")


for machine in [rabbit1, rabbit2, rabbit3]:
    wait_for_rabbit(machine)

# Form a 3-node RabbitMQ cluster. rabbit1 is the seed; rabbit2 and
# rabbit3 join it via the same Erlang cookie.
for machine in [rabbit2, rabbit3]:
    rabbitmqctl(machine, "stop_app")
    rabbitmqctl(machine, "reset")
    rabbitmqctl(machine, "join_cluster rabbit@rabbit1")
    rabbitmqctl(machine, "start_app")

# Wait until every node sees the full cluster.
for machine in [rabbit1, rabbit2, rabbit3]:
    machine.wait_until_succeeds(
        "su -s /bin/sh rabbitmq -c 'rabbitmqctl cluster_status' > /tmp/rabbitmq-cluster-status && "
        "grep -q 'rabbit@rabbit1' /tmp/rabbitmq-cluster-status && "
        "grep -q 'rabbit@rabbit2' /tmp/rabbitmq-cluster-status && "
        "grep -q 'rabbit@rabbit3' /tmp/rabbitmq-cluster-status",
        timeout=60,
    )

# Declare a 3-replica quorum queue on every node. queue_declare is
# idempotent so it is safe to call from each node, and it ensures the
# queue exists on all replicas before any publishing starts.
for machine in [rabbit1, rabbit2, rabbit3]:
    machine.succeed(
        """
python3 - <<'PY'
import pika

connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
channel.queue_declare(
    queue="topotestix_memory",
    durable=True,
    arguments={"x-queue-type": "quorum", "x-quorum-initial-group-size": 3},
)
connection.close()
PY
        """
    )

# Read the fuzzed publish-load parameters (memory size and broker
# watermark were applied at NixOS evaluation time and are already
# active in the broker).
publish_count = int(rabbit1.succeed("cat /etc/topotestix-memory-publish-count").strip())
message_size = int(rabbit1.succeed("cat /etc/topotestix-memory-message-size").strip())

# Capture the configured watermark and host memory for the report.
watermark_line = rabbit1.succeed(
    "su -s /bin/sh rabbitmq -c 'rabbitmqctl environment' | grep -E 'vm_memory_high_watermark'"
).strip()
free_line = rabbit1.succeed("free -m | head -2").strip()


def check_memory_high_watermark(machine):
    """Return 'failed' (alarm active) or 'passed' (no alarm) on this node.

    Newer rabbitmq-diagnostics removed `check_memory_high_watermark`.
    `check_local_alarms` exits non-zero when any resource alarm
    (memory, disk) is firing on the local node, which is the
    replacement signal.
    """
    out = machine.execute(
        "su -s /bin/sh rabbitmq -c 'rabbitmq-diagnostics -q check_local_alarms'",
        check_return=False,
    )[1].strip()
    # check_local_alarms exits 0 = no alarms, non-zero = at least one alarm.
    # Empty output usually means success (no alarms).
    if not out:
        return "passed"
    return "failed"


# Initial memory alarm state, before any publishing.
alarm_initial = check_memory_high_watermark(rabbit1)

# Phase 1: publish N durable, confirmed messages. We capture the
# per-message outcome so the properties can assert the flow-control
# behavior without re-running the writes.
PUBLISH_TEMPLATE = """
python3 - <<'PY'
import pika
import sys

QUEUE = "topotestix_memory"
MSG_INDEX = MSG_INDEX_PLACEHOLDER
PAYLOAD_SIZE = MESSAGE_SIZE_PLACEHOLDER

payload = ("msg-{:06d}-".format(MSG_INDEX) + "X" * max(0, PAYLOAD_SIZE - 12)).encode()

try:
    connection = pika.BlockingConnection(
        pika.ConnectionParameters("localhost", socket_timeout=10),
    )
    channel = connection.channel()
    channel.confirm_delivery()
    try:
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE,
            body=payload,
            properties=pika.BasicProperties(delivery_mode=2, message_id=str(MSG_INDEX)),
            mandatory=True,
        )
        print("PUBLISH_OK")
    except pika.exceptions.UnroutableError:
        print("PUBLISH_UNROUTABLE")
    except pika.exceptions.NackError:
        print("PUBLISH_NACKED")
    except pika.exceptions.AMQPError as e:
        print("PUBLISH_AMQP_ERROR: " + type(e).__name__ + ": " + str(e))
    except Exception as e:
        print("PUBLISH_ERROR: " + type(e).__name__ + ": " + str(e))
    connection.close()
except Exception as e:
    print("PUBLISH_CONNECT_ERROR: " + type(e).__name__ + ": " + str(e))
PY
"""

publish_summary = {"ok": 0, "unroutable": 0, "nacked": 0, "amqp_error": 0, "other_error": 0}
for i in range(publish_count):
    script = (
        PUBLISH_TEMPLATE
        .replace("MSG_INDEX_PLACEHOLDER", str(i))
        .replace("MESSAGE_SIZE_PLACEHOLDER", str(message_size))
    )
    _, out = rabbit1.execute(script, timeout=30)
    line = out.strip()
    if "PUBLISH_OK" in line:
        publish_summary["ok"] += 1
    elif "PUBLISH_UNROUTABLE" in line:
        publish_summary["unroutable"] += 1
    elif "PUBLISH_NACKED" in line:
        publish_summary["nacked"] += 1
    elif "PUBLISH_AMQP_ERROR" in line:
        publish_summary["amqp_error"] += 1
    else:
        publish_summary["other_error"] += 1

# Memory alarm state immediately after the publish phase.
alarm_after_publish = check_memory_high_watermark(rabbit1)

# Phase 2: wait for the broker to drain and recover. 30s is enough
# for flow-control-released publishes to drain and for the broker to
# release memory back to the OS.
time.sleep(30)

alarm_after_drain = check_memory_high_watermark(rabbit1)

# Phase 3: drain the queue and count the durable messages that
# RabbitMQ actually retained. auto_ack=True means we consume the
# messages; the total is the durable messages that survived.
count_out = rabbit1.succeed(
    """
python3 - <<'PY'
import pika
import time

queue = "topotestix_memory"
total = 0
ids = []
connection = pika.BlockingConnection(
    pika.ConnectionParameters("localhost", socket_timeout=10),
)
channel = connection.channel()
deadline = time.time() + 30
last_count = -1
stable_iters = 0
while time.time() < deadline:
    method, properties, body = channel.basic_get(queue=queue, auto_ack=True)
    if method is None:
        if last_count == total and stable_iters >= 2:
            break
        last_count = total
        stable_iters += 1
        time.sleep(1)
        continue
    stable_iters = 0
    total += 1
    if properties and properties.message_id is not None:
        ids.append(properties.message_id)
connection.close()
print("TOTAL=" + str(total))
print("IDS_FIRST=" + str(ids[:5]))
print("IDS_LAST=" + str(ids[-5:] if len(ids) > 5 else ids))
PY
    """
)

m = re.search(r"TOTAL=\s*(\d+)", count_out)
final_count = int(m.group(1)) if m else -1

# Persist the publish/drain results for the property checks.
results = {
    "publish_count": publish_count,
    "message_size": message_size,
    "watermark_line": watermark_line,
    "free_line": free_line,
    "publish_summary": publish_summary,
    "alarm_initial": alarm_initial,
    "alarm_after_publish": alarm_after_publish,
    "alarm_after_drain": alarm_after_drain,
    "final_count": final_count,
}
rabbit1.succeed(
    "cat > /tmp/mempressure-results.json << 'EOF'\n"
    + json.dumps(results, indent=2)
    + "\nEOF\n"
)
