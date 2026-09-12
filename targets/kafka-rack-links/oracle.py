import re
from collections import Counter

BROKERS = {"racka1": 1, "racka2": 2, "rackb1": 3, "rackb2": 4, "rackc1": 5, "rackc2": 6}
RACKS = {
    "racka1": "rack-a",
    "racka2": "rack-a",
    "rackb1": "rack-b",
    "rackb2": "rack-b",
    "rackc1": "rack-c",
    "rackc2": "rack-c",
}
RACK_VLANS = {"rack-a": 31, "rack-b": 32, "rack-c": 33}
# Link VLAN -> the two racks it joins.
LINKS = {10: ("rack-a", "rack-b"), 11: ("rack-a", "rack-c"), 12: ("rack-b", "rack-c")}
CLIENT_VLAN = 20
# Peers without a shared VLAN resolve to a documentation address with no route.
UNREACHABLE_PREFIX = "192.0.2."


def parse_cut(value):
    if value == "none":
        return []
    vlans = sorted(int(part) for part in value.split(","))
    if len(set(vlans)) != len(vlans) or not set(vlans) <= set(LINKS):
        raise ValueError("unknown link cut: " + repr(value))
    return vlans


def rack_links(rack):
    return sorted(vlan for vlan, racks in LINKS.items() if rack in racks)


def link_address(node, peer, vlans, suffixes):
    """Address under which node reaches peer for controller and replication traffic."""
    if RACKS[node] == RACKS[peer]:
        return f"192.168.{RACK_VLANS[RACKS[peer]]}.{suffixes[peer]}"
    shared = sorted((set(vlans[node]) & set(vlans[peer])) - {CLIENT_VLAN})
    if not shared:
        return UNREACHABLE_PREFIX + str(suffixes[peer])
    return f"192.168.{shared[0]}.{suffixes[peer]}"


def links_present(vlans):
    return [
        vlan
        for vlan, racks in LINKS.items()
        if all(vlan in vlans[node] for node, rack in RACKS.items() if rack in racks)
    ]


def expected_cut_nics(cut_vlans, vlans):
    return sorted((node, vlan) for vlan in cut_vlans for node in BROKERS if vlan in vlans[node])


def require_completed(results):
    if results["classification"] != "completed":
        raise AssertionError(str(results["classification"]) + ": " + str(results["error"]))


def check_materialized(results):
    brokers = results["topology"]["brokers"]
    if sorted(brokers) != sorted(BROKERS):
        raise AssertionError("brokers=" + str(sorted(brokers)))
    vlans = {name: brokers[name]["vlans"] for name in BROKERS}
    suffixes = {name: brokers[name]["address_suffix"] for name in BROKERS}
    errors = []
    for name in BROKERS:
        rack = RACKS[name]
        own = set(vlans[name])
        links = own - {CLIENT_VLAN, RACK_VLANS[rack]}
        if CLIENT_VLAN not in own or RACK_VLANS[rack] not in own:
            errors.append(f"{name} lacks the client or rack VLAN: {sorted(own)}")
        if not links or not links <= set(rack_links(rack)):
            errors.append(
                f"{name} link VLANs {sorted(links)} are not a non-empty subset of "
                f"{rack_links(rack)}"
            )
        rack_peers = [peer for peer in BROKERS if RACKS[peer] == rack]
        if any(vlans[peer] != vlans[name] for peer in rack_peers):
            errors.append(f"{name} VLANs differ from its rack peers")
        hosts_lines = set(brokers[name]["hosts_file"].splitlines())
        for peer in BROKERS:
            expected = link_address(name, peer, vlans, suffixes)
            if brokers[name]["link_addresses"].get(peer) != expected:
                errors.append(
                    f"{name} resolves {peer} to "
                    f"{brokers[name]['link_addresses'].get(peer)}, expected {expected}"
                )
            if f"{expected} {peer}-link" not in hosts_lines:
                errors.append(f"{name} hosts file lacks '{expected} {peer}-link'")
            if peer != name:
                reachable = not expected.startswith(UNREACHABLE_PREFIX)
                if brokers[name]["peer_ping"].get(peer) != reachable:
                    errors.append(
                        f"{name} -> {peer} ping={brokers[name]['peer_ping'].get(peer)}, "
                        f"expected {reachable}"
                    )
    if results["topology"]["links_present"] != links_present(vlans):
        errors.append("links_present=" + str(results["topology"]["links_present"]))
    if errors:
        raise AssertionError("; ".join(errors))


def check_cut_accurate(results):
    network = results["network"]
    vlans = {name: results["topology"]["brokers"][name]["vlans"] for name in BROKERS}
    cut_vlans = parse_cut(results["configuration"]["cut"])
    errors = []
    if results["configuration"]["cut_vlans"] != cut_vlans:
        errors.append("cut_vlans=" + str(results["configuration"]["cut_vlans"]))
    recorded = sorted((entry["node"], entry["vlan"]) for entry in network["cut_nics"])
    expected = expected_cut_nics(cut_vlans, vlans)
    if recorded != expected:
        errors.append(f"cut NICs {recorded}, expected {expected}")
    for entry in network["cut_nics"]:
        if network["nics"][entry["node"]].get(str(entry["vlan"])) != entry["nic"]:
            errors.append(f"{entry['node']} NIC {entry['nic']} is not its VLAN {entry['vlan']} NIC")
    started = network["cut_started_wall_ns"]
    restored = network["cut_restored_wall_ns"]
    if started is None or restored is None or restored <= started:
        errors.append(f"cut window started={started} restored={restored}")
    if errors:
        raise AssertionError("; ".join(errors))


def check_confirmed_records_recovered_exactly_once(results):
    require_completed(results)
    workload = results["workload"]
    if not workload["complete_read"]:
        raise AssertionError("complete read did not reach the end offset")
    produced = workload["baseline"] + workload["stream"]
    produced_ids = Counter(event["op_id"] for event in produced)
    reused = sorted(op_id for op_id, count in produced_ids.items() if count > 1)
    if reused:
        raise AssertionError("operation IDs were produced more than once: " + str(reused[:10]))
    unconfirmed_baseline = [
        event["op_id"] for event in workload["baseline"] if event["outcome"] != "confirmed"
    ]
    if unconfirmed_baseline:
        raise AssertionError("baseline records not confirmed: " + str(unconfirmed_baseline[:10]))
    confirmed = {event["op_id"] for event in produced if event["outcome"] == "confirmed"}
    recovered = Counter(record["op_id"] for record in workload["recovered"])
    missing = sorted(confirmed - set(recovered))
    duplicated = sorted(op_id for op_id, count in recovered.items() if count > 1)
    unknown = sorted(set(recovered) - set(produced_ids))
    if missing or duplicated or unknown:
        raise AssertionError(
            f"missing={missing[:10]} ({len(missing)}); duplicated={duplicated[:10]} "
            f"({len(duplicated)}); unknown={unknown[:10]} ({len(unknown)})"
        )


def check_cluster_recovered(results):
    require_completed(results)
    before = results["topic"]["pre_cut"]
    after = results["topic"]["after"]
    if not after or after["leader"] not in after["replicas"]:
        raise AssertionError("no leader after recovery: " + str(after))
    if not set(before["isr"]) <= set(after["isr"]):
        raise AssertionError(f"ISR after recovery {after['isr']} lacks pre-cut ISR {before['isr']}")


def describe_offset_line(topic, output):
    match = re.search(rf"^{re.escape(topic)}:0:(\d+)$", output, flags=re.MULTILINE)
    return int(match.group(1)) if match else None


def check_runtime_versions(results):
    versions = results.get("versions") or {}
    errors = []
    if not re.match(r"4\.2\.0\b", versions.get("kafka") or ""):
        errors.append("kafka=" + repr(versions.get("kafka")))
    if not re.search(r'version "17[."]', versions.get("java") or ""):
        errors.append("java=" + repr(versions.get("java")))
    if errors:
        raise AssertionError("; ".join(errors))


def parse_topic_description(output):
    line = next(
        (line for line in output.splitlines() if re.search(r"\bPartition:\s*0\b", line)), None
    )
    if line is None:
        raise ValueError("partition zero is missing from topic description: " + output[-500:])
    leader = re.search(r"\bLeader:\s*(-?\d+)", line)
    replicas = re.search(r"\bReplicas:\s*([0-9,]+)", line)
    isr = re.search(r"\bIsr:\s*([0-9,]*)", line)
    elr = re.search(r"\bElr:\s*([0-9,]*)", line)
    if not leader or not replicas or not isr:
        raise ValueError("cannot parse topic description: " + line)
    return {
        "leader": int(leader.group(1)),
        "replicas": [int(value) for value in replicas.group(1).split(",")],
        "isr": [int(value) for value in isr.group(1).split(",") if value],
        "elr": [int(value) for value in elr.group(1).split(",") if value] if elr else [],
    }


def parse_quorum_status(output):
    fields = {
        key: re.search(rf"^{key}:\s*(-?\d+)", output, flags=re.MULTILINE)
        for key in ["LeaderId", "LeaderEpoch", "HighWatermark"]
    }
    if fields["LeaderId"] is None:
        raise ValueError("no LeaderId in quorum status: " + output[-500:])
    return {
        "leader_id": int(fields["LeaderId"].group(1)),
        "leader_epoch": int(fields["LeaderEpoch"].group(1)) if fields["LeaderEpoch"] else None,
        "high_watermark": (
            int(fields["HighWatermark"].group(1)) if fields["HighWatermark"] else None
        ),
    }


def parse_quorum_replication(output):
    """The controller leader's view of how far each voter and observer has fetched."""
    rows = [
        {
            "node": int(node),
            "log_end_offset": int(log_end_offset),
            "lag": int(lag),
            "last_fetch_ms": int(last_fetch),
            "last_caught_up_ms": int(last_caught_up),
            "status": role,
        }
        for node, log_end_offset, lag, last_fetch, last_caught_up, role in re.findall(
            r"^(\d+)\s+\S+\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(\w+)\s*$",
            output,
            flags=re.MULTILINE,
        )
    ]
    if not rows:
        raise ValueError("no replication rows in quorum description: " + output[-500:])
    return rows


def parse_jmx_properties(output):
    """kafka-jmx.sh --report-format properties: one 'object:attribute=value' line each."""
    metrics = {}
    for line in output.splitlines():
        key, separator, value = line.rpartition("=")
        if separator and ":" in key:
            metrics[key] = value.strip()
    return metrics


# Exit status of a sampler call killed by `timeout -s KILL`.
KILLED_STATUS = 137
SAMPLE_PHASES = ["lead", "cut", "tail"]


def sample_phase(at_ns, phases):
    for name in SAMPLE_PHASES:
        start, end = phases[name]
        if start is not None and end is not None and start <= at_ns < end:
            return name
    return "outside"


def sample_counters(samples, phases, period_s):
    """Planned, executed, successful and killed samples of one node per phase."""
    counters = {}
    for name in SAMPLE_PHASES:
        start, end = phases[name]
        planned = 0 if start is None or end is None else round((end - start) / (period_s * 1e9))
        in_phase = [sample for sample in samples if sample["phase"] == name]
        counters[name] = {
            "planned": planned,
            "executed": len(in_phase),
            "successful": sum(bool(sample["successful"]) for sample in in_phase),
            "killed": sum(bool(sample["killed"]) for sample in in_phase),
        }
    return counters
