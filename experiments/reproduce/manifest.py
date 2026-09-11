"""Manifest loading, validation, and unit expansion.

Thin layer over models.py: adds consistency validation and the analysis
ordering used by __main__ to schedule phases.
"""

from __future__ import annotations

from typing import List

from experiments.reproduce.models import (
    KINDS,
    PRODUCES_KNOWN,
    Manifest,
    Unit,
    expand_units,
    load_manifest,
)


def load_and_validate(path: str) -> Manifest:
    manifest = load_manifest(path)
    seen_ids = set()
    for entry in manifest.entries:
        if entry.id in seen_ids:
            raise ValueError(f"duplicate manifest entry id {entry.id!r}")
        seen_ids.add(entry.id)
        if entry.kind not in KINDS:
            raise ValueError(f"entry {entry.id!r}: unknown kind {entry.kind!r}")
        if entry.kind != "test_suites" and not entry.target:
            raise ValueError(f"entry {entry.id!r}: missing target")
        for p in entry.produces:
            if p not in PRODUCES_KNOWN:
                raise ValueError(f"entry {entry.id!r}: unknown produces id {p!r}")
        if entry.kind in ("sweep", "fuzz_only") and not entry.seeds:
            raise ValueError(f"entry {entry.id!r}: sweep/fuzz_only needs seeds")
        if entry.kind == "exhaustive" and not entry.exhaustive_dims:
            raise ValueError(f"entry {entry.id!r}: exhaustive needs dims")
        if entry.kind == "run" and not entry.variants and entry.choices is None and not entry.seeds:
            raise ValueError(f"entry {entry.id!r}: run needs variants or choices+seeds")
    return manifest


def expand_all(manifest: Manifest, framework_rev: str) -> List[Unit]:
    """Validated expansion; raises on unit-id collisions."""
    return expand_units(manifest, framework_rev)


def analysis_order() -> List[str]:
    """Deterministic analysis execution order (dependencies first)."""
    return [
        "resolution",
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
        "test-suites",
        "stage-timing",
        "parallelism",
        "execution-accounting",
    ]
