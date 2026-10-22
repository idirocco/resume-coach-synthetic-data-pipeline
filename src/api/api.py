"""Step 5: REST API over the pipeline's analysis functions. Run with: uvicorn src.api.api:app --reload"""

import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from functools import lru_cache

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from src import config
from src.api.api_models import ReviewRequest, ReviewResponse
from src.llm_judge import JudgeFailed, JudgeUnavailable, judge_resume, make_judge_client
from src.resume_metrics import hallucination_reasons, awkward_language_reasons
from src.schemas import JobDescription, Resume, validation_messages
from src.step3_failure_analysis import (
    EXPERIENCE_RATIO_THRESHOLD,
    FLAGS,
    SENIORITY_GAP_THRESHOLD,
    SKILLS_GAP_THRESHOLD,
    discover_latest_stats,
    job_fit_checks,
    resume_checks,
)

RESUME_FLAGS = ("hallucination_flag", "awkward_language_flag")

API_VERSION = "0.1.0"

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Resume Coach Review API",
    version=API_VERSION,
    description="Scores resumes against job requirements with the same rules as the synthetic data pipeline.",
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # Covers missing fields, wrong types and malformed JSON bodies (type "json_invalid").
    detail = [
        {"loc": [str(part) for part in error["loc"]], "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"error": "validation_error", "detail": detail})


@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "internal_error"})


FAILURE_RATE_FIELDS = ("validation_timestamp", "pair_count", "skipped", "overall_failure_rates", "any_failure_rate", "by_group")
OPTIONAL_SECTIONS = ("correlation", "distributions", "spot_check")


@app.get("/analysis/failure-rates")
def failure_rates(
    include: str = Query(
        default="",
        description="Comma-separated extra sections from the stats file: " + ", ".join(OPTIONAL_SECTIONS),
        examples=["correlation,distributions"],
    ),
):
    """Aggregate failure rates from the newest step 3 run (output/failure_stats_*.json)."""
    sections = [section.strip() for section in include.split(",") if section.strip()]
    unknown = sorted(set(sections) - set(OPTIONAL_SECTIONS))
    if unknown:
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "detail": [{"loc": ["query", "include"], "msg": f"Unknown section(s): {', '.join(unknown)}; allowed: {', '.join(OPTIONAL_SECTIONS)}", "type": "value_error"}],
            },
        )
    latest = discover_latest_stats(config.OUTPUT_DIR)
    if latest is None:
        return JSONResponse(
            status_code=404,
            content={"error": "no_failure_stats", "hint": "run python3 -m src.pipeline step3"},
        )
    _, path = latest
    try:
        stats = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not read %s", path)
        return JSONResponse(status_code=500, content={"error": "invalid_failure_stats", "file": path.name})
    return {
        "source_file": path.name,
        **{field: stats.get(field) for field in FAILURE_RATE_FIELDS},
        **{section: stats.get(section) for section in sections},
    }


@app.get("/health")
def health():
    # Read config.OUTPUT_DIR at call time so tests can point it elsewhere.
    latest = discover_latest_stats(config.OUTPUT_DIR)
    return {
        "status": "ok",
        "version": API_VERSION,
        "latest_failure_stats": latest[0] if latest else None,
    }


def _schema_warnings(resume, job):
    """What the strict pipeline schemas would reject (missing metadata, pipeline list sizes, job rules)."""
    warnings = []
    for prefix, model, payload in (("resume", Resume, resume), ("job", JobDescription, job)):
        if payload is None:
            continue
        try:
            model.model_validate(payload, context={})
        except ValidationError as exc:
            warnings.extend(f"{prefix}.{message}" for message in validation_messages(exc))
    return warnings


def _detail(resume, resume_side, job_side, integrity):
    detail = [reason["msg"] for reason in hallucination_reasons(resume)]
    detail += [reason["msg"] for reason in awkward_language_reasons(resume)]
    if job_side is None:
        return detail
    if job_side["skills_jaccard"] is None:
        detail.append("Job lists no required skills, so skill overlap, fit level and core skills were not scored.")
    elif job_side["skills_gap_flag"]:
        detail.append(
            f"Required-skill overlap {job_side['skills_jaccard']:.0%} is below {SKILLS_GAP_THRESHOLD:.0%}."
        )
    if job_side["missing_core_skills"]:
        detail.append("Missing core skills: " + ", ".join(job_side["missing_core_skills"]) + ".")
    if job_side["experience_mismatch_flag"]:
        detail.append(
            f"{resume_side['resume_years']} years of experience is under {EXPERIENCE_RATIO_THRESHOLD:.0%} "
            f"of the {job_side['required_years']} required."
        )
    if job_side["seniority_mismatch_flag"]:
        gap = job_side["seniority_gap"]
        detail.append(
            f"Resume seniority {resume_side['resume_seniority_name']} is {abs(gap)} levels "
            f"{'above' if gap > 0 else 'below'} the job's {job_side['job_seniority_name']} "
            f"(more than {SENIORITY_GAP_THRESHOLD} is flagged)."
        )
    if integrity is not None and not integrity["met_intended_fit"]:
        detail.append(
            f"Intended fit was {integrity['intended_fit_level']}, but the skill overlap gives "
            f"{integrity['actual_fit_level']}."
        )
    return detail


# httpx timeouts are per read and OpenRouter keeps the connection alive while the model works, so the
# request deadline is enforced here. A timed-out call finishes in the background and its result is dropped.
_judge_pool = ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_REQUESTS)


@lru_cache(maxsize=1)
def _judge_client():
    # Not cached when it raises, so setting the key later works without a restart.
    return make_judge_client(timeout=config.JUDGE_API_TIMEOUT_SECONDS)


@app.post("/review-resume", response_model=ReviewResponse)
def review_resume(
    request: ReviewRequest,
    judge: bool = Query(default=False, description="Also run the LLM judge (one model call, up to ~10 s)."),
):
    """Score a resume, optionally against a job. Without a job only the resume-side checks run."""
    resume = request.resume.model_dump(exclude_none=True)
    job = request.job.model_dump(exclude_none=True) if request.job is not None else None

    resume_side = resume_checks(resume)
    job_side = job_fit_checks(job, resume) if job is not None else None
    applicable = FLAGS if job_side is not None else RESUME_FLAGS
    flags = {flag: (resume_side | (job_side or {}))[flag] for flag in applicable}

    intended = (resume.get("metadata") or {}).get("fit_level")
    integrity = None
    if job_side is not None and intended is not None and job_side["actual_fit_level"] is not None:
        integrity = {
            "intended_fit_level": intended,
            "actual_fit_level": job_side["actual_fit_level"],
            "skills_jaccard": job_side["skills_jaccard"],
            "met_intended_fit": intended == job_side["actual_fit_level"],
        }

    verdict = None
    if judge:
        trace_id = (resume.get("metadata") or {}).get("trace_id") or f"review-{uuid.uuid4()}"
        try:
            verdict = _judge_pool.submit(
                judge_resume, _judge_client(), resume, job, trace_id, attempts=1, reasoning=False
            ).result(timeout=config.JUDGE_API_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            return JSONResponse(
                status_code=504,
                content={"error": "judge_timeout", "detail": f"no verdict within {config.JUDGE_API_TIMEOUT_SECONDS} s"},
            )
        except JudgeUnavailable as exc:
            return JSONResponse(status_code=503, content={"error": "judge_unavailable", "detail": str(exc)})
        except JudgeFailed as exc:
            logger.warning("Judge failed for %s: %s", trace_id, exc)
            return JSONResponse(status_code=502, content={"error": "judge_failed", "detail": str(exc)})

    return {
        "resume_checks": resume_side,
        "job_fit": job_side,
        "integrity": integrity,
        "flags": flags,
        "triggered_flags": [flag for flag, value in flags.items() if value],
        "failure_count": sum(flags.values()),
        "schema_warnings": _schema_warnings(resume, job),
        "detail": _detail(resume, resume_side, job_side, integrity),
        "judge": verdict,
    }
