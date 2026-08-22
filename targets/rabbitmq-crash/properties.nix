{ lib }:

{
  exact_confirmed_durability = {
    name = "rabbitmq-crash-confirmed-recovered-exactly-once";
    setup = ''
from collections import Counter

def load_crash_results():
    return json.loads(rabbit1.succeed("cat /tmp/crash-results.json"))

def check_crash_confirmed_durability():
    results = load_crash_results()
    operations = results["operations"]
    recovered_records = results["recovered"]
    recovered = Counter(item["message_id"] for item in recovered_records)
    attempted = {op["op_id"] for op in operations}
    confirmed = {op["op_id"] for op in operations if op["outcome"] == "confirmed"}
    rejected = {op["op_id"] for op in operations if op["outcome"] in {"rejected", "timed_out"}}

    if len(attempted) != len(operations):
        raise AssertionError("duplicate operation IDs in publisher history")
    malformed = [item for item in recovered_records if item["message_id"] != item["body_id"]]
    lost = {op_id: recovered[op_id] for op_id in confirmed if recovered[op_id] != 1}
    duplicates = {op_id: count for op_id, count in recovered.items() if count != 1}
    unknown = set(recovered) - attempted
    forbidden = set(recovered) & rejected
    if malformed or lost or duplicates or unknown or forbidden:
        raise AssertionError(
            "crash durability violation: malformed=" + str(malformed)
            + "; confirmed=" + str(lost) + "; duplicates=" + str(duplicates)
            + "; unknown=" + str(unknown) + "; rejected=" + str(forbidden)
        )
    '';
    check = ''
_check("rabbitmq-crash-confirmed-recovered-exactly-once", check_crash_confirmed_durability)
    '';
  };

  fault_was_abrupt_and_role_accurate = {
    name = "rabbitmq-crash-fault-was-abrupt-and-role-accurate";
    setup = ''
def check_crash_fault_was_abrupt_and_role_accurate():
    results = load_crash_results()
    before = results["service_before"]
    after = results["service_after"]
    leader = str(results["queue_before"]["leader"]).split("@")[-1]
    if before.get("Restart") != "no":
        raise AssertionError("service auto-restart was enabled")
    if before.get("MainPID") == after.get("MainPID") or after.get("MainPID") in {None, "0"}:
        raise AssertionError("broker process was not replaced by recovery")
    if results["target_role"] == "leader" and results["target_node"] != leader:
        raise AssertionError("configured leader fault did not target observed leader")
    if results["target_role"] == "follower" and results["target_node"] == leader:
        raise AssertionError("configured follower fault targeted observed leader")
    '';
    check = ''
_check("rabbitmq-crash-fault-was-abrupt-and-role-accurate", check_crash_fault_was_abrupt_and_role_accurate)
    '';
  };

  queue_and_cluster_recover = {
    name = "rabbitmq-crash-queue-and-cluster-recover";
    setup = ''
def check_crash_queue_and_cluster_recover():
    results = load_crash_results()
    state = results["queue_after"]
    if state.get("type") != "quorum" or not state.get("leader"):
        raise AssertionError("quorum queue has no healthy leader after recovery: " + str(state))
    members = {str(item).split("@")[-1] for item in state.get("members", [])}
    online = {str(item).split("@")[-1] for item in state.get("online", [])}
    expected = {"rabbit1", "rabbit2", "rabbit3"}
    if members and members != expected:
        raise AssertionError("unexpected queue members after recovery: " + str(state))
    if online and online != expected:
        raise AssertionError(
            "not all queue members online after recovery: " + str(state)
            + "; cluster_status_from_rabbit1: "
            + str(results.get("cluster_status_after_recovery"))
        )
    for machine in [rabbit1, rabbit2, rabbit3]:
        machine.succeed("systemctl is-active rabbitmq.service")
        machine.succeed("su -s /bin/sh rabbitmq -c 'rabbitmq-diagnostics -q ping'")
    '';
    check = ''
_check("rabbitmq-crash-queue-and-cluster-recover", check_crash_queue_and_cluster_recover)
    '';
  };
}
