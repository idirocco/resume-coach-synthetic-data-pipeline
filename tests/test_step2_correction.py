import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.correction import build_correction_prompt, error_context
from src.step2_correction import correct_run
from src.step2_validation import validate_run
from test_step2_validation import make_job, make_pair, make_resume


class ScriptedClient:
    """Stand-in for the OpenAI client that replies with the given strings in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs["messages"]))
        reply = self.replies.pop(0)
        content = reply if isinstance(reply, str) else json.dumps(reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def broken_job():
    job = make_job()
    job["job_description"]["company"]["size"] = "tiny"
    return job


class CorrectionLoopTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.output_dir = self.root / "output"
        self.paths = {kind: self.root / f"{kind}_20260930T120000Z.jsonl" for kind in ("jobs", "resumes", "pairs")}

    def tearDown(self):
        self.temporary_directory.cleanup()

    def validate(self, job=None, resume=None, pair=None):
        records = {
            "jobs": job or make_job(),
            "resumes": resume or make_resume(),
            "pairs": pair or make_pair(),
        }
        for kind, path in self.paths.items():
            path.write_text(json.dumps(records[kind]) + "\n", encoding="utf-8")
        return validate_run(self.paths["jobs"], self.paths["resumes"], self.paths["pairs"], self.output_dir)

    def test_job_fixed_on_first_attempt_unblocks_resume_and_pair(self):
        pre = self.validate(job=broken_job())
        self.assertEqual(pre["report"]["summary"]["blocked_records"], 2)
        client = ScriptedClient([make_job()["job_description"]])
        result = correct_run(pre["failure_modes_path"], self.output_dir, client)
        summary = result["report"]["summary"]
        self.assertEqual((summary["attempted"], summary["corrected"]), (1, 1))
        self.assertEqual(summary["success_rate_percent"], 100.0)
        self.assertEqual(summary["avg_attempts_corrected"], 1)
        self.assertEqual(summary["post_success_rate_percent"], 100.0)
        self.assertEqual(summary["unblocked_records"], 2)
        self.assertEqual(result["report"]["corrected_by_attempt"]["1"], 1)

    def test_prompt_carries_error_context_and_original(self):
        pre = self.validate(job=broken_job())
        client = ScriptedClient([make_job()["job_description"]])
        correct_run(pre["failure_modes_path"], self.output_dir, client)
        prompt = client.calls[0][0]["content"]
        self.assertTrue(prompt.startswith("The following data failed validation with these errors:"))
        self.assertIn('"field_path": "company.size"', prompt)
        self.assertIn('"invalid_value": "tiny"', prompt)
        self.assertIn("Original data:", prompt)
        self.assertIn("Please generate a corrected version that fixes these issues.", prompt)

    def test_fixed_on_third_attempt_after_bad_json(self):
        pre = self.validate(job=broken_job())
        client = ScriptedClient(["not json", broken_job()["job_description"], make_job()["job_description"]])
        result = correct_run(pre["failure_modes_path"], self.output_dir, client)
        log = [json.loads(line) for line in result["correction_log_path"].read_text().splitlines()]
        self.assertEqual(log[0]["outcome"], "corrected")
        self.assertEqual(log[0]["attempts"], 3)
        self.assertEqual(log[0]["per_attempt_errors"][0][0]["type"], "json_decode")
        self.assertEqual(result["report"]["corrected_by_attempt"]["3"], 1)
        # The follow-up turn carries the new error, not the original one.
        self.assertIn("json_decode", client.calls[1][-1]["content"])

    def test_permanently_failed_after_max_attempts(self):
        pre = self.validate(job=broken_job())
        client = ScriptedClient([broken_job()["job_description"]] * 3)
        result = correct_run(pre["failure_modes_path"], self.output_dir, client)
        summary = result["report"]["summary"]
        self.assertEqual((summary["corrected"], summary["permanently_failed"]), (0, 1))
        self.assertEqual(
            result["report"]["top_failure_reasons"][0],
            {"field": "company.size", "category": "Type mismatches", "count": 1},
        )
        self.assertEqual(len(client.calls), 3)

    def test_protected_ids_are_restored(self):
        pre = self.validate(job=broken_job())
        fixed = make_job()["job_description"]
        fixed["metadata"]["trace_id"] = "job-renamed-by-llm"
        client = ScriptedClient([fixed])
        result = correct_run(pre["failure_modes_path"], self.output_dir, client)
        self.assertEqual(result["report"]["summary"]["corrected"], 1)
        corrected_jobs = next(self.output_dir.glob("corrected_jobs_*.jsonl")).read_text().splitlines()
        self.assertEqual(json.loads(corrected_jobs[0])["job_description"]["metadata"]["trace_id"], "job-1")

    def test_job_without_ids_gets_pipeline_ids_not_invented_ones(self):
        job = broken_job()
        del job["job_description"]["metadata"]
        pre = self.validate(job=job)
        fixed = make_job()["job_description"]
        fixed["metadata"]["trace_id"] = "trace-12345"
        result = correct_run(pre["failure_modes_path"], self.output_dir, ScriptedClient([fixed]))
        self.assertEqual(result["report"]["summary"]["corrected"], 1)
        corrected_jobs = next(self.output_dir.glob("corrected_jobs_*.jsonl")).read_text().splitlines()
        trace_id = json.loads(corrected_jobs[0])["job_description"]["metadata"]["trace_id"]
        self.assertTrue(trace_id.startswith("jd-"))

    def test_resume_fit_level_context_includes_required_skills(self):
        resume = make_resume()
        resume["skills"] = resume["skills"][:1]
        pre = self.validate(resume=resume)
        client = ScriptedClient([make_resume()])
        result = correct_run(pre["failure_modes_path"], self.output_dir, client)
        self.assertEqual(result["report"]["summary"]["corrected"], 1)
        prompt = client.calls[0][0]["content"]
        self.assertIn('\\"Python\\", \\"SQL\\"', prompt)
        self.assertIn("for fit level excellent", prompt)

    def test_pair_errors_are_not_correctable(self):
        pair = make_pair()
        pair["fit_level"] = "good"
        pre = self.validate(pair=pair)
        result = correct_run(pre["failure_modes_path"], self.output_dir, ScriptedClient([]))
        summary = result["report"]["summary"]
        self.assertEqual((summary["attempted"], summary["not_correctable"]), (0, 1))
        self.assertEqual(result["post_report_path"], pre["failure_modes_path"])


class ErrorContextTests(unittest.TestCase):
    def test_expected_formats(self):
        data = {"company": {"size": "tiny"}, "skills": []}
        errors = [
            {"type": "literal_error", "loc": ["company", "size"], "msg": "bad", "ctx": {"expected": "'1-10' or '11-50'"}},
            {"type": "missing", "loc": ["title"], "msg": "Field required"},
            {"type": "too_short", "loc": ["skills"], "msg": "short", "ctx": {"min_length": 1}},
            {"type": "string_type", "loc": ["company", "name"], "msg": "x", "input": 5},
        ]
        entries = error_context(errors, data)
        self.assertEqual(entries[0]["invalid_value"], "tiny")
        self.assertEqual(entries[0]["expected"], "one of '1-10' or '11-50'")
        self.assertEqual(entries[1]["expected"], "required field; add it")
        self.assertEqual(entries[2]["expected"], "at least 1 items")
        self.assertEqual(entries[3]["invalid_value"], "5")
        self.assertEqual(entries[3]["expected"], "a string")

    def test_prompt_wording(self):
        prompt = build_correction_prompt([], {"a": 1})
        self.assertIn("Original data:\n{\n  \"a\": 1\n}", prompt)
        self.assertIn("Keep every field that is not listed above unchanged.", prompt)


if __name__ == "__main__":
    unittest.main()
