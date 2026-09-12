# NixOS test-driver machine objects are injected into the composed script.
# ruff: noqa: F821
# json comes from the runner preamble; re and the topology, parsing and
# sampling helpers (BROKERS, RACKS, CLIENT_VLAN, KILLED_STATUS, link_address,
# links_present, parse_cut, parse_topic_description, parse_quorum_status,
# parse_jmx_properties, sample_phase, sample_counters, describe_offset_line)
# come from the inlined oracle setup.
import os
import shlex
import tempfile
import time
import traceback
import uuid
from typing import Any, cast


class PreconditionFailure(Exception):
    pass


class InconclusiveExecution(Exception):
    pass


NODES = {
    "racka1": racka1,
    "racka2": racka2,
    "rackb1": rackb1,
    "rackb2": rackb2,
    "rackc1": rackc1,
    "rackc2": rackc2,
}
CLIENT_PORT = 9095
BIN = "/run/current-system/sw/bin/"
WORKLOAD = BIN + "kafka-rack-links-workload"
CENTRAL_SAMPLER = BIN + "kafka-rack-links-central-sampler"
JMX_SAMPLER = BIN + "kafka-rack-links-jmx-sampler"
SAMPLER_UNIT = "kafka-rack-links-sampler"
ADMIN_CONFIG = "/etc/topotestix-admin.properties"
# Every admin tool call is killed after this long; the samplers use the same bound.
CALL_TIMEOUT_SECONDS = 12
SAMPLE_PERIOD_SECONDS = 10
BASELINE_COUNT = 100
# Long enough for the leader to drop an unreachable follower from the ISR
# (replica.lag.time.max.ms is 30 s) before the first baseline record expires.
BASELINE_TIMEOUT_MS = 60000
STREAM_INTERVAL_MS = 1000
STREAM_TIMEOUT_MS = 5000
LEAD_SECONDS = 10
CUT_WINDOW_SECONDS = 60
TAIL_SECONDS = 30
FORMATION_TIMEOUT_SECONDS = 120
RECOVERY_TIMEOUT_SECONDS = 180
LOG_PATTERNS = {
    "prevote_transitions": "Completed transition to ProspectiveState",
    "candidate_transitions": "Completed transition to CandidateState",
    "leader_transitions": "Completed transition to Leader",
    "fenced_records": "fenced=1,",
}

run_id = uuid.uuid4().hex
topic = "topotestix-rack-links-" + run_id[:12]
result = cast(dict[str, Any], {
    "schema_version": 2,
    "run_id": run_id,
    "classification": "harness_failure",
    "error": None,
    "configuration": {
        "cut": None,
        "cut_vlans": [],
        "placement": None,
        "replicas": [],
        "replication_factor": 3,
        "min_isr": 2,
        "baseline_count": BASELINE_COUNT,
        "baseline_timeout_ms": BASELINE_TIMEOUT_MS,
        "stream_interval_ms": STREAM_INTERVAL_MS,
        "stream_timeout_ms": STREAM_TIMEOUT_MS,
        "lead_seconds": LEAD_SECONDS,
        "cut_window_seconds": CUT_WINDOW_SECONDS,
        "tail_seconds": TAIL_SECONDS,
    },
    "versions": {},
    "topology": {
        "brokers": {},
        "links_present": [],
        "unfenced_at_start": [],
        "bootstrap_servers": [],
    },
    "network": {
        "nics": {},
        "cut_nics": [],
        "stream_started_wall_ns": None,
        "cut_started_wall_ns": None,
        "cut_restored_wall_ns": None,
        "stream_finished_wall_ns": None,
        "cut_offset_s": None,
        "restore_offset_s": None,
    },
    "quorum_before": None,
    "topic": {"name": topic, "pre_cut": None, "after": None},
    "samples": {"central": [], "nodes": {}},
    "sampling": {
        "period_s": SAMPLE_PERIOD_SECONDS,
        "call_timeout_s": CALL_TIMEOUT_SECONDS,
        "counters": {},
    },
    "workload": {
        "baseline": [],
        "stream": [],
        "stream_status": None,
        "recovered": [],
        "complete_read": False,
        "end_offset": None,
    },
    "log_digest": {},
    "artifact_errors": [],
    "started_wall_ns": time.time_ns(),
})


def bootstrap():
    return ",".join(result["topology"]["bootstrap_servers"])


def shell_words(values):
    return " ".join(shlex.quote(str(value)) for value in values)


def admin(tool, arguments):
    return (
        f"timeout -s KILL {CALL_TIMEOUT_SECONDS} {tool} --command-config {ADMIN_CONFIG}"
        f" --bootstrap-server {shlex.quote(bootstrap())} {arguments} 2>&1"
    )


def read_json_lines(machine, path):
    # Copy through the shared directory: large outputs are not reliable over
    # the serial console.
    if machine.execute("test -s " + shlex.quote(path))[0] != 0:
        return []
    machine.copy_from_machine(path)
    with open(machine.out_dir / os.path.basename(path), encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def describe_topic():
    status, output = client1.execute(
        admin("kafka-topics.sh", "--describe --topic " + shlex.quote(topic)), timeout=30
    )
    if status != 0:
        raise RuntimeError(output[-1500:])
    return parse_topic_description(output)


def wait_for_topic(accept, timeout, failure):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            state = describe_topic()
            if accept(state):
                return state
            last = state
        except Exception as exception:
            last = {"error": str(exception)[-500:]}
        time.sleep(1)
    raise failure("topic did not reach the expected state; last=" + repr(last))


def quorum_status():
    status, output = client1.execute(
        admin("kafka-metadata-quorum.sh", "describe --status"), timeout=30
    )
    if status != 0:
        return {"status": status, "error": output[-500:]}
    try:
        return {"status": 0, **parse_quorum_status(output)}
    except ValueError as exception:
        return {"status": 0, "error": str(exception)}


def unfenced_brokers():
    # Metadata responses list only unfenced brokers.
    _, output = client1.execute(admin("kafka-broker-api-versions.sh", ""), timeout=30)
    return sorted({int(value) for value in re.findall(r"\(id: (\d+) rack:", output)})


def nic_map(machine):
    output = machine.send_monitor_command("info network")
    nics = {}
    for nic, mac in re.findall(
        r"^\s*(\S+): index=\d+,type=nic,model=[^,]+,macaddr=([0-9a-fA-F:]+)",
        output,
        flags=re.MULTILINE,
    ):
        # The test framework encodes the VLAN in the fifth MAC byte.
        nics[str(int(mac.split(":")[4], 16))] = nic
    return nics


def set_links(state):
    for entry in result["network"]["cut_nics"]:
        NODES[entry["node"]].send_monitor_command(f"set_link {entry['nic']} {state}")


def ping_peers(name, addresses):
    script = "; ".join(
        f"ping -c 1 -W 1 {shlex.quote(address)} >/dev/null 2>&1"
        f" && echo {peer}=up || echo {peer}=down"
        for peer, address in addresses.items()
        if peer != name
    )
    output = NODES[name].succeed(script)
    return {
        peer: state == "up"
        for peer, state in re.findall(r"^(\w+)=(up|down)$", output, flags=re.MULTILINE)
    }


def record_versions():
    # The monitor echoes the typed command with terminal escapes; keep the version.
    qemu = racka1.send_monitor_command("info version")
    qemu_version = re.search(r"\b(\d+\.\d+\.\d+)\b", qemu)
    result["versions"] = {
        "kafka": client1.succeed("kafka-topics.sh --version 2>/dev/null").strip().splitlines()[-1],
        "java": racka1.succeed("java -version 2>&1").strip(),
        "kafka_package": client1.succeed("cat /etc/topotestix-kafka-package").strip(),
        "nixpkgs": client1.succeed("cat /etc/topotestix-nixpkgs-version").strip(),
        "qemu": qemu_version.group(1) if qemu_version else qemu.strip()[-200:],
    }


def sampler_machines():
    return [("central", client1)] + list(NODES.items())


def sampler_files(name):
    return f"/tmp/samples-{name}.jsonl", f"/tmp/samples-{name}.stop"


def start_samplers():
    out, stop = sampler_files("central")
    client1.succeed(
        f"systemd-run --unit={SAMPLER_UNIT} "
        + shell_words([CENTRAL_SAMPLER, out, stop, bootstrap(), topic, SAMPLE_PERIOD_SECONDS])
    )
    for name, machine in NODES.items():
        out, stop = sampler_files(name)
        machine.succeed(
            f"systemd-run --unit={SAMPLER_UNIT} "
            + shell_words([JMX_SAMPLER, out, stop, topic, SAMPLE_PERIOD_SECONDS])
        )


def stop_samplers():
    for name, machine in sampler_machines():
        machine.succeed("touch " + sampler_files(name)[1])
    for _, machine in sampler_machines():
        try:
            machine.wait_until_fails(
                f"systemctl is-active --quiet {SAMPLER_UNIT}", timeout=3 * CALL_TIMEOUT_SECONDS
            )
        except Exception:
            machine.execute(f"systemctl stop {SAMPLER_UNIT}")


def sample_timing(record, phases):
    return {
        "phase": sample_phase(record["started_wall_ns"], phases),
        "t_s": round(
            (record["started_wall_ns"] - result["network"]["stream_started_wall_ns"]) / 1e9, 1
        ),
        "duration_s": round((record["finished_wall_ns"] - record["started_wall_ns"]) / 1e9, 1),
    }


def central_sample(record, phases):
    calls = record["calls"]
    sample = cast(dict[str, Any], sample_timing(record, phases))
    sample["calls"] = {name: call["status"] for name, call in calls.items()}
    errors = {}
    for name, parser in [
        ("topic", parse_topic_description),
        ("quorum", parse_quorum_status),
        ("replication", parse_quorum_replication),
    ]:
        sample[name] = None
        if calls[name]["status"] != 0:
            errors[name] = calls[name]["output"][-300:]
            continue
        try:
            sample[name] = parser(calls[name]["output"])
        except ValueError as exception:
            errors[name] = str(exception)[-300:]
    sample["errors"] = errors
    sample["successful"] = not errors
    sample["killed"] = any(call["status"] == KILLED_STATUS for call in calls.values())
    return sample


def node_sample(record, phases):
    sample = cast(dict[str, Any], sample_timing(record, phases))
    metrics = parse_jmx_properties(record["output"]) if record["status"] == 0 else {}
    sample["status"] = record["status"]
    sample["metrics"] = metrics or None
    sample["error"] = None if metrics else record["output"][-300:]
    sample["successful"] = bool(metrics)
    sample["killed"] = record["status"] == KILLED_STATUS
    return sample


def collect_samples():
    network = result["network"]
    phases = {
        "lead": (network["stream_started_wall_ns"], network["cut_started_wall_ns"]),
        "cut": (network["cut_started_wall_ns"], network["cut_restored_wall_ns"]),
        "tail": (network["cut_restored_wall_ns"], network["stream_finished_wall_ns"]),
    }
    counters = result["sampling"]["counters"]
    for name, machine in sampler_machines():
        records = read_json_lines(machine, sampler_files(name)[0])
        if name == "central":
            samples = [central_sample(record, phases) for record in records]
            result["samples"]["central"] = samples
        else:
            samples = [node_sample(record, phases) for record in records]
            result["samples"]["nodes"][name] = samples
        counters[name] = sample_counters(samples, phases, SAMPLE_PERIOD_SECONDS)


def log_digest(machine):
    journal = "journalctl --no-pager --unit apache-kafka.service"
    digest = cast(dict[str, Any], {
        key: int(
            machine.succeed(f"{journal} | grep -cF {shlex.quote(pattern)} || true").strip() or 0
        )
        for key, pattern in LOG_PATTERNS.items()
    })
    digest["topic_truncations"] = machine.succeed(
        f"{journal} | grep -F {shlex.quote(topic)} | grep -F Truncat"
        " | sed -E 's/^.*\\] (INFO|WARN) //' | cut -c1-240 | tail -n 20 || true"
    ).strip().splitlines()
    return digest


def persist_result():
    for name, machine in NODES.items():
        log_path = f"/tmp/{name}-apache-kafka.log"
        try:
            result["log_digest"][name] = log_digest(machine)
            machine.succeed(
                "journalctl --no-pager --unit apache-kafka.service > " + shlex.quote(log_path)
            )
            machine.copy_from_machine(log_path)
        except Exception as exception:
            result["artifact_errors"].append({"artifact": log_path, "error": str(exception)})
    result["finished_wall_ns"] = time.time_ns()
    # The payload exceeds the kernel's per-argument limit, so it travels through
    # the shared directory instead of the shell command line.
    with tempfile.TemporaryDirectory() as host_dir:
        host_path = os.path.join(host_dir, "kafka-rack-links-result.json")
        with open(host_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
        client1.copy_from_host(host_path, "/tmp/kafka-rack-links-result.json")
    client1.copy_from_machine("/tmp/kafka-rack-links-result.json")


links_cut = False
samplers_running = False
samples_collected = False
try:
    start_all()

    # Not named "vlans": the test driver already defines that global.
    broker_vlans = {}
    suffixes = {}
    for name, machine in NODES.items():
        machine.wait_for_unit("multi-user.target", timeout=240)
        addresses = re.findall(
            r"\binet\s+192\.168\.(\d+)\.(\d+)/",
            machine.succeed("ip -4 -o address show scope global"),
        )
        broker_vlans[name] = sorted(int(vlan) for vlan, _ in addresses)
        suffixes[name] = int(addresses[0][1])
    result["topology"]["links_present"] = links_present(broker_vlans)
    client1.wait_for_unit("multi-user.target", timeout=240)
    record_versions()

    for name, machine in NODES.items():
        link_addresses = {
            peer: link_address(name, peer, broker_vlans, suffixes) for peer in NODES
        }
        hosts = ["127.0.0.1 localhost", f"{link_addresses[name]} {name}"] + [
            f"{address} {peer}-link" for peer, address in link_addresses.items()
        ]
        machine.succeed("printf '%s\\n' " + shell_words(hosts) + " > /run/topotestix-link-hosts")
        result["network"]["nics"][name] = nic_map(machine)
        result["topology"]["brokers"][name] = {
            "broker_id": BROKERS[name],
            "rack": RACKS[name],
            "vlans": broker_vlans[name],
            "address_suffix": suffixes[name],
            "link_addresses": link_addresses,
            "hosts_file": machine.succeed("cat /run/topotestix-link-hosts"),
            "peer_ping": ping_peers(name, link_addresses),
        }
    for machine in NODES.values():
        machine.succeed("systemctl start --no-block apache-kafka.service")

    cut = client1.succeed("cat /etc/topotestix-kafka-cut").strip()
    placement = json.loads(client1.succeed("cat /etc/topotestix-kafka-placement.json"))
    cut_vlans = parse_cut(cut)
    result["configuration"]["cut"] = cut
    result["configuration"]["cut_vlans"] = cut_vlans
    result["configuration"]["placement"] = placement["profile"]
    result["configuration"]["replicas"] = placement["replicas"]
    result["topology"]["bootstrap_servers"] = [
        f"192.168.{CLIENT_VLAN}.{suffixes[name]}:{CLIENT_PORT}" for name in NODES
    ]

    formation_deadline = time.monotonic() + FORMATION_TIMEOUT_SECONDS
    unfenced = []
    while time.monotonic() < formation_deadline:
        unfenced = unfenced_brokers()
        if unfenced == sorted(BROKERS.values()):
            break
        time.sleep(2)
    result["topology"]["unfenced_at_start"] = unfenced
    for name, machine in NODES.items():
        result["topology"]["brokers"][name]["service_active_at_start"] = (
            machine.execute("systemctl is-active --quiet apache-kafka.service")[0] == 0
        )
    result["quorum_before"] = quorum_status()
    if "leader_id" not in result["quorum_before"] or not unfenced:
        raise PreconditionFailure(
            "cluster did not form under this topology: unfenced="
            + str(unfenced)
            + "; quorum="
            + str(result["quorum_before"])
        )

    replicas = placement["replicas"]
    status, output = client1.execute(
        admin(
            "kafka-topics.sh",
            "--create --topic "
            + shlex.quote(topic)
            + " --replica-assignment "
            + ":".join(str(replica) for replica in replicas)
            + " --config min.insync.replicas=2",
        ),
        timeout=60,
    )
    if status != 0:
        raise PreconditionFailure("topic creation rejected: " + output[-1500:])
    wait_for_topic(lambda state: state["leader"] in replicas, 60, PreconditionFailure)

    status, output = client1.execute(
        shell_words([
            WORKLOAD,
            "produce",
            bootstrap(),
            topic,
            "/tmp/baseline.jsonl",
            f"{run_id}/baseline",
            BASELINE_COUNT,
            BASELINE_TIMEOUT_MS,
        ]),
        timeout=BASELINE_TIMEOUT_MS // 1000 + 90,
    )
    result["workload"]["baseline"] = read_json_lines(client1, "/tmp/baseline.jsonl")
    if status != 0 or len(result["workload"]["baseline"]) != BASELINE_COUNT:
        raise PreconditionFailure("baseline was not fully confirmed: " + output[-1500:])
    result["topic"]["pre_cut"] = describe_topic()

    for vlan in cut_vlans:
        for name in NODES:
            if vlan in broker_vlans[name]:
                result["network"]["cut_nics"].append(
                    {"node": name, "vlan": vlan, "nic": result["network"]["nics"][name][str(vlan)]}
                )

    start_samplers()
    samplers_running = True
    stream_seconds = LEAD_SECONDS + CUT_WINDOW_SECONDS + TAIL_SECONDS
    stream_command = shell_words([
        WORKLOAD,
        "stream",
        bootstrap(),
        topic,
        "/tmp/stream.jsonl",
        f"{run_id}/stream",
        stream_seconds * 1000,
        STREAM_INTERVAL_MS,
        STREAM_TIMEOUT_MS,
    ])
    client1.succeed(
        "systemd-run --unit=kafka-rack-links-stream /bin/sh -c "
        + shlex.quote(stream_command + "; echo $? > /tmp/stream.status")
    )
    stream_started = time.monotonic()
    result["network"]["stream_started_wall_ns"] = time.time_ns()

    # Links are cut and restored on schedule; the samplers run inside the VMs
    # and cannot delay either step.
    time.sleep(max(0.0, stream_started + LEAD_SECONDS - time.monotonic()))
    result["network"]["cut_started_wall_ns"] = time.time_ns()
    result["network"]["cut_offset_s"] = round(time.monotonic() - stream_started, 1)
    links_cut = True
    set_links("off")
    cut_started = time.monotonic()
    time.sleep(max(0.0, cut_started + CUT_WINDOW_SECONDS - time.monotonic()))
    set_links("on")
    links_cut = False
    result["network"]["cut_restored_wall_ns"] = time.time_ns()
    result["network"]["restore_offset_s"] = round(time.monotonic() - stream_started, 1)

    stream_deadline = stream_started + stream_seconds + STREAM_TIMEOUT_MS / 1000 + 60
    while client1.execute("test -f /tmp/stream.status")[0] != 0:
        if time.monotonic() > stream_deadline:
            raise InconclusiveExecution("stream workload did not finish")
        time.sleep(1)
    result["network"]["stream_finished_wall_ns"] = time.time_ns()
    stop_samplers()
    samplers_running = False
    collect_samples()
    samples_collected = True

    result["workload"]["stream_status"] = int(client1.succeed("cat /tmp/stream.status").strip())
    result["workload"]["stream"] = read_json_lines(client1, "/tmp/stream.jsonl")
    if result["workload"]["stream_status"] != 0:
        raise InconclusiveExecution(
            "stream workload exited with status " + str(result["workload"]["stream_status"])
        )

    pre_cut_isr = set(result["topic"]["pre_cut"]["isr"])
    result["topic"]["after"] = wait_for_topic(
        lambda state: state["leader"] in state["replicas"] and pre_cut_isr <= set(state["isr"]),
        RECOVERY_TIMEOUT_SECONDS,
        InconclusiveExecution,
    )

    end_offset = describe_offset_line(
        topic,
        client1.succeed(
            admin("kafka-get-offsets.sh", "--topic " + shlex.quote(topic) + " --time -1")
        ),
    )
    if end_offset is None:
        raise InconclusiveExecution("cannot establish the end offset")
    result["workload"]["end_offset"] = end_offset
    status, output = client1.execute(
        shell_words(
            [WORKLOAD, "consume", bootstrap(), topic, "/tmp/recovered.jsonl", end_offset, 60000]
        ),
        timeout=90,
    )
    result["workload"]["recovered"] = read_json_lines(client1, "/tmp/recovered.jsonl")
    result["workload"]["complete_read"] = status == 0
    if status != 0:
        raise InconclusiveExecution("complete read did not reach the end offset: " + output[-1000:])
    result["classification"] = "completed"
except PreconditionFailure as exception:
    result["classification"] = "precondition_failure"
    result["error"] = str(exception)
except InconclusiveExecution as exception:
    result["classification"] = "inconclusive"
    result["error"] = str(exception)
except Exception:
    result["classification"] = "harness_failure"
    result["error"] = traceback.format_exc()
finally:
    # A persistence failure must not abort the script: the appended properties
    # then fail on the missing payload and report.json is still written.
    try:
        if links_cut:
            set_links("on")
        if samplers_running:
            stop_samplers()
        if not samples_collected and result["network"]["stream_started_wall_ns"]:
            collect_samples()
        persist_result()
    except Exception:
        print("kafka-rack-links result payload was not persisted:\n" + traceback.format_exc())
