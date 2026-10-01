from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Total job descriptions for step 1. Templates and industries are cycled so both are used evenly.
JOBS = 10
RESUMES_PER_JOB = 2
RESUME_WRITING_STYLES = ["concise", "metrics-driven", "technical", "narrative", "understated"]
RESUME_STYLE_DEFINITIONS = {
    "concise": "short, plain bullets of 8-14 words; no adjectives that are not facts",
    "metrics-driven": "every achievement carries a number (percent, count, time, or money) and every responsibility is an action plus its scope",
    "technical": "name tools, systems and methods in each bullet; fewer people and business outcomes",
    "narrative": "full sentences giving context and outcome, 15-25 words each, no first-person pronouns",
    "understated": "modest, factual wording; few superlatives and only one or two numbers across the whole resume",
}
# Per-fit instructions: [skill_instruction, years_factor, levels_below_job]. Levels shift downward unless the job is already entry level.
RESUME_FIT_DIRECTIVES = {
    "excellent": ("Strong, specific evidence for every included skill, with the same seniority as the job.", 1.0, 0),
    "good": ("Solid evidence for the included skills, with the same seniority as the job; the omitted skills are simply absent.", 1.0, 0),
    "partial": ("Mixed evidence: the included skills are real, the work history is in an adjacent specialty, and the seniority is one level off.", 0.7, 1),
    "poor": ("Thin evidence: only a few skills appear, and the work history is mostly in a neighboring field with clearly lower seniority.", 0.4, 2),
    "complete_mismatch": ("None of the job's skills appear. The career is in an unrelated field, with seniority clearly off from the job.", 0.4, 2),
}

MODEL = "openai/gpt-oss-20b" #"meta-llama/llama-3.1-8b-instruct"
TEMPERATURE = 0.8
MAX_ATTEMPTS = 3
# Upper bound for simultaneous LLM requests.
MAX_CONCURRENT_REQUESTS = 3

PROMPTS_DIR = ROOT / "prompts" / "job_description"
RESUME_PROMPTS_DIR = ROOT / "prompts" / "resume"
OUTPUT_DIR = ROOT / "output"


def ensure_output_dir() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR

PROMPT_TEMPLATES = [
    "formal_corporate",
    "casual_startup",
    "technical_detail",
    "achievement_metrics",
    "career_changer",
    "niche_specialist",
]

# July 2026 BLS JOLTS industries with the most open jobs, largest first.
INDUSTRIES = [
    "Health care and social assistance",
    "Professional and business services",
    "Government",
    "Retail trade",
    "Accommodation and food services",
    "Manufacturing",
    "Financial activities",
    "Construction",
    "Transportation, warehousing, and utilities",
    "Other services",
]
