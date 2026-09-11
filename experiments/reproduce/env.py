"""Environment provenance: repo location, git/nix/host snapshots, and the lock file.

Everything written here goes into ``MANIFEST.lock.json`` (the reproduction
provenance record).  The only harness-generated timestamp is
``provenance.written_at`` in ``write_lock``; harness-written artifacts carry no
other timestamps, so artifact diffs show real drift only.  The auto-minted
campaign token (``mint_campaign_token``) embeds a coarse UTC date as
human-readable context in an otherwise opaque random token — not provenance.
Timestamps under raw/ (RunStore trial directory names, run.json
startedAt/finishedAt) are upstream CLI data copied through verbatim, not
harness provenance.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from experiments.reproduce.models import atomic_write_json

DEFAULT_THESIS_REPO = "/home/freerat/projects/master-thesis"

# Nix derivation names accept [A-Za-z0-9+._?=-] and must not start with a dot;
# the token is concatenated as "<run-name>-<token>", so keep it to this set.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def mint_campaign_token(explicit: Optional[str] = None) -> str:
    """Return the fresh-execution token for a campaign.

    ``explicit`` (from --campaign-token) is validated and returned as-is;
    otherwise a new ``c<UTC-date>-<6 hex>`` token is generated. A fresh value
    every call is intentional: re-minting is how --fresh-token forces a whole
    campaign to re-execute rather than replay the Nix cache.
    """
    if explicit is not None:
        if not _TOKEN_RE.match(explicit):
            raise ValueError(
                f"--campaign-token {explicit!r} must match {_TOKEN_RE.pattern} "
                "(letters, digits, '.', '_', '+', '-'; no leading dot)"
            )
        return explicit
    return f"c{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(3)}"


try:  # psutil is NOT installed in this environment; /proc fallbacks are required.
    import psutil  # type: ignore
except ImportError:  # pragma: no cover - depends on host
    psutil = None  # type: ignore[assignment]


def locate_repo(project_root: str) -> Path:
    """Resolve ``project_root`` and validate it is the TopoTestix repo."""
    root = Path(project_root).resolve()
    for marker in ("flake.nix", "targets", "lib"):
        if not (root / marker).exists():
            raise ValueError(f"{root} is not the TopoTestix repo (missing {marker!r})")
    return root


def _git(args: List[str], cwd: str, timeout: int = 30) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError):
        return None


def git_rev(project_root: str) -> Dict[str, Any]:
    """{"rev": sha, "dirty": bool, "dirty_files": [paths]} of the framework repo."""
    rev = None
    dirty = False
    dirty_files: List[str] = []
    proc = _git(["rev-parse", "HEAD"], project_root)
    if proc is not None and proc.returncode == 0:
        rev = proc.stdout.strip()
    proc = _git(["status", "--porcelain"], project_root)
    if proc is not None and proc.returncode == 0:
        dirty_files = _porcelain_paths(proc.stdout)
        dirty = bool(dirty_files)
    return {"rev": rev, "dirty": dirty, "dirty_files": dirty_files}


def _porcelain_paths(stdout: str) -> List[str]:
    """Paths from ``git status --porcelain`` (v1) output."""
    paths: List[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        # porcelain v1: "XY path" (renames: "XY old -> new").  Slice the
        # RAW line: stripping first eats the status column's own leading
        # space, so " M .gitignore" would come back as "gitignore".
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path)
    return paths


def _read_meminfo() -> Dict[str, int]:
    total = 0
    available = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    fields = rest.split()
                    if fields:
                        value = int(fields[0]) * 1024
                        if key == "MemTotal":
                            total = value
                        else:
                            available = value
    except (OSError, ValueError):
        pass
    return {"total": total, "available": available}


def host_info() -> Dict[str, Any]:
    """hostname, cpus, RAM (psutil if available, else /proc/meminfo), kernel, python."""
    if psutil is not None:
        vm = psutil.virtual_memory()
        total = int(vm.total)
        available = int(vm.available)
        method = "psutil"
    else:
        mem = _read_meminfo()
        total = mem["total"]
        available = mem["available"]
        method = "proc"
    return {
        "hostname": socket.gethostname(),
        "cpu_count": os.cpu_count(),
        "total_ram_bytes": total,
        "available_ram_bytes": available,
        "kernel": platform.release(),
        "python": platform.python_version(),
        "method": method,
    }


def nix_info(project_root: str) -> Dict[str, Any]:
    """`nix --version` + nixpkgs rev from `nix flake metadata --json` (best effort)."""
    info: Dict[str, Any] = {"version": None, "nixpkgs_rev": None, "error": None}
    try:
        proc = subprocess.run(["nix", "--version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        info["error"] = str(exc)
        return info
    if proc.returncode != 0:
        info["error"] = proc.stderr.strip() or f"nix --version exited {proc.returncode}"
        return info
    lines = proc.stdout.strip().splitlines()
    if lines:
        info["version"] = lines[0]
    try:
        proc = subprocess.run(
            ["nix", "flake", "metadata", "--json", str(project_root)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            info["error"] = proc.stderr.strip() or f"nix flake metadata exited {proc.returncode}"
            return info
        meta = json.loads(proc.stdout)
        locks = meta.get("locks") or {}
        if not isinstance(locks, dict):
            return info
        nodes = locks.get("nodes") or {}
        root_name = locks.get("root")
        root_inputs = {}
        if isinstance(root_name, str):
            root_inputs = (nodes.get(root_name) or {}).get("inputs") or {}
        elif isinstance(root_name, dict):
            root_inputs = root_name.get("inputs") or {}
        for name in root_inputs.values():
            node = nodes.get(name) if isinstance(name, str) else None
            locked = (node or {}).get("locked") or {}
            if locked.get("rev"):
                info["nixpkgs_rev"] = locked["rev"]
                break
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
        KeyError,
        AttributeError,
    ) as exc:
        info["error"] = str(exc)
    return info


def thesis_rev(thesis_repo: str = DEFAULT_THESIS_REPO) -> Optional[Dict[str, Any]]:
    """Git rev + dirty state of the thesis repo; None when unreachable."""
    proc = _git(["rev-parse", "HEAD"], thesis_repo)
    if proc is None or proc.returncode != 0:
        return None
    rev = proc.stdout.strip()
    dirty = None
    dirty_files: List[str] = []
    proc = _git(["status", "--porcelain"], thesis_repo)
    if proc is not None and proc.returncode == 0:
        dirty_files = _porcelain_paths(proc.stdout)
        dirty = bool(dirty_files)
    return {"rev": rev, "dirty": dirty, "dirty_files": dirty_files}


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def disk_free(path: str) -> int:
    """Free bytes at ``path``."""
    return shutil.disk_usage(path).free


def build_lock(
    project_root: str,
    manifest_path: str,
    thesis_path: str = DEFAULT_THESIS_REPO,
    campaign_token: Optional[str] = None,
) -> Dict[str, Any]:
    """The lock document; ``written_at`` is the harness's only generated timestamp."""
    manifest_sha = file_sha256(manifest_path)
    return {
        "provenance": {
            "written_at": datetime.now(timezone.utc).isoformat(),
            "framework": git_rev(project_root),
            "nix": nix_info(project_root),
            "python": {"version": platform.python_version(), "executable": sys.executable},
            "host": host_info(),
            "manifest": {"path": manifest_path, "sha256": manifest_sha},
            "thesis": thesis_rev(thesis_path),
        },
        "manifest_sha256": manifest_sha,
        # Fresh-execution token threaded into every unit's --repetition-token.
        # Written once; re-minted only on an explicit --fresh-token.
        "campaign_token": campaign_token,
    }


def write_lock(
    out_dir: Path,
    project_root: str,
    manifest_path: str,
    thesis_path: str = DEFAULT_THESIS_REPO,
    campaign_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Build and atomically write ``MANIFEST.lock.json``; returns the document."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    lock = build_lock(project_root, manifest_path, thesis_path, campaign_token)
    atomic_write_json(out / "MANIFEST.lock.json", lock)
    return lock


def read_campaign_token(out_dir: Path) -> Optional[str]:
    """The campaign token recorded in ``MANIFEST.lock.json``; None if absent."""
    path = Path(out_dir) / "MANIFEST.lock.json"
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    token = lock.get("campaign_token")
    return token if isinstance(token, str) and token else None


def set_campaign_token(out_dir: Path, token: str) -> None:
    """Rewrite only ``campaign_token`` in an existing lock (for --fresh-token).

    The provenance block is preserved untouched — the environment record is
    still write-once; only the execution token is deliberately mutable.
    """
    path = Path(out_dir) / "MANIFEST.lock.json"
    lock = json.loads(path.read_text(encoding="utf-8"))
    lock["campaign_token"] = token
    atomic_write_json(path, lock)


def check_lock(out_dir: Path, project_root: str, manifest_path: str) -> List[str]:
    """Compare the lock against current rev/dirty/manifest hash; list of drift warnings."""
    path = Path(out_dir) / "MANIFEST.lock.json"
    if not path.is_file():
        return ["MANIFEST.lock.json missing — run phase 'lock'"]
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"MANIFEST.lock.json unreadable: {exc}"]
    prov = lock.get("provenance") or {}
    warnings: List[str] = []
    current_fw = git_rev(project_root)
    locked_fw = prov.get("framework") or {}
    if locked_fw.get("rev") != current_fw.get("rev"):
        warnings.append(
            f"framework rev drift: locked {locked_fw.get('rev')} vs current {current_fw.get('rev')}"
        )
    if locked_fw.get("dirty") != current_fw.get("dirty"):
        warnings.append(
            f"framework dirty-state drift: locked {locked_fw.get('dirty')} vs current "
            f"{current_fw.get('dirty')}"
        )
    try:
        current_sha = file_sha256(manifest_path)
    except OSError as exc:
        current_sha = None
        warnings.append(f"manifest unreadable: {exc}")
    locked_sha = (prov.get("manifest") or {}).get("sha256")
    if current_sha is not None and locked_sha != current_sha:
        warnings.append(f"manifest sha256 drift: locked {locked_sha} vs current {current_sha}")
    return warnings


__all__ = [
    "DEFAULT_THESIS_REPO",
    "build_lock",
    "check_lock",
    "disk_free",
    "file_sha256",
    "git_rev",
    "host_info",
    "locate_repo",
    "mint_campaign_token",
    "nix_info",
    "read_campaign_token",
    "set_campaign_token",
    "thesis_rev",
    "write_lock",
]
