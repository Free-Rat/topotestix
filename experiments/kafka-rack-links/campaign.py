"""Kafka rack-link campaign planner, runner and summarizer.

    nix develop -c python3 experiments/kafka-rack-links/campaign.py plan \
        --out experiments/kafka-rack-links/<campaign> --seeds 41-120
    nix develop -c python3 experiments/kafka-rack-links/campaign.py run \
        --out experiments/kafka-rack-links/<campaign> --seeds 41-120 --repetitions 3 --jobs 2
    nix develop -c python3 experiments/kafka-rack-links/campaign.py control \
        --out experiments/kafka-rack-links/<campaign> --seeds 57 --repetitions 3
    nix develop -c python3 experiments/kafka-rack-links/campaign.py summarize \
        --out experiments/kafka-rack-links/<campaign>
    nix develop -c python3 experiments/kafka-rack-links/campaign.py manifest \
        --out experiments/kafka-rack-links/<campaign>

`plan` resolves every seed's cell offline with the fuzzer's choice function
(no VM, no outcome) and predicts cluster formation. `run` executes every
(seed, repetition) as a fresh VM run; each seed resolves its own rack links
(topology seed S) and its cut and placement (client-role config seed S+1),
and nothing is overridden. `control` runs a seed with the cut forced to
"none"; it is the only forced choice the protocol allows. Units start in
repetition-major order, at most --jobs at a time, and a unit starts next to a
running one only when the host has enough available memory. The ledger is
append-only; `run` and `control` skip units that already have an entry, and
refuse to start while the code that shapes a run differs from the committed
revision (--allow-dirty for development runs). Each ledger entry records the
revision it ran on.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RACK_NODES = {"rack-a": "racka1", "rack-b": "rackb1", "rack-c": "rackc1"}
RACK_VLANS = {"rack-a": 31, "rack-b": 32, "rack-c": 33}
LINKS = {10: ("rack-a", "rack-b"), 11: ("rack-a", "rack-c"), 12: ("rack-b", "rack-c")}
CLIENT_VLAN = 20
BROKER_RACKS = {1: "rack-a", 2: "rack-a", 3: "rack-b", 4: "rack-b", 5: "rack-c", 6: "rack-c"}
# Mirrors targets/kafka-rack-links/topology.nix (link VLANs only) and config.nix.
RACK_OPTIONS = {
    "rack-a": (".rackaVlans", [[10, 11], [10], [11]]),
    "rack-b": (".rackbVlans", [[10, 12], [10], [12]]),
    "rack-c": (".rackcVlans", [[11, 12], [11], [12]]),
}
CUT_PATH = ".environment.etc.topotestix-kafka-cut.text"
CUTS = ["none", "10", "11", "12", "10,11", "10,12", "11,12", "10,11,12"]
PLACEMENT_PATH = ".environment.etc.topotestix-kafka-placement.json.text"
PLACEMENTS = ["spread", "concentrated"]
PLACEMENT_REPLICAS = {"spread": [1, 3, 5], "concentrated": [1, 2, 3]}
GRAPH_CLASSES = {0: "all isolated", 1: "one link", 2: "path", 3: "triangle"}
GATES = [
    "kafka-rack-links-execution-completed",
    "kafka-rack-links-materialized",
    "kafka-rack-links-cut-accurate",
    "kafka-rack-links-runtime-versions-pinned",
]
DURABILITY = "kafka-rack-links-confirmed-records-recovered-exactly-once"
RECOVERY = "kafka-rack-links-cluster-recovers"
CONTRACTS = {RECOVERY: "recovery", DURABILITY: "durability"}
VERDICTS = {"pass", "contract_violation"}
# The payload schema the gates and contracts above are defined for.
SCHEMA_VERSION = 3
# Code that shapes a run; a campaign runs only on a committed revision of it.
SOURCE_PATHS = [
    "targets/kafka-rack-links",
    "targets/default.nix",
    "experiments/kafka-rack-links/campaign.py",
    "lib",
    "topotestix",
    "flake.nix",
    "flake.lock",
]
# A unit starts next to a running one only above this much available memory.
MIN_AVAILABLE_KIB = 12 * 1024 * 1024


# ---------------------------------------------------------------------------
# Offline resolution and formation prediction


def to_int(key):
    """Mirror of lib/combinators.nix toInt: fold the SHA-256 hex digest."""
    value = 0
    for character in hashlib.sha256(key.encode()).hexdigest():
        value = (value * 256 + ord(character)) % 1000000000
    return value


def choice_index(seed, path, count):
    return to_int(str(seed) + path) % count


def parse_cut(value):
    return [] if value == "none" else sorted(int(part) for part in value.split(","))


def links_present(rack_links):
    return [
        vlan
        for vlan, (left, right) in LINKS.items()
        if vlan in rack_links[left] and vlan in rack_links[right]
    ]


def neighbours(rack, links):
    return {
        other
        for vlan in links
        for left, right in [LINKS[vlan]]
        if rack in (left, right)
        for other in [right if rack == left else left]
    }


def predict_formation(links, placement):
    """certain / election / impossible: can every rack holding a replica reach the
    controller leader? A leader is a voter that reaches another voter (2 of 3)."""
    needed = {BROKER_RACKS[broker] for broker in PLACEMENT_REPLICAS[placement]}
    leaders = [rack for rack in RACK_NODES if neighbours(rack, links)]
    reachable = [
        all(rack == leader or rack in neighbours(leader, links) for rack in needed)
        for leader in leaders
    ]
    if reachable and all(reachable):
        return "certain"
    if any(reachable):
        return "election"
    return "impossible"


def resolve_cell(seed):
    rack_links = {
        rack: options[choice_index(seed, path, len(options))]
        for rack, (path, options) in RACK_OPTIONS.items()
    }
    links = links_present(rack_links)
    cut = CUTS[choice_index(seed + 1, CUT_PATH, len(CUTS))]
    placement = PLACEMENTS[choice_index(seed + 1, PLACEMENT_PATH, len(PLACEMENTS))]
    remaining = sorted(set(links) - set(parse_cut(cut)))
    return {
        "seed": seed,
        "rack_links": rack_links,
        "links_present": links,
        "cut": cut,
        "placement": placement,
        "formation": predict_formation(links, placement),
        "links_during_cut": remaining,
        "graph_class": GRAPH_CLASSES[len(remaining)],
        "cut_removes_link": bool(set(links) & set(parse_cut(cut))),
    }


def parse_seeds(value):
    seeds = []
    for part in value.split(","):
        if "-" in part:
            first, last = part.split("-")
            seeds.extend(range(int(first), int(last) + 1))
        else:
            seeds.append(int(part))
    return seeds


def cmd_plan(args):
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    rows = [resolve_cell(seed) for seed in parse_seeds(args.seeds)]
    with open(os.path.join(out_dir, "plan.json"), "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2, sort_keys=True)
        handle.write("\n")
    formation = Counter(row["formation"] for row in rows)
    formable = [row for row in rows if row["formation"] != "impossible"]
    lines = [
        f"Seed scan for seeds {args.seeds}: resolved offline with the fuzzer's choice"
        " function; no run outcome is used.",
        "",
        "| Seed | Links a / b / c | Links present | Cut | Placement | Formation |"
        " Links during cut | Graph during cut | Cut removes a link |",
        "|---:|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {seed} | {links} | {present} | {cut} | {placement} | {formation} | {during} |"
            " {graph} | {removes} |".format(
                seed=row["seed"],
                links=" / ".join(
                    ",".join(str(vlan) for vlan in row["rack_links"][rack]) for rack in RACK_NODES
                ),
                present=",".join(str(vlan) for vlan in row["links_present"]) or "none",
                cut=row["cut"],
                placement=row["placement"],
                formation=row["formation"],
                during=",".join(str(vlan) for vlan in row["links_during_cut"]) or "none",
                graph=row["graph_class"],
                removes="yes" if row["cut_removes_link"] else "no",
            )
        )
    lines += [
        "",
        "Formation: " + ", ".join(f"{name} {count}" for name, count in sorted(formation.items())),
        "Formable seeds by graph during cut: "
        + ", ".join(
            f"{name} {count}"
            for name, count in sorted(Counter(row["graph_class"] for row in formable).items())
        ),
        f"Formable seeds whose cut removes a link: "
        f"{sum(row['cut_removes_link'] for row in formable)} of {len(formable)}",
    ]
    table = "\n".join(lines) + "\n"
    with open(os.path.join(out_dir, "plan.md"), "w", encoding="utf-8") as handle:
        handle.write(table)
    print(table)
    return 0


# ---------------------------------------------------------------------------
# Execution


def units(seeds, repetitions, control=False):
    for repetition in range(1, repetitions + 1):
        for seed in seeds:
            yield {"seed": seed, "repetition": repetition, "control": control}


def unit_key(unit):
    kind = "control" if unit.get("control") else "rep"
    return f"seed-{unit['seed']}-{kind}-{unit['repetition']}"


def entry_key(entry):
    return entry.get("key") or unit_key(entry)


def read_ledger(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def append_ledger(path, entry):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def mem_available_kib(meminfo=None):
    if meminfo is None:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            meminfo = handle.read()
    match = re.search(r"^MemAvailable:\s+(\d+) kB$", meminfo, flags=re.MULTILINE)
    if not match:
        raise ValueError("MemAvailable missing from /proc/meminfo")
    return int(match.group(1))


def memory_allows_start(running, available_kib, threshold_kib=MIN_AVAILABLE_KIB):
    return running == 0 or available_kib >= threshold_kib


class MemoryLog(threading.Thread):
    """Append the host's available memory to a JSONL file every few seconds."""

    def __init__(self, path, period=5.0):
        super().__init__(daemon=True)
        self.path = path
        self.period = period
        self.stopped = threading.Event()

    def run(self):
        while not self.stopped.wait(self.period):
            record = {
                "at": datetime.now(timezone.utc).isoformat(),
                "mem_available_kib": mem_available_kib(),
            }
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")

    def stop(self):
        self.stopped.set()
        self.join()


def run_command(unit, out_dir, campaign):
    key = unit_key(unit)
    command = [
        sys.executable,
        "-c",
        "import sys; from topotestix.cli import main; sys.exit(main())",
        "orchestrator",
        "run",
        "kafka-rack-links",
        "--seed",
        str(unit["seed"]),
        "--name",
        f"kafka-rack-links-{key}",
        "--repetition-token",
        f"{campaign}-{key}",
        "--output-dir",
        os.path.join(out_dir, "runs"),
    ]
    if unit.get("control"):
        command += ["--config-choices", json.dumps({"client": {CUT_PATH: CUTS.index("none")}})]
    return command


def source_state():
    """The committed revision and any uncommitted change to the code that shapes a run."""

    def git(*arguments):
        return subprocess.run(
            ["git", *arguments], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
        ).stdout

    return {
        "commit": git("rev-parse", "HEAD").strip(),
        "changed": git(
            "status", "--porcelain", "--untracked-files=all", "--", *SOURCE_PATHS
        ).splitlines(),
    }


def run_unit(unit, out_dir, campaign, jobs, available_kib, source):
    key = unit_key(unit)
    command = run_command(unit, out_dir, campaign)
    log_path = os.path.join(out_dir, "logs", key + ".log")
    started = datetime.now(timezone.utc).isoformat()
    started_monotonic = time.monotonic()
    with open(log_path, "w", encoding="utf-8") as log:
        completed = subprocess.run(
            command, cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT, check=False
        )
    with open(log_path, encoding="utf-8", errors="replace") as log:
        match = re.search(r"Run dir: (\S+)", log.read())
    return {
        **unit,
        "key": key,
        "command": command,
        "jobs": jobs,
        "source": {"commit": source["commit"], "dirty": bool(source["changed"])},
        "mem_available_kib_at_start": available_kib,
        "started": started,
        "finished": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.monotonic() - started_monotonic, 1),
        "exit_status": completed.returncode,
        "run_dir": os.path.relpath(match.group(1), out_dir) if match else None,
        "log": os.path.relpath(log_path, out_dir),
    }


def execute_units(planned, out_dir, campaign, jobs, source):
    """Run units at most `jobs` at a time; only this thread writes the ledger."""
    ledger_path = os.path.join(out_dir, "ledger.jsonl")
    memory_log = MemoryLog(os.path.join(out_dir, "host-memory.jsonl"))
    memory_log.start()
    pending = list(planned)
    running = {}
    started = 0
    try:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            while pending or running:
                while pending and len(running) < jobs:
                    available = mem_available_kib()
                    if not memory_allows_start(len(running), available):
                        break
                    unit = pending.pop(0)
                    started += 1
                    print(
                        f"[{started}/{len(planned)}] {unit_key(unit)}"
                        f" (MemAvailable {available // 1024} MiB)",
                        flush=True,
                    )
                    future = pool.submit(run_unit, unit, out_dir, campaign, jobs, available, source)
                    running[future] = unit
                done, _ = wait(list(running), timeout=10, return_when=FIRST_COMPLETED)
                for future in done:
                    running.pop(future)
                    entry = future.result()
                    append_ledger(ledger_path, entry)
                    print(
                        f"    {entry['key']} exit={entry['exit_status']}"
                        f" {entry['duration_seconds']}s run_dir={entry['run_dir']}",
                        flush=True,
                    )
    finally:
        memory_log.stop()
    return 0


def prepare(out_dir):
    out_dir = os.path.abspath(out_dir)
    os.makedirs(os.path.join(out_dir, "logs"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "runs"), exist_ok=True)
    done = {entry_key(entry) for entry in read_ledger(os.path.join(out_dir, "ledger.jsonl"))}
    return out_dir, done


def execute_command(args, control):
    source = source_state()
    if source["changed"] and not args.allow_dirty:
        print(
            "uncommitted changes to code that shapes a run (commit them, or pass"
            " --allow-dirty for a development run):\n  " + "\n  ".join(source["changed"]),
            file=sys.stderr,
        )
        return 2
    out_dir, done = prepare(args.out)
    campaign = args.campaign or os.path.basename(out_dir)
    planned = [
        unit
        for unit in units(parse_seeds(args.seeds), args.repetitions, control=control)
        if unit_key(unit) not in done
    ]
    return execute_units(planned, out_dir, campaign, args.jobs, source)


def cmd_run(args):
    return execute_command(args, control=False)


def cmd_control(args):
    return execute_command(args, control=True)


# ---------------------------------------------------------------------------
# Classification


def load_json(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def resolved_cell(resolved):
    node_vlans = {
        rack: resolved["nodeConfigs"][node]["virtualisation"]["vlans"]
        for rack, node in RACK_NODES.items()
    }
    etc = resolved["roleFuzz"]["client"]["result"]["environment"]["etc"]
    return {
        "rack_links": {
            rack: sorted(set(vlans) - {CLIENT_VLAN, RACK_VLANS[rack]})
            for rack, vlans in node_vlans.items()
        },
        "cut": etc["topotestix-kafka-cut"]["text"],
        "placement": json.loads(etc["topotestix-kafka-placement.json"]["text"])["profile"],
        "node_vlans": {
            node: resolved["nodeConfigs"][node]["virtualisation"]["vlans"]
            for node in resolved["nodeConfigs"]
            if node != "client1"
        },
    }


def recovery_kinds(payload):
    """Mirror of oracle.recovery_failures."""
    before = payload["topic"]["pre_cut"]
    after = payload["topic"].get("after") or {}
    workload = payload["workload"]
    kinds = []
    if after.get("leader") not in after.get("replicas", []) or not set(before["isr"]) <= set(
        after.get("isr", [])
    ):
        kinds.append("not_recovered")
    if workload.get("end_offset") is None or not workload.get("complete_read"):
        kinds.append("unreadable")
    return kinds


def durability_kinds(payload):
    """Durability violation kinds; the contract can only be judged on a complete read."""
    workload = payload["workload"]
    if not workload.get("complete_read"):
        return []
    produced = workload["baseline"] + workload["stream"]
    produced_ids = {event["op_id"] for event in produced}
    confirmed = {event["op_id"] for event in produced if event["outcome"] == "confirmed"}
    recovered = Counter(record["op_id"] for record in workload["recovered"])
    kinds = []
    if confirmed - set(recovered):
        kinds.append("missing")
    if any(count > 1 for count in recovered.values()):
        kinds.append("duplicated")
    if set(recovered) - produced_ids:
        kinds.append("unknown")
    return kinds


def jmx_values(metrics, suffix):
    return [value for key, value in (metrics or {}).items() if key.endswith(suffix)]


def observations(payload):
    network = payload["network"]
    started = network["cut_started_wall_ns"]
    restored = network["cut_restored_wall_ns"]
    phases = {"before": Counter(), "during": Counter(), "after": Counter()}
    for event in payload["workload"]["stream"]:
        at = event["started_wall_ns"]
        phase = (
            "before" if at < started else "during" if restored is None or at < restored else "after"
        )
        phases[phase][event["outcome"]] += 1
    samples = payload.get("samples") or {}
    central = samples.get("central", []) if isinstance(samples, dict) else samples
    nodes = samples.get("nodes", {}) if isinstance(samples, dict) else {}
    cut_topics = [
        sample["topic"] for sample in central if sample["phase"] == "cut" and sample.get("topic")
    ]
    isr_sizes = [len(topic["isr"]) for topic in cut_topics]
    epochs = sorted(
        {
            sample["quorum"]["leader_epoch"]
            for sample in central
            if (sample.get("quorum") or {}).get("leader_epoch") is not None
        }
    )
    node_leaders = sorted(
        {
            int(float(value))
            for node_samples in nodes.values()
            for sample in node_samples
            if sample["phase"] == "cut"
            for value in jmx_values(sample.get("metrics"), "type=raft-metrics:current-leader")
        }
    )
    counters = (payload.get("sampling") or {}).get("counters") or {}
    completeness = {
        phase: {
            field: sum((counters.get(node) or {}).get(phase, {}).get(field, 0) for node in counters)
            for field in ["planned", "executed", "successful"]
        }
        for phase in ["lead", "cut", "tail"]
    }
    digest = payload.get("log_digest") or {}
    return {
        "stream": {phase: dict(counts) for phase, counts in phases.items()},
        "isr_during_cut": [min(isr_sizes), max(isr_sizes)] if isr_sizes else None,
        "partition_leaders_during_cut": sorted({topic["leader"] for topic in cut_topics}),
        "controller_epochs": epochs,
        "controller_leaders_seen_by_nodes_during_cut": node_leaders,
        "prevote_transitions": sum(item.get("prevote_transitions", 0) for item in digest.values()),
        "candidate_transitions": sum(
            item.get("candidate_transitions", 0) for item in digest.values()
        ),
        "topic_truncation_lines": sum(
            len(item.get("topic_truncations", [])) for item in digest.values()
        ),
        "unfenced_at_start": payload["topology"]["unfenced_at_start"],
        "isr_pre_cut": (payload["topic"].get("pre_cut") or {}).get("isr"),
        "recovery_waited_s": (payload.get("recovery") or {}).get("waited_s"),
        "cut_seconds": round((restored - started) / 1e9, 1) if started and restored else None,
        "sampling": completeness if counters else None,
    }


def classify(entry, out_dir):
    run_dir = os.path.join(out_dir, entry["run_dir"]) if entry.get("run_dir") else None
    resolved = load_json(run_dir and os.path.join(run_dir, "resolved.json"))
    payload = load_json(run_dir and os.path.join(run_dir, "kafka-rack-links-result.json"))
    report = load_json(run_dir and os.path.join(run_dir, "report.json")) or []
    checks = {item["name"]: item["status"] for item in report}
    predicted = resolve_cell(entry["seed"])
    cell = resolved_cell(resolved) if resolved else None
    row = {
        "key": entry_key(entry),
        "seed": entry["seed"],
        "repetition": entry.get("repetition", 1),
        "control": bool(entry.get("control")),
        "duration_seconds": entry["duration_seconds"],
        "run_dir": entry.get("run_dir"),
        "checks": checks,
        "cell": cell,
        "prediction": predicted,
        "resolution_matches_plan": None
        if cell is None or entry.get("control")
        else (
            cell["rack_links"] == predicted["rack_links"]
            and cell["cut"] == predicted["cut"]
            and cell["placement"] == predicted["placement"]
        ),
        "formed": None,
        "signature": None,
        "violated_contracts": [],
        "source": entry.get("source"),
    }
    if payload is None:
        row["outcome"] = "infrastructure_or_harness_failure"
        row["detail"] = "no kafka-rack-links-result.json (exit " + str(entry["exit_status"]) + ")"
        return row
    if payload.get("schema_version") != SCHEMA_VERSION:
        row["outcome"] = "harness_failure"
        row["detail"] = (
            f"payload schema_version {payload.get('schema_version')}; the gates and contracts"
            f" are defined for schema_version {SCHEMA_VERSION}"
        )
        return row
    row["formed"] = payload["classification"] != "precondition_failure"
    if payload["classification"] != "completed":
        row["outcome"] = payload["classification"]
        row["detail"] = (payload["error"] or "")[-600:]
        if payload["network"]["cut_started_wall_ns"] and payload["workload"]["stream"]:
            row["observations"] = observations(payload)
        return row
    materialized = {
        name: broker["vlans"] for name, broker in payload["topology"]["brokers"].items()
    }
    if cell is None or materialized != cell["node_vlans"]:
        row["outcome"] = "harness_failure"
        row["detail"] = "materialized VLANs differ from resolved.json: " + str(materialized)
        return row
    failed_gates = [name for name in GATES if checks.get(name) != "passed"]
    if failed_gates:
        row["outcome"] = "harness_failure"
        row["detail"] = "failed gates: " + ", ".join(failed_gates)
        return row
    row["observations"] = observations(payload)
    recovery = recovery_kinds(payload)
    # Without a complete read the durability contract cannot be judged; the
    # recovery contract already reports the unreadable partition.
    violated = [
        label
        for name, label in CONTRACTS.items()
        if checks.get(name) != "passed" and not (name == DURABILITY and "unreadable" in recovery)
    ]
    if not violated:
        row["outcome"] = "pass"
    else:
        row["outcome"] = "contract_violation"
        row["violated_contracts"] = violated
        links = payload["topology"]["links_present"]
        row["signature"] = {
            "links_during_cut": sorted(set(links) - set(payload["configuration"]["cut_vlans"])),
            "placement": payload["configuration"]["placement"],
            "kinds": recovery + durability_kinds(payload),
        }
    return row


# ---------------------------------------------------------------------------
# Aggregation (protocol decisions D2, D3 and D6)


def prediction_consistent(formation, formed):
    if formed is None or formation == "election":
        return True
    return formed == (formation == "certain")


def seed_summaries(rows):
    by_seed = defaultdict(list)
    for row in rows:
        if not row["control"]:
            by_seed[row["seed"]].append(row)
    summaries = []
    for seed, executions in sorted(by_seed.items()):
        predicted = resolve_cell(seed)
        summaries.append(
            {
                "seed": seed,
                "executions": len(executions),
                "outcomes": dict(Counter(row["outcome"] for row in executions)),
                "verdict_executions": sum(row["outcome"] in VERDICTS for row in executions),
                "formation_prediction": predicted["formation"],
                "formed_executions": sum(bool(row["formed"]) for row in executions),
                "prediction_consistent": all(
                    prediction_consistent(predicted["formation"], row["formed"])
                    for row in executions
                ),
                "resolution_matches_plan": all(
                    row["resolution_matches_plan"] is not False for row in executions
                ),
                "graph_class": predicted["graph_class"],
                "cut_removes_link": predicted["cut_removes_link"],
            }
        )
    return summaries


def evaluate_d2(summaries, rows):
    verdict = [item for item in summaries if item["verdict_executions"]]
    classes = sorted({item["graph_class"] for item in verdict})
    removes = [item["seed"] for item in verdict if item["cut_removes_link"]]
    nothing = [item["seed"] for item in verdict if not item["cut_removes_link"]]
    predictions = all(
        item["prediction_consistent"]
        for item in summaries
        if item["formation_prediction"] in ("certain", "impossible")
    )
    materialized = all(
        row["checks"].get("kafka-rack-links-materialized") == "passed"
        for row in rows
        if row["formed"] is not None and row["outcome"] != "precondition_failure"
    )
    return {
        "verdict_seeds": len(verdict),
        "graph_classes": classes,
        "cut_removes_link_seeds": removes,
        "cut_changes_nothing_seeds": nothing,
        "predictions_hold": predictions,
        "materialized_in_all_verdict_runs": materialized,
        "demonstration_minimum_met": len(verdict) >= 15
        and len(classes) >= 3
        and len(removes) >= 5
        and len(nothing) >= 3
        and predictions,
        "null_minimum_met": len(removes) >= 10,
    }


def source_summary(rows):
    """Which revisions the units ran on; campaign evidence needs one clean revision."""
    sources = [row.get("source") for row in rows]
    commits = sorted({source["commit"] for source in sources if source})
    dirty = sum(bool(source and source["dirty"]) for source in sources)
    unrecorded = sum(source is None for source in sources)
    return {
        "commits": commits,
        "dirty_units": dirty,
        "unrecorded_units": unrecorded,
        "single_clean_revision": bool(rows) and len(commits) == 1 and not dirty and not unrecorded,
    }


def signature_key(signature):
    return json.dumps(signature, sort_keys=True)


def evaluate_d3(rows):
    results = []
    violating = sorted(
        {
            row["seed"]
            for row in rows
            if not row["control"] and row["outcome"] == "contract_violation"
        }
    )
    for seed in violating:
        principal = [row for row in rows if row["seed"] == seed and not row["control"]]
        signatures = Counter(
            signature_key(row["signature"])
            for row in principal
            if row["outcome"] == "contract_violation"
        )
        best, count = signatures.most_common(1)[0]
        controls = [row for row in rows if row["seed"] == seed and row["control"]]
        controls_clear = len(controls) >= 3 and all(
            row["outcome"] in VERDICTS
            and not (
                row["outcome"] == "contract_violation" and signature_key(row["signature"]) == best
            )
            for row in controls
        )
        results.append(
            {
                "seed": seed,
                "signature": json.loads(best),
                "principal_executions_with_signature": count,
                "principal_executions": len(principal),
                "controls": [row["outcome"] for row in controls],
                "status": "confirmatory" if count >= 2 and controls_clear else "exploratory",
            }
        )
    return results


def min_available_mib(out_dir):
    path = os.path.join(out_dir, "host-memory.jsonl")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        values = [json.loads(line)["mem_available_kib"] for line in handle if line.strip()]
    return min(values) // 1024 if values else None


def write_manifest(out_dir):
    """SHA-256 of every run log kept outside git (sha256sum -c format, campaign-relative)."""
    lines = []
    for root, _, files in os.walk(os.path.join(out_dir, "runs")):
        for name in files:
            if not name.endswith(".log"):
                continue
            path = os.path.join(root, name)
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
            lines.append((os.path.relpath(path, out_dir), digest.hexdigest()))
    with open(os.path.join(out_dir, "logs-manifest.sha256"), "w", encoding="utf-8") as handle:
        handle.writelines(f"{digest}  {path}\n" for path, digest in sorted(lines))
    return len(lines)


def cmd_manifest(args):
    count = write_manifest(os.path.abspath(args.out))
    print(f"logs-manifest.sha256: {count} files")
    return 0


def stream_cell(counts):
    return "/".join(
        str(counts.get(outcome, 0)) for outcome in ["confirmed", "ambiguous", "failed_before_send"]
    )


def execution_line(row):
    cell = row["cell"] or row["prediction"]
    seen = row.get("observations")
    sampling = (seen or {}).get("sampling") or {}
    cut_sampling = sampling.get("cut")
    return (
        "| {key} | {links} | {cut} | {placement} | {outcome} | {before} | {during} | {after} |"
        " {isr} | {epochs} | {cut_s} | {sampled} | {duration} |".format(
            key=row["key"],
            links=" / ".join(
                ",".join(str(vlan) for vlan in cell["rack_links"][rack]) for rack in RACK_NODES
            ),
            cut=cell["cut"] + (" (forced)" if row["control"] else ""),
            placement=cell["placement"],
            outcome=row["outcome"]
            + (
                f" ({', '.join(row['violated_contracts'])})"
                if row.get("violated_contracts")
                else ""
            ),
            before=stream_cell(seen["stream"]["before"]) if seen else "-",
            during=stream_cell(seen["stream"]["during"]) if seen else "-",
            after=stream_cell(seen["stream"]["after"]) if seen else "-",
            isr="-".join(str(size) for size in seen["isr_during_cut"])
            if seen and seen["isr_during_cut"]
            else "-",
            epochs=",".join(str(epoch) for epoch in seen["controller_epochs"]) if seen else "-",
            cut_s=(seen or {}).get("cut_seconds") or "-",
            sampled="{successful}/{planned}".format(**cut_sampling) if cut_sampling else "-",
            duration=row["duration_seconds"],
        )
    )


def cmd_summarize(args):
    out_dir = os.path.abspath(args.out)
    rows = [
        classify(entry, out_dir) for entry in read_ledger(os.path.join(out_dir, "ledger.jsonl"))
    ]
    summaries = seed_summaries(rows)
    d2 = evaluate_d2(summaries, rows)
    d3 = evaluate_d3(rows)
    provenance = source_summary(rows)
    report = {
        "executions": rows,
        "seeds": summaries,
        "d2": d2,
        "d3": d3,
        "source": provenance,
        "min_mem_available_mib": min_available_mib(out_dir),
    }
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")

    lines = [
        "Stream columns count confirmed/ambiguous/failed-before-send writes by phase;"
        " 'Cut samples' counts successful/planned samples over all nodes during the cut.",
        "",
        "## Executions",
        "",
        "| Unit | Links a / b / c | Cut | Placement | Outcome | Stream before |"
        " Stream during cut | Stream after | ISR during cut | Controller epochs | Cut (s) |"
        " Cut samples | Duration (s) |",
        "|---|---|---|---|---|---|---|---|---|---|---:|---|---:|",
    ]
    lines += [execution_line(row) for row in rows]
    lines += [
        "",
        "## Seeds",
        "",
        "| Seed | Formation predicted | Formed | Outcomes | Graph during cut | Cut removes a link |"
        " Prediction holds | Resolution matches plan |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for item in summaries:
        lines.append(
            f"| {item['seed']} | {item['formation_prediction']} |"
            f" {item['formed_executions']}/{item['executions']} |"
            f" {', '.join(f'{name} {count}' for name, count in sorted(item['outcomes'].items()))} |"
            f" {item['graph_class']} | {'yes' if item['cut_removes_link'] else 'no'} |"
            f" {'yes' if item['prediction_consistent'] else 'NO'} |"
            f" {'yes' if item['resolution_matches_plan'] else 'NO'} |"
        )
    lines += [
        "",
        "## Decision checks",
        "",
        f"- D2 verdict seeds: {d2['verdict_seeds']} (minimum 15)",
        f"- D2 graph classes with a verdict: {', '.join(d2['graph_classes']) or 'none'}"
        " (minimum 3 of 4)",
        f"- D2 verdict seeds whose cut removes a link: {len(d2['cut_removes_link_seeds'])}"
        " (minimum 5; null conclusion needs 10)",
        f"- D2 verdict seeds whose cut changes nothing: {len(d2['cut_changes_nothing_seeds'])}"
        " (minimum 3)",
        f"- D6 predictions hold for every certain and impossible seed: "
        f"{'yes' if d2['predictions_hold'] else 'NO'}",
        f"- Gate 'materialized' passes in every run past formation: "
        f"{'yes' if d2['materialized_in_all_verdict_runs'] else 'NO'}",
        f"- Demonstration minimum met: {'yes' if d2['demonstration_minimum_met'] else 'no'};"
        f" null minimum met: {'yes' if d2['null_minimum_met'] else 'no'}",
        "- Contract violations (D3): "
        + (
            "; ".join(
                f"seed {item['seed']} {item['status']}"
                f" ({item['principal_executions_with_signature']}/{item['principal_executions']},"
                f" controls {item['controls'] or 'not run'})"
                for item in d3
            )
            or "none"
        ),
        "- Source revisions: "
        + (", ".join(provenance["commits"]) or "not recorded")
        + f"; units on uncommitted code: {provenance['dirty_units']};"
        f" units without a recorded revision: {provenance['unrecorded_units']};"
        f" single clean revision: {'yes' if provenance['single_clean_revision'] else 'NO'}",
        f"- Lowest host MemAvailable during the campaign: "
        f"{report['min_mem_available_mib'] if report['min_mem_available_mib'] is not None else '-'}"
        " MiB",
        "",
        "Outcomes: "
        + ", ".join(
            f"{name} {count}" for name, count in sorted(Counter(r["outcome"] for r in rows).items())
        ),
    ]
    table = "\n".join(lines) + "\n"
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as handle:
        handle.write(table)
    print(table)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--out", required=True)
    plan.add_argument("--seeds", required=True, help="Seed list, e.g. 41-120 or 1,5,9")
    for name in ["run", "control"]:
        command = sub.add_parser(name)
        command.add_argument("--out", required=True)
        command.add_argument("--seeds", required=True, help="Seed list, e.g. 41-120 or 1,5,9")
        command.add_argument("--repetitions", type=int, default=3 if name == "control" else 1)
        command.add_argument("--jobs", type=int, default=1)
        command.add_argument(
            "--campaign", default=None, help="Repetition-token prefix (default: out dir name)"
        )
        command.add_argument(
            "--allow-dirty",
            action="store_true",
            help="Run on uncommitted code (development only; recorded in the ledger)",
        )
    for name in ["summarize", "manifest"]:
        sub.add_parser(name).add_argument("--out", required=True)
    args = parser.parse_args()
    commands = {
        "plan": cmd_plan,
        "run": cmd_run,
        "control": cmd_control,
        "summarize": cmd_summarize,
        "manifest": cmd_manifest,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
