import importlib.util
import os

from config import ROOT, ensure_output_dir

REQUIRED_PACKAGES = ["openai", "dotenv", "pydantic"]


def ensure_dependencies(packages=REQUIRED_PACKAGES):
    missing = [pkg for pkg in packages if importlib.util.find_spec(pkg) is None]
    if missing:
        print("Missing required dependencies:", ", ".join(missing))
        print("Please install them before running the pipeline:")
        print("  python3 -m pip install -r requirements.txt")
        print("or:")
        print("  python3 -m pip install openai python-dotenv pydantic")
        raise SystemExit(1)


def ensure_openrouter_key():
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    if not os.getenv("OPENROUTER_API_KEY"):
        print("Missing environment variable: OPENROUTER_API_KEY")
        print("Please set it in your shell or .env file before running the pipeline:")
        print("  export OPENROUTER_API_KEY=your_key_here")
        print("or create a .env file with:")
        print("  OPENROUTER_API_KEY=your_key_here")
        raise SystemExit(1)


def run_startup_checks(step="step1", require_api_key=True):
    ensure_output_dir()
    if step in {"step1", "all"}:
        ensure_dependencies(["openai", "dotenv"])
        if require_api_key:
            ensure_openrouter_key()
    if step in {"step2", "all"}:
        ensure_dependencies(["pydantic"])
