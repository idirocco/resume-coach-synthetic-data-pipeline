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
    normalized = skill.lower().replace(".js", " ")
    normalized = re.sub(r"\b\d+(?:\.\d+)*\b|(?<=[a-z])\d+(?:\.\d+)*\b", " ", normalized)
    parts = normalized.split()
    while parts and parts[-1] in {"developer", "engineer"}:
        parts.pop()
    return " ".join(parts).strip(" -_.")


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


FitLevel = Literal["excellent", "good", "partial", "poor", "complete_mismatch"]
ProficiencyLevel = Literal["Beginner", "Intermediate", "Advanced", "Expert"]


class ContactInfo(StrictModel):
    name: NonBlank
    email: NonBlank
    phone: NonBlank = Field(min_length=10)
    location: NonBlank
    linkedin: NonBlank | None = None
    portfolio: NonBlank | None = None

    @model_validator(mode="after")
    def validate_email(self) -> "ContactInfo":
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.email):
            raise ValueError("email must be a valid email address")
        return self


class Education(StrictModel):
    degree: NonBlank
    institution: NonBlank
    graduation_date: NonBlank
    gpa: float | None = Field(default=None, ge=0.0, le=4.0)
    coursework: list[NonBlank] | None = None

    @model_validator(mode="after")
    def validate_graduation_date(self) -> "Education":
        _parse_iso_date(self.graduation_date, "graduation_date")
        return self


class Experience(StrictModel):
    company: NonBlank
    title: NonBlank
    start_date: NonBlank
    end_date: NonBlank | None = None
    responsibilities: list[NonBlank] = Field(min_length=1, max_length=8)
    achievements: list[NonBlank] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_dates(self) -> "Experience":
        start_date = _parse_iso_date(self.start_date, "start_date")
        if self.end_date is not None:
            end_date = _parse_iso_date(self.end_date, "end_date")
            if end_date <= start_date:
                raise ValueError("end_date must be after start_date")
        return self


class ResumeSkill(StrictModel):
    name: NonBlank
    proficiency_level: ProficiencyLevel
    years: float | None = Field(default=None, ge=0.0, le=50.0)


class ResumeMetadata(StrictModel):
    trace_id: NonBlank
    generated_at: NonBlank
    prompt_template: NonBlank
    fit_level: FitLevel
    writing_style: NonBlank
    job_trace_id: NonBlank | None = None


class Resume(StrictModel):
    contact_info: ContactInfo
    education: list[Education] = Field(min_length=1, max_length=5)
    experience: list[Experience] = Field(min_length=1, max_length=8)
    skills: list[ResumeSkill] = Field(min_length=1, max_length=30)
    metadata: ResumeMetadata

    @model_validator(mode="after")
    def validate_fit_level(self, info: ValidationInfo) -> "Resume":
        required_skills = info.context.get("required_skills", []) if info.context else []
        expected_fit_level = info.context.get("fit_level") if info.context else None
        if not required_skills:
            return self

        required_keys = {_skill_key(skill) for skill in required_skills}
        resume_keys = {_skill_key(skill.name) for skill in self.skills}
        union = required_keys | resume_keys
        overlap = len(required_keys & resume_keys) / len(union) if union else 0.0
        actual_fit_level = fit_level_for_overlap(overlap)
        if actual_fit_level != self.metadata.fit_level:
            raise ValueError(
                f"metadata.fit_level is {self.metadata.fit_level}, but normalized required-skill overlap "
                f"{overlap:.0%} is {actual_fit_level}"
            )
        if expected_fit_level is not None and actual_fit_level != expected_fit_level:
            raise ValueError(
                f"normalized required-skill overlap {overlap:.0%} must be {expected_fit_level}"
            )
        return self


def fit_level_for_overlap(overlap: float) -> FitLevel:
    if overlap >= 0.8:
        return "excellent"
    if overlap >= 0.6:
        return "good"
    if overlap >= 0.4:
        return "partial"
    if overlap >= 0.2:
        return "poor"
    return "complete_mismatch"


def _parse_iso_date(value: str, field_name: str):
    from datetime import date

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date (YYYY-MM-DD)") from exc


def parse_resume(payload, *, required_skills, fit_level) -> Resume:
    return Resume.model_validate(
        payload,
        context={"required_skills": required_skills, "fit_level": fit_level},
    )


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
