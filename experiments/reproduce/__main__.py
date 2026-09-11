"""Campaign CLI for the thesis reproduction harness.

Run from the TopoTestix repo root:
    nix develop -c python3 -m experiments.reproduce \
        --out experiments/thesis-evals-20260904 --phase all

Phases: lock -> run (VM units + fuzz-only resolution) -> analyze -> verify -> report.
`analyze`/`verify`/`report` are pure functions of raw/ + resolution/ and are
always safe to re-run. `run` is idempotent: units with status.json
state=="done" and a matching input hash are skipped unless --force.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import sys
import time
from pathlib import Path

from experiments.reproduce import analyze, collect, env, manifest, models, report, resolve
from experiments.reproduce import runner as runner_mod
from experiments.reproduce.models import Unit, parse_seeds

# Wall-clock estimates (seconds per unit) from study/repro-discovery/0d-cost-probe.md
PER_UNIT_S = {"kafka": 214.0, "etcd": 98.0, "rabbitmq": 83.0, "shrink-loop": 1800.0}
# Per-run unique disk: the VM closure (linux/qemu ~4-5 GiB) is shared in the
# nix store; a new vm-test-run drv's own closure is small (driver + etc
# derivations).  0.1 GiB/run including raw logs is a conservative ceiling.
DISK_GB_PER_RUN = 0.1
DISK_GUARD_BYTES = 50 * 2**30  # cap the headroom requirement at 50 GiB; smaller scoped runs need less


def kind_seconds(unit: Unit) -> float:
    if unit.kind in ("sweep", "run", "exhaustive"):
        if unit.target and "kafka" in unit.target:
            return PER_UNIT_S["kafka"]
        if unit.target and "rabbitmq" in unit.target:
            return PER_UNIT_S["rabbitmq"]
        return PER_UNIT_S["etcd"]
    if unit.kind == "shrink":
        return PER_UNIT_S["shrink-loop"]
    return 0.0


def select_units(units, only: str, seeds: str):
    out = units
    if only:
        ids = {s.strip() for s in only.split(",")}
        out = [u for u in out if u.entry_id in ids]
    if seeds:
        want = set(parse_seeds(seeds))
        out = [u for u in out if u.seed in want]
    return out


def phase_lock(args) -> None:
    out = Path(args.out)
    # Written once: later runs only compare (check_lock) — the first
    # provenance record is never overwritten by a re-run.  The campaign_token
    # is the one deliberately mutable field: --fresh-token re-mints it in
    # place so a whole campaign re-executes instead of replaying the cache.
    final = out / "MANIFEST.lock.json"
    if final.is_file():
        if args.fresh_token:
            new = env.mint_campaign_token(args.campaign_token)
            env.set_campaign_token(out, new)
            print(
                f"FRESH TOKEN: campaign_token re-minted to {new!r}; every unit will "
                f"re-execute and idempotency for {out} is reset",
                file=sys.stderr,
            )
        elif args.campaign_token:
            stored = env.read_campaign_token(out)
            if stored != args.campaign_token:
                raise SystemExit(
                    f"--campaign-token {args.campaign_token!r} does not match the "
                    f"stored token {stored!r}; pass --fresh-token to change it"
                )
        for w in env.check_lock(out, args.project_root, args.manifest):
            print(f"DRIFT WARNING: {w}", file=sys.stderr)
        return
    token = env.mint_campaign_token(args.campaign_token)
    lock = env.write_lock(out, args.project_root, args.manifest, campaign_token=token)
    fw = lock["provenance"]["framework"].get("rev")
    print(f"lock written: {final} (framework {fw}, campaign_token {token})")


def phase_run(args, units) -> int:
    """Run every selected unit; returns how many ended in state "failed"."""
    # Prune raw dirs that no planned unit claims: leftovers from an earlier
    # manifest/framework revision must not leak into analysis.  NOTE: planned
    # = FULL manifest expansion, not the --only-selected subset — scoping a
    # run to one group must not delete the other groups' artifacts.
    full = manifest.expand_all(manifest.load_manifest(args.manifest), framework_rev_of(args))
    planned = {u.id for u in full}
    raw_root = Path(args.out) / "raw"
    if raw_root.is_dir():
        names = sorted(os.listdir(raw_root))
        for name in names:
            if name.endswith(".partial"):
                shutil.rmtree(raw_root / name, ignore_errors=True)
                print(f"pruned partial staging dir: {name}", file=sys.stderr)
            elif name.endswith(".stale"):
                shutil.rmtree(raw_root / name, ignore_errors=True)
                print(f"pruned stale staging dir: {name}", file=sys.stderr)
        existing = [
            n for n in names if not n.endswith((".partial", ".stale")) and (raw_root / n).is_dir()
        ]
        unplanned = [n for n in existing if n not in planned]
        # unit.id folds in framework_rev, so ANY commit, checkout or change of
        # the dirty flag re-keys every planned unit at once.  That signature —
        # existing units, none of them planned — is a changed id domain, not a
        # campaign of stale leftovers: deleting there would silently destroy a
        # whole campaign's evidence (including the gitignored *.log files).
        if (
            unplanned
            and len(unplanned) == len(existing)
            and not getattr(args, "prune_stale", False)
        ):
            raise SystemExit(
                f"prune guard: none of the {len(existing)} existing raw/ unit dirs are in the "
                f"planned set of {len(planned)} — the unit-id domain changed (unit ids fold in "
                f"the framework revision, now {framework_rev_of(args)}), so pruning would delete "
                "the entire campaign. Re-run against the campaign's own revision, use a fresh "
                "--out directory, or pass --prune-stale to delete them deliberately."
            )
        for name in unplanned:
            shutil.rmtree(raw_root / name, ignore_errors=True)
            print(f"pruned stale raw unit (not in manifest): {name}", file=sys.stderr)
    # Disk-space guard: never start a campaign (especially the 96-cell
    # exhaustive set) without verified headroom.
    n_vm = len([u for u in units if u.kind != "fuzz_only"])
    need = n_vm * DISK_GB_PER_RUN * 2**30
    free = env.disk_free(args.out)
    if free is not None and not args.allow_small_disk and free < min(need, DISK_GUARD_BYTES):
        raise SystemExit(
            f"disk guard: {free / 2**30:.1f} GiB free but ~{need / 2**30:.1f} GiB "
            f"estimated for {n_vm} VM units — free space, reduce scope, "
            "or pass --allow-small-disk to proceed anyway"
        )
    vm_units = [u for u in units if u.kind != "fuzz_only"]
    fuzz_units = [u for u in units if u.kind == "fuzz_only"]

    # Group by entry so per-entry jobs overrides apply; deterministic order.
    by_entry: dict = {}
    for u in vm_units:
        by_entry.setdefault(u.entry_id, []).append(u)
    entries = [e for e in manifest.load_manifest(args.manifest).entries if e.id in by_entry]

    jobs = args.jobs or 4
    if args.jobs == 1:
        jobs = 1
    timeout_s = getattr(args, "unit_timeout", 3600)
    total = len(vm_units)
    done = 0
    errored = 0
    failed = 0
    start = time.monotonic()
    for entry in entries:
        units_e = sorted(by_entry[entry.id], key=lambda u: u.id)
        e_jobs = entry.jobs if entry.jobs is not None else jobs
        if e_jobs <= 1 or args.jobs == 1:
            for u in units_e:
                try:
                    st = runner_mod.run_unit(
                        u, args.out, args.project_root, force=args.force, timeout_s=timeout_s
                    )
                except Exception as exc:
                    st = {"state": "failed", "error": str(exc)}
                    errored += 1
                done += 1
                if st.get("state") == "failed":
                    failed += 1
                if st.get("error"):
                    print(
                        f"[{done}/{total}] {u.entry_id} {u.run_name} -> failed ({st['error']})",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"[{done}/{total}] {u.entry_id} {u.run_name} -> {st.get('state')}",
                        flush=True,
                    )
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=e_jobs) as pool:
                futures = {
                    pool.submit(
                        runner_mod.run_unit,
                        u,
                        args.out,
                        args.project_root,
                        args.force,
                        timeout_s=timeout_s,
                    ): u
                    for u in units_e
                }
                for fut in concurrent.futures.as_completed(futures):
                    u = futures[fut]
                    try:
                        st = fut.result()
                    except Exception as exc:
                        st = {"state": "failed", "error": str(exc)}
                        errored += 1
                    done += 1
                    if st.get("state") == "failed":
                        failed += 1
                    if st.get("error"):
                        print(
                            f"[{done}/{total}] {u.entry_id} {u.run_name} -> failed "
                            f"({st['error']})",
                            file=sys.stderr,
                        )
                    else:
                        print(
                            f"[{done}/{total}] {u.entry_id} {u.run_name} -> {st.get('state')}",
                            flush=True,
                        )
    if errored:
        print(f"run phase: {errored} unit(s) raised and were recorded as failed", file=sys.stderr)
    if failed:
        print(f"run phase: {failed} unit(s) failed", file=sys.stderr)
    if fuzz_units:
        resolve.run_fuzz_units(args.out, args.project_root, fuzz_units)
        print(f"resolution: {len(fuzz_units)} fuzz units evaluated", flush=True)
    phase_digest(args)
    print(f"run phase complete in {time.monotonic() - start:.1f}s", flush=True)
    return failed


def phase_digest(args) -> None:
    """(Re)write raw/<unit>/log-digest.json for every unit dir on disk.

    run_unit writes a digest for each unit it executes; this covers units
    that were skipped as already-done (and backfills campaigns run before
    digests existed), so a committed raw/ tree carries everything analyze.py
    reads out of the gitignored *.log files."""
    raw_root = Path(args.out) / "raw"
    if not raw_root.is_dir():
        return
    written = 0
    refreshed = 0
    for name in sorted(os.listdir(raw_root)):
        unit_dir = raw_root / name
        if not unit_dir.is_dir() or name.endswith((".partial", ".stale")):
            continue
        final_trial = None
        trials = None
        try:
            with open(unit_dir / "trials.json", "r", encoding="utf-8") as fh:
                trials = json.load(fh)
        except (OSError, ValueError):
            trials = None
        if isinstance(trials, list) and trials and isinstance(trials[-1], dict):
            candidate = raw_root / name / "run-store" / str(trials[-1].get("dir"))
            if candidate.is_dir():
                final_trial = candidate
        if runner_mod.write_log_digest(unit_dir, final_trial) is not None:
            written += 1
        if final_trial is not None:
            refreshed += _refresh_phase_markers(unit_dir, final_trial)
    print(f"log digests written: {written}; timing stage markers refreshed: {refreshed}")


def _refresh_phase_markers(unit_dir: Path, final_trial: Path) -> int:
    """Rewrite timing.json's stage info from the trial log, dropping the old
    "phases" key — it held log-line counts written as if they were seconds."""
    timing_path = unit_dir / "timing.json"
    try:
        with open(timing_path, "r", encoding="utf-8") as fh:
            timing_doc = json.load(fh)
    except (OSError, ValueError):
        return 0
    if not isinstance(timing_doc, dict):
        return 0
    combined = ""
    for name in ("stdout.log", "stderr.log"):
        try:
            combined += (final_trial / name).read_text(encoding="utf-8", errors="replace") + "\n"
        except OSError:
            pass
    phases = runner_mod._parse_log_phases(combined)
    had_phases = "phases" in timing_doc
    if phases is None and not had_phases:
        return 0
    timing_doc.pop("phases", None)
    timing_doc.pop("phases_completeness", None)
    if phases is not None:
        timing_doc["phase_markers"] = phases["markers"]
        timing_doc["phase_markers_completeness"] = phases["completeness"]
    models.atomic_write_json(timing_path, timing_doc)
    return 1


def phase_analyze(args) -> None:
    data = collect.collect(args.out)
    analyze.run_all(args.out, data)
    print("analysis written")


def phase_verify(args) -> dict:
    data = collect.collect(args.out)
    summary = verify_run(args, data)
    print(
        f"verify: {summary['match']} match / {summary['within-tolerance']} within-tolerance / "
        f"{summary['mismatch']} mismatch / {summary['not-reproduced']} not-reproduced"
    )
    return summary


def verify_run(args, data):
    from experiments.reproduce import verify

    claims = args.claims or str(Path(args.project_root) / "study/repro-discovery/claims.csv")
    return verify.run(Path(args.out), data, claims)


def phase_report(args, summary) -> None:
    # Without a verify phase in this invocation the summary is empty; the
    # report then has to come from the claims matrix on disk.  Refuse rather
    # than overwrite a real report with an all-zero one.
    if not summary.get("rows") and not report.load_matrix_rows(Path(args.out)):
        raise SystemExit(
            f"report: no claim rows — {Path(args.out) / 'verification/claims-matrix.csv'} "
            "is missing and verify did not run in this invocation; "
            "run with --phase verify first (or --phase all)"
        )
    report.write_verification_report(Path(args.out), summary)
    report.write_readme(Path(args.out), args.manifest)
    print("report written")


def framework_rev_of(args) -> str:
    rev_doc = env.git_rev(args.project_root)
    return f"{rev_doc.get('rev', 'unknown')}{'-dirty' if rev_doc.get('dirty') else ''}"


def phase_dry_run(args, units) -> None:
    token = units[0].repetition_token if units else None
    print(f"campaign_token: {token or '(minted when the lock is written)'}")
    print(f"units selected: {len(units)}")
    per_entry: dict = {}
    for u in units:
        d = per_entry.setdefault(u.entry_id, {"n": 0, "s": 0.0, "kinds": set()})
        d["n"] += 1
        d["s"] += kind_seconds(u)
        d["kinds"].add(u.kind)
    total_s = 0.0
    for eid in sorted(per_entry):
        d = per_entry[eid]
        total_s += d["s"]
        print(f"  {eid:35s} n={d['n']:4d} est={d['s'] / 3600.0:6.2f}h  kinds={sorted(d['kinds'])}")
    jobs = args.jobs or 4
    hours = total_s / 3600.0
    par = min(jobs, 4)
    print(
        f"estimated wall-clock: jobs=1 {hours:.1f}h | jobs={jobs} ~{hours / par:.1f}h (RAM-bound)"
    )
    n_vm = len([u for u in units if u.kind != "fuzz_only"])
    print(f"estimated disk: ~{n_vm * DISK_GB_PER_RUN}GB (VM closures)")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="experiments.reproduce")
    p.add_argument("--out", default="experiments/thesis-evals-20260904")
    p.add_argument("--manifest", default="experiments/reproduce/MANIFEST.json")
    p.add_argument(
        "--claims", default=None, help="claims.csv path (default study/repro-discovery/claims.csv)"
    )
    p.add_argument("--project-root", default=".")
    p.add_argument("--only", default=None, help="comma-separated manifest entry ids")
    p.add_argument("--seeds", default=None, help="seed filter")
    p.add_argument("--jobs", type=int, default=None)
    p.add_argument(
        "--unit-timeout",
        type=int,
        default=3600,
        help="seconds before a unit's process group is killed (default 3600)",
    )
    p.add_argument(
        "--phase",
        default="all",
        choices=["lock", "run", "digest", "analyze", "verify", "report", "all", "dry-run"],
    )
    p.add_argument("--force", action="store_true", help="re-run units even if done")
    p.add_argument(
        "--prune-stale",
        action="store_true",
        help="delete raw/ unit dirs outside the planned set even when NONE of "
        "them is planned (the signature of a changed unit-id domain, e.g. a "
        "different framework revision). Destroys that campaign's evidence.",
    )
    p.add_argument(
        "--allow-small-disk",
        action="store_true",
        help="bypass the disk-space guard (owner accepts the risk)",
    )
    p.add_argument(
        "--campaign-token",
        default=None,
        help="explicit fresh-execution token to record in MANIFEST.lock.json on "
        "first lock (default: auto 'c<date>-<hex>'). Threaded into every unit's "
        "--repetition-token so a new campaign is a genuine fresh VM run, not a "
        "Nix cache replay. Excluded from cell identity, so repetitions stay "
        "comparable.",
    )
    p.add_argument(
        "--fresh-token",
        action="store_true",
        help="re-mint campaign_token in an existing lock: forces every unit to "
        "re-execute against the same out dir (resets idempotency for that dir).",
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help="implies --force and --fresh-token: re-mint the campaign token and "
        "re-run every selected unit as a genuine fresh VM execution.",
    )
    args = p.parse_args(argv)
    if args.jobs is not None and args.jobs < 1:
        p.error("--jobs must be >= 1")
    if args.unit_timeout < 1:
        p.error("--unit-timeout must be >= 1")
    if args.fresh:
        args.force = True
        args.fresh_token = True

    m = manifest.load_and_validate(args.manifest)
    lock_exists = (Path(args.out) / "MANIFEST.lock.json").is_file()
    lock_done = False
    if args.phase in ("run", "all") and (not lock_exists or args.fresh_token):
        # A run without a lock has no pinned provenance — lock first.  With
        # --fresh-token, re-lock even when one exists so the token is re-minted.
        if not lock_exists:
            print("no MANIFEST.lock.json — running lock phase first", file=sys.stderr)
        phase_lock(args)
        lock_done = True
    elif args.phase == "run":
        # "all" reaches phase_lock below, which runs the same check.
        for w in env.check_lock(Path(args.out), args.project_root, args.manifest):
            print(f"DRIFT WARNING: {w}", file=sys.stderr)
    rev_doc = env.git_rev(args.project_root)
    framework_rev = f"{rev_doc.get('rev', 'unknown')}{'-dirty' if rev_doc.get('dirty') else ''}"
    units = manifest.expand_all(m, framework_rev)
    units = select_units(units, args.only, args.seeds)

    # Campaign token: written by phase_lock, read back here and threaded into
    # every unit.  unit.id stays token-free (stable raw/<id>/ dir); only
    # unit_input_hash sees it, so a re-minted token re-runs everything.
    campaign_token = env.read_campaign_token(Path(args.out))
    if campaign_token:
        for u in units:
            u.repetition_token = campaign_token

    if args.phase == "dry-run":
        phase_dry_run(args, units)
        return 0
    if args.phase in ("lock", "all") and not lock_done:
        # phase_lock must run at most once per invocation: with --fresh-token
        # and run/all the guard above already re-minted the token and the
        # units read it back — locking again would store a different token
        # than the one the units executed with, breaking idempotency.
        phase_lock(args)
    run_failed = 0
    if args.phase in ("run", "all"):
        # Failed units don't stop "all": analysis still runs on what exists,
        # but the exit status reports the failure.
        run_failed = phase_run(args, units) or 0
    if args.phase == "digest":
        phase_digest(args)
        return 0
    if args.phase in ("analyze", "all"):
        phase_analyze(args)
    summary = {"match": 0, "within-tolerance": 0, "mismatch": 0, "not-reproduced": 0}
    if args.phase in ("verify", "all"):
        summary = phase_verify(args)
    if args.phase in ("report", "all"):
        phase_report(args, summary)
    return 1 if run_failed else 0


if __name__ == "__main__":
    sys.exit(main())
