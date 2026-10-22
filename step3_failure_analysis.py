"""Step 3: label every resume-job pair with failure metrics and summarize failure patterns."""

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from config import CORE_SKILL_COUNT, OUTPUT_DIR
from resume_metrics import (
    HALLUCINATION_REASONS,
    JOB_LEVEL_SENIORITY,
    SENIORITY_NAMES,
    awkward_language_reasons,
    awkward_language_stats,
    expert_skill_count,
    hallucination_reasons,
    infer_resume_seniority,
    jaccard,
    resume_years,
    skill_key,
)
from schemas import fit_level_for_overlap

ENRICHED_PATTERN = re.compile(r"^pairs_enriched_(\d{8}T\d{6}\d*Z)\.jsonl$")
STATS_PATTERN = re.compile(r"^failure_stats_(\d{8}T\d{6}\d*Z)\.json$")
FLAGS = (
    "skills_gap_flag",
    "experience_mismatch_flag",
    "seniority_mismatch_flag",
    "missing_core_skills_flag",
    "hallucination_flag",
    "awkward_language_flag",
)
GROUP_FIELDS = ("fit_level", "job_template", "resume_writing_style", "is_niche_role", "resume_seniority")
# (field, determined_by): a field whose groups would only repeat another field's groups.
CONFOUND_CHECKS = (("resume_writing_style", "fit_level"),)
# Below "partial" in fit_level_for_overlap.
SKILLS_GAP_THRESHOLD = 0.4
EXPERIENCE_RATIO_THRESHOLD = 0.5
SENIORITY_GAP_THRESHOLD = 1
SPOT_CHECK_COUNT = 10


def discover_latest_enriched(output_dir=OUTPUT_DIR):
    candidates = []
    for path in Path(output_dir).glob("pairs_enriched_*.jsonl"):
        match = ENRICHED_PATTERN.fullmatch(path.name)
        if match:
            candidates.append((match.group(1), path))
    if not candidates:
        raise FileNotFoundError(f"No pairs_enriched_*.jsonl found in {output_dir}; run step2 first")
    return max(candidates)


def discover_latest_stats(output_dir=OUTPUT_DIR):
    """(timestamp, path) of the newest failure_stats file, or None if step 3 has not run."""
    candidates = []
    for path in Path(output_dir).glob("failure_stats_*.json"):
        match = STATS_PATTERN.fullmatch(path.name)
        if match:
            candidates.append((match.group(1), path))
    return max(candidates) if candidates else None


def _corrections_for(timestamp, output_dir):
    """Attempts per corrected (record_type, trace_id) from the correction run that produced this validation."""
    corrections = {}
    for report_path in Path(output_dir).glob("correction_report_*.json"):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("post_validation_timestamp") != timestamp:
            continue
        log_path = report_path.with_name(f"correction_log_{report['correction_timestamp']}.jsonl")
        if not log_path.is_file():
            continue
        for line in log_path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry["outcome"] == "corrected" and entry["trace_id"]:
                corrections[(entry["record_type"], entry["trace_id"])] = entry["attempts"]
    return corrections


def resume_checks(resume):
    """Metrics and flags that need only the resume (no job)."""
    resume_seniority, seniority_source = infer_resume_seniority(resume)
    hallucinations = hallucination_reasons(resume)
    awkward_stats = awkward_language_stats(resume)
    awkward = awkward_language_reasons(resume)
    return {
        "resume_seniority": resume_seniority,
        "resume_seniority_name": SENIORITY_NAMES[resume_seniority],
        "resume_seniority_source": seniority_source,
        "resume_years": resume_years(resume),
        "expert_skill_count": expert_skill_count(resume),
        "hallucination_reasons": sorted({reason["code"] for reason in hallucinations}),
        "buzzword_density": awkward_stats["buzzword_density"],
        "buzzword_hits": awkward_stats["buzzword_hits"],
        "repetition_flag": awkward_stats["repetition"],
        "awkward_language_reasons": [reason["code"] for reason in awkward],
        "hallucination_flag": bool(hallucinations),
        "awkward_language_flag": bool(awkward),
    }


def job_fit_checks(job, resume):
    """Metrics and flags comparing a resume against a job description's requirements."""
    requirements = job["requirements"]
    required_skills = requirements["required_skills"]
    resume_skill_names = [skill["name"] for skill in resume["skills"]]

    overlap = jaccard(required_skills, resume_skill_names)
    resume_keys = set(overlap["resume"])
    core_skills = required_skills[:CORE_SKILL_COUNT]
    missing_core = [skill for skill in core_skills if skill_key(skill) not in resume_keys]

    required_years = requirements["experience_years"]
    years = resume_years(resume)
    experience_ratio = round(years / required_years, 3) if required_years > 0 else None

    job_seniority = JOB_LEVEL_SENIORITY[requirements["experience_level"]]
    resume_seniority, _ = infer_resume_seniority(resume)
    seniority_gap = resume_seniority - job_seniority
    # Pipeline jobs always list required skills; API input may not, and then there is no overlap to score.
    has_required = bool(required_skills)
    return {
        "job_experience_level": requirements["experience_level"],
        "job_seniority": job_seniority,
        "job_seniority_name": SENIORITY_NAMES[job_seniority],
        "seniority_gap": seniority_gap,
        "required_years": required_years,
        "experience_gap_years": round(required_years - years, 2),
        "experience_ratio": experience_ratio,
        "skills_jaccard": round(overlap["score"], 4) if has_required else None,
        "actual_fit_level": fit_level_for_overlap(overlap["score"]) if has_required else None,
        "matched_skills": overlap["intersection"],
        "core_skills": core_skills,
        "missing_core_skills": missing_core,
        "skills_gap_flag": has_required and overlap["score"] < SKILLS_GAP_THRESHOLD,
        "experience_mismatch_flag": experience_ratio is not None and experience_ratio < EXPERIENCE_RATIO_THRESHOLD,
        "seniority_mismatch_flag": abs(seniority_gap) > SENIORITY_GAP_THRESHOLD,
        "missing_core_skills_flag": bool(missing_core),
    }


def label_pair(row, corrections=None):
    """All failure metrics for one enriched pair whose job and resume both validated."""
    corrections = corrections or {}
    job = row["job"]["job_description"]
    resume = row["resume"]
    resume_side = resume_checks(resume)
    job_side = job_fit_checks(job, resume)
    flags = {flag: (resume_side | job_side)[flag] for flag in FLAGS}
    failure_count = sum(flags.values())
    job_attempts = corrections.get(("job", row["job_trace_id"]))
    resume_attempts = corrections.get(("resume", row["resume_trace_id"]))
    return {
        "pair_id": row["pair_id"],
        "job_trace_id": row["job_trace_id"],
        "resume_trace_id": row["resume_trace_id"],
        "fit_level": row["fit_level"],
        "job_template": row["job"]["prompt_template"],
        "resume_writing_style": resume["metadata"]["writing_style"],
        "industry": row["job"]["assigned_industry"],
        "is_niche_role": job["metadata"]["is_niche_role"],
        "job_experience_level": job_side["job_experience_level"],
        "job_seniority": job_side["job_seniority"],
        "resume_seniority": resume_side["resume_seniority"],
        "resume_seniority_name": resume_side["resume_seniority_name"],
        "resume_seniority_source": resume_side["resume_seniority_source"],
        "seniority_gap": job_side["seniority_gap"],
        "required_years": job_side["required_years"],
        "resume_years": resume_side["resume_years"],
        "experience_gap_years": job_side["experience_gap_years"],
        "experience_ratio": job_side["experience_ratio"],
        "skills_jaccard": job_side["skills_jaccard"],
        "matched_skills": job_side["matched_skills"],
        "core_skills": job_side["core_skills"],
        "missing_core_skills": job_side["missing_core_skills"],
        "expert_skill_count": resume_side["expert_skill_count"],
        "hallucination_reasons": resume_side["hallucination_reasons"],
        "buzzword_density": resume_side["buzzword_density"],
        "buzzword_hits": resume_side["buzzword_hits"],
        "repetition_flag": resume_side["repetition_flag"],
        "awkward_language_reasons": resume_side["awkward_language_reasons"],
        **flags,
        "failure_count": failure_count,
        "any_failure": failure_count > 0,
        "validation_status": row["validation_status"],
        "validation_categories": row["validation_categories"],
        "job_corrected": job_attempts is not None,
        "resume_corrected": resume_attempts is not None,
        "correction_attempts": (job_attempts or 0) + (resume_attempts or 0),
    }


def _rate(values):
    return round(sum(values) / len(values), 4) if values else None


def _phi(xs, ys):
    """Pearson correlation of two 0/1 series; None when either never varies."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return round(covariance / math.sqrt(var_x * var_y), 4)


def is_determined_by(values, by_values):
    """True when each value maps to exactly one by-value and the by-values vary.

    Then grouping by `values` only relabels the groups of `by_values`.
    """
    mapping = defaultdict(set)
    for value, by_value in zip(values, by_values):
        mapping[str(value)].add(str(by_value))
    return len(set().union(*mapping.values())) > 1 and all(len(by) == 1 for by in mapping.values())


def confounded_groups(labels):
    return [
        {"field": field, "determined_by": by}
        for field, by in CONFOUND_CHECKS
        if is_determined_by([label[field] for label in labels], [label[by] for label in labels])
    ]


def spot_check(rows, labels, count=SPOT_CHECK_COUNT):
    """Show the sets behind Jaccard for a sample of pairs, and whether step 2's value agrees."""
    checks = []
    for row, label in list(zip(rows, labels))[:count]:
        overlap = jaccard(
            row["job"]["job_description"]["requirements"]["required_skills"],
            [skill["name"] for skill in row["resume"]["skills"]],
        )
        checks.append(
            {
                "pair_id": label["pair_id"],
                "required_normalized": overlap["required"],
                "resume_normalized": overlap["resume"],
                "intersection": overlap["intersection"],
                "union_size": overlap["union_size"],
                "jaccard": label["skills_jaccard"],
                "step2_jaccard": row["skills_jaccard"],
                "matches_step2": row["skills_jaccard"] is not None
                and abs(row["skills_jaccard"] - label["skills_jaccard"]) < 1e-4,
            }
        )
    return checks


def failure_stats(labels, skipped, rows=None):
    n = len(labels)
    overall = {flag: _rate([label[flag] for label in labels]) for flag in FLAGS}
    by_group = {}
    for field in GROUP_FIELDS:
        groups = defaultdict(list)
        for label in labels:
            groups[str(label[field])].append(label)
        by_group[field] = {
            value: {"n": len(members), "rates": {flag: _rate([m[flag] for m in members]) for flag in FLAGS}}
            for value, members in sorted(groups.items())
        }
    columns = {flag: [int(label[flag]) for label in labels] for flag in FLAGS}
    correlation = (
        {a: {b: _phi(columns[a], columns[b]) for b in FLAGS} for a in FLAGS} if n > 1 else {}
    )
    histogram = Counter(min(int(label["skills_jaccard"] * 10), 9) for label in labels)
    return {
        "pair_count": n,
        "skipped": dict(skipped),
        "overall_failure_rates": overall,
        "any_failure_rate": _rate([label["any_failure"] for label in labels]),
        "by_group": by_group,
        "confounded_groups": confounded_groups(labels),
        "correlation": correlation,
        "constant_flags": [flag for flag in FLAGS if len(set(columns[flag])) <= 1],
        "distributions": {
            "skills_jaccard_histogram": {
                f"{bucket / 10:.1f}-{(bucket + 1) / 10:.1f}": histogram[bucket] for bucket in range(10)
            },
            "seniority_gap": dict(sorted(Counter(label["seniority_gap"] for label in labels).items())),
            "failure_count": dict(sorted(Counter(label["failure_count"] for label in labels).items())),
            "hallucination_reasons": {
                reason: sum(reason in label["hallucination_reasons"] for label in labels)
                for reason in HALLUCINATION_REASONS
            },
            "resume_seniority_source": dict(Counter(label["resume_seniority_source"] for label in labels)),
        },
        "spot_check": spot_check(rows, labels) if rows else [],
    }


def analyze_run(enriched_path, output_dir=OUTPUT_DIR):
    enriched_path = Path(enriched_path)
    output_dir = Path(output_dir)
    match = ENRICHED_PATTERN.fullmatch(enriched_path.name)
    timestamp = match.group(1) if match else enriched_path.stem.removeprefix("pairs_enriched_")
    rows = [
        json.loads(line)
        for line in enriched_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    corrections = _corrections_for(timestamp, output_dir)
    labeled_rows = []
    labels = []
    skipped = Counter()
    for row in rows:
        if row["job"] is None or row["resume"] is None:
            skipped[row["validation_status"]] += 1
            continue
        labeled_rows.append(row)
        labels.append(label_pair(row, corrections))

    stats = {"validation_timestamp": timestamp, "source_file": str(enriched_path), **failure_stats(labels, skipped, labeled_rows)}
    labels_path = output_dir / f"failure_labels_{timestamp}.jsonl"
    stats_path = output_dir / f"failure_stats_{timestamp}.json"
    with labels_path.open("w", encoding="utf-8") as handle:
        for label in labels:
            handle.write(json.dumps(label, ensure_ascii=False) + "\n")
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Labeled {len(labels)} pairs ({sum(skipped.values())} skipped: job or resume failed validation).")
    for flag in FLAGS:
        rate = stats["overall_failure_rates"][flag]
        print(f"  {flag}: {'n/a' if rate is None else f'{rate:.0%}'}")
    for confound in stats["confounded_groups"]:
        print(f"  warning: {confound['field']} is fully determined by {confound['determined_by']} in this run")
    print(f"Wrote failure labels to {labels_path}")
    print(f"Wrote failure statistics to {stats_path}")
    return {"labels_path": labels_path, "stats_path": stats_path, "stats": stats}


def analyze_latest_run(output_dir=OUTPUT_DIR):
    _, path = discover_latest_enriched(output_dir)
    return analyze_run(path, output_dir)
