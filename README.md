# Resume Coach Synthetic Data Pipeline

Generate and validate synthetic job descriptions, resumes, and resume-job pairs.

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
```

`step1` runs generation in dependency order: jobs, resumes, then pairs. Omit the selector to generate all three. Its selectors are mutually exclusive:

- `--only-jobs` generates job descriptions; it has no data-file dependencies.
- `--only-resumes` generates resumes from the newest existing jobs JSONL file. It exits with an explicit error if no usable jobs file exists.
- `--only-pairs` creates pairs from the newest existing jobs and resumes JSONL files. It validates that both files exist and that each resume references a job in the jobs file before writing pairs.

Jobs-only and resume-only require `OPENROUTER_API_KEY` in the environment or `.env`; pair-only does not call the model. Step2 only needs the installed dependencies and source data; it does not call the model or require an API key.

## Generation

Generation uses the OpenRouter model `meta-llama/llama-3.1-8b-instruct`, configured in `config.py`. It writes `jobs_<UTC timestamp>.jsonl`, `resumes_<UTC timestamp>.jsonl`, and `pairs_<UTC timestamp>.jsonl` under `output/`. Pair rows reference job and resume trace IDs. Step1 decodes model replies as JSON objects but does not perform Pydantic schema validation.

## Validation

Step2 validates job descriptions, resumes, and pair records using Pydantic, including cross-record references and resume fit levels. Without a selector, it validates the newest timestamp for which all three source JSONL files exist. Its mutually exclusive selectors are:

- `--only-jobs` validates the newest jobs JSONL file only.
- `--only-resumes` validates the newest jobs and resumes files; job records are checked as dependencies, but only resume results are included in the report.
- `--only-pairs` validates the newest jobs, resumes, and pairs files; jobs and resumes are checked as dependencies, but only pair results are included in the report.

Selected modes choose the newest file for each required type independently, so separately generated stages can be checked together. Step2 reports a clear missing-file error when a required source is unavailable. Running `python3 pipeline.py` with no arguments generates all three artifact types and validates the exact run it just generated. Use `step1` or `step2` to run a single step.

Each validation invocation writes three artifacts under `output/`, named with its UTC timestamp:

- `validated_data_<timestamp>.json` contains validated records with their record type and source location.
- `invalid_<timestamp>.jsonl` contains failed source records, locations, and categorized errors.
- `schema_failure_modes_<timestamp>.json` summarizes category counts, failure percentages, common fields, and the observed validation success rate. The 90% success rate is a target, not a guarantee.
