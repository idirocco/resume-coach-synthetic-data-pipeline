"""Deterministic resume/job metrics shared by step 2 (validation warnings) and step 3 (failure labels).

Everything here is a pure function of plain dicts, so both steps compute identical values.
"""

import re
from datetime import date

# --- Skills -----------------------------------------------------------------


def skill_key(skill: str) -> str:
    """Normalize a skill name: lowercase, drop versions and .js, strip trailing developer/engineer."""
    normalized = skill.lower().replace(".js", " ")
    normalized = re.sub(r"\b\d+(?:\.\d+)*\b|(?<=[a-z])\d+(?:\.\d+)*\b", " ", normalized)
    parts = normalized.split()
    while parts and parts[-1] in {"developer", "engineer"}:
        parts.pop()
    return " ".join(parts).strip(" -_.")


def jaccard(required_skills, resume_skill_names):
    """Jaccard overlap of normalized required skills vs. resume skills (same formula as Resume.validate_fit_level)."""
    required = {skill_key(skill) for skill in required_skills}
    resume = {skill_key(skill) for skill in resume_skill_names}
    union = required | resume
    intersection = required & resume
    return {
        "required": sorted(required),
        "resume": sorted(resume),
        "intersection": sorted(intersection),
        "union_size": len(union),
        "score": len(intersection) / len(union) if union else 0.0,
    }


# --- Experience timeline ----------------------------------------------------


def _parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def as_of_date(resume):
    """Reference date for ongoing roles: the resume's generated_at, so results are reproducible."""
    metadata = resume.get("metadata") or {}
    return _parse_date(metadata.get("generated_at")) or date.today()


def employment_periods(resume):
    """Sorted (start, end) date pairs; ongoing roles end at as_of_date."""
    as_of = as_of_date(resume)
    periods = []
    for entry in resume.get("experience") or []:
        if not isinstance(entry, dict):
            continue
        start = _parse_date(entry.get("start_date"))
        if start is None:
            continue
        end = _parse_date(entry.get("end_date")) if entry.get("end_date") else as_of
        if end is None:
            continue
        periods.append((start, end))
    return sorted(periods)


def has_overlapping_roles(periods):
    """A role overlaps when it starts strictly before the previous one ends; same-day transitions are fine."""
    return any(next_start < previous_end for (_, previous_end), (next_start, _) in zip(periods, periods[1:]))


def resume_years(resume):
    """Total years worked, counting overlapping periods once."""
    total_days = 0
    current_start = current_end = None
    for start, end in employment_periods(resume):
        if current_end is None or start > current_end:
            if current_end is not None:
                total_days += (current_end - current_start).days
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_end is not None:
        total_days += (current_end - current_start).days
    return round(max(0, total_days) / 365.25, 2)


def career_span_years(resume):
    """Years from the first role's start to as_of_date, gaps included."""
    periods = employment_periods(resume)
    if not periods:
        return 0.0
    return round(max(0, (as_of_date(resume) - periods[0][0]).days) / 365.25, 2)


# --- Seniority --------------------------------------------------------------

SENIORITY_NAMES = {0: "Entry/Junior", 1: "Mid/Intermediate", 2: "Senior", 3: "Lead/Principal/Staff", 4: "Executive/Director/VP"}
JOB_LEVEL_SENIORITY = {"intern": 0, "entry": 0, "mid": 1, "senior": 2, "lead": 3, "executive": 4}
# Checked from the highest level down, so "Senior Director" is 4. Whole-word matches only.
TITLE_SENIORITY_PATTERNS = (
    (4, r"executive|director|vp|vice president|chief|ceo|cto|cfo|coo|cio|ciso|president|head of"),
    (3, r"lead|principal|staff"),
    (2, r"senior|sr|manager"),
    (1, r"mid|intermediate"),
    (0, r"entry|junior|jr|intern|trainee|apprentice"),
)
# "Assistant Store Manager" or "Associate Director" sit one level below the keyword they qualify.
JUNIOR_QUALIFIER_PATTERN = r"\b(?:assistant|associate|asst)\b"
# Fallback when the title has no keyword; YEAR_BANDS in schemas.py with overlaps removed.
YEAR_SENIORITY_CUTOFFS = ((12, 4), (8, 3), (5, 2), (3, 1))


def title_seniority(title):
    lowered = str(title or "").lower()
    for level, pattern in TITLE_SENIORITY_PATTERNS:
        if re.search(rf"\b(?:{pattern})\b", lowered):
            if level > 0 and re.search(JUNIOR_QUALIFIER_PATTERN, lowered):
                return level - 1
            return level
    return None


def years_seniority(years):
    for cutoff, level in YEAR_SENIORITY_CUTOFFS:
        if years >= cutoff:
            return level
    return 0


def most_recent_title(resume):
    entries = [entry for entry in resume.get("experience") or [] if isinstance(entry, dict)]
    if not entries:
        return None
    # Ongoing roles first, then latest start date.
    latest = max(entries, key=lambda entry: (entry.get("end_date") is None, str(entry.get("start_date") or "")))
    return latest.get("title")


def infer_resume_seniority(resume):
    """(level, source) from the most recent title's keywords, else from total years."""
    level = title_seniority(most_recent_title(resume))
    if level is not None:
        return level, "title"
    return years_seniority(resume_years(resume)), "years"


# --- Hallucination ----------------------------------------------------------

EXCESSIVE_EXPERT_SKILLS = 20
ENTRY_OVERCLAIM_YEARS = 2
ENTRY_OVERCLAIM_EXPERT_SKILLS = 10
# Skills may predate the first job (degree, projects), so allow one year of slack.
SKILL_YEARS_SLACK = 1
ABSOLUTE_CLAIM_PATTERN = re.compile(r"\b(?:expert|certified)\s+(?:in|across)\s+(?:all|everything|every(?:thing)?)\b")
HALLUCINATION_REASONS = ("excessive_expert", "entry_overclaim", "impossible_timeline", "absolute_claims")


def expert_skill_count(resume):
    return sum(
        1
        for skill in resume.get("skills") or []
        if isinstance(skill, dict) and str(skill.get("proficiency_level", "")).lower() == "expert"
    )


def resume_text(resume):
    chunks = []
    for key in ("title", "description", "responsibilities"):
        value = resume.get(key)
        if isinstance(value, str):
            chunks.append(value)
        elif isinstance(value, list):
            chunks.extend(str(item) for item in value if isinstance(item, str))
    for entry in resume.get("experience") or []:
        if isinstance(entry, dict):
            for key in ("title", "responsibilities", "achievements"):
                value = entry.get(key)
                if isinstance(value, list):
                    chunks.extend(str(item) for item in value if isinstance(item, str))
                elif isinstance(value, str):
                    chunks.append(value)
    for skill in resume.get("skills") or []:
        if isinstance(skill, dict):
            chunks.append(str(skill.get("name", "")))
            chunks.append(str(skill.get("proficiency_level", "")))
    return " ".join(chunks)


def hallucination_reasons(resume):
    """List of {"code", "loc", "msg"} for each implausible claim found."""
    reasons = []
    experts = expert_skill_count(resume)
    years = resume_years(resume)
    if experts >= EXCESSIVE_EXPERT_SKILLS:
        reasons.append(
            {"code": "excessive_expert", "loc": ["skills"], "msg": f"Resume claims {experts} expert-level skills."}
        )
    if years < ENTRY_OVERCLAIM_YEARS and experts >= ENTRY_OVERCLAIM_EXPERT_SKILLS:
        reasons.append(
            {
                "code": "entry_overclaim",
                "loc": ["skills"],
                "msg": f"Entry-level experience ({years} years) claims {experts} expert skills.",
            }
        )
    if has_overlapping_roles(employment_periods(resume)):
        reasons.append(
            {"code": "impossible_timeline", "loc": ["experience"], "msg": "Resume shows overlapping work timelines."}
        )
    else:
        span = career_span_years(resume)
        too_long = [
            skill.get("name")
            for skill in resume.get("skills") or []
            if isinstance(skill, dict)
            and isinstance(skill.get("years"), (int, float))
            and skill["years"] > span + SKILL_YEARS_SLACK
        ]
        if too_long:
            reasons.append(
                {
                    "code": "impossible_timeline",
                    "loc": ["skills"],
                    "msg": f"Skill years exceed the {span}-year career for: " + ", ".join(map(str, too_long[:5])),
                }
            )
    if ABSOLUTE_CLAIM_PATTERN.search(resume_text(resume).lower()):
        reasons.append(
            {
                "code": "absolute_claims",
                "loc": ["skills"],
                "msg": "Resume uses absolutes like 'expert in all' or 'certified in everything'.",
            }
        )
    return reasons


# --- Awkward language -------------------------------------------------------

BUZZWORD_PATTERNS = (
    "synergy",
    "thinking outside the box",
    "move the needle",
    "leverage",
    "paradigm shift",
    "circle back",
    "deep dive",
    "game changer",
    "value proposition",
    "thought leader",
    "holistic",
    "best in class",
    "bandwidth",
    "stakeholder management",
    "innovation strategy",
)
BUZZWORD_DENSITY_LIMIT = 2.0  # occurrences per 100 words
DISTINCT_BUZZWORD_LIMIT = 5


def awkward_language_stats(resume):
    lowered = resume_text(resume).lower()
    words = re.findall(r"[a-zA-Z']+", lowered)
    hits = [term for term in BUZZWORD_PATTERNS if term in lowered]
    occurrences = sum(len(re.findall(rf"\b{re.escape(term)}", lowered)) for term in hits)
    density = round(100 * occurrences / len(words), 2) if words else 0.0
    repetition = any(words[i] == words[i + 1] == words[i + 2] for i in range(len(words) - 2))
    return {"word_count": len(words), "buzzword_hits": hits, "buzzword_density": density, "repetition": repetition}


def awkward_language_reasons(resume):
    stats = awkward_language_stats(resume)
    reasons = []
    if stats["buzzword_density"] > BUZZWORD_DENSITY_LIMIT:
        reasons.append(
            {
                "code": "buzzword_density",
                "loc": ["experience"],
                "msg": f"Buzzword density {stats['buzzword_density']} per 100 words: " + ", ".join(stats["buzzword_hits"][:5]),
            }
        )
    if len(stats["buzzword_hits"]) > DISTINCT_BUZZWORD_LIMIT:
        reasons.append(
            {
                "code": "buzzword_variety",
                "loc": ["experience"],
                "msg": f"{len(stats['buzzword_hits'])} distinct buzzwords: " + ", ".join(stats["buzzword_hits"][:5]),
            }
        )
    if stats["repetition"]:
        reasons.append(
            {"code": "repetition", "loc": ["experience"], "msg": "Resume repeats the same word three times in a row."}
        )
    return reasons
