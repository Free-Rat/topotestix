{ lib }:

{
  kafka_rack_links_contracts = {
    name = "kafka-rack-links-contracts";
    # The oracle is inlined verbatim so the NixOS test driver type-checks it
    # together with the rest of the composed script; the test script also
    # uses its topology helpers.
    setup = builtins.readFile ./oracle.py + ''

def load_kafka_rack_links_result():
    # Read the copy the test script already placed in $out.
    with open(client1.out_dir / "kafka-rack-links-result.json", encoding="utf-8") as handle:
        return json.load(handle)

def check_kafka_rack_links_completed():
    require_completed(load_kafka_rack_links_result())

def check_kafka_rack_links_materialized():
    check_materialized(load_kafka_rack_links_result())

def check_kafka_rack_links_cut_accurate():
    check_cut_accurate(load_kafka_rack_links_result())

def check_kafka_rack_links_durability():
    check_confirmed_records_recovered_exactly_once(load_kafka_rack_links_result())

def check_kafka_rack_links_recovery():
    check_cluster_recovered(load_kafka_rack_links_result())

def check_kafka_rack_links_versions():
    check_runtime_versions(load_kafka_rack_links_result())
    '';
    check = ''
_check("kafka-rack-links-execution-completed", check_kafka_rack_links_completed)
_check("kafka-rack-links-materialized", check_kafka_rack_links_materialized)
_check("kafka-rack-links-cut-accurate", check_kafka_rack_links_cut_accurate)
_check("kafka-rack-links-confirmed-records-recovered-exactly-once", check_kafka_rack_links_durability)
_check("kafka-rack-links-cluster-recovers", check_kafka_rack_links_recovery)
_check("kafka-rack-links-runtime-versions-pinned", check_kafka_rack_links_versions)
    '';
  };
}
