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
| Keep/Revert | Pending; rationale and comparable metrics were not recorded |

## Iteration 1

| Field | Value |
| --- | --- |
| Date | 2026-10-01 |
| Component | Jobs Generator |
| Change | Set an exact description sentence target and added a field-specific recount instruction to all job-description prompts |
| Reason | The latest validation report had 6 of 10 job records fail because description sentence counts were outside their required ranges |
| Before Metric | Validated 10 records: 2 valid, 8 invalid, 0 blocked (20.0% success). |
| After Metric | Validated 10 records: 3 valid, 7 invalid, 0 blocked (30.0% success). |
| Delta | 10.0& |
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
| Delta | +8.69 percentage points; 4 fewer invalid records and 2 fewer blocked records |
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
| Delta | +17.4 percentage points; 4 fewer invalid resumes and 4 fewer blocked pairs |
| Keep/Revert | Keep. The remaining failure is one job with missing required fields |

## Iteration 9

| Field | Value |
| --- | --- |
| Date | 2026-10-08 |
| Component | Resume Validation |
| Change | Moved hallucination and awkward-language checks into the shared `resume_metrics.py` and recorded them as warnings on valid resumes instead of rejections. Hallucination now flags 20+ Expert skills (was 30+ total skills, above the schema cap of 30) and skill years longer than the career span plus one year. Awkward language now uses buzzword density (more than 2 per 100 words), more than 5 distinct buzzwords, or triple-word repetition, instead of flagging any single buzzword. Job template rule failures are split into one error per field, model-level errors point at the field they name, errors keep Pydantic `input`/`ctx`, and the report adds a field × category matrix. Step 2 also writes `pairs_enriched_{ts}.jsonl` for step 3 |
| Reason | Content-quality signals are what step 3 analyzes, so rejecting them removed the data; the old hallucination threshold could not fire; per-field errors are needed for the schema heatmap and the correction loop |
| Before Metric | Validated 46 records: 45 valid, 1 invalid, 0 blocked (97.83% success) on the 20261001 sources |
| After Metric | Validated 46 records: 45 valid, 1 invalid, 0 blocked (97.83% success); 0 records with warnings |
| Delta | No change in success rate on these sources; success rate no longer counts hallucination or awkward-language findings, so it is not comparable with iterations 6-7 |
| Keep/Revert | Keep |

## Iteration 10

| Field | Value |
| --- | --- |
| Date | 2026-10-08 |
| Component | Correction Loop |
| Change | Added `step2_correction.py` (`python3 pipeline.py correct`, and part of the full run after validation). For each invalid job or resume it sends the error context (field path, error type, invalid value, expected format) and the original record back to the LLM, re-validates, and retries up to `MAX_ATTEMPTS` (3). Pipeline-assigned ids are restored after every reply, and pair or id errors are marked not correctable. Corrected records go to `corrected_{jobs,resumes}_{ts}.jsonl`, which step 2 then re-validates. Step 1's retry messages now use the same error context and prompt builder (`correction.py`) |
| Reason | SPEC calls for a correction loop with >50% success within 3 attempts; step 1 never schema-checks jobs, so job errors were only found in step 2 and never fixed |
| Before Metric | Validated 46 records: 45 valid, 1 invalid, 0 blocked (97.83% success) on the 20261001 sources |
| After Metric | Corrected 1 of 1 correctable invalid records on attempt 3 (100%); re-validation: 46 valid, 0 invalid (100.0% success) |
| Delta | +2.17 percentage points validation success; correction success rate not meaningful on 1 record |
| Keep/Revert | Pending; needs a larger generation run to measure the >50% target |

## Iteration 11

| Field | Value |
| --- | --- |
| Date | 2026-10-08 |
| Component | Failure Analysis |
| Change | Added `step3_failure_analysis.py` (`python3 pipeline.py step3`, and part of the full run after correction). It labels every pair in `pairs_enriched_{ts}.jsonl` whose job and resume validated with six flags (skills gap: Jaccard < 0.4; experience: resume years < 50% of required; seniority: level gap > 1; missing any of the first 3 required skills; hallucination; awkward language) plus the numeric values behind them, and writes `failure_labels_{ts}.jsonl` and `failure_stats_{ts}.json` (rates overall and by fit level, job template, writing style, niche, seniority; phi correlation; distributions; 10-pair Jaccard spot check against step 2) |
| Reason | SPEC step 3: explain why a resume fails to match a job, and provide the data step 4 charts |
| Before Metric | Not measured |
| After Metric | 18 pairs labeled, 0 skipped (20261008T150517 validation; only excellent/good fits). Flag rates: skills gap 0%, experience 0%, seniority 11%, missing core skills 50%, hallucination 0%, awkward language 0%. Jaccard spot check matched step 2 on 10/10 pairs |
| Delta | Not measured; first run |
| Keep/Revert | Keep |

## Iteration 12

| Field | Value |
| --- | --- |
| Date | 2026-10-08 |
| Component | Failure Analysis and Resume Generator |
| Change | (1) Seniority mapping: "Manager" moved from level 3 to level 2, and an Assistant/Associate/Asst qualifier lowers a title one level (e.g. "Assistant Store Manager" = 1, "Associate Director" = 3). (2) `select_resume_skills` now always includes the first `CORE_SKILL_COUNT` (3) required skills for excellent and good fits and rotates only the remaining skills; partial/poor/complete_mismatch are unchanged. `CORE_SKILL_COUNT` moved to `config.py` and is shared with step 3 |
| Reason | (1) Both seniority mismatches in iteration 11 were mid-level jobs matched to "Store Manager"/"Facilities Manager" resumes, which are mid-level roles in those industries. (2) All 9 missing-core-skill flags were good fits that the generator's rotation had made omit one of the first three required skills |
| Before Metric | Seniority mismatch 11% (2/18), missing core skills 50% (9/18) on the 20261008T150517 validation |
| After Metric | Seniority mismatch 0% (0/18) on the same data. Missing core skills still 50% on existing data: the generator change only applies to newly generated resumes |
| Delta | Seniority mismatch -11 percentage points; missing core skills not yet measured |
| Keep/Revert | Keep (1). Pending (2) until a new generation run |

## Iteration 14

| Field | Value |
| --- | --- |
| Date | 2026-10-08 |
| Component | Validator |
| Change | Compared validation success rate for jobs, pairs, resumes using `--log` |
| Reason | Not recorded |
| Before Metric | 100.0% success rate (20261008T150517125129Z) |
| After Metric | 100.0% success rate (20261008T230347229454Z) |
| Delta | No change of 0 percentage points |
| Keep/Revert | Pending; a run comparison alone does not establish a code-change decision |

## Iteration 15

| Field | Value |
| --- | --- |
| Date | 2026-10-14 |
| Component | Validator |
| Change | Compared validation success rate for jobs, pairs, resumes using `--log` |
| Reason | Not recorded |
| Before Metric | 100.0% success rate (20261008T230347229454Z) |
| After Metric | 100.0% success rate (20261014T093233843676Z) |
| Delta | No change of 0 percentage points |
| Keep/Revert | Pending; a run comparison alone does not establish a code-change decision |

## Iteration 13

| Field | Value |
| --- | --- |
| Date | 2026-10-14 |
| Component | Resume Generator |
| Change | Measured iteration 12's core-skills change on a new generation run (jobs_20261013T204224Z: 5 jobs written of 10 planned, 25 resumes, 25 pairs) |
| Reason | Iteration 12 left the generator change Pending until a new run |
| Before Metric | Missing core skills 50% (9/18, good fits only) on the 20261008 data |
| After Metric | Missing core skills 0% for excellent (0/5) and good (0/5); partial, poor and complete_mismatch 100% (15/15, expected: their prompts still omit core skills). Validation 55/55 valid (100%); correction had nothing to fix |
| Delta | -50 percentage points for good fits (9/18 to 0/5 missing); excellent was not measured before |
| Keep/Revert | Keep. Only 5 of 10 jobs were written, so no niche_specialist job exists in this run and the correction success rate is still unmeasured |

## Iteration 14

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
