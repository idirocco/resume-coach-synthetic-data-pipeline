import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from config import OUTPUT_DIR
from schemas import ResumeJobPair, parse_job_description, parse_resume

SOURCE_FILE_PATTERN = re.compile(r"^(jobs|resumes|pairs)_(\d{8}T\d{6}Z)\.jsonl$")
ERROR_CATEGORIES = (
    "Missing required fields",
    "Type mismatches",
    "Format violations",
    "Logical inconsistencies",
)


def discover_latest_run(output_dir=OUTPUT_DIR):
    runs = defaultdict(dict)
    for path in Path(output_dir).glob("*.jsonl"):
        match = SOURCE_FILE_PATTERN.fullmatch(path.name)
        if match:
            kind, timestamp = match.groups()
            runs[timestamp][kind] = path
    complete = [
        (timestamp, paths)
        for timestamp, paths in runs.items()
        if all(kind in paths for kind in ("jobs", "resumes", "pairs"))
    ]
    if not complete:
        raise FileNotFoundError(f"No complete jobs/resumes/pairs JSONL run found in {output_dir}")
    timestamp, paths = max(complete, key=lambda item: item[0])
    return {"source_timestamp": timestamp, **paths}


def _read_jsonl(path):
    entries = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            raw_record = raw_line.rstrip("\r\n")
            if not raw_record.strip():
                continue
            entry = {
                "source_file": str(path),
                "line_number": line_number,
                "raw_record": raw_record,
                "data": None,
                "errors": [],
            }
            try:
                entry["data"] = json.loads(raw_record)
            except json.JSONDecodeError as exc:
                entry["errors"] = [
                    {"type": "json_decode", "loc": [], "msg": str(exc)}
                ]
            entries.append(entry)
    return entries


def _validation_errors(exc, prefix=()):
    return [
        {
            "type": error["type"],
            "loc": [*prefix, *error["loc"]],
            "msg": error["msg"],
        }
        for error in exc.errors()
    ]


def _category_for_error(error):
    error_type = error.get("type", "")
    message = error.get("msg", "").lower()
    location = ".".join(str(part) for part in error.get("loc", ())).lower()
    if error_type == "missing":
        return "Missing required fields"
    if error_type.startswith("type_") or error_type.endswith("_type") or error_type in {
        "literal_error",
        "model_type",
        "dict_type",
        "extra_forbidden",
    }:
        return "Type mismatches"
    if (
        "email" in location
        or "date" in location
        or "iso" in message
        or "valid email" in message
        or error_type == "json_decode"
    ):
        return "Format violations"
    if error_type in {"job_description_rules", "value_error"} or any(
        field in location for field in ("experience_years", "gpa", "end_date", "fit_level", "trace_id")
    ):
        return "Logical inconsistencies"
    return "Logical inconsistencies"


def _field_for_error(error):
    location = error.get("loc", ())
    return ".".join(str(part) for part in location) or "<record>"


def _add_invalid(invalid, entry, record_type, errors):
    categorized_errors = [
        {**error, "category": _category_for_error(error)} for error in errors
    ]
    category_order = {category: index for index, category in enumerate(ERROR_CATEGORIES)}
    primary_category = min(
        (error["category"] for error in categorized_errors),
        key=category_order.__getitem__,
    )
    primary_error = next(
        error for error in categorized_errors if error["category"] == primary_category
    )
    invalid.append(
        {
            "record_type": record_type,
            "source_file": entry["source_file"],
            "line_number": entry["line_number"],
            "raw_record": entry["raw_record"],
            "category": primary_category,
            "field": _field_for_error(primary_error),
            "errors": categorized_errors,
        }
    )


def _valid_record(valid, entry, record_type, data):
    valid.append(
        {
            "record_type": record_type,
            "source_file": entry["source_file"],
            "line_number": entry["line_number"],
            "data": data,
        }
    )


def _job_parts(row):
    if not isinstance(row, dict):
        return None, None, None, None
    job = row.get("job_description")
    if not isinstance(job, dict):
        return job, None, None, None
    metadata = job.get("metadata")
    requirements = job.get("requirements")
    trace_id = metadata.get("trace_id") if isinstance(metadata, dict) else None
    generated_at = metadata.get("generated_at") if isinstance(metadata, dict) else None
    industry = row.get("assigned_industry")
    template = row.get("prompt_template")
    skills = requirements.get("required_skills") if isinstance(requirements, dict) else None
    return job, industry, template, (trace_id, generated_at, skills)


def _validate_job_entries(entries, valid, invalid):
    skills_by_job_trace = {}
    pending_valid = []
    for entry in entries:
        if entry["errors"]:
            _add_invalid(invalid, entry, "job", entry["errors"])
            continue
        row = entry["data"]
        if not isinstance(row, dict):
            _add_invalid(
                invalid,
                entry,
                "job",
                [{"type": "model_type", "loc": [], "msg": "job record must be an object"}],
            )
            continue
        missing = [
            key
            for key in ("index", "prompt_template", "assigned_industry", "model", "job_description")
            if key not in row
        ]
        errors = [
            {"type": "missing", "loc": [key], "msg": "Field required"}
            for key in missing
        ]
        for key in ("prompt_template", "assigned_industry", "model"):
            if key in row and not isinstance(row[key], str):
                errors.append({"type": "string_type", "loc": [key], "msg": "Input should be a valid string"})
        if "index" in row and type(row["index"]) is not int:
            errors.append({"type": "int_type", "loc": ["index"], "msg": "Input should be a valid integer"})

        job, industry, template, _ = _job_parts(row)

        if not isinstance(job, dict):
            errors.append(
                {
                    "type": "model_type",
                    "loc": ["job_description"],
                    "msg": "job_description must be an object",
                }
            )
        elif template is None or isinstance(template, str):
            metadata = job.get("metadata")
            trace_id = metadata.get("trace_id") if isinstance(metadata, dict) else None
            generated_at = metadata.get("generated_at") if isinstance(metadata, dict) else None
            try:
                parsed = parse_job_description(
                    job,
                    industry=industry,
                    trace_id=trace_id,
                    generated_at=generated_at,
                    prompt_template=template,
                )
                if not errors:
                    pending_valid.append((entry, row, parsed.model_dump(), errors))
            except ValidationError as exc:
                errors.extend(_validation_errors(exc, ("job_description",)))

        if errors:
            _add_invalid(invalid, entry, "job", errors)
        elif not isinstance(job, dict):
            _add_invalid(invalid, entry, "job", [{"type": "model_type", "loc": ["job_description"], "msg": "job_description must be an object"}])

    job_rows_by_trace = defaultdict(list)
    for entry, row, parsed_job, _ in pending_valid:
        job_rows_by_trace[parsed_job["metadata"]["trace_id"]].append((entry, row, parsed_job))
    duplicate_ids = {trace_id for trace_id, rows in job_rows_by_trace.items() if len(rows) > 1}
    for entry, row, parsed_job, errors in pending_valid:
        trace_id = parsed_job["metadata"]["trace_id"]
        if trace_id in duplicate_ids:
            _add_invalid(
                invalid,
                entry,
                "job",
                [
                    {
                        "type": "value_error",
                        "loc": ["job_description", "metadata", "trace_id"],
                        "msg": "job trace_id is not unique",
                    }
                ],
            )
        else:
            _valid_record(valid, entry, "job", {**row, "job_description": parsed_job})
            skills_by_job_trace[trace_id] = parsed_job["requirements"]["required_skills"]
    return skills_by_job_trace


def _resume_parts(row):
    if not isinstance(row, dict):
        return None, None, None
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return None, None, None
    return metadata.get("trace_id"), metadata.get("job_trace_id"), metadata.get("fit_level")


def _validate_resume_entries(entries, skills_by_job_trace, valid, invalid):
    resumes_by_trace = {}
    resume_trace_entries = defaultdict(list)
    pending_valid = []
    for entry in entries:
        if entry["errors"]:
            _add_invalid(invalid, entry, "resume", entry["errors"])
            continue
        row = entry["data"]
        if not isinstance(row, dict):
            _add_invalid(
                invalid,
                entry,
                "resume",
                [{"type": "model_type", "loc": [], "msg": "resume record must be an object"}],
            )
            continue
        resume_trace_id, job_trace_id, fit_level = _resume_parts(row)
        if isinstance(resume_trace_id, str):
            resume_trace_entries[resume_trace_id].append(entry)
        errors = []
        if not isinstance(job_trace_id, str) or job_trace_id not in skills_by_job_trace:
            errors.append(
                {
                    "type": "value_error",
                    "loc": ["metadata", "job_trace_id"],
                    "msg": "resume references a missing, invalid, or ambiguous job",
                }
            )
        required_skills = skills_by_job_trace.get(job_trace_id, [])
        try:
            parsed = parse_resume(row, required_skills=required_skills, fit_level=fit_level)
        except ValidationError as exc:
            errors.extend(_validation_errors(exc))
        if errors:
            _add_invalid(invalid, entry, "resume", errors)
        else:
            pending_valid.append((entry, parsed.model_dump(), errors, resume_trace_id))

    duplicate_ids = {trace_id for trace_id, rows in resume_trace_entries.items() if len(rows) > 1}
    for entry, parsed_resume, errors, trace_id in pending_valid:
        if trace_id in duplicate_ids:
            _add_invalid(
                invalid,
                entry,
                "resume",
                [
                    {
                        "type": "value_error",
                        "loc": ["metadata", "trace_id"],
                        "msg": "resume trace_id is not unique",
                    }
                ],
            )
        elif errors:
            _add_invalid(invalid, entry, "resume", errors)
        else:
            _valid_record(valid, entry, "resume", parsed_resume)
            resumes_by_trace[trace_id] = parsed_resume
    return resumes_by_trace


def _validate_pair_entries(entries, valid, invalid, jobs_by_trace, resumes_by_trace):
    for entry in entries:
        if entry["errors"]:
            _add_invalid(invalid, entry, "pair", entry["errors"])
            continue
        row = entry["data"]
        try:
            pair = ResumeJobPair.model_validate(row)
        except ValidationError as exc:
            _add_invalid(invalid, entry, "pair", _validation_errors(exc))
            continue

        errors = []
        job = jobs_by_trace.get(pair.job_trace_id)
        resume = resumes_by_trace.get(pair.resume_trace_id)
        if job is None:
            errors.append({"type": "value_error", "loc": ["job_trace_id"], "msg": "pair references a missing or invalid job"})
        if resume is None:
            errors.append({"type": "value_error", "loc": ["resume_trace_id"], "msg": "pair references a missing or invalid resume"})
        if resume is not None:
            metadata = resume["metadata"]
            if metadata["job_trace_id"] != pair.job_trace_id:
                errors.append({"type": "value_error", "loc": ["job_trace_id"], "msg": "pair job_trace_id does not match the resume"})
            if metadata["fit_level"] != pair.fit_level:
                errors.append({"type": "value_error", "loc": ["fit_level"], "msg": "pair fit_level does not match the resume"})
        if errors:
            _add_invalid(invalid, entry, "pair", errors)
        else:
            _valid_record(valid, entry, "pair", pair.model_dump())


def _failure_report(valid, invalid, source_files, validation_timestamp):
    invalid_count = len(invalid)
    total = len(valid) + invalid_count
    category_counts = Counter(record["category"] for record in invalid)
    category_fields = defaultdict(Counter)
    for record in invalid:
        for error in record["errors"]:
            if error["category"] == record["category"]:
                category_fields[record["category"]][_field_for_error(error)] += 1
    categories = {}
    for category in ERROR_CATEGORIES:
        count = category_counts[category]
        fields = category_fields[category]
        categories[category] = {
            "count": count,
            "percent_of_failures": round((100 * count / invalid_count), 2) if invalid_count else 0.0,
            "most_common_field": fields.most_common(1)[0][0] if fields else None,
        }
    return {
        "validation_timestamp": validation_timestamp,
        "source_files": {kind: str(path) for kind, path in source_files.items()},
        "summary": {
            "total_records": total,
            "valid_records": len(valid),
            "invalid_records": invalid_count,
            "success_rate_percent": round((100 * len(valid) / total), 2) if total else 0.0,
            "success_rate_target_percent": 90,
        },
        "categories": categories,
        "invalid_records": invalid,
    }


def validate_run(jobs_path, resumes_path, pairs_path, output_dir=OUTPUT_DIR):
    source_files = {
        "jobs": Path(jobs_path),
        "resumes": Path(resumes_path),
        "pairs": Path(pairs_path),
    }
    for path in source_files.values():
        if not path.is_file():
            raise FileNotFoundError(path)

    job_entries = _read_jsonl(source_files["jobs"])
    resume_entries = _read_jsonl(source_files["resumes"])
    pair_entries = _read_jsonl(source_files["pairs"])
    valid = []
    invalid = []
    skills_by_job_trace = _validate_job_entries(job_entries, valid, invalid)
    jobs_by_trace = {
        record["data"]["job_description"]["metadata"]["trace_id"]: record["data"]["job_description"]
        for record in valid
        if record["record_type"] == "job"
    }
    resumes_by_trace = _validate_resume_entries(resume_entries, skills_by_job_trace, valid, invalid)
    _validate_pair_entries(pair_entries, valid, invalid, jobs_by_trace, resumes_by_trace)

    validation_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    validated_path = output_dir / f"validated_data_{validation_timestamp}.json"
    invalid_path = output_dir / f"invalid_{validation_timestamp}.jsonl"
    failure_modes_path = output_dir / f"schema_failure_modes_{validation_timestamp}.json"
    report = _failure_report(valid, invalid, source_files, validation_timestamp)

    validated_path.write_text(json.dumps(valid, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with invalid_path.open("w", encoding="utf-8") as handle:
        for record in invalid:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    failure_modes_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"Validated {report['summary']['total_records']} records: "
        f"{report['summary']['valid_records']} valid, {report['summary']['invalid_records']} invalid "
        f"({report['summary']['success_rate_percent']}% success)."
    )
    print(f"Wrote validated records to {validated_path}")
    print(f"Wrote invalid records to {invalid_path}")
    print(f"Wrote failure analysis to {failure_modes_path}")
    return {
        "validated_path": validated_path,
        "invalid_path": invalid_path,
        "failure_modes_path": failure_modes_path,
        "report": report,
    }


def validate_latest_run(output_dir=OUTPUT_DIR):
    inputs = discover_latest_run(output_dir)
    return validate_run(inputs["jobs"], inputs["resumes"], inputs["pairs"], output_dir)
