import copy
import importlib.util
import os
import unittest

ORACLE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "targets",
    "kafka-topology",
    "oracle.py",
)
SPEC = importlib.util.spec_from_file_location("kafka_topology_oracle", ORACLE_PATH)
ORACLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORACLE)


def valid_result():
    baseline_ids = [f"run/baseline/{index:04d}" for index in range(100)]
    probe_id = "run/probe/0000"
    post_id = "run/post-recovery/0000"
    recovered = [
        {"op_id": op_id, "key_id": op_id, "partition": 0, "offset": index}
        for index, op_id in enumerate(baseline_ids + [probe_id, post_id])
    ]
    brokers = {
        f"kafka{index}": {
            "broker_id": index,
            "rack": "rack-a" if index <= 2 else "rack-b" if index <= 4 else "rack-c",
            "internal_address": f"192.168.10.{index + 1}",
            "external_address": f"192.168.20.{index + 1}",
            "runtime_configuration": "broker.rack="
            + ("rack-a" if index <= 2 else "rack-b" if index <= 4 else "rack-c"),
        }
        for index in range(1, 6)
    }
    service_before = {
        name: {
            "active": True,
            "main_pid": index,
            "restart": "no",
            "data_identity": name,
            "control_group": "/system.slice/apache-kafka.service",
            "client_endpoint_reachable": True,
        }
        for index, name in enumerate(brokers, start=10)
    }
    quorum_status = (
        'CurrentVoters: [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}]\n'
        "CurrentObservers: []"
    )
    return {
        "classification": "completed",
        "error": None,
        "configuration": {
            "placement": "spread",
            "intervention": "no-fault",
            "client_plane": "shared",
            "client_vlan": 10,
            "producer": {"observation_delay_seconds": 35},
        },
        "topology": {
            "brokers": brokers,
            "client_addresses": ["192.168.10.1"],
            "bootstrap_servers": [f"192.168.10.{suffix}:9092" for suffix in range(2, 7)],
            "selected_route_status": 0,
            "opposite_route_status": 2,
            "manifest_consistent": True,
            "listeners_ready": True,
        },
        "topic": {
            "expected_assignment": [1, 3, 5],
            "before": {"leader": 1, "replicas": [1, 3, 5], "isr": [1, 3, 5]},
            "during": {"leader": 1, "replicas": [1, 3, 5], "isr": [1, 3, 5]},
            "after": {"leader": 1, "replicas": [1, 3, 5], "isr": [1, 3, 5]},
        },
        "intervention": {
            "observed_leader": 1,
            "target_nodes": [],
            "target_broker_ids": [],
            "kill_timestamps_ns": [],
            "kill_completed_timestamps_ns": [],
            "kill_interval_ms": 0,
            "observation_window_started_ns": 100,
            "observation_checkpoint_ns": 35_000_000_100,
            "service_before": service_before,
            "service_after_kill": copy.deepcopy(service_before),
            "service_after_recovery": service_before,
        },
        "workload": {
            "baseline": [{"op_id": op_id, "outcome": "confirmed"} for op_id in baseline_ids],
            "baseline_ids": baseline_ids,
            "probe": {
                "op_id": probe_id,
                "invoked": True,
                "outcome": "confirmed",
                "exception_type": None,
            },
            "post_recovery": [{"op_id": post_id, "outcome": "confirmed"}],
            "recovered": recovered,
            "complete_read": True,
            "start_offset": 0,
            "end_offset": len(recovered),
        },
        "recovery": {
            "all_services_active": True,
            "restarted_broker_readiness": {},
            "metadata_quorum_before": quorum_status,
            "metadata_quorum_pre_intervention": quorum_status,
            "metadata_quorum_after": quorum_status,
        },
        "oracle": {
            "expected_probe_confirmation": True,
        },
        "versions": {
            "kafka": "4.2.0",
            "kafka_package": "apache-kafka-2.13-4.2.0",
            "kafka_store_path": "/nix/store/hash-apache-kafka-2.13-4.2.0/bin/kafka-topics.sh",
            "java": 'openjdk version "17.0.18"',
        },
    }


class KafkaTopologyOracleTests(unittest.TestCase):
    def test_valid_result_passes_all_checks(self):
        result = valid_result()
        ORACLE.check_materialized(result)
        ORACLE.check_intervention_accurate(result)
        ORACLE.check_probe_confirmation(result)
        ORACLE.check_runtime_versions(result)
        ORACLE.check_prefault_acknowledged_records_recovered_exactly_once(result)
        ORACLE.check_cluster_recovered(result)

    def test_concentrated_separated_topology_materializes(self):
        result = valid_result()
        result["configuration"].update(
            {
                "placement": "concentrated",
                "client_plane": "separated",
                "client_vlan": 20,
            }
        )
        result["topology"]["client_addresses"] = ["192.168.20.1"]
        result["topology"]["bootstrap_servers"] = [
            f"192.168.20.{suffix}:9095" for suffix in range(2, 7)
        ]
        result["topic"]["expected_assignment"] = [1, 2, 3]
        result["topic"]["before"].update({"leader": 1, "replicas": [1, 2, 3], "isr": [1, 2, 3]})
        result["topic"]["after"].update({"leader": 1, "replicas": [1, 2, 3], "isr": [1, 2, 3]})
        ORACLE.check_materialized(result)

    def test_rack_kill_evidence_passes_with_new_pids(self):
        result = valid_result()
        result["configuration"]["intervention"] = "rack-kill"
        result["intervention"]["target_nodes"] = ["kafka1", "kafka2"]
        result["intervention"]["target_broker_ids"] = [1, 2]
        result["intervention"]["kill_timestamps_ns"] = [10, 20]
        result["intervention"]["kill_completed_timestamps_ns"] = [11, 21]
        result["intervention"]["observation_window_started_ns"] = 22
        result["intervention"]["observation_checkpoint_ns"] = 35_000_000_022
        result["topic"]["during"] = {
            "leader": 3,
            "replicas": [1, 3, 5],
            "isr": [3, 5],
        }
        result["intervention"]["service_after_recovery"] = copy.deepcopy(
            result["intervention"]["service_before"]
        )
        for name in ["kafka1", "kafka2"]:
            result["intervention"]["service_after_kill"][name] = {
                "active": False,
                "main_pid": 0,
                "restart": "no",
                "data_identity": name,
                "control_group": "/system.slice/apache-kafka.service",
                "client_endpoint_reachable": False,
            }
            result["intervention"]["service_after_recovery"][name]["main_pid"] += 100
        ORACLE.check_intervention_accurate(result)

    def test_probe_confirmation_mismatch_fails(self):
        result = valid_result()
        result["oracle"]["expected_probe_confirmation"] = False
        with self.assertRaisesRegex(AssertionError, "differs from the frozen rule"):
            ORACLE.check_probe_confirmation(result)

    def test_expected_negative_probe_requires_invocation_and_expected_kafka_error(self):
        result = valid_result()
        result["configuration"]["placement"] = "concentrated"
        result["configuration"]["intervention"] = "rack-kill"
        result["oracle"]["expected_probe_confirmation"] = False
        result["workload"]["probe"].update(
            {
                "outcome": "ambiguous",
                "exception_type": "org.apache.kafka.common.errors.TimeoutException",
            }
        )
        ORACLE.check_probe_confirmation(result)

        result["workload"]["probe"]["invoked"] = False
        with self.assertRaisesRegex(AssertionError, "did not return a Future"):
            ORACLE.check_probe_confirmation(result)

        result["workload"]["probe"].update(
            {
                "invoked": True,
                "exception_type": "org.apache.kafka.common.errors.TopicAuthorizationException",
            }
        )
        with self.assertRaisesRegex(AssertionError, "exception_type"):
            ORACLE.check_probe_confirmation(result)

    def test_missing_baseline_record_fails(self):
        result = valid_result()
        result["workload"]["recovered"].pop(0)
        with self.assertRaisesRegex(AssertionError, "baseline multiplicity"):
            ORACLE.check_prefault_acknowledged_records_recovered_exactly_once(result)

    def test_duplicate_baseline_record_fails(self):
        result = valid_result()
        result["workload"]["recovered"].append(copy.deepcopy(result["workload"]["recovered"][0]))
        with self.assertRaisesRegex(AssertionError, "duplicates"):
            ORACLE.check_prefault_acknowledged_records_recovered_exactly_once(result)

    def test_unknown_record_fails(self):
        result = valid_result()
        result["workload"]["recovered"].append(
            {"op_id": "unknown", "key_id": "unknown", "partition": 0, "offset": 102}
        )
        with self.assertRaisesRegex(AssertionError, "unknown"):
            ORACLE.check_prefault_acknowledged_records_recovered_exactly_once(result)

    def test_ambiguous_probe_may_be_absent(self):
        result = valid_result()
        probe_id = result["workload"]["probe"]["op_id"]
        result["workload"]["probe"]["outcome"] = "ambiguous"
        result["workload"]["recovered"] = [
            record for record in result["workload"]["recovered"] if record["op_id"] != probe_id
        ]
        post_id = result["workload"]["post_recovery"][0]["op_id"]
        next(record for record in result["workload"]["recovered"] if record["op_id"] == post_id)[
            "offset"
        ] = 100
        result["workload"]["end_offset"] = 101
        ORACLE.check_prefault_acknowledged_records_recovered_exactly_once(result)

    def test_short_observation_window_fails(self):
        result = valid_result()
        result["intervention"]["observation_checkpoint_ns"] -= 1
        with self.assertRaisesRegex(AssertionError, "observation window"):
            ORACLE.check_intervention_accurate(result)

    def test_no_fault_pid_change_fails(self):
        result = valid_result()
        result["intervention"]["service_after_kill"]["kafka2"]["main_pid"] += 100
        with self.assertRaisesRegex(AssertionError, "changed during the observation window"):
            ORACLE.check_intervention_accurate(result)

    def test_missing_controller_voter_fails(self):
        result = valid_result()
        result["recovery"]["metadata_quorum_after"] = (
            'CurrentVoters: [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}]\n' "CurrentObservers: []"
        )
        with self.assertRaisesRegex(AssertionError, "five frozen voters"):
            ORACLE.check_cluster_recovered(result)

    def test_recovery_requires_readiness_for_every_restarted_broker(self):
        result = valid_result()
        result["intervention"]["target_nodes"] = ["kafka1", "kafka2"]
        result["recovery"]["restarted_broker_readiness"] = {
            "kafka1": {
                "service_active": True,
                "listeners_ready": True,
                "client_api_ready": True,
                "client_endpoint": "192.168.10.2:9092",
            }
        }
        with self.assertRaisesRegex(AssertionError, "restarted broker readiness set"):
            ORACLE.check_cluster_recovered(result)
        result["recovery"]["restarted_broker_readiness"]["kafka2"] = {
            "service_active": True,
            "listeners_ready": True,
            "client_api_ready": True,
            "client_endpoint": "192.168.10.3:9092",
        }
        ORACLE.check_cluster_recovered(result)

    def test_post_recovery_marker_is_a_recovery_gate(self):
        result = valid_result()
        result["workload"]["post_recovery"][0]["outcome"] = "ambiguous"
        ORACLE.check_prefault_acknowledged_records_recovered_exactly_once(result)
        with self.assertRaisesRegex(AssertionError, "post-recovery marker"):
            ORACLE.check_cluster_recovered(result)

    def test_incomplete_execution_blocks_contract_checks(self):
        result = valid_result()
        result["classification"] = "inconclusive"
        with self.assertRaisesRegex(AssertionError, "did not reach a contract verdict"):
            ORACLE.check_prefault_acknowledged_records_recovered_exactly_once(result)


if __name__ == "__main__":
    unittest.main()
