# Local setup
# Install dependencies first:
#   python3 -m pip install -r requirements.txt

import sys

from startup_checks import run_startup_checks


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else "step1"
    if step not in {"step1", "step2", "all"}:
        raise SystemExit(f"Unknown step: {step}. Available steps: step1, step2, all")
    run_startup_checks(step)

    if step == "step2":
        from step2_validation import validate_latest_run

        validate_latest_run()
        return

    from step1_generation import generate_job_descriptions

    generated_run = generate_job_descriptions()
    if step == "all":
        from step2_validation import validate_run

        validate_run(
            generated_run["jobs_path"],
            generated_run["resumes_path"],
            generated_run["pairs_path"],
        )


if __name__ == "__main__":
    main()
