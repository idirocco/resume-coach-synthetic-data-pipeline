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
    "Hallucination detection",
    "Awkward language",
)


def discover_latest_run(output_dir=OUTPUT_DIR, only=None):
    if only not in {None, "jobs", "resumes", "pairs"}:
        raise ValueError(f"unknown validation selection: {only}")
    latest_by_kind = {}
    for path in Path(output_dir).glob("*.jsonl"):
        match = SOURCE_FILE_PATTERN.fullmatch(path.name)
        if match:
            kind, timestamp = match.groups()
            current = latest_by_kind.get(kind)
            if current is None or timestamp > current[0]:
                latest_by_kind[kind] = (timestamp, path)
    required = {
        None: ("jobs", "resumes", "pairs"),
        "jobs": ("jobs",),
        "resumes": ("jobs", "resumes"),
        "pairs": ("jobs", "resumes", "pairs"),
    }[only]
    selected = {}
    for kind in required:
        if kind not in latest_by_kind:
            selection = only or "all"
            raise FileNotFoundError(f"No {kind} JSONL file found for {selection} validation in {output_dir}")
        selected[kind] = latest_by_kind[kind]
    source_timestamp = max(timestamp for timestamp, _ in selected.values())
    return {
        "source_timestamp": source_timestamp,
        **{kind: path for kind, (_, path) in selected.items()},
    }


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
    if error_type == "hallucination_detected":
        return "Hallucination detection"
    if error_type == "awkward_language_detected":
        return "Awkward language"
    if error_type in {"job_description_rules", "value_error"} or any(
        field in location for field in ("experience_years", "gpa", "end_date", "fit_level", "trace_id")
    ):
        return "Logical inconsistencies"
    return "Logical inconsistencies"


def _field_for_error(error):
    location = error.get("loc", ())
    return ".".join(str(part) for part in location) or "<record>"


BUZZWORD_PATTERNS = (
    "synergy",
    "thinking outside the box",
    "move the needle",
    "leverage",
    "paradigm shift",
    "circle back",
    "deep dive",
    "game changer",
    "value proposition",
    "thought leader",
    "holistic",
    "best in class",
    "bandwidth",
    "stakeholder management",
    "innovation strategy",
)


def _resume_text(resume):
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()
    if not isinstance(resume, dict):
        return ""
    chunks = []
    for key in ("title", "description", "responsibilities"):
        value = resume.get(key)
        if isinstance(value, str):
            chunks.append(value)
        elif isinstance(value, list):
            chunks.extend(str(item) for item in value if isinstance(item, str))
    for entry in resume.get("experience", []) or []:
        if isinstance(entry, dict):
            for key in ("title", "responsibilities", "achievements"):
                value = entry.get(key)
                if isinstance(value, list):
                    chunks.extend(str(item) for item in value if isinstance(item, str))
                elif isinstance(value, str):
                    chunks.append(value)
    for skill in resume.get("skills", []) or []:
        if isinstance(skill, dict):
            chunks.append(str(skill.get("name", "")))
            chunks.append(str(skill.get("proficiency_level", "")))
    return " ".join(chunks)


def detect_hallucination(resume):
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()
    if not isinstance(resume, dict):
        return []

    issues = []
    skills = resume.get("skills", []) or []
    expert_count = sum(
        1
        for skill in skills
        if isinstance(skill, dict) and str(skill.get("proficiency_level", "")).lower() == "expert"
    )
    total_skills = len(skills)
    if total_skills >= 30 and expert_count >= max(10, total_skills // 2):
        issues.append(
            {
                "type": "hallucination_detected",
                "loc": ["skills"],
                "msg": "Resume lists an implausibly large set of expert-level skills for one person.",
            }
        )

    experience = resume.get("experience", []) or []
    total_years = 0.0
    employment_periods = []
    for entry in experience:
        if not isinstance(entry, dict):
            continue
        start = entry.get("start_date")
        end = entry.get("end_date")
        if start:
            try:
                start_date = datetime.fromisoformat(start)
            except ValueError:
                start_date = None
            if start_date is not None:
                end_date = None
                if end:
                    try:
                        end_date = datetime.fromisoformat(end)
                    except ValueError:
                        end_date = None
                employment_periods.append(
                    (start_date.date(), end_date.date() if end_date else datetime.now(timezone.utc).date())
                )
        if end:
            try:
                parsed_end_date = datetime.fromisoformat(end)
            except ValueError:
                parsed_end_date = None
            if parsed_end_date is not None and start and start_date is not None:
                total_years += max(0.0, (parsed_end_date - start_date).days / 365.25)
    if total_years < 2 and expert_count >= 10:
        issues.append(
            {
                "type": "hallucination_detected",
                "loc": ["skills"],
                "msg": "Entry-level experience is claiming an implausibly high number of expert skills.",
            }
        )

    employment_periods.sort(key=lambda period: period[0])
    if any(
        next_start <= previous_end
        for (_, previous_end), (next_start, _) in zip(employment_periods, employment_periods[1:])
    ):
        issues.append(
            {
                "type": "hallucination_detected",
                "loc": ["experience"],
                "msg": "Resume shows overlapping or impossible work timelines.",
            }
        )

    text = _resume_text(resume).lower()
    if re.search(r"\b(?:expert|certified)\s+(?:in|across)\s+(?:all|everything|every(?:thing)?)\b", text):
        issues.append(
            {
                "type": "hallucination_detected",
                "loc": ["skills"],
                "msg": "Resume uses absolutes like 'expert in all' or 'certified in everything'.",
            }
        )

    return issues


def detect_awkward_language(resume):
    if hasattr(resume, "model_dump"):
        resume = resume.model_dump()
    if not isinstance(resume, dict):
        return []

    text = _resume_text(resume)
    lowered = text.lower()
    issues = []
    buzzword_hits = [term for term in BUZZWORD_PATTERNS if term in lowered]
    if buzzword_hits:
        issues.append(
            {
                "type": "awkward_language_detected",
                "loc": ["experience"],
                "msg": "Resume contains corporate buzzwords or AI-like jargon: " + ", ".join(buzzword_hits[:5]),
            }
        )

    words = re.findall(r"[a-zA-Z']+", lowered)
    for index in range(len(words) - 2):
        if words[index] == words[index + 1] == words[index + 2]:
            issues.append(
                {
                    "type": "awkward_language_detected",
                    "loc": ["experience"],
                    "msg": "Resume repeats the same word three times in close proximity.",
                }
            )
            break

    if len(buzzword_hits) > 5:
        issues.append(
            {
                "type": "awkward_language_detected",
                "loc": ["experience"],
                "msg": "Buzzword density is too high for a believable resume summary.",
            }
        )

    return issues


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


def _add_blocked(blocked, entry, record_type, reason, blocked_by):
    blocked.append(
        {
            "record_type": record_type,
            "source_file": entry["source_file"],
            "line_number": entry["line_number"],
            "raw_record": entry["raw_record"],
            "reason": reason,
            "blocked_by": blocked_by,
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
    job_trace_counts = Counter()
    for entry in entries:
        row = entry["data"]
        job, _, _, _ = _job_parts(row)
        metadata = job.get("metadata") if isinstance(job, dict) else None
        trace_id = metadata.get("trace_id") if isinstance(metadata, dict) else None
        if isinstance(trace_id, str):
            job_trace_counts[trace_id] += 1

        if entry["errors"]:
            _add_invalid(invalid, entry, "job", entry["errors"])
            continue
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

    duplicate_ids = {
        trace_id for trace_id, count in job_trace_counts.items() if count > 1
    }
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
    invalid_job_trace_ids = set(job_trace_counts) - set(skills_by_job_trace)
    return skills_by_job_trace, invalid_job_trace_ids


def _resume_parts(row):
    if not isinstance(row, dict):
        return None, None, None
    metadata = row.get("metadata")
    if not isinstance(metadata, dict):
        return None, None, None
    return metadata.get("trace_id"), metadata.get("job_trace_id"), metadata.get("fit_level")


def _validate_resume_entries(entries, skills_by_job_trace, invalid_job_trace_ids, valid, invalid, blocked):
    resumes_by_trace = {}
    resume_trace_entries = defaultdict(list)
    pending_valid = []
    pending_blocked = []
    invalid_resume_trace_ids = set()
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

        if isinstance(job_trace_id, str) and job_trace_id in invalid_job_trace_ids:
            try:
                parsed = parse_resume(row, required_skills=[], fit_level=None)
            except ValidationError as exc:
                _add_invalid(invalid, entry, "resume", _validation_errors(exc))
                if isinstance(resume_trace_id, str):
                    invalid_resume_trace_ids.add(resume_trace_id)
            else:
                pending_blocked.append((entry, parsed.model_dump(), resume_trace_id, job_trace_id))
            continue

        errors = []
        valid_job_reference = (
            isinstance(job_trace_id, str) and job_trace_id in skills_by_job_trace
        )
        if not valid_job_reference:
            errors.append(
                {
                    "type": "value_error",
                    "loc": ["metadata", "job_trace_id"],
                    "msg": "resume references a missing, invalid, or ambiguous job",
                }
            )
        required_skills = skills_by_job_trace.get(job_trace_id, []) if valid_job_reference else []
        try:
            parsed = parse_resume(
                row,
                required_skills=required_skills,
                fit_level=fit_level if valid_job_reference else None,
            )
        except ValidationError as exc:
            errors.extend(_validation_errors(exc))
        if errors:
            _add_invalid(invalid, entry, "resume", errors)
            if isinstance(resume_trace_id, str):
                invalid_resume_trace_ids.add(resume_trace_id)
        else:
            quality_errors = detect_hallucination(parsed.model_dump()) + detect_awkward_language(parsed.model_dump())
            if quality_errors:
                _add_invalid(
                    invalid,
                    entry,
                    "resume",
                    [
                        {"type": issue["type"], "loc": issue.get("loc", []), "msg": issue["msg"]}
                        for issue in quality_errors
                    ],
                )
                if isinstance(resume_trace_id, str):
                    invalid_resume_trace_ids.add(resume_trace_id)
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
            if isinstance(trace_id, str):
                invalid_resume_trace_ids.add(trace_id)
        elif errors:
            _add_invalid(invalid, entry, "resume", errors)
        else:
            _valid_record(valid, entry, "resume", parsed_resume)
            resumes_by_trace[trace_id] = parsed_resume
    for entry, parsed_resume, trace_id, job_trace_id in pending_blocked:
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
            if isinstance(trace_id, str):
                invalid_resume_trace_ids.add(trace_id)
        else:
            _add_blocked(
                blocked,
                entry,
                "resume",
                "resume references a job that failed validation",
                [{"record_type": "job", "trace_id": job_trace_id}],
            )
    blocked_resume_trace_ids = {
        trace_id
        for entry, _, trace_id, _ in pending_blocked
        if isinstance(trace_id, str) and trace_id not in invalid_resume_trace_ids
    }
    return resumes_by_trace, invalid_resume_trace_ids, blocked_resume_trace_ids


def _validate_pair_entries(
    entries,
    valid,
    invalid,
    blocked,
    jobs_by_trace,
    resumes_by_trace,
    invalid_job_trace_ids,
    invalid_resume_trace_ids,
    blocked_resume_trace_ids,
):
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

        blocked_by = []
        if pair.job_trace_id in invalid_job_trace_ids:
            blocked_by.append({"record_type": "job", "trace_id": pair.job_trace_id})
        if pair.resume_trace_id in invalid_resume_trace_ids:
            blocked_by.append({"record_type": "resume", "trace_id": pair.resume_trace_id})
        elif pair.resume_trace_id in blocked_resume_trace_ids:
            blocked_by.append({"record_type": "resume", "trace_id": pair.resume_trace_id})
        if blocked_by:
            _add_blocked(
                blocked,
                entry,
                "pair",
                "pair references a job or resume that failed validation",
                blocked_by,
            )
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


def _failure_report(valid, invalid, blocked, source_files, validation_timestamp):
    invalid_count = len(invalid)
    blocked_count = len(blocked)
    total = len(valid) + invalid_count + blocked_count
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
            "blocked_records": blocked_count,
            "success_rate_percent": round((100 * len(valid) / total), 2) if total else 0.0,
            "success_rate_target_percent": 90,
        },
        "categories": categories,
        "invalid_records": invalid,
        "blocked_records": blocked,
    }


def validate_run(jobs_path=None, resumes_path=None, pairs_path=None, output_dir=OUTPUT_DIR, only=None):
    if only not in {None, "jobs", "resumes", "pairs"}:
        raise ValueError(f"unknown validation selection: {only}")
    required = {
        None: ("jobs", "resumes", "pairs"),
        "jobs": ("jobs",),
        "resumes": ("jobs", "resumes"),
        "pairs": ("jobs", "resumes", "pairs"),
    }[only]
    provided_paths = {"jobs": jobs_path, "resumes": resumes_path, "pairs": pairs_path}
    source_files = {}
    for kind in required:
        path = provided_paths[kind]
        if path is None or not Path(path).is_file():
            raise FileNotFoundError(f"Required {kind} source file not found: {path}")
        source_files[kind] = Path(path)

    job_entries = _read_jsonl(source_files["jobs"])
    resume_entries = _read_jsonl(source_files["resumes"]) if "resumes" in source_files else []
    pair_entries = _read_jsonl(source_files["pairs"]) if "pairs" in source_files else []
    valid = []
    invalid = []
    blocked = []
    job_valid = valid if only in {None, "jobs"} else []
    job_invalid = invalid if only in {None, "jobs"} else []
    skills_by_job_trace, invalid_job_trace_ids = _validate_job_entries(job_entries, job_valid, job_invalid)
    jobs_by_trace = {
        record["data"]["job_description"]["metadata"]["trace_id"]: record["data"]["job_description"]
        for record in job_valid
        if record["record_type"] == "job"
    }
    resumes_by_trace = {}
    invalid_resume_trace_ids = set()
    blocked_resume_trace_ids = set()
    if "resumes" in source_files:
        resume_valid = valid if only in {None, "resumes"} else []
        resume_invalid = invalid if only in {None, "resumes"} else []
        resume_blocked = blocked if only in {None, "resumes"} else []
        resumes_by_trace, invalid_resume_trace_ids, blocked_resume_trace_ids = _validate_resume_entries(
            resume_entries,
            skills_by_job_trace,
            invalid_job_trace_ids,
            resume_valid,
            resume_invalid,
            resume_blocked,
        )
    if "pairs" in source_files:
        _validate_pair_entries(
            pair_entries,
            valid,
            invalid,
            blocked,
            jobs_by_trace,
            resumes_by_trace,
            invalid_job_trace_ids,
            invalid_resume_trace_ids,
            blocked_resume_trace_ids,
        )

    validation_timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    validated_path = output_dir / f"validated_data_{validation_timestamp}.json"
    invalid_path = output_dir / f"invalid_{validation_timestamp}.jsonl"
    failure_modes_path = output_dir / f"schema_failure_modes_{validation_timestamp}.json"
    report = _failure_report(valid, invalid, blocked, source_files, validation_timestamp)

    validated_path.write_text(json.dumps(valid, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with invalid_path.open("w", encoding="utf-8") as handle:
        for record in invalid:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    failure_modes_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"Validated {report['summary']['total_records']} records: "
        f"{report['summary']['valid_records']} valid, {report['summary']['invalid_records']} invalid, "
        f"{report['summary']['blocked_records']} blocked "
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


def validate_latest_run(output_dir=OUTPUT_DIR, only=None):
    inputs = discover_latest_run(output_dir, only=only)
    return validate_run(
        inputs.get("jobs"),
        inputs.get("resumes"),
        inputs.get("pairs"),
        output_dir,
        only=only,
    )
