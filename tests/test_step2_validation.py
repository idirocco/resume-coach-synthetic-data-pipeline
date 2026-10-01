import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from pipeline import main, parse_arguments
from schemas import Requirements, ResumeJobPair
from step1_generation import generate_one
from startup_checks import run_startup_checks
from step2_validation import _category_for_error, discover_latest_run, validate_run

GENERATED_AT = "2026-09-30T12:00:00+00:00"
REQUIRED_SKILLS = ["Python", "SQL", "Git", "Docker", "Linux"]


def make_job():
    return {
        "index": 0,
        "prompt_template": "formal_corporate",
        "assigned_industry": "Retail trade",
        "model": "test-model",
        "job_description": {
            "company": {
                "name": "Example Systems",
                "industry": "Retail trade",
                "size": "1001-5000",
                "location": "Chicago, IL",
            },
            "requirements": {
                "required_skills": REQUIRED_SKILLS,
                "preferred_skills": ["Communication", "Planning", "Testing"],
                "education": "Bachelor's degree or equivalent experience",
                "experience_years": 4,
                "experience_level": "mid",
            },
            "title": "Software Engineer",
            "description": (
                "First sentence. Second sentence. Third sentence. Fourth sentence. "
                "Fifth sentence. Sixth sentence. Seventh sentence. Eighth sentence."
            ),
            "responsibilities": ["Build", "Review", "Test", "Deploy", "Document"],
            "metadata": {
                "trace_id": "job-1",
                "generated_at": GENERATED_AT,
                "is_niche_role": False,
            },
        },
    }


def make_resume(email="candidate@example.com"):
    return {
        "contact_info": {
            "name": "Taylor Example",
            "email": email,
            "phone": "+1-202-555-0100",
            "location": "Chicago, IL",
        },
        "education": [
            {
                "degree": "Bachelor of Science",
                "institution": "Example University",
                "graduation_date": "2020-05-15",
                "gpa": 3.5,
                "coursework": ["Systems Design"],
            }
        ],
        "experience": [
            {
                "company": "Sample Works",
                "title": "Software Engineer",
                "start_date": "2021-01-01",
                "end_date": "2025-01-01",
                "responsibilities": ["Built internal services"],
                "achievements": ["Improved deployment reliability"],
            }
        ],
        "skills": [
            {"name": skill, "proficiency_level": "Advanced", "years": 4}
            for skill in REQUIRED_SKILLS
        ],
        "metadata": {
            "trace_id": "resume-1",
            "generated_at": GENERATED_AT,
            "prompt_template": "controlled_fit",
            "fit_level": "excellent",
            "writing_style": "concise",
            "job_trace_id": "job-1",
        },
    }


def make_pair():
    return {
        "pair_id": "pair-1",
        "job_trace_id": "job-1",
        "resume_trace_id": "resume-1",
        "fit_level": "excellent",
        "generated_at": GENERATED_AT,
    }


class Step2ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source_dir = self.root / "source"
        self.output_dir = self.root / "validated"
        self.source_dir.mkdir()
        self.paths = {
            "jobs": self.source_dir / "jobs_20260930T120000Z.jsonl",
            "resumes": self.source_dir / "resumes_20260930T120000Z.jsonl",
            "pairs": self.source_dir / "pairs_20260930T120000Z.jsonl",
        }
        self.write_records()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_records(self, job=None, resume=None, pair=None):
        records = {
            "jobs": [make_job() if job is None else job],
            "resumes": [make_resume() if resume is None else resume],
            "pairs": [make_pair() if pair is None else pair],
        }
        for kind, path in self.paths.items():
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in records[kind]),
                encoding="utf-8",
            )

    def test_valid_complete_run_writes_three_artifacts(self):
        result = validate_run(
            self.paths["jobs"],
            self.paths["resumes"],
            self.paths["pairs"],
            self.output_dir,
        )
        self.assertEqual(result["report"]["summary"]["valid_records"], 3)
        self.assertEqual(result["report"]["summary"]["invalid_records"], 0)
        self.assertEqual(result["report"]["summary"]["blocked_records"], 0)
        self.assertTrue(result["validated_path"].is_file())
        self.assertTrue(result["invalid_path"].is_file())
        self.assertTrue(result["failure_modes_path"].is_file())
        validated = json.loads(result["validated_path"].read_text(encoding="utf-8"))
        self.assertEqual({record["record_type"] for record in validated}, {"job", "resume", "pair"})

    def test_jobs_only_does_not_require_or_report_other_sources(self):
        result = validate_run(
            self.paths["jobs"],
            output_dir=self.output_dir,
            only="jobs",
        )
        validated = json.loads(result["validated_path"].read_text(encoding="utf-8"))
        self.assertEqual([record["record_type"] for record in validated], ["job"])
        self.assertEqual(result["report"]["summary"]["total_records"], 1)
        self.assertEqual(set(result["report"]["source_files"]), {"jobs"})

    def test_resumes_only_validates_jobs_as_dependency_without_reporting_them(self):
        result = validate_run(
            self.paths["jobs"],
            self.paths["resumes"],
            output_dir=self.output_dir,
            only="resumes",
        )
        validated = json.loads(result["validated_path"].read_text(encoding="utf-8"))
        self.assertEqual([record["record_type"] for record in validated], ["resume"])
        self.assertEqual(result["report"]["summary"]["total_records"], 1)
        self.assertEqual(set(result["report"]["source_files"]), {"jobs", "resumes"})

    def test_pairs_only_validates_both_dependencies_without_reporting_them(self):
        result = validate_run(
            self.paths["jobs"],
            self.paths["resumes"],
            self.paths["pairs"],
            self.output_dir,
            only="pairs",
        )
        validated = json.loads(result["validated_path"].read_text(encoding="utf-8"))
        self.assertEqual([record["record_type"] for record in validated], ["pair"])
        self.assertEqual(result["report"]["summary"]["total_records"], 1)

    def test_latest_run_selection_requires_only_selected_dependencies(self):
        partial_dir = self.root / "partial"
        partial_dir.mkdir()
        (partial_dir / "jobs_20260930T130000Z.jsonl").touch()
        jobs_only = discover_latest_run(partial_dir, only="jobs")
        self.assertEqual(set(jobs_only) - {"source_timestamp"}, {"jobs"})
        with self.assertRaisesRegex(FileNotFoundError, "No resumes JSONL file"):
            discover_latest_run(partial_dir, only="resumes")

    def test_latest_resume_selection_can_use_separately_generated_jobs(self):
        staged_dir = self.root / "staged"
        staged_dir.mkdir()
        jobs_path = staged_dir / "jobs_20260930T120000Z.jsonl"
        resumes_path = staged_dir / "resumes_20260930T130000Z.jsonl"
        jobs_path.touch()
        resumes_path.touch()
        selected = discover_latest_run(staged_dir, only="resumes")
        self.assertEqual(selected["jobs"], jobs_path)
        self.assertEqual(selected["resumes"], resumes_path)

    def test_email_failure_and_invalid_pair_reference_are_categorized(self):
        self.write_records(resume=make_resume(email="not-an-email"))
        result = validate_run(
            self.paths["jobs"],
            self.paths["resumes"],
            self.paths["pairs"],
            self.output_dir,
        )
        categories = {record["category"] for record in result["report"]["invalid_records"]}
        self.assertIn("Format violations", categories)
        self.assertNotIn("Logical inconsistencies", categories)
        self.assertEqual(
            [record["record_type"] for record in result["report"]["blocked_records"]],
            ["pair"],
        )

    def test_resume_and_pair_are_blocked_by_schema_invalid_job(self):
        job = make_job()
        job["job_description"]["company"]["size"] = "tiny"
        self.write_records(job=job)
        result = validate_run(
            self.paths["jobs"],
            self.paths["resumes"],
            self.paths["pairs"],
            self.output_dir,
        )
        invalid_records = result["report"]["invalid_records"]
        blocked_records = result["report"]["blocked_records"]
        self.assertEqual([record["record_type"] for record in invalid_records], ["job"])
        self.assertEqual(
            {record["record_type"] for record in blocked_records},
            {"resume", "pair"},
        )
        self.assertEqual(result["report"]["summary"]["invalid_records"], 1)
        self.assertEqual(result["report"]["summary"]["blocked_records"], 2)

    def test_resume_with_unknown_job_reference_remains_invalid(self):
        resume = make_resume()
        resume["metadata"]["job_trace_id"] = "missing-job"
        self.write_records(resume=resume)
        result = validate_run(
            self.paths["jobs"],
            self.paths["resumes"],
            self.paths["pairs"],
            self.output_dir,
        )
        invalid_records = result["report"]["invalid_records"]
        resume_failure = next(record for record in invalid_records if record["record_type"] == "resume")
        self.assertEqual(resume_failure["category"], "Logical inconsistencies")
        self.assertEqual(
            result["report"]["summary"]["blocked_records"],
            1,
        )

    def test_latest_run_selects_each_source_independently(self):
        older = "20260929T120000Z"
        for kind in ("jobs", "resumes", "pairs"):
            (self.source_dir / f"{kind}_{older}.jsonl").touch()
        newer = "20260930T130000Z"
        newer_jobs = self.source_dir / f"jobs_{newer}.jsonl"
        newer_jobs.touch()
        selected = discover_latest_run(self.source_dir)
        self.assertEqual(selected["source_timestamp"], newer)
        self.assertEqual(selected["jobs"], newer_jobs)
        self.assertEqual(selected["resumes"], self.paths["resumes"])
        self.assertEqual(selected["pairs"], self.paths["pairs"])

    def test_experience_years_is_limited_to_thirty(self):
        with self.assertRaises(ValidationError):
            Requirements.model_validate(
                {
                    "required_skills": REQUIRED_SKILLS,
                    "preferred_skills": ["Communication", "Planning", "Testing"],
                    "education": "degree",
                    "experience_years": 31,
                    "experience_level": "executive",
                }
            )

    def test_pair_requires_iso_timestamp(self):
        with self.assertRaises(ValidationError):
            ResumeJobPair.model_validate({**make_pair(), "generated_at": "yesterday"})

    def test_error_categories_cover_requested_modes(self):
        errors = [
            ({"type": "missing", "loc": ["contact_info", "name"], "msg": "Field required"}, "Missing required fields"),
            ({"type": "string_type", "loc": ["skills", 0, "proficiency_level"], "msg": "Expected string"}, "Type mismatches"),
            ({"type": "value_error", "loc": ["contact_info"], "msg": "email must be a valid email address"}, "Format violations"),
            ({"type": "value_error", "loc": ["experience", 0], "msg": "end_date must be after start_date"}, "Logical inconsistencies"),
        ]
        for error, expected in errors:
            with self.subTest(expected=expected):
                self.assertEqual(_category_for_error(error), expected)

    def test_malformed_json_line_is_preserved_as_invalid(self):
        with self.paths["jobs"].open("a", encoding="utf-8") as handle:
            handle.write("{broken json}\n")
        result = validate_run(
            self.paths["jobs"],
            self.paths["resumes"],
            self.paths["pairs"],
            self.output_dir,
        )
        invalid_lines = result["invalid_path"].read_text(encoding="utf-8").splitlines()
        invalid = [json.loads(line) for line in invalid_lines]
        malformed = next(record for record in invalid if record["raw_record"] == "{broken json}")
        self.assertEqual(malformed["category"], "Format violations")

    def test_no_args_generates_then_validates_generated_paths(self):
        generated = {"jobs_path": "jobs.jsonl", "resumes_path": "resumes.jsonl", "pairs_path": "pairs.jsonl"}
        with (
            patch("pipeline.run_startup_checks") as startup,
            patch("sys.argv", ["pipeline.py"]),
            patch("step1_generation.generate_job_descriptions", return_value=generated),
            patch("step2_validation.validate_run") as validate,
        ):
            main()
        startup.assert_called_once_with("all", require_api_key=True)
        validate.assert_called_once_with("jobs.jsonl", "resumes.jsonl", "pairs.jsonl")

    def test_only_jobs_generates_then_validates_generated_jobs(self):
        generated = {"jobs_path": "jobs.jsonl", "resumes_path": None, "pairs_path": None}
        with (
            patch("pipeline.run_startup_checks") as startup,
            patch("step1_generation.generate_job_descriptions", return_value=generated) as generate,
            patch("step2_validation.validate_run") as validate,
        ):
            main(["--only-jobs"])
        startup.assert_called_once_with("all", require_api_key=True)
        generate.assert_called_once_with(only="jobs")
        validate.assert_called_once_with("jobs.jsonl", None, None, only="jobs")

    def test_all_is_not_a_supported_positional_argument(self):
        with self.assertRaises(SystemExit):
            parse_arguments(["all"])

    def test_step2_selector_is_forwarded_to_latest_validation(self):
        with (
            patch("pipeline.run_startup_checks"),
            patch("step2_validation.validate_latest_run") as validate,
        ):
            main(["step2", "--only-resumes"])
        validate.assert_called_once_with(only="resumes")

    def test_step2_startup_does_not_check_api_key(self):
        with patch("startup_checks.ensure_openrouter_key") as ensure_key:
            run_startup_checks("step2")
        ensure_key.assert_not_called()

    def test_step1_returns_schema_invalid_json_for_step2(self):
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content='{"unexpected": true}'))]
                    )
                )
            )
        )
        payload, failure = generate_one(client, "formal_corporate", "", "Retail trade")
        self.assertEqual(payload, {"unexpected": True})
        self.assertIsNone(failure)


if __name__ == "__main__":
    unittest.main()
