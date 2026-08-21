import re
import time

# `json` is already imported by the harness preamble; do not reimport it.

# Each mode maps every cluster peer name to the broker it resolves to (its own
# broker = valid; the wrong broker = the broken/ambiguous modes). The value is
# the TARGET node whose IP the name maps to. See config.nix for the rationale.
MODE_TO_MAPPING = {
    "valid": {"rabbit1": "rabbit1", "rabbit2": "rabbit2", "rabbit3": "rabbit3"},
    "missing-seed": {"rabbit2": "rabbit2", "rabbit3": "rabbit3"},
    "ambiguous-seed": {"rabbit1": "rabbit3", "rabbit2": "rabbit2", "rabbit3": "rabbit3"},
    "all-to-same": {"rabbit1": "rabbit3", "rabbit2": "rabbit3", "rabbit3": "rabbit3"},
}

start_all()


def rabbitmqctl(machine, args):
    machine.succeed(f"su -s /bin/sh rabbitmq -c 'rabbitmqctl {args}'")


def rabbitmqctl_rc(machine, args):
    """Run a rabbitmqctl command and return (rc, out) without raising."""
    return machine.execute(f"su -s /bin/sh rabbitmq -c 'rabbitmqctl {args}'")


def wait_for_rabbit(machine):
    machine.wait_for_unit("rabbitmq.service")
    machine.wait_for_open_port(5672)
    machine.wait_for_open_port(15672)
    machine.wait_until_succeeds("su -s /bin/sh rabbitmq -c 'rabbitmq-diagnostics -q ping'")
    machine.wait_until_succeeds(
        "curl -fsS -u guest:guest http://localhost:15672/api/overview >/dev/null"
    )


def wait_for_cluster_full(machines, timeout=120):
    for machine in machines:
        machine.wait_until_succeeds(
            "su -s /bin/sh rabbitmq -c 'rabbitmqctl cluster_status' > /tmp/rabbitmq-cluster-status && "
            "grep -q 'rabbit@rabbit1' /tmp/rabbitmq-cluster-status && "
            "grep -q 'rabbit@rabbit2' /tmp/rabbitmq-cluster-status && "
            "grep -q 'rabbit@rabbit3' /tmp/rabbitmq-cluster-status",
            timeout=timeout,
        )


def member_names(machine):
    """Return the distinct rabbit@rabbitN node names in this node's cluster."""
    _, out = machine.execute(
        "su -s /bin/sh rabbitmq -c 'rabbitmqctl cluster_status 2>/dev/null' "
        "| grep -oE 'rabbit@rabbit[123]' | sort -u"
    )
    return sorted(set(out.split()))


for machine in [rabbit1, rabbit2, rabbit3]:
    wait_for_rabbit(machine)

# Read the fuzzed DNS parameters.
mode = rabbit1.succeed(
    "grep -oE 'topotestix-dns-mode=[a-z-]+' /etc/hosts | cut -d= -f2"
).strip()
publish_count = int(rabbit1.succeed("cat /etc/topotestix-dns-publish-count").strip())
expected_full = mode == "valid"
mapping = MODE_TO_MAPPING[mode]

# Attempt to form the cluster the way a node would at startup: rabbit2 and
# rabbit3 join the seed name rabbit@rabbit1. Bounded so a broken-resolution
# mode fails cleanly instead of hanging the harness. rabbit1 is the seed and
# is never joined (it must remain reachable as the report node).
join_ok = {}
for member in [rabbit2, rabbit3]:
    rabbitmqctl(member, "stop_app")
    rabbitmqctl(member, "reset")
    rc, _ = member.execute(
        "timeout 45 su -s /bin/sh rabbitmq -c 'rabbitmqctl join_cluster rabbit@rabbit1'"
    )
    joined = rc == 0
    join_ok["rabbit2" if member is rabbit2 else "rabbit3"] = joined
    # Bring the application up regardless: a member that joined, or a healthy
    # singleton whose join legitimately failed under a broken-resolver mode.
    rabbitmqctl(member, "start_app")
    time.sleep(3)

# In the expected-healthy (valid) state, wait for full membership to settle;
# in broken modes there is no shared cluster to wait for, so skip the wait and
# let the member-reading below capture the split/singleton reality.
if expected_full and all(join_ok.values()):
    time.sleep(10)
    try:
        wait_for_cluster_full([rabbit1, rabbit2, rabbit3], timeout=60)
    except Exception:
        pass  # formation did not converge; captured below

# Declare a 3-replica quorum queue on the report node. In a healthy cluster
# this is a quorum group; in a broken-resolution state it degrades to whatever
# members are present, which still lets us exercise per-node durable storage.
rabbit1.succeed(
    """
python3 - <<'PY'
import pika
c = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
ch = c.channel()
try:
    ch.queue_declare(
        queue="topotestix_dns",
        durable=True,
        arguments={"x-queue-type": "quorum", "x-quorum-initial-group-size": 3},
    )
except Exception:
    ch.queue_declare(queue="topotestix_dns", durable=True)
c.close()
PY
    """
)

MESSAGE_SIZE = 2048


def publish_batch(count):
    """Publish `count` durable confirmed messages to rabbit1. Return tally."""
    script = f"""
python3 - <<'PY'
import pika, sys
QUEUE = "topotestix_dns"
SIZE = {MESSAGE_SIZE}
COUNT = {count}
ok = unroutable = nacked = amqp_err = other = 0
try:
    c = pika.BlockingConnection(pika.ConnectionParameters("localhost", socket_timeout=10))
    ch = c.channel()
    ch.confirm_delivery()
    for i in range(COUNT):
        body = ("dns-{{:06d}}-".format(i) + "X" * max(0, SIZE - 8)).encode()
        try:
            ch.basic_publish(
                exchange="", routing_key=QUEUE, body=body,
                properties=pika.BasicProperties(delivery_mode=2, message_id=str(i)),
                mandatory=True,
            )
            ok += 1
        except pika.exceptions.UnroutableError:
            unroutable += 1
        except pika.exceptions.NackError:
            nacked += 1
        except pika.exceptions.AMQPError:
            amqp_err += 1
        except Exception:
            other += 1
    c.close()
except Exception:
    other = COUNT
print("OK=" + str(ok)); print("UNROUTABLE=" + str(unroutable))
print("NACKED=" + str(nacked)); print("AMQP=" + str(amqp_err))
print("OTHER=" + str(other))
PY
    """
    _, out = rabbit1.execute(script, timeout=180)
    tally = {}
    for key, line_prefix in [
        ("ok", "OK="), ("unroutable", "UNROUTABLE="), ("nacked", "NACKED="),
        ("amqp_error", "AMQP="), ("other", "OTHER="),
    ]:
        m = re.search(re.escape(line_prefix) + r"(\d+)", out)
        tally[key] = int(m.group(1)) if m else 0
    return tally


def drain_queue():
    out = rabbit1.succeed(
        """
python3 - <<'PY'
import pika, time
q = "topotestix_dns"; total = 0
c = pika.BlockingConnection(pika.ConnectionParameters("localhost", socket_timeout=10))
ch = c.channel()
deadline = time.time() + 30; last = -1; stable = 0
while time.time() < deadline:
    m = ch.basic_get(queue=q, auto_ack=True)
    if m[0] is None:
        if last == total and stable >= 2:
            break
        last = total; stable += 1; time.sleep(1); continue
    stable = 0; total += 1
c.close()
print("TOTAL=" + str(total))
PY
        """
    )
    m = re.search(r"TOTAL=\s*(\d+)", out)
    return int(m.group(1)) if m else -1


# Durable-delivery control: the broker must keep its own confirmed durable
# messages internally consistent regardless of how its peer names resolve.
summary = publish_batch(publish_count)
recovered = drain_queue()

results = {
    "mode": mode,
    "publish_count": publish_count,
    "expected_full": expected_full,
    "mapping": mapping,
    "join_ok": join_ok,
    "members": {
        "rabbit1": member_names(rabbit1),
        "rabbit2": member_names(rabbit2),
        "rabbit3": member_names(rabbit3),
    },
    "publish_summary": summary,
    "recovered": recovered,
}
rabbit1.succeed(
    "cat > /tmp/dns-results.json << 'EOF'\n"
    + json.dumps(results, indent=2)
    + "\nEOF\n"
)
