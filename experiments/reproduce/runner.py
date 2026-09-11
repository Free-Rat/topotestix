"""Execute one experiment Unit: CLI invocation, artifact capture, status record.

Contract (see experiments/reproduce/models.py module docstring):
  run_unit(unit, out_dir, project_root, force=False, timeout_s=3600) -> dict

Never raises for a failed unit — returns a status dict with state "failed".
Raises only for pre-execution validation problems (bad kind, bad target, ...).
Every unit runs inside a sibling "<unit.id>.partial" directory which is
atomically renamed onto "raw/<unit.id>" via os.replace once status.json is in
place, so observers never see a half-written final dir.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from experiments.reproduce.models import Unit, atomic_write_json, canonical_hash, canonical_json

_STATUS_FILE = "status.json"
_PARTIAL_SUFFIX = ".partial"

_NIX_UNIT_EXPR = "import ./tests { lib = (import <nixpkgs> {}).lib; }"
# Every unit's own run-store subdir, given to the CLI via --output-dir so
# topotestix writes directly into raw/<unit-id>/run-store/<trial>/ instead of
# the volatile, shared .topotestix/runs/ (see _index_run_store below).
_RUN_STORE_DIRNAME = "run-store"

try:  # psutil is NOT installed in this environment; /proc fallback is required.
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - depends on host
    psutil = None  # type: ignore[assignment]

# JSON files copied flat from the FINAL trial into partial_dir/ so collect.py's
# flat-file contract (raw/<unit-id>/run.json, choices.json, ...) keeps working
# unchanged; the full per-trial data (all trials, including logs) still lives
# in partial_dir/run-store/<trial>/.
_RUN_STORE_JSON_STEMS = ("run", "choices", "resolved", "report", "target")


# --------------------------------------------------------------------------
# Command construction (pure, exported for tests)
# --------------------------------------------------------------------------


def build_command(unit: Unit, project_root: str, output_dir: Optional[Path] = None) -> List[str]:
    """Subprocess list form of the CLI invocation for ``unit``. NEVER shell=True.

    ``output_dir``, when given, is passed as topotestix's own
    ``--output-dir``: the CLI's RunStore then writes directly under it
    instead of falling back to the shared, volatile ``.topotestix/runs/``.
    See _index_run_store."""
    if unit.kind in ("sweep", "run", "exhaustive"):
        if not unit.target:
            raise ValueError(f"unit {unit.id}: kind {unit.kind!r} needs a target")
        cmd = [
            "nix",
            "develop",
            "-c",
            "python3",
            "-m",
            "topotestix.cli",
            "orchestrator",
            "run",
            unit.target,
        ]
        # Exhaustive cells (and seed-less "run" entries) are expanded with
        # seed=None: the cell is pinned by explicit --topology-choices /
        # --config-choices, not by a seed.  "--seed None" makes argparse
        # (type=int) abort with exit code 2 before the CLI even starts, so
        # omit the flag entirely and let the CLI's own default (1) stand.
        if unit.seed is not None:
            cmd += ["--seed", str(unit.seed)]
        cmd += [
            "--name",
            unit.run_name,
            "--project-root",
            project_root,
            "--json",
        ]
        if output_dir is not None:
            cmd += ["--output-dir", str(output_dir)]
        if unit.repetition_token:
            cmd += ["--repetition-token", unit.repetition_token]
        if unit.topology_choices is not None:
            cmd += ["--topology-choices", canonical_json(unit.topology_choices)]
        if unit.config_choices is not None:
            cmd += ["--config-choices", canonical_json(unit.config_choices)]
        if unit.topology_target:
            cmd += ["--topology-target", unit.topology_target]
        if unit.config_target:
            cmd += ["--config-target", unit.config_target]
        if unit.base_module:
            cmd += ["--base-module", unit.base_module]
        if unit.test_script:
            cmd += ["--test-script", unit.test_script]
        if unit.properties:
            cmd += ["--properties", unit.properties]
        return cmd
    if unit.kind == "shrink":
        if not unit.target:
            raise ValueError(f"unit {unit.id}: kind 'shrink' needs a target")
        if unit.seed is None:
            # Unlike `run`, shrink takes the seed as a required positional —
            # there is no default to fall back on.
            raise ValueError(f"unit {unit.id}: kind 'shrink' needs a seed")
        # `orchestrator shrink <target> <seed>` + add_run_common flags (cli.py).
        # --json is accepted (harmless: cmd_shrink always prints its text form).
        cmd = [
            "nix",
            "develop",
            "-c",
            "python3",
            "-m",
            "topotestix.cli",
            "orchestrator",
            "shrink",
            unit.target,
            str(unit.seed),
            "--name",
            unit.run_name,
            "--project-root",
            project_root,
            "--json",
        ]
        if output_dir is not None:
            cmd += ["--output-dir", str(output_dir)]
        if unit.repetition_token:
            cmd += ["--repetition-token", unit.repetition_token]
        return cmd
    if unit.kind == "fuzz_only":
        return []
    if unit.kind == "test_suites":
        if unit.variant_name == "nix":
            # Mirrors flake.nix checks.default, usable non-flake from repo root.
            return ["nix", "develop", "-c", "nix-unit", "--expr", _NIX_UNIT_EXPR]
        # The thesis counts the FRAMEWORK's test suite (57 tests).  The
        # harness's own tests live in the same directory — load only the
        # framework test modules (same discovery rules as flake checks,
        # excluding tests/test_reproduce_*).
        tests_dir = Path(project_root) / "tests"
        modules = sorted(
            p.stem for p in tests_dir.glob("test_*.py") if not p.name.startswith("test_reproduce_")
        )
        if not modules:
            raise ValueError(f"unit {unit.id}: no framework test modules found")
        loader = (
            "import sys, unittest; "
            "sys.path.insert(0, 'tests'); "
            f"mods = {modules!r}; "
            "suite = unittest.defaultTestLoader.loadTestsFromNames(mods); "
            "result = unittest.TextTestRunner(verbosity=1).run(suite); "
            "sys.exit(0 if result.wasSuccessful() else 1)"
        )
        return ["nix", "develop", "-c", "python3", "-c", loader]
    raise ValueError(f"unit {unit.id}: unknown kind {unit.kind!r}")


# --------------------------------------------------------------------------
# Cache-vs-fresh detection (detect, do not trust)
# --------------------------------------------------------------------------

# Modern nix prints "this derivation will be built:" (count-less) or
# "these N derivations will be built:" (trailing colon); older nix prints
# "building '/nix/store/...'".  Accept all variants.
_FRESH_RE = re.compile(
    r"^(?:building '/nix/store/[^']+'" r"|(?:this|these) (?:\d+ )?derivations? will be built)"
)
_SUBST_RE = re.compile(r"(copying path|substitut)")


def classify_execution(combined_output: str, default: str = "unknown") -> Tuple[str, List[str]]:
    """Label a nix build by its output markers: fresh | substituted, or
    ``default`` when no build marker is found at all.  run_unit always passes
    ``unknown``: under concurrent nix builds the daemon may not echo markers
    even for a fresh build, so an absent marker never proves a cache replay.
    Detection only — never trusted without a marker to point at."""
    markers: List[str] = []
    fresh = False
    substituted = False
    for line in combined_output.splitlines():
        if _FRESH_RE.match(line):
            fresh = True
            if len(markers) < 20:
                markers.append(line)
        elif _SUBST_RE.search(line):
            substituted = True
            if len(markers) < 20:
                markers.append(line)
    if fresh:
        label = "fresh"
    elif substituted:
        label = "substituted"
    else:
        label = default
    return label, markers


# --------------------------------------------------------------------------
# Resource sampler (psutil if importable, else /proc walk)
# --------------------------------------------------------------------------


def _proc_tree_pids(root_pid: int) -> List[int]:
    """BFS over /proc children links; returns [root_pid, ...descendants]."""
    pids = [root_pid]
    frontier = [root_pid]
    seen = {root_pid}
    while frontier:
        next_frontier: List[int] = []
        for pid in frontier:
            try:
                tasks = os.listdir(f"/proc/{pid}/task")
            except OSError:
                continue
            for tid in tasks:
                try:
                    with open(f"/proc/{pid}/task/{tid}/children", "r", encoding="utf-8") as fh:
                        for child in fh.read().split():
                            cpid = int(child)
                            if cpid not in seen:
                                seen.add(cpid)
                                next_frontier.append(cpid)
                except OSError:
                    continue
        pids.extend(next_frontier)
        frontier = next_frontier
    return pids


def _proc_sample(pid: int) -> Tuple[int, float]:
    """(rss_bytes, cpu_seconds) summed over the process tree, /proc method."""
    rss = 0
    cpu = 0.0
    ticks = os.sysconf("SC_CLK_TCK")
    for p in _proc_tree_pids(pid):
        try:
            with open(f"/proc/{p}/status", "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        rss += int(line.split()[1]) * 1024
                        break
        except (OSError, ValueError, IndexError):
            pass
        try:
            with open(f"/proc/{p}/stat", "r", encoding="utf-8") as fh:
                stat = fh.read()
            # comm may contain spaces/parens: split after the closing paren.
            fields = stat[stat.rfind(")") + 2 :].split()
            cpu += (int(fields[11]) + int(fields[12])) / ticks
        except (OSError, ValueError, IndexError):
            pass
    return rss, cpu


def _psutil_sample(pid: int) -> Tuple[int, float]:
    rss = 0
    cpu = 0.0
    assert psutil is not None
    try:
        procs = [psutil.Process(pid)] + psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        return 0, 0.0
    for proc in procs:
        try:
            rss += proc.memory_info().rss
        except psutil.Error:
            pass
        try:
            times = proc.cpu_times()
            cpu += times.user + times.system
        except psutil.Error:
            pass
    return int(rss), cpu


def _sample_resources(
    pid: int,
    stop_event: threading.Event,
    interval: float,
    holder: Dict[str, Any],
) -> None:
    """Background sampler thread body; writes its result into ``holder``."""
    method = "psutil" if psutil is not None else "proc"
    sample_fn: Callable[[int], Tuple[int, float]] = (
        _psutil_sample if psutil is not None else _proc_sample
    )
    peak_rss = 0
    cpu_seconds = 0.0
    n_samples = 0
    while not stop_event.is_set():
        rss, cpu = sample_fn(pid)
        peak_rss = max(peak_rss, rss)
        cpu_seconds = max(cpu_seconds, cpu)
        n_samples += 1
        stop_event.wait(interval)
    rss, cpu = sample_fn(pid)
    peak_rss = max(peak_rss, rss)
    cpu_seconds = max(cpu_seconds, cpu)
    n_samples += 1
    holder.update(
        {
            "peak_rss_bytes": peak_rss,
            "cpu_seconds": round(cpu_seconds, 3),
            "sample_interval_s": interval,
            "n_samples": n_samples,
            "method": method,
        }
    )


# --------------------------------------------------------------------------
# Status / skip helpers (pure-ish, testable without executing)
# --------------------------------------------------------------------------


def unit_input_hash(unit: Unit, project_root: str = "") -> str:
    payload = unit.to_dict()
    if project_root:
        # The command interpolates --project-root; fold it in so rerunning
        # against a different root cannot silently skip a unit.
        payload["project_root"] = str(Path(project_root).resolve())
    return canonical_hash(payload)


def should_skip(
    raw_dir: Path, unit: Unit, force: bool, project_root: str = ""
) -> Optional[Dict[str, Any]]:
    """Existing done status with a matching input_hash (unless force) => skip."""
    path = raw_dir / _STATUS_FILE
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            status = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if (
        status.get("state") == "done"
        and status.get("input_hash") == unit_input_hash(unit, project_root)
        and not force
    ):
        return status
    return None


def write_status(partial_dir: Path, status: Dict[str, Any]) -> None:
    """Atomically write status.json (tmp file + os.replace)."""
    atomic_write_json(partial_dir / _STATUS_FILE, status)


def _promote(partial_dir: Path, raw_dir: Path) -> None:
    """Crash-safe swap of partial_dir onto raw_dir.

    If raw_dir exists it is first renamed aside to "<name>.stale" (after
    pruning any leftover .stale dir), then partial_dir is renamed onto
    raw_dir, then the stale copy is removed best-effort.  A kill between
    any two steps leaves the previous complete data under either
    raw/<id>/ or raw/<id>.stale/ (the campaign CLI prunes .stale dirs on
    next run) — never a half-written or entirely missing raw dir."""
    stale = raw_dir.with_name(raw_dir.name + ".stale")
    if stale.exists():
        shutil.rmtree(stale)
    if raw_dir.exists():
        os.replace(raw_dir, stale)
    os.replace(partial_dir, raw_dir)
    if stale.exists():
        shutil.rmtree(stale, ignore_errors=True)


# --------------------------------------------------------------------------
# Run-store indexing
#
# --output-dir (see build_command) makes topotestix write every execution's
# run-store data directly under partial_dir/run-store/<trial>/, private to
# this unit — no shared/volatile .topotestix/runs/ involved, and (unlike the
# old name-substring search over the shared store) no possibility of two
# concurrent --jobs>1 units' trials being confused with each other. A "run"/
# "sweep"/"exhaustive" unit performs exactly one execution (one trial dir); a
# "shrink" unit's internal candidate search performs one per candidate tried,
# all captured here.
# --------------------------------------------------------------------------


def _trial_dirs(run_store_dir: Path) -> List[Path]:
    """Every trial RunStore created for this unit, oldest first (dir names are
    timestamp-prefixed, so lexicographic order is chronological order)."""
    if not run_store_dir.is_dir():
        return []
    return sorted(p for p in run_store_dir.iterdir() if p.is_dir())


def _classify_trial(trial_dir: Path) -> Dict[str, Any]:
    """One trial's outcome + fresh/cache/substituted classification, read from
    its own build log in place. The full log is never copied into a summary —
    it stays exactly where RunStore wrote it, under run-store/<trial>/."""
    stdout = (
        (trial_dir / "stdout.log").read_text(encoding="utf-8", errors="replace")
        if (trial_dir / "stdout.log").is_file()
        else ""
    )
    stderr = (
        (trial_dir / "stderr.log").read_text(encoding="utf-8", errors="replace")
        if (trial_dir / "stderr.log").is_file()
        else ""
    )
    execution_label, markers = classify_execution(stdout + "\n" + stderr, default="unknown")
    run_meta: Dict[str, Any] = {}
    run_json = trial_dir / "run.json"
    if run_json.is_file():
        try:
            run_meta = json.loads(run_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            run_meta = {}
    return {
        "dir": trial_dir.name,
        "execution": execution_label,
        "markers": markers,
        # "status" is absent (None) when a kill/timeout landed mid-build, before
        # run_once ever reached its final store.write_json(run.json) call.
        "status": run_meta.get("status"),
        "name": run_meta.get("name"),
    }


def _index_run_store(
    unit: Unit,
    partial_dir: Path,
    run_store_dir: Path,
    stdout: str,
    returncode: Optional[int],
) -> Optional[Path]:
    """Index every trial RunStore wrote under run_store_dir; return the final
    (kept/last) trial's directory for the caller to derive nix-build.json /
    stage-timing from, or None if none exists.

    Writes trials.json — one compact record per trial (shrink loops: every
    candidate tried; run/sweep/exhaustive: the single execution) — and copies
    the final trial's small JSON files (run/choices/resolved/report/target,
    plus any materialised evidence JSON) flat into partial_dir so collect.py's
    existing flat-file contract keeps working unchanged. Never copies a log:
    every trial's full data, including its build log, already lives under
    run-store/<trial>/ because --output-dir pointed the CLI there directly."""
    if unit.kind == "shrink":
        # cmd_shrink prints final choices + reproduce command as plain text
        # (--json is not honoured by cmd_shrink) — capture it as shrink.json.
        parsed = parse_shrink_stdout(stdout)
        # 1 = the initial seed passed, so there was nothing to shrink.
        parsed["exit_code"] = returncode
        atomic_write_json(partial_dir / "shrink.json", parsed)
    elif unit.kind == "test_suites":
        return None

    trials = _trial_dirs(run_store_dir)
    if not trials:
        return None
    summaries = [_classify_trial(d) for d in trials]
    atomic_write_json(partial_dir / "trials.json", summaries)

    final_trial = trials[-1]
    for stem in _RUN_STORE_JSON_STEMS:
        src = final_trial / f"{stem}.json"
        if src.is_file():
            shutil.copy2(src, partial_dir / f"{stem}.json")
    # Designed cells (e.g. rabbitmq) materialise extra evidence JSON straight
    # into the RunStore dir (run_store.materialize_result_artifacts) — surface
    # those too; already-copied stems are skipped, never overwritten.
    for src in sorted(final_trial.glob("*.json")):
        dst = partial_dir / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
    return final_trial


_SHRINK_SECTION_RE = re.compile(r"^(Final topology choices|Final config choices|Reproduce with):$")


def parse_shrink_stdout(stdout: str) -> Dict[str, Any]:
    """Parse cmd_shrink's text output into structured final choices."""
    parsed: Dict[str, Any] = {}
    lines = stdout.splitlines()
    i = 0
    while i < len(lines):
        match = _SHRINK_SECTION_RE.match(lines[i])
        if not match:
            i += 1
            continue
        section = match.group(1)
        i += 1
        if section == "Reproduce with":
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines):
                parsed["reproduce_command"] = lines[i].strip()
                i += 1
            continue
        # JSON blob (possibly multi-line, indent=2) follows the section header.
        depth = 0
        blob: List[str] = []
        start = i
        while i < len(lines):
            opens = lines[i].count("{") + lines[i].count("[")
            closes = lines[i].count("}") + lines[i].count("]")
            depth += opens - closes
            blob.append(lines[i])
            i += 1
            if depth <= 0:
                break
        try:
            key = (
                "final_topology_choices"
                if section == "Final topology choices"
                else "final_config_choices"
            )
            parsed[key] = json.loads("\n".join(blob))
        except json.JSONDecodeError:
            parsed[f"{section.lower().replace(' ', '_')}_raw"] = "\n".join(blob)
            i = start + 1
    return parsed


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------


def run_unit(
    unit: Unit,
    out_dir: Path,
    project_root: str,
    force: bool = False,
    timeout_s: int = 3600,
) -> Dict[str, Any]:
    """Execute one unit; returns its status record. Never raises on failure."""
    if unit.kind == "fuzz_only":
        # resolve.py owns fuzz-only resolution; runner must not invoke the CLI.
        return {"state": "fuzz-only-delegated", "input_hash": unit_input_hash(unit, project_root)}

    raw_dir = Path(out_dir) / "raw" / unit.id
    previous = should_skip(raw_dir, unit, force, project_root)
    if previous is not None:
        skipped = dict(previous)
        skipped["skipped"] = True
        return skipped

    input_hash = unit_input_hash(unit, project_root)
    partial_dir = raw_dir.parent / (unit.id + _PARTIAL_SUFFIX)
    if partial_dir.exists():
        shutil.rmtree(partial_dir)
    partial_dir.mkdir(parents=True)
    run_store_dir = partial_dir / _RUN_STORE_DIRNAME

    command = build_command(unit, project_root, run_store_dir)  # raises on pre-exec validation

    start_mono = time.monotonic()
    # Wall-clock start too: time.monotonic() is only comparable within one
    # boot of one machine, and the parallelism analysis needs to place units
    # on a shared timeline (max end - min start) across processes.
    start_epoch = time.time()
    stop_event = threading.Event()
    holder: Dict[str, Any] = {}
    sampler: Optional[threading.Thread] = None
    proc: Optional[subprocess.Popen] = None

    status: Dict[str, Any] = {
        "state": "failed",
        "input_hash": input_hash,
        "exit_code": None,
        "execution": None,
        "unit": unit.to_dict(),
    }
    try:
        proc = subprocess.Popen(
            command,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        status["error"] = f"failed to start subprocess: {exc}"
        write_status(partial_dir, status)
        _promote(partial_dir, raw_dir)
        return status

    if proc.pid > 0:
        sampler = threading.Thread(
            target=_sample_resources, args=(proc.pid, stop_event, 0.5, holder), daemon=True
        )
        sampler.start()
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass
        status["error"] = f"timed out after {timeout_s}s"
        try:
            # Bounded: a descendant that escaped the process group can hold
            # the pipes open forever.
            stdout, stderr = proc.communicate(timeout=30)
        except OSError:
            stdout, stderr = "", ""
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            stdout, stderr = "", ""
            status["error"] += "; output lost (pipes still open 30s after kill)"
        timed_out = True
    except OSError as exc:
        # The child may still be alive (e.g. a broken pipe mid-execution);
        # never leave an orphaned process group behind, and reap it so the
        # real exit status is available below (no zombie, no lost code).
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass
        try:
            stdout, stderr = proc.communicate()
        except OSError:
            stdout, stderr = "", ""
        status["error"] = str(exc)
        timed_out = False
    except BaseException:
        # KeyboardInterrupt and friends: the child runs in its own session
        # (start_new_session=True), so it would survive parent exit as an
        # orphaned QEMU.  Kill the group, then re-raise.
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass
        raise
    else:
        timed_out = False
    finally:
        stop_event.set()
        if sampler is not None:
            sampler.join(timeout=5.0)

    returncode = proc.returncode
    wall_s = time.monotonic() - start_mono
    (partial_dir / "stdout.log").write_text(stdout or "", encoding="utf-8")
    (partial_dir / "stderr.log").write_text(stderr or "", encoding="utf-8")
    combined = (stdout or "") + "\n" + (stderr or "")
    execution_label, markers = classify_execution(combined)
    atomic_write_json(
        partial_dir / "nix-build.json",
        {"execution": execution_label, "markers": markers},
    )
    atomic_write_json(
        partial_dir / "timing.json",
        {
            "wall_s": round(wall_s, 3),
            "started_monotonic_relative": round(start_mono, 6),
            "started_epoch": round(start_epoch, 6),
            "finished_epoch": round(start_epoch + wall_s, 6),
            "timeout_s": timeout_s,
            "timed_out": bool(timed_out),
        },
    )
    if holder:
        holder = dict(holder)
        # Attribution caveat: the sampler walks this process's descendant
        # tree; under multi-user Nix, QEMU/build workers may live outside it
        # (owned by the nix daemon), so peaks can undercount.
        holder["attribution"] = "process-tree-descendants"
        holder["attribution_caveat"] = (
            "QEMU/build workers spawned by the nix daemon may not appear in "
            "the sampled tree; peak RSS and CPU seconds can undercount."
        )
        atomic_write_json(partial_dir / "resources.json", holder)

    status["exit_code"] = returncode
    status["execution"] = execution_label
    # Exit semantics (cli.py / orchestrator.py): run/shrink use 0=passed, 1=failed
    # (both are completed executions worth keeping); >=2 or negative = CLI error.
    if timed_out:
        status["state"] = "failed"
    elif returncode is not None and returncode in (0, 1):
        status["state"] = "done"
    else:
        status["state"] = "failed"
        if returncode is not None and returncode >= 2:
            err_lines = (stderr or "").strip().splitlines()
            message = err_lines[-1] if err_lines else f"command exited {returncode}"
            # Don't clobber a more specific error already recorded (e.g. the
            # OSError from a broken pipe whose kill we just reaped above).
            status.setdefault("error", message)
        elif returncode is not None and returncode < 0:
            err_lines = (stderr or "").strip().splitlines()
            message = f"command killed by signal {-returncode}"
            if err_lines:
                message += f": {err_lines[-1]}"
            # Don't clobber a more specific error already recorded (e.g. the
            # OSError from a broken pipe whose kill we just reaped above).
            status.setdefault("error", message)

    final_trial: Optional[Path] = None
    if status["state"] == "done":
        try:
            final_trial = _index_run_store(
                unit, partial_dir, run_store_dir, stdout or "", returncode
            )
        except (OSError, json.JSONDecodeError) as exc:
            status["error"] = f"artifact collection failed: {exc}"
            status["state"] = "failed"
    elif timed_out:
        # A timed-out unit has no final result, but the trials it did finish
        # (a shrink search's candidates) are still on disk: index them so
        # trials.json records what the search reached before the kill.
        trials = _trial_dirs(run_store_dir)
        if trials:
            try:
                atomic_write_json(
                    partial_dir / "trials.json", [_classify_trial(d) for d in trials]
                )
            except (OSError, json.JSONDecodeError):
                pass

    # The CLI's own stdout/stderr swallow the nix build log (build_test uses
    # capture_output).  Re-classify from the final trial's own build log, read
    # in place under run-store/<trial>/ (never copied out), so fresh-vs-replay
    # detection actually sees markers.
    if final_trial is not None:
        combined = (
            (final_trial / "stdout.log").read_text(encoding="utf-8", errors="replace")
            if (final_trial / "stdout.log").is_file()
            else ""
        )
        combined += "\n" + (
            (final_trial / "stderr.log").read_text(encoding="utf-8", errors="replace")
            if (final_trial / "stderr.log").is_file()
            else ""
        )
        default = "unknown"  # no markers is ambiguous under concurrent builds
        execution_label, markers = classify_execution(combined, default=default)
        atomic_write_json(
            partial_dir / "nix-build.json",
            {
                "execution": execution_label,
                "markers": markers,
                "source": "run-store-log",
                "wall_s": round(time.monotonic() - start_mono, 3),
                "note": (
                    "No build markers in the captured log. Under concurrent"
                    " nix builds the daemon may not echo per-invocation"
                    " markers even for freshly built derivations; treat"
                    " 'unknown' as fresh-likely when wall_s is VM-scale."
                    if execution_label == "unknown"
                    else ""
                ),
            },
        )
        status["execution"] = execution_label

        # Stage boundaries (best-effort): the run-store build log carries no
        # per-line timestamps, so all that can honestly be extracted is WHERE
        # each stage's lines sit in the log — never how long it took.  Real
        # per-stage seconds come from the VM driver's own "(finished: ..., in
        # N seconds)" lines, which analyze.py parses directly.
        phases = _parse_log_phases(combined)
        if phases:
            with open(partial_dir / "timing.json", "r", encoding="utf-8") as fh:
                timing_doc = json.load(fh)
            timing_doc.pop("phases", None)  # never write line counts as seconds
            timing_doc["phase_markers"] = phases["markers"]
            timing_doc["phase_markers_completeness"] = phases["completeness"]
            atomic_write_json(partial_dir / "timing.json", timing_doc)

    # Committed, bounded stand-in for the *.log files, which are far too large
    # to keep in git (~340 MB/campaign) yet are read by analyze.py.  See
    # write_log_digest: without it, analysis from a fresh clone silently loses
    # the test-suite counts and the etcd v1 startup error message.
    write_log_digest(partial_dir, final_trial)

    write_status(partial_dir, status)
    _promote(partial_dir, raw_dir)
    return status


# --------------------------------------------------------------------------
# log-digest.json — the committed projection of the (gitignored) *.log files
# --------------------------------------------------------------------------

# Lines analysis actually reads out of the logs: unittest/nix-unit result
# lines, the VM driver's own "(finished: ..., in N seconds)" timings, nix
# build markers, and anything error-shaped (the etcd v1 startup failures only
# ever surface in the VM console log).
_DIGEST_KEEP_RE = re.compile(
    r"\(finished:|\bRan \d+ tests?\b|^OK\b|^FAILED\b|^ERROR\b|"
    r"✅|❌|\btests? (passed|failed)\b|"
    r"error|Error|ERROR|Traceback|error:|failed|Failed|FAILED|"
    r"panic|fatal|refus|timed out|timeout|"
    r"building '/nix/store|derivations? will be built|copying path|substitut"
)
# Lines a parser in analyze.py consumes ARITHMETICALLY (it sums or maxes
# them, so dropping one changes the number): the driver's per-step timings
# and the two test-suite result lines.  These are never trimmed by the cap —
# analysis must come out identical whether it reads the logs or this digest.
_DIGEST_ALWAYS_RE = re.compile(
    r"\(finished: .*, in [0-9.]+ seconds\)"
    r"|^Ran \d+ tests?"
    r"|^OK\b|FAILED"
    r"|\d+/\d+\s*successful"
)
_DIGEST_HEAD_LINES = 20
_DIGEST_TAIL_LINES = 120
_DIGEST_MAX_LINES = 300
# VM console lines can be enormous (base64 blobs, JSON dumps); nothing
# analysis parses needs more than the head of a line.
_DIGEST_MAX_LINE_CHARS = 500


def digest_stream(text: str) -> Dict[str, Any]:
    """Bounded, order-preserving projection of one log stream.

    Keeps the head, the tail, and every salient line in between, so the
    parsers in analyze.py see exactly the lines they look for while the
    stored artifact stays a few KB instead of a few hundred MB."""
    lines = (text or "").splitlines()
    total = len(lines)
    keep: List[int] = []
    seen = set()

    def take(idx: int) -> None:
        if idx not in seen:
            seen.add(idx)
            keep.append(idx)

    for i in range(min(_DIGEST_HEAD_LINES, total)):
        take(i)
    for i in range(max(0, total - _DIGEST_TAIL_LINES), total):
        take(i)
    for i, line in enumerate(lines):
        if _DIGEST_KEEP_RE.search(line):
            take(i)
    always = [i for i, line in enumerate(lines) if _DIGEST_ALWAYS_RE.search(line)]
    keep.sort()
    truncated = len(keep) < total
    if len(keep) > _DIGEST_MAX_LINES:
        # Salient lines dominate (VM consoles are full of error-shaped
        # noise).  Keep the last ones: the failure that matters, the suite
        # result and the driver's timing lines all land near the end, and
        # _condense_error picks the LAST matching line anyway.
        head = _DIGEST_MAX_LINES // 5
        keep = keep[:head] + keep[head - _DIGEST_MAX_LINES :]
        truncated = True
    # The arithmetic lines survive the cap unconditionally.
    keep = sorted(set(keep) | set(always))
    truncated = truncated or len(keep) < total

    always_set = set(always)

    def clip(idx: int) -> str:
        line = lines[idx]
        # An arithmetic line is never clipped: the seconds sit at its END
        # ("(finished: must succeed: <long command>, in 3.6 seconds)"), so
        # truncating it silently drops the value from the sum.
        if idx in always_set or len(line) <= _DIGEST_MAX_LINE_CHARS:
            return line
        return line[:_DIGEST_MAX_LINE_CHARS] + "…"

    return {
        "total_lines": total,
        "kept_lines": len(keep),
        "truncated": truncated,
        "lines": [clip(i) for i in keep],
    }


def write_log_digest(unit_dir: Path, final_trial: Optional[Path]) -> Optional[Dict[str, Any]]:
    """Write ``unit_dir/log-digest.json`` from the unit's on-disk logs.

    Streams: the wrapper CLI's own stdout/stderr and — for VM units — the
    final trial's run-store console log, which is where the VM's systemd and
    application output lands (runner routes it there via --output-dir).
    Returns the document, or None when there is nothing to digest."""
    unit_dir = Path(unit_dir)

    def read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    streams: Dict[str, Any] = {}
    for name in ("stdout", "stderr"):
        path = unit_dir / f"{name}.log"
        if path.is_file():
            streams[name] = digest_stream(read(path))
    if final_trial is not None:
        console = read(final_trial / "stderr.log") + "\n" + read(final_trial / "stdout.log")
        if console.strip():
            streams["final_trial_console"] = digest_stream(console)
            streams["final_trial_console"]["trial_dir"] = Path(final_trial).name
    if not streams:
        return None
    doc = {
        "version": 1,
        "note": (
            "Bounded projection of the *.log files, which are gitignored "
            "(too large for git) but are read by analyze.py. collect.py "
            "falls back to this document when the logs are absent."
        ),
        "streams": streams,
    }
    atomic_write_json(unit_dir / "log-digest.json", doc)
    return doc


# Stage-boundary markers in the run-store build log.  Best-effort: a missing
# boundary leaves that stage absent and completeness "partial".
_STAGE_BOUNDS = [
    # (phase, regex on the log line)
    ("nix_eval", r"evaluating (file|derivation)|nix eval"),
    ("build", r"^(building|these \d* ?derivations? will be built|building '/nix/store)"),
    ("vm_boot", r"booting|start_all|machine #.*starting"),
    ("test_script", r"test script|running the test script|testScript"),
]


def _parse_log_phases(combined: str) -> Optional[Dict[str, Any]]:
    """Best-effort stage POSITIONS in the build log — never durations.

    The log has no per-line timestamps, so a line-index delta is a count of
    lines, not a number of seconds; emitting one as a duration produced
    absurdities (7233 "seconds" of build inside a 222 s run, and negative
    boot times).  This returns only what the log actually shows: the first
    and last line index at which each stage's marker appears, plus the total
    line count, so a reader can see stage ordering and coverage without any
    fabricated timing.  Real per-stage seconds come from the VM driver's own
    "(finished: ..., in N seconds)" lines (see analyze._stage_timing_for_unit).

    Returns {"markers": {phase: {"first_line", "last_line"} | None,
                         "total_lines": int},
             "completeness": "full"|"partial"} or None when no marker at all
    is found."""
    lines = combined.splitlines()
    first_line_at: Dict[str, int] = {}
    last_line_at: Dict[str, int] = {}
    for idx, line in enumerate(lines):
        for name, pattern in _STAGE_BOUNDS:
            if re.search(pattern, line):
                first_line_at.setdefault(name, idx)
                last_line_at[name] = idx
    if not first_line_at:
        return None
    markers: Dict[str, Any] = {
        name: (
            {"first_line": first_line_at[name], "last_line": last_line_at[name]}
            if name in first_line_at
            else None
        )
        for name, _ in _STAGE_BOUNDS
    }
    markers["total_lines"] = len(lines)
    completeness = "full" if len(first_line_at) == len(_STAGE_BOUNDS) else "partial"
    return {"markers": markers, "completeness": completeness}
