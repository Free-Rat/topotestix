"""Shared types and canonical hashing for the thesis reproduction harness.

This module is the frozen contract for experiments/reproduce/. Every other
module imports types and helpers from here and nowhere else.

Module contract (who implements what):
  manifest.py : load_manifest(path) -> Manifest
                expand_units(manifest, framework_rev) -> List[Unit]
  env.py      : locate_repo(project_root) -> Path
                write_lock(out_dir, project_root, manifest_path, thesis_rev) -> dict
                check_lock(out_dir) -> List[str]        # drift warnings
                host_info() -> dict                     # psutil host probe
  runner.py   : run_unit(unit, out_dir, project_root, force=False,
                         timeout=None) -> dict          # status record
                plus the psutil resource sampler subprocess.
  resolve.py  : resolve_seed(target, seed, project_root) -> dict  # topology+config
                build_resolution_artifacts(out_dir, project_root, targets, seeds)
  collect.py  : collect(out_dir) -> Collected
  analyze.py  : run_all(out_dir, collected) -> None      # writes analysis/*. artifacts
  verify.py   : run(out_dir, collected) -> dict summary  # writes verification/*
  report.py   : write_readme(out_dir) -> None
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

KINDS = {"sweep", "run", "shrink", "fuzz_only", "exhaustive", "test_suites"}

# Analysis/verification artifact ids that may appear in entry "produces".
PRODUCES_KNOWN = {
    "kafka-sweep",
    "kafka-crosstab",
    "kafka-shrink",
    "kafka-min-configs",
    "etcd-v1-sweep",
    "etcd-v2-sweep",
    "etcd-v2-quota-correlation",
    "etcd-v2-shrink",
    "etcd-v2-exhaustive",
    "rabbitmq-disk-cells",
    "rabbitmq-faildom-cells",
    "rabbitmq-crash-cells",
    "determinism",
    "parallelism",
    "test-suites",
    "resolution",
    "execution-accounting",
    "stage-timing",
}


def canonical_json(obj: Any) -> str:
    """Stable JSON text: sorted keys, no whitespace, always ASCII-safe."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def atomic_write_text(path: Union[str, Path], text: str) -> None:
    """Atomically write ``text`` (tmp file + os.replace).

    The caller must ensure the parent directory exists. The tmp file is
    fsync'd before the rename so the finished file survives a crash intact.
    This is the one write primitive every module should use for on-disk
    artifacts (JSON via ``atomic_write_json`` below, CSV/other text direct).
    """
    target = Path(path)
    tmp = target.parent / (target.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, target)


def atomic_write_json(path: Union[str, Path], obj: Any) -> None:
    """Atomically write ``obj`` as pretty JSON. See ``atomic_write_text``."""
    atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True) + "\n")


def parse_seeds(spec: Any) -> List[int]:
    """Accept "1..50", "1,3,5", [1,2], a bare int, or None -> []."""
    if spec is None:
        return []
    if isinstance(spec, int):
        return [spec]
    if isinstance(spec, list):
        return [int(s) for s in spec]
    text = str(spec).strip()
    if ".." in text:
        lo, hi = text.split("..", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(s) for s in text.split(",") if s.strip()]


@dataclass
class Variant:
    """One designed execution cell of a `run` entry (RabbitMQ / kafka-min)."""

    name: str
    executions: int = 1
    topology_choices: Optional[Dict[str, int]] = None
    config_choices: Optional[Dict[str, Any]] = None
    # Explicit target-file overrides (faithful to the thesis reproduceCommand):
    topology_target: Optional[str] = None
    config_target: Optional[str] = None
    base_module: Optional[str] = None
    test_script: Optional[str] = None
    properties: Optional[str] = None


@dataclass
class Entry:
    id: str
    kind: str
    target: Optional[str] = None
    seeds: List[int] = field(default_factory=list)
    choices: Optional[Dict[str, Any]] = None  # {"topology": {...}, "config": {...}}
    variants: List[Variant] = field(default_factory=list)
    exhaustive_dims: List[Dict[str, int]] = field(
        default_factory=list
    )  # [{"path": ".x.y", "n": 2}, ...]
    exhaustive_role: Optional[str] = None  # role key for exhaustive config choices
    topology_choices: Optional[Dict[str, int]] = None  # for exhaustive entries
    repetitions: int = 1
    jobs: Optional[int] = None  # per-entry parallelism override
    produces: List[str] = field(default_factory=list)
    notes: str = ""

    def entry_hash(self) -> str:
        payload = {
            "choices": self.choices,
            "exhaustive_dims": self.exhaustive_dims,
            "exhaustive_role": self.exhaustive_role,
            "id": self.id,
            "kind": self.kind,
            "seeds": self.seeds,
            "target": self.target,
            "topology_choices": self.topology_choices,
            "variants": [
                {
                    "config_choices": v.config_choices,
                    "config_target": v.config_target,
                    "executions": v.executions,
                    "name": v.name,
                    "properties": v.properties,
                    "test_script": v.test_script,
                    "topology_choices": v.topology_choices,
                    "topology_target": v.topology_target,
                    "base_module": v.base_module,
                }
                for v in self.variants
            ],
        }
        return canonical_hash(payload)


@dataclass
class Manifest:
    path: str
    entries: List[Entry]
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Unit:
    """A single executable experiment unit (one CLI invocation, one run dir)."""

    id: str
    entry_id: str
    kind: str
    target: Optional[str]
    seed: Optional[int]
    repetition_index: int
    execution_index: int
    variant_name: Optional[str]
    topology_choices: Optional[Dict[str, int]]
    config_choices: Optional[Dict[str, Any]]
    config_target: Optional[str]
    topology_target: Optional[str]
    base_module: Optional[str]
    test_script: Optional[str]
    properties: Optional[str]
    produces: List[str]
    # Run-name passed to the CLI (--name); distinct names force fresh nix drvs.
    run_name: str
    entry_hash: str
    # Campaign-scoped fresh-execution token (--repetition-token). None keeps the
    # pre-token behaviour. Set once per campaign from MANIFEST.lock.json, never
    # from the manifest — so it is NOT folded into ``id`` (cell + repetition
    # identity), only into ``unit_input_hash`` (skip/replay identity): a new
    # token re-runs every unit against the same ``raw/<id>/`` dir.
    repetition_token: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_choices": self.config_choices,
            "config_target": self.config_target,
            "entry_hash": self.entry_hash,
            "entry_id": self.entry_id,
            "execution_index": self.execution_index,
            "id": self.id,
            "kind": self.kind,
            "produces": sorted(self.produces),
            "repetition_index": self.repetition_index,
            "repetition_token": self.repetition_token,
            "run_name": self.run_name,
            "seed": self.seed,
            "target": self.target,
            "test_script": self.test_script,
            "topology_choices": self.topology_choices,
            "topology_target": self.topology_target,
            "base_module": self.base_module,
            "properties": self.properties,
            "variant_name": self.variant_name,
        }


def unit_id(
    target: Optional[str],
    seed: Optional[int],
    choices: Optional[Dict[str, Any]],
    repetition_index: int,
    execution_index: int,
    framework_rev: str,
    entry_hash: str,
    variant_name: Optional[str] = None,
) -> str:
    """Plan §3 ID: sha256(target + seed + canonical(choices) + repetition_index
    + framework_rev + entry_hash)[:16].  execution_index and variant_name are
    folded in so that duplicated executions / same-choices variants of an
    identical cell still get distinct IDs."""
    payload = {
        "choices": choices,
        "entry_hash": entry_hash,
        "execution_index": execution_index,
        "framework_rev": framework_rev,
        "repetition_index": repetition_index,
        "seed": seed,
        "target": target,
        "variant": variant_name,
    }
    return canonical_hash(payload)[:16]


def _expand_entry(entry: Entry, framework_rev: str) -> List[Unit]:
    units: List[Unit] = []

    def add(seed, rep, exec_i, variant, tchoices, cchoices, ttarget, ctarget, bmod, tscript, props):
        topo = (
            tchoices
            if tchoices is not None
            else (entry.topology_choices if entry.kind == "exhaustive" else None)
        )
        choices_payload = {"config": cchoices, "topology": topo}
        run_name = f"{entry.id}-rep{rep}"
        if variant is not None:
            run_name += f"-{variant}"
        # Execution index must be part of the name: identical CLI invocations
        # otherwise produce the same nix derivation (cache replay, not a
        # fresh VM run) and cross-match under concurrent scheduling.
        if entry.kind == "run":
            run_name += f"-e{exec_i}"
        elif entry.kind == "shrink":
            run_name += f"-seed{seed}"
        if entry.kind in ("sweep", "run") and seed is not None:
            run_name += f"-seed{seed}"
        # exhaustive entries already carry the cell name via the generic
        # ``-{variant}`` append above (variant == "cell{exec_i:03d}").
        uid = unit_id(
            entry.target,
            seed,
            choices_payload,
            rep,
            exec_i,
            framework_rev,
            entry.entry_hash(),
            variant,
        )
        units.append(
            Unit(
                id=uid,
                entry_id=entry.id,
                kind=entry.kind,
                target=entry.target,
                seed=seed,
                repetition_index=rep,
                execution_index=exec_i,
                variant_name=variant,
                topology_choices=topo,
                config_choices=cchoices,
                config_target=ctarget,
                topology_target=ttarget,
                base_module=bmod,
                test_script=tscript,
                properties=props,
                produces=list(entry.produces),
                run_name=run_name,
                entry_hash=entry.entry_hash(),
            )
        )

    if entry.kind == "sweep":
        for rep in range(entry.repetitions):
            for seed in entry.seeds:
                add(seed, rep, 0, None, None, None, None, None, None, None, None)
    elif entry.kind == "shrink":
        for rep in range(entry.repetitions):
            for seed in entry.seeds:
                add(seed, rep, 0, None, None, None, None, None, None, None, None)
    elif entry.kind == "fuzz_only":
        for seed in entry.seeds:
            add(seed, 0, 0, None, None, None, None, None, None, None, None)
    elif entry.kind == "exhaustive":
        dims = entry.exhaustive_dims
        combo = [0] * len(dims)
        exec_i = 0
        while True:
            config = {d["path"]: combo[i] for i, d in enumerate(dims)}
            add(
                None,
                0,
                exec_i,
                f"cell{exec_i:03d}",
                entry.topology_choices,
                {entry.exhaustive_role: config},
                None,
                None,
                None,
                None,
                None,
            )
            exec_i += 1
            i = len(dims) - 1
            while i >= 0:
                combo[i] += 1
                if combo[i] < dims[i]["n"]:
                    break
                combo[i] = 0
                i -= 1
            if i < 0:
                break
    elif entry.kind == "run":
        if entry.variants:
            for variant in entry.variants:
                for rep in range(entry.repetitions):
                    for exec_i in range(variant.executions):
                        for seed in entry.seeds or [None]:
                            add(
                                seed,
                                rep,
                                exec_i,
                                variant.name,
                                variant.topology_choices,
                                variant.config_choices,
                                variant.topology_target,
                                variant.config_target,
                                variant.base_module,
                                variant.test_script,
                                variant.properties,
                            )
        else:
            for rep in range(entry.repetitions):
                for seed in entry.seeds or [None]:
                    add(
                        seed,
                        rep,
                        0,
                        None,
                        (entry.choices or {}).get("topology"),
                        (entry.choices or {}).get("config"),
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
    elif entry.kind == "test_suites":
        for variant in entry.variants or [Variant(name="default")]:
            add(None, 0, 0, variant.name, None, None, None, None, None, None, None)
    else:
        raise ValueError(f"unknown kind {entry.kind!r}")
    return units


def expand_units(manifest: Manifest, framework_rev: str) -> List[Unit]:
    units: List[Unit] = []
    seen: Dict[str, str] = {}
    for entry in manifest.entries:
        for u in _expand_entry(entry, framework_rev):
            if u.id in seen:
                raise ValueError(f"unit id collision {u.id}: {seen[u.id]} vs {u.entry_id}")
            seen[u.id] = u.entry_id
            units.append(u)
    return units


def _entry_from_dict(raw: Dict[str, Any]) -> Entry:
    kind = raw.get("kind", "")
    if kind not in KINDS:
        raise ValueError(f"entry {raw.get('id')!r}: bad kind {kind!r}")
    seeds = parse_seeds(raw.get("seeds"))
    variants = [
        Variant(
            name=v["name"],
            executions=int(v.get("executions", 1)),
            topology_choices=v.get("topology_choices"),
            config_choices=v.get("config_choices"),
            topology_target=v.get("topology_target"),
            config_target=v.get("config_target"),
            base_module=v.get("base_module"),
            test_script=v.get("test_script"),
            properties=v.get("properties"),
        )
        for v in raw.get("variants", [])
    ]
    return Entry(
        id=raw["id"],
        kind=kind,
        target=raw.get("target"),
        seeds=seeds,
        choices=raw.get("choices"),
        variants=variants,
        exhaustive_dims=raw.get("exhaustive_dims", []),
        exhaustive_role=raw.get("exhaustive_role"),
        topology_choices=raw.get("topology_choices"),
        repetitions=int(raw.get("repetitions", 1)),
        jobs=raw.get("jobs"),
        produces=list(raw.get("produces", [])),
        notes=str(raw.get("notes", "")),
    )


def load_manifest(path: str) -> Manifest:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    entries_raw = raw["entries"] if isinstance(raw, dict) else raw
    entries = [_entry_from_dict(e) for e in entries_raw]
    meta = {k: v for k, v in raw.items() if k != "entries"} if isinstance(raw, dict) else {}
    return Manifest(path=path, entries=entries, meta=meta)
