#!/usr/bin/env python3
"""Build a June-schema summary for the 2026-08-24 kafka-cluster sweep rerun.

Reads per-run payloads (run.json, resolved.json, report.json) from the run
store for every seed of the named rerun sweep and emits:

  * kafka-cluster-sweep-rerun-20260824-summary.json  (same schema as
    kafka-cluster-sweep-1-50-fixed-20260613-summary.json)
  * kafka-cluster-sweep-rerun-20260824-summary.txt   (counts + CSV)

Usage:
  nix develop -c python3 experiments/kafka-cluster/rerun-sweep-summarize-20260824.py \
      --runs-dir .topotestix/runs --name kafka-cluster-sweep-1-50-rerun-20260824 \
      --seeds 1..50 --out-prefix experiments/kafka-cluster/kafka-cluster-sweep-rerun-20260824-summary
"""

import argparse
import csv
import json
import os


def parse_seeds(spec):
    out = []
    for part in spec.split(","):
        if ".." in part:
            lo, hi = part.split("..", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return out


def classify(report):
    """Return (status, category, failed_properties) from a report.json list."""
    failed = [e for e in report if e.get("status") == "failed"]
    failed_names = [e.get("name", "?") for e in failed]
    if not failed:
        return "pass", "pass", []
    text = "\n".join(e.get("message", "") for e in failed)
    # Order matters conceptually: the two exception classes are disjoint strings.
    if "RecordBatchTooLargeException" in text:
        cat = "log-segment-too-small"
    elif "RecordTooLargeException" in text:
        cat = "broker-message-max-too-small"
    elif "TimeoutException" in text:
        cat = "timeout"
    else:
        cat = "other-failure"
    return "fail", cat, failed_names


def summarize_run(run_dir):
    with open(os.path.join(run_dir, "run.json")) as f:
        meta = json.load(f)
    with open(os.path.join(run_dir, "resolved.json")) as f:
        resolved = json.load(f)
    report = []
    report_path = os.path.join(run_dir, "report.json")
    if os.path.exists(report_path):
        with open(report_path) as f:
            report = json.load(f)

    role_result = {}
    role_fuzz = resolved.get("roleFuzz", {})
    for _role, entry in role_fuzz.items():
        role_result = entry.get("result", {})
        break
    settings = role_result.get("services", {}).get("apache-kafka", {}).get("settings", {})
    virt = role_result.get("virtualisation", {})

    status, category, failed_props = classify(report)

    return {
        "autoCreate": bool(settings.get("auto.create.topics.enable", False)),
        "heap": role_result.get("services", {}).get("apache-kafka", {}).get("jvmOptions", []),
        "logSegmentBytes": settings.get("log.segment.bytes"),
        "memory": virt.get("memorySize"),
        "messageMax": settings.get("message.max.bytes"),
        # NB: the June 2026-06-13 summary's `minIsr` provably drew from
        # `min.insync.replicas` (verified 50/50 against rerun draws), so we
        # reproduce that mapping here for like-for-like comparison.
        "minIsr": settings.get("min.insync.replicas"),
        "transactionStateLogMinIsr": settings.get(
            "transaction.state.log.min.isr"
        ),
        "replicaFetchMax": settings.get("replica.fetch.max.bytes"),
        "rf": settings.get("default.replication.factor"),
        "runSeed": meta.get("seed"),
        "unclean": bool(settings.get("unclean.leader.election.enable", False)),
        "status": status,
        "category": category,
        "runDir": meta.get("runDir", run_dir),
        "failedProperties": failed_props,
        "gitHead": meta.get("gitHead"),
        "summaryCounts": meta.get("summary"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-dir", default=".topotestix/runs")
    ap.add_argument("--name", required=True)
    ap.add_argument("--seeds", default="1..50")
    ap.add_argument("--out-prefix", required=True)
    args = ap.parse_args()

    seeds = parse_seeds(args.seeds)
    by_seed = {}
    for entry in sorted(os.listdir(args.runs_dir)):
        run_json = os.path.join(args.runs_dir, entry, "run.json")
        if not os.path.exists(run_json):
            continue
        with open(run_json) as f:
            meta = json.load(f)
        if meta.get("name") != args.name or meta.get("target") != "kafka-cluster":
            continue
        seed = meta.get("seed")
        started = meta.get("startedAt", "")
        # keep the earliest-started run per seed (initial fuzz run of the sweep)
        if seed not in by_seed or started < by_seed[seed][0]:
            by_seed[seed] = (started, os.path.join(args.runs_dir, entry))

    rows = []
    missing = []
    for seed in seeds:
        if seed not in by_seed:
            missing.append(seed)
            continue
        rows.append(summarize_run(by_seed[seed][1]))

    with open(args.out_prefix + ".json", "w") as f:
        json.dump(rows, f, indent=2)
        f.write("\n")

    counts = {}
    for r in rows:
        counts[r["category"]] = counts.get(r["category"], 0) + 1

    lines = []
    lines.append("kafka-cluster sweep rerun 2026-08-24 (HEAD 8ff5f96f4a43d04f8bb6fdf305c911384adbcd0c)")
    lines.append(f"sweep name: {args.name}")
    lines.append(f"seeds summarized: {len(rows)} / {len(seeds)}")
    if missing:
        lines.append(f"MISSING seeds (no run dir found): {missing}")
    lines.append("")
    lines.append("category counts")
    for cat, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"{n} {cat}")
    passed = sum(1 for r in rows if r["status"] == "pass")
    failed = sum(1 for r in rows if r["status"] == "fail")
    lines.append("")
    lines.append(f"passed={passed} failed={failed} total={len(rows)}")

    flips_note = ""
    june_pass = {2, 3, 6, 21, 24, 25, 26, 27, 29, 30, 38, 39, 42}
    now_pass = {r["runSeed"] for r in rows if r["status"] == "pass"}
    gained = sorted(now_pass - june_pass)
    lost = sorted(june_pass - now_pass)
    lines.append(f"flips vs June: newly-passing={gained} newly-failing={lost}")

    lines.append("")
    lines.append("per-seed outcomes")
    for r in rows:
        lines.append(
            f"seed={r['runSeed']} status={r['status']} category={r['category']} "
            f"messageMax={r['messageMax']} logSegmentBytes={r['logSegmentBytes']} "
            f"failedProperties={'|'.join(r['failedProperties']) or '-'}"
        )

    lines.append("")
    lines.append("CSV")
    lines.append(
        "seed,status,category,messageMax,replicaFetchMax,logSegmentBytes,heap,memory,rf,minIsr"
    )
    buf = []
    for r in rows:
        buf.append(
            [
                r["runSeed"],
                r["status"],
                r["category"],
                r["messageMax"],
                r["replicaFetchMax"],
                r["logSegmentBytes"],
                "+".join(r["heap"]),
                r["memory"],
                r["rf"],
                r["minIsr"],
            ]
        )
    import io

    sio = io.StringIO()
    w = csv.writer(sio, lineterminator="\n")
    w.writerows(buf)
    lines.append(sio.getvalue().rstrip("\n"))
    lines.append("")
    lines.append(flips_note)

    with open(args.out_prefix + ".txt", "w") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")

    print("\n".join(lines[:14]))


if __name__ == "__main__":
    main()
