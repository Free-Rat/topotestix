"""Tests for experiments/reproduce/__main__.py — campaign CLI orchestration.

These tests never launch nix/VMs: heavy phases are monkeypatched to no-ops or
fakes, and only the lock/token flow and run-phase error handling are
exercised in-process against tmp dirs.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

from experiments.reproduce import env
from experiments.reproduce import runner as runner_mod

main_mod = importlib.import_module("experiments.reproduce.__main__")

REPO_ROOT = str(Path(__file__).resolve().parent.parent)

MANIFEST_TEXT = json.dumps(
    {
        "entries": [
            {
                "id": "etcd-run",
                "kind": "run",
                "target": "etcd-cluster",
                "seeds": [1, 2],
                "produces": ["etcd-v2-sweep"],
            }
        ]
    }
)


def _write_manifest(tmp_path: Path) -> str:
    path = tmp_path / "MANIFEST.json"
    path.write_text(MANIFEST_TEXT, encoding="utf-8")
    return str(path)


def _write_lock(out_dir: Path, token: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    lock = {
        "campaign_token": token,
        "provenance": {
            "written_at": "2026-09-04T00:00:00+00:00",
            "framework": {"rev": "0" * 40, "dirty": False},
            "manifest": {"path": "MANIFEST.json", "sha256": "0" * 64},
        },
        "manifest_sha256": "0" * 64,
    }
    (out_dir / "MANIFEST.lock.json").write_text(json.dumps(lock, indent=2), encoding="utf-8")


def _expect_system_exit(fn) -> SystemExit:
    try:
        fn()
    except SystemExit as exc:
        return exc
    raise AssertionError("expected SystemExit")


class _MainCase(unittest.TestCase):
    """tmp dir, attribute patching and stdout/stderr capture for each test."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_path = Path(tmp.name)

    def patch(self, obj, name, value) -> None:
        patcher = unittest.mock.patch.object(obj, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def capture(self, fn):
        """Run fn(); return (result, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = fn()
        return result, out.getvalue(), err.getvalue()

    def stub_downstream_phases(self, captured: dict, run_failed: int = 0) -> None:
        def fake_phase_run(args, units):
            captured["units"] = list(units)
            return run_failed

        def record(name):
            return lambda *a: captured.setdefault("called", []).append(name)

        self.patch(main_mod, "phase_run", fake_phase_run)
        self.patch(main_mod, "phase_analyze", record("analyze"))
        self.patch(
            main_mod,
            "phase_verify",
            lambda args: {"match": 0, "within-tolerance": 0, "mismatch": 0, "not-reproduced": 0},
        )
        self.patch(main_mod, "phase_report", record("report"))

    def counting_mint(self) -> list:
        calls: list = []

        def fake_mint(explicit=None):
            token = explicit if explicit is not None else f"c-test-{len(calls):04d}"
            calls.append(token)
            return token

        self.patch(env, "mint_campaign_token", fake_mint)
        return calls

    def main_argv(self, out: Path, mpath: str, *extra: str) -> list:
        return ["--out", str(out), "--manifest", mpath, "--project-root", REPO_ROOT, *extra]


class TestPhaseLockOnce(_MainCase):
    def test_fresh_token_all_remints_exactly_once(self):
        out = self.tmp_path / "out"
        _write_lock(out, "c-original")
        mpath = _write_manifest(self.tmp_path)
        minted = self.counting_mint()
        captured: dict = {}
        self.stub_downstream_phases(captured)

        rc, _, _ = self.capture(
            lambda: main_mod.main(self.main_argv(out, mpath, "--phase", "all", "--fresh-token"))
        )
        self.assertEqual(rc, 0)
        # phase_lock must re-mint exactly once, not once in the guard and once
        # again in the phase dispatch.
        self.assertEqual(len(minted), 1)
        stored = env.read_campaign_token(out)
        self.assertEqual(stored, minted[0])
        # The token units executed with must be the token left in the lock,
        # otherwise the next invocation re-runs the whole campaign.
        self.assertTrue(captured["units"], "manifest should expand to at least one unit")
        for u in captured["units"]:
            self.assertEqual(u.repetition_token, stored)

    def test_fresh_run_all_locks_exactly_once(self):
        out = self.tmp_path / "out"
        _write_lock(out, "c-original")
        mpath = _write_manifest(self.tmp_path)
        lock_calls: list = []
        self.patch(main_mod, "phase_lock", lambda args: lock_calls.append(1))
        self.stub_downstream_phases({})

        rc = main_mod.main(self.main_argv(out, mpath, "--phase", "all", "--fresh"))
        self.assertEqual(rc, 0)
        self.assertEqual(len(lock_calls), 1)

    def test_phase_lock_alone_still_locks(self):
        out = self.tmp_path / "out"
        _write_lock(out, "c-original")
        mpath = _write_manifest(self.tmp_path)
        lock_calls: list = []
        self.patch(main_mod, "phase_lock", lambda args: lock_calls.append(1))
        self.stub_downstream_phases({})

        rc = main_mod.main(self.main_argv(out, mpath, "--phase", "lock"))
        self.assertEqual(rc, 0)
        self.assertEqual(len(lock_calls), 1)

    def test_all_without_lock_locks_once_via_guard(self):
        out = self.tmp_path / "out"
        out.mkdir()
        mpath = _write_manifest(self.tmp_path)
        lock_calls: list = []
        self.patch(main_mod, "phase_lock", lambda args: lock_calls.append(1))
        self.stub_downstream_phases({})

        rc, _, _ = self.capture(lambda: main_mod.main(self.main_argv(out, mpath, "--phase", "all")))
        self.assertEqual(rc, 0)
        self.assertEqual(len(lock_calls), 1)


class TestExitCode(_MainCase):
    def _setup(self, run_failed: int) -> tuple:
        out = self.tmp_path / "out"
        _write_lock(out, "c-original")
        mpath = _write_manifest(self.tmp_path)
        self.patch(main_mod, "phase_lock", lambda args: None)
        self.patch(env, "check_lock", lambda *a: [])
        captured: dict = {}
        self.stub_downstream_phases(captured, run_failed=run_failed)
        return out, mpath, captured

    def test_run_with_failed_unit_returns_1(self):
        out, mpath, _ = self._setup(run_failed=1)
        self.assertEqual(main_mod.main(self.main_argv(out, mpath, "--phase", "run")), 1)

    def test_all_with_failed_unit_still_analyzes_then_returns_1(self):
        out, mpath, captured = self._setup(run_failed=2)
        self.assertEqual(main_mod.main(self.main_argv(out, mpath, "--phase", "all")), 1)
        self.assertEqual(captured["called"], ["analyze", "report"])

    def test_all_without_failures_returns_0(self):
        out, mpath, _ = self._setup(run_failed=0)
        self.assertEqual(main_mod.main(self.main_argv(out, mpath, "--phase", "all")), 0)


class TestPhaseRunErrorHandling(_MainCase):
    def _args(self, jobs: int, prune_stale: bool = False) -> SimpleNamespace:
        return SimpleNamespace(
            out=str(self.tmp_path / "out"),
            manifest=_write_manifest(self.tmp_path),
            project_root=REPO_ROOT,
            allow_small_disk=True,
            force=False,
            jobs=jobs,
            prune_stale=prune_stale,
        )

    def _units(self, args) -> list:
        return main_mod.manifest.expand_all(main_mod.manifest.load_manifest(args.manifest), "rev")

    def _run_with(self, jobs: int, outcome_seed1) -> tuple:
        """phase_run over seeds 1-2; seed 1 raises or returns outcome_seed1."""
        args = self._args(jobs)
        (self.tmp_path / "out").mkdir()
        seen = []

        def fake_run_unit(unit, out, project_root, force=False, **kwargs):
            seen.append(unit.seed)
            if unit.seed == 1:
                if isinstance(outcome_seed1, Exception):
                    raise outcome_seed1
                return outcome_seed1
            return {"state": "done"}

        self.patch(runner_mod, "run_unit", fake_run_unit)
        self.patch(main_mod, "phase_digest", lambda args: None)
        failed, out, err = self.capture(lambda: main_mod.phase_run(args, self._units(args)))
        self.assertEqual(sorted(seen), [1, 2])
        return failed, out, err

    def test_serial_run_continues_past_raising_unit(self):
        failed, _, err = self._run_with(1, ValueError("no matching test modules"))
        self.assertEqual(failed, 1)
        self.assertIn("-> failed (no matching test modules)", err)
        self.assertIn("1 unit(s) raised and were recorded as failed", err)

    def test_parallel_run_continues_past_raising_unit(self):
        failed, out, err = self._run_with(2, ValueError("no matching test modules"))
        self.assertEqual(failed, 1)
        self.assertIn("-> failed (no matching test modules)", err)
        combined = out + err
        self.assertIn("[1/2]", combined)
        self.assertIn("[2/2]", combined)
        self.assertIn("-> done", out)  # the healthy unit still reported normally

    def test_serial_counts_failed_status_without_exception(self):
        failed, _, err = self._run_with(1, {"state": "failed", "error": "timed out after 1s"})
        self.assertEqual(failed, 1)
        self.assertIn("1 unit(s) failed", err)
        self.assertNotIn("raised", err)

    def test_parallel_counts_failed_status_without_exception(self):
        failed, _, err = self._run_with(2, {"state": "failed", "error": "command exited 2"})
        self.assertEqual(failed, 1)
        self.assertIn("1 unit(s) failed", err)

    def test_prune_removes_partial_and_stale_dirs(self):
        args = self._args(jobs=1)
        self.patch(main_mod, "framework_rev_of", lambda a: "rev")
        raw_root = self.tmp_path / "out" / "raw"
        planned_id = self._units(args)[0].id
        for name in (
            f"{planned_id}.partial",
            f"{planned_id}.stale",
            "0000000000000000",  # stale raw dir not in the manifest
            planned_id,  # planned unit artifact — must survive
        ):
            (raw_root / name).mkdir(parents=True)

        def must_not_run(*a, **k):
            raise AssertionError("run_unit must not be called: no units selected")

        self.patch(runner_mod, "run_unit", must_not_run)
        self.patch(main_mod, "phase_digest", lambda args: None)
        # no selected units: exercise pruning only
        _, _, err = self.capture(lambda: main_mod.phase_run(args, []))

        self.assertTrue((raw_root / planned_id).is_dir())
        self.assertFalse((raw_root / f"{planned_id}.partial").exists())
        self.assertFalse((raw_root / f"{planned_id}.stale").exists())
        self.assertFalse((raw_root / "0000000000000000").exists())
        self.assertIn(f"pruned partial staging dir: {planned_id}.partial", err)
        self.assertIn(f"pruned stale staging dir: {planned_id}.stale", err)

    def test_prune_refuses_to_wipe_a_whole_campaign(self):
        """unit.id folds in the framework revision, so a commit/checkout
        re-keys every planned unit at once. Deleting there would destroy the
        campaign's evidence (including the gitignored *.log files), so the
        run phase must refuse instead."""
        args = self._args(jobs=1)
        self.patch(main_mod, "framework_rev_of", lambda a: "some-other-rev")
        raw_root = self.tmp_path / "out" / "raw"
        for name in ("1111111111111111", "2222222222222222"):
            (raw_root / name).mkdir(parents=True)

        raised = _expect_system_exit(lambda: main_mod.phase_run(args, []))

        self.assertIn("prune guard", str(raised))
        self.assertTrue((raw_root / "1111111111111111").is_dir())
        self.assertTrue((raw_root / "2222222222222222").is_dir())

    def test_prune_stale_forces_the_wipe(self):
        args = self._args(jobs=1, prune_stale=True)
        self.patch(main_mod, "framework_rev_of", lambda a: "some-other-rev")
        self.patch(main_mod, "phase_digest", lambda args: None)
        raw_root = self.tmp_path / "out" / "raw"
        (raw_root / "1111111111111111").mkdir(parents=True)

        self.capture(lambda: main_mod.phase_run(args, []))

        self.assertFalse((raw_root / "1111111111111111").exists())


class TestPhaseReport(_MainCase):
    def test_report_alone_reads_the_claims_matrix(self):
        """Without verify in the same invocation the in-memory summary is
        empty; the report must come from claims-matrix.csv rather than
        overwriting a real report with an all-zero headline."""
        out = self.tmp_path / "out"
        (out / "verification").mkdir(parents=True)
        (out / "verification" / "claims-matrix.csv").write_text(
            "claim_id,location,expected,observed,verdict,artifact,reason\n"
            "k-01,06-evaluation.typ:1,x,x,match,analysis/kafka-sweep.json,\n"
            "m-01,06-evaluation.typ:2,y,y,informational-observed,,\n",
            encoding="utf-8",
        )
        args = SimpleNamespace(out=str(out), manifest=_write_manifest(self.tmp_path))
        self.capture(lambda: main_mod.phase_report(args, {"match": 0, "mismatch": 0}))

        text = (out / "verification" / "VERIFICATION_REPORT.md").read_text(encoding="utf-8")
        self.assertIn("| match | 1 |", text)
        self.assertIn("| informational-observed | 1 |", text)
        self.assertIn("| total | 2 |", text)

    def test_report_alone_without_a_matrix_refuses(self):
        out = self.tmp_path / "out"
        out.mkdir()
        args = SimpleNamespace(out=str(out), manifest=_write_manifest(self.tmp_path))
        _expect_system_exit(lambda: main_mod.phase_report(args, {}))
        self.assertFalse((out / "verification" / "VERIFICATION_REPORT.md").exists())


class TestPhaseDigest(_MainCase):
    def test_digest_backfills_and_drops_line_count_phases(self):
        out = self.tmp_path / "out"
        unit_dir = out / "raw" / "aaaaaaaaaaaaaaaa"
        trial = unit_dir / "run-store" / "trial-1"
        trial.mkdir(parents=True)
        (unit_dir / "stdout.log").write_text("Ran 57 tests in 1.0s\nOK\n", encoding="utf-8")
        (unit_dir / "trials.json").write_text('[{"dir": "trial-1"}]', encoding="utf-8")
        (trial / "stdout.log").write_text(
            "these 58 derivations will be built\netcd: error: boom\n", encoding="utf-8"
        )
        (unit_dir / "timing.json").write_text(
            json.dumps({"wall_s": 222.0, "phases": {"build": 7233, "vm_boot": -4}}),
            encoding="utf-8",
        )

        self.capture(lambda: main_mod.phase_digest(SimpleNamespace(out=str(out))))

        digest = json.loads((unit_dir / "log-digest.json").read_text(encoding="utf-8"))
        self.assertIn("Ran 57 tests in 1.0s", digest["streams"]["stdout"]["lines"])
        self.assertIn("etcd: error: boom", digest["streams"]["final_trial_console"]["lines"])
        timing = json.loads((unit_dir / "timing.json").read_text(encoding="utf-8"))
        self.assertNotIn("phases", timing)  # line counts were never seconds
        self.assertEqual(timing["phase_markers"]["build"]["first_line"], 0)
        self.assertEqual(timing["wall_s"], 222.0)


class TestArgValidation(_MainCase):
    def _rejected(self, *argv: str) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            exc = _expect_system_exit(lambda: main_mod.main([*argv, "--phase", "dry-run"]))
        self.assertEqual(exc.code, 2)
        self.assertIn("must be >= 1", err.getvalue())

    def test_jobs_zero_rejected(self):
        self._rejected("--jobs", "0")

    def test_unit_timeout_zero_rejected(self):
        self._rejected("--unit-timeout", "0")


if __name__ == "__main__":
    unittest.main()
