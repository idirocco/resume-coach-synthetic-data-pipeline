import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.api import app
from src.step3_failure_analysis import FLAGS, label_pair
from test_step2_validation import REQUIRED_SKILLS, make_job, make_resume
from test_step3_failure_analysis import enriched_row

client = TestClient(app, raise_server_exceptions=False)


def review(resume=None, job="default"):
    body = {"resume": resume or make_resume()}
    if job == "default":
        body["job"] = make_job()["job_description"]
    elif job is not None:
        body["job"] = job
    return client.post("/review-resume", json=body)


def without_metadata(resume=None):
    resume = resume or make_resume()
    resume.pop("metadata")
    return resume


class HealthTests(unittest.TestCase):
    def test_health_reports_latest_stats(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "failure_stats_20260930T120000Z.json").write_text("{}")
            with patch("src.config.OUTPUT_DIR", Path(directory)):
                body = client.get("/health").json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["latest_failure_stats"], "20260930T120000Z")

    def test_health_without_stats(self):
        with tempfile.TemporaryDirectory() as directory, patch("src.config.OUTPUT_DIR", Path(directory)):
            response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["latest_failure_stats"])

    def test_openapi_docs(self):
        self.assertEqual(client.get("/docs").status_code, 200)
        paths = client.get("/openapi.json").json()["paths"]
        self.assertEqual(set(paths), {"/health", "/review-resume", "/analysis/failure-rates"})


class ReviewResumeTests(unittest.TestCase):
    def test_excellent_match_with_job(self):
        response = review()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body["flags"]), set(FLAGS))
        self.assertEqual(body["triggered_flags"], [])
        self.assertEqual(body["failure_count"], 0)
        self.assertEqual(
            body["integrity"],
            {"intended_fit_level": "excellent", "actual_fit_level": "excellent", "skills_jaccard": 1.0, "met_intended_fit": True},
        )
        self.assertEqual(body["schema_warnings"], [])
        self.assertEqual(body["detail"], [])

    def test_without_job_only_resume_checks(self):
        body = review(job=None).json()
        self.assertEqual(set(body["flags"]), {"hallucination_flag", "awkward_language_flag"})
        self.assertIsNone(body["job_fit"])
        self.assertIsNone(body["integrity"])
        self.assertEqual(body["resume_checks"]["resume_seniority_source"], "years")

    def test_missed_intended_fit(self):
        resume = make_resume()
        resume["skills"] = [{"name": "Linux", "proficiency_level": "Advanced", "years": 4}]
        body = review(resume).json()
        self.assertEqual(body["integrity"]["actual_fit_level"], "poor")
        self.assertFalse(body["integrity"]["met_intended_fit"])
        self.assertEqual(set(body["triggered_flags"]), {"skills_gap_flag", "missing_core_skills_flag"})
        self.assertIn("Missing core skills: Python, SQL, Git.", body["detail"])
        self.assertTrue(any(line.startswith("Intended fit was excellent") for line in body["detail"]))

    def test_flags_match_step3_label_pair(self):
        variants = {"baseline": make_resume()}
        variants["skills_gap"] = make_resume()
        variants["skills_gap"]["skills"] = [{"name": "Linux", "proficiency_level": "Advanced", "years": 4}]
        variants["short_experience"] = make_resume()
        variants["short_experience"]["experience"][0].update(start_date="2024-01-01", end_date="2025-07-01")
        variants["director"] = make_resume()
        variants["director"]["experience"][0]["title"] = "Director of Engineering"
        variants["hallucination"] = make_resume()
        variants["hallucination"]["skills"] = [{"name": f"Skill {i}", "proficiency_level": "Expert"} for i in range(20)]
        variants["buzzwords"] = make_resume()
        variants["buzzwords"]["experience"][0]["achievements"] = ["Drove synergy and leverage for holistic best in class value"]
        for name, resume in variants.items():
            with self.subTest(name):
                row = enriched_row(resume=copy.deepcopy(resume))
                expected = {flag: value for flag, value in label_pair(row).items() if flag in FLAGS}
                body = review(resume).json()
                self.assertEqual(body["flags"], expected)

    def test_missing_metadata_is_a_warning_not_an_error(self):
        response = review(without_metadata())
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["integrity"])
        self.assertEqual(body["job_fit"]["actual_fit_level"], "excellent")
        self.assertEqual(body["schema_warnings"], ["resume.metadata: Field required"])

    def test_empty_resume_skills(self):
        resume = without_metadata()
        resume["skills"] = []
        body = review(resume).json()
        self.assertEqual(body["job_fit"]["skills_jaccard"], 0.0)
        self.assertEqual(body["job_fit"]["missing_core_skills"], REQUIRED_SKILLS[:3])
        self.assertTrue(body["flags"]["skills_gap_flag"])
        self.assertIn("resume.skills: List should have at least 1 item after validation, not 0", body["schema_warnings"])

    def test_empty_required_skills_are_not_scored(self):
        job = make_job()["job_description"]
        job["requirements"]["required_skills"] = []
        body = review(job=job).json()
        self.assertIsNone(body["job_fit"]["skills_jaccard"])
        self.assertIsNone(body["integrity"])
        self.assertFalse(body["flags"]["skills_gap_flag"])
        self.assertFalse(body["flags"]["missing_core_skills_flag"])
        self.assertIn("Job lists no required skills", body["detail"][0])

    def test_empty_experience(self):
        resume = without_metadata()
        resume["experience"] = []
        resume["skills"] = [{"name": "Python", "proficiency_level": "Beginner"}]
        body = review(resume).json()
        self.assertEqual(body["resume_checks"]["resume_years"], 0.0)
        self.assertEqual(body["resume_checks"]["resume_seniority_source"], "years")

    def test_minimal_job(self):
        job = {"title": "Data Engineer", "requirements": {"required_skills": ["Python"], "experience_years": 3, "experience_level": "mid"}}
        response = review(job=job)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["schema_warnings"])

    def test_invalid_input_returns_422_json(self):
        missing_contact = make_resume()
        missing_contact.pop("contact_info")
        wrong_type = make_job()["job_description"]
        wrong_type["requirements"]["experience_years"] = "five"
        bad_date = make_resume()
        bad_date["metadata"]["generated_at"] = "yesterday"
        bad_level = make_job()["job_description"]
        bad_level["requirements"]["experience_level"] = "guru"
        cases = {
            "missing_contact_info": ({"resume": missing_contact}, ["body", "resume", "contact_info"]),
            "wrong_type": ({"resume": make_resume(), "job": wrong_type}, ["body", "job", "requirements", "experience_years"]),
            "bad_generated_at": ({"resume": bad_date}, ["body", "resume", "metadata"]),
            "bad_experience_level": ({"resume": make_resume(), "job": bad_level}, ["body", "job", "requirements", "experience_level"]),
            "empty_body": ({}, ["body", "resume"]),
        }
        for name, (body, loc) in cases.items():
            with self.subTest(name):
                response = client.post("/review-resume", json=body)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"], "validation_error")
                self.assertEqual(response.json()["detail"][0]["loc"], loc)

    def test_malformed_json_returns_422_json(self):
        response = client.post("/review-resume", content="{not json", headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"][0]["type"], "json_invalid")

    def test_unexpected_error_returns_500_json(self):
        with patch("src.api.api.resume_checks", side_effect=RuntimeError("boom")), self.assertLogs("src.api.api", level="ERROR"):
            response = review()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"error": "internal_error"})

    def test_response_time_under_two_seconds(self):
        resume = make_resume()
        resume["skills"] = [{"name": f"Skill {i}", "proficiency_level": "Expert", "years": 2} for i in range(30)]
        resume["experience"] = resume["experience"] * 8
        start = time.perf_counter()
        response = review(resume)
        self.assertEqual(response.status_code, 200)
        self.assertLess(time.perf_counter() - start, 2.0)


class FailureRatesTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temporary_directory.name)
        self.patcher = patch("src.config.OUTPUT_DIR", self.output_dir)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temporary_directory.cleanup()

    def write_stats(self, timestamp, **overrides):
        stats = {
            "validation_timestamp": timestamp,
            "pair_count": 2,
            "skipped": {},
            "overall_failure_rates": {flag: 0.5 for flag in FLAGS},
            "any_failure_rate": 0.5,
            "by_group": {},
            "correlation": {"a": {"b": 1.0}},
            "distributions": {"failure_count": {"0": 1}},
            "spot_check": [],
            **overrides,
        }
        (self.output_dir / f"failure_stats_{timestamp}.json").write_text(json.dumps(stats))

    def test_serves_newest_stats_file(self):
        self.write_stats("20260930T120000Z", pair_count=1)
        self.write_stats("20261001T120000Z", pair_count=7)
        body = client.get("/analysis/failure-rates").json()
        self.assertEqual(body["source_file"], "failure_stats_20261001T120000Z.json")
        self.assertEqual(body["pair_count"], 7)
        self.assertNotIn("correlation", body)

    def test_include_adds_sections(self):
        self.write_stats("20260930T120000Z")
        body = client.get("/analysis/failure-rates", params={"include": "correlation, distributions"}).json()
        self.assertEqual(body["correlation"], {"a": {"b": 1.0}})
        self.assertIn("distributions", body)
        self.assertNotIn("spot_check", body)

    def test_unknown_include_returns_422(self):
        self.write_stats("20260930T120000Z")
        response = client.get("/analysis/failure-rates", params={"include": "bogus"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "validation_error")

    def test_no_stats_returns_404(self):
        response = client.get("/analysis/failure-rates")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"], "no_failure_stats")

    def test_corrupt_stats_returns_500(self):
        (self.output_dir / "failure_stats_20260930T120000Z.json").write_text("{not json")
        with self.assertLogs("src.api.api", level="ERROR"):
            response = client.get("/analysis/failure-rates")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"], "invalid_failure_stats")


if __name__ == "__main__":
    unittest.main()
