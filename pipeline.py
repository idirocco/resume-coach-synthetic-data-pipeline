# Local setup
# Install dependencies first:
#   python3 -m pip install -r requirements.txt

import sys

from startup_checks import run_startup_checks
from step1_generation import generate_job_descriptions

run_startup_checks()


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else "step1"
    if step not in {"step1", "all"}:
        raise SystemExit(f"Unknown step: {step}. Available steps: step1")
    generate_job_descriptions()


if __name__ == "__main__":
    main()
