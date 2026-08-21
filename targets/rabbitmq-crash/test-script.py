import time
import uuid

# json is provided by the runner preamble.

start_all()

NODES = {"rabbit1": rabbit1, "rabbit2": rabbit2, "rabbit3": rabbit3}
QUEUE = "topotestix_crash_durability"


def rabbitmqctl(machine, args):
    return machine.succeed(f"su -s /bin/sh rabbitmq -c 'rabbitmqctl {args}'")


def wait_for_rabbit(machine):
    machine.wait_for_unit("rabbitmq.service", timeout=120)
    machine.wait_for_open_port(5672, timeout=120)
    machine.wait_until_succeeds(
        "su -s /bin/sh rabbitmq -c 'rabbitmq-diagnostics -q ping'", timeout=120
    )


def queue_state():
    data = json.loads(
        rabbit1.succeed(
            f"curl -fsS -u guest:guest http://localhost:15672/api/queues/%2F/{QUEUE}"
        )
    )
    return {
        "name": data.get("name"),
        "type": data.get("type") or data.get("arguments", {}).get("x-queue-type"),
        "leader": data.get("leader"),
        "members": data.get("members", []),
        "online": data.get("online", []),
        "state": data.get("state"),
    }


def normalize_node(value):
    if not value:
        return None
    return str(value).split("@")[-1]


def service_state(machine):
    output = machine.succeed(
        "systemctl show rabbitmq.service --property=MainPID --property=Restart "
        "--property=KillMode --property=ActiveState --property=SubState"
    )
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def crash_service(machine):
    before = service_state(machine)
    if before.get("Restart") != "no":
        raise RuntimeError("rabbitmq.service must have Restart=no: " + str(before))
    machine.succeed("systemctl kill --signal=SIGKILL --kill-who=all rabbitmq.service")
    machine.wait_until_fails(
        "su -s /bin/sh rabbitmq -c 'rabbitmq-diagnostics -q ping'", timeout=30
    )
    machine.wait_until_succeeds(
        "test \"$(systemctl show rabbitmq.service -p MainPID --value)\" = 0", timeout=30
    )
    return before


def restart_service(machine, old_pid):
    machine.succeed("systemctl reset-failed rabbitmq.service")
    machine.succeed("systemctl start rabbitmq.service")
    wait_for_rabbit(machine)
    after = service_state(machine)
    if after.get("MainPID") in {None, "0", old_pid}:
        raise RuntimeError("RabbitMQ did not restart with a new process: " + str(after))
    return after


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

crash_timing = rabbit1.succeed("cat /etc/topotestix-crash-timing").strip()
target_role = rabbit1.succeed("cat /etc/topotestix-crash-target-role").strip()
restart_delay = int(rabbit1.succeed("cat /etc/topotestix-crash-delay"))
publish_count = int(rabbit1.succeed("cat /etc/topotestix-crash-publish-count"))
run_id = uuid.uuid4().hex

state_before = queue_state()
leader = normalize_node(state_before.get("leader"))
if leader not in NODES:
    raise RuntimeError("could not determine quorum queue leader: " + str(state_before))
members = {normalize_node(member) for member in state_before.get("members", [])}
if members and members != set(NODES):
    raise RuntimeError("unexpected quorum queue members: " + str(state_before))

if target_role == "leader":
    target_name = leader
else:
    target_name = next(name for name in sorted(NODES) if name != leader)
target = NODES[target_name]
client_name = next(name for name in sorted(NODES) if name != target_name)
client = NODES[client_name]

publisher = f"""
import json, os, pika, time
run_id = {run_id!r}
queue = {QUEUE!r}
count = {publish_count}
path = "/tmp/crash-publisher.json"
operations = []

def save(done=False):
    temporary = path + ".tmp"
    with open(temporary, "w") as handle:
        json.dump({{"done": done, "operations": operations}}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)

save()
for sequence in range(count):
    op_id = f"{{run_id}}/publish/{{sequence:08d}}"
    record = {{"op_id": op_id, "sequence": sequence, "outcome": None,
              "attempt_wall_ns": time.time_ns(), "exception_type": None,
              "exception_message": None}}
    invoked = False
    connection = None
    try:
        connection = pika.BlockingConnection(pika.ConnectionParameters(
            "localhost", socket_timeout=3, blocked_connection_timeout=3))
        channel = connection.channel()
        channel.confirm_delivery()
        invoked = True
        channel.basic_publish(
            exchange="", routing_key=queue, body=op_id.encode(), mandatory=True,
            properties=pika.BasicProperties(delivery_mode=2, message_id=op_id))
        record["outcome"] = "confirmed"
    except (pika.exceptions.NackError, pika.exceptions.UnroutableError) as exc:
        record["outcome"] = "rejected"
        record["exception_type"] = type(exc).__name__
        record["exception_message"] = str(exc)
    except Exception as exc:
        record["outcome"] = "ambiguous" if invoked else "timed_out"
        record["exception_type"] = type(exc).__name__
        record["exception_message"] = str(exc)
    finally:
        try:
            connection.close()
        except Exception:
            pass
    record["finish_wall_ns"] = time.time_ns()
    operations.append(record)
    save()
    time.sleep(0.15)
save(done=True)
"""
client.succeed("cat > /tmp/crash-publisher.py <<'PY'\n" + publisher + "\nPY")


def start_publisher():
    client.succeed(
        "rm -f /tmp/crash-publisher.json /tmp/crash-publisher.log; "
        "nohup python3 /tmp/crash-publisher.py >/tmp/crash-publisher.log 2>&1 &"
    )


def wait_for_operations(minimum):
    client.wait_until_succeeds(
        "test $(python3 -c \"import json; print(len(json.load(open('/tmp/crash-publisher.json'))['operations']))\") "
        f"-ge {minimum}",
        timeout=120,
    )


def wait_for_publisher():
    client.wait_until_succeeds(
        "python3 -c \"import json,sys; sys.exit(0 if json.load(open('/tmp/crash-publisher.json'))['done'] else 1)\"",
        timeout=180,
    )


if crash_timing == "before_publish":
    service_before = crash_service(target)
    time.sleep(restart_delay)
    service_after = restart_service(target, service_before["MainPID"])
    start_publisher()
    wait_for_publisher()
elif crash_timing == "during_publish":
    start_publisher()
    wait_for_operations(min(5, publish_count))
    service_before = crash_service(target)
    time.sleep(restart_delay)
    service_after = restart_service(target, service_before["MainPID"])
    wait_for_publisher()
elif crash_timing == "after_publish":
    start_publisher()
    wait_for_publisher()
    service_before = crash_service(target)
    time.sleep(restart_delay)
    service_after = restart_service(target, service_before["MainPID"])
else:
    raise RuntimeError("unknown crash timing: " + crash_timing)

publisher_results = json.loads(client.succeed("cat /tmp/crash-publisher.json"))

for machine in NODES.values():
    wait_for_rabbit(machine)
deadline = time.time() + 120
state_after = queue_state()
while time.time() < deadline:
    online = {normalize_node(node) for node in state_after.get("online", [])}
    if online == set(NODES):
        break
    time.sleep(3)
    state_after = queue_state()

drain_out = rabbit1.succeed(
    f"""
python3 - <<'PY'
import json, pika, time
c = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
ch = c.channel()
recovered = []
empty_since = None
while True:
    method, props, body = ch.basic_get({QUEUE!r}, auto_ack=False)
    if method is None:
        if empty_since is None:
            empty_since = time.monotonic()
        if time.monotonic() - empty_since >= 2:
            break
        time.sleep(0.2)
        continue
    empty_since = None
    recovered.append({{"message_id": props.message_id, "body_id": body.decode(),
                       "redelivered": bool(method.redelivered)}})
    ch.basic_ack(method.delivery_tag)
c.close()
print(json.dumps(recovered))
PY
"""
)

results = {
    "schema_version": 1,
    "run_id": run_id,
    "crash_timing": crash_timing,
    "target_role": target_role,
    "target_node": target_name,
    "client_node": client_name,
    "restart_delay": restart_delay,
    "queue_before": state_before,
    "queue_after": state_after,
    "service_before": service_before,
    "service_after": service_after,
    "operations": publisher_results["operations"],
    "recovered": json.loads(drain_out.strip().splitlines()[-1]),
}
rabbit1.succeed(
    "cat > /tmp/crash-results.json <<'EOF'\n" + json.dumps(results, indent=2) + "\nEOF"
)
rabbit1.copy_from_machine("/tmp/crash-results.json")
