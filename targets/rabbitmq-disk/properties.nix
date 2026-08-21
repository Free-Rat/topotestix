{ lib }:

{
  exact_operation_history = {
    name = "rabbitmq-disk-exact-operation-history";
    setup = ''
from collections import Counter

def load_disk_results():
    return json.loads(rabbit1.succeed("cat /tmp/disk-results.json"))

def check_disk_exact_operation_history():
    results = load_disk_results()
    operations = results["operations"]
    ids = [op["op_id"] for op in operations]
    if len(ids) != len(set(ids)):
        raise AssertionError("duplicate operation IDs in publisher history")
    allowed = {"confirmed", "rejected", "timed_out", "ambiguous"}
    invalid = [op for op in operations if op.get("outcome") not in allowed]
    if invalid:
        raise AssertionError("unclassified publish operations: " + str(invalid))
    for message in results["recovered"]:
        if message["message_id"] != message["body_id"]:
            raise AssertionError("message_id/body mismatch: " + str(message))
    '';
    check = ''
_check("rabbitmq-disk-exact-operation-history", check_disk_exact_operation_history)
    '';
  };

  confirmed_recovered_exactly_once = {
    name = "rabbitmq-disk-confirmed-recovered-exactly-once";
    setup = ''
def check_disk_confirmed_recovered_exactly_once():
    results = load_disk_results()
    recovered = Counter(item["message_id"] for item in results["recovered"])
    confirmed = {op["op_id"] for op in results["operations"] if op["outcome"] == "confirmed"}
    bad = {op_id: recovered[op_id] for op_id in confirmed if recovered[op_id] != 1}
    if bad:
        raise AssertionError("confirmed messages not recovered exactly once: " + str(bad))
    '';
    check = ''
_check("rabbitmq-disk-confirmed-recovered-exactly-once", check_disk_confirmed_recovered_exactly_once)
    '';
  };

  no_unexplained_messages = {
    name = "rabbitmq-disk-no-unexplained-messages";
    setup = ''
def check_disk_no_unexplained_messages():
    results = load_disk_results()
    operations = {op["op_id"]: op for op in results["operations"]}
    recovered = Counter(item["message_id"] for item in results["recovered"])
    unknown = set(recovered) - set(operations)
    duplicates = {op_id: count for op_id, count in recovered.items() if count != 1}
    forbidden = {
        op_id for op_id, op in operations.items()
        if op["outcome"] in {"rejected", "timed_out"} and recovered[op_id]
    }
    if unknown or duplicates or forbidden:
        raise AssertionError(
            "invalid recovered history: unknown=" + str(unknown)
            + "; duplicates=" + str(duplicates) + "; rejected_or_presend=" + str(forbidden)
        )
    '';
    check = ''
_check("rabbitmq-disk-no-unexplained-messages", check_disk_no_unexplained_messages)
    '';
  };

  capacity_confirmation_contract = {
    name = "rabbitmq-disk-capacity-confirmation-contract";
    setup = ''
def check_disk_capacity_confirmation_contract():
    results = load_disk_results()
    if not results["contract"]["capacity_sufficient"]:
        return
    non_confirmed = [
        op for op in results["operations"] if op["outcome"] != "confirmed"
    ]
    alarms = [
        sample for sample in results["telemetry"]
        if sample["phase"] in {"after_fill", "after_publish"} and sample["disk_free_alarm"]
    ]
    if non_confirmed or alarms:
        raise AssertionError(
            "declared capacity was sufficient but confirmation SLO failed: operations="
            + str(non_confirmed) + "; alarms=" + str(alarms)
        )
    '';
    check = ''
_check("rabbitmq-disk-capacity-confirmation-contract", check_disk_capacity_confirmation_contract)
    '';
  };

  alarms_clear_and_cluster_healthy = {
    name = "rabbitmq-disk-recovers-healthy";
    setup = ''
def check_disk_recovers_healthy():
    results = load_disk_results()
    final_samples = [s for s in results["telemetry"] if s["phase"] == "after_recovery"]
    alarming = [s["node"] for s in final_samples if s["disk_free_alarm"]]
    if alarming:
        raise AssertionError("disk alarms did not clear on: " + str(alarming))
    state = results["queue_before"]
    if state.get("type") != "quorum":
        raise AssertionError("queue is not quorum: " + str(state))
    for machine in [rabbit1, rabbit2, rabbit3]:
        machine.succeed("systemctl is-active rabbitmq.service")
        machine.succeed("su -s /bin/sh rabbitmq -c 'rabbitmq-diagnostics -q ping'")
    '';
    check = ''
_check("rabbitmq-disk-recovers-healthy", check_disk_recovers_healthy)
    '';
  };
}
