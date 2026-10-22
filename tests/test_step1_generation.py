import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.pipeline import main, parse_arguments
from src.step1_generation import generate_job_descriptions


class Step1SelectionTests(unittest.TestCase):
    def test_only_flags_parse_and_default_to_all(self):
        self.assertTrue(parse_arguments(["step1", "--only-jobs"]).only_jobs)
        self.assertTrue(parse_arguments(["step1", "--only-resumes"]).only_resumes)
        self.assertTrue(parse_arguments(["step1", "--only-pairs"]).only_pairs)
        self.assertFalse(parse_arguments(["step1"]).only_jobs)

    def test_only_pairs_skips_api_key_check(self):
        with (
            patch("src.pipeline.run_startup_checks") as startup,
            patch("src.step1_generation.generate_job_descriptions") as generate,
        ):
            main(["step1", "--only-pairs"])
        startup.assert_called_once_with("step1", require_api_key=False)
        generate.assert_called_once_with(only="pairs")

    def test_only_resumes_reports_missing_jobs_before_api_key(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch("src.step1_generation.OUTPUT_DIR", Path(temporary_directory)):
                with self.assertRaisesRegex(SystemExit, "no existing jobs JSONL file"):
                    generate_job_descriptions(only="resumes")

    def test_only_jobs_writes_no_resumes_or_pairs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            generated_job = {"metadata": {"trace_id": "jd-generated"}}
            batch_item = {"index": 0, "prompt_template": "template", "industry": "industry"}
            with (
                patch("src.step1_generation.OUTPUT_DIR", output_dir),
                patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}),
                patch("src.step1_generation.OpenAI"),
                patch("src.step1_generation.load_templates", return_value={"template": "prompt"}),
                patch("src.step1_generation.plan_batch", return_value=[batch_item]),
                patch("src.step1_generation.generate_one", return_value=(generated_job, None)),
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
                patch("src.step1_generation.OUTPUT_DIR", output_dir),
                patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}),
                patch("src.step1_generation.OpenAI"),
                patch("src.step1_generation.load_resume_template", return_value="prompt"),
                patch("src.step1_generation.generate_resume_one", return_value=(generated_resume, None)),
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
            with patch("src.step1_generation.OUTPUT_DIR", output_dir):
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
            with patch("src.step1_generation.OUTPUT_DIR", output_dir):
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
            with patch("src.step1_generation.OUTPUT_DIR", output_dir):
                result = generate_job_descriptions(only="pairs")

            pair = json.loads(result["pairs_path"].read_text(encoding="utf-8"))
            self.assertEqual(pair["job_trace_id"], job_trace_id)
            self.assertEqual(pair["resume_trace_id"], "resume-existing")
            self.assertFalse(result["jobs_path"])
            self.assertFalse(result["resumes_path"])

class ResumePromptTests(unittest.TestCase):
    JOB = {
        "title": "Data Engineer",
        "company": {"name": "Acme"},
        "description": "Build pipelines.",
        "responsibilities": ["Own ETL"],
        "requirements": {
            "required_skills": ["Python", "SQL", "Airflow", "Spark", "dbt", "Kafka", "AWS"],
            "experience_years": 6,
            "experience_level": "senior",
        },
        "metadata": {"trace_id": "jd-1"},
    }

    def test_selected_skills_land_in_the_target_fit_band(self):
        from src.schemas import fit_level_for_overlap
        from src.step1_generation import FIT_LEVELS, select_resume_skills

        required = self.JOB["requirements"]["required_skills"]
        for fit_level in FIT_LEVELS:
            for resume_index in range(len(required)):
                included, omitted = select_resume_skills(required, fit_level, resume_index)
                extra = 1 if fit_level == "complete_mismatch" else 0
                self.assertEqual(fit_level_for_overlap(len(included) / (len(required) + extra)), fit_level)
                self.assertEqual(sorted(included + omitted), sorted(required))
                if fit_level in ("excellent", "good"):
                    self.assertEqual(included[:3], required[:3])

    def test_render_fills_every_placeholder_and_hides_job_metadata(self):
        from src.step1_generation import load_resume_template, render_resume_prompt

        prompt = render_resume_prompt(load_resume_template(), self.JOB, "partial", "concise", 1)
        self.assertNotIn("jd-1", prompt)
        self.assertIn("4 years in total, at mid level", prompt)
        self.assertIn('["SQL", "Airflow", "Spark", "dbt"]', prompt)


class ResumeStylePlanTests(unittest.TestCase):
    def test_each_job_gets_every_style_once(self):
        from src.step1_generation import RESUME_WRITING_STYLES, plan_resume_styles

        for job_index in range(12):
            self.assertEqual(sorted(plan_resume_styles(job_index, 5)), sorted(RESUME_WRITING_STYLES))

    def test_five_consecutive_jobs_cover_every_fit_style_pair_once(self):
        from collections import Counter

        from src.step1_generation import FIT_LEVELS, RESUME_WRITING_STYLES, plan_resume_fits, plan_resume_styles

        pairs = Counter(
            pair
            for job_index in range(5)
            for pair in zip(plan_resume_fits(5), plan_resume_styles(job_index, 5))
        )
        self.assertEqual(len(pairs), len(FIT_LEVELS) * len(RESUME_WRITING_STYLES))
        self.assertEqual(set(pairs.values()), {1})

    def test_job_zero_keeps_the_previous_order(self):
        from src.step1_generation import RESUME_WRITING_STYLES, plan_resume_styles

        self.assertEqual(plan_resume_styles(0, 5), RESUME_WRITING_STYLES)

    def test_counts_other_than_five_keep_rotating(self):
        from src.step1_generation import RESUME_WRITING_STYLES, plan_resume_styles

        n = len(RESUME_WRITING_STYLES)
        for count in (7, 10):
            for job_index in (0, 3):
                styles = plan_resume_styles(job_index, count)
                self.assertEqual(len(styles), count)
                self.assertEqual(styles, [RESUME_WRITING_STYLES[(job_index + i) % n] for i in range(count)])


class ResumeStyleCallSiteTests(unittest.TestCase):
    JOB = {
        "title": "Data Engineer",
        "company": {"name": "Acme"},
        "description": "Build pipelines.",
        "responsibilities": ["Own ETL"],
        "requirements": {
            "required_skills": ["Python", "SQL", "Airflow"],
            "experience_years": 3,
            "experience_level": "mid",
        },
        "metadata": {"trace_id": "jd-1"},
    }

    @staticmethod
    def styles_by_job(generate):
        # generate_resume_one(client, job, template, fit_level, writing_style, resume_index)
        styles = {}
        for call in generate.call_args_list:
            job, writing_style, resume_index = call.args[1], call.args[4], call.args[5]
            styles[(job["metadata"]["trace_id"], resume_index)] = writing_style
        return styles

    def job(self, trace_id):
        return {**self.JOB, "metadata": {"trace_id": trace_id}}

    def test_full_step1_rotates_styles_by_job_index(self):
        from src.step1_generation import RESUME_WRITING_STYLES

        jobs = {"template-0": self.job("jd-0"), "template-1": self.job("jd-1")}
        batch = [
            {"index": 0, "prompt_template": "template-0", "industry": "industry"},
            {"index": 1, "prompt_template": "template-1", "industry": "industry"},
        ]
        resume = {"metadata": {"trace_id": "resume", "fit_level": "excellent"}}
        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch("src.step1_generation.OUTPUT_DIR", Path(temporary_directory)),
                patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}),
                patch("src.step1_generation.OpenAI"),
                patch("src.step1_generation.load_templates", return_value={"template-0": "p", "template-1": "p"}),
                patch("src.step1_generation.load_resume_template", return_value="prompt"),
                patch("src.step1_generation.plan_batch", return_value=batch),
                patch("src.step1_generation.generate_one", side_effect=lambda c, name, t, i: (jobs[name], None)),
                patch("src.step1_generation.generate_resume_one", return_value=(resume, None)) as generate,
            ):
                generate_job_descriptions()

        styles = self.styles_by_job(generate)
        self.assertEqual(styles[("jd-0", 0)], RESUME_WRITING_STYLES[0])
        self.assertEqual(styles[("jd-1", 0)], RESUME_WRITING_STYLES[1])

    def test_only_resumes_rotates_by_stored_index_or_position(self):
        from src.step1_generation import RESUME_WRITING_STYLES

        records = [
            {"index": 0, "job_description": self.job("jd-0")},
            {"index": 1, "job_description": self.job("jd-1")},
            {"job_description": self.job("jd-legacy")},
        ]
        resume = {"metadata": {"trace_id": "resume", "fit_level": "excellent"}}
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            (output_dir / "jobs_20261001T000000Z.jsonl").write_text(
                "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
            )
            with (
                patch("src.step1_generation.OUTPUT_DIR", output_dir),
                patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}),
                patch("src.step1_generation.OpenAI"),
                patch("src.step1_generation.load_resume_template", return_value="prompt"),
                patch("src.step1_generation.generate_resume_one", return_value=(resume, None)) as generate,
            ):
                generate_job_descriptions(only="resumes")

        styles = self.styles_by_job(generate)
        self.assertEqual(styles[("jd-0", 0)], RESUME_WRITING_STYLES[0])
        self.assertEqual(styles[("jd-1", 0)], RESUME_WRITING_STYLES[1])
        self.assertEqual(styles[("jd-legacy", 0)], RESUME_WRITING_STYLES[2])


if __name__ == "__main__":
    unittest.main()
