{ lib }:

# Paired negative control for rabbitmq-partition. Quorum queues intentionally
# trade minority availability for safety. This strict all-node availability
# contract should therefore produce an expected_failure for partitioned cells.
{
  all_nodes_remain_available = {
    name = "rabbitmq-partition-all-nodes-remain-available";
    setup = ''
def check_all_nodes_remain_available():
    results = json.loads(rabbit1.succeed("cat /tmp/partition-results.json"))
    for name in ["rabbit1", "rabbit2", "rabbit3"]:
        write_result = results["writes"].get(name, "")
        write_status = results["write_statuses"].get(name)
        if write_status != 0 or "WRITE_SUCCEEDED" not in write_result:
            raise AssertionError(
                "node " + name + " was unavailable during partition: "
                + write_result + "; process_status=" + str(write_status)
            )

    '';
    check = ''
_partition_contract_results = json.loads(rabbit1.succeed("cat /tmp/partition-results.json"))
_check_expected(
    "rabbitmq-partition-all-nodes-remain-available",
    check_all_nodes_remain_available,
    _partition_contract_results["shape"] != "none",
)
    '';
  };
}
