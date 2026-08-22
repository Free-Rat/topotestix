import time
import uuid

# json is provided by the runner preamble.

start_all()

NODES = {"rabbit1": rabbit1, "rabbit2": rabbit2, "rabbit3": rabbit3}
QUEUE = "topotestix_disk_capacity"
EXPECTED_MEMBERS = {"rabbit@rabbit1", "rabbit@rabbit2", "rabbit@rabbit3"}


def rabbitmqctl(machine, args):
    return machine.succeed(f"su -s /bin/sh rabbitmq -c 'rabbitmqctl {args}'")


def wait_for_rabbit(machine):
    machine.wait_for_unit("rabbitmq.service")
    machine.wait_for_open_port(5672)
    machine.wait_for_open_port(15672)
    machine.wait_until_succeeds(
        "su -s /bin/sh rabbitmq -c 'rabbitmq-diagnostics -q ping'", timeout=90
    )


def node_sample(name, machine, phase):
    fs = json.loads(
        machine.succeed(
            "python3 - <<'PY'\n"
            "import json, os\n"
            "s = os.statvfs('/var/lib/rabbitmq')\n"
            "print(json.dumps({'total': s.f_blocks*s.f_frsize, "
            "'free': s.f_bfree*s.f_frsize, 'available': s.f_bavail*s.f_frsize}))\n"
            "PY"
        )
    )
    raw = machine.succeed(
        f"curl -fsS -u guest:guest http://localhost:15672/api/nodes/rabbit@{name}"
    )
    broker = json.loads(raw)
    return {
        "wall_ns": time.time_ns(),
        "phase": phase,
        "node": name,
        "fs_total_bytes": fs["total"],
        "fs_free_bytes": fs["free"],
        "fs_available_bytes": fs["available"],
        "rabbit_disk_free_bytes": broker.get("disk_free"),
        "rabbit_disk_free_limit_bytes": broker.get("disk_free_limit"),
        "disk_free_alarm": bool(broker.get("disk_free_alarm", False)),
    }


def sample_all(phase):
    return [node_sample(name, machine, phase) for name, machine in NODES.items()]


def queue_state():
    raw = rabbit1.succeed(
        f"curl -fsS -u guest:guest http://localhost:15672/api/queues/%2F/{QUEUE}"
    )
    data = json.loads(raw)
    return {
        "name": data.get("name"),
        "type": data.get("type") or data.get("arguments", {}).get("x-queue-type"),
        "leader": data.get("leader"),
        "members": data.get("members", []),
        "online": data.get("online", []),
        "state": data.get("state"),
    }


for machine in NODES.values():
    wait_for_rabbit(machine)

for machine in [rabbit2, rabbit3]:
    rabbitmqctl(machine, "stop_app")
    rabbitmqctl(machine, "reset")
    rabbitmqctl(machine, "join_cluster rabbit@rabbit1")
    rabbitmqctl(machine, "start_app")

for machine in NODES.values():
    machine.wait_until_succeeds(
        "su -s /bin/sh rabbitmq -c 'rabbitmqctl cluster_status' > /tmp/cluster-status && "
        "grep -q 'rabbit@rabbit1' /tmp/cluster-status && "
        "grep -q 'rabbit@rabbit2' /tmp/cluster-status && "
        "grep -q 'rabbit@rabbit3' /tmp/cluster-status",
        timeout=90,
    )

rabbit1.succeed(
    f"""
python3 - <<'PY'
import pika
c = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
ch = c.channel()
ch.queue_declare(queue="{QUEUE}", durable=True,
                 arguments={{"x-queue-type": "quorum", "x-quorum-initial-group-size": 3}})
c.close()
PY
"""
)
time.sleep(5)

initial_free_target_mb = int(rabbit1.succeed("cat /etc/topotestix-disk-initial-free-mb"))
backlog_rate = int(rabbit1.succeed("cat /etc/topotestix-disk-backlog-rate"))
outage_seconds = int(rabbit1.succeed("cat /etc/topotestix-disk-consumer-outage-seconds"))
message_size = int(rabbit1.succeed("cat /etc/topotestix-disk-message-size"))
confirm_timeout_ms = int(rabbit1.succeed("cat /etc/topotestix-disk-confirm-timeout-ms"))
safety_factor_milli = int(
    rabbit1.succeed("cat /etc/topotestix-disk-capacity-safety-factor-milli")
)
planned_messages = backlog_rate * outage_seconds
run_id = uuid.uuid4().hex
telemetry = sample_all("before_fill")

for machine in NODES.values():
    free_mb = int(machine.succeed("df -BM --output=avail /var/lib/rabbitmq | tail -1").strip()[:-1])
    fill_mb = max(0, free_mb - initial_free_target_mb)
    if fill_mb:
        machine.succeed(f"fallocate -l {fill_mb}M /var/lib/rabbitmq/topotestix-fill")

time.sleep(5)
telemetry.extend(sample_all("after_fill"))

publish_script = f"""
python3 - <<'PY'
import json, pika, time
run_id = {run_id!r}
queue = {QUEUE!r}
count = {planned_messages}
message_size = {message_size}
timeout = {confirm_timeout_ms} / 1000.0
operations = []
connection = None
for sequence in range(count):
    op_id = f"{{run_id}}/backlog/{{sequence:08d}}"
    record = {{"op_id": op_id, "sequence": sequence, "attempt_wall_ns": time.time_ns(),
              "outcome": None, "exception_type": None, "exception_message": None}}
    invoked = False
    started = time.monotonic()
    try:
        if connection is None or connection.is_closed:
            connection = pika.BlockingConnection(pika.ConnectionParameters(
                "localhost", socket_timeout=timeout, blocked_connection_timeout=timeout))
            channel = connection.channel()
            channel.confirm_delivery()
        body = op_id.encode() + b":" + b"x" * max(0, message_size - len(op_id) - 1)
        invoked = True
        channel.basic_publish(
            exchange="", routing_key=queue, body=body, mandatory=True,
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
        try:
            connection.close()
        except Exception:
            pass
        connection = None
    record["finish_wall_ns"] = time.time_ns()
    record["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
    operations.append(record)
print(json.dumps(operations))
PY
"""
publish_status, publish_out = rabbit1.execute(
    publish_script, timeout=max(60, planned_messages * (confirm_timeout_ms / 1000 + 1))
)
if publish_status != 0:
    raise RuntimeError(f"publisher process failed with status {publish_status}: {publish_out}")
operations = json.loads(publish_out.strip().splitlines()[-1])
telemetry.extend(sample_all("after_publish"))

for machine in NODES.values():
    machine.succeed("rm -f /var/lib/rabbitmq/topotestix-fill")

deadline = time.time() + 90
while time.time() < deadline:
    current = sample_all("recovery_poll")
    telemetry.extend(current)
    if not any(sample["disk_free_alarm"] for sample in current):
        break
    time.sleep(3)

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
    body_id = body.split(b":", 1)[0].decode()
    recovered.append({{"message_id": props.message_id, "body_id": body_id,
                       "redelivered": bool(method.redelivered)}})
    ch.basic_ack(method.delivery_tag)
c.close()
print(json.dumps(recovered))
PY
"""
)
recovered = json.loads(drain_out.strip().splitlines()[-1])
telemetry.extend(sample_all("after_recovery"))

after_fill = [sample for sample in telemetry if sample["phase"] == "after_fill"]
limit_bytes = after_fill[0]["rabbit_disk_free_limit_bytes"]
if not isinstance(limit_bytes, int) or limit_bytes <= 0:
    raise RuntimeError("management API did not report a valid disk_free_limit")
limit_mb = limit_bytes // (1024 * 1024)
planned_payload_bytes = planned_messages * message_size
required_free_bytes = limit_bytes + (
    planned_payload_bytes * safety_factor_milli // 1000
)
# Naive planning model: budgets only the payload backlog and ignores the
# alarm margin. Strictly weaker (required_free_bytes >= naive, since limit >
# 0); exposed so the capacity contract can also fire on configurations where
# a naive capacity planner is "sufficient" but the disk_free alarm still
# breaks the confirmation SLO.
naive_required_free_bytes = planned_payload_bytes * safety_factor_milli // 1000

results = {
    "schema_version": 1,
    "run_id": run_id,
    "contract": {
        "volume_placement": "independent-vm-root-volumes",
        "initial_free_target_mb": initial_free_target_mb,
        "disk_free_limit_mb": limit_mb,
        "backlog_rate": backlog_rate,
        "consumer_outage_seconds": outage_seconds,
        "planned_messages": planned_messages,
        "message_size": message_size,
        "confirm_timeout_ms": confirm_timeout_ms,
        "capacity_safety_factor_milli": safety_factor_milli,
        "required_free_bytes": required_free_bytes,
        "naive_required_free_bytes": naive_required_free_bytes,
        "capacity_sufficient": all(
            sample["fs_available_bytes"] >= required_free_bytes for sample in after_fill
        ),
        "naive_capacity_sufficient": all(
            sample["fs_available_bytes"] >= naive_required_free_bytes
            for sample in after_fill
        ),
    },
    "operations": operations,
    "telemetry": telemetry,
    "recovered": recovered,
    "queue_before": queue_state(),
}

rabbit1.succeed(
    "cat > /tmp/disk-results.json <<'EOF'\n" + json.dumps(results, indent=2) + "\nEOF"
)
rabbit1.copy_from_machine("/tmp/disk-results.json")
