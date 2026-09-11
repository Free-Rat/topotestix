{ lib }:

let
  oracleSource = builtins.toJSON (builtins.readFile ./oracle.py);
in
{
  kafka_topology_contracts = {
    name = "kafka-topology-contracts";
    setup = ''
exec(
    compile(
        ${oracleSource},
        "kafka-topology-oracle.py",
        "exec",
    ),
    globals(),
)

def load_kafka_topology_result():
    return json.loads(client1.succeed("cat /tmp/kafka-topology-result.json"))

def check_kafka_topology_completed():
    require_completed(load_kafka_topology_result())

def check_kafka_topology_materialized():
    check_materialized(load_kafka_topology_result())

def check_kafka_intervention_accurate():
    check_intervention_accurate(load_kafka_topology_result())

def check_kafka_probe_confirmation():
    check_probe_confirmation(load_kafka_topology_result())

def check_kafka_runtime_versions():
    check_runtime_versions(load_kafka_topology_result())

def check_kafka_durability():
    check_prefault_acknowledged_records_recovered_exactly_once(load_kafka_topology_result())

def check_kafka_recovery():
    check_cluster_recovered(load_kafka_topology_result())
    '';
    check = ''
_check("kafka-topology-execution-completed", check_kafka_topology_completed)
_check("kafka-topology-materialized", check_kafka_topology_materialized)
_check("kafka-topology-intervention-accurate", check_kafka_intervention_accurate)
_check("kafka-topology-probe-confirmation-matches-oracle", check_kafka_probe_confirmation)
_check("kafka-topology-runtime-versions-pinned", check_kafka_runtime_versions)
_check("kafka-topology-prefault-acknowledged-records-recovered-exactly-once", check_kafka_durability)
_check("kafka-topology-cluster-recovers", check_kafka_recovery)
    '';
  };
}
