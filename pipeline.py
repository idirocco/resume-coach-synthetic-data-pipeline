# Local setup
# Install dependencies first:
#   python3 -m pip install -r requirements.txt

import argparse

from iteration_log import append_iteration_log
from startup_checks import run_startup_checks


def parse_arguments(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("step", nargs="?", choices=("step1", "step2"))
    only_group = parser.add_mutually_exclusive_group()
    only_group.add_argument("--only-jobs", action="store_true")
    only_group.add_argument("--only-resumes", action="store_true")
    only_group.add_argument("--only-pairs", action="store_true")
    parser.add_argument(
        "--log",
        action="store_true",
        help="Compare this validation result with the previous comparable run in iteration_log.md",
    )
    args = parser.parse_args(argv)
    if args.log and (
        args.step == "step1"
        or (args.step is None and any((args.only_jobs, args.only_resumes, args.only_pairs)))
    ):
        parser.error("--log requires validation; run the full pipeline or select step2")
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
    run_jobs_validation = args.step is None and only == "jobs"
    step = args.step or "step1"
    checks_step = "all" if run_complete_pipeline or run_jobs_validation else step
    run_startup_checks(checks_step, require_api_key=only in {None, "jobs"})

    if step == "step2":
        from step2_validation import validate_latest_run

        result = validate_latest_run(only=only)
        if args.log:
            append_iteration_log(result["failure_modes_path"])
        return

    from step1_generation import generate_job_descriptions

    if only is None:
        generated_run = generate_job_descriptions()
    else:
        generated_run = generate_job_descriptions(only=only)
    if run_complete_pipeline or run_jobs_validation:
        from step2_validation import validate_run

        validation_paths = (
            generated_run["jobs_path"],
            generated_run["resumes_path"],
            generated_run["pairs_path"],
        )
        if run_jobs_validation:
            result = validate_run(*validation_paths, only="jobs")
        else:
            result = validate_run(*validation_paths)
        if args.log:
            append_iteration_log(result["failure_modes_path"])


if __name__ == "__main__":
    main()
