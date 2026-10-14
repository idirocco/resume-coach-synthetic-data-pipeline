"""Correction loop: feed step 2 validation errors back to the LLM, re-validate, and track success."""

import json
import os
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from config import MAX_ATTEMPTS, MAX_CONCURRENT_REQUESTS, MODEL, OUTPUT_DIR, ROOT, TEMPERATURE
from correction import build_correction_prompt, error_context
from schemas import parse_job_description, parse_resume
from step2_validation import _category_for_error, _validation_errors, field_pattern, validate_run

SUCCESS_RATE_TARGET_PERCENT = 50
# Errors about ids and references are written by the pipeline, not the LLM; rewriting text cannot fix them.
NOT_CORRECTABLE_MESSAGES = ("not unique", "references a missing", "references a job")


def discover_latest_report(output_dir=OUTPUT_DIR):
    reports = sorted(Path(output_dir).glob("schema_failure_modes_*.json"))
    if not reports:
        raise FileNotFoundError(f"No step 2 report (schema_failure_modes_*.json) found in {output_dir}")
    return reports[-1]


def _make_client():
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENROUTER_API_KEY in the environment or a .env file.")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)


def _read_lines(path):
    return Path(path).read_text(encoding="utf-8").splitlines()


def _not_correctable_reason(record, row):
    if record["record_type"] == "pair":
        return "pair errors are id or fit-level mismatches between records"
    if not isinstance(row, dict):
        return "line is not a JSON object"
    for error in record["errors"]:
        if error["type"] == "json_decode":
            return "line is not valid JSON"
        if any(text in error["msg"] for text in NOT_CORRECTABLE_MESSAGES):
            return error["msg"]
        if record["record_type"] == "job" and (not error["loc"] or error["loc"][0] != "job_description"):
            return f"job row field {field_pattern(error['loc'])} is written by the pipeline"
    return None


def _job_errors(row, payload):
    """Validate a corrected job_description against the same context step 2 uses; errors are relative to it."""
    metadata = payload.get("metadata") if isinstance(payload, dict) else None
    try:
        parse_job_description(
            payload,
            industry=row.get("assigned_industry"),
            trace_id=metadata.get("trace_id") if isinstance(metadata, dict) else None,
            generated_at=metadata.get("generated_at") if isinstance(metadata, dict) else None,
            prompt_template=row.get("prompt_template"),
        )
    except ValidationError as exc:
        return _validation_errors(exc)
    return []


def _resume_errors(payload, required_skills):
    fit_level = (payload.get("metadata") or {}).get("fit_level") if required_skills else None
    try:
        parse_resume(payload, required_skills=required_skills, fit_level=fit_level)
    except ValidationError as exc:
        return _validation_errors(exc)
    return []


def _protect_job(original):
    """Restore the ids the pipeline assigned so the LLM cannot change a job's identity.

    When the original lost them, assign fresh ones the way step 1 does instead of keeping invented values.
    """
    original_metadata = original.get("metadata") if isinstance(original, dict) else None
    original_metadata = original_metadata if isinstance(original_metadata, dict) else {}
    ids = {
        "trace_id": original_metadata.get("trace_id") or f"jd-{uuid.uuid4()}",
        "generated_at": original_metadata.get("generated_at") or datetime.now(timezone.utc).isoformat(),
    }

    def protect(payload):
        if isinstance(payload.get("metadata"), dict):
            payload["metadata"].update(ids)
        return payload

    return protect


def _protect_resume(original):
    def protect(payload):
        if "metadata" in original:
            payload["metadata"] = original["metadata"]
        return payload

    return protect


def correct_record(client, original, errors, validate, protect, context=None, extra_instructions=None):
    """Up to MAX_ATTEMPTS correction turns. Returns (corrected payload or None, errors after each attempt)."""
    from step1_generation import parse_json_object

    prompt = build_correction_prompt(error_context(errors, original, context), original, extra_instructions)
    messages = [{"role": "user", "content": prompt}]
    attempt_errors = []
    for _ in range(MAX_ATTEMPTS):
        raw_response = ""
        try:
            response = client.chat.completions.create(
                model=MODEL,
                temperature=TEMPERATURE,
                messages=messages,
                response_format={"type": "json_object"},
            )
            raw_response = response.choices[0].message.content or ""
            payload = protect(parse_json_object(raw_response))
        except Exception as exc:
            errors = [{"type": "json_decode", "loc": [], "msg": str(exc)}]
            data = raw_response
        else:
            errors = validate(payload)
            data = payload
            if not errors:
                attempt_errors.append([])
                return payload, attempt_errors
        attempt_errors.append(errors)
        messages.append({"role": "assistant", "content": raw_response})
        messages.append(
            {
                "role": "user",
                "content": build_correction_prompt(error_context(errors, data, context), data, extra_instructions),
            }
        )
    return None, attempt_errors


def _categorized(errors):
    return [
        {"type": error["type"], "loc": error["loc"], "msg": error["msg"], "category": _category_for_error(error), "field": field_pattern(error["loc"])}
        for error in errors
    ]


def _log_entry(record, trace_id, outcome, attempt_errors=None, reason=None):
    attempt_errors = attempt_errors or []
    return {
        "record_type": record["record_type"],
        "trace_id": trace_id,
        "source_file": record["source_file"],
        "line_number": record["line_number"],
        "original_categories": sorted({error["category"] for error in record["errors"]}),
        "original_errors": [
            {key: error[key] for key in ("type", "loc", "msg", "category", "field") if key in error}
            for error in record["errors"]
        ],
        "outcome": outcome,
        "attempts": len(attempt_errors),
        "per_attempt_errors": [_categorized(errors) for errors in attempt_errors],
        "final_errors": _categorized(attempt_errors[-1]) if attempt_errors else [],
        "reason": reason,
    }


def _rate(corrected, attempted):
    return round(100 * corrected / attempted, 2) if attempted else 0.0


def _correction_report(log, pre_report, post_report, correction_timestamp):
    attempted = [entry for entry in log if entry["outcome"] != "not_correctable"]
    corrected = [entry for entry in attempted if entry["outcome"] == "corrected"]
    failed = [entry for entry in attempted if entry["outcome"] == "permanently_failed"]
    by_type = defaultdict(Counter)
    by_category = defaultdict(Counter)
    for entry in attempted:
        by_type[entry["record_type"]]["attempted"] += 1
        by_type[entry["record_type"]]["corrected"] += entry["outcome"] == "corrected"
        for category in entry["original_categories"]:
            by_category[category]["attempted"] += 1
            by_category[category]["corrected"] += entry["outcome"] == "corrected"
    failure_reasons = Counter(
        (error["field"], error["category"]) for entry in failed for error in entry["final_errors"]
    )
    pre_summary = pre_report["summary"]
    post_summary = post_report["summary"]
    return {
        "correction_timestamp": correction_timestamp,
        "pre_validation_timestamp": pre_report["validation_timestamp"],
        "post_validation_timestamp": post_report["validation_timestamp"],
        "model": MODEL,
        "max_attempts": MAX_ATTEMPTS,
        "summary": {
            "invalid_records": len(log),
            "attempted": len(attempted),
            "corrected": len(corrected),
            "permanently_failed": len(failed),
            "not_correctable": len(log) - len(attempted),
            "success_rate_percent": _rate(len(corrected), len(attempted)),
            "success_rate_target_percent": SUCCESS_RATE_TARGET_PERCENT,
            "avg_attempts_corrected": round(sum(e["attempts"] for e in corrected) / len(corrected), 2) if corrected else None,
            "avg_attempts_all": round(sum(e["attempts"] for e in attempted) / len(attempted), 2) if attempted else None,
            "pre_success_rate_percent": pre_summary["success_rate_percent"],
            "post_success_rate_percent": post_summary["success_rate_percent"],
            "unblocked_records": max(0, pre_summary["blocked_records"] - post_summary["blocked_records"]),
        },
        "corrected_by_attempt": {
            str(attempt): sum(1 for entry in corrected if entry["attempts"] == attempt)
            for attempt in range(1, MAX_ATTEMPTS + 1)
        },
        "by_record_type": {
            record_type: {**counts, "success_rate_percent": _rate(counts["corrected"], counts["attempted"])}
            for record_type, counts in sorted(by_type.items())
        },
        "by_category": {
            category: {**counts, "success_rate_percent": _rate(counts["corrected"], counts["attempted"])}
            for category, counts in sorted(by_category.items())
        },
        "top_failure_reasons": [
            {"field": field, "category": category, "count": count}
            for (field, category), count in failure_reasons.most_common(10)
        ],
        "not_correctable_reasons": dict(
            Counter(entry["reason"] for entry in log if entry["outcome"] == "not_correctable")
        ),
    }


def correct_run(report_path, output_dir=OUTPUT_DIR, client=None):
    report_path = Path(report_path)
    output_dir = Path(output_dir)
    pre_report = json.loads(report_path.read_text(encoding="utf-8"))
    sources = {kind: Path(path) for kind, path in pre_report["source_files"].items()}
    lines = {kind: _read_lines(path) for kind, path in sources.items() if kind in {"jobs", "resumes"}}

    log = []
    job_tasks = []
    resume_tasks = []
    for record in pre_report["invalid_records"]:
        try:
            row = json.loads(record["raw_record"])
        except json.JSONDecodeError:
            row = None
        reason = _not_correctable_reason(record, row)
        trace_holder = (row.get("job_description") if record["record_type"] == "job" else row) if isinstance(row, dict) else None
        metadata = trace_holder.get("metadata") if isinstance(trace_holder, dict) else None
        trace_id = metadata.get("trace_id") if isinstance(metadata, dict) else None
        if reason is not None:
            log.append(_log_entry(record, trace_id, "not_correctable", reason=reason))
        elif record["record_type"] == "job":
            job_tasks.append((record, row, trace_id))
        else:
            resume_tasks.append((record, row, trace_id))

    if job_tasks or resume_tasks:
        client = client or _make_client()

    def finish(record, trace_id, kind, payload, attempt_errors):
        outcome = "corrected" if payload is not None else "permanently_failed"
        log.append(_log_entry(record, trace_id, outcome, attempt_errors))
        if payload is not None:
            lines[kind][record["line_number"] - 1] = json.dumps(payload, ensure_ascii=False)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as executor:
        # Jobs first: corrected jobs supply the required skills their resumes are checked against.
        futures = []
        for record, row, trace_id in job_tasks:
            original = row["job_description"]
            errors = [{**error, "loc": error["loc"][1:]} for error in record["errors"]]
            futures.append(
                (
                    record,
                    row,
                    trace_id,
                    executor.submit(
                        correct_record,
                        client,
                        original,
                        errors,
                        lambda payload, row=row: _job_errors(row, payload),
                        _protect_job(original),
                    ),
                )
            )
        for record, row, trace_id, future in futures:
            payload, attempt_errors = future.result()
            finish(record, trace_id, "jobs", {**row, "job_description": payload} if payload is not None else None, attempt_errors)

        required_skills_by_job = {}
        for line in lines.get("jobs", []):
            try:
                job = json.loads(line)["job_description"]
                required_skills_by_job[job["metadata"]["trace_id"]] = job["requirements"]["required_skills"]
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        futures = []
        for record, row, trace_id in resume_tasks:
            job_trace_id = (row.get("metadata") or {}).get("job_trace_id")
            required_skills = required_skills_by_job.get(job_trace_id, [])
            context = {"required_skills": required_skills, "fit_level": (row.get("metadata") or {}).get("fit_level")}
            futures.append(
                (
                    record,
                    trace_id,
                    executor.submit(
                        correct_record,
                        client,
                        row,
                        record["errors"],
                        lambda payload, skills=required_skills: _resume_errors(payload, skills),
                        _protect_resume(row),
                        context,
                        "Keep the same fit level and writing style.",
                    ),
                )
            )
        for record, trace_id, future in futures:
            payload, attempt_errors = future.result()
            finish(record, trace_id, "resumes", payload, attempt_errors)

    correction_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    corrected_paths = {}
    for kind, kind_lines in lines.items():
        path = output_dir / f"corrected_{kind}_{correction_timestamp}.jsonl"
        path.write_text("".join(line + "\n" for line in kind_lines), encoding="utf-8")
        corrected_paths[kind] = path

    if any(entry["outcome"] == "corrected" for entry in log):
        only = None if "pairs" in sources else ("resumes" if "resumes" in sources else "jobs")
        validation = validate_run(
            corrected_paths["jobs"],
            corrected_paths.get("resumes"),
            sources.get("pairs"),
            output_dir,
            only=only,
        )
        post_report = validation["report"]
        post_report_path = validation["failure_modes_path"]
    else:
        print("No records were corrected; skipping re-validation.")
        post_report = pre_report
        post_report_path = report_path

    report = _correction_report(log, pre_report, post_report, correction_timestamp)
    log_path = output_dir / f"correction_log_{correction_timestamp}.jsonl"
    report_out = output_dir / f"correction_report_{correction_timestamp}.json"
    with log_path.open("w", encoding="utf-8") as handle:
        for entry in log:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    report_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = report["summary"]
    print(
        f"Corrected {summary['corrected']} of {summary['attempted']} correctable invalid records "
        f"({summary['success_rate_percent']}%, target >{SUCCESS_RATE_TARGET_PERCENT}%); "
        f"{summary['not_correctable']} not correctable."
    )
    print(f"Wrote correction log to {log_path}")
    print(f"Wrote correction report to {report_out}")
    return {
        "correction_log_path": log_path,
        "correction_report_path": report_out,
        "post_report_path": post_report_path,
        "report": report,
    }


def correct_latest_run(output_dir=OUTPUT_DIR, client=None):
    return correct_run(discover_latest_report(output_dir), output_dir, client)
