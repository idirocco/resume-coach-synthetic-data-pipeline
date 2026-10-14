import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import main
from step3_failure_analysis import FLAGS
from step4_visualization import discover_latest_labels, load_labels, visualize_run

TIMESTAMP = "20261001T120000000000Z"
EXPECTED_CHARTS = {
    "1_failure_mode_correlation.png",
    "2_failure_rates_by_fit_level.png",
    "3_failure_rates_by_job_template.png",
    "3b_failure_rates_by_writing_style.png",
    "4_niche_vs_standard_roles.png",
    "5_schema_validation_heatmap.png",
    "6_hallucination_by_seniority.png",
    "7_skills_overlap_by_fit_level.png",
    "8_correction_success_by_category.png",
    "9_correction_attempts.png",
}


def label_row(index, fit_level="good", flags=(), niche=False, seniority=1, reasons=()):
    row = {
        "pair_id": f"pair-{index}",
        "fit_level": fit_level,
        "job_template": "niche_specialist" if niche else "formal_corporate",
        "resume_writing_style": "concise",
        "is_niche_role": niche,
        "resume_seniority": seniority,
        "skills_jaccard": 0.7,
        "hallucination_reasons": list(reasons),
    }
    row.update({flag: flag in flags for flag in FLAGS})
    return row


class VisualizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.output_dir = self.root / "output"
        self.viz_dir = self.root / "viz"
        self.output_dir.mkdir()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_labels(self, rows):
        path = self.output_dir / f"failure_labels_{TIMESTAMP}.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def assert_all_charts(self, result):
        names = {path.name for path in result["charts"]}
        self.assertEqual(names, EXPECTED_CHARTS)
        for path in result["charts"]:
            self.assertGreater(path.stat().st_size, 2000, path.name)
        self.assertTrue(result["table"].is_file())

    def test_clean_data_without_reports_still_writes_every_chart(self):
        rows = [label_row(i, fit_level=level) for i, level in enumerate(("excellent", "good", "partial"))]
        result = visualize_run(self.write_labels(rows), self.output_dir, self.viz_dir)
        self.assert_all_charts(result)
        self.assertEqual(result["directory"].name, TIMESTAMP)

    def test_full_data_with_schema_errors_and_corrections(self):
        flags_a = ("skills_gap_flag", "missing_core_skills_flag", "hallucination_flag")
        rows = [
            label_row(0, "excellent"),
            label_row(1, "good", flags=("seniority_mismatch_flag",)),
            label_row(2, "poor", flags=flags_a, niche=True, seniority=0, reasons=("excessive_expert", "impossible_timeline")),
            label_row(3, "complete_mismatch", flags=flags_a + ("awkward_language_flag",), seniority=3, reasons=("entry_overclaim",)),
            label_row(4, "partial", flags=("experience_mismatch_flag", "missing_core_skills_flag"), seniority=2),
        ]
        (self.output_dir / f"schema_failure_modes_{TIMESTAMP}.json").write_text(
            json.dumps(
                {
                    "summary": {"success_rate_percent": 80.0, "success_rate_target_percent": 90},
                    "field_category_counts": {
                        "job.job_description.company.size": {"Type mismatches": 3},
                        "resume.experience[].end_date": {"Logical inconsistencies": 2, "Format violations": 1},
                    },
                }
            )
        )
        correction_timestamp = "20261001T120100000000Z"
        (self.output_dir / f"correction_report_{correction_timestamp}.json").write_text(
            json.dumps(
                {
                    "correction_timestamp": correction_timestamp,
                    "pre_validation_timestamp": TIMESTAMP,
                    "post_validation_timestamp": TIMESTAMP,
                    "max_attempts": 3,
                    "summary": {
                        "attempted": 4,
                        "corrected": 3,
                        "permanently_failed": 1,
                        "success_rate_percent": 75.0,
                        "success_rate_target_percent": 50,
                        "avg_attempts_corrected": 1.67,
                        "pre_success_rate_percent": 80.0,
                    },
                    "corrected_by_attempt": {"1": 2, "2": 0, "3": 1},
                    "by_category": {
                        "Type mismatches": {"attempted": 3, "corrected": 2, "success_rate_percent": 66.67},
                        "Logical inconsistencies": {"attempted": 1, "corrected": 1, "success_rate_percent": 100.0},
                    },
                }
            )
        )
        result = visualize_run(self.write_labels(rows), self.output_dir, self.viz_dir)
        self.assert_all_charts(result)
        table = result["table"].read_text(encoding="utf-8")
        self.assertIn("fit_level,poor,1,hallucination_flag,100.0", table)
        self.assertIn("role_type,Niche,1,skills_gap_flag,100.0", table)

    def test_pre_correction_schema_report_is_used(self):
        correction_timestamp = "20261001T120100000000Z"
        pre_timestamp = "20261001T110000000000Z"
        (self.output_dir / f"schema_failure_modes_{pre_timestamp}.json").write_text(
            json.dumps(
                {
                    "summary": {"success_rate_percent": 50.0, "success_rate_target_percent": 90},
                    "field_category_counts": {"job.title": {"Missing required fields": 1}},
                }
            )
        )
        (self.output_dir / f"correction_report_{correction_timestamp}.json").write_text(
            json.dumps(
                {
                    "correction_timestamp": correction_timestamp,
                    "pre_validation_timestamp": pre_timestamp,
                    "post_validation_timestamp": TIMESTAMP,
                    "max_attempts": 3,
                    "summary": {"attempted": 0, "pre_success_rate_percent": 50.0},
                }
            )
        )
        from step4_visualization import load_correction_report, load_schema_report

        report = load_correction_report(TIMESTAMP, self.output_dir)
        schema = load_schema_report(TIMESTAMP, report, self.output_dir)
        self.assertEqual(schema["summary"]["success_rate_percent"], 50.0)

    def test_latest_labels_are_discovered_and_empty_input_is_rejected(self):
        path = self.write_labels([label_row(0)])
        self.assertEqual(discover_latest_labels(self.output_dir), (TIMESTAMP, path))
        self.write_labels([])
        with self.assertRaisesRegex(ValueError, "no labeled pairs"):
            load_labels(path)
        with self.assertRaises(FileNotFoundError):
            discover_latest_labels(self.root)

    def test_step4_cli_runs_latest_visualization(self):
        with patch("pipeline.run_startup_checks"), patch("step4_visualization.visualize_latest_run") as visualize:
            main(["step4"])
        visualize.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
