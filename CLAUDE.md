# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A synthetic data pipeline that generates, validates, and analyzes resume/job-description pairs using LLMs, for training/evaluating a resume-coaching product. Implemented today: step 1 (generation of jobs, resumes and pairs), step 2 (validation), a correction loop, step 3 (failure labeling), step 4 (charts), an optional LLM judge, and step 5 (the FastAPI review API, with the judge behind `?judge=1`).

**See `SPEC.md` for the full target design.** `Instructor` is not adopted yet; LLM output is hand-parsed (`parse_json_object` in `src/step1_generation.py`).

## Commands

```bash
python3 -m pip install -r requirements.txt   # install deps
python3 -m src.pipeline                          # steps 1 -> 2 -> correction -> 3 -> 4 (makes LLM calls)
python3 -m src.pipeline step1                    # generation only
python3 -m src.pipeline step2                    # validate the latest jobs/resumes/pairs files
python3 -m src.pipeline correct                  # LLM correction of the latest step 2 report's invalid records
python3 -m src.pipeline step3                    # failure labels from the latest pairs_enriched file
python3 -m src.pipeline step4                    # charts from the latest failure labels
python3 -m src.pipeline judge [--limit N]        # LLM judge over the latest pairs_enriched file -> output/judge_output.json
python3 -m src.judge_chart                       # bar chart of output/judge_output.json -> docs/judge_summary.png
python3 -m pytest                            # tests (no LLM calls)
uvicorn src.api.api:app --reload                     # review API on :8000, docs at /docs
```

Steps 2-4 and `correct` read the newest files in `output/`; only step 1, `correct` and `judge` need `OPENROUTER_API_KEY`. The API needs a key only for `?judge=1`. There is no lint config or CI.

### Configuration

- Requires `OPENROUTER_API_KEY` set in the environment or a `.env` file (see `.env.example`). `src/startup_checks.py` fails fast with actionable messages if dependencies or the API key are missing.
- Generation parameters (batch size `JOBS`, model, temperature, retry count, the industry list, and which prompt templates cycle through) live in `src/config.py` — edit there rather than passing flags.
- Step 1 writes `output/jobs_<UTC timestamp>.jsonl`, `resumes_<ts>.jsonl` and `pairs_<ts>.jsonl`, one JSON line per record. `output/` and `visualizations/` are gitignored; the README's charts are curated copies in `docs/`.

## Architecture

All Python code lives in the `src/` package: the step modules, the shared modules (`config`, `schemas`, `resume_metrics`, `correction`, `llm_judge`, `startup_checks`, `iteration_log`), the entry points `src/pipeline.py` and `src/judge_chart.py`, and the review API in `src/api/` (`src.api.api:app`). Import as `from src.config import ...` (also in `patch("src....")` targets) and run everything from the repo root with `python3 -m src.<module>`; `config.ROOT` is the repo root, so `prompts/`, `output/` and `docs/` stay where they are.

The pipeline is a straight-line script, not a framework — each module has one job:

- **`src/config.py`** — all tunables (batch count `JOBS`, generation model `MODEL` = `openai/gpt-oss-20b`, judge model `JUDGE_MODEL`, temperature, `MAX_ATTEMPTS`, the six `PROMPT_TEMPLATES` names, the ten BLS-derived `INDUSTRIES`). `plan_batch` (in `src/step1_generation.py`) cycles templates and industries independently by index so both are covered evenly across `JOBS` items regardless of how they divide.
- **`src/startup_checks.py`** — verifies output dir, required packages, and `OPENROUTER_API_KEY` before any generation work starts.
- **`prompts/job_description/*.txt`** — one prompt template per synthetic scenario (`formal_corporate`, `casual_startup`, `technical_detail`, `achievement_metrics`, `career_changer`, `niche_specialist`). Templates use `[INDUSTRY]`, `[TRACE_ID]`, `[GENERATED_AT]`, `[NOTES]` placeholders filled by `render_prompt`; any leftover `[UPPER_CASE]` placeholder after substitution raises an error, so a new template must use exactly these tokens or `render_prompt` needs updating too.
- **`src/schemas.py`** — the Pydantic contract for a `JobDescription` (company/requirements/title/description/responsibilities/metadata), plus **template-specific validation rules**. This is the important cross-cutting piece: `TEMPLATE_CONSTRAINTS` maps each template name to a `TemplateConstraints` (skill counts, sentence counts, allowed company sizes/experience levels, whether the role must be niche). `JobDescription.apply_rules` runs both universal checks (experience-years-matches-level band, no duplicate/overlapping skills, industry/trace_id/generated_at echoed back correctly) and the template-specific ones from this map. **A prompt template and its `TemplateConstraints` entry must stay in sync** — the LLM output is only as good as the prompt's instructions, but it's the schema that actually enforces/rejects it.
- **`src/step1_generation.py`** — orchestrates one run: loads templates, builds the batch plan, calls OpenRouter (`openai` SDK pointed at `https://openrouter.ai/api/v1`, `response_format={"type": "json_object"}`) per item, and appends successes to the JSONL output as it goes (not batched at the end). Jobs (`generate_one`) are only parsed as JSON; their schema checks happen first in step 2. Each job gets one resume per fit level (`plan_resume_fits`) and one per writing style (`plan_resume_styles`). Styles rotate by the job's batch `index`, so style and fit level are not confounded. Resumes are validated with `parse_resume` against the job's required skills and fit level. On a failure, generation doesn't retry blind: it appends the bad response plus the error (JSON decode or Pydantic) to the conversation via `build_correction_prompt` and asks the model to fix it, up to `MAX_ATTEMPTS` turns, before skipping the item.
- **`src/pipeline.py`** — thin entrypoint: runs startup checks, then dispatches to the requested step.

### Steps 2-4 (analysis)

- **`src/resume_metrics.py`** — pure functions shared by steps 2 and 3 so they cannot disagree: `skill_key`/`jaccard`, `resume_years` (ongoing roles end at the resume's `generated_at`), seniority inference (title keywords, else years), hallucination and awkward-language rules. Change a threshold here, not in the steps.
- **`src/step2_validation.py`** — schema failures reject a record; hallucination/awkward language are only *warnings* on valid resumes. Writes `validated_data`, `invalid`, `schema_failure_modes` (with a field × category matrix) and `pairs_enriched_{ts}.jsonl`, the one-row-per-pair file step 3 reads.
- **`src/correction.py` + `src/step2_correction.py`** — error context and correction prompt shared with step 1's retries; up to `MAX_ATTEMPTS` turns per invalid job/resume, pipeline-assigned ids restored after each reply, then the corrected files are re-validated. Pair errors are not correctable.
- **`src/step3_failure_analysis.py`** — six flags per pair plus the numbers behind them, `failure_labels_{ts}.jsonl` and `failure_stats_{ts}.json`. Targets for core skills live in `src/config.py` (`CORE_SKILL_COUNT`, shared with the generator). `failure_stats` also lists `confounded_groups` (a group field fully determined by another, checked by `is_determined_by`). Step 4 uses the same check to replace the writing-style chart with a placeholder. `label_pair` is built from `resume_checks(resume)` and `job_fit_checks(job, resume)`, which the API calls directly — add a new metric there, not in the API.
- **`src/step4_visualization.py`** — 10 PNGs plus a rates CSV in `visualizations/{ts}/`; a chart without data is a placeholder PNG saying why. Targets come from `FAILURE_TARGETS` in `src/config.py`.
- **`src/llm_judge.py`** — `judge_resume` (one verdict, shared with the API) and `judge_run` (every valid pair → `output/judge_output.json`, overwritten each run, with rates and agreement with the step 3 rule flags). Prompt in `prompts/llm_judge.txt` (`[TRACE_ID]`, `[TODAY]`, `[JOB_DESCRIPTION]`, `[RESUME]`); `JUDGE_MODEL` in `src/config.py` must stay a different model family from `MODEL`. Metadata is stripped before sending so the intended fit cannot bias the verdict; the returned `trace_id` is overwritten with the caller's.

### Step 5 (API)

- **`src/api/api.py`** — FastAPI app. `POST /review-resume` runs `resume_checks` (always) and `job_fit_checks` (when a job is sent) and adds the integrity view (`resume.metadata.fit_level` vs the actual fit), triggered flags, `schema_warnings` (what the strict pipeline schemas would reject, informational) and plain-language `detail`. `GET /analysis/failure-rates` serves the newest `failure_stats_*.json` (`?include=correlation,distributions,spot_check`). `?judge=1` adds the LLM verdict (one attempt, reasoning off, hard deadline `JUDGE_API_TIMEOUT_SECONDS` enforced by a thread pool because httpx timeouts are per read). `GET /health`. Every error is JSON: 422 `validation_error`, 404 `no_failure_stats`, 500 `internal_error`, and with the judge 503 `judge_unavailable`, 502 `judge_failed`, 504 `judge_timeout`. `config.OUTPUT_DIR` is read per request so tests can patch it.
- **`src/api/api_models.py`** — request/response models. Field rules reuse the `src/schemas.py` models; only metadata is optional and the pipeline's list minimums are dropped, so hand-written resumes and jobs are accepted.

### Adding a new prompt template

Touch three places together: add the `.txt` file under `prompts/job_description/`, add its name to `PROMPT_TEMPLATES` in `src/config.py`, and add a matching entry to `TEMPLATE_CONSTRAINTS` in `src/schemas.py` (omit fields to inherit the `TemplateConstraints` defaults).

## Iteration Logging

At the end of every work iteration that changes pipeline behavior, prompts, configuration, thresholds, or validation rules, append an entry to `iteration_log.md` using the format in that file. Record the measured before/after metric and delta when available; never invent metrics or reasons. Use `Not measured` when no comparable metric exists and `Pending` for a keep/revert decision that lacks evidence. See `.github/skills/iteration-log/SKILL.md` for the workflow.
