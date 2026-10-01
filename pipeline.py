# Local setup
# Install dependencies first:
#   python3 -m pip install -r requirements.txt

import argparse

from startup_checks import run_startup_checks


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("step", nargs="?", choices=("step1", "step2"))
    only_group = parser.add_mutually_exclusive_group()
    only_group.add_argument("--only-jobs", action="store_true")
    only_group.add_argument("--only-resumes", action="store_true")
    only_group.add_argument("--only-pairs", action="store_true")
    args = parser.parse_args(argv)
    return args


def main(argv=None):
    args = parse_arguments(argv)
    only = None
    if args.only_jobs:
        only = "jobs"
    elif args.only_resumes:
        only = "resumes"
    elif args.only_pairs:
        only = "pairs"

    run_complete_pipeline = args.step is None and only is None
    step = args.step or "step1"
    checks_step = "all" if run_complete_pipeline else step
    run_startup_checks(checks_step, require_api_key=only in {None, "jobs"})

    if step == "step2":
        from step2_validation import validate_latest_run

        validate_latest_run(only=only)
        return

    from step1_generation import generate_job_descriptions

    if only is None:
        generated_run = generate_job_descriptions()
    else:
        generated_run = generate_job_descriptions(only=only)
    if run_complete_pipeline:
        from step2_validation import validate_run

        validate_run(
            generated_run["jobs_path"],
            generated_run["resumes_path"],
            generated_run["pairs_path"],
        )


if __name__ == "__main__":
    main()
