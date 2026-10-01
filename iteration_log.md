# Iteration Log

## Iteration 0

| Field | Value |
| --- | --- |
| Date | 2026-09-30 |
| Component | Generator |
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
| Component | Generator |
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
| Component | Generator |
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
| Component | Generator |
| Change | Added explicit JSON array-of-strings rules for skill and responsibility fields and an exact six-item responsibility target to all job prompts; achievement metrics must be encoded in responsibility strings |
| Reason | The latest report showed scalar or object values in list fields and one responsibilities list exceeding the schema limit |
| Before Metric | Validated 10 records: 6 valid, 4 invalid, 0 blocked (60.0% success). |
| After Metric | Validated 10 records: 7 valid, 3 invalid, 0 blocked (70.0% success). |
| Delta | 10.0% |
| Keep/Revert | Keep. There's more room for improvement to reach the 90% success rate |