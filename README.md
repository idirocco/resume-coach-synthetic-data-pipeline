# Resume Coach Synthetic Data Pipeline
 Production-grade synthetic data pipeline that generates, validates, and analyzes resume-job description pairs using LLMs.

Running `python3 pipeline.py` generates job descriptions and, for each valid job, 5 resumes by default with one resume in each controlled fit band. Set `RESUMES_PER_JOB` in `config.py` to any value from 5 through 10.

Generation currently uses the OpenRouter model `meta-llama/llama-3.1-8b-instruct`, set in `config.py`.

Each run writes `jobs_<UTC timestamp>.jsonl`, `resumes_<UTC timestamp>.jsonl`, and `pairs_<UTC timestamp>.jsonl` under `output/`. Pair rows contain a pair ID, the job and resume trace IDs, fit level, and generation timestamp.
