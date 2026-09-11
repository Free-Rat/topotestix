"""Fuzz-only resolution phase: pure per-seed configuration resolution.

For a target and a seed list, resolves the full per-seed configuration
(topology AND per-role config) purely, with no VM builds, and computes the
resolution statistics (uniqueness, marginals, pairwise coverage).

Method (mirrors lib/orchestrate.nix seed derivation exactly):
  The per-seed resolution is a single pure `nix eval` of
  topotestix.orchestrator.generate_inspect_expr, which evaluates
  lib/fuzzer.nix over topology.nix with fuzzer seed str(master) and over
  config.nix once per role with fuzzer seed str(master + 1 + roleIndex),
  roles in alphabetical order -- the same expressions orchestrate.nix
  evaluates inside every real run (shrinker applied with empty overrides is
  the identity). No `nix build`, no run store.

Candidate counts (dim_counts / space_size) are computed per target by a
`nix eval` over the target files that reports, for every fuzzable path
(any list -- the fuzzer treats every list as a choice list), the candidate
count and the candidate values. Results are cached per target so resolving
50 seeds costs 50 resolution evals + 1 counting eval.

All artifacts are deterministic: sorted keys, no timestamps, floats
formatted with "%.6g" BEFORE writing (as strings).
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import sys
from typing import Any, Dict, Iterable, List, Tuple

from experiments.reproduce.models import (
    Unit,
    atomic_write_json,
    atomic_write_text,
    canonical_hash,
    canonical_json,
)
from topotestix.nix import eval_json, nix_path
from topotestix.orchestrator import generate_inspect_expr
from topotestix.targets import get_target

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def fmt6(value: float) -> str:
    """Thesis float formatting: "%.6g", applied BEFORE writing (string)."""
    return f"{float(value):.6g}"


def value_at(obj: Any, path: str) -> Any:
    """Fetch a value by dotted choice path (".a.b" -> obj["a"]["b"]).

    Attribute keys may THEMSELVES contain dots (e.g. the Kafka settings
    key "auto.create.topics.enable"), so traversal tries the longest
    remaining key first at each step and falls back to single segments."""
    parts = [p for p in path.lstrip(".").split(".") if p != ""]
    cur = obj
    i = 0
    while i < len(parts):
        if not isinstance(cur, dict):
            return None
        matched = False
        for j in range(len(parts), i, -1):
            key = ".".join(parts[i:j])
            if key in cur:
                cur = cur[key]
                i = j
                matched = True
                break
        if not matched:
            return None
    return cur


# ---------------------------------------------------------------------------
# Per-seed records
# ---------------------------------------------------------------------------


def seed_line(record: Dict[str, Any]) -> str:
    """Canonical per-seed jsonl line (sorted keys, compact)."""
    return canonical_json(
        {
            "config": record["config"],
            "config_choices": record["config_choices"],
            "seed": record["seed"],
            "topology": record["topology"],
            "topology_choices": record["topology_choices"],
        }
    )


def resolved_hash(record: Dict[str, Any]) -> str:
    """sha256 over the canonical resolved configuration (topology + config)."""
    return canonical_hash({"config": record["config"], "topology": record["topology"]})


def collision_groups(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group per-seed records by resolved-config hash; keep groups with >1 seed.

    Returns [{"hash": <sha>, "seeds": [..]} ...] sorted by hash.
    """
    by_hash: Dict[str, List[int]] = {}
    for record in records:
        by_hash.setdefault(resolved_hash(record), []).append(int(record["seed"]))
    return [
        {"hash": digest, "seeds": sorted(seeds)}
        for digest, seeds in sorted(by_hash.items())
        if len(seeds) > 1
    ]


# ---------------------------------------------------------------------------
# Dimension enumeration (candidate counts + values, cached per target)
# ---------------------------------------------------------------------------

_DIM_CACHE: Dict[Tuple[str, str], Dict[str, Any]] = {}


def _counts_expr(topology_path: str, config_path: str) -> str:
    """nix eval expression: candidate counts+values for every fuzzable path.

    The fuzzer (lib/combinators.nix resolveWithKeyPrefix) treats EVERY list as
    a choice list, so every list path is a fuzzable dimension with n = length.
    """
    return f"""let
  nixpkgs = builtins.getFlake "nixpkgs";
  pkgs = nixpkgs.legacyPackages.x86_64-linux;
  lib = pkgs.lib;

  dims = prefix: v:
    if builtins.isList v then
      {{ "${{prefix}}" = {{ n = builtins.length v; values = v; }}; }}
    else if builtins.isAttrs v then
      builtins.foldl' (acc: n: acc // dims (prefix + "." + n) v.${{n}}) {{}}
        (builtins.attrNames v)
    else if builtins.isFunction v then
      dims prefix (v {{ inherit lib; }})
    else
      {{}};

  topologyTarget = import {nix_path(topology_path)} {{ inherit lib; }};
  configTarget = import {nix_path(config_path)} {{ inherit lib; }};
in
{{
  topology = dims "" topologyTarget;
  config = dims "" configTarget;
  roles = builtins.sort (a: b: a < b)
    (builtins.attrNames (topologyTarget.roles or {{}}));
}}"""


def target_dims(target: str, project_root: str, use_cache: bool = True) -> Dict[str, Any]:
    """Per-target dimension table: {topology: {...}, config: {...}, roles: [...]}.

    Each dim entry: {"n": candidate count, "values": [candidate values]}.
    Cached per (project_root, target) so resolving many seeds re-computes once.
    """
    key = (os.path.abspath(project_root), target)
    if use_cache and key in _DIM_CACHE:
        return _DIM_CACHE[key]
    tgt = get_target(project_root, target)
    raw = eval_json(_counts_expr(tgt.topology_target, tgt.config_target))
    table = {
        "topology": raw["topology"],
        "config": raw["config"],
        "roles": raw["roles"],
    }
    if use_cache:
        _DIM_CACHE[key] = table
    return table


def prime_dims(target: str, project_root: str, table: Dict[str, Any]) -> Dict[str, Any]:
    """Inject a dimension table into the per-target cache (test seam; also
    lets callers avoid re-probing a target they already measured)."""
    _DIM_CACHE[(os.path.abspath(project_root), target)] = table
    return table


def space_size_of(table: Dict[str, Any]) -> int:
    """Product of candidate-list lengths across ALL fuzzable dims.

    Topology is drawn once (fuzzer seed = master seed); each role draws its
    own config (fuzzer seed = master + 1 + roleIndex), so the per-role config
    product is raised to the number of roles.
    """
    topo = int(math.prod(int(d["n"]) for d in table["topology"].values()))
    conf = int(math.prod(int(d["n"]) for d in table["config"].values()))
    n_roles = max(1, len(table["roles"]))
    return topo * conf**n_roles


def dim_counts_of(table: Dict[str, Any]) -> Dict[str, int]:
    """Flat {path: n} across topology + config paths (config counted once:
    all roles share the same configTarget and therefore the same candidates)."""
    counts = {path: int(d["n"]) for path, d in table["topology"].items()}
    counts.update({path: int(d["n"]) for path, d in table["config"].items()})
    return counts


def qualified_dims(table: Dict[str, Any]) -> Dict[str, Any]:
    """Role-qualified dimension table used for marginals/pairwise:
    {"topology:<path>": entry, "<role>:<path>": entry}."""
    dims: Dict[str, Any] = {f"topology:{path}": entry for path, entry in table["topology"].items()}
    for role in table["roles"]:
        for path, entry in table["config"].items():
            dims[f"{role}:{path}"] = entry
    return dims


def _resolved_dims(record: Dict[str, Any]) -> Dict[str, Any]:
    """Role-qualified {dimension: resolved value} for one per-seed record."""
    dims: Dict[str, Any] = {}
    for path in sorted(record["topology_choices"]):
        dims[f"topology:{path}"] = value_at(record["topology"], path)
    for role in sorted(record["config_choices"]):
        for path in sorted(record["config_choices"][role]):
            dims[f"{role}:{path}"] = value_at(record["config"][role], path)
    return dims


# ---------------------------------------------------------------------------
# resolve_seed
# ---------------------------------------------------------------------------


def resolve_seed(target: str, seed: int, project_root: str) -> Dict[str, Any]:
    """Resolve the full per-seed configuration (topology AND per-role config).

    One pure nix eval of generate_inspect_expr (the expression the orchestrator
    evaluates for every real run's resolved.json): fuzzer over topology.nix
    with seed str(master); fuzzer over config.nix per role with seed
    str(master + 1 + roleIndex), roles alphabetical (lib/orchestrate.nix).
    """
    tgt = get_target(project_root, target)
    resolved = eval_json(
        generate_inspect_expr(seed, tgt.topology_target, tgt.config_target, project_root)
    )
    role_fuzz = resolved["roleFuzz"]
    roles = sorted(role_fuzz)
    table = target_dims(target, project_root)
    return {
        "seed": seed,
        "topology": resolved["topology"],
        "topology_choices": resolved["topologyChoices"],
        "config": {role: role_fuzz[role]["result"] for role in roles},
        "config_choices": {role: role_fuzz[role]["choices"] for role in roles},
        "space_size": space_size_of(table),
        "dim_counts": dim_counts_of(table),
    }


# ---------------------------------------------------------------------------
# Pure statistics (unit-tested without nix)
# ---------------------------------------------------------------------------


def marginals_rows(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tally resolved values per dimension over the per-seed records.

    Returns rows [{"dimension": ..., "resolved_value": <canonical str>,
    "count": int}, ...] sorted by (dimension, value).
    """
    tally: Dict[Tuple[str, str], int] = {}
    for record in records:
        for dim, value in _resolved_dims(record).items():
            key = (dim, canonical_json(value))
            tally[key] = tally.get(key, 0) + 1
    return [
        {"dimension": dim, "resolved_value": value, "count": count}
        for (dim, value), count in sorted(tally.items())
    ]


def pairwise_coverage(records: Iterable[Dict[str, Any]], dims: Dict[str, Any]) -> Dict[str, Any]:
    """Pairwise (dimension, value) co-occurrence coverage.

    A "pair" = (dimension, value) pair of two distinct dimensions co-occurring
    in one resolved config. pairs_total = sum over unordered dimension pairs of
    product of candidate counts (dedup symmetric); uncovered_sample lists up to
    20 uncovered combos, sorted deterministically.
    """
    names = sorted(dims)
    total = 0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            total += int(dims[names[i]]["n"]) * int(dims[names[j]]["n"])

    covered = set()
    for record in records:
        values = {dim: canonical_json(v) for dim, v in _resolved_dims(record).items()}
        rnames = sorted(values)
        for i in range(len(rnames)):
            for j in range(i + 1, len(rnames)):
                covered.add((rnames[i], values[rnames[i]], rnames[j], values[rnames[j]]))

    covered_count = 0
    uncovered: List[Tuple[str, str, str, str]] = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            for val_a in dims[a]["values"]:
                sa = canonical_json(val_a)
                for val_b in dims[b]["values"]:
                    sb = canonical_json(val_b)
                    if (a, sa, b, sb) in covered:
                        covered_count += 1
                    elif len(uncovered) < 20:
                        uncovered.append((a, sa, b, sb))
    uncovered.sort()
    covered_ratio = (covered_count / total) if total else 0.0
    return {
        "pairs_total": total,
        "pairs_covered": covered_count,
        "coverage": fmt6(covered_ratio),
        "uncovered_sample": [
            {"dim_a": a, "val_a": sa, "dim_b": b, "val_b": sb} for (a, sa, b, sb) in uncovered
        ],
    }


def uniqueness_summary(
    target: str, space_size: int, records: Iterable[Dict[str, Any]]
) -> Dict[str, Any]:
    """Uniqueness statistics over per-seed records."""
    records = list(records)
    n = len(records)
    unique = len({resolved_hash(r) for r in records})
    dup_rate = ((n - unique) / n) if n else 0.0
    return {
        "target": target,
        "space_size": space_size,
        "seeds": n,
        "unique_resolved": unique,
        "duplicate_rate": fmt6(dup_rate),
        "collisions": collision_groups(records),
    }


# ---------------------------------------------------------------------------
# Artifact files
# ---------------------------------------------------------------------------


def target_dir(out_dir: Any, target: str) -> str:
    return os.path.join(str(out_dir), "resolution", target)


def per_seed_path(out_dir: Any, target: str) -> str:
    return os.path.join(target_dir(out_dir, target), "per-seed-choices.jsonl")


def _read_seed_records(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    records = []
    for raw in _complete_lines(text):
        line = raw.strip()
        if line:
            records.append(json.loads(line))
    return records


def _complete_lines(text: str) -> List[str]:
    """Newline-terminated lines only: a final line without its newline is a
    write torn by a crash and is dropped (append_seed_line rewrites it)."""
    lines = text.splitlines(True)
    if lines and not lines[-1].endswith("\n"):
        lines.pop()
    return lines


def recorded_seeds(path: str) -> set:
    return {int(r["seed"]) for r in _read_seed_records(path)}


def append_seed_line(path: str, record: Dict[str, Any]) -> bool:
    """Append the canonical line for `record` unless its seed is present.

    Returns True if a line was appended (idempotent re-runs skip).
    """
    line = seed_line(record) + "\n"
    existing = ""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            existing = fh.read()
    complete = _complete_lines(existing)
    seed = int(record["seed"])
    if any(int(json.loads(c)["seed"]) == seed for c in complete if c.strip()):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    kept = "".join(complete)
    if len(kept) != len(existing):
        # Drop a torn final line before appending after it.
        atomic_write_text(path, kept)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)
    return True


def _write_json(path: str, payload: Dict[str, Any]) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_write_json(path, payload)
    return path


def _write_marginals(path: str, rows: List[Dict[str, Any]]) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["dimension", "resolved_value", "count"])
    for row in rows:
        writer.writerow([row["dimension"], row["resolved_value"], row["count"]])
    atomic_write_text(path, buf.getvalue())
    return path


def build_resolution_artifacts(
    out_dir: Any, project_root: str, targets: List[str], seeds: List[int]
) -> Dict[str, Any]:
    """Build uniqueness/marginals/pairwise artifacts per target.

    Reads per-seed-choices.jsonl; resolves any requested-but-missing seeds
    (one pure nix eval each) and appends them first. Pure statistics after.
    """
    artifacts: List[str] = []
    summary: Dict[str, Dict[str, Any]] = {}
    for target in targets:
        tdir = target_dir(out_dir, target)
        jsonl = per_seed_path(out_dir, target)
        have = recorded_seeds(jsonl)
        table = target_dims(target, project_root)
        space = space_size_of(table)
        dims = qualified_dims(table)
        for seed in seeds:
            if seed in have:
                continue
            record = resolve_seed(target, seed, project_root)
            append_seed_line(jsonl, record)
            have.add(seed)
        records = _read_seed_records(jsonl)
        summary[target] = {
            "space_size": space,
            "unique_resolved": uniqueness_summary(target, space, records)["unique_resolved"],
        }
        artifacts.append(
            _write_json(
                os.path.join(tdir, "uniqueness.json"), uniqueness_summary(target, space, records)
            )
        )
        artifacts.append(
            _write_marginals(os.path.join(tdir, "marginals.csv"), marginals_rows(records))
        )
        artifacts.append(
            _write_json(
                os.path.join(tdir, "pairwise-coverage.json"), pairwise_coverage(records, dims)
            )
        )
    return {"targets": summary, "artifacts": artifacts}


def collect_existing(out_dir: Any) -> Dict[str, Any]:
    """Read back resolution/<target>/* for analyze.py/execution-accounting.

    Pure: no subprocesses. Missing targets/files are simply absent.
    """
    root = os.path.join(str(out_dir), "resolution")
    result: Dict[str, Any] = {"targets": {}}
    if not os.path.isdir(root):
        return result
    for target in sorted(os.listdir(root)):
        tdir = os.path.join(root, target)
        if not os.path.isdir(tdir):
            continue
        entry: Dict[str, Any] = {}
        uniqueness_path = os.path.join(tdir, "uniqueness.json")
        if os.path.exists(uniqueness_path):
            with open(uniqueness_path, "r", encoding="utf-8") as fh:
                entry["uniqueness"] = json.load(fh)
        marginals_path = os.path.join(tdir, "marginals.csv")
        if os.path.exists(marginals_path):
            rows = []
            with open(marginals_path, "r", encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    rows.append(
                        {
                            "dimension": row["dimension"],
                            "resolved_value": row["resolved_value"],
                            "count": int(row["count"]),
                        }
                    )
            entry["marginals_rows"] = rows
        pairwise_path = os.path.join(tdir, "pairwise-coverage.json")
        if os.path.exists(pairwise_path):
            with open(pairwise_path, "r", encoding="utf-8") as fh:
                entry["pairwise"] = json.load(fh)
        result["targets"][target] = entry
    return result


# ---------------------------------------------------------------------------
# CLI-facing wrapper (used by __main__.py)
# ---------------------------------------------------------------------------


def run_fuzz_units(out_dir: Any, project_root: str, units: Iterable[Unit]) -> Dict[str, Any]:
    """Execute the fuzz_only units: resolve each seed purely, append the
    per-seed line to per-seed-choices.jsonl (deterministic; already-resolved
    seeds are skipped based on the jsonl contents, never re-evaluated), then
    build the per-target statistics.

    Writes a per-target status side file {"state": "done", "seeds": [...]} at
    the end for consumers.
    """
    by_target: Dict[str, List[int]] = {}
    for unit in units:
        if unit.kind != "fuzz_only" or unit.target is None or unit.seed is None:
            continue
        seeds = by_target.setdefault(unit.target, [])
        if unit.seed not in seeds:
            seeds.append(unit.seed)

    artifacts: List[str] = []
    summary: Dict[str, Dict[str, Any]] = {}
    for target in sorted(by_target):
        requested = sorted(by_target[target])
        jsonl = per_seed_path(out_dir, target)
        status_path = os.path.join(target_dir(out_dir, target), "status.json")
        have = recorded_seeds(jsonl)
        for index, seed in enumerate(requested, start=1):
            if seed in have:
                continue
            record = resolve_seed(target, seed, project_root)
            append_seed_line(jsonl, record)
            print(f"[resolve] {target} seed {seed} ({index}/{len(requested)})", file=sys.stderr)
        recorded = sorted(recorded_seeds(jsonl))
        built = build_resolution_artifacts(out_dir, project_root, [target], recorded)
        artifacts.extend(built["artifacts"])
        summary[target] = built["targets"][target]
        _write_json(status_path, {"state": "done", "seeds": recorded})
    return {"targets": summary, "artifacts": artifacts}
