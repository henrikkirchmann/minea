"""Generate descriptive vector charts from the frozen evaluation inputs."""

import csv
import gzip
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
import tempfile


def generate(root, output, rules):
    # Keep rendering caches outside the artifact. No TeX or external fonts needed.
    os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "minea-reviewer-mpl"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    source = root / "inputs/reference/full"
    with (source / "ground_truth.csv").open() as stream:
        gt = list(csv.DictReader(stream))
    with gzip.open(source / "uncertain_log.csv.gz", "rt") as stream:
        uncertain = list(csv.DictReader(stream))
    assert [r["event_id"] for r in gt] == [r["event_id"] for r in uncertain]
    blue, orange, gray = "#176b91", "#d27b2c", "#a3adb6"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#cad3da", "text.color": "#203341",
                         "axes.labelcolor": "#203341", "axes.titleweight": "bold",
                         "svg.fonttype": "none", "svg.hashsalt": "minea-reviewer-v1",
                         "savefig.facecolor": "white"})

    def save(fig, name):
        fig.savefig(output / name, format="svg", bbox_inches="tight",
                    metadata={"Date": None, "Creator": "MINEA reviewer report / Matplotlib"})
        plt.close(fig)

    by_case = Counter(r["case_id"] for r in gt)
    vectors = [json.loads(r["scores"]) for r in uncertain]
    ranks = Counter(sorted(v, key=lambda a: (-v[a], a)).index(g["activity"]) + 1
                    for g, v in zip(gt, vectors))
    masses = [sum(float(r[key]) for r in uncertain) / len(uncertain)
              for key in ("remaining_score_mass", "removed_na_score", "discarded_non_na_score_mass")]
    fig, axs = plt.subplots(2, 2, figsize=(10, 7), constrained_layout=True)
    lengths = list(by_case.values())
    axs[0, 0].hist(lengths, bins=range(min(lengths), max(lengths) + 2),
                   color=blue, edgecolor="white", align="left")
    axs[0, 0].set(title="A · GT observations per case", xlabel="Observations", ylabel="Cases")
    durations = [int(r["duration_frames"]) / 25 for r in gt]
    axs[0, 1].hist(durations, bins=30, color=blue, edgecolor="white")
    axs[0, 1].set(title="B · GT segment durations", xlabel="Seconds (25 frames/s)", ylabel="Observations")
    axs[1, 0].bar([1, 2, 3], [ranks[i] for i in (1, 2, 3)], color=blue, width=.65)
    for i in (1, 2, 3):
        axs[1, 0].text(i, ranks[i] + 20, f"{ranks[i]:,}", ha="center")
    axs[1, 0].set(title="C · Where the GT label ranks", xlabel="Rank within final 3 (1 = highest original score)",
                   ylabel="Observations", xticks=[1, 2, 3], ylim=(0, max(ranks.values()) * 1.17))
    axs[1, 0].text(.98, .86, "After inserting GT when missing.\n353 insertions are included at rank 3.",
                   transform=axs[1, 0].transAxes, ha="right", va="top", fontsize=9)
    bottom = 0
    for value, label, color in zip(masses, ("Final 3 candidates (sum)", "Removed NA score", "Other discarded non-NA scores (sum)"),
                                   (blue, gray, orange)):
        axs[1, 1].barh([0], [value], left=bottom, color=color, height=.35, label=f"{label}: {value:.3f}")
        bottom += value
    axs[1, 1].set(title="D · How original scores are split", xlabel="Mean sum of original scores (not renormalized)",
                   xlim=(0, 1), ylim=(-.5, .6), yticks=[])
    axs[1, 1].text(.5, .94, "Add scores within each group per observation,\nthen average over all 1,856 observations.\nThe three parts total approximately 1.",
                   transform=axs[1, 1].transAxes, ha="center", va="top", fontsize=9)
    axs[1, 1].legend(loc="upper left", bbox_to_anchor=(0, -.22), frameon=False, fontsize=9)
    save(fig, "log_profiles.svg")

    gt_counts = Counter(r["activity"] for r in gt)
    candidate_counts = Counter(label for v in vectors for label in v)
    top_counts = Counter(r["top_activity"] for r in uncertain)
    labels = sorted(candidate_counts, key=lambda a: (-gt_counts[a], a))
    y = np.arange(len(labels))
    fig, ax = plt.subplots(figsize=(10, 10.2), constrained_layout=True)
    ax.barh(y - .25, [gt_counts[a] for a in labels], height=.23, color=blue, label="GT observations (total 1,856)")
    ax.barh(y, [candidate_counts[a] for a in labels], height=.23, color=gray, label="Candidate occurrences (total 5,568)")
    ax.barh(y + .25, [top_counts[a] for a in labels], height=.23, color=orange, label="Highest-scoring retained label (total 1,856)")
    ax.set(yticks=y, yticklabels=labels, xlabel="Occurrences", title="Activity frequencies · Different denominators")
    ax.tick_params(axis="y", labelsize=9)
    ax.invert_yaxis()
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.grid(axis="x", alpha=.12)
    ax.set_axisbelow(True)
    save(fig, "activity_profile.svg")

    prerequisites = sorted(rules["prerequisites"], key=lambda r: r["rank"])
    fig, ax = plt.subplots(figsize=(10, 6), constrained_layout=True)
    x = np.arange(len(prerequisites))
    ax.bar(x, [r["support_cases"] for r in prerequisites],
           color=[blue if r["selected"] else gray for r in prerequisites])
    ax.set(xticks=x, xticklabels=[r["id"] for r in prerequisites],
           ylabel="Cases containing the trigger (out of 116)", xlabel="Accepted prerequisites, ordered by the selection ranking",
           title="A rule can hold in every trace and be activated in few cases", ylim=(0, 116))
    ax.tick_params(axis="x", labelrotation=90, labelsize=8)
    ax.axhline(116, color=orange, linewidth=1, linestyle=":")
    ax.text(.99, .94, "Blue: 3 selected prerequisites\nGray: 38 other accepted prerequisites\nNo prerequisite is activated in all 116 cases.",
            transform=ax.transAxes, ha="right", va="top", fontsize=10)
    ax.grid(axis="y", alpha=.12)
    ax.set_axisbelow(True)
    save(fig, "rule_support.svg")
    return ["log_profiles.svg", "activity_profile.svg", "rule_support.svg"]
