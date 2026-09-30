import json
import math
import os
import re
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import OpenAI

from config import (
    INDUSTRIES,
    MAX_ATTEMPTS,
    MODEL,
    JOBS,
    OUTPUT_DIR,
    PROMPT_TEMPLATES,
    PROMPTS_DIR,
    RESUME_PROMPTS_DIR,
    RESUME_WRITING_STYLES,
    RESUMES_PER_JOB,
    ROOT,
    TEMPERATURE,
)

FIT_LEVELS = ("excellent", "good", "partial", "poor", "complete_mismatch")


def plan_batch(count, templates, industries):
    if count < 1:
        raise ValueError("JOBS must be at least 1")
    if not templates or not industries:
        raise ValueError("prompt templates and industries are required")
    batch = []
    for index in range(count):
        batch.append(
            {
                "index": index,
                "prompt_template": templates[index % len(templates)],
                "industry": industries[index % len(industries)],
            }
        )
    return batch


def render_prompt(template_text, industry, trace_id, generated_at):
    rendered = (
        template_text.replace("[INDUSTRY]", industry)
        .replace("[TRACE_ID]", trace_id)
        .replace("[GENERATED_AT]", generated_at)
        .replace("[NOTES]", "none")
    )
    leftover = re.findall(r"\[[A-Z_]+\]", rendered)
    if leftover:
        raise ValueError(f"unfilled prompt placeholders: {', '.join(leftover)}")
    return rendered


def parse_json_object(text):
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    payload = json.loads(cleaned)
    if not isinstance(payload, dict):
        raise ValueError("model response is not a JSON object")
    return payload


def load_templates():
    templates = {}
    for name in PROMPT_TEMPLATES:
        path = PROMPTS_DIR / f"{name}.txt"
        if not path.is_file():
            raise FileNotFoundError(f"missing prompt template: {path}")
        templates[name] = path.read_text(encoding="utf-8")
    return templates


def load_resume_template():
    path = RESUME_PROMPTS_DIR / "controlled_fit.txt"
    if not path.is_file():
        raise FileNotFoundError(f"missing resume prompt template: {path}")
    return path.read_text(encoding="utf-8")


def jobs_output_path(started_at):
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    return OUTPUT_DIR / f"jobs_{stamp}.jsonl"


def resumes_output_path(started_at):
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    return OUTPUT_DIR / f"resumes_{stamp}.jsonl"


def pairs_output_path(started_at):
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    return OUTPUT_DIR / f"pairs_{stamp}.jsonl"


def plan_resume_fits(count):
    if not 5 <= count <= 10:
        raise ValueError("RESUMES_PER_JOB must be between 5 and 10")
    return [FIT_LEVELS[index % len(FIT_LEVELS)] for index in range(count)]


def fit_match_bounds(required_skill_count, fit_level):
    if fit_level == "excellent":
        return math.ceil(0.8 * required_skill_count), required_skill_count
    if fit_level == "good":
        return math.ceil(0.6 * required_skill_count), math.ceil(0.8 * required_skill_count) - 1
    if fit_level == "partial":
        return math.ceil(0.4 * required_skill_count), math.ceil(0.6 * required_skill_count) - 1
    if fit_level == "poor":
        return math.ceil(0.2 * required_skill_count), math.ceil(0.4 * required_skill_count) - 1
    if fit_level == "complete_mismatch":
        return 0, 0
    raise ValueError(f"unknown fit level: {fit_level}")


def append_job(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def generate_one(client, template_name, template_text, industry):
    trace_id = f"jd-{uuid.uuid4()}"
    generated_at = datetime.now(timezone.utc).isoformat()
    prompt = render_prompt(template_text, industry, trace_id, generated_at)
    messages = [{"role": "user", "content": prompt}]
    last_error = "no response"
    raw_response = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                temperature=TEMPERATURE,
                messages=messages,
                response_format={"type": "json_object"},
            )
            raw_response = response.choices[0].message.content or ""
            payload = parse_json_object(raw_response)
            return payload, None
        except Exception as exc:
            last_error = str(exc)
        print(f"  attempt {attempt} failed: {last_error}")
        messages.append({"role": "assistant", "content": raw_response})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"That response could not be used: {last_error}. "
                    "Return a valid JSON object only."
                ),
            }
        )
    return None, {"error": last_error, "raw_response": raw_response}


def render_resume_prompt(template_text, job, fit_level, writing_style):
    required_skills = job["requirements"]["required_skills"]
    minimum, maximum = fit_match_bounds(len(required_skills), fit_level)
    replacements = {
        "[FIT_LEVEL]": fit_level,
        "[MIN_MATCHED_SKILLS]": str(minimum),
        "[MAX_MATCHED_SKILLS]": str(maximum),
        "[REQUIRED_SKILLS]": ", ".join(required_skills),
        "[EXPERIENCE_YEARS]": str(job["requirements"]["experience_years"]),
        "[EXPERIENCE_LEVEL]": job["requirements"]["experience_level"],
        "[WRITING_STYLE]": writing_style,
        "[JOB_DESCRIPTION]": json.dumps(job, ensure_ascii=False, indent=2),
    }
    rendered = template_text
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    leftover = re.findall(r"\[[A-Z_]+\]", rendered)
    if leftover:
        raise ValueError(f"unfilled resume prompt placeholders: {', '.join(leftover)}")
    return rendered


def generate_resume_one(client, job, template_text, fit_level, writing_style):
    trace_id = f"resume-{uuid.uuid4()}"
    generated_at = datetime.now(timezone.utc).isoformat()
    prompt = render_resume_prompt(template_text, job, fit_level, writing_style)
    messages = [{"role": "user", "content": prompt}]
    last_error = "no response"
    raw_response = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                temperature=TEMPERATURE,
                messages=messages,
                response_format={"type": "json_object"},
            )
            raw_response = response.choices[0].message.content or ""
            payload = parse_json_object(raw_response)
            payload["metadata"] = {
                "trace_id": trace_id,
                "generated_at": generated_at,
                "prompt_template": "controlled_fit",
                "fit_level": fit_level,
                "writing_style": writing_style,
                "job_trace_id": job["metadata"]["trace_id"],
            }
            return payload, None
        except Exception as exc:
            last_error = str(exc)
        print(f"  resume attempt {attempt} failed: {last_error}")
        messages.append({"role": "assistant", "content": raw_response})
        messages.append(
            {
                "role": "user",
                "content": (
                    f"That response could not be used: {last_error}. Return a valid JSON object only, "
                    "keeping the requested fit level and writing style."
                ),
            }
        )
    return None, {"error": last_error, "raw_response": raw_response}


def generate_job_descriptions():
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENROUTER_API_KEY in the environment or a .env file.")

    templates = load_templates()
    resume_template = load_resume_template()
    fit_plan = plan_resume_fits(RESUMES_PER_JOB)
    batch = plan_batch(JOBS, PROMPT_TEMPLATES, INDUSTRIES)
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    started_at = datetime.now(timezone.utc)
    output_path = jobs_output_path(started_at)
    resume_path = resumes_output_path(started_at)
    pair_path = pairs_output_path(started_at)
    for path in (output_path, resume_path, pair_path):
        path.touch(exist_ok=True)
    written = 0
    failed = 0
    resumes_written = 0
    resumes_failed = 0

    for item in batch:
        label = f"[{item['index'] + 1}/{JOBS}] {item['prompt_template']} | {item['industry']}"
        print(label)
        payload, failure = generate_one(
            client,
            item["prompt_template"],
            templates[item["prompt_template"]],
            item["industry"],
        )
        if payload is None:
            failed += 1
            error = failure["error"] if failure else "generation failed without error details"
            print(f"  skipped: {error}")
            continue
        append_job(
            output_path,
            {
                "index": item["index"],
                "prompt_template": item["prompt_template"],
                "assigned_industry": item["industry"],
                "model": MODEL,
                "job_description": payload,
            },
        )
        written += 1

        try:
            render_resume_prompt(
                resume_template,
                payload,
                fit_plan[0],
                RESUME_WRITING_STYLES[0],
            )
            payload["metadata"]["trace_id"]
        except (KeyError, TypeError) as exc:
            print(f"  resume generation skipped: job lacks prompt fields ({exc})")
            continue

        for resume_index, fit_level in enumerate(fit_plan):
            writing_style = RESUME_WRITING_STYLES[resume_index % len(RESUME_WRITING_STYLES)]
            print(f"  resume {resume_index + 1}/{len(fit_plan)}: {fit_level} ({writing_style})")
            resume_payload, resume_failure = generate_resume_one(
                client,
                payload,
                resume_template,
                fit_level,
                writing_style,
            )
            if resume_payload is None:
                resumes_failed += 1
                error = resume_failure["error"] if resume_failure else "generation failed without error details"
                print(f"    skipped: {error}")
                continue
            append_job(resume_path, resume_payload)
            resumes_written += 1
            append_job(
                pair_path,
                {
                    "pair_id": uuid.uuid4().hex[:12],
                    "job_trace_id": payload["metadata"]["trace_id"],
                    "resume_trace_id": resume_payload["metadata"]["trace_id"],
                    "fit_level": resume_payload["metadata"]["fit_level"],
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
            )

    print(f"Wrote {written} job descriptions to {output_path}")
    print(f"Wrote {resumes_written} resumes to {resume_path}")
    print(f"Wrote {resumes_written} resume-job pairs to {pair_path}")
    if failed:
        print(f"{failed} jobs could not be generated after {MAX_ATTEMPTS} attempts.")
    if resumes_failed:
        print(f"{resumes_failed} resumes could not be generated after {MAX_ATTEMPTS} attempts.")
    return {
        "started_at": started_at,
        "jobs_path": output_path,
        "resumes_path": resume_path,
        "pairs_path": pair_path,
    }
