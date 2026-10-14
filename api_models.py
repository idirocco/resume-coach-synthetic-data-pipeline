"""Request/response models for api.py.

Field rules come from schemas.py (contact info, education, experience, skills, company). What is relaxed for
real-world input: metadata is optional, and skills/experience/responsibility counts have no pipeline minimums.
"""

from pydantic import BaseModel, Field, model_validator

from schemas import (
    Company,
    ContactInfo,
    Education,
    Experience,
    ExperienceLevel,
    FitLevel,
    NonBlank,
    ResumeSkill,
    StrictModel,
    _parse_iso_datetime,
)


class ReviewResumeMetadata(StrictModel):
    trace_id: NonBlank | None = None
    generated_at: NonBlank | None = Field(
        default=None, description="ISO datetime; ongoing roles are counted up to this date (default: today)."
    )
    prompt_template: NonBlank | None = None
    fit_level: FitLevel | None = Field(
        default=None, description="Intended fit against the job; enables the integrity view."
    )
    writing_style: NonBlank | None = None
    job_trace_id: NonBlank | None = None

    @model_validator(mode="after")
    def validate_generated_at(self) -> "ReviewResumeMetadata":
        if self.generated_at is not None:
            _parse_iso_datetime(self.generated_at, "generated_at")
        return self


class ReviewResume(StrictModel):
    contact_info: ContactInfo
    education: list[Education] = Field(min_length=1)
    experience: list[Experience] = Field(default_factory=list)
    skills: list[ResumeSkill] = Field(default_factory=list)
    metadata: ReviewResumeMetadata | None = None


class ReviewRequirements(StrictModel):
    required_skills: list[NonBlank] = Field(default_factory=list)
    preferred_skills: list[NonBlank] = Field(default_factory=list)
    education: NonBlank | None = None
    experience_years: int = Field(ge=0, le=50)
    experience_level: ExperienceLevel


class ReviewJobMetadata(StrictModel):
    trace_id: NonBlank | None = None
    generated_at: NonBlank | None = None
    is_niche_role: bool | None = None


class ReviewJob(StrictModel):
    title: NonBlank
    company: Company | None = None
    description: NonBlank | None = None
    responsibilities: list[NonBlank] = Field(default_factory=list)
    requirements: ReviewRequirements
    metadata: ReviewJobMetadata | None = None


class ReviewRequest(StrictModel):
    resume: ReviewResume
    job: ReviewJob | None = Field(default=None, description="Omit to run only the resume-side checks.")


# --- Responses ---------------------------------------------------------------


class ResumeChecks(BaseModel):
    resume_seniority: int
    resume_seniority_name: str
    resume_seniority_source: str
    resume_years: float
    expert_skill_count: int
    hallucination_reasons: list[str]
    buzzword_density: float
    buzzword_hits: list[str]
    repetition_flag: bool
    awkward_language_reasons: list[str]


class JobFit(BaseModel):
    job_experience_level: str
    job_seniority: int
    job_seniority_name: str
    seniority_gap: int
    required_years: int
    experience_gap_years: float
    experience_ratio: float | None
    skills_jaccard: float | None = Field(description="Null when the job lists no required skills.")
    actual_fit_level: FitLevel | None
    matched_skills: list[str]
    core_skills: list[str]
    missing_core_skills: list[str]


class Integrity(BaseModel):
    intended_fit_level: FitLevel
    actual_fit_level: FitLevel
    skills_jaccard: float
    met_intended_fit: bool


class ReviewResponse(BaseModel):
    resume_checks: ResumeChecks
    job_fit: JobFit | None
    integrity: Integrity | None = Field(
        description="Null without a job, without required skills, or without resume.metadata.fit_level."
    )
    flags: dict[str, bool] = Field(description="Only the flags that apply: 2 resume-side flags without a job, all 6 with one.")
    triggered_flags: list[str]
    failure_count: int
    schema_warnings: list[str] = Field(description="What the strict pipeline schemas would reject; informational only.")
    detail: list[str]
