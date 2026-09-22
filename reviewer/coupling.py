"""Draw the checked first synthetic exclusion for the coupling guide.

Run from the project root: python -m reviewer.coupling
Only reads frozen inputs and writes docs/coupling/assets/endpoint_choices.svg.
"""

import gzip
import json
from pathlib import Path

from reviewer.diagrams import SVG, BLUE, INK, MUTED
from minea_ikea.instances import semantic_violations


ROOT = Path(__file__).resolve().parents[1]


def checked_example():
    def read(name):
        return json.loads(gzip.decompress((ROOT / name).read_bytes()))
    plan = read("inputs/provenance/plan_seed0.json.gz")
    original = read("inputs/provenance/original_instance.json.gz")
    instance = read("results/benchmark_sweep/preparation/instances/seed0_K8_C1.json.gz")
    row = plan["bridges"][0]
    candidates = {candidate["id"]: candidate for candidate in original["candidates"]}
    g, f = row["gt_candidate_id"], row["replacement_candidate_id"]
    old = row["witness"]["removed_candidate_id"]
    expected = [(g, "v004874", "86", "spin leg"),
                (old, "v005002", "9", "pick up leg"),
                (f, "v005001", "9", "align leg screw with table thread")]
    for actual_id, expected_id, case, label in expected:
        candidate = candidates[actual_id]
        if (actual_id, candidate["case_id"], candidate["activity"]) != (expected_id, case, label):
            raise ValueError("The illustration's saved example changed")
    if row["id"] != "bridge:000000" or row["terms"] != {g: 1, f: 1} or row["upper"] != 1:
        raise ValueError("The illustrated exclusion changed")
    gt = set(original["gt_selected"])
    changed = gt - {old} | {f}
    if semantic_violations(original, gt) or semantic_violations(original, changed):
        raise ValueError("The example must satisfy every original constraint")
    if semantic_violations(instance, gt):
        raise ValueError("GT must satisfy every added exclusion")
    violations = semantic_violations(instance, changed)
    if len(violations) != 1 or violations[0]["row_id"] != row["id"]:
        raise ValueError("The changed matching must violate exactly the illustrated row")
    endpoints = [bridge[key] for bridge in plan["bridges"]
                 for key in ("a_observation_id", "b_observation_id")]
    if len(endpoints) != len(set(endpoints)):
        raise ValueError("Each observation must be used in at most one exclusion")
    return row


def diagram(row):
    s = SVG("An inter-case constraint restricts activity interpretations",
            "Actual saved exclusion bridge:000000. Each candidate is listed once with a fixed GT or "
            "non-GT label. The two columns represent complete selections for the same observations, "
            "not different logs. Checked boxes mean selected; empty boxes mean not selected. In the "
            "GT selection, Case 86's spin leg and Case 9's pick up leg are selected. In the second "
            "selection, spin leg remains selected, pick up leg is deselected, and Case 9's non-GT "
            "alternative align leg screw with table thread is selected instead. All other observations "
            "keep their GT candidate. The exclusion allows at most one of spin leg (g) and the "
            "alternative (f). It allows GT with value 1 and excludes the changed selection with value 2. "
            "Both selections satisfy all original constraints and every other added exclusion. "
            "Only relevant candidates are shown; each observation has three candidates.", 1088)
    s.text(40, 53, "An inter-case constraint restricts activity interpretations", 32, INK, 700)
    s.text(40, 89, "The same observations: compare GT with one different activity interpretation in case 9.", 22, MUTED)

    s.rect(40, 112, 1120, 109, "white", "#D7E1EB", 12)
    s.text(64, 148, "Candidate = a proposed activity interpretation", 22, INK, 700)
    s.text(64, 179, "The GT candidate proposes the annotated activity.", 19, MUTED)
    s.text(64, 205, "A non-GT candidate proposes another activity.", 19, MUTED)
    s.text(627, 148, "Selection = which candidates are accepted", 22, INK, 700)
    s.text(627, 179, "A checked box selects that candidate (x = 1).", 19, MUTED)
    s.text(627, 205, "An empty box leaves it unselected (x = 0).", 19, MUTED)

    s.rect(40, 242, 1120, 77, "#EAF0F8", "#C8D9EB", 12)
    s.text(64, 272, "ADDED ROW · encodes the exclusion of candidates g and f from different cases", 17, BLUE, 700)
    s.text(64, 302, "At most one of g and f may be selected.", 23, INK, 700)
    s.text(1133, 296, "x_g + x_f ≤ 1", 27, INK, 700, "end")

    # One shared candidate column prevents the two selections being mistaken
    # for different observations or alternative experimental configurations.
    s.rect(40, 341, 1120, 582, "white", "#D7E1EB", 12)
    s.text(64, 380, "CANDIDATES · unchanged", 20, INK, 700)
    s.text(64, 410, "Only relevant candidates are shown.", 17, MUTED)
    s.text(740, 380, "GT selection", 23, INK, 700, "middle")
    s.text(740, 410, "Choose GT throughout", 17, MUTED, anchor="middle")
    s.text(1020, 380, "Changed selection", 23, INK, 700, "middle")
    s.text(1020, 410, "Change only case 9 below", 17, MUTED, anchor="middle")

    # The observation group bands span both selection columns.
    s.rect(41, 432, 1118, 37, "#F0F3F7", "none", 0)
    s.text(64, 457, "CASE 86 · one observation", 17, INK, 700)
    s.rect(41, 561, 1118, 37, "#F0F3F7", "none", 0)
    s.text(64, 586, "CASE 9 · one observation, two candidates shown", 17, INK, 700)
    for x in (600, 880):
        s.arrow([(x, 348), (x, 921)], head=False)
    s.arrow([(41, 695), (1159, 695)], head=False)
    s.arrow([(41, 824), (1159, 824)], head=False)

    def endpoint(x, y, label):
        s.rect(x, y - 22, 32, 32, "white", INK, 6)
        s.text(x + 16, y + 1, label, 22, INK, 700, "middle")

    endpoint(64, 505, "g")
    s.text(110, 505, "spin leg", 24, INK, 700)
    s.text(110, 537, "GT candidate · annotated activity", 18, INK)
    s.text(110, 630, "pick up leg", 24, INK, 700)
    s.text(110, 663, "GT candidate · annotated activity", 18, INK)
    endpoint(64, 733, "f")
    s.text(110, 733, "align leg screw with table thread", 24, INK, 700)
    s.text(110, 773, "NON-GT candidate · alternative activity", 18, INK)

    def selection(center, y, selected):
        x = center - 110
        s.rect(x, y - 29, 220, 59, "#EAF0F8" if selected else "white",
               "#ABC4DF" if selected else "#CDD5DF", 10)
        s.rect(x + 17, y - 12, 24, 24, BLUE if selected else "white",
               BLUE if selected else MUTED, 3)
        if selected:
            s.parts.append(f'<path d="M {x + 22} {y} l 5 5 l 10 -11" '
                           'fill="none" stroke="white" stroke-width="3" '
                           'stroke-linecap="round" stroke-linejoin="round"/>')
        s.text(x + 54, y + 7, "SELECTED" if selected else "Not selected", 20,
               BLUE if selected else INK, 700 if selected else 400)

    for center, changed in ((740, False), (1020, True)):
        selection(center, 511, True)
        selection(center, 643, not changed)
        selection(center, 754, changed)
        s.text(center, 862, "1 + 1 = 2 > 1" if changed else "1 + 0 = 1 ≤ 1", 24, INK, 700, "middle")
        s.text(center, 900, "ROW VIOLATED" if changed else "ROW SATISFIED", 21, INK, 700, "middle")
    s.text(64, 862, "Check the added row", 23, INK, 700)
    s.text(64, 896, "Count selected candidates g and f only.", 19, MUTED)

    s.text(40, 960, "One observation’s activity interpretation changes; cases and times stay fixed.", 24, INK, 700)
    s.text(40, 995, "Every other observation keeps its GT choice; all original rules and all other exclusions still hold.", 20, MUTED)
    s.text(40, 1027, "GT remains feasible. The changed selection becomes feasible only if this added row is removed.", 20, INK)
    s.text(40, 1064, "Saved example: bridge:000000 · Each observation has three candidates; only those needed here are shown.", 17, MUTED)
    return s.finish()


def generate():
    row = checked_example()
    target = ROOT / "docs/coupling/assets/endpoint_choices.svg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(diagram(row), encoding="utf-8")
    print(f"Checked example and generated: {target}")


if __name__ == "__main__":
    generate()
