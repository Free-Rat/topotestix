"""Tests for experiments/reproduce/runner.py — pure logic only, no real runs.

These tests never launch nix/VMs: subprocess is monkeypatched to fail loudly,
and only command construction, skip logic, marker classification, and status
writing are exercised.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

from experiments.reproduce import runner
from experiments.reproduce.models import Unit, canonical_hash

REPO_ROOT = str(Path(__file__).resolve().parent.parent)


def make_unit(**overrides) -> Unit:
    fields = dict(
        id="deadbeef00000000",
        entry_id="entry",
        kind="run",
        target="nginx",
        seed=1,
        repetition_index=0,
        execution_index=0,
        variant_name=None,
        topology_choices=None,
        config_choices=None,
        config_target=None,
        topology_target=None,
        base_module=None,
        test_script=None,
        properties=None,
        produces=[],
        run_name="entry-rep0",
        entry_hash="0" * 64,
    )
    fields.update(overrides)
    return Unit(**fields)


def forbid_subprocess(*_args, **_kwargs):
    raise AssertionError("subprocess.run/Popen must not be invoked in this test")


class BuildCommandSweepTest(unittest.TestCase):
    def test_sweep_shape(self):
        unit = make_unit(
            kind="sweep", target="kafka-cluster", seed=5, run_name="kafka-sweep-rep0-seed5"
        )
        cmd = runner.build_command(unit, REPO_ROOT)
        self.assertIsInstance(cmd, list)
        self.assertNotIn("sudo", cmd)
        self.assertEqual(
            cmd[:8],
            ["nix", "develop", "-c", "python3", "-m", "topotestix.cli", "orchestrator", "run"],
        )
        self.assertIn("kafka-cluster", cmd)
        self.assertEqual(cmd[cmd.index("--seed") + 1], "5")
        self.assertEqual(cmd[cmd.index("--name") + 1], "kafka-sweep-rep0-seed5")
        self.assertEqual(cmd[cmd.index("--project-root") + 1], REPO_ROOT)
        self.assertIn("--json", cmd)
        self.assertNotIn("--topology-choices", cmd)
        self.assertNotIn("--config-choices", cmd)

    def test_run_with_choices_and_overrides(self):
        unit = make_unit(
            kind="run",
            target="rabbitmq-disk",
            seed=1,
            topology_choices={"roles": 3},
            config_choices={"rabbit": {".a.b": 0}},
            topology_target="targets/rabbitmq-disk/topology.nix",
            config_target="targets/rabbitmq-disk/config.nix",
            base_module="targets/rabbitmq-disk/module.nix",
            test_script="targets/rabbitmq-disk/test-script.py",
            properties="targets/rabbitmq-disk/properties.nix",
        )
        cmd = runner.build_command(unit, REPO_ROOT)
        self.assertEqual(cmd[cmd.index("--topology-choices") + 1], '{"roles":3}')
        self.assertEqual(cmd[cmd.index("--config-choices") + 1], '{"rabbit":{".a.b":0}}')
        for flag in (
            "--topology-target",
            "--config-target",
            "--base-module",
            "--test-script",
            "--properties",
        ):
            self.assertIn(flag, cmd)
        # sorted keys => canonical JSON
        self.assertEqual(cmd[cmd.index("--topology-choices") + 1], '{"roles":3}')

    def test_seed_flag_omitted_when_the_unit_has_no_seed(self):
        """Exhaustive cells expand with seed=None. "--seed None" makes the
        CLI's argparse (type=int) abort with exit code 2 before it starts."""
        cmd = runner.build_command(
            make_unit(kind="exhaustive", target="etcd-cluster", seed=None), REPO_ROOT
        )
        self.assertNotIn("--seed", cmd)
        self.assertNotIn("None", cmd)
        # The rest of the invocation is unchanged.
        self.assertEqual(cmd[cmd.index("orchestrator") + 1], "run")
        self.assertIn("--json", cmd)

    def test_shrink_without_a_seed_raises(self):
        # shrink takes the seed as a required positional: no default to use.
        with self.assertRaises(ValueError):
            runner.build_command(
                make_unit(kind="shrink", target="kafka-cluster", seed=None), REPO_ROOT
            )

    def test_choices_absent_when_none(self):
        cmd = runner.build_command(make_unit(kind="exhaustive", target="etcd-cluster"), REPO_ROOT)
        self.assertNotIn("--topology-choices", cmd)
        self.assertNotIn("--config-target", cmd)
        self.assertNotIn("--properties", cmd)

    def test_shrink_arg_order(self):
        unit = make_unit(
            kind="shrink", target="kafka-cluster", seed=9, run_name="kafka-shrink-rep0-seed9"
        )
        cmd = runner.build_command(unit, REPO_ROOT)
        i = cmd.index("orchestrator")
        self.assertEqual(cmd[i + 1], "shrink")
        self.assertEqual(cmd[i + 2], "kafka-cluster")
        self.assertEqual(cmd[i + 3], "9")
        self.assertEqual(cmd[cmd.index("--name") + 1], "kafka-shrink-rep0-seed9")

    def test_output_dir_flag(self):
        # run/sweep path.
        cmd = runner.build_command(
            make_unit(kind="run", target="nginx"), REPO_ROOT, Path("/out/raw/x/run-store")
        )
        self.assertEqual(cmd[cmd.index("--output-dir") + 1], "/out/raw/x/run-store")
        # shrink path.
        cmd = runner.build_command(
            make_unit(kind="shrink", target="kafka-cluster", seed=9),
            REPO_ROOT,
            Path("/out/raw/y/run-store"),
        )
        self.assertEqual(cmd[cmd.index("--output-dir") + 1], "/out/raw/y/run-store")
        # absent by default (no output_dir given).
        self.assertNotIn(
            "--output-dir", runner.build_command(make_unit(kind="run", target="nginx"), REPO_ROOT)
        )

    def test_repetition_token_flag(self):
        # run/sweep path: --repetition-token appears, once, with its value.
        cmd = runner.build_command(
            make_unit(kind="run", target="nginx", repetition_token="c20260904-abcdef"),
            REPO_ROOT,
        )
        self.assertEqual(cmd.count("--repetition-token"), 1)
        self.assertEqual(cmd[cmd.index("--repetition-token") + 1], "c20260904-abcdef")
        # shrink path carries it too.
        scmd = runner.build_command(
            make_unit(
                kind="shrink",
                target="kafka-cluster",
                seed=9,
                run_name="kafka-shrink-rep0-seed9",
                repetition_token="c20260904-abcdef",
            ),
            REPO_ROOT,
        )
        self.assertIn("--repetition-token", scmd)
        # absent by default.
        self.assertNotIn(
            "--repetition-token",
            runner.build_command(make_unit(kind="run", target="nginx"), REPO_ROOT),
        )

    def test_repetition_token_changes_input_hash_not_unit_id(self):
        base = make_unit()
        toked = make_unit(repetition_token="c20260904-abcdef")
        # unit.id is caller-supplied here, but the point is the token rides in
        # to_dict()/input_hash, not in the plan-§3 identity payload.
        self.assertNotEqual(
            runner.unit_input_hash(base, REPO_ROOT), runner.unit_input_hash(toked, REPO_ROOT)
        )
        self.assertEqual(base.id, toked.id)

    def test_test_suites_variants(self):
        py = runner.build_command(make_unit(kind="test_suites", variant_name="python"), REPO_ROOT)
        self.assertEqual(py[:4], ["nix", "develop", "-c", "python3"])
        # Framework test modules only (harness's own tests excluded); the
        # -c loader puts tests/ on sys.path before loading the names.
        self.assertEqual(py[4], "-c")
        self.assertIn("'test_cli'", py[5])
        self.assertNotIn("test_reproduce", py[5])
        self.assertIn("sys.path.insert(0, 'tests')", py[5])
        nix = runner.build_command(make_unit(kind="test_suites", variant_name="nix"), REPO_ROOT)
        self.assertEqual(nix[:4], ["nix", "develop", "-c", "nix-unit"])
        self.assertIn("import ./tests { lib = (import <nixpkgs> {}).lib; }", nix)

    def test_fuzz_only_is_empty_and_never_invoked(self):
        self.assertEqual(runner.build_command(make_unit(kind="fuzz_only"), REPO_ROOT), [])

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            runner.build_command(make_unit(kind="bogus"), REPO_ROOT)

    def test_missing_target_raises(self):
        with self.assertRaises(ValueError):
            runner.build_command(make_unit(kind="run", target=None), REPO_ROOT)


class SkipLogicTest(unittest.TestCase):
    def test_done_matching_hash_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit = make_unit()
            raw_dir = Path(tmp) / "raw" / unit.id
            raw_dir.mkdir(parents=True)
            status = {"state": "done", "input_hash": canonical_hash(unit.to_dict())}
            (raw_dir / "status.json").write_text(json.dumps(status))
            self.assertEqual(runner.should_skip(raw_dir, unit, force=False), status)

    def test_hash_mismatch_does_not_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit = make_unit()
            raw_dir = Path(tmp) / "raw" / unit.id
            raw_dir.mkdir(parents=True)
            status = {"state": "done", "input_hash": "stale"}
            (raw_dir / "status.json").write_text(json.dumps(status))
            self.assertIsNone(runner.should_skip(raw_dir, unit, force=False))

    def test_failed_state_does_not_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit = make_unit()
            raw_dir = Path(tmp) / "raw" / unit.id
            raw_dir.mkdir(parents=True)
            status = {"state": "failed", "input_hash": canonical_hash(unit.to_dict())}
            (raw_dir / "status.json").write_text(json.dumps(status))
            self.assertIsNone(runner.should_skip(raw_dir, unit, force=False))

    def test_force_revalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit = make_unit()
            raw_dir = Path(tmp) / "raw" / unit.id
            raw_dir.mkdir(parents=True)
            status = {"state": "done", "input_hash": canonical_hash(unit.to_dict())}
            (raw_dir / "status.json").write_text(json.dumps(status))
            self.assertIsNone(runner.should_skip(raw_dir, unit, force=True))

    def test_missing_or_corrupt_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp) / "raw" / "x"
            self.assertIsNone(runner.should_skip(raw_dir, make_unit(id="x"), force=False))
            raw_dir.mkdir(parents=True)
            (raw_dir / "status.json").write_text("{not json")
            self.assertIsNone(runner.should_skip(raw_dir, make_unit(id="x"), force=False))


class StatusWriteTest(unittest.TestCase):
    def test_atomic_write_and_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            partial = Path(tmp)
            runner.write_status(partial, {"state": "done", "input_hash": "abc"})
            data = json.loads((partial / "status.json").read_text())
            self.assertEqual(data["state"], "done")
            leftovers = [n for n in tmp if n.endswith(".tmp")]
            self.assertEqual(leftovers, [])


class ClassifyExecutionTest(unittest.TestCase):
    def test_fresh(self):
        out = (
            "building '/nix/store/abc-vm-test-run-x.drv.drv'...\n"
            "these 3 derivations will be built:\n"
        )
        label, markers = runner.classify_execution(out)
        self.assertEqual(label, "fresh")
        self.assertGreater(len(markers), 0)

    def test_fresh_from_the_summary_line_alone(self):
        """Nix's plural summary line on its own must read as a fresh build.
        The old pattern spelled the alternative "this(ese)?", which matches
        "this" or "thisese" but never "these", so a build that printed only
        the summary was misfiled as cache-replay."""
        for line in (
            "these 58 derivations will be built:",
            "this derivation will be built:",
        ):
            label, markers = runner.classify_execution(line + "\n")
            self.assertEqual(label, "fresh", line)
            self.assertEqual(markers, [line])

    def test_substituted(self):
        out = "copying path '/nix/store/abc' from 'https://cache.nixos.org'...\n"
        label, markers = runner.classify_execution(out)
        self.assertEqual(label, "substituted")

    def test_default_returned_when_no_markers(self):
        # No marker yields whatever default the caller passes; run_unit always
        # passes "unknown", since an absent marker never proves a cache replay.
        label, _ = runner.classify_execution(
            "warning: netrc-file...\nno build lines here\n", default="cache-replay"
        )
        self.assertEqual(label, "cache-replay")

    def test_unknown_when_no_markers(self):
        label, _ = runner.classify_execution("no build lines here\n")
        self.assertEqual(label, "unknown")

    def test_markers_capped_at_20(self):
        out = "".join(f"building '/nix/store/{i}-x.drv'\n" for i in range(30))
        _, markers = runner.classify_execution(out)
        self.assertEqual(len(markers), 20)


class LogDigestTest(unittest.TestCase):
    """log-digest.json is the committed stand-in for the gitignored *.log
    files that analyze.py reads."""

    def test_keeps_salient_lines_from_a_huge_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit_dir = Path(tmp)
            trial = unit_dir / "run-store" / "t1"
            trial.mkdir(parents=True)
            noise = "".join(f"padding line {i}\n" for i in range(5000))
            (unit_dir / "stdout.log").write_text(
                noise + "Ran 57 tests in 3.1s\nOK\n", encoding="utf-8"
            )
            (unit_dir / "stderr.log").write_text("", encoding="utf-8")
            (trial / "stderr.log").write_text(
                noise + "etcd1: error: invalid heartbeat interval\n" + noise, encoding="utf-8"
            )

            doc = runner.write_log_digest(unit_dir, trial)

            self.assertIsNotNone(doc)
            stdout_lines = doc["streams"]["stdout"]["lines"]
            self.assertIn("Ran 57 tests in 3.1s", stdout_lines)
            self.assertIn("OK", stdout_lines)
            self.assertTrue(doc["streams"]["stdout"]["truncated"])
            self.assertIn(
                "etcd1: error: invalid heartbeat interval",
                doc["streams"]["final_trial_console"]["lines"],
            )
            # Bounded: a digest must stay committable next to 5000-line logs.
            size = (unit_dir / "log-digest.json").stat().st_size
            self.assertLess(size, 512 * 1024)

    def test_no_logs_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(runner.write_log_digest(Path(tmp), None))
            self.assertFalse((Path(tmp) / "log-digest.json").exists())


class ParseLogPhasesTest(unittest.TestCase):
    """The build log has no per-line timestamps, so only positions are
    extractable — never durations."""

    def test_markers_are_line_positions_not_seconds(self):
        log = "\n".join(
            ["nix eval starting"]
            + ["these 4 derivations will be built"]
            + [f"building '/nix/store/{i}-x.drv'" for i in range(3)]
            + ["booting", "running the test script", "done"]
        )
        phases = runner._parse_log_phases(log)
        self.assertEqual(phases["markers"]["nix_eval"], {"first_line": 0, "last_line": 0})
        self.assertEqual(phases["markers"]["build"]["first_line"], 1)
        self.assertEqual(phases["markers"]["build"]["last_line"], 4)
        self.assertEqual(phases["markers"]["total_lines"], 8)
        self.assertEqual(phases["completeness"], "full")
        # No key may carry a duration.
        self.assertNotIn("durations", phases)

    def test_none_without_any_marker(self):
        self.assertIsNone(runner._parse_log_phases("nothing interesting here\n"))


class ParseShrinkStdoutTest(unittest.TestCase):
    def test_parse_final_choices(self):
        stdout = (
            "Final topology choices:\n"
            '{\n  "roles": 1\n}\n'
            "Final config choices:\n"
            '{\n  "rabbit": {\n    ".a.b": 0\n  }\n}\n'
            "Reproduce with:\n"
            "topotestix orchestrator run rabbitmq --seed 3 --name x\n"
        )
        parsed = runner.parse_shrink_stdout(stdout)
        self.assertEqual(parsed["final_topology_choices"], {"roles": 1})
        self.assertEqual(parsed["final_config_choices"], {"rabbit": {".a.b": 0}})
        self.assertEqual(
            parsed["reproduce_command"], "topotestix orchestrator run rabbitmq --seed 3 --name x"
        )

    def test_empty_choices(self):
        stdout = "Final topology choices:\n{}\nFinal config choices:\n{}\n"
        parsed = runner.parse_shrink_stdout(stdout)
        self.assertEqual(parsed["final_topology_choices"], {})
        self.assertEqual(parsed["final_config_choices"], {})


def _write_trial(run_store_dir: Path, dir_name: str, *, fresh: bool, status: str) -> None:
    """A fake trial directory, as if RunStore (via --output-dir) had written
    it directly — mirrors what topotestix's own run_once() produces."""
    trial = run_store_dir / dir_name
    trial.mkdir(parents=True)
    (trial / "stdout.log").write_text(
        (
            "building '/nix/store/abc-vm-test-run-x.drv.drv'...\n"
            if fresh
            else "warning: netrc-file\nno build lines\n"
        ),
        encoding="utf-8",
    )
    (trial / "stderr.log").write_text("", encoding="utf-8")
    (trial / "run.json").write_text(
        json.dumps({"status": status, "name": "unit-run-name"}), encoding="utf-8"
    )
    (trial / "choices.json").write_text("{}", encoding="utf-8")
    (trial / "resolved.json").write_text("{}", encoding="utf-8")
    (trial / "target.json").write_text("{}", encoding="utf-8")


class RunStoreIndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="repro-runstore-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))

    def test_trial_dirs_chronological_and_empty_when_missing(self):
        self.assertEqual(runner._trial_dirs(self.tmp / "nope"), [])
        rs = self.tmp / "run-store"
        _write_trial(rs, "20260904-100000-x", fresh=True, status="passed")
        _write_trial(rs, "20260904-090000-x", fresh=True, status="failed")
        dirs = runner._trial_dirs(rs)
        self.assertEqual([d.name for d in dirs], ["20260904-090000-x", "20260904-100000-x"])

    def test_classify_trial_reads_own_log_and_status(self):
        rs = self.tmp / "run-store"
        _write_trial(rs, "t1", fresh=True, status="passed")
        summary = runner._classify_trial(rs / "t1")
        self.assertEqual(summary["execution"], "fresh")
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["dir"], "t1")

    def test_classify_trial_missing_run_json_is_status_none(self):
        # A kill/timeout mid-build: run_once never reached its final
        # store.write_json(run.json) call.
        rs = self.tmp / "run-store"
        trial = rs / "t1"
        trial.mkdir(parents=True)
        (trial / "stdout.log").write_text("no build lines\n", encoding="utf-8")
        summary = runner._classify_trial(trial)
        self.assertIsNone(summary["status"])

    def test_index_run_store_shrink_indexes_every_trial_copies_only_final(self):
        unit = make_unit(
            kind="shrink", target="etcd-cluster", seed=3, run_name="etcd-shrink-rep0-seed3"
        )
        partial = self.tmp / "partial"
        partial.mkdir()
        rs = partial / "run-store"
        _write_trial(rs, "20260904-090000-a", fresh=True, status="failed")  # rejected candidate
        _write_trial(rs, "20260904-090100-b", fresh=True, status="failed")  # kept/final
        stdout = (
            "Final topology choices:\n{}\nFinal config choices:\n{}\n"
            "Reproduce with:\ntopotestix orchestrator shrink etcd-cluster 3\n"
        )
        final = runner._index_run_store(unit, partial, rs, stdout, 0)
        self.assertEqual(final.name, "20260904-090100-b")
        trials = json.loads((partial / "trials.json").read_text())
        self.assertEqual([t["dir"] for t in trials], ["20260904-090000-a", "20260904-090100-b"])
        self.assertTrue((partial / "shrink.json").is_file())
        # Only the final trial's small JSON is copied flat; its log is not.
        self.assertTrue((partial / "run.json").is_file())
        self.assertFalse((partial / "stdout.log").is_file())
        self.assertEqual(json.loads((partial / "run.json").read_text())["status"], "failed")

    def test_index_run_store_shrink_records_real_exit_code(self):
        # cmd_shrink exits 1 when the initial seed passes (nothing to shrink);
        # shrink.json must say so rather than claim a clean exit.
        unit = make_unit(kind="shrink", target="etcd-cluster", seed=3)
        partial = self.tmp / "partial"
        partial.mkdir()
        rs = partial / "run-store"
        _write_trial(rs, "20260904-090000-a", fresh=True, status="passed")
        runner._index_run_store(unit, partial, rs, "", 1)
        self.assertEqual(json.loads((partial / "shrink.json").read_text())["exit_code"], 1)

    def test_index_run_store_run_kind_single_trial(self):
        unit = make_unit(kind="run", target="nginx", run_name="nginx-run")
        partial = self.tmp / "partial"
        partial.mkdir()
        rs = partial / "run-store"
        _write_trial(rs, "20260904-090000-only", fresh=True, status="passed")
        final = runner._index_run_store(unit, partial, rs, "", 0)
        self.assertEqual(final.name, "20260904-090000-only")
        trials = json.loads((partial / "trials.json").read_text())
        self.assertEqual(len(trials), 1)
        self.assertFalse((partial / "shrink.json").exists())

    def test_index_run_store_no_trials_returns_none(self):
        unit = make_unit(kind="run", target="nginx")
        partial = self.tmp / "partial"
        partial.mkdir()
        result = runner._index_run_store(unit, partial, partial / "run-store", "", 0)
        self.assertIsNone(result)
        self.assertFalse((partial / "trials.json").exists())

    def test_index_run_store_test_suites_never_touches_run_store(self):
        unit = make_unit(kind="test_suites", target=None, variant_name="python")
        partial = self.tmp / "partial"
        partial.mkdir()
        result = runner._index_run_store(unit, partial, partial / "run-store", "", 0)
        self.assertIsNone(result)

    def test_evidence_json_copied_from_final_trial(self):
        unit = make_unit(kind="run", target="rabbitmq-disk", run_name="rabbitmq-disk-run")
        partial = self.tmp / "partial"
        partial.mkdir()
        rs = partial / "run-store"
        _write_trial(rs, "20260904-090000-only", fresh=True, status="failed")
        (rs / "20260904-090000-only" / "disk-results.json").write_text(
            '{"contract": {}}', encoding="utf-8"
        )
        runner._index_run_store(unit, partial, rs, "", 0)
        self.assertTrue((partial / "disk-results.json").is_file())


class ResourceSamplerTest(unittest.TestCase):
    def test_proc_sampler_samples_self(self):
        stop = threading.Event()
        holder = {}
        thread = threading.Thread(
            target=runner._sample_resources, args=(0, stop, 0.05, holder), daemon=True
        )
        thread.start()
        stop.set()
        thread.join(timeout=5)
        self.assertEqual(holder["method"], "proc")
        self.assertGreaterEqual(holder["n_samples"], 1)


class RunUnitTest(unittest.TestCase):
    def test_fuzz_only_delegated_without_subprocess(self):
        with unittest.mock.patch.object(runner.subprocess, "Popen", forbid_subprocess):
            status = runner.run_unit(make_unit(kind="fuzz_only"), Path("/tmp"), REPO_ROOT)
        self.assertEqual(status["state"], "fuzz-only-delegated")
        self.assertEqual(
            status["input_hash"], runner.unit_input_hash(make_unit(kind="fuzz_only"), REPO_ROOT)
        )

    def test_skip_if_done_does_not_invoke_subprocess(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit = make_unit()
            raw_dir = Path(tmp) / "raw" / unit.id
            raw_dir.mkdir(parents=True)
            status = {
                "state": "done",
                "input_hash": runner.unit_input_hash(unit, REPO_ROOT),
                "exit_code": 0,
                "execution": "fresh",
            }
            (raw_dir / "status.json").write_text(json.dumps(status))
            with unittest.mock.patch.object(runner.subprocess, "Popen", forbid_subprocess):
                result = runner.run_unit(unit, Path(tmp), REPO_ROOT)
            self.assertTrue(result["skipped"])
            self.assertEqual(result["state"], "done")
            # returned copy only: on-disk status must not gain a "skipped" key
            on_disk = json.loads((raw_dir / "status.json").read_text())
            self.assertNotIn("skipped", on_disk)

    def test_failed_pre_start_promotes_partial_to_raw(self):
        def boom(*args, **kwargs):
            raise OSError("no such command")

        with tempfile.TemporaryDirectory() as tmp:
            unit = make_unit(id="cafebabe")
            with unittest.mock.patch.object(runner.subprocess, "Popen", boom):
                status = runner.run_unit(unit, Path(tmp), REPO_ROOT, timeout_s=1)
            self.assertEqual(status["state"], "failed")
            raw_dir = Path(tmp) / "raw" / "cafebabe"
            on_disk = json.loads((raw_dir / "status.json").read_text())
            self.assertEqual(on_disk["state"], "failed")
            self.assertEqual(on_disk["input_hash"], runner.unit_input_hash(unit, REPO_ROOT))
            self.assertFalse((Path(tmp) / "raw" / "cafebabe.partial").exists())


class PromoteCrashSafetyTest(unittest.TestCase):
    def _mk(self, tmp: Path, name: str, marker: str) -> Path:
        d = tmp / name
        d.mkdir(parents=True)
        (d / "status.json").write_text(json.dumps({"marker": marker}), encoding="utf-8")
        return d

    def test_promote_replaces_raw_and_prunes_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            raw = self._mk(tmp, "raw", "old")
            partial = self._mk(tmp, "partial", "new")
            runner._promote(partial, raw)
            self.assertEqual(json.loads((raw / "status.json").read_text())["marker"], "new")
            self.assertFalse((tmp / "raw.stale").exists())
            self.assertFalse(partial.exists())

    def test_promote_failure_mid_swap_keeps_old_data_in_stale(self):
        real_replace = runner.os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:  # the partial -> raw swap itself "crashes"
                raise OSError("simulated crash")
            return real_replace(src, dst)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            raw = self._mk(tmp, "raw", "old")
            partial = self._mk(tmp, "partial", "new")
            with unittest.mock.patch.object(runner.os, "replace", side_effect=flaky_replace):
                with self.assertRaises(OSError):
                    runner._promote(partial, raw)
            # Old complete data survives under raw/<id>.stale/ ...
            stale = tmp / "raw.stale"
            self.assertFalse(raw.exists())
            self.assertEqual(json.loads((stale / "status.json").read_text())["marker"], "old")
            # ... and a later successful promote recovers: stale is pruned.
            runner._promote(partial, raw)
            self.assertEqual(json.loads((raw / "status.json").read_text())["marker"], "new")
            self.assertFalse(stale.exists())


class FakePopen:
    """Minimal stand-in for subprocess.Popen driving run_unit's error paths.

    ``communicate_exc``: exception raised by the FIRST communicate() call, or
    a list/tuple raising successive items on successive calls.
    ``returncode_after``: value written to .returncode when communicate()
    completes, mimicking Popen only populating returncode once reaped."""

    def __init__(
        self,
        *,
        stdout="",
        stderr="",
        returncode_after=0,
        communicate_exc=None,
        call_log=None,
    ):
        self.pid = -1  # skip the resource sampler thread
        self.returncode = None
        self._stdout = stdout
        self._stderr = stderr
        self._returncode_after = returncode_after
        self._communicate_exc = communicate_exc
        self.calls = call_log if call_log is not None else []

    def communicate(self, timeout=None):
        self.calls.append("communicate")
        if self._communicate_exc is not None:
            if isinstance(self._communicate_exc, (list, tuple)):
                queue = list(self._communicate_exc)
                exc, self._communicate_exc = queue[0], (queue[1:] or None)
            else:
                exc, self._communicate_exc = self._communicate_exc, None
            raise exc
        self.returncode = self._returncode_after
        return self._stdout, self._stderr

    def kill(self):
        self.calls.append("kill")

    def wait(self, timeout=None):
        self.calls.append("wait")
        self.returncode = -9
        return self.returncode


class RunUnitFailurePathsTest(unittest.TestCase):
    def _run_with_fake(self, tmp, fake, killpg_calls):
        def spy_killpg(pid, sig):
            fake.calls.append("killpg")
            killpg_calls.append((pid, sig))

        with unittest.mock.patch.object(runner.subprocess, "Popen", return_value=fake):
            with unittest.mock.patch.object(runner.os, "killpg", side_effect=spy_killpg):
                return runner.run_unit(
                    make_unit(kind="run", target="nginx"), Path(tmp), REPO_ROOT, timeout_s=1
                )

    def test_signal_killed_unit_gets_error_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakePopen(
                stderr="some noise\nOut of memory: killed process\n",
                returncode_after=-9,
            )
            status = self._run_with_fake(tmp, fake, [])
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["exit_code"], -9)
            self.assertTrue(status.get("error"), "negative returncode must populate error")
            self.assertIn("command killed by signal 9", status["error"])
            self.assertIn("Out of memory: killed process", status["error"])
            # and it reached disk
            on_disk = json.loads(
                (Path(tmp) / "raw" / "deadbeef00000000" / "status.json").read_text()
            )
            self.assertTrue(on_disk.get("error"))

    def test_exit_2_path_still_uses_stderr_last_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakePopen(stderr="boom line one\nusage error: bad flag\n", returncode_after=2)
            status = self._run_with_fake(tmp, fake, [])
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["error"], "usage error: bad flag")

    def test_oserror_during_communicate_reaps_child_after_killpg(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakePopen(
                stderr="late output\n",
                returncode_after=-9,
                communicate_exc=OSError("pipe broke"),
            )
            killpg_calls = []
            status = self._run_with_fake(tmp, fake, killpg_calls)
            # killpg fired, then communicate() was called AGAIN to reap.
            self.assertEqual(len(killpg_calls), 1)
            self.assertIn("killpg", fake.calls)
            self.assertGreater(fake.calls.count("communicate"), 1)
            self.assertLess(fake.calls.index("killpg"), len(fake.calls) - 1)
            self.assertEqual(fake.calls[-1], "communicate")
            # the real exit code was recovered, not left as None.
            self.assertEqual(status["exit_code"], -9)
            self.assertTrue(status.get("error"))
            self.assertEqual(status["state"], "failed")

    def test_oserror_message_survives_later_exit_2(self):
        # rc>=2 must not clobber the more specific OSError already recorded
        # (setdefault, mirroring the negative-returncode branch).
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakePopen(
                stderr="boom line one\nusage error: bad flag\n",
                returncode_after=2,
                communicate_exc=OSError("pipe broke"),
            )
            status = self._run_with_fake(tmp, fake, [])
            self.assertEqual(status["state"], "failed")
            self.assertEqual(status["exit_code"], 2)
            self.assertEqual(status["error"], "pipe broke")

    def test_timeout_reap_oserror_never_raises(self):
        # Second communicate() after the timeout killpg blowing up must fall
        # back to empty output, not escape run_unit (failure contract).
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakePopen(
                communicate_exc=[
                    subprocess.TimeoutExpired("cmd", 1),
                    OSError("pipe broke after kill"),
                ]
            )
            killpg_calls = []
            status = self._run_with_fake(tmp, fake, killpg_calls)
            self.assertEqual(status["state"], "failed")
            self.assertIn("timed out", status["error"])
            self.assertEqual(len(killpg_calls), 1)
            self.assertGreater(fake.calls.count("communicate"), 1)

    def test_timeout_reap_bounded_when_pipes_stay_open(self):
        # A descendant outside the process group keeps the pipes open: the
        # post-kill communicate() times out too, and run_unit must still return.
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakePopen(
                communicate_exc=[
                    subprocess.TimeoutExpired("cmd", 1),
                    subprocess.TimeoutExpired("cmd", 30),
                ]
            )
            status = self._run_with_fake(tmp, fake, [])
            self.assertEqual(status["state"], "failed")
            self.assertIn("timed out after 1s", status["error"])
            self.assertIn("output lost", status["error"])
            self.assertEqual(fake.calls[-2:], ["kill", "wait"])


if __name__ == "__main__":
    unittest.main()
