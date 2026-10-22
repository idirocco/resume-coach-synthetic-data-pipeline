import unittest

from src.resume_metrics import (
    awkward_language_reasons,
    awkward_language_stats,
    hallucination_reasons,
    infer_resume_seniority,
    jaccard,
    resume_years,
    skill_key,
    title_seniority,
)

GENERATED_AT = "2026-01-01T00:00:00+00:00"


def resume_with(experience=None, skills=None):
    return {
        "experience": experience or [],
        "skills": skills or [],
        "metadata": {"generated_at": GENERATED_AT},
    }


class SkillNormalizationTests(unittest.TestCase):
    def test_lowercase_version_and_suffix_stripping(self):
        cases = {
            "Python 3.11": "python",
            "React.js": "react",
            "Node.js Developer": "node",
            "Java8": "java",
            "AWS": "aws",
            "Data Engineer": "data",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(skill_key(raw), expected)


class JaccardSpotCheckTests(unittest.TestCase):
    # Hand-computed: |A ∩ B| / |A ∪ B| after normalization.
    CASES = [
        (["Python", "SQL"], ["Python", "SQL"], 1.0),
        (["Python", "SQL"], ["python 3", "sql"], 1.0),
        (["Python", "SQL", "Git"], ["Python"], 1 / 3),
        (["Python", "SQL"], ["Python", "Excel"], 1 / 3),
        (["A", "B", "C", "D"], ["A", "B", "C", "D", "E"], 4 / 5),
        (["A", "B", "C", "D", "E"], ["A", "B", "C"], 3 / 5),
        (["A", "B", "C", "D", "E"], ["F", "G"], 0.0),
        (["React", "Node.js", "Docker"], ["React.js", "Node", "Kubernetes"], 2 / 4),
        (["Java", "Spring"], ["Java 17", "Spring", "Kotlin", "Gradle"], 2 / 4),
        (["Excel", "Tableau", "SQL", "Python", "R"], ["Excel", "SQL"], 2 / 5),
        (["Welding", "Blueprint reading"], ["welding", "BLUEPRINT READING", "Forklift"], 2 / 3),
        ([], [], 0.0),
    ]

    def test_hand_computed_pairs(self):
        for required, resume, expected in self.CASES:
            with self.subTest(required=required, resume=resume):
                self.assertAlmostEqual(jaccard(required, resume)["score"], expected)

    def test_reports_sets_used(self):
        result = jaccard(["Python", "SQL"], ["Python", "Excel"])
        self.assertEqual(result["intersection"], ["python"])
        self.assertEqual(result["union_size"], 3)


class TimelineTests(unittest.TestCase):
    def test_ongoing_role_ends_at_generated_at(self):
        resume = resume_with([{"start_date": "2024-01-01"}])
        self.assertAlmostEqual(resume_years(resume), 2.0, places=1)

    def test_overlapping_roles_count_once(self):
        resume = resume_with(
            [
                {"start_date": "2020-01-01", "end_date": "2022-01-01"},
                {"start_date": "2021-01-01", "end_date": "2023-01-01"},
            ]
        )
        self.assertAlmostEqual(resume_years(resume), 3.0, places=1)

    def test_gaps_are_not_counted(self):
        resume = resume_with(
            [
                {"start_date": "2018-01-01", "end_date": "2019-01-01"},
                {"start_date": "2021-01-01", "end_date": "2022-01-01"},
            ]
        )
        self.assertAlmostEqual(resume_years(resume), 2.0, places=1)


class SeniorityTests(unittest.TestCase):
    def test_title_mapping(self):
        cases = {
            "Junior Accountant": 0,
            "Entry Level Analyst": 0,
            "Intermediate Developer": 1,
            "Senior Nurse": 2,
            "Sr. Engineer": 2,
            "Staff Engineer": 3,
            "Principal Consultant": 3,
            "Store Manager": 2,
            "Assistant Store Manager": 1,
            "Associate Director": 3,
            "Sales Associate": None,
            "Team Lead": 3,
            "Director of Operations": 4,
            "VP Engineering": 4,
            "Senior Director": 4,
            "Software Engineer": None,
            "Staffing Coordinator": None,
            "Midwest Sales Rep": None,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(title_seniority(title), expected)

    def test_falls_back_to_years_without_keyword(self):
        resume = resume_with([{"title": "Accountant", "start_date": "2019-01-01"}])
        self.assertEqual(infer_resume_seniority(resume), (2, "years"))

    def test_uses_most_recent_title(self):
        resume = resume_with(
            [
                {"title": "Junior Analyst", "start_date": "2018-01-01", "end_date": "2021-01-01"},
                {"title": "Senior Analyst", "start_date": "2021-01-01"},
            ]
        )
        self.assertEqual(infer_resume_seniority(resume), (2, "title"))


class HallucinationTests(unittest.TestCase):
    def codes(self, resume):
        return {reason["code"] for reason in hallucination_reasons(resume)}

    def test_excessive_expert(self):
        skills = [{"name": f"S{i}", "proficiency_level": "Expert"} for i in range(20)]
        resume = resume_with([{"start_date": "2010-01-01"}], skills)
        self.assertEqual(self.codes(resume), {"excessive_expert"})

    def test_entry_overclaim(self):
        skills = [{"name": f"S{i}", "proficiency_level": "Expert"} for i in range(10)]
        resume = resume_with([{"start_date": "2025-06-01"}], skills)
        self.assertEqual(self.codes(resume), {"entry_overclaim"})

    def test_overlapping_roles(self):
        resume = resume_with(
            [
                {"start_date": "2020-01-01", "end_date": "2022-01-01"},
                {"start_date": "2021-06-01"},
            ]
        )
        self.assertEqual(self.codes(resume), {"impossible_timeline"})

    def test_skill_years_exceed_career(self):
        resume = resume_with(
            [{"start_date": "2023-01-01"}],
            [{"name": "Python", "proficiency_level": "Advanced", "years": 8}],
        )
        self.assertEqual(self.codes(resume), {"impossible_timeline"})

    def test_skill_years_within_slack_are_fine(self):
        resume = resume_with(
            [{"start_date": "2023-01-01"}],
            [{"name": "Python", "proficiency_level": "Advanced", "years": 4}],
        )
        self.assertEqual(self.codes(resume), set())

    def test_absolute_claims(self):
        resume = resume_with(
            [{"start_date": "2015-01-01", "achievements": ["Expert in all cloud platforms"]}]
        )
        self.assertEqual(self.codes(resume), {"absolute_claims"})


class AwkwardLanguageTests(unittest.TestCase):
    def test_density_is_per_hundred_words(self):
        words = ["delivered"] * 98
        resume = resume_with([{"start_date": "2020-01-01", "achievements": [" ".join(words) + " synergy leverage"]}])
        stats = awkward_language_stats(resume)
        self.assertEqual(stats["buzzword_density"], 2.0)
        self.assertNotIn("buzzword_density", {reason["code"] for reason in awkward_language_reasons(resume)})

    def test_single_buzzword_in_long_text_is_not_flagged(self):
        text = "Managed vendor contracts and reduced costs across twelve regional sites " * 5 + "using leverage"
        resume = resume_with([{"start_date": "2020-01-01", "achievements": [text]}])
        self.assertEqual(awkward_language_reasons(resume), [])

    def test_variety_and_repetition(self):
        text = (
            "synergy leverage holistic paradigm shift deep dive game changer "
            "and many many many more plain words " + "filler " * 300
        )
        resume = resume_with([{"start_date": "2020-01-01", "achievements": [text]}])
        codes = {reason["code"] for reason in awkward_language_reasons(resume)}
        self.assertEqual(codes, {"buzzword_variety", "repetition"})


if __name__ == "__main__":
    unittest.main()
