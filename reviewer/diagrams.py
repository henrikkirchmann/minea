#!/usr/bin/env python3
"""Generate deterministic reviewer SVGs from the saved preparation evidence.

Standard library only. This reads committed inputs, checks the figure facts,
and writes SVG diagrams; it does not train a model, aggregate video frames,
change observations, mine a different rule set, or run matching.

    python -m reviewer.diagrams --output docs/reviewer/assets
"""

import argparse
import csv
import gzip
from html import escape
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLUE = "#155E9A"
TEAL = "#146C61"
ORANGE = "#A85317"
INK = "#172B42"
MUTED = "#526579"
BORDER = "#D7E1EB"


class SVG:
    """Small, explicit SVG writer: no external assets, fonts, scripts or filters."""

    def __init__(self, title, description, height):
        self.parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" '
            f'viewBox="0 0 1200 {height}" role="img" aria-labelledby="title description">',
            f'<title id="title">{escape(title)}</title>',
            f'<desc id="description">{escape(description)}</desc>',
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="#8799AC"/></marker></defs>',
            f'<rect width="1200" height="{height}" fill="#F7F9FC"/>',
            '<g font-family="Arial, Helvetica, sans-serif">',
        ]

    def rect(self, x, y, w, h, fill="white", stroke=BORDER, radius=16):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                          f'rx="{radius}" fill="{fill}" stroke="{stroke}"/>')

    def text(self, x, y, text, size=20, color=INK, weight=400, anchor="start"):
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
                          f'font-weight="{weight}" text-anchor="{anchor}">{escape(str(text))}</text>')

    def lines(self, x, y, lines, size=20, color=INK, leading=29, weight=400):
        for i, line in enumerate(lines):
            self.text(x, y + i * leading, line, size, color, weight)

    def arrow(self, points, head=True):
        path = " ".join(("M" if i == 0 else "L") + f" {x} {y}" for i, (x, y) in enumerate(points))
        marker = ' marker-end="url(#arrow)"' if head else ''
        self.parts.append(f'<path d="{path}" fill="none" stroke="#8799AC" '
                          f'stroke-width="2.2" stroke-linejoin="round"{marker}/>')

    def card(self, x, y, w, h, label, title, color=BLUE, title_size=25):
        self.rect(x, y, w, h)
        self.rect(x + 20, y + 22, 5, 25, color, color, 2)
        self.text(x + 38, y + 41, label.upper(), 14, color, 700)
        self.text(x + 24, y + 84, title, title_size, INK, 700)

    def finish(self):
        return "\n".join([*self.parts, '</g>', '</svg>', ''])


def _facts():
    """Refuse to silently draw stale diagram claims for another input profile."""
    def read(name):
        return json.loads((ROOT / name).read_text())
    summary = read("inputs/reference/summary.json")
    audit = read("inputs/reference/full/constraint_audit.json")
    source = read("inputs/reference/source_audit.json")
    policy = read("inputs/reference/full/candidate_policy.json")
    selection = read("inputs/provenance/selection_protocol.json")
    original = json.loads(gzip.decompress((ROOT / "inputs/provenance/original_instance.json.gz").read_bytes()))
    if (len(original["prerequisites"]), len(original["occurrence_bounds"]),
        len(original["cases"]), len(original["candidates"]), len(original["sources"])) != (41, 32, 116, 5568, 2):
        raise ValueError("Diagram full-model calibration profile changed")
    if selection["seconds_per_method"] != 300 or selection["components"] != 116:
        raise ValueError("Diagram calibration limit or component count changed")
    constraints = {r["id"]: r for r in read("inputs/reference/full/constraints.json")["constraints"]}
    with (ROOT / "inputs/reference/model_selection.csv").open(newline="") as stream:
        models = list(csv.DictReader(stream))
    best = max(models, key=lambda r: float(r["accuracy_non_na_frames"]))
    expected = {"case_count": 116, "event_count": 1856, "activity_count": 32,
                "candidate_count": 5568, "top_k": 3, "gt_replacement_count": 353,
                "removed_na_segments": 817, "candidate_policy": "top-k-gt"}
    for key, value in expected.items():
        if summary[key] != value:
            raise ValueError(f"Diagram profile changed: {key}")
    if len(source["original_case_ids"]) != 117 or source["explicitly_excluded_empty_cases"] != ["38"]:
        raise ValueError("Diagram source-case accounting changed")
    if summary["accuracy_scope"] != "non_na" or summary["model_override"] is not None:
        raise ValueError("Diagram model selection policy changed")
    if best["model_id"] != summary["selected_model"] or "__p3d__" not in best["model_id"]:
        raise ValueError("P3D is not the selected best non-NA model")
    if (int(best["correct_non_na_frames"]), int(best["non_na_frames"])) != (183638, 276058):
        raise ValueError("Diagram accuracy counts changed")
    if policy["renormalized"] or not policy["gt_label_insertion"]:
        raise ValueError("Diagram candidate-score policy changed")
    meta = audit["metadata"]
    if (meta["prerequisite_pair_count"], len(audit["accepted_prerequisites"]),
        len(audit["occurrence_bounds"]), meta["accepted_active_in_all_cases_count"]) != (992, 41, 32, 0):
        raise ValueError("Diagram mining counts changed")
    if any(b["minimum"] != 0 for b in audit["occurrence_bounds"]):
        raise ValueError("Not every empirical lower bound is zero")
    if any(r["violation_count"] != 0 or not r["nonvacuous"] for r in audit["accepted_prerequisites"]):
        raise ValueError("Accepted prerequisite semantics changed")
    if selection["selection"] != {"prerequisites": ["pre_019", "pre_036", "pre_023"],
                                  "occurrence_bounds": ["occ_031", "occ_021"]}:
        raise ValueError("Diagram selected templates changed")
    prerequisites = [("pre_019", "pick up leg", "attach shelf to table"),
                     ("pre_036", "spin leg", "attach shelf to table"),
                     ("pre_023", "pick up leg", "pick up shelf")]
    for key, predecessor, trigger in prerequisites:
        row = constraints[key]
        if row["predecessor_activities"] != [predecessor] or row["trigger_activity"] != trigger:
            raise ValueError(f"Diagram prerequisite changed: {key}")
    for key, activity, upper in [("occ_031", "spin leg", 8), ("occ_021", "pick up leg", 5)]:
        row = constraints[key]
        if (row["activities"], row["lower"], row["upper"]) != ([activity], 0, upper):
            raise ValueError(f"Diagram occurrence bound changed: {key}")
    return {"summary": summary, "best": best, "constraints": constraints}


def _data_pipeline(facts):
    s = SVG("Data preparation: from annotated assembly video to aligned logs",
            "The supplied model-score exports cover 117 IKEA ASM test recordings, chosen because "
            "the IKEA ASM authors provide classifier scores for the test recordings. This is not the full "
            "dataset or 117 distinct people. GT means ground truth, the reference activity labels. "
            "NA means No Annotation: frames not covered by an annotated activity, not necessarily "
            "an absence of movement. P3D is an existing video classifier evaluated by the IKEA ASM "
            "authors. The earlier IKEA_ASM_UncertainEventLogs repository converts released scores "
            "into uncertain-log observations: each maximal consecutive run of a single GT label forms one "
            "observation, with segment bounds and GT label. Each activity score is independently averaged "
            "across the frames of that run. An explicitly illustrative five-frame example shows GT A "
            "on frames 10 to 12 with mean scores A 0.6 and B 0.4, and GT B on frames 13 to 14 with "
            "mean scores A 0.3 and B 0.7. This artifact uses half-open intervals [10,13) and [13,15); "
            "the upstream CSV stores inclusive end frames. This evaluation reuses the GT-aligned arithmetic "
            "mean scores, without new training, inference or frame aggregation. It removes GT-NA "
            "segments and the NA candidate option, focusing the task on activity matching. Empty "
            "case 38 is excluded separately. Both logs contain 116 cases and 1856 observations. "
            "The uncertain log retains three original non-NA scores per observation, replacing "
            "the third candidate with GT only if GT is absent from the top three: 353 replacements "
            "and 5568 candidates, without renormalization.", 2006)
    s.text(40, 54, "From assembly video to two aligned logs", 34, INK, 700)
    s.text(40, 91, "We use the IKEA ASM test set because its authors provide classifier scores for those recordings.", 20, MUTED)

    s.rect(40, 120, 1120, 121, "#EAF0F8", "#D3E0EF", 12)
    s.text(64, 155, "GT = ground truth: reference activity labels supplied with the recordings.", 21, BLUE, 700)
    s.text(64, 187, "NA = No Annotation: frames not covered by an annotated activity interval.", 21, INK, 700)
    s.text(64, 219, "NA does not necessarily mean that the person is inactive or not moving.", 20, MUTED)

    s.card(40, 270, 350, 330, "Upstream test recordings", "IKEA ASM TEST set", BLUE)
    s.lines(64, 391, ["117 test-recording cases.", "RGB videos of furniture assembly.", "We use this set because its", "classifier scores are provided", "by the IKEA ASM authors."], 18, MUTED, 29)
    s.text(64, 568, "Recordings, not individual people.", 18, BLUE, 700)

    s.card(425, 270, 340, 330, "Model selection", "Choose P3D", BLUE)
    s.lines(449, 391, ["An existing video classifier", "evaluated by IKEA ASM authors."], 18, MUTED, 29)
    s.text(449, 475, f'{float(facts["best"]["accuracy_non_na_frames"]):.2%}', 35, BLUE, 700)
    s.lines(449, 512, ["183,638 / 276,058 non-NA frames", "Best among supplied outputs", "on non-NA frame accuracy."], 18, MUTED, 27)

    s.card(800, 270, 360, 330, "Our earlier log repository", "Reuse segment means", BLUE)
    s.lines(824, 391, ["Converts released classifier scores", "into uncertain-log observations.", "This evaluation reuses its supplied", "GT-aligned segment means."], 18, MUTED, 29)
    s.text(824, 531, "Mean = average of frame scores.", 18, BLUE, 700)
    s.text(824, 568, "No new model or frame processing.", 18, BLUE, 700)
    s.arrow([(395, 440), (420, 440)])
    s.arrow([(770, 440), (795, 440)])
    s.arrow([(980, 608), (980, 635), (600, 635), (600, 662)])

    # This small example is illustrative, not an observation from the dataset.
    # Exact arithmetic keeps its displayed means consistent with its frame scores.
    from fractions import Fraction
    frames = [(10, "A", "0.6", "0.4"), (11, "A", "0.9", "0.1"),
              (12, "A", "0.3", "0.7"), (13, "B", "0.2", "0.8"),
              (14, "B", "0.4", "0.6")]
    means = [tuple(sum((Fraction(row[col]) for row in group), Fraction()) / len(group)
                   for col in (2, 3)) for group in (frames[:3], frames[3:])]
    if means != [(Fraction(3, 5), Fraction(2, 5)), (Fraction(3, 10), Fraction(7, 10))]:
        raise ValueError("Illustrative frame-score means changed")

    s.card(40, 670, 1120, 560, "Inside the earlier log repository", "One GT run → one observation; average each activity score", BLUE, 26)
    s.text(64, 786, "Illustrative two-activity example, not real IKEA data: every frame has a GT label and model scores.", 19, MUTED)
    for x, label in ((112, "Frame"), (213, "GT"), (316, "Score A"), (436, "Score B")):
        s.text(x, 831, label, 19, MUTED, 700, "middle")
    s.rect(64, 844, 430, 120, "#E8F0FA", "#ABC4DF", 9)
    s.rect(64, 975, 430, 82, "#FFF1E6", "#E6BF9F", 9)
    for row, y in zip(frames, (871, 909, 947, 1004, 1042)):
        for x, value in zip((112, 213, 316, 436), row):
            s.text(x, y, value, 21, BLUE if row[1] == "A" else ORANGE, 700 if x == 213 else 400, "middle")
    s.text(585, 889, "mean per activity", 17, BLUE, anchor="middle")
    s.arrow([(505, 906), (677, 906)])
    s.text(585, 1005, "mean per activity", 17, ORANGE, anchor="middle")
    s.arrow([(505, 1022), (677, 1022)])

    s.rect(691, 844, 443, 120, "#E8F0FA", "#ABC4DF", 9)
    s.text(711, 875, "Observation 1 · GT = A", 23, BLUE, 700)
    s.text(711, 912, "[10, 13): start 10, end 13 exclusive", 20, INK)
    s.text(711, 946, f"Mean scores: A = {float(means[0][0]):.1f}; B = {float(means[0][1]):.1f}", 21, BLUE, 700)
    s.rect(691, 976, 443, 110, "#FFF1E6", "#E6BF9F", 9)
    s.text(711, 1007, "Observation 2 · GT = B", 23, ORANGE, 700)
    s.text(711, 1040, "[13, 15): start 13, end 15 exclusive", 20, INK)
    s.text(711, 1072, f"Mean scores: A = {float(means[1][0]):.1f}; B = {float(means[1][1]):.1f}", 21, ORANGE, 700)

    s.text(64, 1100, "Example: mean(A) for observation 1 = (0.6 + 0.9 + 0.3) / 3 = 0.6; mean(B) = 0.4.", 19, MUTED)
    s.text(64, 1138, "Within each case, a maximal consecutive same-GT run forms one observation (event). GT changes start a new run.", 19, INK)
    s.text(64, 1173, "Bounds here are half-open [start, end); the upstream CSV uses inclusive end frames.", 19, MUTED)
    s.text(64, 1208, "Matching uses the precomputed export; this evaluation does not redo the frame averaging.", 20, BLUE, 700)
    s.arrow([(600, 1238), (600, 1258)])

    # Make room for the explicit frame-to-observation explanation above.
    s.parts.append('<g transform="translate(0 596)">')
    s.card(40, 670, 1120, 170, "Cohort and segment filtering", "Remove GT-NA segments and the NA candidate option", TEAL)
    s.text(64, 784, "Focus on matching annotated activities; unannotated intervals are outside this task.", 21, MUTED)
    s.text(64, 817, "817 NA segments removed within the 116 retained cases; empty case 38 is excluded separately.", 20, MUTED)
    s.arrow([(600, 847), (600, 870), (310, 870), (310, 897)])
    s.arrow([(600, 870), (890, 870), (890, 897)])
    s.rect(413, 856, 374, 34, "#F7F9FC", "#F7F9FC", 7)
    s.text(600, 879, "Aligned case IDs and segment boundaries", 17, MUTED, anchor="middle")

    s.card(40, 905, 540, 305, "Certain representation", "Ground-truth log", TEAL)
    s.lines(64, 1026, ["One annotated activity per observation.", "116 cases and 1,856 observations.", "The GT trace supplies rule-mining input."], 21, MUTED, 34)
    s.rect(64, 1123, 490, 58, "#ECF5F2", "#CDE5DD", 10)
    s.text(84, 1159, "Keep the original segment boundaries.", 19, TEAL, 700)

    s.card(620, 905, 540, 305, "Uncertain representation", "Three candidates per observation", ORANGE, 23)
    s.lines(644, 1026, ["1. Rank non-NA activities by original score.", "2. Keep the three highest-scoring labels.", "3. If GT is absent, replace only the third", "    label with GT and its original score."], 19, MUTED, 29)
    s.rect(644, 1150, 490, 39, "#FFF2E8", "#F0D9C6", 10)
    s.text(661, 1176, "353 replacements · no renormalization", 19, ORANGE, 700)

    s.rect(40, 1234, 1120, 66, "#EAF0F8", "#D3E0EF", 12)
    s.text(600, 1263, "116 cases  ·  1,856 observations  ·  5,568 candidate variables", 23, BLUE, 700, "middle")
    s.text(600, 1287, "GT assistance makes this a controlled experiment, not held-out recognition evaluation.", 17, MUTED, anchor="middle")
    s.text(40, 1336, "Data and classifier context: Ben-Shabat et al. (2021), IKEA ASM.", 18, MUTED)
    s.text(40, 1365, "Log conversion and supplied segment means: IKEA_ASM_UncertainEventLogs (pinned earlier repository).", 18, MUTED)
    s.parts.append("</g>")
    return s.finish()


def _rule_mining(facts):
    s = SVG("Rule mining: 992 prerequisite pairs and 32 occurrence bounds to five selected templates",
            "All rules are mined from the same 116 retained ground-truth cases and 32 activities. "
            "Every ordered pair of distinct activities is tested. A prerequisite holds when every "
            "trigger has a same-case predecessor ending no later than its start; the predecessor need "
            "not be immediately preceding. A case without the trigger satisfies it vacuously. "
            "Forty-one prerequisites have no violations and at least one trigger overall; none is "
            "active in all 116 cases. Thirty-two empirical minimum/maximum occurrence bounds are "
            "computed; all lower bounds are zero. Rules are ranked separately by support cases, "
            "then support events, then ID. The fixed selected profile has three prerequisites "
            "and two count bounds. The full 41-plus-32 profile reached the 300-second distributed "
            "matching limit at two sources and 116 components. The reduced profile retains all cases "
            "and candidates and is fixed throughout the sweep.", 1485)
    s.text(40, 54, "How five fixed intra-case templates were selected", 32, INK, 700)
    s.text(40, 91, "GT = ground truth (reference activity labels). Mine these same cases, then rank each rule family.", 20, MUTED)
    s.rect(40, 121, 1120, 67, "#EAF0F8", "#D3E0EF", 12)
    s.text(600, 163, "116 GT cases  ·  1,856 original non-NA segments  ·  32 activities", 23, BLUE, 700, "middle")
    s.arrow([(600, 194), (600, 210), (310, 210), (310, 236)])
    s.arrow([(600, 210), (890, 210), (890, 236)])

    s.card(40, 244, 540, 374, "Family 1 · Prerequisites", "32 × 31 = 992 ordered pairs", BLUE, 25)
    s.lines(64, 364, ["Test each distinct predecessor / trigger pair.", "For every trigger, require a same-case", "predecessor that has already ended."], 20, MUTED, 29)
    # Schematic intervals share a boundary: equality is explicitly permitted.
    s.rect(69, 453, 220, 47, "#E8F0FA", "#ABC4DF", 7)
    s.rect(289, 453, 220, 47, "#FFF1E6", "#E6BF9F", 7)
    s.text(179, 483, "predecessor", 20, BLUE, 700, "middle")
    s.text(399, 483, "trigger", 20, ORANGE, 700, "middle")
    s.arrow([(70, 515), (530, 515)])
    s.text(288, 544, "end ≤ start, in the same case", 20, INK, 700, "middle")
    s.lines(64, 578, ["Earlier activity need not be immediately prior.", "Equality is allowed (as drawn above)."], 18, MUTED, 25)

    s.card(620, 244, 540, 374, "Family 2 · Occurrence bounds", "32 empirical min–max bounds", TEAL, 24)
    s.lines(644, 364, ["Count each activity’s segments in every case.", "Include zero counts when the activity is absent.", "Take the minimum and maximum across cases."], 19, MUTED, 30)
    s.rect(644, 461, 490, 84, "#ECF5F2", "#CDE5DD", 10)
    s.text(665, 495, "All 32 lower bounds are zero.", 23, TEAL, 700)
    s.text(665, 526, "No activity is required in every case.", 19, TEAL)
    s.lines(644, 578, ["Counts refer to original non-NA GT segments,", "not physical objects or resource capacities."], 18, MUTED, 25)

    s.rect(40, 643, 540, 123, "#EAF0F8", "#D3E0EF", 12)
    s.text(64, 679, "41 prerequisites accepted", 25, BLUE, 700)
    s.lines(64, 714, ["At least one trigger overall; zero GT violations.", "No trigger in a case ⇒ the rule holds vacuously."], 19, MUTED, 28)
    s.rect(620, 643, 540, 123, "#ECF5F2", "#CDE5DD", 12)
    s.text(644, 679, "32 occurrence templates", 25, TEAL, 700)
    s.lines(644, 714, ["These bounds hold for the mined GT cohort.", "They are descriptive limits, not physical laws."], 19, MUTED, 28)
    s.text(40, 797, "Holding for all cases is not activation in all cases: none of the 41 prerequisites activates in every case.", 19, MUTED)

    s.arrow([(310, 814), (310, 832), (600, 832), (600, 851)])
    s.arrow([(890, 814), (890, 832), (600, 832)], head=False)
    s.rect(40, 859, 1120, 142, "#FFF2E8", "#F0D9C6", 14)
    s.text(64, 898, "Why reduce the rule set? The initial full model reached its matching limit.", 25, ORANGE, 700)
    s.text(64, 934, "Distributed matching with 41 prerequisites + 32 bounds reached 300 s (2 sources; 116 components).", 20, INK)
    s.text(64, 968, "Retain all 116 cases and 5,568 candidates; use a fixed 3 + 2 subset for the sweep.", 21, MUTED)
    s.arrow([(600, 1008), (600, 1030)])

    s.rect(40, 1038, 1120, 112, "white", BORDER, 14)
    s.text(64, 1076, "Rank separately within each family", 25, INK, 700)
    s.text(64, 1109, "More support cases → more support events → ascending template ID", 21, BLUE, 700)
    s.text(64, 1134, "Prerequisite support counts triggers; bound support counts positive occurrences.", 19, MUTED)
    s.arrow([(600, 1157), (600, 1178)])

    s.card(40, 1187, 710, 219, "Selected · three prerequisites", "Every trigger needs its earlier activity", BLUE, 23)
    for i, key in enumerate(("pre_019", "pre_036", "pre_023")):
        rule = facts["constraints"][key]
        text = f'{key}:  {rule["predecessor_activities"][0]} → {rule["trigger_activity"]}'
        s.text(64, 1309 + 32 * i, text, 20, INK)
    s.card(780, 1187, 380, 219, "Selected · two bounds", "Per-case segment counts", TEAL, 23)
    s.text(804, 1309, "occ_031: spin leg  0…8", 21, INK)
    s.text(804, 1341, "occ_021: pick up leg  0…5", 21, INK)
    s.text(804, 1376, "Zero lower rows are redundant.", 17, MUTED)
    s.text(600, 1443, "These five templates stay fixed. This is an exploratory reduced model, not held-out validation.", 20, MUTED, anchor="middle")
    s.text(600, 1472, "Evidence: recorded full-model calibration and the frozen selection protocol.", 17, MUTED, anchor="middle")
    return s.finish()


def generate(output):
    """Write the two diagrams into ``output`` and return their absolute paths."""
    output = Path(output).resolve()
    facts = _facts()
    output.mkdir(parents=True, exist_ok=True)
    documents = {"data_pipeline.svg": _data_pipeline(facts), "rule_mining.svg": _rule_mining(facts)}
    paths = []
    for name, text in documents.items():
        path = output / name
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/reviewer/assets")
    for path in generate(parser.parse_args().output):
        print(path)


if __name__ == "__main__":
    main()
