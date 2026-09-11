"""collect.py — pure read of the campaign tree into the Collected record.

Contract (frozen in models.py): collect(out_dir) -> Collected.
Reads and only reads:

  raw/<unit-id>/          one directory per planned unit; whatever files the
                          runner wrote (status.json, run.json, choices.json,
                          resolved.json, report.json, timing.json,
                          resources.json, nix-build.json, shrink.json,
                          target.json, stdout.log, stderr.log, trials.json,
                          plus any materialised evidence payloads like
                          disk-results.json / *-results.json, plus
                          log-digest.json — the committed, bounded projection
                          of the gitignored *.log files, used as the stdout /
                          stderr source when the logs themselves are absent
                          from the tree). The flat files
                          are the FINAL trial only (a shrink unit tries many);
                          trials.json indexes every trial (see runner.py
                          _index_run_store); the full per-trial data,
                          including every candidate's own build log, lives
                          under raw/<unit-id>/run-store/<trial>/ — not read by
                          collect() (kept out of memory; large campaigns can
                          have many trials), but on disk for anyone who wants
                          the raw evidence.
  resolution/<target>/    per-seed-choices.jsonl, uniqueness.json,
                          marginals.csv, pairwise-coverage.json (optional;
                          resolve.py may not have run).

Rules:
  - one record per raw/<unit-id> directory (keep it dumb and robust);
  - missing file => key absent from the record (never fabricated data);
  - JSON parse failures => key absent;
  - any other *.json in the unit dir is treated as materialised evidence and
    collected under record["evidence"][<filename>].
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Files merged into the record under their basename-without-.json stem.
_KNOWN_STEMS = (
    "unit",
    "status",
    "run",
    "choices",
    "resolved",
    "report",
    "timing",
    "resources",
    "nix-build",
    "shrink",
    "target",
    "trials",
)


@dataclass
class Collected:
    """Everything analyze.py/verify.py are allowed to look at."""

    units: List[Dict[str, Any]] = field(default_factory=list)
    by_entry: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    resolution: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    out_dir: Optional[Path] = None


def _read_json(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _read_text(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _digest_text(digest: Any, stream: str) -> Optional[str]:
    """The digest's stored lines for ``stream``, rejoined, or None."""
    if not isinstance(digest, dict):
        return None
    streams = digest.get("streams")
    if not isinstance(streams, dict):
        return None
    entry = streams.get(stream)
    if not isinstance(entry, dict) or not isinstance(entry.get("lines"), list):
        return None
    return "\n".join(str(line) for line in entry["lines"])


def _collect_unit_dir(unit_dir: Path) -> Dict[str, Any]:
    record: Dict[str, Any] = {"id": unit_dir.name, "evidence": {}}
    for name in sorted(os.listdir(unit_dir)):
        path = unit_dir / name
        if not path.is_file():
            continue
        if name == "stdout.log":
            record["stdout"] = _read_text(path)
            continue
        if name == "stderr.log":
            record["stderr"] = _read_text(path)
            continue
        if not name.endswith(".json"):
            continue
        data = _read_json(path)
        if data is None:
            continue
        stem = name[: -len(".json")]
        if stem == "log-digest":
            record["log_digest"] = data
            continue
        if stem in _KNOWN_STEMS:
            record[stem] = data
            # The runner embeds Unit.to_dict() in status.json["unit"]; lift it
            # so record["unit"] is always the unit spec when available.
            if stem == "status" and isinstance(data.get("unit"), dict):
                record["unit"] = data["unit"]
        else:
            record["evidence"][name] = data
    # The *.log files are gitignored (too large for git), so from a fresh
    # clone they are simply absent.  log-digest.json is the committed,
    # bounded projection of them (runner.write_log_digest): fall back to it so
    # analysis stays a function of what raw/ actually carries in git.
    for stream in ("stdout", "stderr"):
        # Falsy covers both "file absent" and "file present but empty" — an
        # empty log carries nothing the digest would be shadowing.
        if not record.get(stream):
            text = _digest_text(record.get("log_digest"), stream)
            if text is not None:
                record[stream] = text
                record.setdefault("log_source", {})[stream] = "digest"
        elif "log_digest" in record:
            record.setdefault("log_source", {})[stream] = "log"
    console = _digest_text(record.get("log_digest"), "final_trial_console")
    if console is not None:
        record["final_trial_console_digest"] = console
    return record


def _collect_resolution_target(target_dir: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in sorted(os.listdir(target_dir)):
        path = target_dir / name
        if not path.is_file():
            continue
        if name.endswith(".jsonl"):
            lines: List[Any] = []
            for line in _read_text(path).splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    lines.append(json.loads(line))
                except ValueError:
                    pass
            out[name] = lines
        elif name.endswith(".json"):
            data = _read_json(path)
            if data is not None:
                out[name] = data
        else:
            out[name] = _read_text(path)
    return out


def collect(out_dir: Path) -> Collected:
    out_dir = Path(out_dir)
    units: List[Dict[str, Any]] = []
    raw_dir = out_dir / "raw"
    if raw_dir.is_dir():
        for name in sorted(os.listdir(raw_dir)):
            if name.endswith(".partial") or name.endswith(".stale"):
                # ".partial": in-flight staging dir from a killed run;
                # ".stale": old copy renamed aside by _promote when a kill
                # landed mid-swap (phase_run prunes these; collect must never
                # treat either as a completed unit record, so analysis stays
                # byte-identical across a kill/resume).
                continue
            unit_dir = raw_dir / name
            if unit_dir.is_dir():
                units.append(_collect_unit_dir(unit_dir))

    by_entry: Dict[str, List[Dict[str, Any]]] = {}
    for rec in units:
        entry = rec.get("unit", {}).get("entry_id") or rec.get("entry_id")
        if entry is None:
            entry = ""
        by_entry.setdefault(entry, []).append(rec)

    resolution: Dict[str, Dict[str, Any]] = {}
    res_dir = out_dir / "resolution"
    if res_dir.is_dir():
        for name in sorted(os.listdir(res_dir)):
            target_dir = res_dir / name
            if target_dir.is_dir():
                resolution[name] = _collect_resolution_target(target_dir)

    return Collected(units=units, by_entry=by_entry, resolution=resolution, out_dir=out_dir)
