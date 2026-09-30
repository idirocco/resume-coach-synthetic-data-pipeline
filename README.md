# Resume Coach Synthetic Data Pipeline

Generate and validate synthetic job descriptions, resumes, and resume-job pairs.

## Commands

```bash
python3 pipeline.py          # generate data (step1)
python3 pipeline.py step1    # generate data
python3 pipeline.py step2    # validate the newest complete source run
python3 pipeline.py all      # generate, then validate that run
```

Step1 requires `OPENROUTER_API_KEY` in the environment or `.env`. Step2 only needs the installed dependencies and source data; it does not call the model or require an API key.

## Generation

Generation uses the OpenRouter model `meta-llama/llama-3.1-8b-instruct`, configured in `config.py`. It writes `jobs_<UTC timestamp>.jsonl`, `resumes_<UTC timestamp>.jsonl`, and `pairs_<UTC timestamp>.jsonl` under `output/`. Pair rows reference job and resume trace IDs. Step1 decodes model replies as JSON objects but does not perform Pydantic schema validation.

## Validation

Step2 validates job descriptions, resumes, and pair records using Pydantic, including cross-record references and resume fit levels. When run by itself, it selects the newest timestamp for which all three source JSONL files exist. `all` validates the exact run it just generated.

Each validation invocation writes three artifacts under `output/`, named with its UTC timestamp:

- `validated_data_<timestamp>.json` contains validated records with their record type and source location.
- `invalid_<timestamp>.jsonl` contains failed source records, locations, and categorized errors.
- `schema_failure_modes_<timestamp>.json` summarizes category counts, failure percentages, common fields, and the observed validation success rate. The 90% success rate is a target, not a guarantee.
