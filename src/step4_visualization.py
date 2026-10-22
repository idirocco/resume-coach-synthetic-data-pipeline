"""Step 4: charts from the step 3 failure labels (plus step 2 schema errors and the correction report)."""

import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle

from src.config import FAILURE_TARGETS, OUTPUT_DIR, PROMPT_TEMPLATES, RESUME_WRITING_STYLES, VISUALIZATIONS_DIR
from src.resume_metrics import HALLUCINATION_REASONS, SENIORITY_NAMES
from src.step2_validation import ERROR_CATEGORIES
from src.step3_failure_analysis import FLAGS, is_determined_by

LABELS_PATTERN = re.compile(r"^failure_labels_(\d{8}T\d{6}\d*Z)\.jsonl$")
FIT_LEVELS = ("excellent", "good", "partial", "poor", "complete_mismatch")
LOW_N = 5
SCHEMA_HEATMAP_ROWS = 15

# Reference palette (dataviz skill): categorical slots 1-6 validated for adjacent bars on the light surface.
SURFACE, INK, INK_SECONDARY, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
CRITICAL = "#d03b3b"
SEQUENTIAL = LinearSegmentedColormap.from_list("seq_blue", ["#cde2fb", "#86b6ef", "#2a78d6", "#184f95", "#0d366b"])
DIVERGING = LinearSegmentedColormap.from_list("div_blue_red", ["#2a78d6", "#f0efec", "#e34948"])
ORDINAL_BLUES = ["#104281", "#1c5cab", "#2a78d6", "#5598e7", "#86b6ef"]  # excellent (dark) -> complete_mismatch (light)

FLAG_LABELS = {
    "skills_gap_flag": "Skills gap (Jaccard < 0.4)",
    "experience_mismatch_flag": "Experience < 50% of required",
    "seniority_mismatch_flag": "Seniority gap > 1 level",
    "missing_core_skills_flag": "Missing a top-3 required skill",
    "hallucination_flag": "Hallucination",
    "awkward_language_flag": "Awkward language",
}
FLAG_COLORS = dict(zip(FLAGS, SERIES))
HALLUCINATION_LABELS = {
    "excessive_expert": "20+ expert skills",
    "entry_overclaim": "Entry-level overclaim",
    "impossible_timeline": "Impossible timeline",
    "absolute_claims": "'Expert in all' claims",
}
FIT_BANDS = {"excellent": "≥ 0.8", "good": "0.6-0.8", "partial": "0.4-0.6", "poor": "0.2-0.4", "complete_mismatch": "< 0.2"}


def _style():
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": AXIS,
            "axes.labelcolor": INK_SECONDARY,
            "axes.titlecolor": INK,
            "text.color": INK,
            "xtick.color": INK_SECONDARY,
            "ytick.color": INK_SECONDARY,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "font.family": "sans-serif",
            "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


# --- Loading ----------------------------------------------------------------


def discover_latest_labels(output_dir=OUTPUT_DIR):
    candidates = []
    for path in Path(output_dir).glob("failure_labels_*.jsonl"):
        match = LABELS_PATTERN.fullmatch(path.name)
        if match:
            candidates.append((match.group(1), path))
    if not candidates:
        raise FileNotFoundError(f"No failure_labels_*.jsonl found in {output_dir}; run step3 first")
    return max(candidates)


def load_labels(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"{path} contains no labeled pairs")
    for flag in FLAGS:
        df[flag] = df[flag].astype(bool)
    df["role_type"] = np.where(df["is_niche_role"], "Niche", "Standard")
    return df


def load_correction_report(timestamp, output_dir):
    """Correction report for the validation run step 3 labeled, if any."""
    matches = []
    for path in Path(output_dir).glob("correction_report_*.json"):
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("post_validation_timestamp") == timestamp:
            matches.append((report["correction_timestamp"], report))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def load_schema_report(timestamp, correction_report, output_dir):
    """Step 2 report from before correction: the schema heatmap is about what the generator gets wrong."""
    pre_timestamp = correction_report["pre_validation_timestamp"] if correction_report else timestamp
    path = Path(output_dir) / f"schema_failure_modes_{pre_timestamp}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


# --- Shared drawing helpers -------------------------------------------------


def _save(fig, path):
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def _title(ax, title, subtitle=None):
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold", pad=24 if subtitle else 10)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color=INK_SECONDARY, va="bottom")


def placeholder(path, title, message):
    """A chart with no data still gets a PNG that says why."""
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=11, color=INK_SECONDARY, wrap=True, transform=ax.transAxes)
    _title(ax, title)
    return _save(fig, path)


def _style_axes(ax, ylabel, xlabel=None):
    ax.set_ylabel(ylabel)
    if xlabel:
        ax.set_xlabel(xlabel)
    ax.grid(axis="y")
    ax.set_axisbelow(True)


def _group_rates(df, field, order):
    groups = []
    for name in order:
        sub = df[df[field] == name]
        rates = {flag: (100 * sub[flag].mean() if len(sub) else np.nan) for flag in FLAGS}
        groups.append((name, len(sub), rates))
    return groups


def _draw_targets(ax, groups, scope_labels=None):
    """Dashed target lines (named in the legend); targets limited to some fit levels are drawn only over those groups."""
    handles = []
    by_target = {}
    for flag, (value, fit_levels) in FAILURE_TARGETS.items():
        by_target.setdefault((value, fit_levels), []).append(FLAG_LABELS[flag].split(" (")[0])
    for (value, fit_levels), names in sorted(by_target.items(), key=lambda item: item[0][0]):
        if fit_levels and scope_labels:
            spans = [(i - 0.45, i + 0.45) for i, (name, _, _) in enumerate(groups) if name in fit_levels]
        else:
            spans = [(-0.5, len(groups) - 0.5)]
        for left, right in spans:
            ax.hlines(value, left, right, colors=INK_SECONDARY, linestyles="--", linewidth=1.2, zorder=4)
        suffix = " (excellent/good fits)" if fit_levels else ""
        handles.append(
            Line2D([0], [0], color=INK_SECONDARY, linestyle="--", linewidth=1.2, label=f"Target ≤{value:g}%{suffix}: " + ", ".join(names))
        )
    return handles


def grouped_bars(path, groups, title, subtitle, xlabel, fit_scoped_targets=False, note=None):
    """One cluster per group, one bar per failure flag. Groups with fewer than LOW_N pairs are hatched."""
    fig, ax = plt.subplots(figsize=(max(8, 1.7 * len(groups) + 3), 5.5))
    width = 0.8 / len(FLAGS)
    for j, flag in enumerate(FLAGS):
        for i, (_, n, rates) in enumerate(groups):
            if n == 0:
                continue
            ax.bar(
                i - 0.4 + width * (j + 0.5),
                rates[flag],
                width=width,
                color=FLAG_COLORS[flag],
                edgecolor=SURFACE,
                linewidth=1.5,
                hatch="///" if n < LOW_N else None,
            )
    target_handles = _draw_targets(ax, groups, scope_labels=fit_scoped_targets)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([f"{name.replace('_', ' ')}\n(n={n})" for name, n, _ in groups])
    ax.set_ylim(0, 105)
    ax.set_xlim(-0.5, len(groups) - 0.5)
    ax.yaxis.set_major_formatter(lambda value, _: f"{value:.0f}%")
    _style_axes(ax, "Pairs with the failure (%)", xlabel)
    handles = [Patch(facecolor=FLAG_COLORS[flag], label=FLAG_LABELS[flag]) for flag in FLAGS]
    if any(n < LOW_N for _, n, _ in groups):
        handles.append(Patch(facecolor="white", edgecolor=INK_SECONDARY, hatch="///", label=f"Hatched: fewer than {LOW_N} pairs"))
    ax.legend(handles=handles + target_handles, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, frameon=False, fontsize=8.5)
    _title(ax, title, subtitle)
    if note:
        ax.text(0, -0.52, note, transform=ax.transAxes, fontsize=8, color=MUTED, ha="left", va="top")
    return _save(fig, path)


# --- Charts -----------------------------------------------------------------


def chart_correlation(df, path):
    corr = df[list(FLAGS)].astype(int).corr()
    n = len(df)
    mask = np.triu(np.ones_like(corr, dtype=bool), k=0)
    fig, ax = plt.subplots(figsize=(8, 6.5))
    sns.heatmap(
        corr,
        mask=mask | corr.isna().to_numpy(),
        annot=True,
        fmt=".2f",
        cmap=DIVERGING,
        vmin=-1,
        vmax=1,
        center=0,
        linewidths=2,
        linecolor=SURFACE,
        square=True,
        cbar_kws={"label": "Phi correlation (-1 = never together, +1 = always together)", "shrink": 0.8},
        annot_kws={"fontsize": 10},
        ax=ax,
    )
    constant = [flag for flag in FLAGS if df[flag].nunique() <= 1]
    for i, row_flag in enumerate(FLAGS):
        for j, col_flag in enumerate(FLAGS):
            if j < i and np.isnan(corr.loc[row_flag, col_flag]):
                ax.add_patch(Rectangle((j, i), 1, 1, facecolor="#eceae4", edgecolor=SURFACE, linewidth=2))
                ax.text(j + 0.5, i + 0.5, "n/a", ha="center", va="center", fontsize=9, color=MUTED)
    labels = [FLAG_LABELS[flag].split(" (")[0] for flag in FLAGS]
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_yticklabels(labels, rotation=0)
    ax.set_xlim(0, len(FLAGS) - 1)
    ax.set_ylim(len(FLAGS), 1)
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.grid(False)
    _title(ax, "Which failure modes co-occur?", f"Phi correlation between the six failure flags across {n} resume-job pairs")
    notes = ["|phi| above about 0.5 means two failures usually appear together."]
    if constant:
        notes.append("n/a = flag never (or always) set, so no correlation: " + ", ".join(FLAG_LABELS[f].split(" (")[0] for f in constant) + ".")
    ax.text(0, -0.28, "\n".join(notes), transform=ax.transAxes, fontsize=8, color=MUTED, ha="left", va="top")
    return _save(fig, path)


def chart_by_fit_level(df, path):
    groups = _group_rates(df, "fit_level", [level for level in FIT_LEVELS if (df["fit_level"] == level).any()] or list(FIT_LEVELS))
    return grouped_bars(
        path,
        groups,
        "Do poorer-fit resumes fail more often?",
        f"Share of pairs with each failure, by intended fit level ({len(df)} pairs)",
        "Intended fit level of the resume",
        fit_scoped_targets=True,
        note="Skills, core-skill and seniority gaps are expected for weaker fits; they confirm the generator hits its fit levels.",
    )


def chart_by_template(df, path):
    order = [name for name in PROMPT_TEMPLATES if (df["job_template"] == name).any()]
    return grouped_bars(
        path,
        _group_rates(df, "job_template", order),
        "Which job-description styles cause the most failures?",
        f"Share of pairs with each failure, by the prompt template that wrote the job ({len(df)} pairs)",
        "Job description template",
        note="Reference lines are the strong-fit targets; each template mixes all fit levels.",
    )


def chart_by_writing_style(df, path):
    title = "Which resume writing styles cause the most failures?"
    if is_determined_by(df["resume_writing_style"], df["fit_level"]):
        return placeholder(
            path,
            title,
            "Writing style is fully determined by fit level in this run, so this chart would repeat the fit-level chart.\n"
            "Regenerate data after the style rotation fix.",
        )
    order = [name for name in RESUME_WRITING_STYLES if (df["resume_writing_style"] == name).any()]
    return grouped_bars(
        path,
        _group_rates(df, "resume_writing_style", order),
        title,
        f"Share of pairs with each failure, by resume writing style ({len(df)} pairs)",
        "Resume writing style",
        note="Reference lines are the strong-fit targets; each style mixes all fit levels.",
    )


def chart_niche_vs_standard(df, path):
    groups = _group_rates(df, "role_type", ["Standard", "Niche"])
    note = "Niche roles come from the niche_specialist template, so this chart overlaps with the template chart."
    if (df["role_type"] == "Niche").sum() == 0:
        note = "No niche roles in this run (the niche_specialist template produced no valid job); rerun generation to compare."
    return grouped_bars(
        path,
        groups,
        "Do niche roles fail differently from standard roles?",
        f"Share of pairs with each failure, niche vs standard roles ({len(df)} pairs)",
        "Role type",
        note=note,
    )


def chart_schema_heatmap(schema_report, path):
    title = "Which fields fail schema validation most often?"
    if schema_report is None:
        return placeholder(path, title, "No step 2 report (schema_failure_modes) found for this run.")
    summary = schema_report["summary"]
    rate = summary["success_rate_percent"]
    target = summary["success_rate_target_percent"]
    status = "meets" if rate >= target else "below"
    subtitle = f"Validation errors by field and error category (before correction). Step 2 success rate {rate:g}% ({status} the {target}% target)"
    counts = schema_report.get("field_category_counts", {})
    if not counts:
        return placeholder(path, title, f"No schema validation errors in this run.\nStep 2 success rate {rate:g}% (target {target}%).")
    table = pd.DataFrame(counts).T.reindex(columns=list(ERROR_CATEGORIES)).fillna(0).astype(int)
    table = table.loc[table.sum(axis=1).sort_values(ascending=False).index][:SCHEMA_HEATMAP_ROWS]
    fig, ax = plt.subplots(figsize=(9, max(3.5, 0.45 * len(table) + 2.2)))
    sns.heatmap(
        table,
        mask=table == 0,
        annot=True,
        fmt="d",
        cmap=SEQUENTIAL,
        vmin=0,
        linewidths=2,
        linecolor=SURFACE,
        cbar_kws={"label": "Errors", "shrink": 0.8},
        ax=ax,
    )
    ax.set_xticklabels(ax.get_xticklabels(), rotation=20, ha="right")
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=8)
    ax.set_xlabel("Error category")
    ax.set_ylabel("Record type . field (list positions collapsed)")
    ax.grid(False)
    _title(ax, title, subtitle)
    hidden = len(counts) - len(table)
    if hidden > 0:
        fig.text(0.01, -0.02, f"Showing the top {len(table)} of {len(counts)} fields.", fontsize=8, color=MUTED, ha="left")
    return _save(fig, path)


def chart_hallucination_by_seniority(df, path):
    levels = sorted(SENIORITY_NAMES)
    totals = [int((df["resume_seniority"] == level).sum()) for level in levels]
    fig, ax = plt.subplots(figsize=(9, 5))
    bottoms = np.zeros(len(levels))
    for color, reason in zip(SERIES, HALLUCINATION_REASONS):
        values = np.array(
            [
                100 * sum(reason in reasons for reasons in df.loc[df["resume_seniority"] == level, "hallucination_reasons"]) / total
                if total
                else 0.0
                for level, total in zip(levels, totals)
            ]
        )
        ax.bar(levels, values, bottom=bottoms, color=color, edgecolor=SURFACE, linewidth=2, width=0.6, label=HALLUCINATION_LABELS[reason])
        bottoms += values
    target = FAILURE_TARGETS["hallucination_flag"][0]
    ax.axhline(target, color=INK_SECONDARY, linestyle="--", linewidth=1.2, zorder=4)
    ax.text(len(levels) - 0.55, target + 0.4, f"Target ≤{target:g}% of pairs", ha="right", va="bottom", fontsize=8, color=INK_SECONDARY)
    ax.set_xticks(levels)
    ax.set_xticklabels([f"{SENIORITY_NAMES[level]}\n(n={total})" for level, total in zip(levels, totals)], fontsize=8.5)
    ax.set_ylim(0, max(10, bottoms.max() * 1.1))
    ax.yaxis.set_major_formatter(lambda value, _: f"{value:.0f}%")
    _style_axes(ax, "Pairs with the hallucination (%)", "Resume seniority (inferred from latest job title, else years)")
    if bottoms.sum() == 0:
        ax.text(0.5, 0.7, f"No hallucination flags in this run ({len(df)} pairs)", transform=ax.transAxes, ha="center", fontsize=11, color=INK_SECONDARY)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, frameon=False, fontsize=8.5)
    _title(ax, "Do entry-level resumes hallucinate more than senior ones?", f"Share of pairs flagged for hallucination, stacked by reason ({len(df)} pairs)")
    ax.text(0, -0.36, "A resume flagged for several reasons counts once in each reason's segment.", transform=ax.transAxes, fontsize=8, color=MUTED, ha="left", va="top")
    return _save(fig, path)


def chart_jaccard_by_fit_level(df, path):
    order = [level for level in FIT_LEVELS if (df["fit_level"] == level).any()]
    palette = dict(zip(FIT_LEVELS, ORDINAL_BLUES))
    fig, ax = plt.subplots(figsize=(9, 5))
    sns.boxplot(
        data=df,
        x="fit_level",
        y="skills_jaccard",
        order=order,
        hue="fit_level",
        palette=palette,
        legend=False,
        width=0.5,
        linewidth=1.2,
        fliersize=0,
        ax=ax,
    )
    sns.stripplot(data=df, x="fit_level", y="skills_jaccard", order=order, color=INK, size=4, jitter=0.12, alpha=0.8, ax=ax)
    for boundary in (0.2, 0.4, 0.6, 0.8):
        ax.axhline(boundary, color=INK_SECONDARY, linestyle="--", linewidth=1, zorder=0)
    for level, (low, high) in zip(FIT_LEVELS, [(0.8, 1.0), (0.6, 0.8), (0.4, 0.6), (0.2, 0.4), (0.0, 0.2)]):
        ax.text(len(order) - 0.42, (low + high) / 2, f"{level.replace('_', ' ')} band {FIT_BANDS[level]}", fontsize=7.5, color=MUTED, va="center", ha="left")
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([f"{level.replace('_', ' ')}\n(n={(df['fit_level'] == level).sum()})" for level in order])
    ax.set_xlim(-0.5, len(order) - 0.5)
    ax.set_ylim(-0.02, 1.05)
    _style_axes(ax, "Skills overlap (Jaccard similarity)", "Intended fit level of the resume")
    _title(ax, "Does skills overlap match the intended fit level?", f"Jaccard overlap of required vs resume skills; dashed lines are the fit-level boundaries ({len(df)} pairs)")
    return _save(fig, path)


def chart_correction_success(report, path):
    title = "How often does the correction loop fix invalid records?"
    if report is None:
        return placeholder(path, title, "No correction run found for this validation run.")
    summary = report["summary"]
    if summary["attempted"] == 0:
        return placeholder(path, title, f"No invalid records needed correction in this run.\nStep 2 success rate {summary['pre_success_rate_percent']:g}%.")
    rows = [("All attempted", summary["attempted"], summary["success_rate_percent"])]
    rows += [(name.replace(" ", "\n", 1), v["attempted"], v["success_rate_percent"]) for name, v in report["by_category"].items()]
    fig, ax = plt.subplots(figsize=(max(7, 1.5 * len(rows) + 2), 5))
    for i, (_, _, rate) in enumerate(rows):
        ax.bar(i, rate, color=SERIES[0], edgecolor=SURFACE, linewidth=2, width=0.55, hatch="///" if rows[i][1] < LOW_N else None)
        ax.text(i, rate + 2, f"{rate:g}%", ha="center", va="bottom", fontsize=9, color=INK)
    target = summary["success_rate_target_percent"]
    ax.axhline(target, color=INK_SECONDARY, linestyle="--", linewidth=1.2, zorder=4)
    ax.legend(
        handles=[Line2D([0], [0], color=INK_SECONDARY, linestyle="--", linewidth=1.2, label=f"Target: more than {target}% corrected")],
        loc="upper right",
        frameon=False,
        fontsize=8.5,
    )
    ax.set_xticks(range(len(rows)))
    ax.set_xticklabels([f"{name}\n(n={n})" for name, n, _ in rows], fontsize=8.5)
    ax.set_ylim(0, 115)
    ax.yaxis.set_major_formatter(lambda value, _: f"{value:.0f}%")
    _style_axes(ax, "Records corrected within 3 attempts (%)", "Original error category (a record can appear in several)")
    _title(ax, title, f"{summary['corrected']} of {summary['attempted']} correctable invalid records fixed")
    if any(n < LOW_N for _, n, _ in rows):
        ax.text(0, -0.28, f"Hatched: fewer than {LOW_N} records, so the rate is not reliable.", transform=ax.transAxes, fontsize=8, color=MUTED, ha="left", va="top")
    return _save(fig, path)


def chart_correction_attempts(report, path):
    title = "How many attempts does a correction take?"
    if report is None:
        return placeholder(path, title, "No correction run found for this validation run.")
    summary = report["summary"]
    if summary["attempted"] == 0:
        return placeholder(path, title, "No invalid records needed correction in this run.")
    attempts = report["corrected_by_attempt"]
    labels = [f"Fixed on\nattempt {attempt}" for attempt in attempts] + ["Not fixed after\n" + f"{report['max_attempts']} attempts"]
    values = list(attempts.values()) + [summary["permanently_failed"]]
    fig, ax = plt.subplots(figsize=(8, 5))
    colors = [SERIES[0]] * len(attempts) + [CRITICAL]
    ax.bar(range(len(values)), values, color=colors, edgecolor=SURFACE, linewidth=2, width=0.55)
    for i, value in enumerate(values):
        ax.text(i, value + 0.05 * max(values + [1]), str(value), ha="center", va="bottom", fontsize=10)
    ax.set_xticks(range(len(values)))
    ax.set_xticklabels(labels)
    ax.set_ylim(0, max(values + [1]) * 1.25)
    ax.yaxis.get_major_locator().set_params(integer=True)
    _style_axes(ax, "Invalid records", None)
    average = summary["avg_attempts_corrected"]
    _title(ax, title, "Records by the attempt that fixed them" + (f"; average {average:g} attempts per fix" if average else ""))
    return _save(fig, path)


def write_rates_table(df, path):
    """Table view of every plotted rate, for readers who cannot rely on the colors."""
    rows = []
    for field in ("fit_level", "job_template", "resume_writing_style", "role_type", "resume_seniority"):
        for name, sub in df.groupby(field):
            for flag in FLAGS:
                rows.append({"group_field": field, "group": name, "n": len(sub), "flag": flag, "failure_rate_percent": round(100 * sub[flag].mean(), 2)})
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


# --- Entry points -----------------------------------------------------------


def visualize_run(labels_path, output_dir=OUTPUT_DIR, viz_dir=VISUALIZATIONS_DIR):
    labels_path = Path(labels_path)
    timestamp = LABELS_PATTERN.fullmatch(labels_path.name).group(1)
    df = load_labels(labels_path)
    correction_report = load_correction_report(timestamp, output_dir)
    schema_report = load_schema_report(timestamp, correction_report, output_dir)
    target_dir = Path(viz_dir) / timestamp
    target_dir.mkdir(parents=True, exist_ok=True)
    _style()
    paths = [
        chart_correlation(df, target_dir / "1_failure_mode_correlation.png"),
        chart_by_fit_level(df, target_dir / "2_failure_rates_by_fit_level.png"),
        chart_by_template(df, target_dir / "3_failure_rates_by_job_template.png"),
        chart_by_writing_style(df, target_dir / "3b_failure_rates_by_writing_style.png"),
        chart_niche_vs_standard(df, target_dir / "4_niche_vs_standard_roles.png"),
        chart_schema_heatmap(schema_report, target_dir / "5_schema_validation_heatmap.png"),
        chart_hallucination_by_seniority(df, target_dir / "6_hallucination_by_seniority.png"),
        chart_jaccard_by_fit_level(df, target_dir / "7_skills_overlap_by_fit_level.png"),
        chart_correction_success(correction_report, target_dir / "8_correction_success_by_category.png"),
        chart_correction_attempts(correction_report, target_dir / "9_correction_attempts.png"),
    ]
    table_path = write_rates_table(df, target_dir / "failure_rates_table.csv")
    print(f"Wrote {len(paths)} charts and a rates table to {target_dir}")
    return {"directory": target_dir, "charts": paths, "table": table_path}


def visualize_latest_run(output_dir=OUTPUT_DIR, viz_dir=VISUALIZATIONS_DIR):
    _, labels_path = discover_latest_labels(output_dir)
    return visualize_run(labels_path, output_dir, viz_dir)
