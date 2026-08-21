{ lib }:

# Negative-control oracle for the stronger production availability assumption:
# every planned publish receives confirmation even when capacity is insufficient.
{
  availability_contract = {
    name = "rabbitmq-disk-all-publishes-confirmed";
    setup = ''
def check_disk_all_publishes_confirmed():
    results = json.loads(rabbit1.succeed("cat /tmp/disk-results.json"))
    failures = [op for op in results["operations"] if op["outcome"] != "confirmed"]
    if failures:
        raise AssertionError("publishes exceeded the confirmation budget: " + str(failures))
    '';
    check = ''
_disk_results = json.loads(rabbit1.succeed("cat /tmp/disk-results.json"))
_check_expected(
    "rabbitmq-disk-all-publishes-confirmed",
    check_disk_all_publishes_confirmed,
    not _disk_results["contract"]["capacity_sufficient"],
)
    '';
  };
}
