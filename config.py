from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Total job descriptions for step 1. Templates and industries are cycled so both are used evenly.
JOBS = 10
RESUMES_PER_JOB = 5
RESUME_WRITING_STYLES = ["concise", "metrics-driven", "technical", "narrative", "understated"]

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
