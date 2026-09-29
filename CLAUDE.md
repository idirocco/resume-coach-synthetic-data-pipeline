# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A synthetic data pipeline that generates, validates, and analyzes resume/job-description pairs using LLMs, for training/evaluating a resume-coaching product. Only "step 1" (job description generation) is implemented today; `pipeline.py` already anticipates further steps via a `step` CLI arg (`step1` vs `all`), but only `step1` does anything.

**See `SPEC.md` for the full target design**: resume generation with controlled fit levels, validation/correction loops, failure-metric analysis (Jaccard skill overlap, seniority/experience mismatch, hallucination detection), and a FastAPI review endpoint. None of that is built yet — treat `SPEC.md` as the roadmap, not the current state. Notably the spec calls for `Instructor` for structured LLM outputs, FastAPI, and Pandas/Matplotlib/Seaborn, none of which are dependencies yet; step 1 gets structured output today by hand-parsing chat completion JSON (`parse_json_object` in `step1_generation.py`).

## Commands

```bash
python3 -m pip install -r requirements.txt   # install deps
python3 pipeline.py                          # run step1 (default)
python3 pipeline.py step1                    # same, explicit
```

There are no tests, lint config, or CI in this repo currently.

### Configuration

- Requires `OPENROUTER_API_KEY` set in the environment or a `.env` file (see `.env.example`). `startup_checks.py` fails fast with actionable messages if dependencies or the API key are missing.
- Generation parameters (batch size `JOBS`, model, temperature, retry count, the industry list, and which prompt templates cycle through) live in `config.py` — edit there rather than passing flags.
- Output is written to `output/jobs_<UTC timestamp>.jsonl`, one JSON line per generated job.

## Architecture

The pipeline is a straight-line script, not a framework — each module has one job:

- **`config.py`** — all tunables (batch count `JOBS`, generation model `meta-llama/llama-3.1-8b-instruct`, temperature, `MAX_ATTEMPTS`, the six `PROMPT_TEMPLATES` names, the ten BLS-derived `INDUSTRIES`). `plan_batch` (in `step1_generation.py`) cycles templates and industries independently by index so both are covered evenly across `JOBS` items regardless of how they divide.
- **`startup_checks.py`** — verifies output dir, required packages, and `OPENROUTER_API_KEY` before any generation work starts.
- **`prompts/job_description/*.txt`** — one prompt template per synthetic scenario (`formal_corporate`, `casual_startup`, `technical_detail`, `achievement_metrics`, `career_changer`, `niche_specialist`). Templates use `[INDUSTRY]`, `[TRACE_ID]`, `[GENERATED_AT]`, `[NOTES]` placeholders filled by `render_prompt`; any leftover `[UPPER_CASE]` placeholder after substitution raises an error, so a new template must use exactly these tokens or `render_prompt` needs updating too.
- **`schemas.py`** — the Pydantic contract for a `JobDescription` (company/requirements/title/description/responsibilities/metadata), plus **template-specific validation rules**. This is the important cross-cutting piece: `TEMPLATE_CONSTRAINTS` maps each template name to a `TemplateConstraints` (skill counts, sentence counts, allowed company sizes/experience levels, whether the role must be niche). `JobDescription.apply_rules` runs both universal checks (experience-years-matches-level band, no duplicate/overlapping skills, industry/trace_id/generated_at echoed back correctly) and the template-specific ones from this map. **A prompt template and its `TemplateConstraints` entry must stay in sync** — the LLM output is only as good as the prompt's instructions, but it's the schema that actually enforces/rejects it.
- **`step1_generation.py`** — orchestrates one run: loads templates, builds the batch plan, calls OpenRouter (`openai` SDK pointed at `https://openrouter.ai/api/v1`, `response_format={"type": "json_object"}`) per item, parses/validates the JSON response against `schemas.py`, and appends successes to the JSONL output as it goes (not batched at the end). On validation failure, `generate_one` doesn't just retry blind — it appends the bad response plus the specific Pydantic error message to the conversation and asks the model to correct it, up to `MAX_ATTEMPTS` turns, before giving up and skipping the item. This is a lightweight version of the "Correction" step described in `SPEC.md`, implemented inline rather than as a separate pass.
- **`pipeline.py`** — thin entrypoint: runs startup checks, then dispatches to the requested step.

### Adding a new prompt template

Touch three places together: add the `.txt` file under `prompts/job_description/`, add its name to `PROMPT_TEMPLATES` in `config.py`, and add a matching entry to `TEMPLATE_CONSTRAINTS` in `schemas.py` (omit fields to inherit the `TemplateConstraints` defaults).
