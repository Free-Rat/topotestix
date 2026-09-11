"""verify.py — claim-by-claim verification against analysis artifacts.

Reads the extracted thesis claims (claims.csv), routes each claim to the
analysis artifact written by analyze.py that can confirm or refute it,
computes an observed value, and emits one row per claim into
verification/claims-matrix.csv plus a machine-readable summary dict.

Verdict semantics:
  match                   artifact present, observed == expected (exact)
  within-tolerance        observed inside the range the claim text allows
  mismatch                artifact present, observed contradicts the claim
  not-reproduced          artifact or data row absent (reason says which)
  informational-observed  informational/timing claim; observed reported only

Determinism: rows sorted by claim_id, LF newlines, no timestamps anywhere;
run() is a pure function of (analysis artifacts, claims.csv).

Module contract (frozen in models.py): verify.run(out_dir, collected, ...) —
`collected` is accepted for the shared call signature but not used: every
comparison is against the already-written analysis/ artifacts.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from experiments.reproduce.models import atomic_write_text

MATRIX_HEADER = [
    "claim_id",
    "location",
    "expected",
    "observed",
    "verdict",
    "artifact",
    "reason",
]
MATCH = "match"
WITHIN = "within-tolerance"
MISMATCH = "mismatch"
MISSING = "not-reproduced"
INFO = "informational-observed"

KAFKA_BROKER_MAX = "broker-message-max-too-small"
KAFKA_LOG_SEGMENT = "log-segment-too-small"
ETCD_V1_CLASS = "invalid-etcd-election-timeout-heartbeat-ratio"
ETCD_V2_CLASS = "quota-backend-too-small-for-write-burst"
KAFKA_CHECK = "kafka-large-message-on-kafka1"
ETCD_V2_CHECK = "etcd-quota-write-burst-etcd1"
RMQ_CONTRACT = "rabbitmq-disk-capacity-confirmation-contract"


@dataclass
class Claim:
    claim_id: str
    location: str
    statement: str
    expected_value: str
    tolerance: str


# claims.csv (0b extraction) is not RFC-4180-clean: statements/expected values
# may contain UNQUOTED commas (e.g. the crosstab cell specs, the seed lists),
# so a plain DictReader truncates those fields. Repair rule: claim_id and
# location never contain commas; tolerance is always the final field; the
# statement/expected boundary is recovered by joining middle fields until the
# expected candidate matches one of the value shapes used in the file.
_EXPECTED_SHAPES = (
    re.compile(r"^\d+(/\d+)*$"),
    re.compile(r"^seeds \d+(,\d+)*$"),
    re.compile(r"^seed \d+$"),
    re.compile(r"^\d+/\d+ .+"),
)
_TOLERANCES = ("exact", "range", "timing", "informational")


def _claim_from_fields(fields: List[str], lineno: int) -> Claim:
    if len(fields) < 5:
        raise ValueError(f"claims.csv line {lineno}: expected 5 fields, got {fields}")
    if len(fields) == 5:
        statement, expected = fields[2], fields[3]
    else:
        middle = fields[2:-1]
        statement, expected = middle[0], middle[-1]
        for i in range(len(middle) - 1):
            cand_stmt = ",".join(middle[: i + 1])
            cand_exp = ",".join(middle[i + 1 :])
            if any(p.match(cand_exp) for p in _EXPECTED_SHAPES):
                statement, expected = cand_stmt, cand_exp
                break
    if fields[-1].strip() not in _TOLERANCES:
        raise ValueError(f"claims.csv line {lineno}: bad tolerance {fields[-1]!r}")
    return Claim(
        claim_id=fields[0].strip(),
        location=fields[1].strip(),
        statement=statement.strip(),
        expected_value=expected.strip(),
        tolerance=fields[-1].strip(),
    )


def load_claims(path: str) -> List[Claim]:
    claims: List[Claim] = []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        if [h.strip() for h in header[:2]] != ["claim_id", "location"]:
            raise ValueError(f"claims.csv: unexpected header {header}")
        for lineno, fields in enumerate(reader, start=2):
            if not fields or not fields[0].strip():
                continue
            claims.append(_claim_from_fields(fields, lineno))
    return claims


class _Absent(Exception):
    def __init__(self, artifact: str) -> None:
        super().__init__(artifact)
        self.artifact = artifact


class _Ctx:
    """Lazy caches over <out>/analysis/; raises _Absent for missing files."""

    def __init__(self, out_dir: Path) -> None:
        self.analysis = Path(out_dir) / "analysis"
        self._json: Dict[str, Any] = {}
        self._csv: Dict[str, Any] = {}

    def json_data(self, name: str) -> Dict[str, Any]:
        if name not in self._json:
            path = self.analysis / f"{name}.json"
            data = None
            if path.is_file():
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        loaded = json.load(fh)
                except (OSError, ValueError):
                    loaded = None
                # tolerate both raw analyze.py output and wrapped forms
                if isinstance(loaded, dict) and set(loaded) == {"artifact", "data"}:
                    loaded = loaded.get("data")
                data = loaded if isinstance(loaded, dict) else None
            self._json[name] = data
        data = self._json[name]
        if data is None:
            raise _Absent(f"analysis/{name}.json")
        return data

    def csv_rows(self, name: str) -> List[Dict[str, str]]:
        if name not in self._csv:
            path = self.analysis / f"{name}.csv"
            rows = None
            if path.is_file():
                try:
                    with open(path, "r", encoding="utf-8", newline="") as fh:
                        rows = [dict(r) for r in csv.DictReader(fh)]
                except OSError:
                    rows = None
            self._csv[name] = rows
        rows = self._csv[name]
        if rows is None:
            raise _Absent(f"analysis/{name}.csv")
        return rows


# --- parsing helpers ----------------------------------------------------------

_INT_RE = re.compile(r"\d+")


def _ints(text: str) -> List[int]:
    return [int(m) for m in _INT_RE.findall(text)]


def _triple(text: str) -> Optional[Tuple[int, int, int]]:
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*/\s*(\d+)", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _mib(value: Any) -> Optional[int]:
    m = re.match(r"(\d+)", str(value or "").strip())
    return int(m.group(1)) if m else None


def _gi(row: Dict[str, str], key: str) -> Optional[int]:
    v = (row.get(key) or "").strip()
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _gs(row: Dict[str, str], key: str) -> str:
    return (row.get(key) or "").strip()


def _gb(row: Dict[str, str], key: str) -> Optional[bool]:
    v = _gs(row, key).lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    return None


def _exec_index(row: Dict[str, str]) -> int:
    v = _gi(row, "execution_index")
    return 0 if v is None else v


def _rows_for(rows: List[Dict[str, str]], variant: str) -> List[Dict[str, str]]:
    return [r for r in rows if _gs(r, "variant") == variant]


def _row_at(
    rows: List[Dict[str, str]], variant: str, exec_index: int, label: str
) -> Tuple[Optional[Dict[str, str]], str]:
    sel = [r for r in rows if _gs(r, "variant") == variant and _exec_index(r) == exec_index]
    if not sel:
        return None, f"no {label} row variant={variant} execution_index={exec_index}"
    return sel[0], ""


def _seeds_run(data: Dict[str, Any]) -> int:
    per = data.get("per_seed")
    return len(per) if isinstance(per, list) else int(data.get("seeds_run") or 0)


def _seed_row(data: Dict[str, Any], seed: int) -> Optional[Dict[str, Any]]:
    for r in data.get("per_seed", []) or []:
        if r.get("seed") == seed:
            return r
    return None


def _final_config_equal(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


HandlerResult = Tuple[str, str, str]  # (verdict, observed, reason)
Handler = Callable[[Claim, _Ctx], HandlerResult]


# --- kafka-sweep handlers -----------------------------------------------------


def _h_k01(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("kafka-sweep")
    p, f = d.get("passed"), d.get("failed")
    observed = f"{p} pass / {f} fail of {_seeds_run(d)} seeds"
    ok = p == 13 and f == 37 and _seeds_run(d) == 50
    return (MATCH if ok else MISMATCH, observed, "")


def _h_k02(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("kafka-sweep")
    failing = [r for r in d.get("per_seed", []) or [] if r.get("status") == "failed"]
    off = [r for r in failing if list(r.get("failed_checks") or []) != [KAFKA_CHECK]]
    observed = (
        f"{len(failing) - len(off)} of {len(failing)} failing seeds failed only {KAFKA_CHECK}"
    )
    ok = len(failing) == 37 and not off
    return (MATCH if ok else MISMATCH, observed, "")


def _h_k03(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("kafka-sweep")
    classes = d.get("failure_classes") or {}
    broker, log = classes.get(KAFKA_BROKER_MAX), classes.get(KAFKA_LOG_SEGMENT)
    observed = (
        f"{KAFKA_BROKER_MAX}: {broker} (RecordTooLargeException); "
        f"{KAFKA_LOG_SEGMENT}: {log} (RecordBatchTooLargeException); "
        f"Pass: {d.get('passed')}"
    )
    ok = broker == 18 and log == 19 and d.get("passed") == 13
    return (MATCH if ok else MISMATCH, observed, "")


def _seed_class_handler(seed: int, expected_class: str) -> Handler:
    def handler(claim: Claim, ctx: _Ctx) -> HandlerResult:
        d = ctx.json_data("kafka-sweep")
        row = _seed_row(d, seed)
        if row is None:
            return MISSING, "", f"seed {seed} absent from kafka-sweep per_seed"
        cls = row.get("failure_class")
        observed = f"seed {seed}: status={row.get('status')}, failure_class={cls}"
        return (MATCH if cls == expected_class else MISMATCH, observed, "")

    return handler


def _h_k31(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("kafka-sweep")
    classes = d.get("failure_classes") or {}
    observed = (
        f"{d.get('passed')}/{d.get('failed')} of {_seeds_run(d)} seeds; "
        f"failure classes: {sorted(classes)}"
    )
    ok = (
        d.get("failed") == 37
        and d.get("passed") == 13
        and KAFKA_BROKER_MAX in classes
        and KAFKA_LOG_SEGMENT in classes
    )
    return (MATCH if ok else MISMATCH, observed, "")


# --- kafka-crosstab handlers --------------------------------------------------

_CELL_RE = re.compile(
    r"\((?:message\.max\.bytes=)?(\d+)MiB,(?:replica\.fetch\.max\.bytes=)?(\d+)MiB,"
    r"(?:log\.segment\.bytes=)?(\d+)MiB\)"
)


def _crosstab_cell(claim: Claim, ctx: _Ctx) -> HandlerResult:
    m = _CELL_RE.search(claim.statement)
    if not m:
        return MISSING, "", "cannot parse crosstab cell key from claim statement"
    key = tuple(int(g) for g in m.groups())
    rows = ctx.csv_rows("kafka-crosstab")
    for r in rows:
        got_key = (
            _mib(r.get("message_max_bytes")),
            _mib(r.get("replica_fetch_max_bytes")),
            _mib(r.get("log_segment_bytes")),
        )
        if got_key == key:
            got = (_gi(r, "pass"), _gi(r, "broker_max"), _gi(r, "log_segment"))
            exp = _triple(claim.expected_value)
            label = f"{key[0]}MiB/{key[1]}MiB/{key[2]}MiB"
            observed = f"{got[0]}/{got[1]}/{got[2]} ({label})"
            return (MATCH if got == exp else MISMATCH, observed, "")
    return (
        MISSING,
        "",
        ("crosstab row %d/%d/%d MiB not present in artifact" % (key[0], key[1], key[2])),
    )


def _h_k22(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("kafka-crosstab")
    bad = []
    for r in rows:
        msg, bm = _mib(r.get("message_max_bytes")), _gi(r, "broker_max") or 0
        if (bm > 0) != (msg == 1):
            bad.append(_gs(r, "message_max_bytes"))
    observed = (
        "broker-max iff message.max.bytes=1MiB (all %d cells)" % len(rows)
        if not bad
        else f"{len(bad)} cells violate the biconditional"
    )
    return (MATCH if not bad else MISMATCH, observed, "")


def _h_k23(claim: Claim, ctx: _Ctx) -> HandlerResult:
    # Cells that already fail the broker-max check never reach the log-segment
    # check, so the biconditional is evaluated over the reachable cells only.
    rows = ctx.csv_rows("kafka-crosstab")
    bad = []
    for r in rows:
        if (_gi(r, "broker_max") or 0) > 0:
            continue
        seg, lg = _mib(r.get("log_segment_bytes")), _gi(r, "log_segment") or 0
        if (lg > 0) != (seg == 1):
            bad.append(f"{_gs(r, 'message_max_bytes')}/{_gs(r, 'log_segment_bytes')}")
    observed = (
        "log-segment iff log.segment.bytes=1MiB (cells reachable past " "broker-max)"
        if not bad
        else f"{len(bad)} reachable cells violate it"
    )
    return (MATCH if not bad else MISMATCH, observed, "")


# --- kafka-shrink / min-configs / accounting / determinism handlers -----------


def _h_k25(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("kafka-min-configs")
    v = (d.get("variants") or d).get("min-message-max", {})
    observed = (
        f"{v.get('passed')} pass / {v.get('failed')} fail (failed check: {v.get('failed_check')})"
    )
    ok = v.get("passed") == 10 and v.get("failed") == 1
    return (MATCH if ok else MISMATCH, observed, "")


def _h_k27(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("kafka-min-configs")
    v = (d.get("variants") or d).get("min-log-segment", {})
    observed = (
        f"{v.get('passed')} pass / {v.get('failed')} fail (failed check: {v.get('failed_check')})"
    )
    ok = v.get("passed") == 10 and v.get("failed") == 1
    return (MATCH if ok else MISMATCH, observed, "")


def _h_k28(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("kafka-shrink")
    s = (d.get("seeds") or {}).get("9", {})
    observed = (
        f"seed 9: original_class={s.get('original_class')}, "
        f"shrunk_status={s.get('shrunk_status')}, "
        f"class_preserved={s.get('class_preserved')}"
    )
    ok = s.get("class_preserved") is False and s.get("shrunk_status") == "failed"
    return (MATCH if ok else MISMATCH, observed, "")


def _h_k29(claim: Claim, ctx: _Ctx) -> HandlerResult:
    acc = ctx.json_data("execution-accounting")
    space = (acc.get("groups") or {}).get("kafka-cluster", {}).get("space_size")
    sampled = _seeds_run(ctx.json_data("kafka-sweep"))
    observed = f"{space} configurations of which {sampled} sampled"
    ok = space == 746496 and sampled == 50
    return (MATCH if ok else MISMATCH, observed, "")


def _h_k30(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("determinism")
    entry = d.get("kafka-sweep") or {}
    if entry.get("present") is not True:
        return MISSING, "", "kafka-sweep repetition pair not present in determinism.json"
    observed = (
        f"flips={entry.get('flips')} across kafka-sweep repetitions "
        f"(present={entry.get('present')})"
    )
    return (MATCH if entry.get("flips") == 0 else MISMATCH, observed, "")


# --- etcd handlers ------------------------------------------------------------


def _etcd_split_handler(artifact: str, exp_pass: int, exp_fail: int) -> Handler:
    def handler(claim: Claim, ctx: _Ctx) -> HandlerResult:
        d = ctx.json_data(artifact)
        observed = f"{d.get('passed')} pass / {d.get('failed')} fail of {_seeds_run(d)} seeds"
        ok = d.get("passed") == exp_pass and d.get("failed") == exp_fail
        return (MATCH if ok else MISMATCH, observed, "")

    return handler


def _failing_seeds_handler() -> Handler:
    def handler(claim: Claim, ctx: _Ctx) -> HandlerResult:
        name = "etcd-v1-sweep" if claim.claim_id.startswith("e1-") else "etcd-v2-sweep"
        d = ctx.json_data(name)
        got = sorted(int(s) for s in d.get("failing_seeds") or [])
        exp = _ints(claim.expected_value)
        observed = "failing seeds " + ",".join(str(s) for s in got)
        return (MATCH if got == exp else MISMATCH, observed, "")

    return handler


def _h_e1_03(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("etcd-v1-sweep")
    cls = d.get("failure_class")
    with_checks = [
        r.get("seed")
        for r in d.get("per_seed", []) or []
        if r.get("failure_class") and (r.get("failed_checks") or [])
    ]
    observed = f"failure_class={cls}; failing seeds with recorded checks: {with_checks}"
    ok = cls == ETCD_V1_CLASS and not with_checks
    return (MATCH if ok else MISMATCH, observed, "")


def _h_e1_04(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("etcd-v1-sweep")
    msg = d.get("sample_error_message") or ""
    # Real etcd startup error (June evidence): "failed to verify flags:
    # --election-timeout[1000ms] should be at least as 5 times as
    # --heartbeat-interval[250ms]" — match on the invariant phrasing.
    hit = re.search(r"election.timeout.*should be at least.*5.*heartbeat", msg, re.IGNORECASE)
    return (MATCH if hit else MISMATCH, msg, "")


def _h_e2_03(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("etcd-v2-sweep")
    failing = [r for r in d.get("per_seed", []) or [] if r.get("failure_class")]
    off = [r for r in failing if list(r.get("failed_checks") or []) != [ETCD_V2_CHECK]]
    observed = (
        f"failure_class={d.get('failure_class')}; "
        f"{len(failing) - len(off)}/{len(failing)} failing seeds failed only {ETCD_V2_CHECK}"
    )
    ok = d.get("failure_class") == ETCD_V2_CLASS and d.get("failed") == 13 and not off
    return (MATCH if ok else MISMATCH, observed, "")


def _h_e2_04(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("etcd-v2-sweep")
    msg = d.get("sample_error_message") or ""
    return (MATCH if "database space exceeded" in msg else MISMATCH, msg, "")


def _quota_cell_handler(quota: int) -> Handler:
    def handler(claim: Claim, ctx: _Ctx) -> HandlerResult:
        rows = ctx.csv_rows("etcd-v2-quota-correlation")
        row = next((r for r in rows if _gi(r, "quota_backend_bytes") == quota), None)
        if row is None:
            return MISSING, "", f"no quota_backend_bytes={quota} row in artifact"
        got = (_gi(row, "passed"), _gi(row, "failed"), _gi(row, "total"))
        exp = _triple(claim.expected_value)
        observed = f"{got[0]}/{got[1]}/{got[2]} (quota {quota})"
        return (MATCH if got == exp else MISMATCH, observed, "")

    return handler


def _h_e2_08(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("etcd-v2-quota-correlation")
    by_q = {(_gi(r, "quota_backend_bytes") or 0): r for r in rows}
    parts, ok = [], True
    for quota in (2097152, 8388608, 67108864):
        r = by_q.get(quota)
        if r is None:
            return MISSING, "", f"no quota_backend_bytes={quota} row in artifact"
        p, f, t = _gi(r, "passed"), _gi(r, "failed"), _gi(r, "total")
        parts.append(f"{quota // 1048576}MiB: {p}/{t} pass, {f}/{t} fail")
        if quota == 2097152:
            ok = ok and p == 0 and f == 13
        elif quota == 8388608:
            ok = ok and p == 20 and f == 0
        else:
            ok = ok and p == 17 and f == 0
    observed = "; ".join(parts)
    return (MATCH if ok else MISMATCH, observed, "")


def _h_e2_09(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("etcd-v2-sweep")
    failing = [
        r
        for r in d.get("per_seed", []) or []
        if r.get("status") == "failed" or r.get("failure_class")
    ]
    off = [r for r in failing if list(r.get("failed_checks") or []) != [ETCD_V2_CHECK]]
    # Claim asserts 11 of 12 checks pass in EVERY failing run: exactly one
    # failed check and no other lost checks.
    observed = (
        f"{len(failing) - len(off)}/{len(failing)} failing runs fail only "
        f"{ETCD_V2_CHECK} (11 of 12 checks passing)"
    )
    ok = len(failing) == 13 and not off
    return (MATCH if ok else MISMATCH, observed, "")


def _h_e2_10(claim: Claim, ctx: _Ctx) -> HandlerResult:
    acc = ctx.json_data("execution-accounting")
    space = (acc.get("groups") or {}).get("etcd-cluster", {}).get("space_size")
    sampled = _seeds_run(ctx.json_data("etcd-v2-sweep"))
    observed = f"{space} configurations of which {sampled} sampled"
    ok = space == 96 and sampled == 50
    return (MATCH if ok else MISMATCH, observed, "")


# etcd shrink minimal config, per the thesis (e2-12)
ETCD_MIN_EXPECTED = {
    "roles_etcd": 3,
    "memory_size": 1024,
    "disk_size": 2048,
    "heartbeat_interval_ms": 100,
    "election_timeout_ms": 1250,
    "snapshot_count": 10000,
    "quota_backend_bytes": 2097152,
}


def _h_e2_11(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("etcd-v2-shrink")
    seeds = d.get("seeds") or {}
    c3, c40 = (seeds.get("3") or {}).get("final_config"), (seeds.get("40") or {}).get(
        "final_config"
    )
    if c3 is None or c40 is None:
        return MISSING, "", "final_config missing for seed 3 or seed 40"
    observed = "identical" if _final_config_equal(c3, c40) else "differ"
    return (MATCH if _final_config_equal(c3, c40) else MISMATCH, observed, "")


def _h_e2_12(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("etcd-v2-shrink")
    fc = ((d.get("seeds") or {}).get("3") or {}).get("final_config") or {}
    bad = {k: fc.get(k) for k, want in ETCD_MIN_EXPECTED.items() if fc.get(k) != want}
    observed = f"final_config={json.dumps(fc, sort_keys=True)}"
    return (
        MATCH if not bad else MISMATCH,
        observed,
        "" if not bad else f"values differing from thesis minimum: {bad}",
    )


def _h_e2_13(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("etcd-v2-shrink")
    seeds = d.get("seeds") or {}
    # Absent data is "not reproduced", never a scored contradiction: the old
    # guard tested `parts`, which this fixed loop always fills, so a campaign
    # with no etcd-v2-shrink data scored a mismatch of "3: None/None/None".
    missing = [s for s in ("3", "40") if not isinstance(seeds.get(s), dict)]
    if missing:
        return MISSING, "", f"no etcd-v2-shrink entry for seed(s) {', '.join(missing)}"
    parts, ok = [], True
    for s in ("3", "40"):
        e = seeds.get(s) or {}
        p, f, t = e.get("passed"), e.get("failed"), e.get("total")
        parts.append(f"seed {s}: {p}/{f}/{t}")
        ok = ok and (p, f, t) == (11, 1, 12)
    return (MATCH if ok else MISMATCH, "; ".join(parts), "")


_ETCD_V2_CELLS = 96
_QUOTA_2MIB = 2097152


def _h_e2_15(claim: Claim, ctx: _Ctx) -> HandlerResult:
    """Exhaustive baseline: every cell reached a property verdict, and the
    property failures are exactly the 2 MiB cells.

    Only property verdicts count (see analyze._exhaustive_outcome): a cell
    that died before the property suite (the CLI never started, or the VM
    shell never came up) says nothing about its configuration.  Such cells are reported, and they make the enumeration
    incomplete, but they are never scored as a quota failure."""
    d = ctx.json_data("etcd-v2-exhaustive")
    cells = d.get("cells") or 0
    passed, failed = d.get("passed") or 0, d.get("failed") or 0
    no_verdict = d.get("no_property_verdict") or 0
    with_verdict = passed + failed
    if with_verdict == 0:
        return (
            MISSING,
            "",
            f"none of the {cells} exhaustive cells produced a property verdict "
            f"({no_verdict} ended before any property ran)",
        )
    by_bytes = d.get("failures_by_quota_bytes") or {}
    cells_by_bytes = d.get("cells_by_quota_bytes") or {}
    fail_desc = ", ".join(f"{v} at {k}" for k, v in sorted(by_bytes.items())) or "none"
    observed = (
        f"{with_verdict}/{cells} cells with a property verdict; {failed} fail ({fail_desc}); "
        f"{passed} pass"
    )
    if no_verdict:
        observed += f"; {no_verdict} without a property verdict (startup/infrastructure)"
    observed += f"; cells per quota {dict(sorted(cells_by_bytes.items()))}"
    two_mib_cells = int(cells_by_bytes.get(str(_QUOTA_2MIB), 0) or 0)
    ok = (
        cells == with_verdict == _ETCD_V2_CELLS
        and set(by_bytes) == {str(_QUOTA_2MIB)}
        and failed == two_mib_cells == 32
        and passed == 64
    )
    return (MATCH if ok else MISMATCH, observed, "")


def _h_e2_14(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("etcd-v2-shrink")
    same = d.get("identical_minimal_config")
    observed = f"identical_minimal_config={same}"
    return (MATCH if same is True else MISMATCH, observed, "")


# --- rabbitmq-disk handlers ---------------------------------------------------


def _h_r01(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-disk-cells")
    r, miss = _row_at(rows, "positive", 0, "disk-cells")
    if r is None:
        return MISSING, "", miss
    pp, pt = _gi(r, "checks_passed"), _gi(r, "checks_total")
    amb, al = _gi(r, "ambiguous_count"), _gi(r, "alarm_samples")
    observed = f"{pp}/{pt} checks pass; {amb} ambiguous publishes; {al} alarm samples"
    ok = (pp, pt, amb, al) == (5, 5, 0, 0)
    return (MATCH if ok else MISMATCH, observed, "")


def _h_r02(claim: Claim, ctx: _Ctx) -> HandlerResult:
    # Cell X free-space configuration values come from the disk-cells
    # artifact's contract columns (nominal free target, alarm limit,
    # payload, confirm timeout, safety factor).
    rows = ctx.csv_rows("rabbitmq-disk-cells")
    r, miss = _row_at(rows, "cell-x", 0, "disk-cells")
    if r is None:
        return MISSING, "", miss
    got = {
        "nominal_free_target_mb": _gi(r, "nominal_free_target_mb"),
        "disk_free_limit_mb": _gi(r, "disk_free_limit_mb"),
        "planned_messages": _gi(r, "planned_messages"),
        "message_size_kib": _gi(r, "message_size_kib"),
        "confirm_timeout_ms": _gi(r, "confirm_timeout_ms"),
        "safety_factor_milli": _gi(r, "safety_factor_milli"),
    }
    observed = "; ".join(f"{k}={v}" for k, v in sorted(got.items()))
    # Thesis wording: 100 MB nominal target, 200 MB alarm limit, 200 x 16 KiB
    # payload, 1 s confirm timeout, 1.5x safety factor. disk_free_limit.absolute
    # is configured as "200MB" (RabbitMQ's own decimal-MB convention, 2*10^8
    # bytes); this artifact's disk_free_limit_mb converts the reported byte
    # value to binary MiB (// 1024**2), which is 190 for a genuinely-correct
    # 200 (decimal) MB config — not an approximation, a fixed unit conversion.
    ok = (
        got["nominal_free_target_mb"] == 100
        and got["disk_free_limit_mb"] == 190
        and got["planned_messages"] == 200
        and got["message_size_kib"] == 16
        and got["confirm_timeout_ms"] == 1000
        and got["safety_factor_milli"] == 1500
    )
    return (MATCH if ok else MISMATCH, observed, "")


def _h_r03(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-disk-cells")
    r, miss = _row_at(rows, "cell-x", 0, "disk-cells")
    if r is None:
        return MISSING, "", miss
    naive, strict = _gb(r, "naive_sufficient"), _gb(r, "strict_sufficient")
    observed = f"naive_capacity_sufficient={naive}; capacity_sufficient={strict}"
    ok = naive is True and strict is False
    return (MATCH if ok else MISMATCH, observed, "")


def _h_r04(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-disk-cells")
    r, miss = _row_at(rows, "cell-x", 0, "disk-cells")
    if r is None:
        return MISSING, "", miss
    amb, al = _gi(r, "ambiguous_count"), _gi(r, "alarm_samples")
    observed = f"{al} alarm samples; {amb} ambiguous publish attempts"
    ok = amb == 200 and al == 14
    return (MATCH if ok else MISMATCH, observed, "")


def _recovered(claim: Claim, ctx: _Ctx, exec_index: int) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-disk-cells")
    r, miss = _row_at(rows, "cell-x", exec_index, "disk-cells")
    if r is None:
        return MISSING, "", miss
    rec = _gi(r, "recovered_count")
    if rec is None:
        return MISSING, "", "recovered_count column absent"
    if rec == 22:
        return MATCH, f"{rec} unconfirmed messages durably applied", ""
    if rec == 23:
        return WITHIN, f"{rec} unconfirmed messages durably applied", ""
    return MISMATCH, f"{rec} unconfirmed messages durably applied", ""


def _h_r05(claim: Claim, ctx: _Ctx) -> HandlerResult:
    return _recovered(claim, ctx, 0)


def _h_r06(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-disk-cells")
    r, miss = _row_at(rows, "cell-x", 0, "disk-cells")
    if r is None:
        return MISSING, "", miss
    pp, pt = _gi(r, "checks_passed"), _gi(r, "checks_total")
    failing = _gs(r, "failing_checks")
    observed = f"{pp}/{pt} checks pass; failing: {failing}"
    ok = (pp, pt) == (4, 5) and RMQ_CONTRACT in failing
    return (MATCH if ok else MISMATCH, observed, "")


def _repro_recovered(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-disk-cells")
    got = []
    for ei in (1, 2):
        r, miss = _row_at(rows, "cell-x", ei, "disk-cells")
        if r is None:
            return MISSING, "", miss
        rec = _gi(r, "recovered_count")
        if rec is None:
            return MISSING, "", "recovered_count column absent"
        got.append(rec)
    observed = f"cell-x reproduction recovered counts: {got[0]} and {got[1]}"
    if got == [22, 23]:
        return MATCH, observed, ""
    if all(g in (22, 23) for g in got):
        return WITHIN, observed, ""
    return MISMATCH, observed, ""


def _h_r08(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-disk-cells")
    pos = _rows_for(rows, "positive")
    if not pos:
        return MISSING, "", "no positive-control rows in artifact"
    bad = [
        r
        for r in pos
        if (
            _gi(r, "checks_passed"),
            _gi(r, "checks_total"),
            _gi(r, "ambiguous_count"),
            _gi(r, "alarm_samples"),
            _gb(r, "strict_sufficient"),
            _gb(r, "naive_sufficient"),
        )
        != (5, 5, 0, 0, True, True)
    ]
    first = pos[0]
    observed = (
        f"{len(pos) - len(bad)}/{len(pos)} positive rows: "
        f"{_gi(first, 'checks_passed')}/{_gi(first, 'checks_total')} checks, "
        f"{_gi(first, 'ambiguous_count')} ambiguous, "
        f"{_gi(first, 'alarm_samples')} alarms"
    )
    return (MATCH if not bad else MISMATCH, observed, "")


def _h_r09(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-disk-cells")
    r, miss = _row_at(rows, "cell-x", 0, "disk-cells")
    if r is None:
        return MISSING, "", miss
    strict, naive = _gb(r, "strict_sufficient"), _gb(r, "naive_sufficient")
    amb, al = _gi(r, "ambiguous_count"), _gi(r, "alarm_samples")
    observed = (
        f"strict_sufficient={strict}; naive_sufficient={naive}; "
        f"{amb} ambiguous; {al} alarm samples"
    )
    ok = strict is False and naive is True and amb == 200 and al == 14
    return (MATCH if ok else MISMATCH, observed, "")


# alarm_samples counts how many times the disk-alarm poller observed the
# alarm raised — a sampling artifact of the polling interval, not a property
# of the configuration under test.  Two byte-identical executions routinely
# land one sample apart (e.g. 15 vs 16 for the minimal cell), so an exact-value
# rule on it makes the verdict a coin flip.  Everything else about the cell
# — checks, failing check, ambiguous publishes — is scored exactly.
_ALARM_SAMPLE_SLACK = 1


def _h_r11(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-disk-cells")
    r, miss = _row_at(rows, "minimal", 0, "disk-cells")
    if r is None:
        return MISSING, "", miss
    amb, al = _gi(r, "ambiguous_count"), _gi(r, "alarm_samples")
    observed = f"{amb} ambiguous publish attempts; {al} alarm samples"
    if amb != 20 or al is None:
        return MISMATCH, observed, ""
    if al == 16:
        return MATCH, observed, ""
    if abs(al - 16) <= _ALARM_SAMPLE_SLACK:
        return (
            WITHIN,
            observed,
            f"20/20 ambiguous as claimed; {al} alarm samples against the thesis's 16 "
            "(the alarm poller samples ±1 between otherwise identical executions)",
        )
    return MISMATCH, observed, ""


def _h_r12(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-disk-cells")
    first, miss = _row_at(rows, "minimal", 0, "disk-cells")
    if first is None:
        return MISSING, "", miss
    second, miss = _row_at(rows, "minimal", 1, "disk-cells")
    if second is None:
        return MISSING, "", miss
    # The claim is that the duplicated run reaches the SAME verdict; the
    # alarm-sample count is compared with the poller's slack (see above).
    sig = ("checks_passed", "checks_total", "ambiguous_count", "failing_checks")
    a = tuple(_gs(first, k) for k in sig)
    b = tuple(_gs(second, k) for k in sig)
    al_a, al_b = _gi(first, "alarm_samples"), _gi(second, "alarm_samples")
    observed = (
        f"second minimal execution: {_gi(second, 'checks_passed')}/"
        f"{_gi(second, 'checks_total')} checks, "
        f"{_gi(second, 'ambiguous_count')} ambiguous, "
        f"{al_b} alarms (first execution: {al_a} alarms)"
    )
    if a != b:
        return MISMATCH, observed, ""
    if al_a == al_b:
        return MATCH, observed, ""
    if al_a is not None and al_b is not None and abs(al_a - al_b) <= _ALARM_SAMPLE_SLACK:
        return (
            WITHIN,
            observed,
            f"identical verdict, checks and ambiguous counts; alarm samples {al_a} vs "
            f"{al_b} (the alarm poller samples ±1 between identical executions)",
        )
    return MISMATCH, observed, ""


# --- rabbitmq-faildom handlers ------------------------------------------------


def _faildom_row(ctx: _Ctx, variant: str, exec_index: int) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-faildom-cells")
    return _row_at(rows, variant, exec_index, "faildom-cells")


def _faildom_observed(r: Dict[str, str]) -> str:
    return (
        f"{_gi(r, 'properties_passed')}/{_gi(r, 'properties_total')} properties; "
        f"{_gi(r, 'operations_recovered')}/{_gi(r, 'operations_total')} operations "
        f"exactly once; probe={_gs(r, 'probe_status')}; "
        f"failing: {_gs(r, 'failing_checks')}"
    )


def _h_r13(claim: Claim, ctx: _Ctx) -> HandlerResult:
    r, miss = _faildom_row(ctx, "spread", 0)
    if r is None:
        return MISSING, "", miss
    ok = (
        (_gi(r, "properties_passed"), _gi(r, "properties_total")) == (2, 2)
        and (_gi(r, "operations_recovered"), _gi(r, "operations_total")) == (11, 11)
        and _gs(r, "probe_status") == "confirmed"
    )
    reason = "" if ok else "spread signature differs from pass 2/2, 11/11, probe confirmed"
    return (MATCH if ok else MISMATCH, _faildom_observed(r), reason)


def _colocated_handler(exec_index: int) -> Handler:
    def handler(claim: Claim, ctx: _Ctx) -> HandlerResult:
        r, miss = _faildom_row(ctx, "colocated", exec_index)
        if r is None:
            return MISSING, "", miss
        pp, pt = _gi(r, "properties_passed"), _gi(r, "properties_total")
        failing = _gs(r, "failing_checks")
        recovery_ok = (_gi(r, "operations_recovered"), _gi(r, "operations_total")) == (11, 11)
        avail_failed = "retains-quorum" in failing or (
            pp is not None and pt is not None and pp < pt
        )
        probe_ok = _gs(r, "probe_status") == "ambiguous"
        ok = recovery_ok and avail_failed and probe_ok
        reason = (
            ""
            if ok
            else (
                "colocated signature requires 11/11 exactly-once recovery, an "
                "availability-contract failure, and an ambiguous probe"
            )
        )
        return (MATCH if ok else MISMATCH, _faildom_observed(r), reason)

    return handler


# --- rabbitmq-crash handlers --------------------------------------------------


def _crash_row(ctx: _Ctx, variant: str, exec_index: int = 0) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-crash-cells")
    return _row_at(rows, variant, exec_index, "crash-cells")


def _crash_handler(variant: str, leader: Optional[Tuple[str, str]]) -> Handler:
    """Score a crash cell: checks/confirmed/ambiguous exactly, plus the
    leader transition given in ``leader`` as (before, after).

    WHICH surviving node RabbitMQ elects after the leader is killed is not
    determined by the configuration under test — repeated executions of the
    same cell elect rabbit2 or rabbit3.  So when a migration was claimed and a migration
    happened, a different successor is within tolerance, not a contradiction.
    A cell claimed NOT to migrate (before == after) is still scored exactly:
    an unexpected migration there is a real difference."""

    def handler(claim: Claim, ctx: _Ctx) -> HandlerResult:
        r, miss = _crash_row(ctx, variant)
        if r is None:
            return MISSING, "", miss
        pp, pt = _gi(r, "checks_passed"), _gi(r, "checks_total")
        conf, amb = _gi(r, "confirmed_count"), _gi(r, "ambiguous_count")
        lb, la = _gs(r, "leader_before"), _gs(r, "leader_after")
        observed = f"{pp}/{pt} checks; {conf} confirmed; {amb} ambiguous; " f"leader {lb}->{la}"
        if (pp, pt, conf, amb) != (3, 3, 50, 0):
            return MISMATCH, observed, ""
        if leader is None or (lb, la) == leader:
            return MATCH, observed, ""
        before, after = leader
        migration_claimed = before != after
        migrated_elsewhere = lb == before and la not in (None, "", lb)
        if migration_claimed and migrated_elsewhere:
            return (
                WITHIN,
                observed,
                f"checks pass and the leader migrated off {before} as claimed, to {la} "
                f"rather than the thesis's {after} (the surviving node RabbitMQ elects "
                "is not determined by the configuration under test)",
            )
        return MISMATCH, observed, ""

    return handler


def _h_r18(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-crash-cells")
    if not rows:
        return MISSING, "", "no crash rows in artifact"
    bad = [
        r
        for r in rows
        if (
            _gi(r, "checks_passed"),
            _gi(r, "checks_total"),
            _gi(r, "confirmed_count"),
            _gi(r, "ambiguous_count"),
        )
        != (3, 3, 50, 0)
    ]
    observed = f"{len(rows) - len(bad)}/{len(rows)} crash rows: pass 3/3, 50 confirmed, 0 ambiguous"
    return (MATCH if not bad else MISMATCH, observed, "")


def _h_r19(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-crash-cells")
    if not rows:
        return MISSING, "", "no crash rows in artifact"
    ambs = [(_gs(r, "variant"), _gi(r, "ambiguous_count")) for r in rows]
    observed = f"ambiguous counts across {len(rows)} crash rows: " + ",".join(
        f"{v}={a}" for v, a in ambs
    )
    ok = all(a == 0 for _v, a in ambs)
    return (MATCH if ok else MISMATCH, observed, "")


def _h_r26(claim: Claim, ctx: _Ctx) -> HandlerResult:
    rows = ctx.csv_rows("rabbitmq-crash-cells")
    counts: Dict[str, int] = {}
    for r in rows:
        cell = _gs(r, "variant")
        if cell in ("follower-repA", "follower-repB"):
            cell = "follower"
        elif cell == "retune-follower":
            # Appendix semantics: the "resolved during-publish follower
            # configuration" is executed twice — the Phase-2 during-publish
            # run and the Phase-3 follower retune (identical resolved
            # parameters: timing=during_publish, delay 10s, count 50).
            cell = "during-publish"
        counts[cell] = counts.get(cell, 0) + 1
    if not counts:
        return MISSING, "", "no crash rows in artifact"
    observed = "; ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    ok = (
        counts.get("follower") == 2
        and counts.get("during-publish") == 2
        and all(v == 1 for k, v in counts.items() if k not in ("follower", "during-publish"))
    )
    return (MATCH if ok else MISMATCH, observed, "")


# --- execution accounting / test suites ---------------------------------------


def _space_handler(group: str, expected: int, extra: str = "") -> Handler:
    def handler(claim: Claim, ctx: _Ctx) -> HandlerResult:
        acc = ctx.json_data("execution-accounting")
        space = (acc.get("groups") or {}).get(group, {}).get("space_size")
        observed = f"{group}: space_size={space}" + (f"; {extra}" if extra else "")
        return (MATCH if space == expected else MISMATCH, observed, "")

    return handler


def _h_c03(claim: Claim, ctx: _Ctx) -> HandlerResult:
    acc = ctx.json_data("execution-accounting")
    groups = acc.get("groups") or {}
    parts, ok = [], True
    for group, want in (("rabbitmq-disk", 864), ("rabbitmq-faildom", 4), ("rabbitmq-crash", 24)):
        space = (groups.get(group) or {}).get("space_size")
        parts.append(f"{group}={space}")
        ok = ok and space == want
    return (MATCH if ok else MISMATCH, "; ".join(parts), "")


# Framework Python test count at the thesis revision.  The harness runs the
# suite of whatever revision is checked out, and the framework has kept
# growing since (e.g. the repetition-token tests), so a larger passing suite
# is a superset of the claim, not a contradiction of it.
_THESIS_PY_TESTS = 57


def _h_t01(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("test-suites")
    py = d.get("python") or {}
    ran, suite_ok = py.get("ran"), py.get("ok")
    observed = f"python suite: ran={ran}, ok={suite_ok}"
    if ran is None:
        return MISSING, observed, "test-suites.json records no python suite result"
    if suite_ok is True and ran == _THESIS_PY_TESTS:
        return MATCH, observed, ""
    if suite_ok is True and ran > _THESIS_PY_TESTS:
        return (
            WITHIN,
            observed,
            f"suite passes; {ran - _THESIS_PY_TESTS} test(s) added to the framework "
            f"after the thesis revision (thesis-era count {_THESIS_PY_TESTS})",
        )
    return MISMATCH, observed, ""


def _h_t02(claim: Claim, ctx: _Ctx) -> HandlerResult:
    d = ctx.json_data("test-suites")
    nix = d.get("nix") or {}
    observed = (
        f"nix suite: successful={nix.get('successful')}/{nix.get('total')}, " f"ok={nix.get('ok')}"
    )
    ok = nix.get("successful") == 114 and nix.get("total") == 114 and nix.get("ok") is True
    return (MATCH if ok else MISMATCH, observed, "")


# --- informational handlers ---------------------------------------------------


def _h_info_absent(claim: Claim, ctx: _Ctx) -> HandlerResult:
    # Genuinely informational (historical) claims are reported as their own
    # verdict, not as not-reproduced — they were never reproduction targets.
    if claim.tolerance == "informational":
        return INFO, "", "historical/informational claim; no reproduction target"
    return MISSING, "", "no analysis artifact records this claim"


def _h_m08(claim: Claim, ctx: _Ctx) -> HandlerResult:
    k = ctx.json_data("kafka-sweep")
    det = (ctx.json_data("determinism").get("kafka-sweep") or {}).get("flips")
    e = ctx.json_data("etcd-v2-sweep")
    observed = (
        f"kafka {k.get('passed')}/{k.get('failed')}, flips={det}; "
        f"etcd v2 {e.get('passed')}/{e.get('failed')}, "
        f"failure_class={e.get('failure_class')}"
    )
    return INFO, observed, ""


def _h_r27(claim: Claim, ctx: _Ctx) -> HandlerResult:
    e = ctx.json_data("etcd-v2-sweep")
    disk = ctx.csv_rows("rabbitmq-disk-cells")
    observed = (
        f"etcd v2 {e.get('passed')}/{e.get('failed')} in class "
        f"{e.get('failure_class')}; {len(disk)} rabbitmq disk cell rows"
    )
    return INFO, observed, ""


# --- routing table -------------------------------------------------------------

ROUTE: Dict[str, Tuple[str, Handler]] = {
    "k-01": ("analysis/kafka-sweep.json", _h_k01),
    "k-02": ("analysis/kafka-sweep.json", _h_k02),
    "k-03": ("analysis/kafka-sweep.json", _h_k03),
    "k-22": ("analysis/kafka-crosstab.csv", _h_k22),
    "k-23": ("analysis/kafka-crosstab.csv", _h_k23),
    "k-24": ("analysis/kafka-sweep.json", _seed_class_handler(13, KAFKA_BROKER_MAX)),
    "k-25": ("analysis/kafka-min-configs.json", _h_k25),
    "k-26": ("analysis/kafka-sweep.json", _seed_class_handler(9, KAFKA_LOG_SEGMENT)),
    "k-27": ("analysis/kafka-min-configs.json", _h_k27),
    "k-28": ("analysis/kafka-shrink.json", _h_k28),
    "k-29": ("analysis/execution-accounting.json", _h_k29),
    "k-30": ("analysis/determinism.json", _h_k30),
    "k-31": ("analysis/kafka-sweep.json", _h_k31),
    "e1-01": ("analysis/etcd-v1-sweep.json", _etcd_split_handler("etcd-v1-sweep", 39, 11)),
    "e1-02": ("analysis/etcd-v1-sweep.json", _failing_seeds_handler()),
    "e1-03": ("analysis/etcd-v1-sweep.json", _h_e1_03),
    "e1-04": ("analysis/etcd-v1-sweep.json", _h_e1_04),
    "e2-01": ("analysis/etcd-v2-sweep.json", _etcd_split_handler("etcd-v2-sweep", 37, 13)),
    "e2-02": ("analysis/etcd-v2-sweep.json", _failing_seeds_handler()),
    "e2-03": ("analysis/etcd-v2-sweep.json", _h_e2_03),
    "e2-04": ("analysis/etcd-v2-sweep.json", _h_e2_04),
    "e2-05": ("analysis/etcd-v2-quota-correlation.csv", _quota_cell_handler(2097152)),
    "e2-06": ("analysis/etcd-v2-quota-correlation.csv", _quota_cell_handler(8388608)),
    "e2-07": ("analysis/etcd-v2-quota-correlation.csv", _quota_cell_handler(67108864)),
    "e2-08": ("analysis/etcd-v2-quota-correlation.csv", _h_e2_08),
    "e2-09": ("analysis/etcd-v2-sweep.json", _h_e2_09),
    "e2-10": ("analysis/execution-accounting.json", _h_e2_10),
    "e2-11": ("analysis/etcd-v2-shrink.json", _h_e2_11),
    "e2-12": ("analysis/etcd-v2-shrink.json", _h_e2_12),
    "e2-13": ("analysis/etcd-v2-shrink.json", _h_e2_13),
    "e2-14": ("analysis/etcd-v2-shrink.json", _h_e2_14),
    "e2-15": ("analysis/etcd-v2-exhaustive.json", _h_e2_15),
    "r-01": ("analysis/rabbitmq-disk-cells.csv", _h_r01),
    "r-02": ("analysis/rabbitmq-disk-cells.csv", _h_r02),
    "r-03": ("analysis/rabbitmq-disk-cells.csv", _h_r03),
    "r-04": ("analysis/rabbitmq-disk-cells.csv", _h_r04),
    "r-05": ("analysis/rabbitmq-disk-cells.csv", _h_r05),
    "r-06": ("analysis/rabbitmq-disk-cells.csv", _h_r06),
    "r-07": ("analysis/rabbitmq-disk-cells.csv", _repro_recovered),
    "r-08": ("analysis/rabbitmq-disk-cells.csv", _h_r08),
    "r-09": ("analysis/rabbitmq-disk-cells.csv", _h_r09),
    "r-10": ("analysis/rabbitmq-disk-cells.csv", _repro_recovered),
    "r-11": ("analysis/rabbitmq-disk-cells.csv", _h_r11),
    "r-12": ("analysis/rabbitmq-disk-cells.csv", _h_r12),
    "r-13": ("analysis/rabbitmq-faildom-cells.csv", _h_r13),
    "r-14": ("analysis/rabbitmq-faildom-cells.csv", _colocated_handler(0)),
    "r-15": ("analysis/rabbitmq-faildom-cells.csv", _h_r13),
    "r-16": ("analysis/rabbitmq-faildom-cells.csv", _colocated_handler(0)),
    "r-17": ("analysis/rabbitmq-faildom-cells.csv", _colocated_handler(1)),
    "r-18": ("analysis/rabbitmq-crash-cells.csv", _h_r18),
    "r-19": ("analysis/rabbitmq-crash-cells.csv", _h_r19),
    "r-20": (
        "analysis/rabbitmq-crash-cells.csv",
        _crash_handler("follower-repA", ("rabbit1", "rabbit1")),
    ),
    "r-21": (
        "analysis/rabbitmq-crash-cells.csv",
        _crash_handler("follower-repB", ("rabbit1", "rabbit1")),
    ),
    "r-22": ("analysis/rabbitmq-crash-cells.csv", _crash_handler("leader", ("rabbit1", "rabbit2"))),
    "r-23": (
        "analysis/rabbitmq-crash-cells.csv",
        _crash_handler("during-publish", ("rabbit1", "rabbit1")),
    ),
    "r-24": ("analysis/rabbitmq-crash-cells.csv", _crash_handler("retune-follower", None)),
    "r-25": (
        "analysis/rabbitmq-crash-cells.csv",
        _crash_handler("retune-leader", ("rabbit1", "rabbit2")),
    ),
    "r-26": ("analysis/rabbitmq-crash-cells.csv", _h_r26),
    "r-27": ("analysis/etcd-v2-sweep.json", _h_r27),
    "c-01": ("analysis/execution-accounting.json", _space_handler("kafka-cluster", 746496)),
    "c-02": ("analysis/execution-accounting.json", _space_handler("etcd-cluster", 96)),
    "c-03": ("analysis/execution-accounting.json", _h_c03),
    "c-04": (
        "analysis/execution-accounting.json",
        _space_handler("kafka-cluster", 746496, "product of per-dimension value counts"),
    ),
    "t-01": ("analysis/test-suites.json", _h_t01),
    "t-02": ("analysis/test-suites.json", _h_t02),
    "m-08": (
        "analysis/kafka-sweep.json + analysis/determinism.json + " "analysis/etcd-v2-sweep.json",
        _h_m08,
    ),
}
# k-04..k-21: the 18 crosstab cells share one generic extractor.
for _n in range(4, 22):
    ROUTE[f"k-{_n:02d}"] = ("analysis/kafka-crosstab.csv", _crosstab_cell)
# m-01..m-07 are informational claims about historical baselines / workload
# descriptions that no current-campaign artifact covers.
for _n in range(1, 8):
    ROUTE[f"m-{_n:02d}"] = ("", _h_info_absent)


def run(out_dir: Path, collected: Any, claims_path: str) -> Dict[str, Any]:
    """Verify every claim; write verification/claims-matrix.csv; return summary."""
    out_dir = Path(out_dir)
    ctx = _Ctx(out_dir)
    rows: List[Dict[str, str]] = []
    for claim in sorted(load_claims(claims_path), key=lambda c: c.claim_id):
        route = ROUTE.get(claim.claim_id)
        if route is None:
            verdict, observed, artifact, reason = (
                MISSING,
                "",
                "",
                f"no routing registered for {claim.claim_id}",
            )
        else:
            artifact, handler = route
            try:
                verdict, observed, reason = handler(claim, ctx)
            except _Absent as exc:
                verdict, observed, reason = MISSING, "", f"artifact {exc.artifact} missing"
        rows.append(
            {
                "claim_id": claim.claim_id,
                "location": claim.location,
                "expected": claim.expected_value,
                "observed": observed,
                "verdict": verdict,
                "artifact": artifact,
                "reason": reason,
            }
        )
    vdir = out_dir / "verification"
    vdir.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(MATRIX_HEADER)
    for row in sorted(rows, key=lambda r: r["claim_id"]):
        writer.writerow([row[h] for h in MATRIX_HEADER])
    atomic_write_text(vdir / "claims-matrix.csv", buf.getvalue())
    counts = {v: 0 for v in (MATCH, WITHIN, MISMATCH, MISSING, INFO)}
    for row in rows:
        counts[row["verdict"]] += 1
    return {
        "match": counts[MATCH],
        "within-tolerance": counts[WITHIN],
        "mismatch": counts[MISMATCH],
        "not-reproduced": counts[MISSING],
        "informational": counts[INFO],
        "rows": rows,
    }
