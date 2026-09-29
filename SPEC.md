# Project Spec: Resume Coach Synthetic Data Pipeline

This is the full target design for the pipeline. Only **Step 1 (job description
generation)** is implemented so far — see `CLAUDE.md` for what actually exists
today. This file is the spec for the rest.

## Context

Build a production-grade synthetic data pipeline that generates, validates,
and analyzes resume-job description pairs using LLMs. The system acts as an
intelligent resume coach that can identify mismatches, detect quality issues,
and provide actionable feedback. It should be able to:

- Generate realistic resume-job pairs with varying quality levels
- Validate that data follows strict structural rules
- Analyze why a resume fails to match a job (skills gap? seniority mismatch? hallucinations?)
- Visualize patterns in failures across different scenarios
- Correct invalid data through iterative LLM feedback
- Serve this intelligence via a REST API for real-time analysis

## System architecture overview

1. **Generation**: Generate job descriptions (with niche role detection) → generate resumes with controlled fit levels per job → create resume-job pairs with metadata.
2. **Validation**: Schema validation (Pydantic models) → error extraction and categorization → save valid/invalid records separately.
3. **Analysis**: Calculate failure metrics (Jaccard, experience gaps, etc.) → optional LLM-as-Judge for subtle quality issues → generate correlation matrices and heatmaps.
4. **Correction** (optional): Feed validation errors back to the LLM → re-validate corrected outputs → track correction success rates.
5. **API exposure**:
   - `POST /review-resume` — analyze resume against job
   - `GET /health` — health check
   - `GET /analysis/failure-rates` — aggregate statistics

Step 1 (job description generation) is implemented in `step1_generation.py` /
`schemas.py` / `config.py` / `prompts/job_description/`. Steps 2-5 are not
started; `pipeline.py`'s `step` argument (`step1` vs `all`) anticipates them
but only dispatches to step 1 today.

## Success metrics

### 1. Data generation quality
- Generate 50+ job descriptions across diverse industries (more or less can be argued for).
- Generate 5-10 resumes per job with controlled fit levels (more or less can be argued for):
  - Excellent fit (80%+ skill overlap)
  - Good fit (60-80%)
  - Partial fit (40-60%)
  - Poor fit (20-40%)
  - Complete mismatch (<20%)

### 2. Schema validation performance
- Target: >90% validation success rate for generated data.
- Detailed error categorization for failures:
  - Missing required fields
  - Type mismatches
  - Format violations (email, dates, phone)
  - Logical inconsistencies (e.g. `end_date` before `start_date`)

### 3. Failure detection accuracy
The labeling system must calculate these metrics for every resume-job pair:
- **Skills Overlap** — Jaccard similarity, A ∩ B
- **Experience Mismatch** — years gap or <50% of required → binary flag
- **Seniority Mismatch** — level difference (Entry=0, Mid=1, Senior=2, Lead=3, Exec=4), >1 level = flag
- **Missing Core Skills** — absence of top-3 required skills → binary flag
- **Hallucinated Skills** — unrealistic claims (20+ "expert" skills, etc.) → binary flag
- **Awkward Language** — excessive buzzwords, AI patterns → binary flag

### 4. Correction loop effectiveness
- Target: >50% correction success rate for invalid records.
- Maximum 3 retry attempts per record.
- Track attempts-per-success and failure reasons.

### 5. API performance
- Response time <2s without the LLM judge, <10s with it enabled.
- All endpoints return valid JSON with proper error handling.

## Target technology stack

- Python 3.10+
- Pydantic — schema validation with detailed error reporting
- **Instructor** — structured LLM outputs (not yet adopted; current `step1_generation.py` parses raw JSON from chat completions manually via `parse_json_object`/regex instead)
- LLM generation currently uses OpenRouter's `meta-llama/llama-3.1-8b-instruct` model via the `openai` SDK. The provider/model choice is set in `config.py`.
- Pandas — data manipulation and analysis (not yet a dependency)
- Matplotlib/Seaborn — visualization generation (not yet a dependency)
- FastAPI — REST API framework (not yet a dependency; no API exists yet)

## Data schema requirements

### Resume schema (not yet implemented)
- **Contact Info**: name, email, phone, location (+ optional LinkedIn, portfolio)
- **Education**: degree, institution, graduation_date (+ optional GPA, coursework)
- **Experience**: company, title, dates, responsibilities, achievements
- **Skills**: name, proficiency_level (Beginner/Intermediate/Advanced/Expert), optional years
- **Metadata**: trace_id, generated_at, prompt_template, fit_level, writing_style

### Job description schema (implemented — see `schemas.py`)
- **Company**: name, industry, size, location
- **Requirements**: required_skills[], preferred_skills[], education, experience_years, experience_level
- **Metadata**: trace_id, generated_at, is_niche_role (boolean flag)

The current `JobDescription` model in `schemas.py` matches this shape and
additionally enforces per-template constraints (skill counts, sentence
counts, allowed company sizes/experience levels) that go beyond this spec —
see `CLAUDE.md` for how `TEMPLATE_CONSTRAINTS` works.

### Validation rules
- Email must be valid format.
- Phone must be ≥10 characters.
- Dates must be ISO format.
- GPA must be 0.0-4.0.
- Experience years must be 0-30.
- `end_date` must be after `start_date` (if present).
