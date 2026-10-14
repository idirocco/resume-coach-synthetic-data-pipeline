"""Error context and correction prompts, shared by step 1's retries and the step 2 correction loop."""

import json

# Overlap band each fit level must land in (see schemas.fit_level_for_overlap).
FIT_LEVEL_BANDS = {
    "excellent": (0.8, 1.0),
    "good": (0.6, 0.8),
    "partial": (0.4, 0.6),
    "poor": (0.2, 0.4),
    "complete_mismatch": (0.0, 0.2),
}
TYPE_NAMES = {
    "string_type": "a string",
    "int_type": "an integer",
    "int_parsing": "an integer",
    "float_type": "a number",
    "bool_type": "true or false",
    "list_type": "a JSON array",
    "dict_type": "a JSON object",
    "model_type": "a JSON object",
}
MAX_VALUE_CHARS = 300
CORRECTION_INSTRUCTIONS = (
    "Keep every field that is not listed above unchanged. Return only the corrected JSON object."
)


def _value_at(data, loc):
    current = data
    for part in loc:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and isinstance(part, int) and part < len(current):
            current = current[part]
        else:
            return None
    return current


def _short(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= MAX_VALUE_CHARS else text[:MAX_VALUE_CHARS] + "..."


def _expected(error, context):
    error_type = error.get("type", "")
    ctx = error.get("ctx") or {}
    message = error.get("msg", "")
    if error_type == "missing":
        return "required field; add it"
    if error_type == "extra_forbidden":
        return "not part of the schema; remove it"
    if error_type == "json_decode":
        return "a single valid JSON object"
    if error_type == "literal_error":
        return f"one of {ctx.get('expected', 'the allowed values')}"
    if error_type in TYPE_NAMES:
        return TYPE_NAMES[error_type]
    if error_type == "too_short":
        return f"at least {ctx.get('min_length')} items"
    if error_type == "too_long":
        return f"at most {ctx.get('max_length')} items"
    if error_type in {"greater_than_equal", "greater_than"}:
        return f"a value >= {ctx.get('ge', ctx.get('gt'))}"
    if error_type in {"less_than_equal", "less_than"}:
        return f"a value <= {ctx.get('le', ctx.get('lt'))}"
    if "required-skill overlap" in message or "fit_level" in message:
        fit_level = context.get("fit_level")
        low, high = FIT_LEVEL_BANDS.get(fit_level, (None, None))
        return (
            f"skills overlap with the job's required skills {json.dumps(context.get('required_skills', []))} "
            f"must be in [{low}, {high}) for fit level {fit_level}; overlap = shared skills / all distinct skills"
        )
    return message.removeprefix("Value error, ")


def error_context(errors, data, context=None):
    """One entry per error: field_path, error_type, invalid_value, expected."""
    context = context or {}
    entries = []
    for error in errors:
        loc = list(error.get("loc") or [])
        if "input" in error:
            value = error["input"]
        else:
            value = _value_at(data, loc) if isinstance(data, (dict, list)) else data
        entries.append(
            {
                "field_path": ".".join(str(part) for part in loc) or "<record>",
                "error_type": error.get("type", "unknown"),
                "invalid_value": _short(value) if value is not None else None,
                "expected": _expected(error, context),
            }
        )
    return entries


def build_correction_prompt(entries, original, extra_instructions=None):
    original_text = original if isinstance(original, str) else json.dumps(original, ensure_ascii=False, indent=2)
    lines = [
        "The following data failed validation with these errors:",
        json.dumps(entries, ensure_ascii=False, indent=2),
        "",
        "Original data:",
        original_text,
        "",
        "Please generate a corrected version that fixes these issues.",
        CORRECTION_INSTRUCTIONS,
    ]
    if extra_instructions:
        lines.append(extra_instructions)
    return "\n".join(lines)
