"""Tests for experiments/reproduce/report.py — deterministic rendering.

Asserted invariants:
  - VERIFICATION_REPORT.md renders from a fake summary without crashing and
    contains headline counts, per-group sections, execution accounting,
    discrepancies, determinism, and the idempotency marker;
  - outputs are byte-identical across re-runs;
  - the discrepancies section lists every non-match row (and only those);
  - README.md renders and is deterministic.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from experiments.reproduce.report import write_readme, write_verification_report
from tests.test_reproduce_verify import build_fake_analysis, write_json

FAKE_SUMMARY = {
    "match": 2,
    "within-tolerance": 1,
    "mismatch": 1,
    "not-reproduced": 1,
    "informational": 1,
    "rows": [
        {
            "claim_id": "k-01",
            "location": "06-evaluation.typ:98",
            "expected": "13/37",
            "observed": "13 pass / 37 fail of 50 seeds",
            "verdict": "match",
            "artifact": "analysis/kafka-sweep.json",
            "reason": "",
        },
        {
            "claim_id": "e2-05",
            "location": "06-evaluation.typ:214",
            "expected": "0/13/13",
            "observed": "0/13/13 (quota 2097152)",
            "verdict": "within-tolerance",
            "artifact": "analysis/etcd-v2-quota-correlation.csv",
            "reason": "",
        },
        {
            "claim_id": "r-26",
            "location": "appendix.typ:148",
            "expected": "two cells x2",
            "observed": "follower=1; leader=1",
            "verdict": "mismatch",
            "artifact": "analysis/rabbitmq-crash-cells.csv",
            "reason": "execution counts differ",
        },
        {
            "claim_id": "e2-11",
            "location": "06-evaluation.typ:225",
            "expected": "identical",
            "observed": "",
            "verdict": "not-reproduced",
            "artifact": "analysis/etcd-v2-shrink.json",
            "reason": "artifact analysis/etcd-v2-shrink.json missing",
        },
        {
            "claim_id": "m-08",
            "location": "06-evaluation.typ:379",
            "expected": "summary",
            "observed": "kafka 13/37, flips=0",
            "verdict": "informational-observed",
            "artifact": "analysis/kafka-sweep.json",
            "reason": "",
        },
        {
            "claim_id": "k-30",
            "location": "06-evaluation.typ:357",
            "expected": "zero",
            "observed": "flips=0",
            "verdict": "match",
            "artifact": "analysis/determinism.json",
            "reason": "",
        },
    ],
}


class ReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-report-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        build_fake_analysis(self.tmp)
        write_json(
            self.tmp,
            "resolution/etcd-cluster/uniqueness.json",
            {
                "target": "etcd-cluster",
                "space_size": 96,
                "seeds": 50,
                "unique_resolved": 48,
                "duplicate_rate": "0.04",
                "collisions": [],
            },
        )
        self.report_path = self.tmp / "verification" / "VERIFICATION_REPORT.md"

    def test_report_renders_and_contains_sections(self):
        write_verification_report(self.tmp, FAKE_SUMMARY)
        text = self.report_path.read_text(encoding="utf-8")
        for needle in (
            "# Verification report",
            "## Headline counts",
            "## Kafka claims",
            "## RabbitMQ claims",
            "## Execution accounting",
            "## Discrepancies",
            "## Determinism (per-seed flips across repetitions)",
        ):
            self.assertIn(needle, text)
        self.assertNotIn("{IDEMPOTENCY_RESULT}", text)
        self.assertIn("kafka-cluster", text)  # accounting group table
        self.assertIn("etcd-cluster", text)  # uniqueness table
        self.assertIn("unique_resolved", text.replace("Unique resolved", "unique_resolved"))
        self.assertIn("| match | 2 |", text)
        self.assertIn("| total | 6 |", text)

    def test_headline_counts_every_verdict_including_informational(self):
        """Counts come from the rows, not from the summary's own key
        spelling: "informational" vs the INFO verdict constant silently
        pinned that row to 0 while the matrix held informational rows."""
        write_verification_report(self.tmp, FAKE_SUMMARY)
        text = self.report_path.read_text(encoding="utf-8")
        self.assertIn("| informational-observed | 1 |", text)
        self.assertIn("| not-reproduced | 1 |", text)
        self.assertIn("| within-tolerance | 1 |", text)
        self.assertIn("| mismatch | 1 |", text)

    def test_counts_ignore_disagreeing_summary_totals(self):
        summary = dict(FAKE_SUMMARY, match=99, informational=0, **{"not-reproduced": 0})
        write_verification_report(self.tmp, summary)
        text = self.report_path.read_text(encoding="utf-8")
        self.assertIn("| match | 2 |", text)
        self.assertIn("| informational-observed | 1 |", text)

    def test_rows_fall_back_to_the_claims_matrix(self):
        """`--phase report` alone has no in-memory rows; the matrix on disk
        is the source, so the real report is not overwritten with zeros."""
        matrix_dir = self.tmp / "verification"
        matrix_dir.mkdir(parents=True, exist_ok=True)
        (matrix_dir / "claims-matrix.csv").write_text(
            "claim_id,location,expected,observed,verdict,artifact,reason\n"
            "k-01,06-evaluation.typ:98,13/37,13/37,match,analysis/kafka-sweep.json,\n"
            "m-08,06-evaluation.typ:379,summary,summary,informational-observed,,\n",
            encoding="utf-8",
        )
        write_verification_report(self.tmp, {})
        text = self.report_path.read_text(encoding="utf-8")
        self.assertIn("| match | 1 |", text)
        self.assertIn("| informational-observed | 1 |", text)
        self.assertIn("| total | 2 |", text)

    def test_discrepancies_list_exactly_non_matches(self):
        write_verification_report(self.tmp, FAKE_SUMMARY)
        text = self.report_path.read_text(encoding="utf-8")
        disc = text.split("## Discrepancies", 1)[1].split("## Determinism", 1)[0]
        self.assertIn("`r-26` [mismatch]", disc)
        self.assertIn("`e2-11` [not-reproduced]", disc)
        self.assertIn("analysis/rabbitmq-crash-cells.csv", disc)
        self.assertIn("analysis/etcd-v2-shrink.json", disc)
        for matched in ("`k-01`", "`e2-05`", "`m-08`", "`k-30`"):
            self.assertNotIn(matched, disc)
        self.assertNotIn("speculat", disc.lower())

    def test_determinism_headline_on_nonzero_flips(self):
        write_json(
            self.tmp,
            "analysis/determinism.json",
            {
                "kafka-sweep": {"present": True, "flips": 3, "seed_diffs": [{"seed": 7}]},
            },
        )
        write_verification_report(self.tmp, FAKE_SUMMARY)
        text = self.report_path.read_text(encoding="utf-8")
        self.assertIn("**Headline finding:**", text)
        self.assertIn("kafka-sweep: 3", text)

    def test_report_byte_identical_on_rerun(self):
        write_verification_report(self.tmp, FAKE_SUMMARY)
        first = self.report_path.read_bytes()
        write_verification_report(self.tmp, FAKE_SUMMARY)
        second = self.report_path.read_bytes()
        self.assertEqual(first, second)

    def test_report_renders_from_empty_out_dir(self):
        empty = self.tmp / "empty-out"
        empty.mkdir()
        summary = dict(FAKE_SUMMARY, rows=[])
        write_verification_report(empty, summary)
        text = (empty / "verification" / "VERIFICATION_REPORT.md").read_text(encoding="utf-8")
        self.assertIn("missing; no accounting data", text)
        self.assertIn("missing; no flip data", text)

    def test_readme_renders_and_deterministic(self):
        write_readme(self.tmp, "experiments/reproduce/MANIFEST.json")
        path = self.tmp / "README.md"
        first = path.read_bytes()
        self.assertIn("python3 -m experiments.reproduce", first.decode("utf-8"))
        self.assertIn("--phase all", first.decode("utf-8"))
        self.assertIn("not-reproduced", first.decode("utf-8"))
        write_readme(self.tmp, "experiments/reproduce/MANIFEST.json")
        self.assertEqual(first, path.read_bytes())

    def test_no_timestamps_in_report_or_readme(self):
        write_verification_report(self.tmp, FAKE_SUMMARY)
        write_readme(self.tmp, "experiments/reproduce/MANIFEST.json")
        for path in (self.report_path, self.tmp / "README.md"):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"20\d{6}", text), path.name)
            self.assertNotIn("generated at", text.lower())


if __name__ == "__main__":
    unittest.main()
