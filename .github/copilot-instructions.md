# Repository Instructions

At the end of every work iteration that changes pipeline behavior, prompts, configuration, thresholds, or validation
rules, append an entry to `iteration_log.md` using the format in that file. Record the measured before/after metric and
delta when available; never invent metrics or reasons. Use `Not measured` when no comparable metric exists and `Pending`
for a keep/revert decision that lacks evidence. Follow `.github/skills/iteration-log/SKILL.md` for the logging workflow.

## Commits

When asked to commit, keep each commit focused on one coherent change and use a concise, specific subject. Avoid unnecessary commit-body text.
