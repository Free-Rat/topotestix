"""Tests for experiments/reproduce/analyze.py — fake campaign tree fixtures.

Mandatory invariants asserted here:
  - artifact numbers derived from the fixture tree are correct;
  - every float is emitted as a "%.6g"-formatted string;
  - run_all twice produces byte-identical analysis/ files.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from experiments.reproduce import analyze
from experiments.reproduce.collect import collect
from tests.test_reproduce_collect import (
    make_kafka_unit,
    make_rabbit_unit,
    unit_dict,
    write_json,
    write_text,
)

KAFKA_RESOLVED = {
    "topology": {"roles": {"kafka": 3}},
    "roleFuzz": {
        "kafka": {
            "choices": {},
            "result": {
                "services": {
                    "apache-kafka": {
                        "settings": {
                            "message.max.bytes": 1048576,
                            "replica.fetch.max.bytes": 1048576,
                            "log.segment.bytes": 1048576,
                        }
                    }
                }
            },
        }
    },
}


def make_kafka_fail_unit(root, uid, seed, message, resolved=None, rep=0):
    make_kafka_unit(root, uid, seed, "failed", failed_check="kafka-large-message-on-kafka1")
    write_json(
        root,
        f"raw/{uid}/report.json",
        [
            {"name": "kafka-large-message-on-kafka1", "status": "failed", "message": message},
            {"name": "kafka-roundtrip-on-kafka1", "status": "passed"},
        ],
    )
    write_json(
        root,
        f"raw/{uid}/run.json",
        {
            "id": uid,
            "target": "kafka-cluster",
            "seed": seed,
            "repetition_index": rep,
            "status": "failed",
            "summary": {"passed": 10, "failed": 1, "total": 11},
        },
    )
    if resolved is not None:
        write_json(root, f"raw/{uid}/resolved.json", resolved)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-analyze-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        root = self.tmp
        # kafka pass, seed 1, rep 0
        make_kafka_unit(root, "unit-pass", 1, "passed")
        write_json(
            root,
            "raw/unit-pass/resolved.json",
            {
                "topology": {"roles": {"kafka": 3}},
                "roleFuzz": {
                    "kafka": {
                        "choices": {},
                        "result": {
                            "services": {
                                "apache-kafka": {
                                    "settings": {
                                        "message.max.bytes": 4194304,
                                        "replica.fetch.max.bytes": 4194304,
                                        "log.segment.bytes": 16777216,
                                    }
                                }
                            }
                        },
                    }
                },
            },
        )
        # kafka fail, seed 2, rep 0 — RecordBatchTooLargeException class
        make_kafka_fail_unit(
            root,
            "unit-fail",
            2,
            "org.apache.kafka.common.errors.RecordBatchTooLargeException: boom",
            resolved=KAFKA_RESOLVED,
        )
        # kafka shrink for seed 2 (no rep1 anywhere -> determinism present=false)
        write_json(
            root,
            "raw/unit-shrink/status.json",
            {
                "state": "done",
                "input_hash": "x",
                "exit_code": 0,
                "execution": "fresh",
                "unit": {
                    "entry_id": "kafka-shrink",
                    "id": "unit-shrink",
                    "kind": "shrink",
                    "seed": 2,
                    "repetition_index": 0,
                    "execution_index": 0,
                    "variant_name": None,
                    "target": "kafka-cluster",
                },
            },
        )
        write_json(
            root,
            "raw/unit-shrink/run.json",
            {
                "id": "unit-shrink",
                "target": "kafka-cluster",
                "seed": 2,
                "status": "failed",
                "summary": {"passed": 10, "failed": 1, "total": 11},
            },
        )
        write_json(
            root,
            "raw/unit-shrink/report.json",
            [
                {
                    "name": "kafka-large-message-on-kafka1",
                    "status": "failed",
                    "message": "org.apache.kafka.common.errors.RecordTooLargeException: x",
                },
            ],
        )
        write_json(
            root,
            "raw/unit-shrink/shrink.json",
            {
                "final_topology_choices": {".roles.kafka": 0},
                "final_config_choices": {".services.apache-kafka.settings.log.segment.bytes": 0},
            },
        )
        write_json(root, "raw/unit-shrink/timing.json", {"wall_s": 123.456789})
        write_json(
            root,
            "raw/unit-shrink/resources.json",
            {"peak_rss_bytes": 3271558144, "cpu_seconds": 99.5},
        )
        write_json(root, "raw/unit-shrink/nix-build.json", {"execution": "fresh", "markers": []})
        # rabbitmq disk cell-x with minimal evidence payload
        make_rabbit_unit(root, "unit-rabbit")
        write_json(root, "raw/unit-rabbit/timing.json", {"wall_s": 82.6})
        write_json(
            root,
            "raw/unit-rabbit/resources.json",
            {"peak_rss_bytes": 2264000000, "cpu_seconds": 40.0},
        )
        write_json(root, "raw/unit-rabbit/nix-build.json", {"execution": "fresh", "markers": []})
        # resolution space size (used by execution-accounting)
        write_json(
            root,
            "resolution/kafka-cluster/uniqueness.json",
            {"space_size": 746496, "unique_resolved": 50},
        )
        self.collected = collect(root)
        analyze.run_all(root, self.collected)

    def analysis_path(self, name: str) -> Path:
        return self.tmp / "analysis" / name

    # --- kafka-sweep ----------------------------------------------------------

    def test_kafka_sweep_counts(self):
        data = read_json(self.analysis_path("kafka-sweep.json"))
        self.assertEqual(data["seeds_run"], 2)
        self.assertEqual(data["passed"], 1)
        self.assertEqual(data["failed"], 1)
        self.assertEqual(data["failure_classes"], {"log-segment-too-small": 1})
        self.assertEqual([r["seed"] for r in data["per_seed"]], [1, 2])
        self.assertIsNone(data["per_seed"][0]["failure_class"])
        self.assertEqual(data["per_seed"][1]["failed_checks"], ["kafka-large-message-on-kafka1"])
        csv_text = self.analysis_path("kafka-sweep.csv").read_text(encoding="utf-8")
        self.assertIn("2,failed,kafka-large-message-on-kafka1,log-segment-too-small", csv_text)

    def test_kafka_crosstab_row_for_failing_seed(self):
        rows = (
            self.analysis_path("kafka-crosstab.csv")
            .read_text(encoding="utf-8")
            .strip()
            .splitlines()
        )
        self.assertEqual(
            rows[0],
            "message_max_bytes,replica_fetch_max_bytes,log_segment_bytes,"
            "pass,broker_max,log_segment",
        )
        self.assertIn("1MiB,1MiB,1MiB,0,0,1", rows)
        self.assertIn("4MiB,4MiB,16MiB,1,0,0", rows)

    def test_kafka_shrink(self):
        data = read_json(self.analysis_path("kafka-shrink.json"))
        seed2 = data["seeds"]["2"]
        self.assertEqual(seed2["original_class"], "log-segment-too-small")
        self.assertEqual(seed2["shrunk_status"], "failed")
        self.assertFalse(seed2["class_preserved"])
        self.assertEqual(
            seed2["final_config"],
            {
                "final_topology_choices": {".roles.kafka": 0},
                "final_config_choices": {".services.apache-kafka.settings.log.segment.bytes": 0},
            },
        )

    # --- determinism ----------------------------------------------------------

    def test_determinism_missing_rep1(self):
        data = read_json(self.analysis_path("determinism.json"))
        self.assertEqual(data["kafka-sweep"], {"present": False})
        self.assertEqual(data["etcd-v1-sweep"], {"present": False})
        self.assertEqual(data["etcd-v2-sweep"], {"present": False})

    # --- rabbitmq-disk-cells ---------------------------------------------------

    def test_rabbitmq_disk_row(self):
        text = (
            self.analysis_path("rabbitmq-disk-cells.csv")
            .read_text(encoding="utf-8")
            .strip()
            .splitlines()
        )
        self.assertEqual(
            text[0],
            "variant,execution_index,seed,status,checks_passed,checks_total,"
            "failing_checks,ambiguous_count,alarm_samples,recovered_count,"
            "strict_sufficient,naive_sufficient,nominal_free_target_mb,"
            "disk_free_limit_mb,planned_messages,message_size_kib,"
            "confirm_timeout_ms,safety_factor_milli",
        )
        self.assertEqual(
            text[1],
            "cell-x,0,1,failed,4,5,"
            "rabbitmq-disk-capacity-confirmation-contract,2,1,1,False,True,"
            ",,,,,",
        )

    # --- execution accounting --------------------------------------------------

    def test_execution_accounting_formatting(self):
        data = read_json(self.analysis_path("execution-accounting.json"))
        kafka = data["groups"]["kafka-cluster"]
        self.assertEqual(kafka["space_size"], 746496)
        self.assertEqual(kafka["units"], 3)
        self.assertEqual(kafka["seeds"], 2)
        # floats must be "%.6g" strings, not raw numbers
        self.assertEqual(kafka["wall_total_s"], f"{10.5 + 10.5 + 123.456789:.6g}")
        self.assertIsInstance(kafka["compute_hours"], str)
        self.assertIsInstance(kafka["peak_rss_max_bytes"], int)
        self.assertEqual(data["totals"]["fresh"], 4)
        csv_text = self.analysis_path("execution-accounting.csv").read_text(encoding="utf-8")
        self.assertIn("kafka-cluster,3,2,3,0,", csv_text)

    # --- determinism of the analysis itself (mandatory) -------------------------

    def test_run_all_is_byte_identical(self):
        before = {p.name: p.read_bytes() for p in sorted((self.tmp / "analysis").iterdir())}
        self.assertTrue(before)
        analyze.run_all(self.tmp, collect(self.tmp))
        after = {p.name: p.read_bytes() for p in sorted((self.tmp / "analysis").iterdir())}
        self.assertEqual(before, after)

    def test_no_unformatted_floats_in_json(self):
        def walk(obj, path=""):
            if isinstance(obj, float):
                raise AssertionError(f"unformatted float at {path}: {obj!r}")
            if isinstance(obj, dict):
                for k, v in obj.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    walk(v, f"{path}[{i}]")

        for p in sorted((self.tmp / "analysis").glob("*.json")):
            walk(read_json(p), p.name)


class ShrinkTrialAccountingTests(unittest.TestCase):
    """A shrink unit whose loop tried multiple candidates (raw/<id>/trials.json,
    written by runner.py's _index_run_store) must have every trial surfaced in
    the shrink analysis and counted in execution-accounting — not just the one
    final/kept candidate."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-analyze-trials-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        root = self.tmp
        write_json(
            root,
            "raw/unit-shrink3/status.json",
            {
                "state": "done",
                "input_hash": "x",
                "exit_code": 0,
                "execution": "fresh",
                "unit": {
                    "entry_id": "kafka-shrink",
                    "id": "unit-shrink3",
                    "kind": "shrink",
                    "seed": 9,
                    "repetition_index": 0,
                    "execution_index": 0,
                    "variant_name": None,
                    "target": "kafka-cluster",
                },
            },
        )
        write_json(
            root,
            "raw/unit-shrink3/run.json",
            {
                "id": "unit-shrink3",
                "target": "kafka-cluster",
                "seed": 9,
                "status": "failed",
                "summary": {"passed": 10, "failed": 1, "total": 11},
            },
        )
        write_json(root, "raw/unit-shrink3/report.json", [])
        write_json(root, "raw/unit-shrink3/shrink.json", {"final_topology_choices": {}})
        write_json(root, "raw/unit-shrink3/timing.json", {"wall_s": 300.0})
        # Three candidates the shrinker tried: two fresh builds, one cache
        # replay (e.g. an earlier-tried config the store already had). Only
        # the last is the kept/final one, but all three actually executed.
        write_json(
            root,
            "raw/unit-shrink3/trials.json",
            [
                {"dir": "t0", "execution": "fresh", "markers": [], "status": "failed"},
                {"dir": "t1", "execution": "cache-replay", "markers": [], "status": "passed"},
                {"dir": "t2", "execution": "fresh", "markers": [], "status": "failed"},
            ],
        )
        write_json(
            root,
            "resolution/kafka-cluster/uniqueness.json",
            {"space_size": 746496, "unique_resolved": 50},
        )
        self.collected = collect(root)
        analyze.run_all(root, self.collected)

    def analysis_path(self, name: str) -> Path:
        return self.tmp / "analysis" / name

    def test_shrink_json_surfaces_every_trial(self):
        data = read_json(self.analysis_path("kafka-shrink.json"))
        trials = data["seeds"]["9"]["trials"]
        self.assertEqual(trials["count"], 3)
        self.assertEqual(trials["executions"], {"fresh": 2, "cache-replay": 1})
        self.assertEqual([t["status"] for t in trials["trials"]], ["failed", "passed", "failed"])

    def test_execution_accounting_counts_every_trial_not_just_one(self):
        data = read_json(self.analysis_path("execution-accounting.json"))
        kafka = data["groups"]["kafka-cluster"]
        # 1 manifest unit, but 3 actual VM executions inside its shrink loop.
        self.assertEqual(kafka["units"], 1)
        self.assertEqual(kafka["fresh"], 2)
        self.assertEqual(kafka["cache_replay"], 1)
        self.assertEqual(data["totals"]["fresh"], 2)
        self.assertEqual(data["totals"]["cache_replay"], 1)


class StageTimingSourceTests(unittest.TestCase):
    """Stage seconds come from the VM driver's own "(finished: ..., in N
    seconds)" lines and from nothing else.  timing.json's stage information is
    positional (line indices in a log with no per-line timestamps), so reading
    it as durations produced nonsense — a 7233 "second" build inside a 222 s
    run, and negative boot times."""

    def _stage_rows(self, root: Path):
        analyze.run_all(root, collect(root))
        return read_json(root / "analysis" / "stage-timing.json")["units"]

    def test_seconds_parsed_from_driver_finished_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_kafka_unit(root, "unit-timing-driver", 1, "passed")
            write_text(
                root,
                "raw/unit-timing-driver/stdout.log",
                "(finished: waiting for the VM to finish booting, in 8.75 seconds)\n"
                "(finished: must succeed: kafka-roundtrip, in 9.50 seconds)\n",
            )
            rows = self._stage_rows(root)
            row = next(r for r in rows if r["unit"] == "unit-timing-driver")
            self.assertEqual(row["vm_boot_s"], "8.75")
            self.assertEqual(row["test_script_s"], "9.5")
            # No timestamped source exists for these two, so they stay null
            # rather than being invented from log-line positions.
            self.assertIsNone(row["nix_eval_s"])
            self.assertIsNone(row["build_s"])
            self.assertEqual(row["completeness"], "partial")

    def test_positional_phase_data_is_never_read_as_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_kafka_unit(root, "unit-timing-positional", 1, "passed")
            write_json(
                root,
                "raw/unit-timing-positional/timing.json",
                {
                    "wall_s": 222.0,
                    # Shape written by pre-fix runs: line counts, not seconds.
                    "phases": {"build": 7233, "vm_boot": -4, "test_script": 8497},
                    "phase_markers": {
                        "build": {"first_line": 3, "last_line": 7236},
                        "total_lines": 8500,
                    },
                },
            )
            rows = self._stage_rows(root)
            row = next(r for r in rows if r["unit"] == "unit-timing-positional")
            for key in ("nix_eval_s", "build_s", "vm_boot_s", "test_script_s"):
                self.assertIsNone(row[key], f"{key} must not come from log-line positions")
            self.assertEqual(row["completeness"], "partial")


class ExhaustiveConfigSourceTests(unittest.TestCase):
    """An exhaustive cell is pinned by --config-choices. resolved.json still
    reports roleFuzz.etcd.choices as the SEED's own draw, identical for every
    cell; reading it made all 96 cells report one config map and attributed
    every failure to the seed's quota index."""

    QUOTA_BYTES = (2097152, 8388608, 67108864)

    def _make_cell(self, root: Path, idx: int, quota_index: int, status: str):
        uid = f"cell-unit-{idx}"
        write_json(
            root,
            f"raw/{uid}/status.json",
            {
                "state": "done",
                "input_hash": "abc",
                "exit_code": 0 if status == "passed" else 1,
                "execution": "fresh",
                "unit": unit_dict(
                    id=uid,
                    entry_id="etcd-v2-exhaustive",
                    kind="exhaustive",
                    target="etcd-cluster",
                    seed=None,
                    variant_name=f"cell{idx:03d}",
                    execution_index=idx,
                ),
            },
        )
        write_json(
            root,
            f"raw/{uid}/run.json",
            {"id": uid, "target": "etcd-cluster", "status": status},
        )
        forced = {".services.etcd.extraConf.QUOTA_BACKEND_BYTES": quota_index}
        write_json(root, f"raw/{uid}/choices.json", {"configChoices": {"etcd": forced}})
        write_json(
            root,
            f"raw/{uid}/resolved.json",
            {
                "roleFuzz": {
                    "etcd": {
                        # The seed's draw — the same for every cell.
                        "choices": {".services.etcd.extraConf.QUOTA_BACKEND_BYTES": 2},
                        "result": {
                            "services": {
                                "etcd": {
                                    "extraConf": {
                                        "QUOTA_BACKEND_BYTES": str(self.QUOTA_BYTES[quota_index])
                                    }
                                }
                            }
                        },
                    }
                }
            },
        )

    def test_cells_report_their_forced_config_and_real_quota(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_cell(root, 0, 0, "failed")  # 2 MiB
            self._make_cell(root, 1, 1, "passed")  # 8 MiB
            self._make_cell(root, 2, 2, "passed")  # 64 MiB
            analyze.run_all(root, collect(root))
            data = read_json(root / "analysis" / "etcd-v2-exhaustive.json")

            configs = [c["config"] for c in data["per_cell"]]
            self.assertEqual(len({json.dumps(c, sort_keys=True) for c in configs}), 3)
            self.assertEqual(
                [c["quota_backend_bytes"] for c in data["per_cell"]], list(self.QUOTA_BYTES)
            )
            # The failure is attributed to the cell's OWN quota, not the seed's.
            self.assertEqual(data["failures_by_quota_index"], {"0": 1})
            self.assertEqual(data["failures_by_quota_bytes"], {"2097152": 1})
            self.assertEqual(
                data["cells_by_quota_bytes"],
                {"2097152": 1, "67108864": 1, "8388608": 1},
            )

    def test_cell_without_properties_is_not_a_configuration_failure(self):
        """A cell that dies before any property runs (0 checks — e.g. the
        test driver's "Shell did not start in time") says nothing about its
        configuration. Counting it as a quota failure attributed an
        infrastructure timeout at 8 MiB to the quota dimension."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_cell(root, 0, 0, "failed")  # 2 MiB: property failure
            self._make_cell(root, 1, 1, "passed")
            self._make_cell(root, 2, 2, "passed")
            self._make_cell(root, 3, 1, "failed")  # 8 MiB: infrastructure, below
            write_json(
                root,
                "raw/cell-unit-3/run.json",
                {
                    "id": "cell-unit-3",
                    "target": "etcd-cluster",
                    "status": "failed",
                    "summary": {"passed": 0, "failed": 0, "total": 0},
                },
            )
            analyze.run_all(root, collect(root))
            data = read_json(root / "analysis" / "etcd-v2-exhaustive.json")

            self.assertEqual(data["failed"], 1)
            self.assertEqual(data["passed"], 2)
            self.assertEqual(data["no_property_verdict"], 1)
            self.assertEqual(data["no_property_verdict_cells"], ["cell003"])
            # The infrastructure failure is NOT attributed to 8 MiB.
            self.assertEqual(data["failures_by_quota_bytes"], {"2097152": 1})
            outcomes = {c["cell"]: c["outcome"] for c in data["per_cell"]}
            self.assertEqual(outcomes["cell000"], "property-failed")
            self.assertEqual(outcomes["cell003"], "no-property-verdict")

    def test_cell_that_never_started_has_no_property_verdict(self):
        # The --seed None shape: status.json only, no run.json at all.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_cell(root, 0, 0, "failed")
            (root / "raw" / "cell-unit-0" / "run.json").unlink()
            analyze.run_all(root, collect(root))
            data = read_json(root / "analysis" / "etcd-v2-exhaustive.json")
            self.assertEqual((data["passed"], data["failed"]), (0, 0))
            self.assertEqual(data["no_property_verdict_cells"], ["cell000"])
            self.assertEqual(data["failures_by_quota_bytes"], {})


class ParallelismMeasureTests(unittest.TestCase):
    """Speedup is a ratio of group wall-clock SPANS. Summing per-unit wall
    times cannot measure parallelism: concurrency does not shrink that sum."""

    def _make_group(self, root: Path, entry: str, uid_prefix: str, spans):
        for i, (start, wall) in enumerate(spans):
            uid = f"{uid_prefix}-{i}"
            make_rabbit_unit(root, uid, entry_id=entry)
            write_json(
                root,
                f"raw/{uid}/timing.json",
                {"wall_s": wall, "started_epoch": start, "finished_epoch": start + wall},
            )

    def test_span_based_speedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Serial: 4 x 100 s back to back -> span 400 s.
            self._make_group(
                root,
                "rabbitmq-disk-serial",
                "ser",
                [(0.0, 100.0), (100.0, 100.0), (200.0, 100.0), (300.0, 100.0)],
            )
            # Parallel: the same 4 units overlapping -> span 100 s.  The sum
            # of unit wall times is 400 s in BOTH groups; only the span moves.
            self._make_group(
                root,
                "rabbitmq-disk",
                "par",
                [(1000.0, 100.0), (1000.0, 100.0), (1000.0, 100.0), (1000.0, 100.0)],
            )
            analyze.run_all(root, collect(root))
            data = read_json(root / "analysis" / "parallelism.json")
            self.assertEqual(data["serial"]["group_wall_s"], "400")
            self.assertEqual(data["parallel"]["group_wall_s"], "100")
            self.assertEqual(data["speedup"], "4")

    def test_unequal_group_sizes_leave_speedup_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_group(root, "rabbitmq-disk-serial", "ser", [(0.0, 100.0), (100.0, 100.0)])
            self._make_group(
                root,
                "rabbitmq-disk",
                "par",
                [(1000.0, 100.0), (1000.0, 100.0), (1000.0, 100.0)],
            )
            analyze.run_all(root, collect(root))
            data = read_json(root / "analysis" / "parallelism.json")
            self.assertIsNone(data["speedup"])
            self.assertIn("different unit counts", data["note"])
            self.assertIsNotNone(data["throughput_ratio_per_unit"])


if __name__ == "__main__":
    unittest.main()
