# Iteration Log

## Iteration 0

| Field | Value |
| --- | --- |
| Date | 2026-09-30 |
| Component | Jobs Generator |
| Change | Baseline |
| Reason | Not recorded |
| Before Metric | Not measured |
| After Metric | Validated 10 records: 2 valid, 8 invalid, 0 blocked (20.0% success) |
| Delta | Not measured |
| Keep/Revert | Pending; |

## Iteration 1

| Field | Value |
| --- | --- |
| Date | 2026-10-01 |
| Component | Jobs Generator |
| Change | Set an exact description sentence target and added a field-specific recount instruction to all job-description prompts |
| Reason | The latest validation report had 8 of 10 job records fail because description sentence counts were outside their required ranges |
| Before Metric | Validated 10 records: 2 valid, 8 invalid, 0 blocked (20.0% success). |
| After Metric | Validated 10 records: 3 valid, 7 invalid, 0 blocked (30.0% success). |
| Delta | 10.0% |
| Keep/Revert | Keep. There's more room for improvement to reach the 90% success rate |

## Iteration 2

| Field | Value |
| --- | --- |
| Date | 2026-10-01 |
| Component | Jobs Generator |
| Change | Clarified description sentence boundaries in all job-description prompts: one paragraph, period endings, uppercase sentence starts, and no period-containing abbreviations or initials |
| Reason | The latest validation still reported description sentence-count failures for technical_detail and niche_specialist after exact-count prompts were added |
| Before Metric | Validated 10 records: 3 valid, 7 invalid, 0 blocked (30.0% success). |
| After Metric | Validated 10 records: 6 valid, 4 invalid, 0 blocked (60.0% success). |
| Delta | 30.0% |
| Keep/Revert | Keep. There's more room for improvement to reach the 90% success rate |

## Iteration 3

| Field | Value |
| --- | --- |
| Date | 2026-10-01 |
| Component | Jobs Generator |
| Change | Added explicit JSON array-of-strings rules for skill and responsibility fields and an exact six-item responsibility target to all job prompts; achievement metrics must be encoded in responsibility strings |
| Reason | The latest report showed scalar or object values in list fields and one responsibilities list exceeding the schema limit |
| Before Metric | Validated 10 records: 6 valid, 4 invalid, 0 blocked (60.0% success). |
| After Metric | Validated 10 records: 7 valid, 3 invalid, 0 blocked (70.0% success). |
| Delta | 10.0% |
| Keep/Revert | Keep. There's more room for improvement to reach the 90% success rate |

## Iteration 4

| Field | Value |
| --- | --- |
| Date | 2026-10-01 |
| Component | Jobs Generator |
| Change | Added per-sentence planning slots and validator-aligned sentence-ending instructions to casual_startup, technical_detail, and niche_specialist description prompts |
| Reason | All 3 invalid jobs in the latest report failed description sentence-count validation |
| Before Metric | Validated 10 records: 7 valid, 3 invalid, 0 blocked (70.0% success) |
| After Metric | Validated 10 records: 9 valid, 1 invalid, 0 blocked (90.0% success) |
| Delta | 20.0% improvement |
| Keep/Revert | Keep. The 90.0% success-rate target was reached |

## Iteration 5

| Field | Value |
| --- | --- |
| Date | 2026-10-01 |
| Component | Resume Generator |
| Change | Rewrote the controlled_fit resume prompt: the pipeline now picks the exact skills to list (rotated per resume) and the experience years and level per fit level, and the prompt gets delimited target and skills blocks, a date anchor, schema counts, style definitions, a realistic JSON example and a self-check. generate_resume_one now validates each resume against the schema and feeds the errors back for correction |
| Reason | The model had to compute the Jaccard overlap and skill normalization itself, experience and seniority gaps per fit level were uncontrolled, and fit-level errors were never corrected during generation |
| Before Metric | Not measured |
| After Metric | Validated 46 records: 45 valid, 1 invalid, 0 blocked (97.83% success) |
| Delta | Not measured; no comparable pre-refactor full step2 run |
| Keep/Revert | Keep. Full step2 now validates independently generated source stages and exceeded the 90% success-rate target |

## Iteration 6

| Field | Value |
| --- | --- |
| Date | 2026-10-01 |
| Component | Resume Validation |
| Change | Added rule-based hallucination detection and awkward-language checks to the resume validation pass; invalid resumes are rejected when they oversell expertise, describe impossible timelines, or rely on buzzword-heavy AI phrasing. The default resume-generation count was also reset to 5 to match the intended fit-level matrix. |
| Reason | The validation layer was still accepting implausible expert claims and buzzword-heavy text even though the spec explicitly calls for hallucination and awkward-language detection. |
| Before Metric | Validated 46 records: 45 valid, 1 invalid, 0 blocked (97.83% success) |
| After Metric | Validated 46 records: 33 valid, 7 invalid, 6 blocked (71.74% success).
| Delta | -26.09% |
| Keep/Revert | Keep. There's more room for improvement to reach the 90% success rate |

## Iteration 7

| Field | Value |
| --- | --- |
| Date | 2026-10-01 |
| Component | Resume Generation and Validation |
| Change | Clarified that experience entries must be sequential and non-overlapping, with the prior role ending the day before a direct transition; corrected timeline validation to compare employment periods chronologically regardless of resume display order |
| Reason | The latest report flagged six resumes for overlapping timelines, including valid newest-first histories; four remaining records have same-day end/start transitions |
| Before Metric | Validated 46 records: 33 valid, 7 invalid, 6 blocked (71.74% success) |
| After Metric | Validated 46 records: 37 valid, 5 invalid, 4 blocked (80.43% success) |
| Delta | +8.69% |
| Keep/Revert | Keep. Overall validation improved; remaining timeline failures reflect same-day job transitions and the 90% target is not yet met |

## Iteration 8

| Field | Value |
| --- | --- |
| Date | 2026-10-08 |
| Component | Resume Validation |
| Change | Timeline overlap check now flags a role only when it starts strictly before the previous role ends (`<` instead of `<=`), so a same-day job transition is no longer treated as overlapping |
| Reason | All four resumes still rejected after iteration 7 were same-day transitions (e.g. one role ends 2025-10-01 and the next starts 2025-10-01), which is a realistic history, not a hallucination |
| Before Metric | Validated 46 records: 37 valid, 5 invalid, 4 blocked (80.43% success) on the 20261001 sources |
| After Metric | Validated 46 records: 45 valid, 1 invalid, 0 blocked (97.83% success) on the same sources |
| Delta | +17.4% |
| Keep/Revert | Keep. The remaining failure is one job with missing required fields |

## Iteration 9

| Field | Value |
| --- | --- |
| Date | 2026-10-14 |
| Component | Visualization |
| Change | Added `step4_visualization.py` (`python3 pipeline.py step4`, and the last step of the full run): 10 PNG charts (failure-mode correlation, failure rates by fit level / job template / writing style / niche vs standard, schema validation heatmap, hallucination by seniority, skills overlap by fit level, correction success by category, attempts per fix) plus a `failure_rates_table.csv` table view in `visualizations/{ts}/`. Targets (`FAILURE_TARGETS`) are in `config.py`; charts without data are placeholder PNGs |
| Reason | SPEC step 4: show failure patterns across fit levels, templates and roles |
| Before Metric | Not measured |
| After Metric | 10 charts rendered for the 20261014T093233 run (25 pairs, 5 jobs). The schema heatmap, hallucination stack, niche comparison and both correction charts have no data in this run (0 invalid records, 0 hallucination or awkward-language flags, 0 niche jobs) |
| Delta | Not measured; first run |
| Keep/Revert | Keep |

## Iteration 10

| Field | Value |
| --- | --- |
| Date | 2026-10-14 |
| Component | API |
| Change | Added the step 5 REST API (`api.py`, `api_models.py`, `uvicorn api:app`): `POST /review-resume` (resume-side checks always, job fit and integrity view when a job is sent, triggered flags, schema warnings, detail), `GET /health`, `GET /analysis/failure-rates` (newest `failure_stats_*.json`). Split `label_pair` into `resume_checks` + `job_fit_checks` so the API reuses step 3; `job_fit_checks` also returns `actual_fit_level`, and scores no skill overlap when a job lists no required skills (unreachable for pipeline jobs, which require 5+). LLM judge deferred |
| Reason | SPEC step 5: serve the failure analysis for real-time review |
| Before Metric | - |
| After Metric | On the 49 valid pairs of 20261014T132013219616Z: API flags equal `label_pair` flags for 49/49, API fit level equals step 2 `actual_fit_level` for 49/49, slowest review 61 ms (target <2 s). Step 3 labels unchanged by the refactor (0 differences on the same 49 pairs). 109 tests pass (21 new API tests) |
| Delta | Not measured; first API version |
| Keep/Revert | Keep. The <10 s LLM-judge budget is untested because the judge is not built |
