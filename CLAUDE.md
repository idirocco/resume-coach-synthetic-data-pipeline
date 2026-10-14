# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A synthetic data pipeline that generates, validates, and analyzes resume/job-description pairs using LLMs, for training/evaluating a resume-coaching product. Implemented today: step 1 (generation of jobs, resumes and pairs), step 2 (validation), a correction loop, step 3 (failure labeling) and step 4 (charts). The FastAPI review endpoint is not built.

**See `SPEC.md` for the full target design.** The FastAPI endpoint and `Instructor` are not adopted yet; LLM output is hand-parsed (`parse_json_object` in `step1_generation.py`).

## Commands

```bash
python3 -m pip install -r requirements.txt   # install deps
python3 pipeline.py                          # steps 1 -> 2 -> correction -> 3 -> 4 (makes LLM calls)
python3 pipeline.py step1                    # generation only
python3 pipeline.py step2                    # validate the latest jobs/resumes/pairs files
python3 pipeline.py correct                  # LLM correction of the latest step 2 report's invalid records
python3 pipeline.py step3                    # failure labels from the latest pairs_enriched file
python3 pipeline.py step4                    # charts from the latest failure labels
python3 -m pytest                            # tests (no LLM calls)
```

Steps 2-4 and `correct` read the newest files in `output/`; only step 1 and `correct` need `OPENROUTER_API_KEY`. There is no lint config or CI.

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

### Steps 2-4 (analysis)

- **`resume_metrics.py`** — pure functions shared by steps 2 and 3 so they cannot disagree: `skill_key`/`jaccard`, `resume_years` (ongoing roles end at the resume's `generated_at`), seniority inference (title keywords, else years), hallucination and awkward-language rules. Change a threshold here, not in the steps.
- **`step2_validation.py`** — schema failures reject a record; hallucination/awkward language are only *warnings* on valid resumes. Writes `validated_data`, `invalid`, `schema_failure_modes` (with a field × category matrix) and `pairs_enriched_{ts}.jsonl`, the one-row-per-pair file step 3 reads.
- **`correction.py` + `step2_correction.py`** — error context and correction prompt shared with step 1's retries; up to `MAX_ATTEMPTS` turns per invalid job/resume, pipeline-assigned ids restored after each reply, then the corrected files are re-validated. Pair errors are not correctable.
- **`step3_failure_analysis.py`** — six flags per pair plus the numbers behind them, `failure_labels_{ts}.jsonl` and `failure_stats_{ts}.json`. Targets for core skills live in `config.py` (`CORE_SKILL_COUNT`, shared with the generator).
- **`step4_visualization.py`** — 10 PNGs plus a rates CSV in `visualizations/{ts}/`; a chart without data is a placeholder PNG saying why. Targets come from `FAILURE_TARGETS` in `config.py`.

### Adding a new prompt template

Touch three places together: add the `.txt` file under `prompts/job_description/`, add its name to `PROMPT_TEMPLATES` in `config.py`, and add a matching entry to `TEMPLATE_CONSTRAINTS` in `schemas.py` (omit fields to inherit the `TemplateConstraints` defaults).

## Iteration Logging

At the end of every work iteration that changes pipeline behavior, prompts, configuration, thresholds, or validation rules, append an entry to `iteration_log.md` using the format in that file. Record the measured before/after metric and delta when available; never invent metrics or reasons. Use `Not measured` when no comparable metric exists and `Pending` for a keep/revert decision that lacks evidence. See `.github/skills/iteration-log/SKILL.md` for the workflow.
