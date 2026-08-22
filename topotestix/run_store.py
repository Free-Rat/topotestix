import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any


def default_runs_dir(project_root: str) -> str:
    return os.path.join(project_root, ".topotestix", "runs")


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "run"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def git_head(cwd: str) -> str:
    """Return the full Git revision (HEAD) of the repository at `cwd`, or "".

    Used to stamp run metadata with provenance. Fails soft so that runs
    started outside a repository (or with git unavailable) are still recorded,
    just with an empty revision.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def materialize_result_artifacts(result_path: str, run_dir: str) -> list[str]:
    """Copy evidence artifacts out of the test's $out store path into the run dir.

    The NixOS test driver writes files copied from guests (the target's
    results payload plus report.json) into the test derivation's output
    directory, which is only reachable through the run dir's `result` symlink.
    That store path is not a GC root, so the artifacts are materialized into
    the run directory to make retention explicit and immune to `nix-store --gc`.

    Returns the sorted list of copied entry names. A missing `result` store
    path (build failure) yields an empty list. Entries already present in the
    run dir (e.g. the canonically written report.json) are skipped, never
    overwritten: store copies are read-only 444 and the canonical run-dir
    files must win.
    """
    src_dir = os.path.realpath(result_path)
    if not os.path.isdir(src_dir):
        return []
    copied = []
    for entry in sorted(os.listdir(src_dir)):
        src = os.path.join(src_dir, entry)
        dst = os.path.join(run_dir, entry)
        if os.path.exists(dst):
            continue
        if os.path.isfile(src):
            shutil.copy2(src, dst)
        elif os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            continue
        copied.append(entry)
    return copied


class RunStore:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def create_run(self, target: str, seed: int, name: str) -> dict[str, str]:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        base_id = safe_name(f"{timestamp}-{target}-seed-{seed}-{name}")
        suffix = 0
        while True:
            run_id = base_id if suffix == 0 else f"{base_id}-{suffix}"
            run_dir = os.path.join(self.root, run_id)
            try:
                # Atomic create: fails if another process/thread made it first.
                os.makedirs(run_dir, exist_ok=False)
                return {"id": run_id, "dir": run_dir}
            except FileExistsError:
                suffix += 1

    def write_json(self, run_dir: str, filename: str, value: Any) -> None:
        with open(os.path.join(run_dir, filename), "w") as f:
            json.dump(value, f, indent=2, sort_keys=True)
            f.write("\n")

    def write_text(self, run_dir: str, filename: str, value: str) -> None:
        with open(os.path.join(run_dir, filename), "w") as f:
            f.write(value)

    def list_runs(self) -> list[dict[str, Any]]:
        runs = []
        if not os.path.exists(self.root):
            return runs
        for run_id in sorted(os.listdir(self.root), reverse=True):
            run_dir = os.path.join(self.root, run_id)
            meta_path = os.path.join(run_dir, "run.json")
            if not os.path.isfile(meta_path):
                continue
            with open(meta_path) as f:
                meta = json.load(f)
            meta.setdefault("id", run_id)
            meta.setdefault("runDir", run_dir)
            runs.append(meta)
        return runs

    def resolve_run(self, run_id_or_path: str) -> str:
        if os.path.isdir(run_id_or_path):
            return run_id_or_path
        candidate = os.path.join(self.root, run_id_or_path)
        if os.path.isdir(candidate):
            return candidate
        matches = [run for run in self.list_runs() if run["id"].startswith(run_id_or_path)]
        if len(matches) == 1:
            return matches[0]["runDir"]
        if not matches:
            raise FileNotFoundError(f"unknown run: {run_id_or_path}")
        raise ValueError(f"ambiguous run prefix: {run_id_or_path}")
