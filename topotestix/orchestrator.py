import argparse
import json
import logging
import os
import shlex
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Iterator, Optional

from .events import Event, event
from .nix import build_test, eval_json, nix_json, nix_path, nix_string, resolve_path
from .reports import parse_report, report_passed, report_summary
from .run_store import RunStore, default_runs_dir, utc_now
from .targets import Target, get_target


def parse_json_object(value: str, label: str) -> dict:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError(f"{label} must be a JSON object")
    return parsed


def generate_nix_expr(
    seed: int,
    topology_target_path: str,
    config_target_path: str,
    base_module_path: str,
    test_script_path: str,
    properties_path: str,
    name: str,
    project_root: str,
    report_node: str = "",
    topology_choices: Optional[dict] = None,
    config_choices: Optional[dict] = None,
) -> str:
    abs_topology_target = resolve_path(topology_target_path, project_root)
    abs_config_target = resolve_path(config_target_path, project_root)
    abs_base_module = resolve_path(base_module_path, project_root)
    abs_test_script = resolve_path(test_script_path, project_root)
    abs_properties = resolve_path(properties_path, project_root)
    abs_orchestrate = resolve_path("lib/orchestrate.nix", project_root)

    return f"""let
  nixpkgs = builtins.getFlake "nixpkgs";
  pkgs = nixpkgs.legacyPackages.x86_64-linux;
  lib = pkgs.lib;

  orchestrate = (import {nix_path(abs_orchestrate)} {{ inherit pkgs lib; testers = pkgs.testers; }}).orchestrate;

  topologyTarget = import {nix_path(abs_topology_target)} {{ inherit lib; }};
  configTarget = import {nix_path(abs_config_target)} {{ inherit lib; }};
  baseModule = import {nix_path(abs_base_module)};
  testScript = builtins.readFile {nix_path(abs_test_script)};
  propertiesMod = import {nix_path(abs_properties)} {{ inherit lib; }};
in
orchestrate {{
  seed = {seed};
  inherit topologyTarget configTarget baseModule testScript;
  properties = builtins.attrValues propertiesMod;
  name = {nix_string(name)};
  reportNode = {nix_string(report_node) if report_node else "null"};
  topologyChoices = {nix_json(topology_choices or {})};
  configChoices = {nix_json(config_choices or {})};
}}"""


def generate_shrink_inputs_expr(
    seed: int, topology_target_path: str, config_target_path: str, project_root: str
) -> str:
    abs_topology_target = resolve_path(topology_target_path, project_root)
    abs_config_target = resolve_path(config_target_path, project_root)
    abs_fuzzer = resolve_path("lib/fuzzer.nix", project_root)
    abs_shrinker = resolve_path("lib/shrinker.nix", project_root)

    return f"""let
  nixpkgs = builtins.getFlake "nixpkgs";
  pkgs = nixpkgs.legacyPackages.x86_64-linux;
  lib = pkgs.lib;

  fuzzer = (import {nix_path(abs_fuzzer)} {{ inherit lib; }}).fuzzer;
  shrinker = import {nix_path(abs_shrinker)} {{ inherit lib; }};
  topologyTarget = import {nix_path(abs_topology_target)} {{ inherit lib; }};
  configTarget = import {nix_path(abs_config_target)} {{ inherit lib; }};

  fuzzedTopology = fuzzer {{ seed = {nix_string(str(seed))}; target = topologyTarget; }};
  topology = shrinker.apply topologyTarget fuzzedTopology.result {{}};
  roleNames = builtins.sort (a: b: a < b) (builtins.attrNames topology.roles);
  configChoices = builtins.listToAttrs (lib.imap0 (idx: roleName:
    let
      roleSeed = toString ({seed} + 1 + idx);
      fuzzedRole = fuzzer {{ seed = roleSeed; target = configTarget; }};
    in
    {{ name = roleName; value = fuzzedRole.choices; }}
  ) roleNames);
in
{{
  topologyChoices = fuzzedTopology.choices;
  inherit configChoices;
}}"""


def generate_fuzz_expr(seed: str, target_path: str, project_root: str) -> str:
    abs_target = resolve_path(target_path, project_root)
    abs_fuzzer = resolve_path("lib/fuzzer.nix", project_root)

    return f"""let
  nixpkgs = builtins.getFlake "nixpkgs";
  pkgs = nixpkgs.legacyPackages.x86_64-linux;
  lib = pkgs.lib;

  fuzzer = (import {nix_path(abs_fuzzer)} {{ inherit lib; }}).fuzzer;
  target = import {nix_path(abs_target)} {{ inherit lib; }};
in
fuzzer {{
  seed = {nix_string(seed)};
  inherit target;
}}"""


def generate_inspect_expr(
    seed: int, topology_target_path: str, config_target_path: str, project_root: str
) -> str:
    abs_topology_target = resolve_path(topology_target_path, project_root)
    abs_config_target = resolve_path(config_target_path, project_root)
    abs_fuzzer = resolve_path("lib/fuzzer.nix", project_root)
    abs_shrinker = resolve_path("lib/shrinker.nix", project_root)
    abs_expand_topology = resolve_path("lib/expand-topology.nix", project_root)

    return f"""let
  nixpkgs = builtins.getFlake "nixpkgs";
  pkgs = nixpkgs.legacyPackages.x86_64-linux;
  lib = pkgs.lib;

  fuzzer = (import {nix_path(abs_fuzzer)} {{ inherit lib; }}).fuzzer;
  shrinker = import {nix_path(abs_shrinker)} {{ inherit lib; }};
  expandTopology = (import {nix_path(abs_expand_topology)} {{ inherit lib; }}).expandTopology;
  topologyTarget = import {nix_path(abs_topology_target)} {{ inherit lib; }};
  configTarget = import {nix_path(abs_config_target)} {{ inherit lib; }};

  fuzzedTopology = fuzzer {{ seed = {nix_string(str(seed))}; target = topologyTarget; }};
  topology = shrinker.apply topologyTarget fuzzedTopology.result {{}};
  expansion = expandTopology {{ topology-map = topology; }};
  roleNames = builtins.sort (a: b: a < b) (builtins.attrNames topology.roles);
  roleFuzz = builtins.listToAttrs (lib.imap0 (idx: roleName:
    let
      roleSeed = toString ({seed} + 1 + idx);
      fuzzedRole = fuzzer {{ seed = roleSeed; target = configTarget; }};
    in
    {{
      name = roleName;
      value = {{
        seed = roleSeed;
        result = fuzzedRole.result;
        choices = fuzzedRole.choices;
      }};
    }}
  ) roleNames);
in
{{
  inherit topology roleFuzz;
  topologyChoices = fuzzedTopology.choices;
  nodeRoles = expansion.nodeRoles;
  nodeConfigs = expansion.nodeConfigs;
}}"""


def apply_overrides(args, target: Target) -> Target:
    return Target(
        name=target.name,
        description=target.description,
        topology_target=args.topology_target or target.topology_target,
        config_target=args.config_target or target.config_target,
        base_module=args.base_module or target.base_module,
        test_script=args.test_script or target.test_script,
        properties=args.properties or target.properties,
        report_node=target.report_node,
    )


def run_once(
    project_root: str,
    target: Target,
    seed: int,
    name: str,
    runs_dir: Optional[str] = None,
    topology_choices: Optional[dict] = None,
    config_choices: Optional[dict] = None,
) -> tuple[bool, list[dict], str, object]:
    store = RunStore(runs_dir or default_runs_dir(project_root))
    run = store.create_run(target.name, seed, name)
    run_dir = run["dir"]
    result_link = os.path.join(run_dir, "result")
    expr_path = os.path.join(run_dir, "expr.nix")
    started_at = utc_now()

    nix_expr = generate_nix_expr(
        seed=seed,
        topology_target_path=target.topology_target,
        config_target_path=target.config_target,
        base_module_path=target.base_module,
        test_script_path=target.test_script,
        properties_path=target.properties,
        name=name,
        project_root=project_root,
        report_node=target.report_node,
        topology_choices=topology_choices,
        config_choices=config_choices,
    )

    store.write_json(run_dir, "target.json", target.as_dict())
    store.write_json(
        run_dir,
        "choices.json",
        {"topologyChoices": topology_choices or {}, "configChoices": config_choices or {}},
    )
    result = build_test(nix_expr, result_link, expr_path=expr_path)
    store.write_text(run_dir, "stdout.log", result.stdout)
    store.write_text(run_dir, "stderr.log", result.stderr)

    build_ok = result.returncode == 0
    report = parse_report(result_link)
    store.write_json(run_dir, "report.json", report)
    passed = build_ok and report_passed(report)
    status = "passed" if passed else "failed"
    meta = {
        "id": run["id"],
        "target": target.name,
        "seed": seed,
        "name": name,
        "status": status,
        "startedAt": started_at,
        "finishedAt": utc_now(),
        "runDir": run_dir,
        "resultPath": result_link,
        "summary": report_summary(report),
        "reproduceCommand": reproduce_command(
            project_root, target, seed, name, topology_choices or {}, config_choices or {}
        ),
    }
    store.write_json(run_dir, "run.json", meta)
    return passed, report, run_dir, result


def find_existing_seeds(store: RunStore, target: Target, seeds: list[int]) -> set[int]:
    """Return the subset of `seeds` that already have a run.json for this target.

    Used by `sweep --resume` to skip seeds that have already been run (passed
    OR failed). To force a re-run, delete the corresponding run dir first.
    """
    seed_set = set(seeds)
    existing: set[int] = set()
    for meta in store.list_runs():
        if meta.get("target") != target.name:
            continue
        seed = meta.get("seed")
        if isinstance(seed, int) and seed in seed_set:
            existing.add(seed)
    return existing


def sweep_events(
    project_root: str,
    target: Target,
    seeds: list[int],
    name: Optional[str] = None,
    runs_dir: Optional[str] = None,
    fail_fast: bool = False,
    resume: bool = False,
    jobs: int = 1,
) -> Iterator[Event]:
    """Drive a sweep over `seeds`.

    With ``jobs <= 1`` runs are executed sequentially in seed order. With
    ``jobs > 1`` up to ``jobs`` seeds run concurrently in worker threads (each
    ``run_once`` blocks on a ``nix build`` subprocess, so the GIL is released).
    Run events are emitted in completion order when parallel; ``[i/total]``
    uses the completion count for executed runs and the seed-list position for
    skipped seeds. Per-run elapsed time (monotonic) is attached to every
    ``run_passed``/``run_failed`` event, and ``sweep_finished`` carries
    ``totalTime`` (wall clock) and ``avgRunTime`` (mean per-run duration).
    """
    sweep_t0 = time.monotonic()
    failures = 0
    classification_counts: dict[str, int] = {}
    skipped = 0
    sum_elapsed = 0.0
    completed = 0
    total = len(seeds)

    def record_classifications(report: list[dict]) -> None:
        for entry in report:
            status = entry.get("status", "unknown")
            classification_counts[status] = classification_counts.get(status, 0) + 1

    store = None
    existing: set[int] = set()
    if resume:
        store = RunStore(runs_dir or default_runs_dir(project_root))
        existing = find_existing_seeds(store, target, seeds)

    yield event(
        "sweep_started",
        f"Running {total} seeds",
        target=target.name,
        total=total,
        resume=resume,
        jobs=jobs,
    )

    if jobs <= 1:
        # Sequential path: preserves seed order and the generator contract.
        for index, seed in enumerate(seeds, start=1):
            if seed in existing:
                skipped += 1
                yield event(
                    "run_skipped",
                    f"[{index}/{total} (seed={seed})] {target.name} (already in run store)",
                    target=target.name,
                    seed=seed,
                    index=index,
                    total=total,
                )
                continue
            run_name = name or f"{target.name}-seed-{seed}"
            yield event(
                "run_started",
                f"[{index}/{total} (seed={seed})] {target.name}",
                target=target.name,
                seed=seed,
                index=index,
                total=total,
            )
            t0 = time.monotonic()
            passed, report, run_dir, result = run_once(
                project_root, target, seed, run_name, runs_dir
            )
            elapsed = time.monotonic() - t0
            sum_elapsed += elapsed
            completed += 1
            if not passed:
                failures += 1
            record_classifications(report)
            yield event(
                "run_passed" if passed else "run_failed",
                f"{'PASS' if passed else 'FAIL'} [{index}/{total} (seed={seed})] ({elapsed:.1f}s)",
                target=target.name,
                seed=seed,
                runDir=run_dir,
                returncode=result.returncode,
                report=report,
                failures=failures,
                elapsed=elapsed,
            )
            if failures and fail_fast:
                break
    else:
        # Parallel path: submit non-skipped seeds to a thread pool, emit
        # events in completion order. ``i`` in run events is the completion
        # count (incremented under the lock); skipped seeds keep their
        # seed-list position.
        pending: list[tuple[int, int]] = []  # (seed_list_index, seed)
        for index, seed in enumerate(seeds, start=1):
            if seed in existing:
                skipped += 1
                yield event(
                    "run_skipped",
                    f"[{index}/{total} (seed={seed})] {target.name} (already in run store)",
                    target=target.name,
                    seed=seed,
                    index=index,
                    total=total,
                )
            else:
                pending.append((index, seed))

        state_lock = threading.Lock()
        stop_submitting = False
        in_flight: dict[Future, tuple[int, int, str]] = {}

        def _run_seed(seed: int, run_name: str) -> tuple[bool, list[dict], str, object, float]:
            t0 = time.monotonic()
            passed, report, run_dir, result = run_once(
                project_root, target, seed, run_name, runs_dir
            )
            return passed, report, run_dir, result, time.monotonic() - t0

        with ThreadPoolExecutor(max_workers=jobs) as executor:
            # Prime the pool with up to `jobs` seeds, then refill as they complete.
            futures_iter = iter(pending)
            for _ in range(min(jobs, len(pending))):
                index, seed = next(futures_iter)
                run_name = name or f"{target.name}-seed-{seed}"
                yield event(
                    "run_started",
                    f"[{index}/{total} (seed={seed})] {target.name}",
                    target=target.name,
                    seed=seed,
                    index=index,
                    total=total,
                )
                fut = executor.submit(_run_seed, seed, run_name)
                in_flight[fut] = (index, seed, run_name)

            while in_flight:
                # wait(FIRST_COMPLETED) observes the *current* in_flight set,
                # so newly submitted futures are visible on the next iteration
                # (unlike as_completed(snapshot), which could hide a fast
                # failure and allow extra submissions).
                done, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
                for fut in done:
                    index, seed, run_name = in_flight.pop(fut)
                    # Cancelled futures (never started) produce no run dir and
                    # must not be counted. Running futures can't be cancelled
                    # and complete normally; their results are emitted below.
                    if fut.cancelled():
                        continue
                    passed, report, run_dir, result, elapsed = fut.result()
                    with state_lock:
                        completed += 1
                        sum_elapsed += elapsed
                        if not passed:
                            failures += 1
                        record_classifications(report)
                        done_idx = completed
                        cur_failures = failures
                    status_label = "PASS" if passed else "FAIL"
                    yield event(
                        "run_passed" if passed else "run_failed",
                        f"{status_label} [{done_idx}/{total} (seed={seed})] ({elapsed:.1f}s)",
                        target=target.name,
                        seed=seed,
                        runDir=run_dir,
                        returncode=result.returncode,
                        report=report,
                        failures=cur_failures,
                        elapsed=elapsed,
                    )
                    if fail_fast and cur_failures:
                        stop_submitting = True
                if stop_submitting:
                    # Stop refilling, but keep draining in-flight (running)
                    # futures so their results are counted and emitted.
                    # Cancel anything not yet started; running ones finish.
                    for f in list(in_flight):
                        f.cancel()
                    continue
                # Refill: one new submission per completed slot in this batch.
                for _ in done:
                    try:
                        next_index, next_seed = next(futures_iter)
                        next_name = name or f"{target.name}-seed-{next_seed}"
                        yield event(
                            "run_started",
                            f"[{next_index}/{total} (seed={next_seed})] {target.name}",
                            target=target.name,
                            seed=next_seed,
                            index=next_index,
                            total=total,
                        )
                        next_fut = executor.submit(_run_seed, next_seed, next_name)
                        in_flight[next_fut] = (next_index, next_seed, next_name)
                    except StopIteration:
                        break

    sweep_total = time.monotonic() - sweep_t0
    avg_run_time = (sum_elapsed / completed) if completed else 0.0
    yield event(
        "sweep_finished",
        "Sweep finished",
        target=target.name,
        total=total,
        skipped=skipped,
        failures=failures,
        completed=completed,
        classifications=classification_counts,
        totalTime=sweep_total,
        avgRunTime=avg_run_time,
    )


def reproduce_command(
    project_root: str,
    target: Target,
    seed: int,
    name: str,
    topology_choices: dict,
    config_choices: dict,
) -> str:
    parts = [
        "topotestix",
        "orchestrator",
        "run",
        target.name,
        "--seed",
        str(seed),
        "--name",
        name,
        "--project-root",
        project_root,
        "--topology-target",
        target.topology_target,
        "--config-target",
        target.config_target,
        "--base-module",
        target.base_module,
        "--test-script",
        target.test_script,
        "--properties",
        target.properties,
    ]
    if topology_choices:
        parts.extend(["--topology-choices", json.dumps(topology_choices, sort_keys=True)])
    if config_choices:
        parts.extend(["--config-choices", json.dumps(config_choices, sort_keys=True)])
    return " ".join(shlex.quote(part) for part in parts)


def print_summary(seed: int, name: str, report: list[dict], build_ok: bool, run_dir: str):
    """Print a human-readable test report summary.

    Outputs pass/fail per property plus an overall verdict.
    Callers are responsible for gating this behind `--quiet`.
    """
    print()
    print("=" * 60)
    print(" TopoTestix Results")
    print(f" Seed: {seed}")
    print(f" Name: {name}")
    print("=" * 60)
    if not build_ok:
        print("\n VM test FAILED (build error)")
        print(f" Run dir: {run_dir}")
        return
    if not report:
        print("\n No report.json found")
        print(f" Run dir: {run_dir}")
        return
    for entry in report:
        status = entry.get("status", "unknown")
        name_str = entry.get("name", "unnamed")
        if status == "passed":
            print(f"  PASS  {name_str}")
        elif status == "expected_failure":
            print(f"  EXPECTED FAILURE  {name_str}: {entry.get('message', '')}")
        elif status == "unexpected_pass":
            print(f"  UNEXPECTED PASS  {name_str}: {entry.get('message', '')}")
        else:
            print(f"  FAIL  {name_str}: {entry.get('message', '')}")
    print()
    print(f" Overall: {'PASSED' if report_passed(report) else 'FAILED'}")
    print(f" Run dir: {run_dir}")
    print("=" * 60)


logger = logging.getLogger("topotestix")


def _verbose(msg: str) -> None:
    """Print a diagnostic message at INFO level.

    Routes the ~15 per-step prints inside `cmd_shrink` through
    stdlib logging so they can be controlled by --quiet/--verbose
    without scattering ``if args.verbose:`` everywhere.
    """
    logger.info(msg)


def candidate_choice_maps(choices: dict):
    for path in sorted(choices):
        current = choices[path]
        if not isinstance(current, int):
            continue
        for next_index in range(current - 1, -1, -1):
            candidate = dict(choices)
            candidate[path] = next_index
            yield path, next_index, candidate


def get_cli_target(project_root: str, args) -> Target:
    if args.target == "__legacy__":
        config_target = args.config_target or getattr(args, "legacy_fuzz_target", None)
        if getattr(args, "orchestrator_command", None) == "fuzz" and config_target:
            return Target(
                name="legacy",
                description="Legacy explicit fuzz target",
                topology_target="",
                config_target=config_target,
                base_module="",
                test_script="",
                properties="",
                report_node="",
            )
        required = {
            "topology_target": args.topology_target,
            "config_target": config_target,
            "base_module": args.base_module,
            "test_script": args.test_script,
            "properties": args.properties,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"legacy target is missing required paths: {', '.join(missing)}")
        return Target(
            name="legacy",
            description="Legacy explicit path target",
            topology_target=args.topology_target,
            config_target=config_target,
            base_module=args.base_module,
            test_script=args.test_script,
            properties=args.properties,
            report_node="",
        )
    return apply_overrides(args, get_target(project_root, args.target))


def cmd_run(args, project_root: str) -> int:
    target = get_cli_target(project_root, args)
    name = args.name or f"{target.name}-seed-{args.seed}"
    if not args.quiet and not args.json:
        print(f"Running {target.name} seed={args.seed}")
    passed, report, run_dir, result = run_once(
        project_root,
        target,
        args.seed,
        name,
        runs_dir=args.output_dir,
        topology_choices=args.topology_choices,
        config_choices=args.config_choices,
    )
    if args.json:
        print(
            json.dumps(
                {"passed": passed, "runDir": run_dir, "report": report}, indent=2, sort_keys=True
            )
        )
    elif not args.quiet:
        if result.returncode != 0 and args.verbose:
            print(result.stderr, file=sys.stderr)
        print_summary(args.seed, name, report, result.returncode == 0, run_dir)
    return 0 if passed else 1


def cmd_fuzz(args, project_root: str) -> int:
    target = get_cli_target(project_root, args)
    result = eval_json(generate_fuzz_expr(str(args.seed), target.config_target, project_root))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_shrink(args, project_root: str) -> int:
    target = get_cli_target(project_root, args)
    seed = args.seed
    inputs = eval_json(
        generate_shrink_inputs_expr(
            seed, target.topology_target, target.config_target, project_root
        )
    )
    topology_choices = inputs["topologyChoices"]
    config_choices = inputs["configChoices"]
    name = args.name or f"{target.name}-shrink-{seed}"

    _verbose("Verifying initial failure before shrinking...")
    passed, _report, _run_dir, _result = run_once(
        project_root, target, seed, name, args.output_dir, topology_choices, config_choices
    )
    if passed:
        print("Initial seed passed; nothing to shrink.", file=sys.stderr)
        return 1

    changed = True
    while changed:
        changed = False
        for path, next_index, candidate in candidate_choice_maps(topology_choices):
            _verbose(f"Trying topology shrink {path} -> {next_index}")
            passed, _report, _run_dir, _result = run_once(
                project_root, target, seed, name, args.output_dir, candidate, config_choices
            )
            if not passed:
                topology_choices = candidate
                changed = True
                _verbose(f"Kept topology shrink {path} -> {next_index}")
                break
        if changed:
            continue
        for role in sorted(config_choices):
            for path, next_index, candidate_role_choices in candidate_choice_maps(
                config_choices[role]
            ):
                candidate_config_choices = dict(config_choices)
                candidate_config_choices[role] = candidate_role_choices
                _verbose(f"Trying config shrink {role}{path} -> {next_index}")
                passed, _report, _run_dir, _result = run_once(
                    project_root,
                    target,
                    seed,
                    name,
                    args.output_dir,
                    topology_choices,
                    candidate_config_choices,
                )
                if not passed:
                    config_choices = candidate_config_choices
                    changed = True
                    _verbose(f"Kept config shrink {role}{path} -> {next_index}")
                    break
            if changed:
                break

    print("Final topology choices:")
    print(json.dumps(topology_choices, indent=2, sort_keys=True))
    print("Final config choices:")
    print(json.dumps(config_choices, indent=2, sort_keys=True))
    print("Reproduce with:")
    print(reproduce_command(project_root, target, seed, name, topology_choices, config_choices))
    return 0


def parse_seed_range(value: str) -> list[int]:
    if ".." in value:
        start_s, end_s = value.split("..", 1)
        start = int(start_s)
        end = int(end_s)
        step = 1 if end >= start else -1
        return list(range(start, end + step, step))
    return [int(part) for part in value.split(",") if part]


def cmd_sweep(args, project_root: str) -> int:
    target = get_cli_target(project_root, args)
    seeds = parse_seed_range(args.seeds)
    json_mode = bool(getattr(args, "json", False))
    quiet = bool(getattr(args, "quiet", False))
    jobs = max(1, int(getattr(args, "jobs", 1) or 1))
    failures = 0
    completed = 0
    skipped = 0
    failed_runs: list[dict] = []
    classification_counts: dict[str, int] = {}
    total_time = 0.0
    avg_run_time = 0.0
    for item in sweep_events(
        project_root,
        target,
        seeds,
        args.name,
        args.output_dir,
        args.fail_fast,
        getattr(args, "resume", False),
        jobs,
    ):
        if item.type == "run_started":
            if not json_mode and not quiet:
                print(item.message)
        elif item.type == "run_skipped":
            skipped += 1
            if not json_mode and not quiet:
                print(f"  SKIP [seed={item.data['seed']}] (already in run store)")
        elif item.type in {"run_passed", "run_failed"}:
            failures = item.data["failures"]
            completed += 1
            if not json_mode and not quiet:
                print(f"  {item.message} {item.data['runDir']}")
            if item.type == "run_failed":
                failed_runs.append(
                    {
                        "seed": item.data["seed"],
                        "runDir": item.data["runDir"],
                        "returncode": item.data.get("returncode"),
                        "elapsed": item.data.get("elapsed"),
                    }
                )
        elif item.type == "sweep_finished":
            total = item.data["total"]
            total_time = float(item.data.get("totalTime", 0.0))
            avg_run_time = float(item.data.get("avgRunTime", 0.0))
            classification_counts = item.data.get("classifications", {})
            if json_mode:
                summary = {
                    "target": target.name,
                    "total": total,
                    "completed": completed,
                    "skipped": skipped,
                    "failed": failures,
                    "failures": failed_runs,
                    "classifications": classification_counts,
                    "totalTime": round(total_time, 3),
                    "avgRunTime": round(avg_run_time, 3),
                    "jobs": jobs,
                }
                print(json.dumps(summary, indent=2, sort_keys=True))
            elif not quiet:
                print(
                    f"Completed {total} planned runs; "
                    f"completed={completed} skipped={skipped} failures={failures} "
                    f"| classifications={classification_counts} "
                    f"| total {total_time:.1f}s avg {avg_run_time:.1f}s"
                )
    return 1 if failures else 0
