{ lib }:

{
  minority_rejects_writes = {
    name = "rabbitmq-partition-minority-rejects-writes";
    setup = ''
def check_minority_rejects_writes():
    """The 1-node side of any partition must not accept unsafe writes.

    With a 3-node cluster, the minority is always exactly one node:
      shape=isolate-1  -> rabbit1 is isolated (minority)
      shape=isolate-2  -> rabbit3 is the lone connected node (minority)

    For one-way partitions with isolate-2, the minority is on the "other"
    side and can still send to the majority. That is expected asymmetric
    behavior, so the property is skipped for that combination.
    """
    shape = rabbit1.succeed("cat /etc/topotestix-partition-shape").strip()
    if shape == "none":
        return  # No partition, nothing to assert

    direction = rabbit1.succeed("cat /etc/topotestix-partition-direction").strip()
    if shape == "isolate-2" and direction == "one-way":
        return  # Minority can still reach the majority in this case

    results_raw = rabbit1.succeed("cat /tmp/partition-results.json")
    results = json.loads(results_raw)

    if shape == "isolate-1":
        minority = ["rabbit1"]
    elif shape == "isolate-2":
        minority = ["rabbit3"]
    else:
        return

    for name in minority:
        write_result = results["writes"].get(name, "")
        if "WRITE_SUCCEEDED" in write_result:
            raise AssertionError(
                f"minority node {name} accepted a write during partition "
                f"(shape={shape}, ports={results['ports']}): {write_result}"
            )
    '';
    check = ''
_check("rabbitmq-partition-minority-rejects-writes", check_minority_rejects_writes)
    '';
  };

  majority_accepts_writes = {
    name = "rabbitmq-partition-majority-accepts-writes";
    setup = ''
def check_majority_accepts_writes():
    """The 2-node side must remain available for writes during a partition."""
    shape = rabbit1.succeed("cat /etc/topotestix-partition-shape").strip()
    if shape == "none":
        return

    results_raw = rabbit1.succeed("cat /tmp/partition-results.json")
    results = json.loads(results_raw)

    if shape == "isolate-1":
        majority = ["rabbit2", "rabbit3"]
    elif shape == "isolate-2":
        majority = ["rabbit1", "rabbit2"]
    else:
        return

    for name in majority:
        write_result = results["writes"].get(name, "")
        if "WRITE_SUCCEEDED" not in write_result:
            raise AssertionError(
                f"majority node {name} rejected a write during partition "
                f"(shape={shape}): {write_result}"
            )
    '';
    check = ''
_check("rabbitmq-partition-majority-accepts-writes", check_majority_accepts_writes)
    '';
  };

  cluster_converges_after_healing = {
    name = "rabbitmq-partition-cluster-converges-after-healing";
    setup = ''
def check_cluster_converges():
    """After iptables rules are flushed, every node must rejoin the cluster.

    A 120s budget covers both fast Erlang distribution reconnects and
    slow quorum re-formation under sustained packet loss.
    """
    for machine in [rabbit1, rabbit2, rabbit3]:
        machine.wait_until_succeeds(
            "su -s /bin/sh rabbitmq -c 'rabbitmqctl cluster_status' > /tmp/cluster-status && "
            "grep -q 'rabbit@rabbit1' /tmp/cluster-status && "
            "grep -q 'rabbit@rabbit2' /tmp/cluster-status && "
            "grep -q 'rabbit@rabbit3' /tmp/cluster-status",
            timeout=120,
        )
    '';
    check = ''
_check("rabbitmq-partition-cluster-converges-after-healing", check_cluster_converges)
    '';
  };

  no_split_brain = {
    name = "rabbitmq-partition-no-split-brain";
    setup = ''
def check_no_split_brain():
    """After healing, the quorum queue must contain a consistent history.

    The defining property of a split-brain is the same message being
    accepted by both sides of the partition and appearing twice in the
    log. A Raft minority that fails to replicate a write may still have
    the uncommitted entry in its local log; if that entry is later
    committed by the new leader after the heal, it is not a split-brain
    duplication -- it is a single message that crossed the partition.

    So the property asserts uniqueness (no duplicates), not the exact
    count.
    """
    output = rabbit1.succeed(
        """
python3 - <<'PY'
import pika
import time

queue = "topotestix_partition"
connection = pika.BlockingConnection(pika.ConnectionParameters("localhost"))
channel = connection.channel()
count = 0
seen = set()
deadline = time.time() + 30
while time.time() < deadline:
    method, properties, body = channel.basic_get(queue=queue, auto_ack=True)
    if method is None:
        if count > 0:
            break
        time.sleep(0.5)
    else:
        count += 1
        seen.add(body)
connection.close()
print("COUNT=", count, "UNIQUE=", len(seen))
PY
        """
    )

    import re
    match = re.search(r"COUNT=\s*(\d+)\s+UNIQUE=\s*(\d+)", output)
    if not match:
        raise AssertionError(f"failed to parse queue drain output: {output}")
    count = int(match.group(1))
    unique = int(match.group(2))

    if count != unique:
        raise AssertionError(
            f"split-brain detected: same message accepted by both partition "
            f"sides (count={count} unique={unique})"
        )
    '';
    check = ''
_check("rabbitmq-partition-no-split-brain", check_no_split_brain)
    '';
  };

  service_still_up_after_delay = {
    name = "rabbitmq-partition-still-up-after-delay";
    setup = ''
def check_service_still_up(machine):
    machine.succeed("systemctl is-active rabbitmq.service")
    '';
    check = ''
_check("rabbitmq-partition-still-up-rabbit1", check_service_still_up, rabbit1)
_check("rabbitmq-partition-still-up-rabbit2", check_service_still_up, rabbit2)
_check("rabbitmq-partition-still-up-rabbit3", check_service_still_up, rabbit3)
    '';
  };
}
