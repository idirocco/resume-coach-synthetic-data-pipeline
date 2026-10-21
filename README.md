# Resume Coach Synthetic Data Pipeline

Production-grade synthetic-data pipeline that generates resume ↔ job-description pairs at controlled quality levels, validates them with Pydantic, labels each pair with six rule-based failure metrics, self-corrects invalid records via an LLM feedback loop, visualizes the failure patterns, and serves the analysis through a FastAPI REST API.

## Commands

```bash
python3 pipeline.py          # generate data, then validate that run
python3 pipeline.py step1    # generate data
python3 pipeline.py step1 --only-jobs
python3 pipeline.py step1 --only-resumes
python3 pipeline.py step1 --only-pairs
python3 pipeline.py step2    # validate the newest complete source run
python3 pipeline.py step2 --only-jobs
python3 pipeline.py step2 --only-resumes
python3 pipeline.py step2 --only-pairs
python3 pipeline.py judge    # LLM judge over the newest pairs_enriched file
python3 pipeline.py judge --limit 10
```

`step1` runs generation in dependency order: jobs, resumes, then pairs. Omit the selector to generate all three. Its selectors are mutually exclusive:

- `--only-jobs` generates job descriptions; it has no data-file dependencies.
- `--only-resumes` generates resumes from the newest existing jobs JSONL file. It exits with an explicit error if no usable jobs file exists.
- `--only-pairs` creates pairs from the newest existing jobs and resumes JSONL files. It validates that both files exist and that each resume references a job in the jobs file before writing pairs.

Jobs-only and resume-only require `OPENROUTER_API_KEY` in the environment or `.env`; pair-only does not call the model. Step2 only needs the installed dependencies and source data; it does not call the model or require an API key.

## Generation

Generation uses the OpenRouter model `meta-llama/llama-3.1-8b-instruct`, configured in `config.py`. It writes `jobs_<UTC timestamp>.jsonl`, `resumes_<UTC timestamp>.jsonl`, and `pairs_<UTC timestamp>.jsonl` under `output/`. Pair rows reference job and resume trace IDs. Step1 decodes model replies as JSON objects but does not perform Pydantic schema validation.

## Validation

Step2 validates job descriptions, resumes, and pair records using Pydantic, including cross-record references and resume fit levels. Without a selector, it validates the newest jobs, resumes, and pairs JSONL file independently. Its mutually exclusive selectors are:

- `--only-jobs` validates the newest jobs JSONL file only.
- `--only-resumes` validates the newest jobs and resumes files; job records are checked as dependencies, but only resume results are included in the report.
- `--only-pairs` validates the newest jobs, resumes, and pairs files; jobs and resumes are checked as dependencies, but only pair results are included in the report.

Selected modes choose the newest file for each required type independently, so separately generated stages can be checked together. Step2 reports a clear missing-file error when a required source is unavailable. Running `python3 pipeline.py` with no arguments generates all three artifact types and validates the exact run it just generated. Use `step1` or `step2` to run a single step.

Each validation invocation writes three artifacts under `output/`, named with its UTC timestamp:

- `validated_data_<timestamp>.json` contains validated records with their record type and source location.
- `invalid_<timestamp>.jsonl` contains failed source records, locations, and categorized errors.
- `schema_failure_modes_<timestamp>.json` summarizes category counts, failure percentages, common fields, and the observed validation success rate. The 90% success rate is a target, not a guarantee.

## LLM judge

`python3 pipeline.py judge` sends every valid pair in the newest `pairs_enriched_*.jsonl` to a second model (`JUDGE_MODEL` in `config.py`, `anthropic/claude-haiku-5.5`, a different family from the generator) with the prompt in `prompts/llm_judge.txt`. The judge looks for what the step 3 rules miss: hallucinations, awkward language, a narrative fit assessment, and red flags such as gaps or inconsistent progression. Resume and job metadata are not sent, so the intended fit level cannot bias it. It is optional, is not part of the default run, and needs `OPENROUTER_API_KEY`; `--limit N` judges only the first N pairs.

It writes `output/judge_output.json`, overwritten on each run, with:

- `results`: one verdict per pair in the judge schema (`trace_id` is the resume's), plus `pair_id`, `fit_level` and the step 3 rule flags for the same resume.
- `summary`: hallucination, awkward-language and red-flag rates, the mean quality score overall and per fit level, and how often the judge agrees with the rule flags.
- `failures`: pairs with no valid verdict after `JUDGE_MAX_ATTEMPTS` turns.

## Review API

```bash
uvicorn api:app --reload    # http://localhost:8000, interactive docs at /docs
```

The API scores resumes with the same functions as step 3, so its flags match `failure_labels_*.jsonl` for the same pair. It needs no API key unless `?judge=1` is used.

- `GET /health` returns the status, the API version, and the timestamp of the newest `failure_stats_*.json` (or `null`).
- `POST /review-resume` takes `{"resume": {...}, "job": {...}}`, and `job` is optional. Resumes and jobs use the pipeline's field shapes, but `metadata` is optional and lists may be empty. The response contains:
  - `resume_checks`: seniority, years of experience, and hallucination and buzzword details.
  - `job_fit`: skill overlap, missing core skills, and the experience and seniority gaps. It is `null` without a job.
  - `integrity`: whether the resume reached its intended fit. The intended fit comes from `resume.metadata.fit_level`; without one, `integrity` is `null`.
  - `flags`, `triggered_flags` and `failure_count`: the two resume-side flags without a job, or all six with one.
  - `schema_warnings`: what the strict pipeline schemas would reject. These are informational only.
  - `detail`: plain-language reasons for each flag.
  - `judge`: the LLM judge verdict with `?judge=1`, otherwise `null`. It makes one model call with reasoning off and needs `OPENROUTER_API_KEY`.
- `GET /analysis/failure-rates` returns the overall and per-group failure rates from the newest step 3 run. Add `?include=correlation,distributions,spot_check` for the larger sections. It returns 404 if step 3 has not run yet.

Every error is JSON: 422 `validation_error` for missing fields, wrong types or malformed JSON, 404 `no_failure_stats`, and 500 `internal_error`. With `?judge=1`: 503 `judge_unavailable` without an API key, 502 `judge_failed` for an invalid model reply, and 504 `judge_timeout` after `JUDGE_API_TIMEOUT_SECONDS` (9 s).

```bash
curl -s localhost:8000/review-resume -H 'content-type: application/json' -d '{
  "resume": {
    "contact_info": {"name": "Ana Diaz", "email": "ana@example.com", "phone": "+1-202-555-0100", "location": "Austin, TX"},
    "education": [{"degree": "BS Computer Science", "institution": "UT Austin", "graduation_date": "2019-05-15"}],
    "experience": [{"company": "Acme", "title": "Data Engineer", "start_date": "2019-07-01",
                    "responsibilities": ["Built ETL pipelines"], "achievements": ["Cut load time 40%"]}],
    "skills": [{"name": "Python", "proficiency_level": "Advanced", "years": 5}, {"name": "SQL", "proficiency_level": "Advanced"}]
  },
  "job": {"title": "Senior Data Engineer",
          "requirements": {"required_skills": ["Python", "SQL", "Airflow"], "experience_years": 5, "experience_level": "senior"}}
}'
```
