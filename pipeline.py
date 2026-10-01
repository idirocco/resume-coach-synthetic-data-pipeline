# Local setup
# Install dependencies first:
#   python3 -m pip install -r requirements.txt

import argparse

from startup_checks import run_startup_checks


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("step", nargs="?", choices=("step1", "step2", "all"), default="step1")
    only_group = parser.add_mutually_exclusive_group()
    only_group.add_argument("--only-jobs", action="store_true")
    only_group.add_argument("--only-resumes", action="store_true")
    only_group.add_argument("--only-pairs", action="store_true")
    args = parser.parse_args(argv)
    if args.step != "step1" and (args.only_jobs or args.only_resumes or args.only_pairs):
        parser.error("--only-jobs, --only-resumes, and --only-pairs can only be used with step1")
    return args


def main(argv=None):
    args = parse_arguments(argv)
    step = args.step
    only = None
    if args.only_jobs:
        only = "jobs"
    elif args.only_resumes:
        only = "resumes"
    elif args.only_pairs:
        only = "pairs"

    run_startup_checks(step, require_api_key=only in {None, "jobs"})

    if step == "step2":
        from step2_validation import validate_latest_run

        validate_latest_run()
        return

    from step1_generation import generate_job_descriptions

    if only is None:
        generated_run = generate_job_descriptions()
    else:
        generated_run = generate_job_descriptions(only=only)
    if step == "all":
        from step2_validation import validate_run

        validate_run(
            generated_run["jobs_path"],
            generated_run["resumes_path"],
            generated_run["pairs_path"],
        )


if __name__ == "__main__":
    main()
