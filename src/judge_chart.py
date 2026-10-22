"""Bar chart of the LLM judge summary in output/judge_output.json, for the README.

python3 -m src.judge_chart [judge_output.json] [out.png]   # default: output/judge_output.json -> docs/judge_summary.png
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from src.config import OUTPUT_DIR, ROOT
from src.step4_visualization import FIT_LEVELS, INK_SECONDARY, MUTED, ORDINAL_BLUES, SERIES, SURFACE, _save, _style, _style_axes, _title

JUDGE_COLOR, RULES_COLOR = SERIES[0], SERIES[1]
CHECKS = (
    ("Hallucination", "has_hallucinations", "rule_hallucination_flag"),
    ("Awkward language", "has_awkward_language", "rule_awkward_language_flag"),
    ("Any red flag", "red_flags", None),
)


def _percent(results, key):
    return 100 * sum(bool(r[key]) for r in results) / len(results)


def _bar_label(ax, x, value, text):
    ax.text(x, value + 1.5, text, ha="center", va="bottom", fontsize=9, color=INK_SECONDARY)


def chart_judge(judge, path):
    """Left: share of pairs flagged by the judge vs the step 3 rules. Right: mean judge quality score per fit level."""
    _style()
    results = judge["results"]
    summary = judge["summary"]
    fig, (left, right) = plt.subplots(1, 2, figsize=(13, 5.5), gridspec_kw={"width_ratios": [1, 1.2], "wspace": 0.3})

    width = 0.38
    for i, (label, judge_key, rule_key) in enumerate(CHECKS):
        judged = _percent(results, judge_key)
        left.bar(i - width / 2, judged, width=width, color=JUDGE_COLOR, edgecolor=SURFACE, linewidth=1.5)
        _bar_label(left, i - width / 2, judged, f"{judged:.0f}%")
        if rule_key is None:
            _bar_label(left, i + width / 2, 0, "no rule")
            continue
        ruled = _percent(results, rule_key)
        left.bar(i + width / 2, ruled, width=width, color=RULES_COLOR, edgecolor=SURFACE, linewidth=1.5)
        _bar_label(left, i + width / 2, ruled, f"{ruled:.0f}%")
    left.set_xticks(range(len(CHECKS)), [label for label, _, _ in CHECKS])
    left.set_ylim(0, 115)
    left.set_yticks(range(0, 101, 20), [f"{v}%" for v in range(0, 101, 20)])
    _style_axes(left, "Pairs flagged (%)")
    left.legend(
        handles=[Patch(color=JUDGE_COLOR, label=f"LLM judge ({judge['model']})"), Patch(color=RULES_COLOR, label="Step 3 rules")],
        loc="upper left",
        frameon=False,
        fontsize=9,
    )
    _title(left, "LLM judge vs step 3 rule flags", f"Share of the {summary['judged']} judged pairs flagged by each check")

    by_fit = summary["by_fit_level"]
    levels = [level for level in FIT_LEVELS if level in by_fit]
    scores = [by_fit[level]["mean_quality_score"] for level in levels]
    right.bar(range(len(levels)), scores, width=0.6, color=ORDINAL_BLUES[: len(levels)], edgecolor=SURFACE, linewidth=1.5)
    for i, score in enumerate(scores):
        right.text(i, score + 0.015, f"{score:.2f}", ha="center", va="bottom", fontsize=9, color=INK_SECONDARY)
    right.axhline(summary["mean_quality_score"], color=MUTED, linestyle="--", linewidth=1.2, label=f"All pairs: {summary['mean_quality_score']:.2f}")
    right.legend(loc="upper right", frameon=False, fontsize=9)
    right.set_xticks(
        range(len(levels)), [f"{level.replace('_', ' ')}\n(n={by_fit[level]['count']})" for level in levels]
    )
    right.set_ylim(0, 1)
    _style_axes(right, "Mean overall_quality_score (0-1)", "Intended fit level of the resume")
    _title(right, "Judge quality score by fit level", "Mean score per intended fit level")

    return _save(fig, path)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    source = Path(argv[0]) if argv else OUTPUT_DIR / "judge_output.json"
    target = Path(argv[1]) if len(argv) > 1 else ROOT / "docs" / "judge_summary.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    print(chart_judge(json.loads(source.read_text()), target))


if __name__ == "__main__":
    main()
