"""Tests for experiments/reproduce/verify.py — fake analysis-tree fixtures.

Asserted invariants:
  - claim verdicts match the fake artifacts (match / within-tolerance /
    mismatch / not-reproduced mix);
  - a missing artifact yields not-reproduced with a reason;
  - claims-matrix.csv is byte-identical across re-runs;
  - running against an empty analysis dir gives all 91 real claims a
    not-reproduced row.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.reproduce.verify import run as verify_run

REPO = Path(__file__).resolve().parent.parent
CLAIMS_CSV = REPO / "experiments" / "reproduce" / "claims.csv"

KAFKA_CHECK = "kafka-large-message-on-kafka1"
ETCD_V2_CHECK = "etcd-quota-write-burst-etcd1"

# Failing-seed split for the fake kafka sweep: 18 broker-max, 19 log-segment.
KAFKA_BROKER_SEEDS = {2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20}
KAFKA_LOG_SEEDS = {1, 9} | set(range(21, 38))

# Crosstab cells straight from the thesis table (claims k-04..k-21).
CROSSTAB = {
    (1, 1, 1): (0, 3, 0),
    (1, 1, 16): (0, 3, 0),
    (1, 2, 1): (0, 3, 0),
    (1, 2, 16): (0, 2, 0),
    (1, 4, 1): (0, 5, 0),
    (1, 4, 16): (0, 2, 0),
    (2, 1, 1): (0, 0, 4),
    (2, 1, 16): (2, 0, 0),
    (2, 2, 1): (0, 0, 4),
    (2, 2, 16): (4, 0, 0),
    (2, 4, 1): (0, 0, 3),
    (2, 4, 16): (2, 0, 0),
    (4, 1, 1): (0, 0, 3),
    (4, 1, 16): (1, 0, 0),
    (4, 2, 1): (0, 0, 2),
    (4, 2, 16): (3, 0, 0),
    (4, 4, 1): (0, 0, 3),
    (4, 4, 16): (1, 0, 0),
}

# Claim rows copied verbatim from experiments/reproduce/claims.csv.
SUBSET_CLAIMS = [
    (
        "k-01",
        "06-evaluation.typ:98 (@sec:evaluation-kafka sweep results)",
        "Kafka 50-seed sweep pass/fail split",
        "13 of 50 pass / 37 of 50 fail",
        "exact",
    ),
    (
        "k-02",
        "06-evaluation.typ:98 (@sec:evaluation-kafka)",
        "All 37 failures concentrated in single check kafka-large-message-on-kafka1 (other 10 checks already passed whenever reached)",  # noqa: E501
        "37 failures all in kafka-large-message-on-kafka1",
        "exact",
    ),
    (
        "k-03",
        "06-evaluation.typ:103-106 (@tab:kafka-classes)",
        "Kafka failure-class counts over 50 seeds",
        "message.max.bytes too small: 18 (RecordTooLargeException); "
        "log.segment.bytes too small: 19 (RecordBatchTooLargeException); Pass: 13",
        "exact",
    ),
    (
        "k-04",
        "06-evaluation.typ:118 (@tab:kafka-crosstab)",
        "Crosstab cell (message.max.bytes=1MiB,replica.fetch.max.bytes=1MiB,"
        "log.segment.bytes=1MiB): pass/broker-max/log-segment",
        "0/3/0",
        "exact",
    ),
    (
        "k-22",
        "06-evaluation.typ:140 (@sec:evaluation-kafka)",
        "Broker-max class occurs exactly when message.max.bytes=1MiB (independent of other size options)",  # noqa: E501
        "broker-max iff message.max.bytes=1MiB",
        "exact",
    ),
    (
        "k-23",
        "06-evaluation.typ:140 (@sec:evaluation-kafka)",
        "Log-segment class occurs exactly when log.segment.bytes=1MiB",
        "log-segment iff log.segment.bytes=1MiB",
        "exact",
    ),
    (
        "k-24",
        "06-evaluation.typ:146 (@sec:kafka-class1)",
        "Representative seed for RecordTooLargeException class",
        "seed 13",
        "exact",
    ),
    (
        "k-25",
        "06-evaluation.typ:153 (@sec:kafka-class1)",
        "Class-isolating minimized config kafka-cluster-min-message-max.nix validation: "
        "10 checks pass + 1 RecordTooLargeException failure",
        "10 pass / 1 fail",
        "exact",
    ),
    (
        "k-26",
        "06-evaluation.typ:157 (@sec:kafka-class2)",
        "Representative seed for RecordBatchTooLargeException class",
        "seed 9",
        "exact",
    ),
    (
        "k-28",
        "06-evaluation.typ:170 (@sec:kafka-shrink-limits)",
        "Unconstrained shrink of seed 9 collapses RecordBatchTooLargeException into "
        "RecordTooLargeException (failure-class not preserved)",
        "minimized seed-9 fails with RecordTooLargeException",
        "exact",
    ),
    (
        "k-29",
        "06-evaluation.typ:76 (@sec:evaluation-kafka)",
        "Kafka fuzzable space product and sample size",
        "746496 configurations of which 50 sampled",
        "exact",
    ),
    (
        "k-30",
        "06-evaluation.typ:357 (@sec:evaluation-reproducibility)",
        "Full second execution of Kafka sweep at evaluated revision reproduced every "
        "per-seed outcome",
        "zero flips across all 50 seeds",
        "exact",
    ),
    (
        "e1-02",
        "06-evaluation.typ:197 (@sec:evaluation-etcd v1 sweep)",
        "etcd v1 failing seeds (list)",
        "seeds 5,7,20,21,25,29,30,34,38,42,49",
        "exact",
    ),
    (
        "e1-03",
        "06-evaluation.typ:197 (@sec:evaluation-etcd v1 sweep)",
        "etcd v1 failure class and property report",
        "class invalid-etcd-election-timeout-heartbeat-ratio with empty 0/0 property "
        "report (failure pre-property-suite)",
        "exact",
    ),
    (
        "e1-04",
        "06-evaluation.typ:191-195 (@sec:evaluation-etcd v1 sweep)",
        "v1 trigger configuration and error message",
        "heartbeat-interval=250ms with election-timeout=1000ms; error 'election-timeout "
        "should be at least 5x heartbeat-interval'",
        "exact",
    ),
    (
        "e2-01",
        "06-evaluation.typ:203 (@sec:evaluation-etcd v2 sweep)",
        "etcd v2 sweep pass/fail split",
        "37 pass / 13 fail of 50 runs",
        "exact",
    ),
    (
        "e2-02",
        "06-evaluation.typ:203 (@sec:evaluation-etcd v2 sweep)",
        "etcd v2 failing seeds (list)",
        "seeds 3,6,12,13,14,28,33,34,38,40,41,42,43",
        "exact",
    ),
    (
        "e2-03",
        "06-evaluation.typ:203 (@sec:evaluation-etcd v2 sweep)",
        "etcd v2 failure class and failing check",
        "all 13 in class quota-backend-too-small-for-write-burst; failed check is last "
        "one etcd-quota-write-burst-etcd1",
        "exact",
    ),
    (
        "e2-05",
        "06-evaluation.typ:214 (@tab:etcd-quota-correlation)",
        "Quota correlation cell QUOTA_BACKEND_BYTES=2MiB (2097152): Passed/Failed/Total",
        "0/13/13",
        "exact",
    ),
    (
        "e2-08",
        "06-evaluation.typ:221 (@sec:evaluation-etcd v2 sweep)",
        "Deterministic quota split: every 2MiB run fails; every 8MiB and 64MiB run passes",
        "2MiB: 13/13 fail; 8MiB: 0/20 fail; 64MiB: 0/17 fail",
        "exact",
    ),
    (
        "e2-11",
        "06-evaluation.typ:225 (@sec:etcd-shrinking)",
        "Both representative v2 failures (seeds 3 and 40) reduce to same minimal config",
        "seeds 3 and 40 shrink to identical minimal configuration",
        "exact",
    ),
    (
        "e2-12",
        "06-evaluation.typ:225 (@sec:etcd-shrinking)",
        "etcd shrink minimal configuration values",
        "3 etcd nodes on one VLAN; memory 1024 MiB; disk 2048 MiB; heartbeat 100 ms; "
        "election timeout 1250 ms; snapshot count 10000; QUOTA_BACKEND_BYTES=2097152 (2 MiB)",
        "exact",
    ),
    (
        "e2-13",
        "06-evaluation.typ:225 (@sec:etcd-shrinking)",
        "Rerun of both shrinks reproduces identical result: same choice maps; same "
        "single failing check; same summary counts",
        "11 passed / 1 failed / 12 total",
        "exact",
    ),
    (
        "e2-14",
        "06-evaluation.typ:357 (@sec:evaluation-reproducibility)",
        "Both etcd shrinks reproduced minimal configurations identically at evaluated revision",
        "identical final choice maps and resolved values",
        "exact",
    ),
    (
        "r-01",
        "06-evaluation.typ:267 (@sec:evaluation-rabbitmq-disk)",
        "Disk positive control run passes all five properties with all confirms and no alarm",
        "5/5 properties pass; 50/50 publishes confirmed; 0 alarm samples (run "
        "20260822-183835-...-seed-1-phase2-disk-positive, rev 998cae1)",
        "exact",
    ),
    (
        "r-04",
        "06-evaluation.typ:274 (@sec:evaluation-rabbitmq-disk)",
        "Cell X alarm and publish outcomes",
        "disk_free alarm activates during publish (14 alarm samples); all 200 publish "
        "attempts ambiguous with ConnectionBlockedTimeout",
        "exact",
    ),
    (
        "r-05",
        "06-evaluation.typ:275 (@sec:evaluation-rabbitmq-disk)",
        "Cell X durably applied unconfirmed messages",
        "22 of the unconfirmed messages were durably applied by the broker",
        "range",
    ),
    (
        "r-06",
        "06-evaluation.typ:276 (@sec:evaluation-rabbitmq-disk)",
        "Cell X property outcome: exactly one property fails",
        "exactly one property fails: rabbitmq-disk-capacity-confirmation-contract; other "
        "four (incl. recovery and consistency) pass",
        "exact",
    ),
    (
        "r-07",
        "06-evaluation.typ:277 (@sec:evaluation-rabbitmq-disk)",
        "Two further identical-cell reproductions of Cell X reproduce the signature with "
        "different recovered counts",
        "22 and 23 recovered messages respectively",
        "range",
    ),
    (
        "r-08",
        "06-evaluation.typ:289-290 (@tab:rabbitmq-disk-cells)",
        "Disk positive-control rows: strict-suff true; naive-suff true; 50/50 confirmed; "
        "0 alarm samples; verdict",
        "pass 5/5 (both rows incl. rerun)",
        "exact",
    ),
    (
        "r-09",
        "06-evaluation.typ:291 (@tab:rabbitmq-disk-cells)",
        "Cell X row: strict-suff false; naive-suff true; 200/200 ambiguous; 14 alarm samples",
        "fails capacity contract only",
        "exact",
    ),
    (
        "r-10",
        "06-evaluation.typ:292-293 (@tab:rabbitmq-disk-cells)",
        "Cell X reproduction rows 1 and 2: same signature with recovered counts",
        "22 recovered (repro 1); 23 recovered (repro 2)",
        "range",
    ),
    (
        "r-11",
        "06-evaluation.typ:294 (@tab:rabbitmq-disk-cells)",
        "Disk minimal cell (nominal 100 MB / 200 MB limit / 20 x 1 KiB; other dimensions "
        "at minimum): 20/20 ambiguous and 16 alarm samples",
        "fails capacity contract only",
        "exact",
    ),
    (
        "r-20",
        "appendix.typ:138 (@tab:rabbitmq-crash-cells)",
        "Crash cell follower reproduction A: rabbit2 killed; 50/50 confirmed; 0 ambiguous; "
        "leader rabbit1->rabbit1",
        "pass 3/3",
        "exact",
    ),
    (
        "r-26",
        "appendix.typ:148 (@sec:crash-cells)",
        "Crash cell execution counts: two cells doubly executed (before-publish follower "
        "A+B; resolved during-publish follower)",
        "rest of cells single execution (existence claims only)",
        "exact",
    ),
    (
        "t-01",
        "06-evaluation.typ:359 (@sec:evaluation-reproducibility)",
        "Python unit-test suite passes at evaluated revisions",
        "57 tests",
        "exact",
    ),
    (
        "t-02",
        "06-evaluation.typ:359 (@sec:evaluation-reproducibility)",
        "Nix unit-test suite passes at evaluated revisions",
        "114 tests",
        "exact",
    ),
    (
        "m-01",
        "07-discussion.typ:91 (@sec:scalability-discussion)",
        "RabbitMQ baseline visited all cells of its conservative configuration space",
        "all 32 cells visited (informational; historical)",
        "informational",
    ),
    (
        "m-08",
        "06-evaluation.typ:379 (@sec:evaluation-summary)",
        "Summary restates both sweep aggregates and zero-flip rerun",
        "Kafka 13/37 of 50 with zero per-seed flips on re-execution; etcd v2 37/13 all "
        "quota class",
        "exact",
    ),
]

EXPECTED_VERDICTS = {
    "k-01": "match",
    "k-02": "match",
    "k-03": "match",
    "k-04": "match",
    "k-22": "match",
    "k-23": "match",
    "k-24": "match",
    "k-25": "match",
    "k-26": "match",
    "k-28": "match",
    "k-29": "match",
    "k-30": "match",
    "e1-02": "match",
    "e1-03": "match",
    "e1-04": "match",
    "e2-01": "match",
    "e2-02": "match",
    "e2-03": "match",
    "e2-05": "match",
    "e2-08": "match",
    "e2-11": "match",
    "e2-12": "match",
    "e2-13": "match",
    "e2-14": "match",
    "r-01": "match",
    "r-04": "match",
    "r-05": "match",
    "r-06": "match",
    "r-07": "within-tolerance",
    "r-08": "match",
    "r-09": "match",
    "r-10": "within-tolerance",
    "r-11": "match",
    "r-20": "match",
    # Appendix semantics: the "resolved during-publish follower" cell is
    # doubly executed (phase-2 during-publish run + phase-3 follower retune);
    # the fixture and manifest both model it that way.
    "r-26": "match",
    "t-01": "match",
    "t-02": "match",
    # Genuinely informational (historical) claims get their own verdict.
    "m-01": "informational-observed",
    "m-08": "informational-observed",
}


def write_json(root: Path, rel: str, obj) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def write_csv(root: Path, rel: str, header, rows) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    path.write_text(buf.getvalue(), encoding="utf-8")


def build_fake_analysis(root: Path) -> None:
    """Fake analysis/ tree matching analyze.py's documented schemas."""
    per_seed = []
    for seed in range(1, 51):
        if seed in KAFKA_BROKER_SEEDS:
            cls, status = "broker-message-max-too-small", "failed"
        elif seed in KAFKA_LOG_SEEDS:
            cls, status = "log-segment-too-small", "failed"
        else:
            cls, status = None, "passed"
        per_seed.append(
            {
                "seed": seed,
                "status": status,
                "failed_checks": [KAFKA_CHECK] if cls else [],
                "failure_class": cls,
            }
        )
    write_json(
        root,
        "analysis/kafka-sweep.json",
        {
            "seeds_run": 50,
            "passed": 13,
            "failed": 37,
            "failure_classes": {"broker-message-max-too-small": 18, "log-segment-too-small": 19},
            "per_seed": per_seed,
        },
    )
    rows = []
    for (msg, rep, seg), (p, b, lg) in sorted(CROSSTAB.items()):
        rows.append([f"{msg}MiB", f"{rep}MiB", f"{seg}MiB", p, b, lg])
    write_csv(
        root,
        "analysis/kafka-crosstab.csv",
        [
            "message_max_bytes",
            "replica_fetch_max_bytes",
            "log_segment_bytes",
            "pass",
            "broker_max",
            "log_segment",
        ],
        rows,
    )
    etcd_min = {
        "roles_etcd": 3,
        "election_timeout_ms": 1250,
        "heartbeat_interval_ms": 100,
        "quota_backend_bytes": 2097152,
        "snapshot_count": 10000,
        "disk_size": 2048,
        "memory_size": 1024,
    }
    write_json(
        root,
        "analysis/kafka-shrink.json",
        {
            "seeds": {
                "9": {
                    "original_class": "log-segment-too-small",
                    "shrunk_status": "failed",
                    "final_config": {"settings": {}},
                    "class_preserved": False,
                },
                "13": {
                    "original_class": "broker-message-max-too-small",
                    "shrunk_status": "failed",
                    "final_config": {"settings": {}},
                    "class_preserved": True,
                },
            }
        },
    )
    write_json(
        root,
        "analysis/kafka-min-configs.json",
        {
            "variants": {
                "min-message-max": {
                    "passed": 10,
                    "failed": 1,
                    "failed_check": KAFKA_CHECK,
                    "exception_class": "broker-message-max-too-small",
                },
                "min-log-segment": {
                    "passed": 10,
                    "failed": 1,
                    "failed_check": "other",
                    "exception_class": "log-segment-too-small",
                },
            }
        },
    )
    etcd_v1_failing = [5, 7, 20, 21, 25, 29, 30, 34, 38, 42, 49]
    write_json(
        root,
        "analysis/etcd-v1-sweep.json",
        {
            "passed": 39,
            "failed": 11,
            "failing_seeds": etcd_v1_failing,
            "failure_class": "invalid-etcd-election-timeout-heartbeat-ratio",
            "sample_error_message": "Error: election-timeout should be at least 5x "
            "heartbeat-interval (got 1000ms/250ms)",
            "per_seed": [
                {
                    "seed": s,
                    "status": "failed" if s in etcd_v1_failing else "passed",
                    "failed_checks": [],
                    "failure_class": (
                        "invalid-etcd-election-timeout-heartbeat-ratio"
                        if s in etcd_v1_failing
                        else None
                    ),
                }
                for s in range(1, 51)
            ],
        },
    )
    etcd_v2_failing = [3, 6, 12, 13, 14, 28, 33, 34, 38, 40, 41, 42, 43]
    write_json(
        root,
        "analysis/etcd-v2-sweep.json",
        {
            "passed": 37,
            "failed": 13,
            "failing_seeds": etcd_v2_failing,
            "failure_class": "quota-backend-too-small-for-write-burst",
            "sample_error_message": "etcdserver: mvcc: database space exceeded",
            "per_seed": [
                {
                    "seed": s,
                    "status": "failed" if s in etcd_v2_failing else "passed",
                    "failed_checks": [ETCD_V2_CHECK] if s in etcd_v2_failing else [],
                    "failure_class": (
                        "quota-backend-too-small-for-write-burst" if s in etcd_v2_failing else None
                    ),
                }
                for s in range(1, 51)
            ],
        },
    )
    write_csv(
        root,
        "analysis/etcd-v2-quota-correlation.csv",
        ["quota_backend_bytes", "passed", "failed", "total"],
        [[2097152, 0, 13, 13], [8388608, 20, 0, 20], [67108864, 17, 0, 17]],
    )
    write_json(
        root,
        "analysis/etcd-v2-shrink.json",
        {
            "seeds": {
                "3": {"final_config": etcd_min, "passed": 11, "failed": 1, "total": 12},
                "40": {"final_config": dict(etcd_min), "passed": 11, "failed": 1, "total": 12},
            },
            "identical_minimal_config": True,
        },
    )
    disk_rows = []
    for ei in (0, 1):
        disk_rows.append(["positive", ei, 1, "passed", 5, 5, "", 0, 0, 0, "true", "true"])
    for ei, recovered in ((0, 22), (1, 23), (2, 23)):
        disk_rows.append(
            [
                "cell-x",
                ei,
                1,
                "failed",
                4,
                5,
                "rabbitmq-disk-capacity-confirmation-contract",
                200,
                14,
                recovered,
                "false",
                "true",
            ]
        )
    for ei in (0, 1):
        disk_rows.append(
            [
                "minimal",
                ei,
                1,
                "failed",
                4,
                5,
                "rabbitmq-disk-capacity-confirmation-contract",
                20,
                16,
                0,
                "false",
                "true",
            ]
        )
    write_csv(
        root,
        "analysis/rabbitmq-disk-cells.csv",
        [
            "variant",
            "execution_index",
            "seed",
            "status",
            "checks_passed",
            "checks_total",
            "failing_checks",
            "ambiguous_count",
            "alarm_samples",
            "recovered_count",
            "strict_sufficient",
            "naive_sufficient",
        ],
        disk_rows,
    )
    write_csv(
        root,
        "analysis/rabbitmq-faildom-cells.csv",
        [
            "variant",
            "execution_index",
            "placement",
            "status",
            "properties_passed",
            "properties_total",
            "operations_recovered",
            "operations_total",
            "probe_status",
            "failing_checks",
        ],
        [
            ["spread", 0, "a=1;a=2;a=3", "passed", 2, 2, 11, 11, "confirmed", ""],
            [
                "colocated",
                0,
                "a=1;a=2;a=2",
                "failed",
                1,
                2,
                11,
                11,
                "ambiguous",
                "rabbitmq-failure-domain-retains-quorum-availability",
            ],
            [
                "colocated",
                1,
                "a=1;a=2;a=2",
                "failed",
                1,
                2,
                11,
                11,
                "ambiguous",
                "rabbitmq-failure-domain-retains-quorum-availability",
            ],
        ],
    )
    crash_rows = [
        ["follower-repA", 0, "passed", 3, 3, 50, 0, "rabbit1", "rabbit1", ""],
        ["follower-repB", 0, "passed", 3, 3, 50, 0, "rabbit1", "rabbit1", ""],
        ["leader", 0, "passed", 3, 3, 50, 0, "rabbit1", "rabbit2", ""],
        ["during-publish", 0, "passed", 3, 3, 50, 0, "rabbit1", "rabbit1", ""],
        ["retune-follower", 0, "passed", 3, 3, 50, 0, "rabbit1", "rabbit1", ""],
        ["retune-leader", 0, "passed", 3, 3, 50, 0, "rabbit1", "rabbit2", ""],
    ]
    write_csv(
        root,
        "analysis/rabbitmq-crash-cells.csv",
        [
            "variant",
            "execution_index",
            "status",
            "checks_passed",
            "checks_total",
            "confirmed_count",
            "ambiguous_count",
            "leader_before",
            "leader_after",
            "failing_checks",
        ],
        crash_rows,
    )
    write_json(
        root,
        "analysis/determinism.json",
        {
            "kafka-sweep": {"present": True, "flips": 0, "seed_diffs": []},
            "etcd-v1-sweep": {"present": True, "flips": 0, "seed_diffs": []},
            "etcd-v2-sweep": {"present": True, "flips": 0, "seed_diffs": []},
        },
    )
    write_json(
        root,
        "analysis/test-suites.json",
        {
            "python": {"ran": 57, "ok": True},
            "nix": {"successful": 114, "total": 114, "ok": True},
        },
    )
    write_json(
        root,
        "analysis/execution-accounting.json",
        {
            "groups": {
                "kafka-cluster": {
                    "space_size": 746496,
                    "units": 100,
                    "seeds": 50,
                    "fresh": 100,
                    "cache_replay": 0,
                    "wall_total_s": 21380.0,
                    "compute_hours": 5.94,
                    "peak_rss_max_bytes": 3271558144,
                },
                "etcd-cluster": {
                    "space_size": 96,
                    "units": 100,
                    "seeds": 50,
                    "fresh": 100,
                    "cache_replay": 0,
                    "wall_total_s": 9800.0,
                    "compute_hours": 2.72,
                    "peak_rss_max_bytes": 1696858112,
                },
                "rabbitmq-disk": {
                    "space_size": 864,
                    "units": 7,
                    "seeds": 1,
                    "fresh": 7,
                    "cache_replay": 0,
                    "wall_total_s": 578.2,
                    "compute_hours": 0.16,
                    "peak_rss_max_bytes": 2264000000,
                },
                "rabbitmq-faildom": {
                    "space_size": 4,
                    "units": 3,
                    "seeds": 1,
                    "fresh": 3,
                    "cache_replay": 0,
                    "wall_total_s": 249.0,
                    "compute_hours": 0.07,
                    "peak_rss_max_bytes": 2264000000,
                },
                "rabbitmq-crash": {
                    "space_size": 24,
                    "units": 6,
                    "seeds": 1,
                    "fresh": 6,
                    "cache_replay": 0,
                    "wall_total_s": 498.0,
                    "compute_hours": 0.14,
                    "peak_rss_max_bytes": 2264000000,
                },
            },
            "totals": {
                "units": 216,
                "fresh": 216,
                "cache_replay": 0,
                "wall_total_s": 32505.2,
                "compute_hours": 9.03,
                "peak_rss_max_bytes": 3271558144,
            },
        },
    )


def write_subset_claims(path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["claim_id", "location", "statement", "expected_value", "tolerance"])
        for row in SUBSET_CLAIMS:
            w.writerow(row)


class VerifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-verify-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        build_fake_analysis(self.tmp)
        self.claims_path = self.tmp / "claims-subset.csv"
        write_subset_claims(self.claims_path)

    def verdicts(self) -> dict:
        summary = verify_run(self.tmp, None, str(self.claims_path))
        return {r["claim_id"]: r["verdict"] for r in summary["rows"]}

    def test_verdict_mix(self):
        got = self.verdicts()
        for claim_id, want in EXPECTED_VERDICTS.items():
            self.assertEqual(got[claim_id], want, claim_id)

    def test_summary_counts(self):
        summary = verify_run(self.tmp, None, str(self.claims_path))
        self.assertEqual(len(summary["rows"]), len(SUBSET_CLAIMS))
        self.assertEqual(summary["match"], 35)
        self.assertEqual(summary["within-tolerance"], 2)
        self.assertEqual(summary["mismatch"], 0)
        self.assertEqual(summary["not-reproduced"], 0)
        self.assertEqual(summary["informational"], 2)

    def test_r10_range_rule(self):
        summary = verify_run(self.tmp, None, str(self.claims_path))
        row = next(r for r in summary["rows"] if r["claim_id"] == "r-10")
        self.assertEqual(row["verdict"], "within-tolerance")
        self.assertIn("23", row["observed"])

    def test_matrix_row_schema_and_order(self):
        verify_run(self.tmp, None, str(self.claims_path))
        text = (self.tmp / "verification" / "claims-matrix.csv").read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertEqual(lines[0], "claim_id,location,expected,observed,verdict," "artifact,reason")
        ids = [line.split(",", 1)[0] for line in lines[1:]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(SUBSET_CLAIMS))

    def test_matrix_byte_identical_on_rerun(self):
        verify_run(self.tmp, None, str(self.claims_path))
        first = (self.tmp / "verification" / "claims-matrix.csv").read_bytes()
        verify_run(self.tmp, None, str(self.claims_path))
        second = (self.tmp / "verification" / "claims-matrix.csv").read_bytes()
        self.assertEqual(first, second)

    def test_missing_artifact_not_reproduced(self):
        (self.tmp / "analysis" / "etcd-v2-shrink.json").unlink()
        summary = verify_run(self.tmp, None, str(self.claims_path))
        for claim_id in ("e2-11", "e2-12", "e2-13", "e2-14"):
            row = next(r for r in summary["rows"] if r["claim_id"] == claim_id)
            self.assertEqual(row["verdict"], "not-reproduced", claim_id)
            self.assertIn("missing", row["reason"])

    def test_e2_13_without_seed_data_is_not_reproduced(self):
        """An artifact present but empty is absent data, not a contradiction:
        the old guard tested a list the loop always filled, so it scored a
        mismatch of "seed 3: None/None/None"."""
        path = self.tmp / "analysis" / "etcd-v2-shrink.json"
        path.write_text(json.dumps({"seeds": {}}), encoding="utf-8")
        summary = verify_run(self.tmp, None, str(self.claims_path))
        row = next(r for r in summary["rows"] if r["claim_id"] == "e2-13")
        self.assertEqual(row["verdict"], "not-reproduced")
        self.assertIn("no etcd-v2-shrink entry", row["reason"])

    def test_t01_passing_larger_suite_is_within_tolerance(self):
        """The harness runs the suite of the checked-out revision, and the
        framework has gained tests since the thesis. A passing superset is
        within tolerance; a failing or shrunken suite is still a mismatch."""
        path = self.tmp / "analysis" / "test-suites.json"
        base = json.loads(path.read_text(encoding="utf-8"))

        base["python"] = {"ran": 59, "ok": True}
        path.write_text(json.dumps(base), encoding="utf-8")
        row = next(
            r
            for r in verify_run(self.tmp, None, str(self.claims_path))["rows"]
            if r["claim_id"] == "t-01"
        )
        self.assertEqual(row["verdict"], "within-tolerance")
        self.assertIn("ran=59", row["observed"])
        self.assertIn("2 test(s) added", row["reason"])

        for py, want in (
            ({"ran": 59, "ok": False}, "mismatch"),
            ({"ran": 56, "ok": True}, "mismatch"),
            ({"ran": 57, "ok": True}, "match"),
        ):
            base["python"] = py
            path.write_text(json.dumps(base), encoding="utf-8")
            row = next(
                r
                for r in verify_run(self.tmp, None, str(self.claims_path))["rows"]
                if r["claim_id"] == "t-01"
            )
            self.assertEqual(row["verdict"], want, py)

    # --- nondeterministic detail vs. claimed substance ------------------------
    #
    # Both campaigns showed these two claim pairs swapping verdicts between
    # themselves while the substance held: which surviving node RabbitMQ
    # elects, and whether the alarm poller catches 15 or 16 samples, are not
    # determined by the configuration under test.

    def _edit_csv(self, name: str, match: dict, column: str, value) -> None:
        path = self.tmp / "analysis" / f"{name}.csv"
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            header, rows = reader.fieldnames, list(reader)
        for row in rows:
            if all(str(row[k]) == str(v) for k, v in match.items()):
                row[column] = str(value)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        path.write_text(buf.getvalue(), encoding="utf-8")

    def _row_for(self, claim_id: str) -> dict:
        # The RabbitMQ cell claims live outside SUBSET_CLAIMS, so score the
        # fake tree against the real claims file and pick the row out.
        return next(
            r
            for r in verify_run(self.tmp, None, str(CLAIMS_CSV))["rows"]
            if r["claim_id"] == claim_id
        )

    def test_crash_cell_other_successor_is_within_tolerance(self):
        self._edit_csv(
            "rabbitmq-crash-cells", {"variant": "retune-leader"}, "leader_after", "rabbit3"
        )
        row = self._row_for("r-25")
        self.assertEqual(row["verdict"], "within-tolerance")
        self.assertIn("rabbit1->rabbit3", row["observed"])
        self.assertIn("rather than the thesis's rabbit2", row["reason"])

    def test_crash_cell_unexpected_migration_is_still_a_mismatch(self):
        # follower cells claim the leader does NOT move; a migration there is
        # a real difference, not election noise.
        self._edit_csv(
            "rabbitmq-crash-cells", {"variant": "follower-repA"}, "leader_after", "rabbit2"
        )
        self.assertEqual(self._row_for("r-20")["verdict"], "mismatch")

    def test_crash_cell_failing_checks_are_still_a_mismatch(self):
        self._edit_csv("rabbitmq-crash-cells", {"variant": "retune-leader"}, "checks_passed", 2)
        self._edit_csv(
            "rabbitmq-crash-cells", {"variant": "retune-leader"}, "leader_after", "rabbit3"
        )
        self.assertEqual(self._row_for("r-25")["verdict"], "mismatch")

    def test_alarm_sample_off_by_one_is_within_tolerance(self):
        self._edit_csv(
            "rabbitmq-disk-cells",
            {"variant": "minimal", "execution_index": "0"},
            "alarm_samples",
            15,
        )
        row = self._row_for("r-11")
        self.assertEqual(row["verdict"], "within-tolerance")
        self.assertIn("15 alarm samples", row["observed"])
        self.assertIn("thesis's 16", row["reason"])
        # ... and the duplicated-run claim tolerates the same one-sample gap
        # (execution 1 still has 16) while reporting both counts.
        row12 = self._row_for("r-12")
        self.assertEqual(row12["verdict"], "within-tolerance")
        self.assertIn("first execution: 15 alarms", row12["observed"])

    def test_alarm_samples_far_off_are_still_a_mismatch(self):
        self._edit_csv(
            "rabbitmq-disk-cells",
            {"variant": "minimal", "execution_index": "0"},
            "alarm_samples",
            4,
        )
        self.assertEqual(self._row_for("r-11")["verdict"], "mismatch")
        self.assertEqual(self._row_for("r-12")["verdict"], "mismatch")

    def test_ambiguous_count_is_still_scored_exactly(self):
        self._edit_csv(
            "rabbitmq-disk-cells",
            {"variant": "minimal", "execution_index": "0"},
            "ambiguous_count",
            19,
        )
        self.assertEqual(self._row_for("r-11")["verdict"], "mismatch")
        self.assertEqual(self._row_for("r-12")["verdict"], "mismatch")

    def test_duplicated_run_with_a_different_verdict_is_a_mismatch(self):
        self._edit_csv(
            "rabbitmq-disk-cells",
            {"variant": "minimal", "execution_index": "1"},
            "checks_passed",
            3,
        )
        self.assertEqual(self._row_for("r-12")["verdict"], "mismatch")

    # --- e2-15: the exhaustive baseline -------------------------------------

    def _write_exhaustive(self, doc: dict) -> None:
        (self.tmp / "analysis" / "etcd-v2-exhaustive.json").write_text(
            json.dumps(doc), encoding="utf-8"
        )

    _EXHAUSTIVE_OK = {
        "cells": 96,
        "passed": 64,
        "failed": 32,
        "no_property_verdict": 0,
        "cells_by_quota_bytes": {"2097152": 32, "8388608": 32, "67108864": 32},
        "failures_by_quota_bytes": {"2097152": 32},
    }

    def test_e2_15_full_space_quota_split_matches(self):
        self._write_exhaustive(self._EXHAUSTIVE_OK)
        row = self._row_for("e2-15")
        self.assertEqual(row["verdict"], "match")
        self.assertIn("96/96 cells with a property verdict", row["observed"])
        self.assertNotIn("without a property verdict", row["observed"])
        self.assertEqual(row["artifact"], "analysis/etcd-v2-exhaustive.json")

    def test_e2_15_infrastructure_failure_is_incomplete_not_a_quota_failure(self):
        """Night 1's stray cell: one cell whose VM shell never came up. It
        must make the enumeration incomplete (mismatch) and be reported as
        such — never counted as a failure at its quota value."""
        doc = dict(self._EXHAUSTIVE_OK, passed=63, no_property_verdict=1)
        self._write_exhaustive(doc)
        row = self._row_for("e2-15")
        self.assertEqual(row["verdict"], "mismatch")
        self.assertIn("95/96 cells with a property verdict", row["observed"])
        self.assertIn("32 fail (32 at 2097152)", row["observed"])
        self.assertIn("1 without a property verdict (startup/infrastructure)", row["observed"])

    def test_e2_15_no_executed_cells_is_not_reproduced(self):
        """The first campaign's shape: 96 cells planned, every unit dead
        before the property suite. That must show up — it previously sat
        behind a clean '0 not-reproduced' because no claim read the file."""
        self._write_exhaustive(
            {"cells": 96, "passed": 0, "failed": 0, "failures_by_quota_bytes": {}}
        )
        row = self._row_for("e2-15")
        self.assertEqual(row["verdict"], "not-reproduced")
        self.assertIn("none of the 96 exhaustive cells", row["reason"])

    def test_e2_15_failure_outside_2mib_is_a_mismatch(self):
        doc = dict(
            self._EXHAUSTIVE_OK,
            passed=63,
            failed=33,
            failures_by_quota_bytes={"2097152": 32, "8388608": 1},
        )
        self._write_exhaustive(doc)
        self.assertEqual(self._row_for("e2-15")["verdict"], "mismatch")

    def test_e2_15_incomplete_enumeration_is_a_mismatch(self):
        doc = dict(self._EXHAUSTIVE_OK, passed=60)  # 92 of 96 produced a verdict
        self._write_exhaustive(doc)
        row = self._row_for("e2-15")
        self.assertEqual(row["verdict"], "mismatch")
        self.assertIn("92/96 cells with a property verdict", row["observed"])

    def test_real_claims_csv_comma_repair(self):
        # claims.csv carries unquoted commas inside statements/expected values
        # (crosstab cell specs, seed lists); load_claims must repair them.
        from experiments.reproduce.verify import load_claims

        claims = {c.claim_id: c for c in load_claims(str(CLAIMS_CSV))}
        self.assertEqual(len(claims), 91)
        self.assertEqual(
            claims["k-04"].statement,
            "Crosstab cell (message.max.bytes=1MiB,"
            "replica.fetch.max.bytes=1MiB,"
            "log.segment.bytes=1MiB): pass/broker-max/log-segment",
        )
        self.assertEqual(claims["k-04"].expected_value, "0/3/0")
        self.assertEqual(claims["e1-02"].expected_value, "seeds 5,7,20,21,25,29,30,34,38,42,49")
        self.assertEqual(
            claims["e2-02"].expected_value, "seeds 3,6,12,13,14,28,33,34,38,40,41,42,43"
        )
        self.assertTrue(claims["r-01"].expected_value.startswith("5/5 properties"))
        self.assertTrue(claims["r-01"].expected_value.endswith("rev 998cae1)"))
        self.assertEqual(
            sorted({c.tolerance for c in claims.values()}), ["exact", "informational", "range"]
        )

    def test_all_real_claims_rowed_against_empty_analysis_dir(self):
        empty = self.tmp / "empty-out"
        empty.mkdir()
        summary = verify_run(empty, None, str(CLAIMS_CSV))
        rows = summary["rows"]
        self.assertEqual(len(rows), 91)
        # m-04/m-05/m-06 are current-campaign setup/workload descriptions with
        # no artifact wired to check them (like m-01/02/03/07's historical
        # baselines) — informational, not a failed reproduction.
        info_ids = ("m-01", "m-02", "m-03", "m-04", "m-05", "m-06", "m-07")
        for row in rows:
            if row["claim_id"] in info_ids:
                self.assertEqual(row["verdict"], "informational-observed", row["claim_id"])
            else:
                self.assertEqual(row["verdict"], "not-reproduced", row["claim_id"])
            self.assertTrue(row["reason"], row["claim_id"])
        self.assertEqual(summary["not-reproduced"], 91 - len(info_ids))
        self.assertEqual(summary["informational"], len(info_ids))
        self.assertEqual(summary["match"], 0)
        matrix = (empty / "verification" / "claims-matrix.csv").read_text(encoding="utf-8")
        self.assertEqual(len(matrix.splitlines()), 92)

    def test_no_timestamps_in_generated_columns(self):
        verify_run(self.tmp, None, str(self.claims_path))
        with open(
            self.tmp / "verification" / "claims-matrix.csv", "r", encoding="utf-8", newline=""
        ) as fh:
            rows = list(csv.DictReader(fh))
        for row in rows:
            for field in ("observed", "verdict", "artifact", "reason"):
                text = row[field].lower()
                for banned in ("20260", "generated at", "timestamp"):
                    self.assertNotIn(banned, text)


if __name__ == "__main__":
    unittest.main()
