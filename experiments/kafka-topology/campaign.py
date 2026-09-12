"""Kafka topology-first campaign runner and summarizer.

    nix develop -c python3 experiments/kafka-topology/campaign.py run \
        --out experiments/kafka-topology/<campaign> --repetitions 1
    nix develop -c python3 experiments/kafka-topology/campaign.py summarize \
        --out experiments/kafka-topology/<campaign>

Each cell uses the lowest seed in 1..40 whose resolved topology (client VLAN,
seed S) and kafka-role config (placement, seed S+2) reach that cell; the
intervention group is forced through the config choice override, so every
group and repetition of a cell shares one seed. Runs execute sequentially in
interleaved block order (repetition, then cell, then group). The ledger is
append-only; `run` skips units that already have a finished ledger entry.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CELLS = {
    "T1": {"seed": 9, "client_plane": "shared", "placement": "spread"},
    "T2": {"seed": 3, "client_plane": "separated", "placement": "spread"},
    "T3": {"seed": 1, "client_plane": "shared", "placement": "concentrated"},
    "T4": {"seed": 2, "client_plane": "separated", "placement": "concentrated"},
}
# Index into targets/kafka-topology/config.nix intervention choices.
GROUPS = {"no-fault": 0, "leader-kill": 1, "rack-kill": 2}
INTERVENTION_PATH = ".environment.etc.topotestix-kafka-intervention.text"


def units(repetitions):
    for repetition in range(1, repetitions + 1):
        for cell in CELLS:
            for group in GROUPS:
                yield {"cell": cell, "group": group, "repetition": repetition}


def unit_key(unit):
    return f"{unit['cell']}-{unit['group']}-rep-{unit['repetition']}"


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


def run_unit(unit, out_dir, campaign):
    cell = CELLS[unit["cell"]]
    key = unit_key(unit)
    command = [
        sys.executable,
        "-c",
        "import sys; from topotestix.cli import main; sys.exit(main())",
        "orchestrator",
        "run",
        "kafka-topology",
        "--seed",
        str(cell["seed"]),
        "--config-choices",
        json.dumps({"kafka": {INTERVENTION_PATH: GROUPS[unit["group"]]}}),
        "--name",
        f"kafka-topology-{key}",
        "--repetition-token",
        f"{campaign}-{key}",
        "--output-dir",
        os.path.join(out_dir, "runs"),
    ]
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
        "seed": cell["seed"],
        "command": command,
        "started": started,
        "finished": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.monotonic() - started_monotonic, 1),
        "exit_status": completed.returncode,
        "run_dir": os.path.relpath(match.group(1), out_dir) if match else None,
        "log": os.path.relpath(log_path, out_dir),
    }


def cmd_run(args):
    out_dir = os.path.abspath(args.out)
    os.makedirs(os.path.join(out_dir, "logs"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "runs"), exist_ok=True)
    ledger_path = os.path.join(out_dir, "ledger.jsonl")
    campaign = args.campaign or os.path.basename(out_dir)
    done = {entry["key"] for entry in read_ledger(ledger_path)}
    planned = [unit for unit in units(args.repetitions) if unit_key(unit) not in done]
    for index, unit in enumerate(planned, start=1):
        print(f"[{index}/{len(planned)}] {unit_key(unit)}", flush=True)
        entry = run_unit(unit, out_dir, campaign)
        append_ledger(ledger_path, entry)
        print(
            f"    exit={entry['exit_status']} {entry['duration_seconds']}s"
            f" run_dir={entry['run_dir']}",
            flush=True,
        )
    return 0


def load_json(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def classify(entry, out_dir):
    run_dir = os.path.join(out_dir, entry["run_dir"]) if entry.get("run_dir") else None
    payload = load_json(run_dir and os.path.join(run_dir, "kafka-topology-result.json"))
    report = load_json(run_dir and os.path.join(run_dir, "report.json")) or []
    checks = {item["name"]: item["status"] for item in report}
    cell = CELLS[entry["cell"]]
    row = {
        "key": entry["key"],
        "cell": entry["cell"],
        "group": entry["group"],
        "repetition": entry["repetition"],
        "seed": entry["seed"],
        "duration_seconds": entry["duration_seconds"],
        "run_dir": entry.get("run_dir"),
        "checks": checks,
    }
    if payload is None:
        row["outcome"] = "infrastructure_or_harness_failure"
        row["detail"] = "no kafka-topology-result.json (exit " + str(entry["exit_status"]) + ")"
        return row
    configuration = payload["configuration"]
    row["resolved"] = {
        "client_plane": configuration["client_plane"],
        "placement": configuration["placement"],
        "intervention": configuration["intervention"],
    }
    expected = {
        "client_plane": cell["client_plane"],
        "placement": cell["placement"],
        "intervention": entry["group"],
    }
    probe = payload["workload"].get("probe") or {}
    row["probe"] = {
        "outcome": probe.get("outcome"),
        "exception_type": probe.get("exception_type"),
        "expected_confirmation": payload["oracle"].get("expected_probe_confirmation"),
    }
    row["topic"] = {
        stage: (
            {key: payload["topic"][stage][key] for key in ["leader", "replicas", "isr"]}
            if payload["topic"].get(stage)
            else None
        )
        for stage in ["before", "during", "after"]
    }
    if payload["classification"] != "completed":
        row["outcome"] = payload["classification"]
        row["detail"] = payload["error"]
        return row
    if row["resolved"] != expected:
        row["outcome"] = "harness_failure"
        row["detail"] = "materialized cell differs from the frozen cell: " + str(row["resolved"])
        return row
    gates = [
        "kafka-topology-execution-completed",
        "kafka-topology-materialized",
        "kafka-topology-intervention-accurate",
        "kafka-topology-runtime-versions-pinned",
        "kafka-topology-cluster-recovers",
    ]
    failed_gates = [name for name in gates if checks.get(name) != "passed"]
    if failed_gates:
        row["outcome"] = "harness_failure"
        row["detail"] = "failed gates: " + ", ".join(failed_gates)
        return row
    durability = checks.get("kafka-topology-prefault-acknowledged-records-recovered-exactly-once")
    row["outcome"] = "pass" if durability == "passed" else "contract_violation"
    row["probe_matches_oracle"] = (
        checks.get("kafka-topology-probe-confirmation-matches-oracle") == "passed"
    )
    return row


def cmd_summarize(args):
    out_dir = os.path.abspath(args.out)
    rows = [
        classify(entry, out_dir) for entry in read_ledger(os.path.join(out_dir, "ledger.jsonl"))
    ]
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2, sort_keys=True)
        handle.write("\n")
    lines = [
        "| Unit | Seed | Outcome | Probe | Probe = oracle | ISR during | Duration (s) |",
        "|---|---:|---|---|---|---|---:|",
    ]
    for row in rows:
        during = (row.get("topic") or {}).get("during")
        probe = row.get("probe") or {}
        lines.append(
            "| {key} | {seed} | {outcome} | {probe} | {match} | {isr} | {duration} |".format(
                key=row["key"],
                seed=row["seed"],
                outcome=row["outcome"],
                probe=(probe.get("outcome") or "-")
                + (
                    " (" + probe["exception_type"].rsplit(".", 1)[-1] + ")"
                    if probe.get("exception_type")
                    else ""
                ),
                match={True: "yes", False: "no"}.get(row.get("probe_matches_oracle"), "-"),
                isr=during["isr"] if during else "-",
                duration=row["duration_seconds"],
            )
        )
    table = "\n".join(lines) + "\n"
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as handle:
        handle.write(table)
    print(table)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--out", required=True)
    run.add_argument("--repetitions", type=int, default=1)
    run.add_argument(
        "--campaign", default=None, help="Repetition-token prefix (default: out dir name)"
    )
    summarize = sub.add_parser("summarize")
    summarize.add_argument("--out", required=True)
    args = parser.parse_args()
    return {"run": cmd_run, "summarize": cmd_summarize}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
