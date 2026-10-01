---
name: iteration-log
description:
  'Log changes that affect pipeline behavior, prompts, configuration, thresholds, or validation rules to
  iteration_log.md. Use after running the synthetic-data pipeline (with --log), changing generator or validator
  settings, or recording keep/revert decisions and before/after metrics.'
---

# Iteration Log

Keep `iteration_log.md` current whenever a work iteration changes pipeline behavior, prompts, configuration, thresholds,
or validation rules. Repository instructions make this workflow always-on; this skill provides the steps and format.

## Procedure

1. Identify every relevant change made in the current iteration and its owning component, such as Generator, Validator,
   Labeler, Correction Loop, or API.
2. Find a comparable before/after metric in available test or pipeline output. Focus on current vs previous summary
   section on `schema_failure_modes_{timestamp}.json` file. Do not run a paid or external generation request solely to
   fill in the log unless the user asks.
3. Append one `## Iteration Log Entry` section to the end of `iteration_log.md` for the iteration, using the exact
   field/value table below.
4. State the observed delta, including its direction. If a metric or rationale is unavailable, write `Not measured` or
   `Not recorded`; do not infer or fabricate it.
5. Set `Keep/Revert` to the evidence-based decision and rationale. Use `Pending` when there is not enough evidence to
   decide.
6. Confirm that the entry is accurate and that `git diff --check` passes.

## Entry Format

```markdown
## Iteration N

| Field         | Value                                                               |
| ------------- | ------------------------------------------------------------------- |
| Date          | YYYY-MM-DD                                                          |
| Component     | Generator, Validator, Labeler, Correction Loop, API, or other owner |
| Change        | What was modified                                                   |
| Reason        | Why the change was made                                             |
| Before Metric | Measured value, or Not measured                                     |
| After Metric  | Measured value, or Not measured                                     |
| Delta         | Improvement/regression and amount, or Not measured                  |
| Keep/Revert   | Decision and rationale, or Pending                                  |
```

Use the current date in `YYYY-MM-DD` format. Append entries chronologically; do not rewrite prior entries to make
results look better.
