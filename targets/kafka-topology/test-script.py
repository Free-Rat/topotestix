# NixOS test-driver machine objects are injected into the composed script.
# ruff: noqa: F821
import base64
import json
import re
import shlex
import time
import traceback
import uuid


class PreconditionFailure(Exception):
    pass


class InconclusiveExecution(Exception):
    pass


NODES = {
    "kafka1": kafka1,
    "kafka2": kafka2,
    "kafka3": kafka3,
    "kafka4": kafka4,
    "kafka5": kafka5,
}
BROKER_IDS = {name: index for index, name in enumerate(NODES, start=1)}
BROKER_NAMES = {broker_id: name for name, broker_id in BROKER_IDS.items()}
RACKS = {
    "kafka1": "rack-a",
    "kafka2": "rack-a",
    "kafka3": "rack-b",
    "kafka4": "rack-b",
    "kafka5": "rack-c",
}
ADDRESS_SUFFIXES = {
    "kafka1": 2,
    "kafka2": 3,
    "kafka3": 4,
    "kafka4": 5,
    "kafka5": 6,
}
BASELINE_COUNT = 100
MIN_ISR = 2
MAX_KILL_INTERVAL_MS = 5000
BASELINE_TIMEOUT_MS = 30000
PROBE_TIMEOUT_MS = 5000
RECOVERY_TIMEOUT_SECONDS = 180
OBSERVATION_DELAY_SECONDS = 35

run_id = uuid.uuid4().hex
topic = "topotestix-topology-" + run_id[:12]
result = {
    "schema_version": 1,
    "run_id": run_id,
    "classification": "harness_failure",
    "error": None,
    "configuration": {
        "placement": None,
        "intervention": None,
        "client_plane": None,
        "client_vlan": None,
        "replication_factor": 3,
        "min_isr": MIN_ISR,
        "baseline_count": BASELINE_COUNT,
        "producer": {
            "acks": "all",
            "enable_idempotence": True,
            "max_in_flight_requests_per_connection": 5,
            "retries": 3,
            "baseline_timeout_ms": BASELINE_TIMEOUT_MS,
            "probe_timeout_ms": PROBE_TIMEOUT_MS,
            "observation_delay_seconds": OBSERVATION_DELAY_SECONDS,
        },
    },
    "versions": {},
    "topology": {
        "brokers": {},
        "client_addresses": [],
        "selected_route_status": None,
        "opposite_route_status": None,
        "bootstrap_servers": [],
        "placement_manifests": {},
        "intervention_manifests": {},
        "manifest_consistent": False,
        "listeners_ready": False,
    },
    "topic": {
        "name": topic,
        "expected_assignment": [],
        "initial": None,
        "before": None,
        "during": None,
        "after": None,
    },
    "intervention": {
        "target_nodes": [],
        "target_broker_ids": [],
        "observed_leader": None,
        "kill_timestamps_ns": [],
        "kill_completed_timestamps_ns": [],
        "kill_interval_ms": 0,
        "observation_window_started_ns": None,
        "observation_checkpoint_ns": None,
        "service_before": {},
        "service_after_kill": {},
        "service_after_recovery": {},
    },
    "workload": {
        "baseline": [],
        "baseline_ids": [],
        "probe": None,
        "post_recovery": [],
        "recovered": [],
        "complete_read": False,
        "start_offset": None,
        "end_offset": None,
    },
    "recovery": {
        "metadata_quorum_before": None,
        "metadata_quorum_pre_intervention": None,
        "metadata_quorum_after": None,
        "restarted_broker_readiness": {},
        "all_services_active": False,
    },
    "oracle": {
        "expected_probe_confirmation": None,
        "observed_probe_confirmation": None,
        "durability_scope": "100-confirmed-prefault-records",
    },
    "artifact_errors": [],
    "started_wall_ns": time.time_ns(),
}


def execute_checked(machine, command, timeout=90):
    status, output = machine.execute(command, timeout=timeout)
    if status != 0:
        raise RuntimeError(f"command failed with status {status}: {command}\n{output[-4000:]}")
    return output


def read_json_lines(machine, path):
    status, output = machine.execute(f"test -f {shlex.quote(path)} && cat {shlex.quote(path)}")
    if status != 0 or not output.strip():
        return []
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def run_producer(prefix, count, history_path, timeout_ms):
    command = " ".join(
        shlex.quote(value)
        for value in [
            "kafka-topology-workload",
            "produce",
            ",".join(result["topology"]["bootstrap_servers"]),
            topic,
            history_path,
            prefix,
            str(count),
            str(timeout_ms),
        ]
    )
    status, output = client1.execute(command, timeout=timeout_ms / 1000 + 20)
    return status, output, read_json_lines(client1, history_path)


def run_consumer(end_offset, history_path):
    command = " ".join(
        shlex.quote(value)
        for value in [
            "kafka-topology-workload",
            "consume",
            ",".join(result["topology"]["bootstrap_servers"]),
            topic,
            history_path,
            str(end_offset),
            "60000",
        ]
    )
    status, output = client1.execute(command, timeout=75)
    return status, output, read_json_lines(client1, history_path)


def parse_topic_description(output):
    partition_line = next(
        (line for line in output.splitlines() if re.search(r"\bPartition:\s*0\b", line)),
        None,
    )
    if partition_line is None:
        raise ValueError("partition zero is missing from topic description")
    leader_match = re.search(r"\bLeader:\s*(-?\d+)", partition_line)
    replicas_match = re.search(r"\bReplicas:\s*([0-9,]+)", partition_line)
    isr_match = re.search(r"\bIsr:\s*([0-9,]*)", partition_line)
    if not leader_match or not replicas_match or not isr_match:
        raise ValueError("cannot parse topic description: " + partition_line)
    return {
        "leader": int(leader_match.group(1)),
        "replicas": [int(value) for value in replicas_match.group(1).split(",")],
        "isr": [int(value) for value in isr_match.group(1).split(",") if value],
        "raw": output,
    }


def describe_topic():
    command = (
        "kafka-topics.sh --bootstrap-server "
        + shlex.quote(",".join(result["topology"]["bootstrap_servers"]))
        + " --describe --topic "
        + shlex.quote(topic)
    )
    status, output = client1.execute(command, timeout=20)
    if status != 0:
        raise RuntimeError(output[-4000:])
    return parse_topic_description(output)


def wait_for_topic_state(expected_replicas, expected_isr, timeout):
    deadline = time.monotonic() + timeout
    last_error = None
    last_state = None
    while time.monotonic() < deadline:
        try:
            last_state = describe_topic()
            if (
                last_state["replicas"] == expected_replicas
                and sorted(last_state["isr"]) == sorted(expected_isr)
                and last_state["leader"] in expected_isr
            ):
                return last_state
        except Exception as exception:
            last_error = str(exception)
        time.sleep(1)
    raise InconclusiveExecution(
        "topic did not reach expected state; last_state="
        + repr(last_state)
        + "; last_error="
        + repr(last_error)
    )


def service_snapshot(name):
    machine = NODES[name]
    return {
        "active": machine.execute("systemctl is-active --quiet apache-kafka.service")[0] == 0,
        "main_pid": int(
            machine.succeed(
                "systemctl show apache-kafka.service --property MainPID --value"
            ).strip()
        ),
        "restart": machine.succeed(
            "systemctl show apache-kafka.service --property Restart --value"
        ).strip(),
        "data_identity": machine.succeed(
            "stat --format='%d:%i' /var/lib/apache-kafka/logs"
        ).strip(),
        "control_group": machine.succeed(
            "systemctl show apache-kafka.service --property ControlGroup --value"
        ).strip(),
    }


def client_endpoint_reachable(name, client_vlan, listener_port):
    suffix = ADDRESS_SUFFIXES[name]
    status, _ = client1.execute(
        "timeout 2 bash -c "
        + shlex.quote(f"</dev/tcp/192.168.{client_vlan}.{suffix}/{listener_port}")
    )
    return status == 0


def wait_for_restarted_broker(name, client_vlan, listener_port):
    machine = NODES[name]
    suffix = ADDRESS_SUFFIXES[name]
    try:
        machine.wait_for_unit("apache-kafka.service", timeout=180)
        for address, port in [
            (f"192.168.10.{suffix}", 9092),
            (f"192.168.10.{suffix}", 9093),
            (f"192.168.10.{suffix}", 9094),
            (f"192.168.20.{suffix}", 9095),
        ]:
            machine.wait_until_succeeds(f"ss -ltn | grep -F '{address}:{port}'", timeout=120)
        client_endpoint = f"192.168.{client_vlan}.{suffix}:{listener_port}"
        client1.wait_until_succeeds(
            "kafka-broker-api-versions.sh --bootstrap-server "
            + shlex.quote(client_endpoint)
            + " >/dev/null 2>&1",
            timeout=120,
        )
    except Exception as exception:
        raise InconclusiveExecution(
            f"restarted broker {name} did not become API-ready: {exception}"
        ) from exception
    return {
        "service_active": True,
        "listeners_ready": True,
        "client_api_ready": True,
        "client_endpoint": client_endpoint,
    }


def metadata_quorum_status():
    command = (
        "kafka-metadata-quorum.sh --bootstrap-server "
        + shlex.quote(",".join(result["topology"]["bootstrap_servers"]))
        + " describe --status"
    )
    return execute_checked(client1, command, timeout=30)


def topic_offset(time_selector):
    output = execute_checked(
        client1,
        "kafka-get-offsets.sh --bootstrap-server "
        + shlex.quote(",".join(result["topology"]["bootstrap_servers"]))
        + " --topic "
        + shlex.quote(topic)
        + " --time "
        + shlex.quote(time_selector),
        timeout=30,
    )
    match = re.search(rf"^{re.escape(topic)}:0:(\d+)$", output, flags=re.MULTILINE)
    if not match:
        raise InconclusiveExecution(
            "cannot establish " + time_selector + " topic offset: " + output[-2000:]
        )
    return int(match.group(1))


def persist_result():
    for name, machine in NODES.items():
        log_path = f"/tmp/{name}-apache-kafka.log"
        try:
            machine.succeed(
                "journalctl --no-pager --unit apache-kafka.service > " + shlex.quote(log_path)
            )
            machine.copy_from_machine(log_path)
        except Exception as exception:
            result["artifact_errors"].append({"artifact": log_path, "error": str(exception)})

    for path in [
        "/tmp/kafka-api-versions",
        "/tmp/kafka-topology-baseline.jsonl",
        "/tmp/kafka-topology-probe.jsonl",
        "/tmp/kafka-topology-post-recovery.jsonl",
        "/tmp/kafka-topology-recovered.jsonl",
    ]:
        try:
            if client1.execute("test -f " + shlex.quote(path))[0] == 0:
                client1.copy_from_machine(path)
        except Exception as exception:
            result["artifact_errors"].append({"artifact": path, "error": str(exception)})

    result["finished_wall_ns"] = time.time_ns()
    encoded = base64.b64encode(json.dumps(result, indent=2, sort_keys=True).encode("utf-8")).decode(
        "ascii"
    )
    client1.succeed(
        "printf %s " + shlex.quote(encoded) + " | base64 -d > /tmp/kafka-topology-result.json"
    )
    client1.copy_from_machine("/tmp/kafka-topology-result.json")


try:
    start_all()

    for name, machine in NODES.items():
        machine.wait_for_unit("apache-kafka.service", timeout=180)
        suffix = ADDRESS_SUFFIXES[name]
        for address, port in [
            (f"192.168.10.{suffix}", 9092),
            (f"192.168.10.{suffix}", 9093),
            (f"192.168.10.{suffix}", 9094),
            (f"192.168.20.{suffix}", 9095),
        ]:
            machine.wait_until_succeeds(f"ss -ltn | grep -F '{address}:{port}'", timeout=120)

    placement_manifests = {
        name: json.loads(machine.succeed("cat /etc/topotestix-kafka-placement.json"))
        for name, machine in NODES.items()
    }
    intervention_manifests = {
        name: machine.succeed("cat /etc/topotestix-kafka-intervention").strip()
        for name, machine in NODES.items()
    }
    result["topology"]["placement_manifests"] = placement_manifests
    result["topology"]["intervention_manifests"] = intervention_manifests
    result["topology"]["manifest_consistent"] = (
        len({json.dumps(value, sort_keys=True) for value in placement_manifests.values()}) == 1
        and len(set(intervention_manifests.values())) == 1
    )
    if not result["topology"]["manifest_consistent"]:
        raise PreconditionFailure("Kafka role manifests differ between brokers")

    placement = placement_manifests["kafka1"]
    intervention = intervention_manifests["kafka1"]
    if placement.get("profile") not in {"spread", "concentrated"}:
        raise PreconditionFailure("unknown placement manifest: " + repr(placement))
    if intervention not in {"no-fault", "leader-kill", "rack-kill"}:
        raise PreconditionFailure("unknown intervention: " + intervention)
    result["configuration"]["placement"] = placement["profile"]
    result["configuration"]["intervention"] = intervention

    client_address_output = client1.succeed("ip -4 -o address show scope global")
    client_addresses = re.findall(r"\binet\s+([0-9.]+)/", client_address_output)
    result["topology"]["client_addresses"] = client_addresses
    if "192.168.10.1" in client_addresses and "192.168.20.1" not in client_addresses:
        client_vlan = 10
        client_plane = "shared"
        listener_port = 9092
        opposite_address = "192.168.20.2"
    elif "192.168.20.1" in client_addresses and "192.168.10.1" not in client_addresses:
        client_vlan = 20
        client_plane = "separated"
        listener_port = 9095
        opposite_address = "192.168.10.2"
    else:
        raise PreconditionFailure(
            "client must belong to exactly one experimental VLAN: " + repr(client_addresses)
        )
    result["configuration"]["client_vlan"] = client_vlan
    result["configuration"]["client_plane"] = client_plane

    bootstrap_servers = [
        f"192.168.{client_vlan}.{suffix}:{listener_port}" for suffix in ADDRESS_SUFFIXES.values()
    ]
    result["topology"]["bootstrap_servers"] = bootstrap_servers
    selected_status, _ = client1.execute("ip route get " + shlex.quote(f"192.168.{client_vlan}.2"))
    opposite_status, _ = client1.execute("ip route get " + shlex.quote(opposite_address))
    result["topology"]["selected_route_status"] = selected_status
    result["topology"]["opposite_route_status"] = opposite_status
    if selected_status != 0 or opposite_status == 0:
        raise PreconditionFailure(
            "client routing does not isolate the selected plane: selected_status="
            + str(selected_status)
            + "; opposite_status="
            + str(opposite_status)
        )

    client1.wait_until_succeeds(
        "kafka-broker-api-versions.sh --bootstrap-server "
        + shlex.quote(",".join(bootstrap_servers))
        + " >/tmp/kafka-api-versions 2>&1",
        timeout=180,
    )
    result["topology"]["listeners_ready"] = True

    result["topology"]["brokers"] = {
        name: json.loads(machine.succeed("cat /etc/topotestix-kafka-node.json"))
        for name, machine in NODES.items()
    }
    for name, broker in result["topology"]["brokers"].items():
        broker_id = broker["broker_id"]
        broker["runtime_configuration"] = execute_checked(
            client1,
            "kafka-configs.sh --bootstrap-server "
            + shlex.quote(",".join(bootstrap_servers))
            + " --entity-type brokers --entity-name "
            + str(broker_id)
            + " --describe --all",
            timeout=30,
        )
    result["versions"] = {
        "kafka": client1.succeed("kafka-topics.sh --version").strip(),
        "java": client1.succeed("java -version 2>&1 | sed -n '1p'").strip(),
        "kafka_package": client1.succeed("cat /etc/topotestix-kafka-package").strip(),
        "nixpkgs": client1.succeed("cat /etc/topotestix-nixpkgs-version").strip(),
        "kafka_store_path": client1.succeed("readlink -f $(command -v kafka-topics.sh)").strip(),
    }
    result["recovery"]["metadata_quorum_before"] = metadata_quorum_status()

    expected_assignment = [int(value) for value in placement["replicas"]]
    result["topic"]["expected_assignment"] = expected_assignment
    assignment_argument = ":".join(str(value) for value in expected_assignment)
    create_command = (
        "kafka-topics.sh --bootstrap-server "
        + shlex.quote(",".join(bootstrap_servers))
        + " --create --topic "
        + shlex.quote(topic)
        + " --replica-assignment "
        + shlex.quote(assignment_argument)
        + " --config min.insync.replicas=2"
        + " --config unclean.leader.election.enable=false"
        + " --config cleanup.policy=delete"
        + " --config retention.ms=86400000"
    )
    execute_checked(client1, create_command, timeout=60)
    initial = wait_for_topic_state(expected_assignment, expected_assignment, timeout=120)
    result["topic"]["initial"] = initial
    if initial["leader"] != 1:
        raise PreconditionFailure("preferred replica kafka1 is not the initial leader")

    baseline_status, baseline_output, baseline = run_producer(
        f"{run_id}/baseline",
        BASELINE_COUNT,
        "/tmp/kafka-topology-baseline.jsonl",
        BASELINE_TIMEOUT_MS,
    )
    result["workload"]["baseline"] = baseline
    result["workload"]["baseline_ids"] = [event["op_id"] for event in baseline]
    if (
        baseline_status != 0
        or len(baseline) != BASELINE_COUNT
        or any(event["outcome"] != "confirmed" for event in baseline)
    ):
        raise PreconditionFailure(
            "baseline was not fully confirmed: status="
            + str(baseline_status)
            + "; events="
            + str(len(baseline))
            + "; output="
            + baseline_output[-2000:]
        )

    before = wait_for_topic_state(expected_assignment, expected_assignment, timeout=60)
    result["topic"]["before"] = before
    if before["leader"] != 1:
        raise PreconditionFailure("kafka1 is not the leader at the pre-intervention checkpoint")
    result["recovery"]["metadata_quorum_pre_intervention"] = metadata_quorum_status()

    for name in NODES:
        snapshot = service_snapshot(name)
        snapshot["client_endpoint_reachable"] = client_endpoint_reachable(
            name, client_vlan, listener_port
        )
        result["intervention"]["service_before"][name] = snapshot

    leader = before["leader"]
    result["intervention"]["observed_leader"] = leader
    if intervention == "no-fault":
        target_nodes = []
    elif intervention == "leader-kill":
        if leader not in BROKER_NAMES:
            raise PreconditionFailure("observed leader is not a known broker: " + str(leader))
        target_nodes = [BROKER_NAMES[leader]]
    else:
        target_nodes = [name for name, rack in RACKS.items() if rack == placement["failed_rack"]]
    target_broker_ids = [BROKER_IDS[name] for name in target_nodes]
    result["intervention"]["target_nodes"] = target_nodes
    result["intervention"]["target_broker_ids"] = target_broker_ids

    kill_timestamps = []
    kill_completed_timestamps = []
    for name in target_nodes:
        kill_timestamps.append(time.monotonic_ns())
        NODES[name].succeed("systemctl kill --signal=SIGKILL --kill-who=all apache-kafka.service")
        kill_completed_timestamps.append(time.monotonic_ns())
    result["intervention"]["kill_timestamps_ns"] = kill_timestamps
    result["intervention"]["kill_completed_timestamps_ns"] = kill_completed_timestamps
    if len(kill_timestamps) > 1:
        result["intervention"]["kill_interval_ms"] = (
            kill_timestamps[-1] - kill_timestamps[0]
        ) / 1_000_000
    if result["intervention"]["kill_interval_ms"] > MAX_KILL_INTERVAL_MS:
        raise InconclusiveExecution("double-kill interval exceeded the fixed maximum")

    for name in target_nodes:
        NODES[name].wait_until_fails("systemctl is-active --quiet apache-kafka.service", timeout=30)

    result["intervention"]["observation_window_started_ns"] = time.monotonic_ns()
    time.sleep(OBSERVATION_DELAY_SECONDS)
    result["intervention"]["observation_checkpoint_ns"] = time.monotonic_ns()

    for name in NODES:
        snapshot = service_snapshot(name)
        snapshot["client_endpoint_reachable"] = client_endpoint_reachable(
            name, client_vlan, listener_port
        )
        result["intervention"]["service_after_kill"][name] = snapshot

    expected_during_isr = [
        broker_id for broker_id in expected_assignment if broker_id not in target_broker_ids
    ]
    during = wait_for_topic_state(expected_assignment, expected_during_isr, timeout=120)
    result["topic"]["during"] = during

    probe_status, probe_output, probe_events = run_producer(
        f"{run_id}/probe",
        1,
        "/tmp/kafka-topology-probe.jsonl",
        PROBE_TIMEOUT_MS,
    )
    if probe_status not in {0, 2} or len(probe_events) != 1:
        raise InconclusiveExecution(
            "probe did not produce one classifiable event: status="
            + str(probe_status)
            + "; events="
            + repr(probe_events)
            + "; output="
            + probe_output[-2000:]
        )
    probe = probe_events[0]
    result["workload"]["probe"] = probe
    expected_probe_confirmation = not (
        placement["profile"] == "concentrated" and intervention == "rack-kill"
    )
    result["oracle"]["expected_probe_confirmation"] = expected_probe_confirmation
    result["oracle"]["observed_probe_confirmation"] = probe["outcome"] == "confirmed"

    for name in target_nodes:
        machine = NODES[name]
        machine.succeed("systemctl reset-failed apache-kafka.service")
        machine.succeed("systemctl start apache-kafka.service")

    for name in target_nodes:
        result["recovery"]["restarted_broker_readiness"][name] = wait_for_restarted_broker(
            name, client_vlan, listener_port
        )

    after = wait_for_topic_state(
        expected_assignment, expected_assignment, timeout=RECOVERY_TIMEOUT_SECONDS
    )
    result["topic"]["after"] = after
    for name in NODES:
        result["intervention"]["service_after_recovery"][name] = service_snapshot(name)
    result["recovery"]["all_services_active"] = all(
        snapshot["active"] for snapshot in result["intervention"]["service_after_recovery"].values()
    )
    result["recovery"]["metadata_quorum_after"] = metadata_quorum_status()

    post_status, post_output, post_events = run_producer(
        f"{run_id}/post-recovery",
        1,
        "/tmp/kafka-topology-post-recovery.jsonl",
        BASELINE_TIMEOUT_MS,
    )
    result["workload"]["post_recovery"] = post_events
    if (
        post_status != 0
        or len(post_events) != 1
        or post_events[0]["outcome"] != "confirmed"
        or post_events[0]["offset"] is None
    ):
        raise InconclusiveExecution(
            "post-recovery marker was not confirmed: status="
            + str(post_status)
            + "; events="
            + repr(post_events)
            + "; output="
            + post_output[-2000:]
        )
    start_offset = topic_offset("earliest")
    end_offset = topic_offset("latest")
    result["workload"]["start_offset"] = start_offset
    result["workload"]["end_offset"] = end_offset

    consume_status, consume_output, recovered = run_consumer(
        end_offset, "/tmp/kafka-topology-recovered.jsonl"
    )
    result["workload"]["recovered"] = recovered
    result["workload"]["complete_read"] = consume_status == 0
    if consume_status != 0:
        raise InconclusiveExecution(
            "complete read did not reach the frozen end offset: status="
            + str(consume_status)
            + "; output="
            + consume_output[-2000:]
        )

    result["classification"] = "completed"

except PreconditionFailure as exception:
    result["classification"] = "precondition_failure"
    result["error"] = str(exception)
except InconclusiveExecution as exception:
    result["classification"] = "inconclusive"
    result["error"] = str(exception)
except Exception as exception:
    result["classification"] = "harness_failure"
    result["error"] = {
        "type": type(exception).__name__,
        "message": str(exception),
        "traceback": traceback.format_exc(),
    }
finally:
    persist_result()
