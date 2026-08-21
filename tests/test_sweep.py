"""Tests for sweep --resume and sweep --json.

These tests are unit-level: they exercise `find_existing_seeds` directly, and
drive `sweep_events` and `cmd_sweep` with a mocked `run_once` so no `nix build`
is ever invoked. The end-to-end behaviour of a real sweep over 50 seeds is
covered by the thesis evaluation run, not by these tests.
"""

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from typing import Optional
from unittest.mock import patch

# Make the topotestix package importable when running from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from topotestix.orchestrator import cmd_sweep, find_existing_seeds, sweep_events
from topotestix.run_store import RunStore
from topotestix.targets import Target


@dataclass
class _StubResult:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _make_target(name: str = "kafka-cluster") -> Target:
    return Target(
        name=name,
        description="test target",
        topology_target="/dev/null/topo.nix",
        config_target="/dev/null/config.nix",
        base_module="/dev/null/module.nix",
        test_script="/dev/null/test-script.py",
        properties="/dev/null/properties.nix",
        report_node="node1",
    )


def _make_args(
    seeds: str,
    *,
    resume: bool = False,
    json_mode: bool = False,
    quiet: bool = False,
    name: Optional[str] = None,
    output_dir: Optional[str] = None,
    fail_fast: bool = False,
    jobs: int = 1,
) -> argparse.Namespace:
    return argparse.Namespace(
        target="kafka-cluster",
        seeds=seeds,
        resume=resume,
        json=json_mode,
        quiet=quiet,
        name=name,
        output_dir=output_dir,
        fail_fast=fail_fast,
        jobs=jobs,
        topology_target=None,
        config_target=None,
        base_module=None,
        test_script=None,
        properties=None,
        project_root=os.getcwd(),
    )


def _record_completed_run(
    store: RunStore, target_name: str, seed: int, status: str = "passed"
) -> None:
    run = store.create_run(target_name, seed, f"{target_name}-seed-{seed}")
    store.write_json(
        run["dir"],
        "run.json",
        {
            "id": run["id"],
            "target": target_name,
            "seed": seed,
            "status": status,
            "summary": {
                "passed": 1 if status == "passed" else 0,
                "failed": 0 if status == "passed" else 1,
                "total": 1,
            },
        },
    )


# --- find_existing_seeds ----------------------------------------------------


class FindExistingSeedsTests(unittest.TestCase):
    def test_returns_seeds_with_completed_run_for_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            for seed in (3, 7):
                _record_completed_run(store, "kafka-cluster", seed)
            target = _make_target("kafka-cluster")
            self.assertEqual(find_existing_seeds(store, target, [3, 4, 5, 6, 7]), {3, 7})

    def test_ignores_runs_for_other_targets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            _record_completed_run(store, "nginx", 3)
            target = _make_target("kafka-cluster")
            self.assertEqual(find_existing_seeds(store, target, [3, 4]), set())

    def test_empty_when_no_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            target = _make_target("kafka-cluster")
            self.assertEqual(find_existing_seeds(store, target, [1, 2, 3]), set())

    def test_only_returns_seeds_in_query_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            _record_completed_run(store, "kafka-cluster", 3)
            _record_completed_run(store, "kafka-cluster", 99)
            target = _make_target("kafka-cluster")
            self.assertEqual(find_existing_seeds(store, target, [1, 2, 3]), {3})

    def test_includes_failed_runs(self):
        # --resume skips both passed and failed runs; user must delete
        # the run dir to force a re-run.
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            _record_completed_run(store, "kafka-cluster", 5, status="failed")
            target = _make_target("kafka-cluster")
            self.assertEqual(find_existing_seeds(store, target, [5]), {5})


# --- sweep_events resume behaviour ------------------------------------------


def _stub_run_once_factory(report: list[dict]):
    """Return a function that mimics run_once: records every call and returns a
    canned passed=True result for each seed."""

    calls: list[int] = []

    def _stub(project_root, target, seed, name, runs_dir=None, **kwargs):
        calls.append(seed)
        report.append({"seed": seed, "name": name})
        run_dir = os.path.join(runs_dir or "/tmp", f"stub-{seed}")
        return (
            True,
            [{"name": f"stub-property-seed-{seed}", "status": "passed"}],
            run_dir,
            _StubResult(returncode=0),
        )

    return _stub, calls


class SweepEventsResumeTests(unittest.TestCase):
    def test_default_does_not_skip_any_seed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            _record_completed_run(store, "kafka-cluster", 3)
            target = _make_target("kafka-cluster")
            stub, calls = _stub_run_once_factory([])
            with patch("topotestix.orchestrator.run_once", side_effect=stub):
                events = list(sweep_events(os.getcwd(), target, [1, 2, 3, 4], runs_dir=tmpdir))
            # All four seeds were run; no skip events.
            self.assertEqual(sorted(calls), [1, 2, 3, 4])
            self.assertEqual([e.type for e in events if e.type == "run_skipped"], [])

    def test_resume_skips_seeds_with_existing_run(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            _record_completed_run(store, "kafka-cluster", 2)
            _record_completed_run(store, "kafka-cluster", 4)
            target = _make_target("kafka-cluster")
            stub, calls = _stub_run_once_factory([])
            with patch("topotestix.orchestrator.run_once", side_effect=stub):
                events = list(
                    sweep_events(os.getcwd(), target, [1, 2, 3, 4, 5], runs_dir=tmpdir, resume=True)
                )
            # Only seeds 1, 3, 5 actually executed.
            self.assertEqual(sorted(calls), [1, 3, 5])
            skipped_events = [e for e in events if e.type == "run_skipped"]
            self.assertEqual([e.data["seed"] for e in skipped_events], [2, 4])
            finished = [e for e in events if e.type == "sweep_finished"][0]
            self.assertEqual(finished.data["skipped"], 2)

    def test_resume_off_does_not_consult_run_store(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            _record_completed_run(store, "kafka-cluster", 3)
            target = _make_target("kafka-cluster")
            stub, calls = _stub_run_once_factory([])
            with patch("topotestix.orchestrator.run_once", side_effect=stub):
                list(sweep_events(os.getcwd(), target, [3], runs_dir=tmpdir, resume=False))
            self.assertEqual(calls, [3])


# --- cmd_sweep --json output mode -------------------------------------------


class CmdSweepJsonTests(unittest.TestCase):
    def test_json_output_is_valid_json_with_expected_shape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = _make_target("kafka-cluster")
            args = _make_args("1..3", json_mode=True, output_dir=tmpdir)
            stub, _ = _stub_run_once_factory([])
            with (
                patch("topotestix.orchestrator.get_cli_target", return_value=target),
                patch("topotestix.orchestrator.run_once", side_effect=stub),
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cmd_sweep(args, os.getcwd())
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(
                sorted(payload.keys()),
                [
                    "avgRunTime",
                    "classifications",
                    "completed",
                    "failed",
                    "failures",
                    "jobs",
                    "skipped",
                    "target",
                    "total",
                    "totalTime",
                ],
            )
            self.assertEqual(payload["target"], "kafka-cluster")
            self.assertEqual(payload["total"], 3)
            self.assertEqual(payload["completed"], 3)
            self.assertEqual(payload["skipped"], 0)
            self.assertEqual(payload["failed"], 0)
            self.assertEqual(payload["failures"], [])
            self.assertEqual(payload["jobs"], 1)
            self.assertIsInstance(payload["totalTime"], (int, float))
            self.assertIsInstance(payload["avgRunTime"], (int, float))

    def test_json_output_records_failures(self):
        def _mixed_stub(project_root, target, seed, name, runs_dir=None, **kwargs):
            run_dir = os.path.join(runs_dir or "/tmp", f"stub-{seed}")
            if seed == 2:
                return (
                    False,
                    [{"name": f"p-{seed}", "status": "failed", "message": "boom"}],
                    run_dir,
                    _StubResult(returncode=1),
                )
            return (
                True,
                [{"name": f"p-{seed}", "status": "passed"}],
                run_dir,
                _StubResult(returncode=0),
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            target = _make_target("kafka-cluster")
            args = _make_args("1..3", json_mode=True, output_dir=tmpdir)
            with (
                patch("topotestix.orchestrator.get_cli_target", return_value=target),
                patch("topotestix.orchestrator.run_once", side_effect=_mixed_stub),
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cmd_sweep(args, os.getcwd())
            self.assertEqual(rc, 1)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["failed"], 1)
            self.assertEqual(payload["completed"], 3)
            self.assertEqual(len(payload["failures"]), 1)
            self.assertEqual(payload["failures"][0]["seed"], 2)
            self.assertEqual(payload["failures"][0]["returncode"], 1)
            self.assertTrue(payload["failures"][0]["runDir"].endswith("stub-2"))

    def test_json_output_reflects_resume_skips(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            _record_completed_run(store, "kafka-cluster", 1)
            _record_completed_run(store, "kafka-cluster", 3)
            target = _make_target("kafka-cluster")
            args = _make_args("1..4", json_mode=True, output_dir=tmpdir, resume=True)
            stub, _ = _stub_run_once_factory([])
            with (
                patch("topotestix.orchestrator.get_cli_target", return_value=target),
                patch("topotestix.orchestrator.run_once", side_effect=stub),
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cmd_sweep(args, os.getcwd())
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["total"], 4)
            self.assertEqual(payload["completed"], 2)
            self.assertEqual(payload["skipped"], 2)
            self.assertEqual(payload["failed"], 0)
            self.assertEqual(payload["failures"], [])

    def test_json_mode_suppresses_streaming_human_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = _make_target("kafka-cluster")
            args = _make_args("1..2", json_mode=True, output_dir=tmpdir)
            stub, _ = _stub_run_once_factory([])
            with (
                patch("topotestix.orchestrator.get_cli_target", return_value=target),
                patch("topotestix.orchestrator.run_once", side_effect=stub),
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    cmd_sweep(args, os.getcwd())
            # stdout must be pure JSON (plus whitespace) — no "PASS"/"FAIL" lines.
            stdout = buf.getvalue()
            self.assertNotIn("PASS", stdout)
            self.assertNotIn("FAIL", stdout)
            self.assertNotIn("Running", stdout)
            # And it must still parse as a single JSON object.
            json.loads(stdout)


# --- CLI parser --------------------------------------------------------------


class CliParserTests(unittest.TestCase):
    def test_sweep_parser_accepts_resume_flag(self):
        from topotestix.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["orchestrator", "sweep", "kafka-cluster", "--seeds", "1..5", "--resume"]
        )
        self.assertTrue(args.resume)

    def test_sweep_parser_resume_defaults_to_false(self):
        from topotestix.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["orchestrator", "sweep", "kafka-cluster", "--seeds", "1..5"])
        self.assertFalse(args.resume)

    def test_sweep_parser_accepts_json_flag(self):
        from topotestix.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["orchestrator", "sweep", "kafka-cluster", "--seeds", "1..5", "--json"]
        )
        self.assertTrue(args.json)

    def test_sweep_parser_accepts_jobs_flag(self):
        from topotestix.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["orchestrator", "sweep", "kafka-cluster", "--seeds", "1..5", "--jobs", "4"]
        )
        self.assertEqual(args.jobs, 4)

    def test_sweep_parser_jobs_defaults_to_one(self):
        from topotestix.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["orchestrator", "sweep", "kafka-cluster", "--seeds", "1..5"])
        self.assertEqual(args.jobs, 1)


# --- sequential timing & labels -------------------------------------------


class SequentialTimingLabelTests(unittest.TestCase):
    def test_run_events_carry_elapsed_and_label(self):
        target = _make_target()
        stub, calls = _stub_run_once_factory([])
        with patch("topotestix.orchestrator.run_once", side_effect=stub):
            events = list(sweep_events(os.getcwd(), target, [1, 2], runs_dir="/tmp/tt-seq"))
        run_events = [e for e in events if e.type in {"run_passed", "run_failed"}]
        self.assertEqual(len(run_events), 2)
        for e in run_events:
            self.assertIn("elapsed", e.data)
            self.assertIsInstance(e.data["elapsed"], float)
            self.assertIn("(seed=", e.message)
            self.assertIn("/", e.message)
        finished = [e for e in events if e.type == "sweep_finished"][0]
        self.assertIn("totalTime", finished.data)
        self.assertIn("avgRunTime", finished.data)

    def test_avg_run_time_is_mean_of_elapsed(self):
        target = _make_target()
        elapseds = []

        def _stub(project_root, target, seed, name, runs_dir=None, **kwargs):
            import time as _time

            d = 0.01 * seed
            _time.sleep(d)
            elapseds.append(d)
            run_dir = os.path.join(runs_dir or "/tmp", f"stub-{seed}")
            return True, [{"name": f"p-{seed}", "status": "passed"}], run_dir, _StubResult()

        with patch("topotestix.orchestrator.run_once", side_effect=_stub):
            events = list(sweep_events(os.getcwd(), target, [1, 2, 3], runs_dir="/tmp/tt-avg"))
        finished = [e for e in events if e.type == "sweep_finished"][0]
        run_events = [e for e in events if e.type in {"run_passed", "run_failed"}]
        self.assertEqual(len(run_events), 3)
        expected_avg = sum(e.data["elapsed"] for e in run_events) / 3
        self.assertAlmostEqual(finished.data["avgRunTime"], expected_avg, places=2)
        self.assertGreater(finished.data["totalTime"], 0.0)

    def test_zero_completed_avg_is_zero(self):
        # All seeds skipped via resume -> no runs complete -> avgRunTime == 0.
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            for s in (1, 2, 3):
                _record_completed_run(store, "kafka-cluster", s)
            target = _make_target()
            stub, _ = _stub_run_once_factory([])
            with patch("topotestix.orchestrator.run_once", side_effect=stub):
                events = list(
                    sweep_events(os.getcwd(), target, [1, 2, 3], runs_dir=tmpdir, resume=True)
                )
        finished = [e for e in events if e.type == "sweep_finished"][0]
        self.assertEqual(finished.data["completed"], 0)
        self.assertEqual(finished.data["avgRunTime"], 0.0)
        self.assertEqual(finished.data["skipped"], 3)


# --- parallel sweep --------------------------------------------------------


def _inverted_sleep_stub(report):
    """A run_once stub whose duration is *inverted* by seed, so that higher
    seeds finish before lower ones — completion order != submission order.
    Records the seed of every call in `report`."""

    def _stub(project_root, target, seed, name, runs_dir=None, **kwargs):
        import time as _time

        # seed 1 sleeps longest, seed 4 sleeps least -> 4 finishes first.
        _time.sleep(0.04 * (5 - seed))
        report.append(seed)
        run_dir = os.path.join(runs_dir or "/tmp", f"stub-{seed}")
        return True, [{"name": f"p-{seed}", "status": "passed"}], run_dir, _StubResult()

    return _stub


class ParallelSweepTests(unittest.TestCase):
    def test_all_seeds_run_and_results_correct(self):
        target = _make_target()
        completed_order: list[int] = []
        stub = _inverted_sleep_stub(completed_order)
        with patch("topotestix.orchestrator.run_once", side_effect=stub):
            events = list(
                sweep_events(os.getcwd(), target, [1, 2, 3, 4], runs_dir="/tmp/tt-par", jobs=3)
            )
        run_events = [e for e in events if e.type in {"run_passed", "run_failed"}]
        self.assertEqual(len(run_events), 4)
        self.assertEqual(sorted(e.data["seed"] for e in run_events), [1, 2, 3, 4])
        # All passed.
        self.assertTrue(all(e.type == "run_passed" for e in run_events))
        finished = [e for e in events if e.type == "sweep_finished"][0]
        self.assertEqual(finished.data["completed"], 4)
        self.assertEqual(finished.data["skipped"], 0)
        self.assertEqual(finished.data["failures"], 0)

    def test_parallel_emits_run_started_per_seed(self):
        # Regression: the parallel path must emit run_started for every
        # submitted seed (not just completion events), matching the sequential
        # event contract that cmd_sweep relies on for progress lines.
        target = _make_target()
        stub, _ = _stub_run_once_factory([])
        with patch("topotestix.orchestrator.run_once", side_effect=stub):
            events = list(
                sweep_events(os.getcwd(), target, [1, 2, 3, 4], runs_dir="/tmp/tt-started", jobs=2)
            )
        started = [e for e in events if e.type == "run_started"]
        self.assertEqual(len(started), 4)
        self.assertEqual(sorted(e.data["seed"] for e in started), [1, 2, 3, 4])
        for e in started:
            self.assertIn("(seed=", e.message)
            self.assertIn("/", e.message)

    def test_completion_order_differs_from_submission_order(self):
        # With inverted sleep, seed 4 should finish before seed 1, so the
        # first run_passed event should not be seed 1.
        target = _make_target()
        order: list[int] = []
        stub = _inverted_sleep_stub(order)
        with patch("topotestix.orchestrator.run_once", side_effect=stub):
            events = list(
                sweep_events(os.getcwd(), target, [1, 2, 3, 4], runs_dir="/tmp/tt-ord", jobs=4)
            )
        run_events = [e for e in events if e.type in {"run_passed", "run_failed"}]
        first_seed = run_events[0].data["seed"]
        self.assertNotEqual(first_seed, 1)

    def test_completion_indices_are_one_through_n(self):
        target = _make_target()
        order: list[int] = []
        stub = _inverted_sleep_stub(order)
        with patch("topotestix.orchestrator.run_once", side_effect=stub):
            events = list(
                sweep_events(os.getcwd(), target, [1, 2, 3, 4], runs_dir="/tmp/tt-idx", jobs=4)
            )
        run_events = [e for e in events if e.type in {"run_passed", "run_failed"}]
        # Extract the [i/total ...] label's i value from each message.
        labels = []
        for e in run_events:
            after_bracket = e.message.split("[", 1)[1]
            i_str = after_bracket.split("/", 1)[0]
            labels.append(int(i_str))
        self.assertEqual(sorted(labels), [1, 2, 3, 4])

    def test_concurrency_actually_happens(self):
        # A stub that tracks the peak number of simultaneously active calls.
        # With jobs>=2 and a small sleep, peak concurrency must be >= 2.
        import threading as _t

        target = _make_target()
        active = 0
        peak = 0
        lock = _t.Lock()

        def _stub(project_root, target, seed, name, runs_dir=None, **kwargs):
            import time as _time

            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            _time.sleep(0.02)
            with lock:
                active -= 1
            run_dir = os.path.join(runs_dir or "/tmp", f"stub-{seed}")
            return True, [{"name": f"p-{seed}", "status": "passed"}], run_dir, _StubResult()

        with patch("topotestix.orchestrator.run_once", side_effect=_stub):
            list(sweep_events(os.getcwd(), target, [1, 2, 3, 4], runs_dir="/tmp/tt-conc", jobs=3))
        self.assertGreaterEqual(peak, 2)

    def test_parallel_timing_fields_present(self):
        target = _make_target()
        order: list[int] = []
        stub = _inverted_sleep_stub(order)
        with patch("topotestix.orchestrator.run_once", side_effect=stub):
            events = list(
                sweep_events(os.getcwd(), target, [1, 2, 3], runs_dir="/tmp/tt-ptm", jobs=2)
            )
        run_events = [e for e in events if e.type in {"run_passed", "run_failed"}]
        for e in run_events:
            self.assertIn("elapsed", e.data)
            self.assertGreaterEqual(e.data["elapsed"], 0.0)
        finished = [e for e in events if e.type == "sweep_finished"][0]
        self.assertIn("totalTime", finished.data)
        self.assertIn("avgRunTime", finished.data)
        # Wall clock should be less than the sum of durations (runs overlapped).
        sum_elapsed = sum(e.data["elapsed"] for e in run_events)
        self.assertGreaterEqual(sum_elapsed, finished.data["totalTime"])

    def test_parallel_fail_fast_no_extra_submissions_after_failure(self):
        # Finding 1 regression: a refilled seed that fails quickly must be
        # observed immediately (via wait(FIRST_COMPLETED)), not hidden behind
        # an as_completed(snapshot) of the prior batch. If hidden, extra seeds
        # would be submitted after the failure is already known.
        #
        # Setup: jobs=2, seeds 1..6. Seed 1 sleeps long; seed 2 finishes fast
        # (pass) → refill submits seed 3, which fails immediately. Seed 3's
        # failure must stop further submissions before seed 1 finishes.
        import time as _time

        target = _make_target()
        ran: list[int] = []

        def _stub(project_root, target, seed, name, runs_dir=None, **kwargs):
            ran.append(seed)
            if seed == 1:
                _time.sleep(0.08)  # slow, still in-flight when seed 3 fails
            run_dir = os.path.join(runs_dir or "/tmp", f"stub-{seed}")
            passed = seed != 3
            return (
                passed,
                [{"name": f"p-{seed}", "status": "passed" if passed else "failed"}],
                run_dir,
                _StubResult(returncode=0 if passed else 1),
            )

        with patch("topotestix.orchestrator.run_once", side_effect=_stub):
            events = list(
                sweep_events(
                    os.getcwd(),
                    target,
                    [1, 2, 3, 4, 5, 6],
                    runs_dir="/tmp/tt-ff1",
                    fail_fast=True,
                    jobs=2,
                )
            )
        run_events = [e for e in events if e.type in {"run_passed", "run_failed"}]
        finished = [e for e in events if e.type == "sweep_finished"][0]
        # Only seeds 1, 2, 3 were started (primed 1+2, refilled 3). No 4/5/6.
        self.assertEqual(sorted(ran), [1, 2, 3])
        # Every started seed got an event (including slow seed 1, drained after
        # fail-fast).
        self.assertEqual(sorted(e.data["seed"] for e in run_events), [1, 2, 3])
        self.assertEqual(finished.data["completed"], 3)
        self.assertEqual(finished.data["failures"], 1)

    def test_parallel_fail_fast_drains_in_flight_results(self):
        # Finding 2 regression: after fail-fast, in-flight (running) futures
        # cannot be cancelled and must still have their results emitted and
        # counted — not silently dropped.
        #
        # A threading.Event barrier guarantees seed 2's worker has entered the
        # stub before seed 1 fails — a bare sleep cannot guarantee this under
        # scheduling jitter, which made the earlier version flaky.
        import threading as _t

        target = _make_target()
        ran: list[int] = []
        seed2_started = _t.Event()

        def _stub(project_root, target, seed, name, runs_dir=None, **kwargs):
            ran.append(seed)
            if seed == 2:
                seed2_started.set()  # signal: seed 2 is now running
            if seed == 1:
                # Block until seed 2 is actually running, then fail fast.
                seed2_started.wait(timeout=2.0)
            run_dir = os.path.join(runs_dir or "/tmp", f"stub-{seed}")
            passed = seed != 1
            return (
                passed,
                [{"name": f"p-{seed}", "status": "passed" if passed else "failed"}],
                run_dir,
                _StubResult(returncode=0 if passed else 1),
            )

        with patch("topotestix.orchestrator.run_once", side_effect=_stub):
            events = list(
                sweep_events(
                    os.getcwd(),
                    target,
                    [1, 2, 3, 4],
                    runs_dir="/tmp/tt-ff2",
                    fail_fast=True,
                    jobs=2,
                )
            )
        run_events = [e for e in events if e.type in {"run_passed", "run_failed"}]
        finished = [e for e in events if e.type == "sweep_finished"][0]
        # Seeds 1 and 2 primed; seed 1 fails, seed 2 is in-flight (running).
        # Seed 2 must be drained and its result emitted (not dropped).
        self.assertIn(2, [e.data["seed"] for e in run_events])
        # completed counts every emitted run, including the drained in-flight.
        self.assertEqual(finished.data["completed"], len(run_events))
        self.assertGreaterEqual(finished.data["completed"], 2)
        self.assertEqual(finished.data["failures"], 1)

    def test_parallel_resume_skips_then_runs_rest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = RunStore(tmpdir)
            _record_completed_run(store, "kafka-cluster", 2)
            target = _make_target()
            ran: list[int] = []

            def _stub(project_root, target, seed, name, runs_dir=None, **kwargs):
                ran.append(seed)
                run_dir = os.path.join(runs_dir or tmpdir, f"stub-{seed}")
                return True, [{"name": f"p-{seed}", "status": "passed"}], run_dir, _StubResult()

            with patch("topotestix.orchestrator.run_once", side_effect=_stub):
                events = list(
                    sweep_events(
                        os.getcwd(), target, [1, 2, 3, 4], runs_dir=tmpdir, resume=True, jobs=2
                    )
                )
        skip_events = [e for e in events if e.type == "run_skipped"]
        self.assertEqual([e.data["seed"] for e in skip_events], [2])
        self.assertEqual(sorted(ran), [1, 3, 4])
        finished = [e for e in events if e.type == "sweep_finished"][0]
        self.assertEqual(finished.data["skipped"], 1)
        self.assertEqual(finished.data["completed"], 3)


# --- cmd_sweep --jobs end-to-end (mocked) -----------------------------------


class CmdSweepJobsTests(unittest.TestCase):
    def test_jobs_flag_threads_through_to_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = _make_target()
            args = _make_args("1..3", json_mode=True, output_dir=tmpdir, jobs=2)
            stub, _ = _stub_run_once_factory([])
            with (
                patch("topotestix.orchestrator.get_cli_target", return_value=target),
                patch("topotestix.orchestrator.run_once", side_effect=stub),
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cmd_sweep(args, os.getcwd())
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["jobs"], 2)
            self.assertEqual(payload["completed"], 3)

    def test_human_summary_includes_timing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = _make_target()
            args = _make_args("1..2", output_dir=tmpdir, jobs=1)
            stub, _ = _stub_run_once_factory([])
            with (
                patch("topotestix.orchestrator.get_cli_target", return_value=target),
                patch("topotestix.orchestrator.run_once", side_effect=stub),
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    cmd_sweep(args, os.getcwd())
            out = buf.getvalue()
            self.assertIn("total ", out)
            self.assertIn("avg ", out)
            self.assertIn("s", out)


if __name__ == "__main__":
    unittest.main()
