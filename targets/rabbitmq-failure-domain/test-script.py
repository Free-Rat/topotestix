import time
import uuid

# json is provided by the runner preamble.

start_all()

NODES = {"rabbit1": rabbit1, "rabbit2": rabbit2, "rabbit3": rabbit3}
QUEUE = "topotestix_failure_domain"


def rabbitmqctl(machine, args):
    return machine.succeed(f"su -s /bin/sh rabbitmq -c 'rabbitmqctl {args}'")


def wait_for_rabbit(machine):
    machine.wait_for_unit("rabbitmq.service", timeout=120)
    machine.wait_for_open_port(5672, timeout=120)
    machine.wait_until_succeeds(
        "su -s /bin/sh rabbitmq -c 'rabbitmq-diagnostics -q ping'", timeout=120
    )


for machine in NODES.values():
    wait_for_rabbit(machine)

for machine in [rabbit2, rabbit3]:
    rabbitmqctl(machine, "stop_app")
    rabbitmqctl(machine, "reset")
    rabbitmqctl(machine, "join_cluster rabbit@rabbit1")
    rabbitmqctl(machine, "start_app")

rabbit1.succeed(
    f"""
python3 - <<'PY'
import pika
c = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
ch = c.channel()
ch.queue_declare(queue={QUEUE!r}, durable=True,
                 arguments={{"x-queue-type": "quorum", "x-quorum-initial-group-size": 3}})
c.close()
PY
"""
)
time.sleep(5)

placement = json.loads(
    rabbit1.succeed("cat /etc/topotestix-failure-domain-placement.json")
)
failed_domain = rabbit1.succeed("cat /etc/topotestix-failed-domain").strip()
confirm_timeout_ms = int(
    rabbit1.succeed("cat /etc/topotestix-domain-confirm-timeout-ms")
)
failed_nodes = sorted(name for name, domain in placement.items() if domain == failed_domain)
surviving_nodes = sorted(set(NODES) - set(failed_nodes))
if not failed_nodes or not surviving_nodes:
    raise RuntimeError("placement must leave at least one failed and one surviving node")

run_id = uuid.uuid4().hex
baseline_ids = [f"{run_id}/baseline/{index:04d}" for index in range(10)]
baseline_script = f"""
python3 - <<'PY'
import pika
ids = {baseline_ids!r}
c = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
ch = c.channel()
ch.confirm_delivery()
for op_id in ids:
    ch.basic_publish(exchange="", routing_key={QUEUE!r}, body=op_id.encode(),
                     mandatory=True, properties=pika.BasicProperties(
                         delivery_mode=2, message_id=op_id))
c.close()
PY
"""
rabbit1.succeed(baseline_script)

service_pids = {}
for name in failed_nodes:
    machine = NODES[name]
    service_pids[name] = machine.succeed(
        "systemctl show rabbitmq.service -p MainPID --value"
    ).strip()
    machine.succeed("systemctl kill --signal=SIGKILL --kill-who=all rabbitmq.service")
    machine.wait_until_fails(
        "su -s /bin/sh rabbitmq -c 'rabbitmq-diagnostics -q ping'", timeout=30
    )

time.sleep(5)
probe_id = f"{run_id}/domain-probe"
probe_node = surviving_nodes[0]
probe_script = f"""
python3 - <<'PY'
import json, pika, time
op_id = {probe_id!r}
invoked = False
record = {{"op_id": op_id, "outcome": None, "exception_type": None,
          "exception_message": None, "attempt_wall_ns": time.time_ns()}}
try:
    c = pika.BlockingConnection(pika.ConnectionParameters(
        "localhost", socket_timeout={confirm_timeout_ms / 1000},
        blocked_connection_timeout={confirm_timeout_ms / 1000}))
    ch = c.channel()
    ch.confirm_delivery()
    invoked = True
    ch.basic_publish(exchange="", routing_key={QUEUE!r}, body=op_id.encode(),
        mandatory=True, properties=pika.BasicProperties(delivery_mode=2, message_id=op_id))
    record["outcome"] = "confirmed"
except (pika.exceptions.NackError, pika.exceptions.UnroutableError) as exc:
    record["outcome"] = "rejected"
    record["exception_type"] = type(exc).__name__
    record["exception_message"] = str(exc)
except Exception as exc:
    record["outcome"] = "ambiguous" if invoked else "timed_out"
    record["exception_type"] = type(exc).__name__
    record["exception_message"] = str(exc)
record["finish_wall_ns"] = time.time_ns()
print(json.dumps(record))
PY
"""
status, output = NODES[probe_node].execute(probe_script, timeout=confirm_timeout_ms / 1000 + 15)
if status == 124:
    probe = {
        "op_id": probe_id,
        "outcome": "ambiguous",
        "exception_type": "OuterCommandTimeout",
        "exception_message": "publish did not complete within the test-driver budget",
    }
elif status != 0:
    raise RuntimeError(f"domain probe harness failed with status {status}: {output}")
else:
    probe = json.loads(output.strip().splitlines()[-1])

for name in failed_nodes:
    machine = NODES[name]
    machine.succeed("systemctl reset-failed rabbitmq.service")
    machine.succeed("systemctl start rabbitmq.service")
    wait_for_rabbit(machine)
time.sleep(10)

drain = rabbit1.succeed(
    f"""
python3 - <<'PY'
import json, pika, time
c = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
ch = c.channel()
items = []
empty_since = None
while True:
    method, props, body = ch.basic_get({QUEUE!r}, auto_ack=False)
    if method is None:
        if empty_since is None:
            empty_since = time.monotonic()
        if time.monotonic() - empty_since > 2:
            break
        time.sleep(.2)
        continue
    empty_since = None
    items.append({{"message_id": props.message_id, "body_id": body.decode()}})
    ch.basic_ack(method.delivery_tag)
c.close()
print(json.dumps(items))
PY
"""
)

results = {
    "schema_version": 1,
    "run_id": run_id,
    "placement": placement,
    "failed_domain": failed_domain,
    "failed_nodes": failed_nodes,
    "surviving_nodes": surviving_nodes,
    "expected_available": len(surviving_nodes) >= 2,
    "baseline_ids": baseline_ids,
    "probe": probe,
    "recovered": json.loads(drain.strip().splitlines()[-1]),
    "service_pids_before": service_pids,
}
rabbit1.succeed(
    "cat > /tmp/failure-domain-results.json <<'EOF'\n"
    + json.dumps(results, indent=2) + "\nEOF"
)
rabbit1.copy_from_machine("/tmp/failure-domain-results.json")
