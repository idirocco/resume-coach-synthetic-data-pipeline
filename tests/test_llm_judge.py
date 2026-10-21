import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import config
from api import app
from llm_judge import JudgeFailed, JudgeUnavailable, judge_resume, judge_run, render_judge_prompt
from test_api import review
from test_step2_correction import ScriptedClient
from test_step2_validation import make_job, make_resume
from test_step3_failure_analysis import enriched_row


def verdict(**overrides):
    return {
        "trace_id": "model-invented-id",
        "has_hallucinations": False,
        "hallucination_details": "None found.",
        "has_awkward_language": True,
        "awkward_language_details": "'Spearheaded synergy' in the newest role.",
        "overall_quality_score": 0.72,
        "fit_assessment": "Strong match on the required skills at the same seniority.",
        "recommendations": ["Replace 'spearheaded synergy' with the project and its result."],
        "red_flags": [],
        **overrides,
    }


class RenderJudgePromptTests(unittest.TestCase):
    def test_fills_every_placeholder_and_hides_metadata(self):
        resume = make_resume()
        job = make_job()["job_description"]
        prompt = render_judge_prompt(config.JUDGE_PROMPT_PATH.read_text(), "rs-1", "2026-10-01", resume, job)
        self.assertIn("trace_id: rs-1", prompt)
        self.assertIn("today: 2026-10-01", prompt)
        self.assertIn(resume["contact_info"]["name"], prompt)
        self.assertIn(job["title"], prompt)
        # The intended fit level and writing style would bias the judge.
        self.assertNotIn('"fit_level"', prompt)
        self.assertNotIn('"writing_style"', prompt)

    def test_without_job(self):
        prompt = render_judge_prompt(config.JUDGE_PROMPT_PATH.read_text(), "rs-1", "2026-10-01", make_resume())
        self.assertIn("<job_description>\nnone\n</job_description>", prompt)


class JudgeResumeTests(unittest.TestCase):
    def test_trace_id_comes_from_caller(self):
        client = ScriptedClient([verdict()])
        result = judge_resume(client, make_resume(), trace_id="rs-1")
        self.assertEqual(result["trace_id"], "rs-1")
        self.assertEqual(result["overall_quality_score"], 0.72)

    def test_uses_judge_model_not_generator(self):
        calls = []
        client = ScriptedClient([verdict()])
        create = client.chat.completions.create
        client.chat.completions.create = lambda **kwargs: calls.append(kwargs["model"]) or create(**kwargs)
        judge_resume(client, make_resume())
        self.assertEqual(calls, [config.JUDGE_MODEL])
        self.assertNotEqual(config.JUDGE_MODEL, config.MODEL)

    def test_invalid_reply_is_sent_back_and_retried(self):
        client = ScriptedClient([verdict(overall_quality_score=7), verdict()])
        result = judge_resume(client, make_resume(), attempts=2)
        self.assertEqual(result["overall_quality_score"], 0.72)
        self.assertIn("overall_quality_score", client.calls[1][-1]["content"])

    def test_gives_up_after_attempts(self):
        client = ScriptedClient(["not json"])
        with self.assertRaises(JudgeFailed):
            judge_resume(client, make_resume(), attempts=1)


class JudgeRunTests(unittest.TestCase):
    def test_writes_judge_output_with_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            enriched = Path(directory, "pairs_enriched_20261001T000000Z.jsonl")
            rows = [enriched_row(), {**enriched_row(), "pair_id": "blocked", "job": None}]
            enriched.write_text("".join(json.dumps(row) + "\n" for row in rows))
            client = ScriptedClient([verdict(has_hallucinations=True, hallucination_details="Skill years exceed career.")])
            result = judge_run(enriched, directory, client)
            written = json.loads(Path(directory, "judge_output.json").read_text())
        self.assertEqual(result["judge_output_path"].name, "judge_output.json")
        self.assertEqual(written["model"], config.JUDGE_MODEL)
        self.assertEqual(len(written["results"]), 1)
        entry = written["results"][0]
        self.assertEqual(entry["trace_id"], rows[0]["resume"]["metadata"]["trace_id"])
        self.assertEqual(entry["pair_id"], rows[0]["pair_id"])
        summary = written["summary"]
        self.assertEqual(summary["judged"], 1)
        self.assertEqual(summary["failed"], 0)
        self.assertEqual(summary["hallucination_rate"], 1.0)
        self.assertEqual(summary["hallucination_vs_rules"]["judge_only"], 1)

    def test_failed_pairs_are_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            enriched = Path(directory, "pairs_enriched_20261001T000000Z.jsonl")
            enriched.write_text(json.dumps(enriched_row()) + "\n")
            client = ScriptedClient(["{}"] * config.JUDGE_MAX_ATTEMPTS)
            report = judge_run(enriched, directory, client)["report"]
        self.assertEqual(report["summary"]["failed"], 1)
        self.assertEqual(report["results"], [])


class ReviewResumeJudgeTests(unittest.TestCase):
    def test_judge_is_off_by_default(self):
        with patch("api.judge_resume") as judge:
            body = review().json()
        judge.assert_not_called()
        self.assertIsNone(body["judge"])

    def test_judge_query_adds_verdict(self):
        with patch("api._judge_client"), patch("api.judge_resume", return_value=verdict(trace_id="rs-1")) as judge:
            response = TestClient(app).post(
                "/review-resume?judge=1", json={"resume": make_resume(), "job": make_job()["job_description"]}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["judge"]["trace_id"], "rs-1")
        self.assertEqual(judge.call_args.kwargs["attempts"], 1)
        self.assertEqual(judge.call_args.args[2]["title"], make_job()["job_description"]["title"])

    def test_judge_without_key_is_503(self):
        with patch("api._judge_client", side_effect=JudgeUnavailable("OPENROUTER_API_KEY is not set")):
            response = TestClient(app).post("/review-resume?judge=1", json={"resume": make_resume()})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "judge_unavailable")

    def test_judge_failure_is_502(self):
        with patch("api._judge_client"), patch("api.judge_resume", side_effect=JudgeFailed("timeout")):
            response = TestClient(app).post("/review-resume?judge=true", json={"resume": make_resume()})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"], "judge_failed")

    def test_judge_past_deadline_is_504(self):
        def slow(*args, **kwargs):
            time.sleep(0.5)
            return verdict()

        with patch("api._judge_client"), patch("api.judge_resume", side_effect=slow), patch(
            "config.JUDGE_API_TIMEOUT_SECONDS", 0.05
        ):
            response = TestClient(app).post("/review-resume?judge=1", json={"resume": make_resume()})
        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["error"], "judge_timeout")

    def test_api_judge_skips_reasoning(self):
        with patch("api._judge_client"), patch("api.judge_resume", return_value=verdict()) as judge:
            TestClient(app).post("/review-resume?judge=1", json={"resume": make_resume()})
        self.assertFalse(judge.call_args.kwargs["reasoning"])
