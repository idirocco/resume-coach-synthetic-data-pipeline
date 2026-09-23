import json
import os
import re
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from config import (
    INDUSTRIES,
    MAX_ATTEMPTS,
    MODEL,
    N,
    OUTPUT_DIR,
    PROMPT_TEMPLATES,
    PROMPTS_DIR,
    ROOT,
    TEMPERATURE,
)
from schemas import parse_job_description, validation_messages


def plan_batch(count, templates, industries):
    if count < 1:
        raise ValueError("N must be at least 1")
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


def jobs_output_path(started_at):
    stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    return OUTPUT_DIR / f"jobs_{stamp}.jsonl"


def append_job(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def generate_one(client, template_name, template_text, industry):
    trace_id = f"jd-{uuid.uuid4()}"
    generated_at = datetime.now(timezone.utc).isoformat()
    prompt = render_prompt(template_text, industry, trace_id, generated_at)
    last_error = "no response"
    raw_response = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                temperature=TEMPERATURE,
                messages=[{"role": "user", "content": prompt}],
            )
            raw_response = response.choices[0].message.content or ""
            payload = parse_json_object(raw_response)
            job = parse_job_description(
                payload,
                industry=industry,
                trace_id=trace_id,
                generated_at=generated_at,
                prompt_template=template_name,
            )
            return job.model_dump(), None
        except ValidationError as exc:
            last_error = "; ".join(validation_messages(exc))
        except Exception as exc:
            last_error = str(exc)
        print(f"  attempt {attempt} failed: {last_error}")
    return None, {"error": last_error, "raw_response": raw_response}


def generate_job_descriptions():
    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENROUTER_API_KEY in the environment or a .env file.")

    templates = load_templates()
    batch = plan_batch(N, PROMPT_TEMPLATES, INDUSTRIES)
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    output_path = jobs_output_path(datetime.now(timezone.utc))
    written = 0
    failed = 0

    for item in batch:
        label = f"[{item['index'] + 1}/{N}] {item['prompt_template']} | {item['industry']}"
        print(label)
        payload, failure = generate_one(
            client,
            item["prompt_template"],
            templates[item["prompt_template"]],
            item["industry"],
        )
        if payload is None:
            failed += 1
            print(f"  skipped: {failure['error']}")
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

    print(f"Wrote {written} job descriptions to {output_path}")
    if failed:
        print(f"{failed} items failed validation after {MAX_ATTEMPTS} attempts.")
    return output_path
