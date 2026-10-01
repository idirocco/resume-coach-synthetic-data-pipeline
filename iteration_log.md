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
