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

# Form a 3-node RabbitMQ cluster. rabbit1 is the seed; rabbit2 and rabbit3
# join it via the same Erlang cookie.
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
# queue exists on all replicas before any partition is applied.
for machine in [rabbit1, rabbit2, rabbit3]:
    machine.succeed(
        """
python3 - <<'PY'
import pika

connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
channel.queue_declare(
    queue="topotestix_partition",
    durable=True,
    arguments={"x-queue-type": "quorum", "x-quorum-initial-group-size": 3},
)
connection.close()
PY
        """
    )

# Read the fuzzed partition parameters. Each parameter is a separate file
# written by config.nix, so the fuzzer can vary each dimension independently.
shape = rabbit1.succeed("cat /etc/topotestix-partition-shape").strip()
ports = rabbit1.succeed("cat /etc/topotestix-partition-ports").strip()
direction = rabbit1.succeed("cat /etc/topotestix-partition-direction").strip()
heal_after = int(rabbit1.succeed("cat /etc/topotestix-partition-heal").strip())

# Resolve node hostnames to their VLAN interface IPs. NixOS VM tests
# expose two interfaces: eth0 on the QEMU user network (10.0.2.15, used
# for management) and eth1 on the test VLAN (192.168.1.x, used for
# inter-VM traffic). The Erlang distribution and AMQP traffic between
# nodes flow over eth1, so iptables rules must target that interface's
# address, not the QEMU management address.
rabbit_machines = {"rabbit1": rabbit1, "rabbit2": rabbit2, "rabbit3": rabbit3}
ip = {}
for name, machine in rabbit_machines.items():
    ip[name] = machine.succeed(
        "ip -j addr show eth1 | python3 -c '"
        "import json, sys\n"
        "data = json.load(sys.stdin)\n"
        "for a in data[0].get(\"addr_info\", []):\n"
        "    if a.get(\"family\") == \"inet\":\n"
        "        print(a[\"local\"])\n"
        "        sys.exit(0)\n"
        "sys.exit(1)\n"
        "'"
    ).strip()

# Decide which nodes belong to which side of the partition.
if shape == "isolate-1":
    isolated = ["rabbit1"]
    others = ["rabbit2", "rabbit3"]
elif shape == "isolate-2":
    isolated = ["rabbit1", "rabbit2"]
    others = ["rabbit3"]
else:
    isolated = []
    others = ["rabbit1", "rabbit2", "rabbit3"]

# Apply the partition with iptables. The current fuzz surface always
# uses `ports = "none"`, which is a blanket drop on all inter-side
# traffic. Port-specific blocking (AMQP-only or Erlang-only) is left
# as future work: the Erlang distribution in particular can use
# ephemeral ports resolved via EPMD, so a port-list rule does not
# reliably partition the cluster in the NixOS VM test harness.
if shape != "none":
    for iso_name in isolated:
        for other_name in others:
            iso_machine = rabbit_machines[iso_name]
            other_machine = rabbit_machines[other_name]
            iso_ip = ip[iso_name]
            other_ip = ip[other_name]

            # Isolated side blocks outgoing traffic toward the other side.
            iso_machine.execute(
                f"iptables -A OUTPUT -d {other_ip} -j DROP"
            )

            # For a two-way partition, the other side also blocks outgoing
            # traffic toward the isolated side. Without this, the "other"
            # side can still send to the "isolated" side, which means a
            # lone "other" node (the Raft minority) can still reach the
            # majority and have its writes accepted.
            if direction == "two-way":
                other_machine.execute(
                    f"iptables -A OUTPUT -d {iso_ip} -j DROP"
                )

    # Give the Erlang distribution time to notice the lost peers. With
    # heartbeat=10 the cluster should detect the failure within 15-20s.
    time.sleep(15)

# Attempt a durable, confirmed publish from every node. The exit status
# and stdout tag are captured so the properties can assert quorum-safety
# invariants without re-running the writes.
WRITE_SCRIPT_TEMPLATE = """
python3 - <<'PY'
import pika
import sys

NODE_NAME = "NODE_NAME_PLACEHOLDER"

try:
    connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
    channel = connection.channel()
    channel.confirm_delivery()
    try:
        channel.basic_publish(
            exchange="",
            routing_key="topotestix_partition",
            body=("write-from-" + NODE_NAME).encode(),
            properties=pika.BasicProperties(delivery_mode=2),
            mandatory=True,
        )
        print("WRITE_SUCCEEDED")
    except pika.exceptions.UnroutableError:
        print("WRITE_UNROUTABLE")
    except pika.exceptions.NackError:
        print("WRITE_NACKED")
    except Exception as e:
        print("WRITE_ERROR:", type(e).__name__, str(e))
    connection.close()
except Exception as e:
    print("WRITE_ERROR:", type(e).__name__, str(e))
PY
"""

write_results = {}
write_statuses = {}
for name, machine in rabbit_machines.items():
    script = WRITE_SCRIPT_TEMPLATE.replace("NODE_NAME_PLACEHOLDER", name)
    status, out = machine.execute(script, timeout=30)
    write_statuses[name] = status
    write_results[name] = out.strip()

# Persist the write outcomes and partition parameters so the property
# checks can read them after the script returns.
results = {
    "shape": shape,
    "ports": ports,
    "direction": direction,
    "heal_after": heal_after,
    "isolated": isolated,
    "others": others,
    "write_statuses": write_statuses,
    "writes": write_results,
}
rabbit1.succeed(
    f"cat > /tmp/partition-results.json << 'EOF'\n{json.dumps(results, indent=2)}\nEOF"
)

# Wait out the configured heal window, then remove all iptables rules so
# the Erlang distribution can re-establish.
if heal_after > 0:
    time.sleep(heal_after)

for machine in [rabbit1, rabbit2, rabbit3]:
    machine.execute("iptables -F")

# Give the cluster a moment to converge after the rules are flushed. The
# cluster_converges_after_healing property performs a stricter check.
time.sleep(10)
