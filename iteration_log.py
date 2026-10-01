import json
import re
from datetime import datetime, timezone
from pathlib import Path

from config import OUTPUT_DIR, ROOT


def _read_report(path):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _format_metric(report):
    summary = report["summary"]
    timestamp = report.get("validation_timestamp", "unknown timestamp")
    return f"{summary['success_rate_percent']}% success rate ({timestamp})"


def _delta(previous_rate, current_rate):
    change = round(current_rate - previous_rate, 2)
    if change > 0:
        direction = "Improvement"
    elif change < 0:
        direction = "Regression"
    else:
        direction = "No change"
    return f"{direction} of {abs(change):g} percentage points"


def append_iteration_log(current_report_path, output_dir=OUTPUT_DIR, log_path=None):
    current_report_path = Path(current_report_path)
    output_dir = Path(output_dir)
    log_path = Path(log_path or ROOT / "iteration_log.md")
    current_report = _read_report(current_report_path)
    if current_report is None:
        raise ValueError(f"Cannot read current validation report: {current_report_path}")

    source_types = set(current_report.get("source_files", {}))
    previous_reports = []
    for path in output_dir.glob("schema_failure_modes_*.json"):
        if path.resolve() == current_report_path.resolve():
            continue
        report = _read_report(path)
        if report is not None and set(report.get("source_files", {})) == source_types:
            previous_reports.append((report.get("validation_timestamp", ""), report))

    previous_report = max(previous_reports, key=lambda item: item[0])[1] if previous_reports else None
    if previous_report is None:
        before_metric = "Not measured"
        after_metric = _format_metric(current_report)
        delta = "Not measured; no previous comparable validation report"
    else:
        before_metric = _format_metric(previous_report)
        after_metric = _format_metric(current_report)
        delta = _delta(
            previous_report["summary"]["success_rate_percent"],
            current_report["summary"]["success_rate_percent"],
        )

    existing = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    prior_entries = re.findall(r"^## Iteration(?:\s+\d+|\s+Log Entry)\s*$", existing, re.MULTILINE)
    iteration = len(prior_entries) + 1
    kinds = ", ".join(sorted(source_types)) or "unknown sources"
    entry = (
        f"\n## Iteration {iteration}\n\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        f"| Date | {datetime.now(timezone.utc).date().isoformat()} |\n"
        "| Component | Validator |\n"
        f"| Change | Compared validation success rate for {kinds} using `--log` |\n"
        "| Reason | Not recorded |\n"
        f"| Before Metric | {before_metric} |\n"
        f"| After Metric | {after_metric} |\n"
        f"| Delta | {delta} |\n"
        "| Keep/Revert | Pending; a run comparison alone does not establish a code-change decision |\n"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(entry)
    print(f"Appended validation comparison to {log_path}")