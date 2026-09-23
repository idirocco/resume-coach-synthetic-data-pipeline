import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, model_validator
from pydantic_core import PydanticCustomError

CompanySize = Literal["1-10", "11-50", "51-200", "201-1000", "1001-5000", "5001+"]
ExperienceLevel = Literal["intern", "entry", "mid", "senior", "lead", "executive"]

ALL_SIZES = frozenset({"1-10", "11-50", "51-200", "201-1000", "1001-5000", "5001+"})
ALL_LEVELS = frozenset({"intern", "entry", "mid", "senior", "lead", "executive"})

# Inclusive bounds. Executive has no upper limit.
YEAR_BANDS = {
    "intern": (0, 0),
    "entry": (0, 2),
    "mid": (3, 5),
    "senior": (5, 8),
    "lead": (8, 12),
    "executive": (10, None),
}


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


NonBlank = Annotated[str, AfterValidator(_non_blank)]


def _count_sentences(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return len(re.findall(r"[.!?](?:\s+[A-Z\"“]|\s*$)", stripped))


def _skill_key(skill: str) -> str:
    return " ".join(skill.lower().split())


@dataclass(frozen=True)
class TemplateConstraints:
    required_skills: tuple[int, int] = (5, 8)
    responsibilities: tuple[int, int] = (5, 7)
    description_sentences: tuple[int, int] = (8, 12)
    company_sizes: frozenset[str] = ALL_SIZES
    experience_levels: frozenset[str] = ALL_LEVELS
    is_niche_role: bool | None = None


TEMPLATE_CONSTRAINTS = {
    "formal_corporate": TemplateConstraints(
        company_sizes=frozenset({"1001-5000", "5001+"}),
    ),
    "casual_startup": TemplateConstraints(
        description_sentences=(6, 9),
        company_sizes=frozenset({"11-50", "51-200"}),
    ),
    "technical_detail": TemplateConstraints(
        required_skills=(6, 10),
        responsibilities=(6, 8),
        description_sentences=(10, 14),
    ),
    "achievement_metrics": TemplateConstraints(
        description_sentences=(7, 10),
    ),
    "career_changer": TemplateConstraints(
        experience_levels=frozenset({"entry", "mid"}),
    ),
    "niche_specialist": TemplateConstraints(
        is_niche_role=True,
    ),
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Company(StrictModel):
    name: NonBlank
    industry: NonBlank
    size: CompanySize
    location: NonBlank


class Requirements(StrictModel):
    required_skills: list[NonBlank] = Field(min_length=5, max_length=10)
    preferred_skills: list[NonBlank] = Field(min_length=3, max_length=5)
    education: NonBlank
    experience_years: int = Field(ge=0)
    experience_level: ExperienceLevel


class Metadata(StrictModel):
    trace_id: NonBlank
    generated_at: NonBlank
    is_niche_role: bool


class JobDescription(StrictModel):
    company: Company
    requirements: Requirements
    title: NonBlank
    description: NonBlank
    responsibilities: list[NonBlank] = Field(min_length=5, max_length=8)
    metadata: Metadata

    @model_validator(mode="after")
    def apply_rules(self, info: ValidationInfo) -> "JobDescription":
        problems = _rule_problems(self, info.context or {})
        if problems:
            raise PydanticCustomError("job_description_rules", "; ".join(problems))
        return self


def _in_range(count: int, bounds: tuple[int, int]) -> bool:
    low, high = bounds
    return low <= count <= high


def _rule_problems(job: JobDescription, context: dict) -> list[str]:
    problems = []
    requirements = job.requirements
    level = requirements.experience_level
    years = requirements.experience_years
    low, high = YEAR_BANDS[level]
    if years < low or (high is not None and years > high):
        band = f"{low}" if high == low else (f"{low} or more" if high is None else f"{low}-{high}")
        problems.append(f"experience_years {years} is outside the {level} band ({band})")

    required_keys = [_skill_key(skill) for skill in requirements.required_skills]
    preferred_keys = [_skill_key(skill) for skill in requirements.preferred_skills]
    if len(required_keys) != len(set(required_keys)):
        problems.append("required_skills contains duplicates")
    if len(preferred_keys) != len(set(preferred_keys)):
        problems.append("preferred_skills contains duplicates")
    overlap = sorted(set(required_keys) & set(preferred_keys))
    if overlap:
        problems.append("preferred_skills repeats required_skills: " + ", ".join(overlap))

    industry = context.get("industry")
    if industry is not None and job.company.industry != industry:
        problems.append("company.industry does not match the assigned industry")
    trace_id = context.get("trace_id")
    if trace_id is not None and job.metadata.trace_id != trace_id:
        problems.append("trace_id does not match the assigned value")
    generated_at = context.get("generated_at")
    if generated_at is not None and job.metadata.generated_at != generated_at:
        problems.append("generated_at does not match the assigned value")

    template = context.get("prompt_template")
    if template is None:
        return problems
    rules = TEMPLATE_CONSTRAINTS.get(template)
    if rules is None:
        problems.append(f"unknown prompt template: {template}")
        return problems

    if not _in_range(len(requirements.required_skills), rules.required_skills):
        low, high = rules.required_skills
        problems.append(f"required_skills must contain {low} to {high} items for {template}")
    if not _in_range(len(job.responsibilities), rules.responsibilities):
        low, high = rules.responsibilities
        problems.append(f"responsibilities must contain {low} to {high} items for {template}")
    sentences = _count_sentences(job.description)
    if not _in_range(sentences, rules.description_sentences):
        low, high = rules.description_sentences
        problems.append(f"description must be {low} to {high} sentences for {template}")
    if job.company.size not in rules.company_sizes:
        allowed = ", ".join(sorted(rules.company_sizes))
        problems.append(f"company.size must be one of {allowed} for {template}")
    notes = str(context.get("notes", "none")).strip().lower()
    if level not in rules.experience_levels and notes in {"", "none"}:
        allowed = ", ".join(sorted(rules.experience_levels))
        problems.append(f"experience_level must be one of {allowed} for {template}")
    if rules.is_niche_role is not None and job.metadata.is_niche_role is not rules.is_niche_role:
        problems.append(f"is_niche_role must be {str(rules.is_niche_role).lower()} for {template}")
    return problems


def parse_job_description(payload, *, industry, trace_id, generated_at, prompt_template, notes="none") -> JobDescription:
    return JobDescription.model_validate(
        payload,
        context={
            "industry": industry,
            "trace_id": trace_id,
            "generated_at": generated_at,
            "prompt_template": prompt_template,
            "notes": notes,
        },
    )


def _format_loc(loc) -> str:
    parts = []
    for item in loc:
        if isinstance(item, int) and parts:
            parts[-1] = f"{parts[-1]}[{item}]"
        else:
            parts.append(str(item))
    return ".".join(parts)


def validation_messages(exc: ValidationError) -> list[str]:
    messages = []
    for err in exc.errors():
        loc = _format_loc(err["loc"])
        msg = err["msg"]
        messages.append(f"{loc}: {msg}" if loc else msg)
    return messages
