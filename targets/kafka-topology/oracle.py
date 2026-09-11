import re
from collections import Counter

EXPECTED_NEGATIVE_PROBE_EXCEPTION_TYPES = {
    "org.apache.kafka.common.errors.NotEnoughReplicasAfterAppendException",
    "org.apache.kafka.common.errors.NotEnoughReplicasException",
    "org.apache.kafka.common.errors.RequestTimedOutException",
    "org.apache.kafka.common.errors.TimeoutException",
}


def metadata_quorum_voter_ids(sample):
    section = sample.split("CurrentVoters:", 1)
    if len(section) != 2:
        return set()
    voter_section = section[1].split("CurrentObservers:", 1)[0]
    object_ids = re.findall(r'"id"\s*:\s*(\d+)', voter_section)
    if object_ids:
        return {int(value) for value in object_ids}
    simple_ids = re.search(r"\[([0-9,\s]+)\]", voter_section)
    if simple_ids:
        return {int(value) for value in simple_ids.group(1).split(",") if value.strip()}
    return set()


def require_completed(results):
    if results["classification"] != "completed":
        raise AssertionError(
            "execution did not reach a contract verdict: classification="
            + str(results["classification"])
            + "; error="
            + str(results.get("error"))
        )


def check_materialized(results):
    require_completed(results)
    configuration = results["configuration"]
    topology = results["topology"]
    expected_nodes = {"kafka1", "kafka2", "kafka3", "kafka4", "kafka5"}
    expected_racks = {
        "kafka1": "rack-a",
        "kafka2": "rack-a",
        "kafka3": "rack-b",
        "kafka4": "rack-b",
        "kafka5": "rack-c",
    }
    expected_assignment = {
        "spread": [1, 3, 5],
        "concentrated": [1, 2, 3],
    }[configuration["placement"]]
    expected_client = {
        "shared": (10, "192.168.10.1"),
        "separated": (20, "192.168.20.1"),
    }[configuration["client_plane"]]
    errors = []
    if set(topology["brokers"]) != expected_nodes:
        errors.append("broker set=" + str(sorted(topology["brokers"])))
    for name, rack in expected_racks.items():
        broker = topology["brokers"].get(name, {})
        suffix = int(name.removeprefix("kafka")) + 1
        if broker.get("broker_id") != int(name.removeprefix("kafka")):
            errors.append(name + " broker_id=" + str(broker.get("broker_id")))
        if broker.get("rack") != rack:
            errors.append(name + " rack=" + str(broker.get("rack")))
        if broker.get("internal_address") != f"192.168.10.{suffix}":
            errors.append(name + " internal_address=" + str(broker.get("internal_address")))
        if broker.get("external_address") != f"192.168.20.{suffix}":
            errors.append(name + " external_address=" + str(broker.get("external_address")))
        if f"broker.rack={rack}" not in broker.get("runtime_configuration", ""):
            errors.append(name + " runtime broker.rack is missing")
    if configuration["client_vlan"] != expected_client[0]:
        errors.append("client_vlan=" + str(configuration["client_vlan"]))
    if expected_client[1] not in topology["client_addresses"]:
        errors.append("client_addresses=" + str(topology["client_addresses"]))
    listener_port = 9092 if configuration["client_plane"] == "shared" else 9095
    expected_bootstrap = [
        f"192.168.{expected_client[0]}.{suffix}:{listener_port}" for suffix in range(2, 7)
    ]
    if topology["bootstrap_servers"] != expected_bootstrap:
        errors.append("bootstrap_servers=" + str(topology["bootstrap_servers"]))
    if topology["selected_route_status"] != 0 or topology["opposite_route_status"] == 0:
        errors.append("client routes are not isolated")
    if not topology["manifest_consistent"] or not topology["listeners_ready"]:
        errors.append("manifest/listener gate failed")
    if results["topic"]["expected_assignment"] != expected_assignment:
        errors.append("expected assignment mismatch")
    before = results["topic"]["before"]
    if before["replicas"] != expected_assignment or sorted(before["isr"]) != sorted(
        expected_assignment
    ):
        errors.append("materialized assignment=" + str(before))
    if errors:
        raise AssertionError("topology materialization failed: " + "; ".join(errors))


def check_intervention_accurate(results):
    require_completed(results)
    intervention = results["configuration"]["intervention"]
    evidence = results["intervention"]
    if intervention == "no-fault":
        expected_nodes = []
    elif intervention == "leader-kill":
        expected_nodes = ["kafka" + str(evidence["observed_leader"])]
    else:
        expected_nodes = ["kafka1", "kafka2"]
    errors = []
    if evidence["observed_leader"] != results["topic"]["before"]["leader"]:
        errors.append("observed leader does not match the pre-fault topic state")
    if evidence["target_nodes"] != expected_nodes:
        errors.append("targets=" + str(evidence["target_nodes"]))
    expected_broker_ids = [int(name.removeprefix("kafka")) for name in expected_nodes]
    if evidence["target_broker_ids"] != expected_broker_ids:
        errors.append("target_broker_ids=" + str(evidence["target_broker_ids"]))
    if len(evidence["kill_timestamps_ns"]) != len(expected_nodes):
        errors.append("kill_timestamps_ns=" + str(evidence["kill_timestamps_ns"]))
    if len(evidence["kill_completed_timestamps_ns"]) != len(expected_nodes):
        errors.append(
            "kill_completed_timestamps_ns=" + str(evidence["kill_completed_timestamps_ns"])
        )
    if evidence["kill_interval_ms"] > 5000:
        errors.append("kill_interval_ms=" + str(evidence["kill_interval_ms"]))
    for started, completed in zip(
        evidence["kill_timestamps_ns"], evidence["kill_completed_timestamps_ns"]
    ):
        if completed < started:
            errors.append("kill completion precedes kill start")
    observation_delay_seconds = results["configuration"]["producer"]["observation_delay_seconds"]
    if observation_delay_seconds != 35:
        errors.append("observation delay differs from the frozen candidate")
    observed_delay_ns = (
        evidence["observation_checkpoint_ns"] - evidence["observation_window_started_ns"]
    )
    if observed_delay_ns < observation_delay_seconds * 1_000_000_000:
        errors.append("observation window was shorter than configured")
    during = results["topic"]["during"]
    expected_isr = [
        broker_id
        for broker_id in results["topic"]["expected_assignment"]
        if broker_id not in expected_broker_ids
    ]
    if (
        during["replicas"] != results["topic"]["expected_assignment"]
        or sorted(during["isr"]) != sorted(expected_isr)
        or during["leader"] not in expected_isr
    ):
        errors.append("post-fault topic state=" + str(during))
    for name, before in evidence["service_before"].items():
        at_checkpoint = evidence["service_after_kill"].get(name, {})
        recovered = evidence["service_after_recovery"][name]
        if before["restart"] != "no":
            errors.append(name + " Restart=" + str(before["restart"]))
        if not before["control_group"]:
            errors.append(name + " service cgroup is missing")
        if before.get("client_endpoint_reachable") is not True:
            errors.append(name + " client endpoint was not reachable before intervention")
        if at_checkpoint.get("data_identity") != before["data_identity"]:
            errors.append(name + " data directory identity changed during observation")
        if name in expected_nodes:
            if at_checkpoint.get("active") is not False or at_checkpoint.get("main_pid") != 0:
                errors.append(name + " did not remain stopped=" + str(at_checkpoint))
            if at_checkpoint.get("client_endpoint_reachable") is not False:
                errors.append(name + " client endpoint remained reachable")
            if not recovered["active"] or recovered["main_pid"] in {0, before["main_pid"]}:
                errors.append(name + " PID evidence=" + str((before, recovered)))
        else:
            if (
                not at_checkpoint.get("active")
                or at_checkpoint.get("main_pid") != before["main_pid"]
            ):
                errors.append(name + " changed during the observation window")
            if at_checkpoint.get("client_endpoint_reachable") is not True:
                errors.append(name + " client endpoint changed during observation")
            if not recovered["active"] or recovered["main_pid"] != before["main_pid"]:
                errors.append(name + " restarted without being targeted")
        if recovered["data_identity"] != before["data_identity"]:
            errors.append(name + " data directory identity changed")
    if errors:
        raise AssertionError("intervention evidence failed: " + "; ".join(errors))


def check_probe_confirmation(results):
    require_completed(results)
    expected = not (
        results["configuration"]["placement"] == "concentrated"
        and results["configuration"]["intervention"] == "rack-kill"
    )
    if results["oracle"]["expected_probe_confirmation"] != expected:
        raise AssertionError(
            "recorded topology oracle differs from the frozen rule: recorded="
            + str(results["oracle"]["expected_probe_confirmation"])
            + "; recomputed="
            + str(expected)
        )
    probe = results["workload"]["probe"]
    observed = probe["outcome"] == "confirmed"
    if observed != expected:
        raise AssertionError(
            "post-fault confirmation differs from the topology oracle: expected="
            + str(expected)
            + "; probe="
            + str(probe)
        )
    if not expected:
        errors = []
        if probe.get("invoked") is not True:
            errors.append("producer send did not return a Future")
        if probe.get("outcome") != "ambiguous":
            errors.append("outcome=" + str(probe.get("outcome")))
        if probe.get("exception_type") not in EXPECTED_NEGATIVE_PROBE_EXCEPTION_TYPES:
            errors.append("exception_type=" + str(probe.get("exception_type")))
        if errors:
            raise AssertionError("negative probe evidence failed: " + "; ".join(errors))


def check_runtime_versions(results):
    require_completed(results)
    versions = results["versions"]
    errors = []
    if "4.2.0" not in versions["kafka"]:
        errors.append("kafka=" + versions["kafka"])
    if versions["kafka_package"] != "apache-kafka-2.13-4.2.0":
        errors.append("kafka_package=" + versions["kafka_package"])
    if "apache-kafka-2.13-4.2.0" not in versions["kafka_store_path"]:
        errors.append("kafka_store_path=" + versions["kafka_store_path"])
    if "17" not in versions["java"]:
        errors.append("java=" + versions["java"])
    if errors:
        raise AssertionError("runtime version gate failed: " + "; ".join(errors))


def check_prefault_acknowledged_records_recovered_exactly_once(results):
    require_completed(results)
    workload = results["workload"]
    baseline = workload["baseline"]
    baseline_ids = workload["baseline_ids"]
    recovered = workload["recovered"]
    counts = Counter(record["op_id"] for record in recovered)
    errors = []
    if len(baseline) != 100 or len(set(baseline_ids)) != 100:
        errors.append("baseline cardinality=" + str(len(baseline_ids)))
    if baseline_ids != [event["op_id"] for event in baseline]:
        errors.append("baseline IDs differ from operation history")
    if any(event["outcome"] != "confirmed" for event in baseline):
        errors.append("baseline contains an unconfirmed operation")
    lost_or_duplicated = {op_id: counts[op_id] for op_id in baseline_ids if counts[op_id] != 1}
    if lost_or_duplicated:
        errors.append("baseline multiplicity=" + str(lost_or_duplicated))
    malformed = [record for record in recovered if record["key_id"] != record["op_id"]]
    operation_history = baseline + [workload["probe"]] + workload["post_recovery"]
    allowed = {event["op_id"] for event in operation_history}
    unknown = sorted(set(counts) - allowed)
    duplicates = {op_id: counts[op_id] for op_id in baseline_ids if counts[op_id] > 1}
    if malformed:
        errors.append("malformed=" + str(malformed))
    if unknown:
        errors.append("unknown=" + str(unknown))
    if duplicates:
        errors.append("duplicates=" + str(duplicates))
    offsets = [record["offset"] for record in recovered]
    expected_offsets = list(range(workload["start_offset"], workload["end_offset"]))
    if workload["start_offset"] != 0 or offsets != expected_offsets:
        errors.append(
            "complete offset range="
            + str(
                {
                    "start": workload["start_offset"],
                    "end": workload["end_offset"],
                    "observed": offsets,
                }
            )
        )
    if any(record["partition"] != 0 for record in recovered):
        errors.append("complete read contains a record outside partition zero")
    if not workload["complete_read"]:
        errors.append("complete read gate failed")
    if errors:
        raise AssertionError("durability contract violated: " + "; ".join(errors))


def check_cluster_recovered(results):
    require_completed(results)
    recovery = results["recovery"]
    after = results["topic"]["after"]
    expected = results["topic"]["expected_assignment"]
    workload = results["workload"]
    recovered_counts = Counter(record["op_id"] for record in workload["recovered"])
    errors = []
    if not recovery["all_services_active"]:
        errors.append("not all services are active")
    expected_restarted = set(results["intervention"]["target_nodes"])
    restarted_readiness = recovery["restarted_broker_readiness"]
    if set(restarted_readiness) != expected_restarted:
        errors.append("restarted broker readiness set=" + str(sorted(restarted_readiness)))
    for name, readiness in restarted_readiness.items():
        if not all(
            readiness.get(field) is True
            for field in ["service_active", "listeners_ready", "client_api_ready"]
        ):
            errors.append(name + " did not become fully ready=" + str(readiness))
        suffix = int(name.removeprefix("kafka")) + 1
        listener_port = 9092 if results["configuration"]["client_plane"] == "shared" else 9095
        expected_endpoint = (
            f"192.168.{results['configuration']['client_vlan']}.{suffix}:{listener_port}"
        )
        if readiness.get("client_endpoint") != expected_endpoint:
            errors.append(name + " recovery endpoint=" + str(readiness.get("client_endpoint")))
    if after["replicas"] != expected or sorted(after["isr"]) != sorted(expected):
        errors.append("topic did not recover=" + str(after))
    quorum_samples = [
        recovery["metadata_quorum_before"],
        recovery["metadata_quorum_pre_intervention"],
        recovery["metadata_quorum_after"],
    ]
    if any(not sample for sample in quorum_samples):
        errors.append("metadata quorum evidence is missing")
    elif any(metadata_quorum_voter_ids(sample) != {1, 2, 3, 4, 5} for sample in quorum_samples):
        errors.append("metadata quorum does not contain the five frozen voters")
    post = workload["post_recovery"]
    if (
        len(post) != 1
        or post[0]["outcome"] != "confirmed"
        or recovered_counts[post[0]["op_id"]] != 1
    ):
        errors.append("post-recovery marker=" + str(post))
    if not workload["complete_read"]:
        errors.append("complete read did not finish")
    if errors:
        raise AssertionError("cluster recovery failed: " + "; ".join(errors))
