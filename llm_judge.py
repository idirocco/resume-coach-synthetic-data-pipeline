"""LLM-as-judge: subtle resume quality issues the step 3 rules miss.

`judge_resume` reviews one resume (optionally against a job) and is shared by `pipeline.py judge` and
`POST /review-resume?judge=1`. `judge_run` judges every valid pair of a pairs_enriched file and writes
output/judge_output.json.
"""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import Field, ValidationError

import config
from schemas import NonBlank, StrictModel, validation_messages
from step3_failure_analysis import discover_latest_enriched, resume_checks

JUDGE_OUTPUT_FILE = "judge_output.json"


class JudgeUnavailable(RuntimeError):
    """The judge cannot be called (no API key or no openai package)."""


class JudgeFailed(RuntimeError):
    """The judge model did not return a valid verdict within its attempts."""


class JudgeVerdict(StrictModel):
    trace_id: NonBlank
    has_hallucinations: bool
    hallucination_details: NonBlank
    has_awkward_language: bool
    awkward_language_details: NonBlank
    overall_quality_score: float = Field(ge=0.0, le=1.0)
    fit_assessment: NonBlank
    recommendations: list[NonBlank]
    red_flags: list[NonBlank]


def make_judge_client(timeout=None):
    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except ImportError as exc:
        raise JudgeUnavailable(f"missing dependency: {exc.name}") from exc

    load_dotenv(config.ROOT / ".env")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise JudgeUnavailable("OPENROUTER_API_KEY is not set")
    options = {"timeout": timeout, "max_retries": 0} if timeout is not None else {}
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key, **options)


def _without_metadata(document):
    # Metadata carries the intended fit level and writing style; the judge must assess the text on its own.
    return {key: value for key, value in document.items() if key != "metadata"}


def render_judge_prompt(template_text, trace_id, today, resume, job=None):
    rendered = (
        template_text.replace("[TRACE_ID]", trace_id)
        .replace("[TODAY]", today)
        .replace("[JOB_DESCRIPTION]", json.dumps(_without_metadata(job), ensure_ascii=False, indent=2) if job else "none")
        .replace("[RESUME]", json.dumps(_without_metadata(resume), ensure_ascii=False, indent=2))
    )
    leftover = re.findall(r"\[[A-Z_]+\]", rendered)
    if leftover:
        raise ValueError(f"unfilled prompt placeholders: {', '.join(leftover)}")
    return rendered


def _review_date(resume):
    generated_at = (resume.get("metadata") or {}).get("generated_at")
    return generated_at[:10] if generated_at else date.today().isoformat()


def judge_resume(client, resume, job=None, trace_id=None, attempts=None, template_text=None, reasoning=True):
    """One judge verdict as a dict. Invalid replies are sent back with the error, up to `attempts` turns.

    reasoning=False skips the model's thinking tokens: about 2x faster, used by the API to stay under 10 s.
    """
    from step1_generation import parse_json_object

    trace_id = trace_id or (resume.get("metadata") or {}).get("trace_id") or "review"
    template_text = template_text or config.JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
    messages = [{"role": "user", "content": render_judge_prompt(template_text, trace_id, _review_date(resume), resume, job)}]
    last_error = "no response"
    for _ in range(attempts or config.JUDGE_MAX_ATTEMPTS):
        raw_response = ""
        try:
            response = client.chat.completions.create(
                model=config.JUDGE_MODEL,
                temperature=config.JUDGE_TEMPERATURE,
                messages=messages,
                response_format={"type": "json_object"},
                extra_body={"reasoning": {"enabled": reasoning}},
            )
            raw_response = response.choices[0].message.content or ""
            payload = parse_json_object(raw_response)
            # The trace id is the caller's, not the model's to choose.
            payload["trace_id"] = trace_id
            return JudgeVerdict.model_validate(payload).model_dump()
        except ValidationError as exc:
            last_error = "; ".join(validation_messages(exc))
        except Exception as exc:
            last_error = str(exc)
        messages.append({"role": "assistant", "content": raw_response})
        messages.append(
            {
                "role": "user",
                "content": f"Your reply was not a valid verdict: {last_error}. "
                "Return the corrected JSON object only, with exactly the keys and types from the output section.",
            }
        )
    raise JudgeFailed(last_error)


def _rate(count, total):
    return round(count / total, 4) if total else None


def _agreement(results, judge_key, rule_key):
    both = sum(1 for r in results if r[judge_key] and r[rule_key])
    judge_only = sum(1 for r in results if r[judge_key] and not r[rule_key])
    rule_only = sum(1 for r in results if r[rule_key] and not r[judge_key])
    return {
        "both": both,
        "judge_only": judge_only,
        "rule_only": rule_only,
        "neither": len(results) - both - judge_only - rule_only,
        "agreement_rate": _rate(len(results) - judge_only - rule_only, len(results)),
    }


def judge_summary(results):
    by_fit = {}
    for fit_level in sorted({r["fit_level"] for r in results}):
        scores = [r["overall_quality_score"] for r in results if r["fit_level"] == fit_level]
        by_fit[fit_level] = {"count": len(scores), "mean_quality_score": round(sum(scores) / len(scores), 4)}
    scores = [r["overall_quality_score"] for r in results]
    return {
        "judged": len(results),
        "hallucination_rate": _rate(sum(r["has_hallucinations"] for r in results), len(results)),
        "awkward_language_rate": _rate(sum(r["has_awkward_language"] for r in results), len(results)),
        "red_flag_rate": _rate(sum(bool(r["red_flags"]) for r in results), len(results)),
        "mean_quality_score": round(sum(scores) / len(scores), 4) if scores else None,
        "by_fit_level": by_fit,
        # Judge verdict vs the step 3 rule flag on the same resumes.
        "hallucination_vs_rules": _agreement(results, "has_hallucinations", "rule_hallucination_flag"),
        "awkward_language_vs_rules": _agreement(results, "has_awkward_language", "rule_awkward_language_flag"),
    }


def judge_run(enriched_path, output_dir=None, client=None, limit=None):
    enriched_path = Path(enriched_path)
    output_dir = Path(output_dir or config.OUTPUT_DIR)
    rows = [
        json.loads(line)
        for line in enriched_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = [row for row in rows if row["job"] is not None and row["resume"] is not None]
    if limit is not None:
        rows = rows[:limit]
    template_text = config.JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
    if rows:
        client = client or make_judge_client()

    def judge_pair(row):
        resume = row["resume"]
        try:
            verdict = judge_resume(
                client, resume, row["job"]["job_description"], resume["metadata"]["trace_id"], template_text=template_text
            )
        except JudgeFailed as exc:
            return None, {"pair_id": row["pair_id"], "resume_trace_id": row["resume_trace_id"], "error": str(exc)}
        rules = resume_checks(resume)
        return {
            "pair_id": row["pair_id"],
            "job_trace_id": row["job_trace_id"],
            "fit_level": row["fit_level"],
            **verdict,
            "rule_hallucination_flag": rules["hallucination_flag"],
            "rule_awkward_language_flag": rules["awkward_language_flag"],
        }, None

    with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT_REQUESTS) as executor:
        outcomes = list(executor.map(judge_pair, rows))
    results = [result for result, _ in outcomes if result is not None]
    failures = [failure for _, failure in outcomes if failure is not None]

    report = {
        "judged_at": datetime.now(timezone.utc).isoformat(),
        "model": config.JUDGE_MODEL,
        "source_file": str(enriched_path),
        "summary": {**judge_summary(results), "failed": len(failures)},
        "results": results,
        "failures": failures,
    }
    output_path = output_dir / JUDGE_OUTPUT_FILE
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = report["summary"]
    print(f"Judged {summary['judged']} pairs with {config.JUDGE_MODEL} ({summary['failed']} failed).")
    if results:
        print(f"  hallucinations: {summary['hallucination_rate']:.0%}, awkward language: {summary['awkward_language_rate']:.0%}, "
              f"mean quality score: {summary['mean_quality_score']}")
    print(f"Wrote judge output to {output_path}")
    return {"judge_output_path": output_path, "report": report}


def judge_latest_run(output_dir=None, client=None, limit=None):
    _, path = discover_latest_enriched(output_dir or config.OUTPUT_DIR)
    return judge_run(path, output_dir, client, limit)
