"""report.py — deterministic rendering of the verification deliverables.

write_verification_report(out_dir, summary): builds
verification/VERIFICATION_REPORT.md with
  1. headline verdict counts,
  2. one section per claim group with that group's claim rows,
  3. an "Execution accounting" section rendering analysis/execution-accounting
     plus resolution/*/uniqueness.json as the tables the thesis is missing,
  4. a "Discrepancies" section listing every non-match row with the artifact
     path and a factual note (no speculation about cause),
  5. a determinism section (flip counts; non-zero flips are a headline finding).

write_readme(out_dir, manifest_path): README.md — how to re-run, what each
artifact/directory contains, verdict semantics.

Both outputs are deterministic and provenance-free: sorted keys, no
timestamps (the lock file owns provenance).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from experiments.reproduce.verify import INFO, MATCH, MISMATCH, MISSING, WITHIN

GROUPS = [
    ("Kafka", "k-"),
    ("etcd v1", "e1-"),
    ("etcd v2", "e2-"),
    ("RabbitMQ", "r-"),
    ("Config spaces", "c-"),
    ("Test suites", "t-"),
    ("Discussion / informational", "m-"),
]

COUNT_KEYS = (MATCH, WITHIN, MISMATCH, MISSING, INFO)


def load_matrix_rows(out_dir: Path) -> List[Dict[str, str]]:
    """Claim rows read back from verification/claims-matrix.csv.

    Lets `--phase report` render the real report on its own: the verify
    phase's in-memory summary is only available when verify ran in the same
    invocation, and rendering a hardcoded all-zero summary instead silently
    overwrote a good report with 'total 0'."""
    path = Path(out_dir) / "verification" / "claims-matrix.csv"
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    except OSError:
        return []


def _read_json(path: Path) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _table(header: List[str], rows: List[List[Any]]) -> List[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        out.append("| " + " | ".join(_csv_cell(v) for v in row) + " |")
    return out


def _group_of(claim_id: str) -> Optional[str]:
    for title, prefix in GROUPS:
        if claim_id.startswith(prefix):
            return title
    return None


def _resolve_uniqueness(out_dir: Path) -> List[Dict[str, Any]]:
    res_dir = out_dir / "resolution"
    blocks = []
    if res_dir.is_dir():
        for target in sorted(p.name for p in res_dir.iterdir() if p.is_dir()):
            uniq = _read_json(res_dir / target / "uniqueness.json")
            if isinstance(uniq, dict):
                blocks.append(uniq)
    return blocks


def _accounting_lines(out_dir: Path) -> List[str]:
    lines = ["## Execution accounting", ""]
    acc = _read_json(out_dir / "analysis" / "execution-accounting.json")
    if not isinstance(acc, dict):
        lines += ["`analysis/execution-accounting.json` missing; no accounting data.", ""]
        return lines
    header = [
        "Group",
        "Units",
        "Seeds",
        "Fresh",
        "Cache replay",
        "Wall total (s)",
        "Compute hours",
        "Peak RSS (MiB)",
        "Space size",
    ]
    rows = []
    for name, g in sorted((acc.get("groups") or {}).items()):
        rss = g.get("peak_rss_max_bytes")
        rss_mib = (float(rss) / 1048576.0) if rss is not None else None
        rows.append(
            [
                name,
                g.get("units"),
                g.get("seeds"),
                g.get("fresh"),
                g.get("cache_replay"),
                g.get("wall_total_s"),
                g.get("compute_hours"),
                f"{rss_mib:.1f}" if rss_mib is not None else "",
                g.get("space_size"),
            ]
        )
    lines += _table(header, rows)
    lines.append("")
    totals = acc.get("totals")
    if isinstance(totals, dict):
        lines += _table(
            ["Totals", "Units", "Fresh", "Cache replay", "Wall total (s)", "Compute hours"],
            [
                [
                    "all groups",
                    totals.get("units"),
                    totals.get("fresh"),
                    totals.get("cache_replay"),
                    totals.get("wall_total_s"),
                    totals.get("compute_hours"),
                ]
            ],
        )
        lines.append("")
    uniq_rows = [
        [
            u.get("target"),
            u.get("space_size"),
            u.get("seeds"),
            u.get("unique_resolved"),
            u.get("duplicate_rate"),
        ]
        for u in _resolve_uniqueness(out_dir)
    ]
    if uniq_rows:
        lines += _table(
            ["Resolution target", "Space size", "Seeds", "Unique resolved", "Duplicate rate"],
            uniq_rows,
        )
        lines.append("")
    return lines


def _determinism_lines(out_dir: Path) -> List[str]:
    lines = ["## Determinism (per-seed flips across repetitions)", ""]
    det = _read_json(out_dir / "analysis" / "determinism.json")
    if not isinstance(det, dict):
        lines += ["`analysis/determinism.json` missing; no flip data.", ""]
        return lines
    rows = []
    non_zero = []
    for name in sorted(det):
        entry = det[name] or {}
        flips = entry.get("flips")
        rows.append([name, entry.get("present"), flips if flips is not None else "n/a"])
        if isinstance(flips, int) and flips > 0:
            non_zero.append(f"{name}: {flips}")
    lines += _table(["Entry", "Repetitions present", "Flips"], rows)
    lines.append("")
    if non_zero:
        lines += [
            f"**Headline finding:** non-zero per-seed flips — {', '.join(non_zero)}.",
            "",
        ]
    return lines


def _discrepancy_note(row: Dict[str, Any]) -> str:
    if row["verdict"] == MISSING:
        return (
            f"not reproduced: {row['reason']}"
            if row.get("reason")
            else "analysis artifact/data absent"
        )
    if row["verdict"] == MISMATCH:
        return "observed value differs from the claim's expected value" + (
            f" ({row['reason']})" if row.get("reason") else ""
        )
    return row.get("reason") or ""


def write_verification_report(out_dir: Path, summary: Dict[str, Any]) -> None:
    out_dir = Path(out_dir)
    rows = summary.get("rows") or load_matrix_rows(out_dir)
    # Count the rows themselves rather than trusting summary keys: the
    # summary names verdicts with its own key spelling ("not-reproduced",
    # "informational"), which silently disagreed with the verdict constants
    # used here and pinned the informational row to 0.
    counts = {k: 0 for k in COUNT_KEYS}
    for row in rows:
        verdict = row.get("verdict")
        if verdict in counts:
            counts[verdict] += 1
    total = len(rows)
    lines: List[str] = ["# Verification report", ""]
    lines += ["## Headline counts", ""]
    lines += _table(["Verdict", "Count"], [[k, counts[k]] for k in COUNT_KEYS] + [["total", total]])
    lines.append("")
    for title, prefix in GROUPS:
        group_rows = [r for r in rows if r.get("claim_id", "").startswith(prefix)]
        if not group_rows:
            continue
        lines.append(f"## {title} claims")
        lines.append("")
        lines += _table(
            ["Claim", "Expected", "Observed", "Verdict"],
            [
                [r["claim_id"], r["expected"], r["observed"], r["verdict"]]
                for r in sorted(group_rows, key=lambda r: r["claim_id"])
            ],
        )
        lines.append("")
    lines += _accounting_lines(out_dir)
    lines.append("## Discrepancies")
    lines.append("")
    non_match = [
        r
        for r in sorted(rows, key=lambda r: r["claim_id"])
        if r["verdict"] not in (MATCH, WITHIN, INFO)
    ]
    if not non_match:
        lines.append("None.")
        lines.append("")
    else:
        for r in non_match:
            artifact = r.get("artifact") or "(no artifact)"
            note = _discrepancy_note(r)
            lines.append(
                f"- `{r['claim_id']}` [{r['verdict']}] — {note} " f"(artifact: {artifact})"
            )
        lines.append("")
    lines += _determinism_lines(out_dir)
    vdir = out_dir / "verification"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "VERIFICATION_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


README = """# Thesis evaluation reproduction — output directory

Re-run everything from the repo root (branch `thesis-eval-repro`):

    nix develop -c python3 -m experiments.reproduce \\
        --manifest {manifest} --out {out} --phase all

Phases (pass individually with `--phase <name>`):

  - `run`      — execute every manifest unit (nix build + VM); resumable via
                 `raw/<unit-id>/status.json`; `--jobs K` bounds concurrency,
                 `--force` re-runs done units, `--only <entry>` limits scope.
  - `digest`   — (re)write `raw/<unit-id>/log-digest.json` from the unit logs.
                 Runs automatically at the end of `run`; run it on its own
                 after any out-of-band run so the committed tree keeps the
                 log-derived evidence.
  - `analyze`  — rebuild `analysis/` from `raw/` + `resolution/` (pure).
  - `verify`   — score `study/repro-discovery/claims.csv` against `analysis/`
                 and write `verification/claims-matrix.csv` (pure).
  - `report`   — write `verification/VERIFICATION_REPORT.md` + this README.

`--dry-run` prints unit counts, wall-clock/compute estimates, and a `--jobs`
recommendation without executing anything. See
`python3 -m experiments.reproduce --help` for the authoritative flag list.

## Directory contents

  - `MANIFEST.lock.json` — pinned revs, host, extraction source (provenance),
    and `campaign_token`: the fresh-execution token threaded into every unit's
    `--repetition-token`. Re-running `--phase all` against this dir reuses it
    (idempotent). A new `--out` dir, or `--fresh-token`, mints a new token so
    every unit re-executes as a genuine VM run instead of a Nix cache replay.
  - `raw/<unit-id>/`     — one directory per planned unit: status.json,
    run.json, choices.json, resolved.json, report.json, timing.json,
    resources.json, nix-build.json, stdout/stderr logs, evidence payloads,
    and log-digest.json — a bounded projection of the logs (which are
    gitignored: ~340 MB/campaign) carrying every line analysis parses, so
    analysis is identical whether the *.log files are present or not.
  - `resolution/<target>/` — pure per-seed resolution statistics:
    per-seed-choices.jsonl, uniqueness.json, marginals.csv,
    pairwise-coverage.json.
  - `analysis/`          — deterministic artifacts written by analyze.py:
    kafka-sweep(.json/.csv), kafka-crosstab.csv, kafka-shrink.json,
    kafka-min-configs.json, etcd-v1-sweep.json, etcd-v2-sweep.json,
    etcd-v2-quota-correlation.csv, etcd-v2-shrink.json,
    etcd-v2-exhaustive(.json/.csv), rabbitmq-{disk,faildom,crash}-cells.csv,
    determinism.json, test-suites.json, stage-timing.json, parallelism.json,
    execution-accounting(.json/.csv).
  - `verification/`      — claims-matrix.csv (one row per thesis claim) and
    VERIFICATION_REPORT.md (human-readable summary).

## Verdict semantics (verification/claims-matrix.csv)

  - `match`                  — artifact present; observed equals expected.
  - `within-tolerance`       — observed inside the range the claim text allows
    (e.g. "22 or 23 recovered", "approx 104.5 MB" accepted as 100-110).
  - `mismatch`               — artifact present; observed contradicts the claim.
  - `not-reproduced`         — artifact or data row absent; the `reason` column
    says which. Never treated as a pass.
  - `informational-observed` — informational/timing claim; the observed value
    is reported but never scored as mismatch.

Analysis and verification are pure functions of `raw/` + `resolution/`:
re-running them re-executes zero VM runs and must produce byte-identical
outputs (no timestamps; the lock file owns provenance). That holds for a
fresh clone too, where the gitignored `*.log` files are absent and
`log-digest.json` is the source for everything derived from them.

`stage-timing.json` reports only stages the VM driver itself timed
(`vm_boot_s`, `test_script_s`); `nix_eval_s`/`build_s` are null because the
nix build log carries no per-line timestamps. `parallelism.json` compares
group wall-clock spans (max end - min start), never sums of per-unit wall
times — concurrency does not shrink such a sum.
"""


def write_readme(out_dir: Path, manifest_path: str) -> None:
    out_dir = Path(out_dir)
    text = README.replace("{manifest}", manifest_path).replace("{out}", str(out_dir))
    (out_dir / "README.md").write_text(text, encoding="utf-8")
