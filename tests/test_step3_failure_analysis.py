import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import main
from step2_validation import validate_run
from step3_failure_analysis import FLAGS, analyze_run, failure_stats, label_pair
from test_step2_validation import REQUIRED_SKILLS, make_job, make_pair, make_resume


def enriched_row(job=None, resume=None, status="valid"):
    job_row = job or make_job()
    resume = resume or make_resume()
    return {
        **make_pair(),
        "validation_status": status,
        "validation_categories": [],
        "job": {
            "prompt_template": job_row["prompt_template"],
            "assigned_industry": job_row["assigned_industry"],
            "job_description": job_row["job_description"],
        },
        "resume": resume,
        "resume_warnings": [],
        "skills_jaccard": 1.0,
        "actual_fit_level": "excellent",
    }


def flags_of(label):
    return {flag for flag in FLAGS if label[flag]}


class LabelPairTests(unittest.TestCase):
    def test_excellent_match_has_no_failures(self):
        label = label_pair(enriched_row())
        self.assertEqual(flags_of(label), set())
        self.assertEqual(label["skills_jaccard"], 1.0)
        self.assertEqual(label["job_seniority"], 1)
        self.assertEqual(label["resume_seniority_source"], "years")
        self.assertEqual(label["experience_ratio"], 1.0)

    def test_skills_gap_and_missing_core(self):
        resume = make_resume()
        resume["skills"] = [{"name": "Linux", "proficiency_level": "Advanced", "years": 4}]
        label = label_pair(enriched_row(resume=resume))
        self.assertEqual(label["skills_jaccard"], 0.2)
        self.assertEqual(label["missing_core_skills"], REQUIRED_SKILLS[:3])
        self.assertEqual(flags_of(label), {"skills_gap_flag", "missing_core_skills_flag"})

    def test_one_missing_core_skill_is_flagged(self):
        resume = make_resume()
        resume["skills"] = [skill for skill in resume["skills"] if skill["name"] != "SQL"]
        label = label_pair(enriched_row(resume=resume))
        self.assertEqual(label["missing_core_skills"], ["SQL"])
        self.assertFalse(label["skills_gap_flag"])
        self.assertTrue(label["missing_core_skills_flag"])

    def test_experience_below_half_of_required(self):
        resume = make_resume()
        resume["experience"][0]["start_date"] = "2024-01-01"
        resume["experience"][0]["end_date"] = "2025-07-01"
        label = label_pair(enriched_row(resume=resume))
        self.assertLess(label["experience_ratio"], 0.5)
        self.assertTrue(label["experience_mismatch_flag"])

    def test_zero_required_years_never_flags_experience(self):
        job = make_job()
        job["job_description"]["requirements"].update(experience_years=0, experience_level="entry")
        label = label_pair(enriched_row(job=job))
        self.assertIsNone(label["experience_ratio"])
        self.assertFalse(label["experience_mismatch_flag"])

    def test_seniority_gap_over_one_level(self):
        resume = make_resume()
        resume["experience"][0]["title"] = "Director of Engineering"
        label = label_pair(enriched_row(resume=resume))
        self.assertEqual((label["job_seniority"], label["resume_seniority"], label["seniority_gap"]), (1, 4, 3))
        self.assertTrue(label["seniority_mismatch_flag"])

    def test_one_level_gap_is_not_a_mismatch(self):
        resume = make_resume()
        resume["experience"][0]["title"] = "Senior Software Engineer"
        label = label_pair(enriched_row(resume=resume))
        self.assertEqual(label["seniority_gap"], 1)
        self.assertFalse(label["seniority_mismatch_flag"])

    def test_hallucination_reasons_are_recorded(self):
        resume = make_resume()
        resume["skills"] = [{"name": f"Skill {i}", "proficiency_level": "Expert"} for i in range(20)]
        label = label_pair(enriched_row(resume=resume))
        self.assertEqual(label["hallucination_reasons"], ["excessive_expert"])
        self.assertTrue(label["hallucination_flag"])

    def test_awkward_language(self):
        resume = make_resume()
        resume["experience"][0]["achievements"] = ["Drove synergy and leverage for holistic best in class value"]
        label = label_pair(enriched_row(resume=resume))
        self.assertGreater(label["buzzword_density"], 2)
        self.assertTrue(label["awkward_language_flag"])

    def test_corrections_are_linked(self):
        label = label_pair(enriched_row(), {("job", "job-1"): 2})
        self.assertTrue(label["job_corrected"])
        self.assertFalse(label["resume_corrected"])
        self.assertEqual(label["correction_attempts"], 2)


class StatsTests(unittest.TestCase):
    def test_constant_flags_have_no_correlation(self):
        labels = [label_pair(enriched_row()), label_pair(enriched_row())]
        stats = failure_stats(labels, {})
        self.assertIsNone(stats["correlation"]["skills_gap_flag"]["hallucination_flag"])
        self.assertEqual(set(stats["constant_flags"]), set(FLAGS))

    def test_co_occurring_flags_correlate(self):
        gap = make_resume()
        gap["skills"] = [{"name": "Linux", "proficiency_level": "Advanced", "years": 4}]
        labels = [label_pair(enriched_row()), label_pair(enriched_row(resume=gap))]
        stats = failure_stats(labels, {})
        self.assertEqual(stats["correlation"]["skills_gap_flag"]["missing_core_skills_flag"], 1.0)
        self.assertEqual(stats["by_group"]["fit_level"]["excellent"]["n"], 2)
        self.assertEqual(stats["overall_failure_rates"]["skills_gap_flag"], 0.5)


class AnalyzeRunTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.output_dir = self.root / "output"
        self.output_dir.mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_end_to_end_from_step2_with_jaccard_agreement(self):
        jobs = self.root / "jobs_20260930T120000Z.jsonl"
        resumes = self.root / "resumes_20260930T120000Z.jsonl"
        pairs = self.root / "pairs_20260930T120000Z.jsonl"
        good = make_resume()
        good["metadata"].update(trace_id="resume-2", fit_level="good")
        good["skills"] = good["skills"][:3]
        jobs.write_text(json.dumps(make_job()) + "\n")
        resumes.write_text(json.dumps(make_resume()) + "\n" + json.dumps(good) + "\n")
        second_pair = {**make_pair(), "pair_id": "pair-2", "resume_trace_id": "resume-2", "fit_level": "good"}
        pairs.write_text(json.dumps(make_pair()) + "\n" + json.dumps(second_pair) + "\n")
        validation = validate_run(jobs, resumes, pairs, self.output_dir)
        result = analyze_run(validation["enriched_path"], self.output_dir)
        stats = result["stats"]
        self.assertEqual(stats["pair_count"], 2)
        self.assertTrue(all(check["matches_step2"] for check in stats["spot_check"]))
        labels = [json.loads(line) for line in result["labels_path"].read_text().splitlines()]
        self.assertEqual([label["skills_jaccard"] for label in labels], [1.0, 0.6])
        self.assertTrue(result["labels_path"].name.startswith("failure_labels_"))

    def test_pairs_without_valid_job_or_resume_are_skipped(self):
        rows = [enriched_row(), {**enriched_row(status="blocked"), "job": None}]
        path = self.output_dir / "pairs_enriched_20260930T120000000000Z.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        result = analyze_run(path, self.output_dir)
        self.assertEqual(result["stats"]["pair_count"], 1)
        self.assertEqual(result["stats"]["skipped"], {"blocked": 1})
        self.assertEqual(result["stats"]["validation_timestamp"], "20260930T120000000000Z")

    def test_step3_cli_runs_latest_analysis(self):
        with patch("pipeline.run_startup_checks"), patch("step3_failure_analysis.analyze_latest_run") as analyze:
            main(["step3"])
        analyze.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
