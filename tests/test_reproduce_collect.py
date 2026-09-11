"""Tests for experiments/reproduce/collect.py — fake campaign tree fixtures."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.reproduce.collect import Collected, collect

REPO_ROOT = Path(__file__).resolve().parent.parent


def write_json(root: Path, rel: str, obj) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def unit_dict(**overrides):
    unit = {
        "config_choices": None,
        "config_target": None,
        "entry_hash": "h",
        "entry_id": "kafka-sweep",
        "execution_index": 0,
        "id": "unit-x",
        "kind": "sweep",
        "produces": [],
        "repetition_index": 0,
        "run_name": "kafka-sweep-rep0-seed1",
        "seed": 1,
        "target": "kafka-cluster",
        "test_script": None,
        "topology_choices": None,
        "topology_target": None,
        "base_module": None,
        "properties": None,
        "variant_name": None,
    }
    unit.update(overrides)
    return unit


def make_kafka_unit(root: Path, uid: str, seed: int, status: str, failed_check=None):
    report = [{"name": "kafka-roundtrip", "status": "passed"}]
    summary = {"passed": 1, "failed": 0, "total": 1}
    if failed_check:
        report = [
            {
                "name": failed_check,
                "status": "failed",
                "message": "boom RecordBatchTooLargeException",
            },
            {"name": "kafka-roundtrip", "status": "passed"},
        ]
        summary = {"passed": 1, "failed": 1, "total": 2}
    write_json(
        root,
        f"raw/{uid}/status.json",
        {
            "state": "done",
            "input_hash": "abc",
            "exit_code": 0,
            "execution": "fresh",
            "unit": unit_dict(id=uid, seed=seed),
        },
    )
    write_json(
        root,
        f"raw/{uid}/run.json",
        {
            "id": uid,
            "target": "kafka-cluster",
            "seed": seed,
            "status": status,
            "summary": summary,
        },
    )
    write_json(root, f"raw/{uid}/report.json", report)
    write_json(
        root,
        f"raw/{uid}/resolved.json",
        {
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
        },
    )
    write_json(root, f"raw/{uid}/timing.json", {"wall_s": 10.5})
    write_json(root, f"raw/{uid}/resources.json", {"peak_rss_bytes": 100, "cpu_seconds": 1.0})
    write_json(root, f"raw/{uid}/nix-build.json", {"execution": "fresh", "markers": []})
    write_text(root, f"raw/{uid}/stdout.log", "")
    write_text(root, f"raw/{uid}/stderr.log", "nix warnings only")


def make_rabbit_unit(root: Path, uid: str, entry_id: str = "rabbitmq-disk"):
    write_json(
        root,
        f"raw/{uid}/status.json",
        {
            "state": "done",
            "input_hash": "abc",
            "exit_code": 1,
            "execution": "fresh",
            "unit": unit_dict(
                id=uid,
                entry_id=entry_id,
                seed=1,
                variant_name="cell-x",
                kind="run",
                target="rabbitmq-disk",
            ),
        },
    )
    write_json(
        root,
        f"raw/{uid}/run.json",
        {
            "id": uid,
            "target": "rabbitmq-disk",
            "seed": 1,
            "status": "failed",
            "summary": {"passed": 4, "failed": 1, "total": 5},
        },
    )
    write_json(
        root,
        f"raw/{uid}/report.json",
        [
            {
                "name": "rabbitmq-disk-capacity-confirmation-contract",
                "status": "failed",
                "message": "capacity contract violated",
            },
            {"name": "rabbitmq-disk-confirmed-recovered-exactly-once", "status": "passed"},
        ],
    )
    write_json(
        root,
        f"raw/{uid}/disk-results.json",
        {
            "schema_version": 1,
            "contract": {"capacity_sufficient": False, "naive_capacity_sufficient": True},
            "operations": [
                {"op_id": "a", "outcome": "ambiguous"},
                {"op_id": "b", "outcome": "ambiguous"},
                {"op_id": "c", "outcome": "confirmed"},
            ],
            "telemetry": [
                {"node": "rabbit1", "disk_free_alarm": True},
                {"node": "rabbit1", "disk_free_alarm": False},
            ],
            "recovered": [{"message_id": "b"}],
        },
    )


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-collect-"))
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_collect_fake_tree(self):
        root = self.tmp
        make_kafka_unit(root, "unit-a", 1, "passed")
        make_kafka_unit(root, "unit-b", 2, "failed", failed_check="kafka-large-message")
        make_rabbit_unit(root, "unit-c")
        write_json(
            root,
            "raw/unit-d/status.json",
            {"state": "done", "unit": unit_dict(id="unit-d", seed=3)},
        )
        write_json(
            root,
            "resolution/kafka-cluster/uniqueness.json",
            {"space_size": 746496, "unique_resolved": 50},
        )
        write_text(
            root, "resolution/kafka-cluster/marginals.csv", "dimension,resolved_value,count\n"
        )

        collected = collect(root)
        self.assertIsInstance(collected, Collected)
        self.assertEqual(len(collected.units), 4)
        self.assertEqual(len(collected.by_entry["kafka-sweep"]), 3)
        self.assertEqual(len(collected.by_entry["rabbitmq-disk"]), 1)
        # merged record fields: unit lifted from status.json, files by stem
        rec_a = next(r for r in collected.units if r["id"] == "unit-a")
        self.assertEqual(rec_a["unit"]["entry_id"], "kafka-sweep")
        self.assertEqual(rec_a["run"]["status"], "passed")
        self.assertEqual(rec_a["timing"]["wall_s"], 10.5)
        self.assertEqual(rec_a["nix-build"]["execution"], "fresh")
        self.assertIn("nix warnings", rec_a["stderr"])
        # missing files => keys absent, never fabricated
        rec_d = next(r for r in collected.units if r["id"] == "unit-d")
        self.assertNotIn("run", rec_d)
        self.assertNotIn("report", rec_d)
        self.assertNotIn("timing", rec_d)
        self.assertEqual(rec_d["unit"]["seed"], 3)
        # evidence payload captured under evidence/
        rec_c = next(r for r in collected.units if r["id"] == "unit-c")
        self.assertIn("disk-results.json", rec_c["evidence"])
        self.assertEqual(len(rec_c["evidence"]["disk-results.json"]["operations"]), 3)
        # resolution block captured
        self.assertEqual(
            collected.resolution["kafka-cluster"]["uniqueness.json"]["space_size"], 746496
        )
        self.assertIn("marginals.csv", collected.resolution["kafka-cluster"])

    def test_trials_json_picked_up_and_run_store_dir_ignored(self):
        root = self.tmp
        make_kafka_unit(root, "unit-e", 9, "failed", failed_check="kafka-large-message")
        write_json(
            root,
            "raw/unit-e/trials.json",
            [
                {"dir": "20260904-1", "execution": "fresh", "markers": [], "status": "passed"},
                {"dir": "20260904-2", "execution": "fresh", "markers": [], "status": "failed"},
            ],
        )
        # The full per-trial data (run-store/<trial>/...) is a directory tree,
        # not a file — _collect_unit_dir must ignore it, never crash on it,
        # and never surface it as "evidence" (it is read from disk directly by
        # anyone who wants it, not loaded into the in-memory Collected record).
        write_text(root, "raw/unit-e/run-store/20260904-1/stdout.log", "big build log")
        write_json(root, "raw/unit-e/run-store/20260904-1/run.json", {"status": "passed"})

        collected = collect(root)
        rec = next(r for r in collected.units if r["id"] == "unit-e")
        self.assertEqual(len(rec["trials"]), 2)
        self.assertEqual(rec["trials"][1]["status"], "failed")
        self.assertNotIn("run-store", rec["evidence"])
        self.assertNotIn("run-store.json", rec)

    def test_stale_and_partial_dirs_never_collected(self):
        # A kill mid-promotion leaves the pre-swap copy under <id>.stale/
        # (runner._promote); phase_run prunes it, but an analyze-only run must
        # never collect it as a phantom/duplicate unit record — same rule as
        # in-flight <id>.partial/ staging dirs.
        root = self.tmp
        make_kafka_unit(root, "unit-live", 1, "passed")
        make_kafka_unit(root, "unit-live.stale", 1, "passed")
        make_kafka_unit(root, "unit-live.partial", 1, "passed")
        collected = collect(root)
        self.assertEqual([r["id"] for r in collected.units], ["unit-live"])
        self.assertEqual(len(collected.by_entry["kafka-sweep"]), 1)

    def test_collect_empty_and_missing_dirs(self):
        collected = collect(self.tmp)  # nothing exists at all
        self.assertEqual(collected.units, [])
        self.assertEqual(collected.by_entry, {})
        self.assertEqual(collected.resolution, {})
        (self.tmp / "raw").mkdir()
        (self.tmp / "resolution").mkdir()
        collected = collect(self.tmp)
        self.assertEqual(collected.units, [])

    def test_log_digest_stands_in_for_absent_logs(self):
        """The *.log files are gitignored, so a fresh clone has only
        log-digest.json. Analysis must still see the log-derived evidence."""
        root = self.tmp
        make_kafka_unit(root, "unit-digest", 1, "passed")
        write_json(
            root,
            "raw/unit-digest/log-digest.json",
            {
                "version": 1,
                "streams": {
                    "stdout": {"total_lines": 900, "truncated": True, "lines": ["Ran 57 tests"]},
                    "stderr": {"total_lines": 0, "truncated": False, "lines": []},
                    "final_trial_console": {
                        "total_lines": 900,
                        "truncated": True,
                        "lines": ["etcd1: error: boom"],
                    },
                },
            },
        )
        rec = next(r for r in collect(root).units if r["id"] == "unit-digest")
        self.assertEqual(rec["stdout"], "Ran 57 tests")
        self.assertEqual(rec["final_trial_console_digest"], "etcd1: error: boom")
        self.assertEqual(rec["log_source"]["stdout"], "digest")

    def test_real_logs_win_over_the_digest(self):
        root = self.tmp
        make_kafka_unit(root, "unit-both", 1, "passed")
        write_text(root, "raw/unit-both/stdout.log", "the real log\n")
        write_json(
            root,
            "raw/unit-both/log-digest.json",
            {"version": 1, "streams": {"stdout": {"lines": ["digest line"]}}},
        )
        rec = next(r for r in collect(root).units if r["id"] == "unit-both")
        self.assertEqual(rec["stdout"], "the real log\n")
        self.assertEqual(rec["log_source"]["stdout"], "log")

    def test_collect_tolerates_bad_json(self):
        d = self.tmp / "raw" / "unit-bad"
        d.mkdir(parents=True)
        (d / "status.json").write_text("{not json", encoding="utf-8")
        (d / "run.json").write_text("[]", encoding="utf-8")  # valid but not a unit
        collected = collect(self.tmp)
        self.assertEqual(len(collected.units), 1)
        rec = collected.units[0]
        self.assertNotIn("status", rec)
        self.assertEqual(rec["run"], [])


if __name__ == "__main__":
    unittest.main()
