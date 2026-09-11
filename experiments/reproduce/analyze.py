"""analyze.py — deterministic artifact generation from collected campaign data.

Contract (frozen in models.py): run_all(out_dir, collected) -> None.
One exported function per analysis/* artifact; every function is a pure
function of (raw/, resolution/) as captured in the Collected record and writes
its artifact into <out_dir>/analysis/ with an atomic replace.

Determinism requirements (verified byte-identical by the tests):
  - JSON: sort_keys=True, indent=2, trailing newline;
  - every float is formatted "%.6g" (and emitted as a string) BEFORE writing;
  - no wall-clock timestamps anywhere;
  - CSV rows sorted; "\n" line terminator.

Real run-store field paths this module reads (verified against the retained
evidence in .topotestix/runs-thesis-redesign/ and .topotestix/runs/):
  run.json:      {"status": "passed"|"failed", "summary": {passed, failed, total}}
  report.json:   [{"name", "status", "message"}]  (status: passed|failed|...)
  resolved.json: {"roleFuzz": {<role>: {"choices": {path: int},
                  "result": {...resolved nix attrs...}}},
                  "topology": {"roles": {role: count}}}
  disk evidence (e.g. disk-results.json):
      operations[i]["outcome"] == "ambiguous"   -> ambiguous publish attempts
      telemetry[i]["disk_free_alarm"] is True   -> alarm samples
      len(recovered)                            -> recovered message count
      contract["capacity_sufficient"]           -> strict capacity flag
      contract["naive_capacity_sufficient"]     -> naive capacity flag
  failure-domain evidence (failure-domain-results.json):
      placement[node], len(baseline_ids), probe["outcome"], len(recovered)
  crash evidence (crash-results.json):
      operations[i]["outcome"] ("confirmed"/"ambiguous"),
      queue_before["leader"], queue_after["leader"], len(recovered)
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from experiments.reproduce.collect import Collected
from experiments.reproduce.models import atomic_write_json, atomic_write_text

MIB = 1048576

# --- determinism helpers ---------------------------------------------------


def _fmt(v: Any) -> Any:
    """Format every float as a "%.6g" string; recurse; leave ints/bools/str."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        return f"{v:.6g}"
    if isinstance(v, dict):
        return {k: _fmt(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_fmt(x) for x in v]
    return v


def _analysis_dir(collected: Collected) -> Path:
    out_dir = Path(collected.out_dir if collected.out_dir is not None else ".")
    d = out_dir / "analysis"
    os.makedirs(d, exist_ok=True)
    return d


def _write_json(collected: Collected, name: str, obj: Any) -> None:
    atomic_write_json(_analysis_dir(collected) / name, _fmt(obj))


def _write_csv(collected: Collected, name: str, header: List[str], rows: List[List[Any]]) -> None:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if v is None else _fmt(v) for v in row])
    atomic_write_text(_analysis_dir(collected) / name, buf.getvalue())


# --- record access helpers --------------------------------------------------


def _units(collected: Collected, entry_id: str) -> List[Dict[str, Any]]:
    return list(collected.by_entry.get(entry_id, []))


def _meta(rec: Dict[str, Any], key: str, default: Any = None) -> Any:
    unit = rec.get("unit")
    if isinstance(unit, dict) and unit.get(key) is not None:
        return unit.get(key)
    run = rec.get("run")
    if isinstance(run, dict) and run.get(key) is not None:
        return run.get(key)
    return default


def _rep(rec: Dict[str, Any]) -> int:
    return int(_meta(rec, "repetition_index", 0) or 0)


def _run(rec: Dict[str, Any]) -> Dict[str, Any]:
    run = rec.get("run")
    return run if isinstance(run, dict) else {}


def _checks(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    report = rec.get("report")
    return report if isinstance(report, list) else []


def _failed_checks(rec: Dict[str, Any]) -> List[str]:
    return [c.get("name", "") for c in _checks(rec) if c.get("status") == "failed"]


def _failed_messages(rec: Dict[str, Any]) -> List[str]:
    return [str(c.get("message", "")) for c in _checks(rec) if c.get("status") == "failed"]


def _summary(rec: Dict[str, Any]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """(passed, failed, total) from run.json summary, else from report.json."""
    s = _run(rec).get("summary")
    if isinstance(s, dict) and isinstance(s.get("total"), int):
        return int(s.get("passed") or 0), int(s.get("failed") or 0), int(s["total"])
    checks = _checks(rec)
    if checks:
        p = sum(1 for c in checks if c.get("status") in ("passed", "expected_failure"))
        f = sum(1 for c in checks if c.get("status") == "failed")
        return p, f, len(checks)
    return None, None, None


def _verdict(rec: Dict[str, Any]) -> Optional[str]:
    status = _run(rec).get("status")
    if status in ("passed", "failed"):
        return str(status)
    _, failed, total = _summary(rec)
    if total and failed is not None:
        return "passed" if failed == 0 else "failed"
    return None


def _evidence(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ev = rec.get("evidence")
    if not isinstance(ev, dict):
        return None
    for name in sorted(ev):
        if name.endswith("-results.json") and isinstance(ev[name], dict):
            return ev[name]
    return None


def _node_name(value: Any) -> Optional[str]:
    """Normalize a queue-leader value: the management API reports
    'rabbit@rabbit1'; the thesis tables use the bare node name."""
    if value is None:
        return None
    return str(value).split("@")[-1]


def _resolve_role(rec: Dict[str, Any], role: str) -> Dict[str, Any]:
    resolved = rec.get("resolved")
    if not isinstance(resolved, dict):
        return {}
    rf = resolved.get("roleFuzz")
    if not isinstance(rf, dict):
        return {}
    info = rf.get(role)
    return info if isinstance(info, dict) else {}


def _role_result(rec: Dict[str, Any], role: str) -> Dict[str, Any]:
    info = _resolve_role(rec, role)
    result = info.get("result")
    return result if isinstance(result, dict) else {}


def _int_at(d: Any, *path: str) -> Optional[int]:
    for key in path:
        if not isinstance(d, dict) or key not in d:
            return None
        d = d[key]
    try:
        return int(d)
    except (TypeError, ValueError):
        return None


def _mib_label(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    if value % MIB == 0:
        return f"{value // MIB}MiB"
    return str(value)


def _first_key(d: Any, keys: Tuple[str, ...]) -> Any:
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


# --- failure-class derivation ----------------------------------------------

KAFKA_BROKER_MAX = "broker-message-max-too-small"
KAFKA_LOG_SEGMENT = "log-segment-too-small"
ETCD_V1_CLASS = "invalid-etcd-election-timeout-heartbeat-ratio"
ETCD_V2_CLASS = "quota-backend-too-small-for-write-burst"
UNCLASSIFIED = "unclassified"


def kafka_failure_class(message: Optional[str]) -> Optional[str]:
    if not message:
        return None
    if "RecordTooLargeException" in message:
        return KAFKA_BROKER_MAX
    if "RecordBatchTooLargeException" in message:
        return KAFKA_LOG_SEGMENT
    return UNCLASSIFIED


def etcd_v1_failure_class(message: Optional[str]) -> Optional[str]:
    if not message:
        return None
    low = message.lower()
    if "election-timeout" in low or "should be at least" in low:
        return ETCD_V1_CLASS
    return UNCLASSIFIED


def etcd_v2_failure_class(check_name: Optional[str], message: Optional[str]) -> Optional[str]:
    if check_name and "quota-write-burst" in check_name:
        return ETCD_V2_CLASS
    if message and "database space exceeded" in message:
        return ETCD_V2_CLASS
    if check_name or message:
        return UNCLASSIFIED
    return None


# --- 1. kafka-sweep.{json,csv} ----------------------------------------------


def _sweep_per_seed(collected: Collected, entry_id: str, classify) -> List[Dict[str, Any]]:
    rows = []
    for rec in _units(collected, entry_id):
        if _rep(rec) != 0:
            continue
        seed = _meta(rec, "seed")
        failed = _failed_checks(rec)
        msgs = _failed_messages(rec)
        cls = classify(msgs[0] if msgs else None) if failed else None
        rows.append(
            {
                "seed": seed,
                "status": _verdict(rec),
                "failed_checks": sorted(failed),
                "failure_class": cls,
            }
        )
    return sorted(rows, key=lambda r: (r["seed"] is None, r["seed"], str(r["status"])))


def analyze_kafka_sweep(collected: Collected) -> Dict[str, Any]:
    per_seed = _sweep_per_seed(collected, "kafka-sweep", kafka_failure_class)
    classes: Dict[str, int] = {}
    for r in per_seed:
        if r["failure_class"]:
            classes[r["failure_class"]] = classes.get(r["failure_class"], 0) + 1
    passed = sum(1 for r in per_seed if r["status"] == "passed")
    failed = sum(1 for r in per_seed if r["status"] == "failed")
    out = {
        "seeds_run": len(per_seed),
        "passed": passed,
        "failed": failed,
        "failure_classes": classes,
        "per_seed": per_seed,
    }
    _write_json(collected, "kafka-sweep.json", out)
    _write_csv(
        collected,
        "kafka-sweep.csv",
        ["seed", "status", "failed_checks", "failure_class"],
        [
            [r["seed"], r["status"], ";".join(r["failed_checks"]), r["failure_class"]]
            for r in per_seed
        ],
    )
    return out


# --- 2. kafka-crosstab.csv ---------------------------------------------------


def _kafka_sizes(rec: Dict[str, Any]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    result = _role_result(rec, "kafka")
    settings = result.get("services", {}).get("apache-kafka", {}).get("settings", {})
    return (
        _int_at(settings, "message.max.bytes"),
        _int_at(settings, "replica.fetch.max.bytes"),
        _int_at(settings, "log.segment.bytes"),
    )


def analyze_kafka_crosstab(collected: Collected) -> List[List[Any]]:
    cells: Dict[Tuple[str, str, str], List[int]] = {}
    for rec in _units(collected, "kafka-sweep"):
        if _rep(rec) != 0:
            continue
        msg_max, rep_max, seg = _kafka_sizes(rec)
        key = (_mib_label(msg_max), _mib_label(rep_max), _mib_label(seg))
        if None in key:
            continue
        counts = cells.setdefault(key, [0, 0, 0])
        verdict = _verdict(rec)
        if verdict == "passed":
            counts[0] += 1
        else:
            msgs = _failed_messages(rec)
            cls = kafka_failure_class(msgs[0] if msgs else None)
            if cls == KAFKA_BROKER_MAX:
                counts[1] += 1
            elif cls == KAFKA_LOG_SEGMENT:
                counts[2] += 1
    rows = [[k[0], k[1], k[2], v[0], v[1], v[2]] for k, v in sorted(cells.items())]
    _write_csv(
        collected,
        "kafka-crosstab.csv",
        [
            "message_max_bytes",
            "replica_fetch_max_bytes",
            "log_segment_bytes",
            "pass",
            "broker_max",
            "log_segment",
        ],
        rows,
    )
    return rows


# --- 3. kafka-shrink.json ----------------------------------------------------


def _parse_final_choices(text: str) -> Optional[Dict[str, Any]]:
    """Parse the CLI shrink output: 'Final topology choices:'/'Final config
    choices:' followed by a JSON object each."""
    out: Dict[str, Any] = {}
    for marker, key in (
        ("Final topology choices:", "topology_choices"),
        ("Final config choices:", "config_choices"),
    ):
        idx = text.find(marker)
        if idx < 0:
            continue
        rest = text[idx + len(marker) :].lstrip()
        try:
            obj, _ = json.JSONDecoder().raw_decode(rest)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out[key] = obj
    return out or None


def _shrink_final_choices(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    shrink = rec.get("shrink")
    if isinstance(shrink, dict):
        for keys in (
            ("final_config",),
            ("final_topology_choices", "final_config_choices"),
            ("topology", "config"),
        ):
            vals = [shrink[k] for k in keys if isinstance(shrink.get(k), dict)]
            if len(vals) == len(keys):
                return {k: v for k, v in zip(keys, vals)}
        text = shrink.get("stdout") or shrink.get("output")
        if isinstance(text, str):
            parsed = _parse_final_choices(text)
            if parsed:
                return parsed
    for text in (rec.get("stdout"), rec.get("stderr")):
        if isinstance(text, str):
            parsed = _parse_final_choices(text)
            if parsed:
                return parsed
    return None


def _trial_table(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Human-readable summary of every candidate build a shrink loop tried (or
    the single execution a run/sweep/exhaustive unit performed), sourced from
    runner.py's trials.json (record["trials"]). This is the cleaner, indexed
    view over the raw per-trial directories under raw/<unit-id>/run-store/ —
    every candidate the shrinker actually built, not just the kept one.
    None when trials.json is absent (unit failed before any trial ran)."""
    trials = rec.get("trials")
    if not isinstance(trials, list) or not trials:
        return None
    executions: Dict[str, int] = {}
    rows = []
    for i, t in enumerate(trials):
        if not isinstance(t, dict):
            continue
        kind = t.get("execution") or "unknown"
        executions[kind] = executions.get(kind, 0) + 1
        rows.append({"index": i, "execution": kind, "status": t.get("status")})
    return {"count": len(rows), "executions": executions, "trials": rows}


def _kafka_resolved_config(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    resolved = rec.get("resolved")
    if not isinstance(resolved, dict):
        return None
    result = _role_result(rec, "kafka")
    if not result:
        return None
    settings = result.get("services", {}).get("apache-kafka", {}).get("settings", {})
    roles = resolved.get("topology", {}).get("roles", {})
    return {
        "roles_kafka": roles.get("kafka"),
        "settings": settings if isinstance(settings, dict) else {},
        "virtualisation": result.get("virtualisation", {}),
    }


def analyze_kafka_shrink(collected: Collected) -> Dict[str, Any]:
    orig = {}
    for r in _sweep_per_seed(collected, "kafka-sweep", kafka_failure_class):
        orig[r["seed"]] = r["failure_class"]
    seeds: Dict[str, Any] = {}
    for rec in sorted(
        _units(collected, "kafka-shrink"),
        key=lambda r: (_meta(r, "seed") is None, _meta(r, "seed")),
    ):
        seed = _meta(rec, "seed")
        failed = _failed_checks(rec)
        msgs = _failed_messages(rec)
        shrunk_class = kafka_failure_class(msgs[0] if msgs else None) if failed else None
        original_class = orig.get(seed)
        preserved: Optional[bool] = None
        if original_class and shrunk_class and shrunk_class != UNCLASSIFIED:
            preserved = original_class == shrunk_class
        final = _kafka_resolved_config(rec) or _shrink_final_choices(rec)
        seeds[str(seed)] = {
            "original_class": original_class,
            "shrunk_status": _verdict(rec),
            "final_config": final,
            "class_preserved": preserved,
            "trials": _trial_table(rec),
        }
    out = {"seeds": seeds}
    _write_json(collected, "kafka-shrink.json", out)
    return out


# --- 4. kafka-min-configs.json ----------------------------------------------


def analyze_kafka_min_configs(collected: Collected) -> Dict[str, Any]:
    per: Dict[str, Dict[str, Any]] = {}
    for rec in _units(collected, "kafka-min-configs"):
        variant = _meta(rec, "variant_name") or "default"
        if variant in per:
            continue
        passed, failed, _total = _summary(rec)
        failed_names = _failed_checks(rec)
        msgs = _failed_messages(rec)
        per[variant] = {
            "passed": passed,
            "failed": failed,
            "failed_check": failed_names[0] if failed_names else None,
            "exception_class": kafka_failure_class(msgs[0] if msgs else None),
        }
    out = {"variants": per}
    _write_json(collected, "kafka-min-configs.json", out)
    return out


# --- 5./6. etcd sweeps -------------------------------------------------------


# Lines worth surfacing as "the error", most-specific first. A captured log
# can be thousands of lines of QEMU/etcd JSON noise; the distilled artifacts
# (and the CSV cells downstream) need one readable line, not a raw dump.
_ERROR_SIGNATURES = (
    "database space exceeded",
    "should be at least",
    "election-timeout",
    "panic:",
    "fatal",
    "error:",
    "failed:",
)
_ERROR_LINE_CAP = 240


def _condense_error(message: Optional[str], cap: int = _ERROR_LINE_CAP) -> Optional[str]:
    """Reduce a possibly huge, multi-line captured error to one salient line.

    Picks the last non-blank line matching a known error signature; failing
    that, the last non-blank line. Always length-capped so it stays legible
    in JSON artifacts and CSV cells."""
    if not message:
        return None
    lines = [ln.strip() for ln in str(message).splitlines() if ln.strip()]
    if not lines:
        return None
    chosen = None
    for sig in _ERROR_SIGNATURES:
        hits = [ln for ln in lines if sig in ln.lower()]
        if hits:
            chosen = hits[-1]
            break
    if chosen is None:
        chosen = lines[-1]
    if len(chosen) > cap:
        chosen = chosen[: cap - 1].rstrip() + "…"
    return chosen


def _final_trial_console_log(rec: Dict[str, Any], collected: Collected) -> str:
    """Best-effort read of the final trial's real VM console log.

    rec["stdout"]/rec["stderr"] are the wrapper CLI's own captured output
    (nix-build phase noise + the final --json summary) — --output-dir routes
    the VM's actual console output (systemd, application logs) straight into
    run-store/<trial>/ instead, and it is deliberately never copied back into
    the flat raw/<id>/ files (see runner.py's _index_run_store docstring).
    Those console logs are gitignored, so in a fresh clone they are absent;
    log-digest.json carries the committed projection of them and collect.py
    exposes it as rec["final_trial_console_digest"] — used as the fallback so
    this stays a function of what raw/ actually holds in git.
    Returns "" if there's no trial to read (e.g. non-VM unit kinds)."""
    trials = rec.get("trials")
    text = ""
    if trials and collected.out_dir is not None:
        last = trials[-1]
        trial_dir_name = last.get("dir") if isinstance(last, dict) else None
        uid = rec.get("id")
        if trial_dir_name and uid:
            trial_dir = Path(collected.out_dir) / "raw" / uid / "run-store" / trial_dir_name
            for name in ("stderr.log", "stdout.log"):
                try:
                    text += (trial_dir / name).read_text(encoding="utf-8", errors="replace") + "\n"
                except OSError:
                    pass
    if not text.strip():
        text = rec.get("final_trial_console_digest") or ""
    return text


def _stderr_error_sample(rec: Dict[str, Any], collected: Collected) -> Optional[str]:
    """Best-effort startup-failure message: v1 etcd failures occur before the
    property suite, so there are no failed checks — the message only surfaces
    in the VM's own console log. Search the final trial's run-store log first
    (where the real application/systemd output lives); fall back to the
    wrapper's captured stdout/stderr for unit kinds with no run-store trial."""
    sample = _condense_error(_final_trial_console_log(rec, collected))
    if sample is not None:
        return sample
    combined = (rec.get("stderr") or "") + "\n" + (rec.get("stdout") or "")
    return _condense_error(combined)


def analyze_etcd_v1_sweep(collected: Collected) -> Dict[str, Any]:
    out = _etcd_sweep(collected, "etcd-v1-sweep", etcd_v1_failure_class)
    _write_json(collected, "etcd-v1-sweep.json", out)
    return out


def analyze_etcd_v2_sweep(collected: Collected) -> Dict[str, Any]:
    out = _etcd_sweep(collected, "etcd-v2-sweep", None)  # classifier set below
    _write_json(collected, "etcd-v2-sweep.json", out)
    return out


def _etcd_sweep(collected: Collected, entry_id: str, classify) -> Dict[str, Any]:
    per_seed = []
    failing: List[Dict[str, Any]] = []
    for rec in _units(collected, entry_id):
        if _rep(rec) != 0:
            continue
        failed_names = _failed_checks(rec)
        msgs = _failed_messages(rec)
        verdict = _verdict(rec)
        if classify is None:  # etcd v2 classifier needs the check name too
            cls = (
                etcd_v2_failure_class(
                    failed_names[0] if failed_names else None, msgs[0] if msgs else None
                )
                if failed_names
                else None
            )
        elif failed_names:
            cls = classify(msgs[0] if msgs else None)
        elif verdict == "failed":
            # Startup-only failure (no property report): classify from the
            # captured error message in the logs.
            cls = classify(_stderr_error_sample(rec, collected))
        else:
            cls = None
        if verdict == "failed" or failed_names:
            failing.append(
                {
                    "seed": _meta(rec, "seed"),
                    "rec": rec,
                    "cls": cls,
                    "failed": failed_names,
                    "msgs": msgs,
                }
            )
        per_seed.append(
            {
                "seed": _meta(rec, "seed"),
                "status": verdict,
                "failed_checks": sorted(failed_names),
                "failure_class": cls,
            }
        )
    per_seed.sort(key=lambda r: (r["seed"] is None, r["seed"], str(r["status"])))
    failing.sort(key=lambda r: (r["seed"] is None, r["seed"]))
    classes = [f["cls"] for f in failing if f["cls"]]
    if failing and classes and len(set(classes)) == 1:
        failure_class = classes[0]
    elif failing:
        failure_class = "mixed"
    else:
        failure_class = None
    sample = None
    for f in failing:
        if f["msgs"]:
            sample = _condense_error(f["msgs"][0])
            break
        sample = _stderr_error_sample(f["rec"], collected)
        if sample:
            break
    out = {
        "passed": sum(1 for r in per_seed if r["status"] == "passed"),
        "failed": sum(1 for r in per_seed if r["status"] == "failed"),
        "failing_seeds": sorted([f["seed"] for f in failing if f["seed"] is not None]),
        "failure_class": failure_class,
        "sample_error_message": sample,
        "per_seed": per_seed,
    }
    return out


# --- 7. etcd-v2-quota-correlation.csv ----------------------------------------


def _quota_backend_bytes(rec: Dict[str, Any]) -> Optional[int]:
    result = _role_result(rec, "etcd")
    return _int_at(result, "services", "etcd", "extraConf", "QUOTA_BACKEND_BYTES")


def analyze_etcd_v2_quota_correlation(collected: Collected) -> List[List[Any]]:
    agg: Dict[int, List[int]] = {}
    for rec in _units(collected, "etcd-v2-sweep"):
        if _rep(rec) != 0:
            continue
        quota = _quota_backend_bytes(rec)
        if quota is None:
            continue
        cell = agg.setdefault(quota, [0, 0])
        if _verdict(rec) == "passed":
            cell[0] += 1
        else:
            cell[1] += 1
    rows = [[q, agg[q][0], agg[q][1], agg[q][0] + agg[q][1]] for q in sorted(agg)]
    _write_csv(
        collected,
        "etcd-v2-quota-correlation.csv",
        ["quota_backend_bytes", "passed", "failed", "total"],
        rows,
    )
    return rows


# --- 8. etcd-v2-shrink.json --------------------------------------------------


def _etcd_resolved_config(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    resolved = rec.get("resolved")
    if not isinstance(resolved, dict):
        return None
    result = _role_result(rec, "etcd")
    if not result:
        return None
    extra = result.get("services", {}).get("etcd", {}).get("extraConf", {})
    virt = result.get("virtualisation", {})
    roles = resolved.get("topology", {}).get("roles", {})
    return {
        "roles_etcd": roles.get("etcd"),
        "election_timeout_ms": _int_at(extra, "ELECTION_TIMEOUT"),
        "heartbeat_interval_ms": _int_at(extra, "HEARTBEAT_INTERVAL"),
        "quota_backend_bytes": _int_at(extra, "QUOTA_BACKEND_BYTES"),
        "snapshot_count": _int_at(extra, "SNAPSHOT_COUNT"),
        "disk_size": virt.get("diskSize"),
        "memory_size": virt.get("memorySize"),
    }


def analyze_etcd_v2_shrink(collected: Collected) -> Dict[str, Any]:
    seeds: Dict[str, Any] = {}
    for rec in sorted(
        _units(collected, "etcd-v2-shrink"),
        key=lambda r: (_meta(r, "seed") is None, _meta(r, "seed")),
    ):
        seed = _meta(rec, "seed")
        final = _etcd_resolved_config(rec) or _shrink_final_choices(rec)
        passed, failed, total = _summary(rec)
        seeds[str(seed)] = {
            "final_config": final,
            "passed": passed,
            "failed": failed,
            "total": total,
            "trials": _trial_table(rec),
        }
    keys = sorted(k for k in seeds if seeds[k]["final_config"] is not None)
    if len(keys) >= 2:
        identical = all(seeds[k]["final_config"] == seeds[keys[0]]["final_config"] for k in keys)
    else:
        identical = None
    out = {"seeds": seeds, "identical_minimal_config": identical}
    _write_json(collected, "etcd-v2-shrink.json", out)
    return out


# --- 9. etcd-v2-exhaustive.{json,csv} ----------------------------------------

QUOTA_PATH = ".services.etcd.extraConf.QUOTA_BACKEND_BYTES"


def _exhaustive_config(rec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The cell's own FORCED choice map (choices.json), not the seed's draw.

    An exhaustive cell is pinned by --config-choices; the seed plays no part.
    resolved.json still reports roleFuzz.<role>.choices as the choices the
    SEED would have drawn, so preferring that made all 96 cells report one
    identical config map — and attributed every failure to whichever quota
    index the seed happened to pick."""
    ch = rec.get("choices")
    if isinstance(ch, dict):
        role = ch.get("configChoices") or ch.get("config") or {}
        if isinstance(role, dict) and isinstance(role.get("etcd"), dict):
            return dict(role["etcd"])
    choices = _resolve_role(rec, "etcd").get("choices")
    if isinstance(choices, dict):
        return dict(choices)
    return None


def _exhaustive_quota_bytes(rec: Dict[str, Any]) -> Optional[int]:
    """The quota the cell actually ran with, in bytes, from the resolved
    config — an index alone says nothing without the dimension's value list."""
    return _int_at(
        _role_result(rec, "etcd"),
        "services",
        "etcd",
        "extraConf",
        "QUOTA_BACKEND_BYTES",
    )


def _exhaustive_outcome(rec: Dict[str, Any]) -> str:
    """passed | property-failed | no-property-verdict.

    Only a property verdict says anything about a cell's configuration.  A
    cell with no verdict at all (the CLI never started) or one where zero
    checks ran (e.g. the test driver's "Shell did not start in time") is a
    startup/infrastructure event — the distinction 06-evaluation.typ:221
    draws explicitly.  Counting such a cell as a failure attributed an
    infrastructure timeout at 8 MiB to the quota dimension."""
    verdict = _verdict(rec)
    _, _, total = _summary(rec)
    if verdict is None or total == 0:
        return "no-property-verdict"
    return "passed" if verdict == "passed" else "property-failed"


def analyze_etcd_v2_exhaustive(collected: Collected) -> Dict[str, Any]:
    per_cell = []
    failures_by_quota: Dict[int, int] = {}
    failures_by_quota_bytes: Dict[int, int] = {}
    cells_by_quota_bytes: Dict[int, int] = {}
    no_verdict_cells: List[str] = []
    passed = failed = 0
    for rec in sorted(
        _units(collected, "etcd-v2-exhaustive"),
        key=lambda r: (_meta(r, "variant_name") or "", _meta(r, "execution_index") or 0),
    ):
        cell = _meta(rec, "variant_name") or f"cell{_meta(rec, 'execution_index') or 0:03d}"
        config = _exhaustive_config(rec)
        quota_bytes = _exhaustive_quota_bytes(rec)
        verdict = _verdict(rec)
        outcome = _exhaustive_outcome(rec)
        _, _, checks_total = _summary(rec)
        if quota_bytes is not None:
            cells_by_quota_bytes[quota_bytes] = cells_by_quota_bytes.get(quota_bytes, 0) + 1
        if outcome == "passed":
            passed += 1
        elif outcome == "property-failed":
            failed += 1
            qidx = (config or {}).get(QUOTA_PATH)
            if qidx is not None:
                failures_by_quota[int(qidx)] = failures_by_quota.get(int(qidx), 0) + 1
            if quota_bytes is not None:
                failures_by_quota_bytes[quota_bytes] = (
                    failures_by_quota_bytes.get(quota_bytes, 0) + 1
                )
        else:
            no_verdict_cells.append(cell)
        per_cell.append(
            {
                "cell": cell,
                "config": config,
                "quota_backend_bytes": quota_bytes,
                "status": verdict,
                "outcome": outcome,
                "checks_total": checks_total,
            }
        )
    out = {
        "cells": len(per_cell),
        # passed / failed count PROPERTY verdicts only; cells that never
        # reached the property suite are listed separately below.
        "passed": passed,
        "failed": failed,
        "no_property_verdict": len(no_verdict_cells),
        "no_property_verdict_cells": no_verdict_cells,
        "failures_by_quota_index": {str(k): v for k, v in sorted(failures_by_quota.items())},
        # Indices mean nothing without the dimension's value list; the byte
        # values are what the thesis's quota finding is stated in.
        "cells_by_quota_bytes": {str(k): v for k, v in sorted(cells_by_quota_bytes.items())},
        "failures_by_quota_bytes": {str(k): v for k, v in sorted(failures_by_quota_bytes.items())},
        "per_cell": per_cell,
    }
    _write_json(collected, "etcd-v2-exhaustive.json", out)
    _write_csv(
        collected,
        "etcd-v2-exhaustive.csv",
        ["cell", "config", "quota_backend_bytes", "status", "outcome"],
        [
            [
                c["cell"],
                (
                    json.dumps(c["config"], sort_keys=True, separators=(",", ":"))
                    if c["config"] is not None
                    else ""
                ),
                c["quota_backend_bytes"],
                c["status"],
                c["outcome"],
            ]
            for c in per_cell
        ],
    )
    return out


# --- 10. rabbitmq-disk-cells.csv ---------------------------------------------


def analyze_rabbitmq_disk_cells(collected: Collected) -> List[List[Any]]:
    rows = []
    for rec in _units(collected, "rabbitmq-disk"):
        ev = _evidence(rec) or {}
        passed, failed, total = _summary(rec)
        failing = _failed_checks(rec)
        ops = [o for o in ev.get("operations", []) if isinstance(o, dict)]
        telemetry = [t for t in ev.get("telemetry", []) if isinstance(t, dict)]
        contract = ev.get("contract", {}) if isinstance(ev.get("contract"), dict) else {}
        rows.append(
            [
                _meta(rec, "variant_name"),
                _meta(rec, "execution_index"),
                _meta(rec, "seed"),
                _verdict(rec),
                passed,
                total,
                ";".join(sorted(failing)),
                sum(1 for o in ops if o.get("outcome") == "ambiguous"),
                sum(1 for t in telemetry if t.get("disk_free_alarm") is True),
                len(ev.get("recovered", []) or []),
                contract.get("capacity_sufficient"),
                contract.get("naive_capacity_sufficient"),
                # Cell-X configuration columns (claim r-02): the resolved
                # designed-cell parameters, straight from the evidence
                # contract block.
                contract.get("initial_free_target_mb"),
                contract.get("disk_free_limit_mb"),
                contract.get("planned_messages"),
                # contract stores the raw byte count; this column is
                # message_size_kib, so convert (bytes are always a whole
                # number of KiB for this target's payload sizing).
                (
                    contract.get("message_size") // 1024
                    if contract.get("message_size") is not None
                    else None
                ),
                contract.get("confirm_timeout_ms"),
                contract.get("capacity_safety_factor_milli"),
            ]
        )
    rows.sort(key=lambda r: (r[0] or "", r[1] if r[1] is not None else 0))
    header = [
        "variant",
        "execution_index",
        "seed",
        "status",
        "checks_passed",
        "checks_total",
        "failing_checks",
        "ambiguous_count",
        "alarm_samples",
        "recovered_count",
        "strict_sufficient",
        "naive_sufficient",
        "nominal_free_target_mb",
        "disk_free_limit_mb",
        "planned_messages",
        "message_size_kib",
        "confirm_timeout_ms",
        "safety_factor_milli",
    ]
    _write_csv(collected, "rabbitmq-disk-cells.csv", header, rows)
    return rows


# --- 11. rabbitmq-faildom-cells.csv ------------------------------------------


def analyze_rabbitmq_faildom_cells(collected: Collected) -> List[List[Any]]:
    rows = []
    for rec in _units(collected, "rabbitmq-faildom"):
        ev = _evidence(rec) or {}
        passed, _failed, total = _summary(rec)
        placement = ev.get("placement", {}) if isinstance(ev.get("placement"), dict) else {}
        placement_str = ";".join(f"{k}={placement[k]}" for k in sorted(placement))
        probe = ev.get("probe", {}) if isinstance(ev.get("probe"), dict) else {}
        rows.append(
            [
                _meta(rec, "variant_name"),
                _meta(rec, "execution_index"),
                placement_str,
                _verdict(rec),
                passed,
                total,
                len(ev.get("recovered", []) or []),
                (len(ev.get("baseline_ids", []) or []) + (1 if probe else 0)),
                probe.get("outcome"),
                ";".join(sorted(_failed_checks(rec))),
            ]
        )
    rows.sort(key=lambda r: (r[0] or "", r[1] if r[1] is not None else 0))
    header = [
        "variant",
        "execution_index",
        "placement",
        "status",
        "properties_passed",
        "properties_total",
        "operations_recovered",
        "operations_total",
        "probe_status",
        "failing_checks",
    ]
    _write_csv(collected, "rabbitmq-faildom-cells.csv", header, rows)
    return rows


# --- 12. rabbitmq-crash-cells.csv --------------------------------------------


def analyze_rabbitmq_crash_cells(collected: Collected) -> List[List[Any]]:
    rows = []
    for rec in _units(collected, "rabbitmq-crash"):
        ev = _evidence(rec) or {}
        passed, _failed, total = _summary(rec)
        ops = [o for o in ev.get("operations", []) if isinstance(o, dict)]
        qb = ev.get("queue_before", {}) if isinstance(ev.get("queue_before"), dict) else {}
        qa = ev.get("queue_after", {}) if isinstance(ev.get("queue_after"), dict) else {}
        rows.append(
            [
                _meta(rec, "variant_name"),
                _meta(rec, "execution_index"),
                _verdict(rec),
                passed,
                total,
                sum(1 for o in ops if o.get("outcome") == "confirmed"),
                sum(1 for o in ops if o.get("outcome") == "ambiguous"),
                _node_name(qb.get("leader")),
                _node_name(qa.get("leader")),
                ";".join(sorted(_failed_checks(rec))),
            ]
        )
    rows.sort(key=lambda r: (r[0] or "", r[1] if r[1] is not None else 0))
    header = [
        "variant",
        "execution_index",
        "status",
        "checks_passed",
        "checks_total",
        "confirmed_count",
        "ambiguous_count",
        "leader_before",
        "leader_after",
        "failing_checks",
    ]
    _write_csv(collected, "rabbitmq-crash-cells.csv", header, rows)
    return rows


# --- 13. determinism.json -----------------------------------------------------


def analyze_determinism(collected: Collected) -> Dict[str, Any]:
    specs = [
        ("kafka-sweep", kafka_failure_class),
        ("etcd-v1-sweep", etcd_v1_failure_class),
        ("etcd-v2-sweep", None),
    ]
    out: Dict[str, Any] = {}
    for entry, classify in specs:
        by_rep: Dict[int, Dict[Any, Dict[str, Any]]] = {}
        for rec in _units(collected, entry):
            rep = _rep(rec)
            seed = _meta(rec, "seed")
            failed = _failed_checks(rec)
            msgs = _failed_messages(rec)
            if classify is None:
                cls = (
                    etcd_v2_failure_class(failed[0] if failed else None, msgs[0] if msgs else None)
                    if failed
                    else None
                )
            else:
                cls = classify(msgs[0] if msgs else None) if failed else None
            by_rep.setdefault(rep, {})[seed] = {
                "status": _verdict(rec),
                "failure_class": cls,
            }
        rep0, rep1 = by_rep.get(0, {}), by_rep.get(1, {})
        if not rep0 or not rep1:
            out[entry] = {"present": False}
            continue
        diffs = []
        for seed in sorted(set(rep0) & set(rep1), key=lambda s: (s is None, s)):
            if rep0[seed] != rep1[seed]:
                diffs.append({"seed": seed, "rep0": rep0[seed], "rep1": rep1[seed]})
        out[entry] = {"present": True, "flips": len(diffs), "seed_diffs": diffs}
    _write_json(collected, "determinism.json", out)
    return out


# --- 14. test-suites.json -----------------------------------------------------


def _parse_python_suite(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"^Ran (\d+) tests?", text, re.M)
    if not m:
        return None
    ok = bool(re.search(r"^OK\b", text, re.M)) and "FAILED" not in text
    return {"ran": int(m.group(1)), "ok": ok}


def _parse_nix_suite(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"(\d+)/(\d+)\s*successful", text)
    if not m:
        return None
    n, total = int(m.group(1)), int(m.group(2))
    return {"successful": n, "total": total, "ok": n == total}


def analyze_test_suites(collected: Collected) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for rec in _units(collected, "test-suites"):
        variant = _meta(rec, "variant_name") or "default"
        text = (rec.get("stdout") or "") + "\n" + (rec.get("stderr") or "")
        if variant == "python" and "python" not in out:
            parsed = _parse_python_suite(text)
            if parsed:
                out["python"] = parsed
        elif variant == "nix" and "nix" not in out:
            parsed = _parse_nix_suite(text)
            if parsed:
                out["nix"] = parsed
    _write_json(collected, "test-suites.json", out)
    return out


# --- 15. stage-timing.json -----------------------------------------------------

_BOOT_RE = re.compile(
    r"\(finished: waiting for the VM to finish booting, in " r"([0-9.]+) seconds\)"
)
_SCRIPT_RE = re.compile(r"\(finished: must succeed.*?, in ([0-9.]+) seconds\)")


def _stage_timing_for_unit(rec: Dict[str, Any], collected: Collected) -> Dict[str, Any]:
    """Per-stage seconds, from timestamped sources only.

    The only per-stage *durations* anything emits are the VM driver's own
    "(finished: ..., in N seconds)" lines.  timing.json's stage information is
    positional (line indices in a log with no per-line timestamps — see
    runner._parse_log_phases), so it is deliberately NOT read here: doing so
    previously reported line counts as seconds (build_s 7233 inside a 222 s
    run, and a negative vm_boot_s).  nix_eval_s / build_s therefore stay null
    until a timestamped source for them exists."""
    # The driver's lines land in the VM console log under run-store/, not in
    # the wrapper CLI's own stdout — include both (log-digest.json stands in
    # for the console log when the gitignored *.log files are absent).
    text = (
        (rec.get("stdout") or "")
        + "\n"
        + (rec.get("stderr") or "")
        + "\n"
        + _final_trial_console_log(rec, collected)
    )
    boots = [float(m) for m in _BOOT_RE.findall(text)]
    script = [float(m) for m in _SCRIPT_RE.findall(text)]
    vals = {
        "nix_eval_s": None,
        "build_s": None,
        "vm_boot_s": max(boots) if boots else None,
        "test_script_s": sum(script) if script else None,
    }
    completeness = "full" if all(v is not None for v in vals.values()) else "partial"
    return {
        "unit": rec.get("id"),
        "entry": _meta(rec, "entry_id"),
        "seed": _meta(rec, "seed"),
        "variant": _meta(rec, "variant_name"),
        "nix_eval_s": vals["nix_eval_s"],
        "build_s": vals["build_s"],
        "vm_boot_s": vals["vm_boot_s"],
        "test_script_s": vals["test_script_s"],
        "source": "vm-driver-finished-lines",
        "completeness": completeness,
    }


def analyze_stage_timing(collected: Collected) -> List[Dict[str, Any]]:
    rows = sorted(
        (_stage_timing_for_unit(rec, collected) for rec in collected.units),
        key=lambda r: r["unit"] or "",
    )
    _write_json(
        collected,
        "stage-timing.json",
        {
            "note": (
                "vm_boot_s / test_script_s come from the VM driver's own "
                "'(finished: ..., in N seconds)' lines. nix_eval_s and "
                "build_s are null: the nix build log has no per-line "
                "timestamps, so no honest duration can be derived from it."
            ),
            "units": rows,
        },
    )
    return rows


# --- 16. parallelism.json -----------------------------------------------------


def _wall_s(rec: Dict[str, Any]) -> Optional[float]:
    timing = rec.get("timing") if isinstance(rec.get("timing"), dict) else {}
    v = _first_key(timing, ("wall_s", "wall_seconds", "elapsed_s", "wallclock_s", "wall"))
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _unit_span(rec: Dict[str, Any]) -> Optional[Tuple[float, float, str]]:
    """(start, end, clock) for one unit, or None when untimed.

    Prefers the wall-clock epoch pair (comparable across processes); falls
    back to time.monotonic() readings, which are only comparable within one
    boot of one machine — the source is reported so a reader can judge."""
    timing = rec.get("timing") if isinstance(rec.get("timing"), dict) else {}
    wall = _wall_s(rec)
    start = _first_key(timing, ("started_epoch",))
    clock = "epoch"
    if start is None:
        start = _first_key(timing, ("started_monotonic_relative",))
        clock = "monotonic"
    if start is None or wall is None:
        return None
    try:
        start = float(start)
    except (TypeError, ValueError):
        return None
    end = _first_key(timing, ("finished_epoch",)) if clock == "epoch" else None
    try:
        end = float(end) if end is not None else start + wall
    except (TypeError, ValueError):
        end = start + wall
    return start, end, clock


def analyze_parallelism(collected: Collected) -> Dict[str, Any]:
    """Wall-clock span per group, never a sum of per-unit durations.

    Running units concurrently does not shrink the sum of their individual
    wall times (contention grows it), so a ratio of sums cannot measure
    parallel speedup — it previously reported parallel execution as 2.5x
    *slower*.  What parallelism actually compresses is the group's own
    wall-clock span: max(end) - min(start) over the group's units."""

    def group(entry: str) -> Dict[str, Any]:
        units = _units(collected, entry)
        spans = [s for s in (_unit_span(r) for r in units) if s is not None]
        clocks = sorted({c for _, _, c in spans})
        span_s = None
        if spans and len(clocks) == 1:
            span_s = round(max(e for _, e, _ in spans) - min(s for s, _, _ in spans), 3)
        walls = [w for w in (_wall_s(r) for r in units) if w is not None]
        return {
            "units": len(units),
            "timed_units": len(spans),
            "group_wall_s": span_s,
            "sum_unit_wall_s": round(sum(walls), 3) if walls else None,
            "clock": clocks[0] if len(clocks) == 1 else None,
        }

    serial = group("rabbitmq-disk-serial")
    parallel = group("rabbitmq-disk")
    parallel["jobs"] = None
    speedup: Optional[float] = None
    throughput_ratio: Optional[float] = None
    note = ""
    s_span, p_span = serial["group_wall_s"], parallel["group_wall_s"]
    if s_span and p_span:
        if serial["units"] == parallel["units"]:
            speedup = s_span / p_span
        else:
            note = (
                f"speedup left null: the groups run different unit counts "
                f"({serial['units']} serial vs {parallel['units']} parallel), "
                "so their spans are not a like-for-like comparison; "
                "throughput_ratio_per_unit compares units-per-second instead."
            )
        throughput_ratio = (parallel["units"] / p_span) / (serial["units"] / s_span)
    else:
        note = "spans unavailable: units carry no comparable start/end timestamps."
    out = {
        "serial": serial,
        "parallel": parallel,
        "speedup": speedup,
        "throughput_ratio_per_unit": throughput_ratio,
        "measure": "group wall-clock span (max end - min start), not a sum of unit wall times",
        "note": note,
    }
    _write_json(collected, "parallelism.json", out)
    return out


# --- 17. execution-accounting.{json,csv} --------------------------------------


def _resource(rec: Dict[str, Any], key: str) -> Optional[float]:
    res = rec.get("resources") if isinstance(rec.get("resources"), dict) else {}
    v = _first_key(res, (key,))
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _peak_rss_bytes(rec: Dict[str, Any]) -> Optional[int]:
    """Peak RSS in bytes as an int (RSS is a byte count; keep exact)."""
    res = rec.get("resources") if isinstance(rec.get("resources"), dict) else {}
    v = _first_key(res, ("peak_rss_bytes", "max_rss_bytes", "peak_rss"))
    if v is not None:
        return int(float(v))
    kb = _first_key(res, ("peak_rss_kb", "max_rss_kb"))
    if kb is not None:
        return int(float(kb) * 1024.0)
    mb = _first_key(res, ("peak_rss_mb", "max_rss_mb"))
    if mb is not None:
        return int(float(mb) * 1048576.0)
    return None


def _execution_kind(rec: Dict[str, Any]) -> Optional[str]:
    nb = rec.get("nix-build") if isinstance(rec.get("nix-build"), dict) else {}
    v = _first_key(nb, ("execution", "mode", "state", "outcome"))
    if isinstance(v, str):
        return v
    fresh = _first_key(nb, ("fresh",))
    if isinstance(fresh, bool):
        return "fresh" if fresh else "cache-replay"
    return None


def _execution_kinds(rec: Dict[str, Any]) -> List[str]:
    """One execution label per actual VM execution the unit performed.

    A run/sweep/exhaustive unit performed exactly one (record["nix-build"]).
    A shrink unit's internal search performs one per candidate tried
    (record["trials"], from runner.py's per-trial classification) — counting
    all of them, not just the kept candidate, is what makes "actual VM
    execution count" correct for shrink groups instead of undercounting a
    12-candidate loop as 1."""
    trials = rec.get("trials")
    if isinstance(trials, list) and trials:
        kinds = [t.get("execution") for t in trials if isinstance(t, dict) and t.get("execution")]
        if kinds:
            return kinds
    kind = _execution_kind(rec)
    return [kind] if kind else []


def _space_size(collected: Collected, target: Optional[str]) -> Optional[int]:
    if not target:
        return None
    block = collected.resolution.get(target, {})
    uniq = _first_key(block, ("uniqueness.json",))
    if isinstance(uniq, dict):
        v = _first_key(
            uniq,
            (
                "space_size",
                "theoretical_space_size",
                "total_combinations",
                "combinations",
                "space",
                "num_configurations",
                "total",
            ),
        )
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    return None


_ACCOUNTING_GROUPS: List[Tuple[str, Tuple[str, ...], Optional[str]]] = [
    ("kafka-cluster", ("kafka-sweep", "kafka-shrink", "kafka-min-configs"), "kafka-cluster"),
    ("etcd-cluster-v1", ("etcd-v1-sweep",), "etcd-cluster-v1"),
    ("etcd-cluster", ("etcd-v2-sweep", "etcd-v2-shrink", "etcd-v2-exhaustive"), "etcd-cluster"),
    ("rabbitmq-disk", ("rabbitmq-disk",), "rabbitmq-disk"),
    ("rabbitmq-disk-serial", ("rabbitmq-disk-serial",), "rabbitmq-disk"),
    ("rabbitmq-faildom", ("rabbitmq-faildom",), "rabbitmq-failure-domain"),
    ("rabbitmq-crash", ("rabbitmq-crash",), "rabbitmq-crash"),
    ("test-suites", ("test-suites",), None),
]


def _group_accounting(
    collected: Collected, name: str, entries: Tuple[str, ...], target: Optional[str]
) -> Dict[str, Any]:
    recs = [r for e in entries for r in _units(collected, e)]
    walls = [w for w in (_wall_s(r) for r in recs) if w is not None]
    compute_hours: Optional[float] = None
    contrib = []
    for r in recs:
        w = _wall_s(r)
        c = _resource(r, "cpu_seconds")
        if w and c is not None and w > 0:
            contrib.append(c)
    if contrib:
        compute_hours = sum(contrib) / 3600.0
    rss = [v for v in (_peak_rss_bytes(r) for r in recs) if v is not None]
    executions = [k for r in recs for k in _execution_kinds(r)]
    seeds = sorted({s for s in (_meta(r, "seed") for r in recs) if s is not None})
    return {
        "target": target,
        "entries": list(entries),
        "space_size": _space_size(collected, target),
        "units": len(recs),
        "seeds": len(seeds),
        "fresh": sum(1 for k in executions if k == "fresh"),
        "substituted": sum(1 for k in executions if k == "substituted"),
        "cache_replay": sum(1 for k in executions if k == "cache-replay"),
        "execution_unknown": sum(
            1 for k in executions if k not in ("fresh", "substituted", "cache-replay")
        ),
        "wall_total_s": sum(walls) if walls else None,
        "wall_mean_s": (sum(walls) / len(walls)) if walls else None,
        "peak_rss_max_bytes": max(rss) if rss else None,
        "compute_hours": compute_hours,
        "wall_per_unit": sorted(
            [{"unit": r.get("id"), "wall_s": _wall_s(r)} for r in recs if _wall_s(r) is not None],
            key=lambda x: x["unit"] or "",
        ),
    }


def analyze_execution_accounting(collected: Collected) -> Dict[str, Any]:
    groups: Dict[str, Dict[str, Any]] = {}
    for name, entries, target in _ACCOUNTING_GROUPS:
        groups[name] = _group_accounting(collected, name, entries, target)
    totals = {
        "groups": len(groups),
        "units": sum(g["units"] for g in groups.values()),
        "fresh": sum(g["fresh"] for g in groups.values()),
        "cache_replay": sum(g["cache_replay"] for g in groups.values()),
        "execution_unknown": sum(g["execution_unknown"] for g in groups.values()),
        "wall_total_s": sum(
            g["wall_total_s"] for g in groups.values() if g["wall_total_s"] is not None
        ),
        "compute_hours": sum(
            g["compute_hours"] for g in groups.values() if g["compute_hours"] is not None
        ),
        "peak_rss_max_bytes": max(
            (
                g["peak_rss_max_bytes"]
                for g in groups.values()
                if g["peak_rss_max_bytes"] is not None
            ),
            default=None,
        ),
    }
    out = {"groups": groups, "totals": totals}
    _write_json(collected, "execution-accounting.json", out)
    header = [
        "group",
        "units",
        "seeds",
        "fresh",
        "cache_replay",
        "wall_total_s",
        "compute_hours",
        "peak_rss_max_bytes",
        "space_size",
    ]
    rows = [
        [
            name,
            g["units"],
            g["seeds"],
            g["fresh"],
            g["cache_replay"],
            g["wall_total_s"],
            g["compute_hours"],
            g["peak_rss_max_bytes"],
            g["space_size"],
        ]
        for name, g in sorted(groups.items())
    ]
    _write_csv(collected, "execution-accounting.csv", header, rows)
    return out


# --- entry point ---------------------------------------------------------------


def run_all(out_dir: Path, collected: Collected) -> None:
    """Write every analysis artifact. Pure in (raw/, resolution/); safe to re-run.

    Entry-scoped artifacts are only written when their entry actually has
    collected units — an empty campaign tree must yield "not-reproduced"
    in verification, not a fake 0/0 aggregate that reads as a mismatch."""
    collected.out_dir = Path(out_dir)
    # Deterministic cleanup: artifacts from a previous (partial) analysis
    # must never survive into the next run — a not-yet-executed entry has to
    # be ABSENT (verify: not-reproduced), not a stale 0/0 aggregate.
    analysis_dir = Path(out_dir) / "analysis"
    if analysis_dir.is_dir():
        for name in sorted(os.listdir(analysis_dir)):
            if name.endswith(".json") or name.endswith(".csv") or name.endswith(".tmp"):
                os.unlink(analysis_dir / name)
    has = collected.by_entry.get

    def units_of(entry: str) -> bool:
        return bool(has(entry))

    if units_of("kafka-sweep"):
        analyze_kafka_sweep(collected)
        analyze_kafka_crosstab(collected)
    if units_of("kafka-shrink"):
        analyze_kafka_shrink(collected)
    if units_of("kafka-min-configs"):
        analyze_kafka_min_configs(collected)
    if units_of("etcd-v1-sweep"):
        analyze_etcd_v1_sweep(collected)
    if units_of("etcd-v2-sweep"):
        analyze_etcd_v2_sweep(collected)
        analyze_etcd_v2_quota_correlation(collected)
    if units_of("etcd-v2-shrink"):
        analyze_etcd_v2_shrink(collected)
    if units_of("etcd-v2-exhaustive"):
        analyze_etcd_v2_exhaustive(collected)
    if units_of("rabbitmq-disk"):
        analyze_rabbitmq_disk_cells(collected)
    if units_of("rabbitmq-faildom"):
        analyze_rabbitmq_faildom_cells(collected)
    if units_of("rabbitmq-crash"):
        analyze_rabbitmq_crash_cells(collected)
    if units_of("kafka-sweep") or units_of("etcd-v1-sweep") or units_of("etcd-v2-sweep"):
        analyze_determinism(collected)
    if units_of("test-suites"):
        analyze_test_suites(collected)
    if units_of("kafka-sweep") or units_of("etcd-v2-sweep"):
        analyze_stage_timing(collected)
    if units_of("rabbitmq-disk"):
        analyze_parallelism(collected)
    if any(
        units_of(e)
        for e in (
            "kafka-sweep",
            "kafka-shrink",
            "kafka-min-configs",
            "etcd-v1-sweep",
            "etcd-v2-sweep",
            "etcd-v2-shrink",
            "etcd-v2-exhaustive",
            "rabbitmq-disk",
            "rabbitmq-faildom",
            "rabbitmq-crash",
            "rabbitmq-disk-serial",
            "test-suites",
        )
    ):
        analyze_execution_accounting(collected)
