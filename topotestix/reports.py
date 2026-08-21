import json
import os
from typing import Any

ACCEPTED_STATUSES = frozenset({"passed", "expected_failure"})


def parse_report(result_path: str) -> list[dict[str, Any]]:
    report_path = os.path.join(result_path, "report.json")
    if not os.path.exists(report_path):
        return []
    with open(report_path) as f:
        return json.load(f)


def report_passed(report: list[dict[str, Any]]) -> bool:
    return bool(report) and all(entry.get("status") in ACCEPTED_STATUSES for entry in report)


def report_summary(report: list[dict[str, Any]]) -> dict[str, int]:
    passed = sum(1 for entry in report if entry.get("status") == "passed")
    failed = sum(1 for entry in report if entry.get("status") not in ACCEPTED_STATUSES)
    summary = {"passed": passed, "failed": failed, "total": len(report)}
    for status in ("expected_failure", "unexpected_pass"):
        count = sum(1 for entry in report if entry.get("status") == status)
        if count:
            summary[status] = count
    return summary


def read_report_path(path_or_run_dir: str) -> list[dict[str, Any]]:
    if os.path.isdir(path_or_run_dir):
        candidate = os.path.join(path_or_run_dir, "report.json")
    else:
        candidate = path_or_run_dir
    with open(candidate) as f:
        return json.load(f)
