import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import main, parse_arguments
from step1_generation import generate_job_descriptions


class Step1SelectionTests(unittest.TestCase):
    def test_only_flags_parse_and_default_to_all(self):
        self.assertTrue(parse_arguments(["step1", "--only-jobs"]).only_jobs)
        self.assertTrue(parse_arguments(["step1", "--only-resumes"]).only_resumes)
        self.assertTrue(parse_arguments(["step1", "--only-pairs"]).only_pairs)
        self.assertFalse(parse_arguments(["step1"]).only_jobs)

    def test_only_pairs_skips_api_key_check(self):
        with (
            patch("pipeline.run_startup_checks") as startup,
            patch("step1_generation.generate_job_descriptions") as generate,
        ):
            main(["step1", "--only-pairs"])
        startup.assert_called_once_with("step1", require_api_key=False)
        generate.assert_called_once_with(only="pairs")

    def test_only_resumes_reports_missing_jobs_before_api_key(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch("step1_generation.OUTPUT_DIR", Path(temporary_directory)):
                with self.assertRaisesRegex(SystemExit, "no existing jobs JSONL file"):
                    generate_job_descriptions(only="resumes")

    def test_only_jobs_writes_no_resumes_or_pairs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            generated_job = {"metadata": {"trace_id": "jd-generated"}}
            batch_item = {"index": 0, "prompt_template": "template", "industry": "industry"}
            with (
                patch("step1_generation.OUTPUT_DIR", output_dir),
                patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}),
                patch("step1_generation.OpenAI"),
                patch("step1_generation.load_templates", return_value={"template": "prompt"}),
                patch("step1_generation.plan_batch", return_value=[batch_item]),
                patch("step1_generation.generate_one", return_value=(generated_job, None)),
            ):
                result = generate_job_descriptions(only="jobs")

            self.assertEqual(len(result["jobs_path"].read_text(encoding="utf-8").splitlines()), 1)
            self.assertEqual(list(output_dir.glob("resumes_*.jsonl")), [])
            self.assertEqual(list(output_dir.glob("pairs_*.jsonl")), [])

    def test_only_resumes_writes_no_jobs_or_pairs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            job = {
                "requirements": {
                    "required_skills": ["skill"],
                    "experience_years": 3,
                    "experience_level": "mid",
                },
                "metadata": {"trace_id": "jd-existing"},
            }
            jobs_path = output_dir / "jobs_20261001T000000Z.jsonl"
            jobs_path.write_text(json.dumps({"job_description": job}) + "\n", encoding="utf-8")
            generated_resume = {"metadata": {"trace_id": "resume-generated", "fit_level": "excellent"}}
            with (
                patch("step1_generation.OUTPUT_DIR", output_dir),
                patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}),
                patch("step1_generation.OpenAI"),
                patch("step1_generation.load_resume_template", return_value="prompt"),
                patch("step1_generation.generate_resume_one", return_value=(generated_resume, None)),
            ):
                result = generate_job_descriptions(only="resumes")

            self.assertEqual(len(result["resumes_path"].read_text(encoding="utf-8").splitlines()), 5)
            self.assertEqual(list(output_dir.glob("jobs_*.jsonl")), [jobs_path])
            self.assertEqual(list(output_dir.glob("pairs_*.jsonl")), [])

    def test_only_pairs_reports_missing_resumes_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            jobs_path = output_dir / "jobs_20261001T000000Z.jsonl"
            jobs_path.write_text(
                json.dumps({"job_description": {"metadata": {"trace_id": "jd-1"}}}) + "\n",
                encoding="utf-8",
            )
            with patch("step1_generation.OUTPUT_DIR", output_dir):
                with self.assertRaisesRegex(SystemExit, "no existing resumes JSONL file"):
                    generate_job_descriptions(only="pairs")
            self.assertEqual(list(output_dir.glob("pairs_*.jsonl")), [])

    def test_only_pairs_rejects_resumes_with_missing_job_references(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            (output_dir / "jobs_20261001T000000Z.jsonl").write_text(
                json.dumps({"job_description": {"metadata": {"trace_id": "jd-existing"}}}) + "\n",
                encoding="utf-8",
            )
            (output_dir / "resumes_20261001T000000Z.jsonl").write_text(
                json.dumps({"metadata": {
                    "trace_id": "resume-existing",
                    "job_trace_id": "jd-missing",
                    "fit_level": "good",
                }}) + "\n",
                encoding="utf-8",
            )
            with patch("step1_generation.OUTPUT_DIR", output_dir):
                with self.assertRaisesRegex(SystemExit, "references jobs missing from the latest jobs file"):
                    generate_job_descriptions(only="pairs")
            self.assertEqual(list(output_dir.glob("pairs_*.jsonl")), [])

    def test_only_pairs_reuses_latest_jobs_and_resumes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            job_trace_id = "jd-existing"
            (output_dir / "jobs_20261001T000000Z.jsonl").write_text(
                json.dumps({"job_description": {"metadata": {"trace_id": job_trace_id}}}) + "\n",
                encoding="utf-8",
            )
            (output_dir / "resumes_20261001T000000Z.jsonl").write_text(
                json.dumps({"metadata": {
                    "trace_id": "resume-existing",
                    "job_trace_id": job_trace_id,
                    "fit_level": "good",
                }}) + "\n",
                encoding="utf-8",
            )
            with patch("step1_generation.OUTPUT_DIR", output_dir):
                result = generate_job_descriptions(only="pairs")

            pair = json.loads(result["pairs_path"].read_text(encoding="utf-8"))
            self.assertEqual(pair["job_trace_id"], job_trace_id)
            self.assertEqual(pair["resume_trace_id"], "resume-existing")
            self.assertFalse(result["jobs_path"])
            self.assertFalse(result["resumes_path"])


if __name__ == "__main__":
    unittest.main()