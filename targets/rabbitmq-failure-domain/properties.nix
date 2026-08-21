{ lib }:

{
  one_domain_failure_retains_availability = {
    name = "rabbitmq-failure-domain-retains-quorum-availability";
    setup = ''
from collections import Counter

def load_failure_domain_results():
    return json.loads(rabbit1.succeed("cat /tmp/failure-domain-results.json"))

def check_failure_domain_availability():
    results = load_failure_domain_results()
    outcome = results["probe"]["outcome"]
    if outcome != "confirmed":
        raise AssertionError(
            "declared one-domain tolerance was violated: placement="
            + str(results["placement"]) + "; failed_domain="
            + results["failed_domain"] + "; surviving_nodes="
            + str(results["surviving_nodes"]) + "; probe=" + str(results["probe"])
        )
    '';
    check = ''
_check("rabbitmq-failure-domain-retains-quorum-availability", check_failure_domain_availability)
    '';
  };

  exact_recovery = {
    name = "rabbitmq-failure-domain-exact-recovery";
    setup = ''
def check_failure_domain_exact_recovery():
    results = load_failure_domain_results()
    records = results["recovered"]
    recovered = Counter(item["message_id"] for item in records)
    malformed = [item for item in records if item["message_id"] != item["body_id"]]
    expected = set(results["baseline_ids"])
    if results["probe"]["outcome"] in {"confirmed", "ambiguous"}:
        expected.add(results["probe"]["op_id"])
    lost = {op_id: recovered[op_id] for op_id in expected if recovered[op_id] != 1}
    unknown = set(recovered) - expected
    duplicates = {op_id: count for op_id, count in recovered.items() if count != 1}
    if malformed or lost or unknown or duplicates:
        raise AssertionError(
            "invalid recovery history: malformed=" + str(malformed)
            + "; expected=" + str(lost) + "; unknown=" + str(unknown)
            + "; duplicates=" + str(duplicates)
        )
    '';
    check = ''
_check("rabbitmq-failure-domain-exact-recovery", check_failure_domain_exact_recovery)
    '';
  };
}
