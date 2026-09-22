#!/usr/bin/env python3
"""Audit saved logs and discovered rules without importing the discovery code.

This independently interprets exported GT events. It checks file integrity,
log alignment, all tested prerequisite pairs, count bounds, witnesses and XES
time conversion. It does not rerun raw frame inference or establish held-out
validity. Usage: python3 verify.py [inputs/reference]
"""

from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_csv(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_cohort(folder):
    gt, uncertain, cases = (read_csv(folder / name) for name in
                             ("ground_truth.csv", "uncertain_log.csv.gz", "cases.csv"))
    case_ids = [row["case_id"] for row in cases]
    require(len(case_ids) == len(set(case_ids)), "Duplicate cases")
    case_set = set(case_ids)
    positions = {row["event_id"]: row for row in gt}
    require(len(positions) == len(gt), "Duplicate event IDs")
    require([row["event_id"] for row in gt] == [row["event_id"] for row in uncertain], "Log alignment differs")
    by_case = defaultdict(list)
    score_count = 0
    policy = json.loads((folder / "candidate_policy.json").read_text())
    alphabet = set(policy["activity_vocabulary"])
    require("NA" not in alphabet and isinstance(policy["top_k"], int) and policy["top_k"] > 0, "Invalid candidate policy")
    candidate_policy = policy.get("candidate_policy", "top-k")
    require(candidate_policy in {"top-k", "top-k-gt"}, "Unexpected candidate policy")
    require(policy["renormalized"] is False and policy["gt_label_insertion"] == (candidate_policy == "top-k-gt"), "Unexpected candidate policy")
    covered = 0
    coverage_rows = []
    for a, b in zip(gt, uncertain):
        require(a["case_id"] in case_set, "GT case absent from roster")
        for field in ("event_id", "case_id", "case_name", "start_frame", "end_frame_exclusive", "duration_frames"):
            require(a[field] == b[field], f"Aligned field differs: {field}")
        require(a["activity"] != "NA", "GT still has NA event")
        start, end = int(a["start_frame"]), int(a["end_frame_exclusive"])
        require(0 <= start < end and end - start == int(a["duration_frames"]), "Bad frame interval")
        scores = json.loads(b["scores"])
        require(set(scores).issubset(alphabet) and len(scores) == min(policy["top_k"], len(alphabet)), "Wrong top-k candidate count or label")
        require(all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0
                    for v in scores.values()), "Invalid candidate score")
        require("NA" not in scores and a["activity"] in alphabet, "Bad activity vocabulary")
        ranked = sorted(scores, key=lambda label: (-scores[label], label))
        require(ranked[0] == b["top_activity"], "Wrong non-NA argmax")
        retained = a["activity"] in scores
        require(candidate_policy != "top-k-gt" or retained, "Oracle candidate policy omitted GT")
        covered += retained
        coverage_rows.append({"event_id": a["event_id"], "case_id": a["case_id"], "gt_activity": a["activity"],
                              "gt_retained": str(retained), "retained_rank": str(ranked.index(a["activity"]) + 1) if retained else ""})
        mass = sum(scores.values())
        require(abs(mass - float(b["remaining_score_mass"])) < 1e-10, "Wrong retained score mass")
        discarded = float(b["discarded_non_na_score_mass"])
        require(math.isfinite(discarded) and discarded >= 0, "Invalid discarded score mass")
        require(abs(mass + float(b["removed_na_score"]) + discarded - 1) < 1e-5, "Score mass not conserved")
        score_count += len(scores)
        by_case[a["case_id"]].append(a)
    for case, events in by_case.items():
        ordered = sorted(events, key=lambda e: int(e["start_frame"]))
        require(all(int(a["end_frame_exclusive"]) <= int(b["start_frame"]) for a, b in zip(ordered, ordered[1:])),
                f"Overlapping GT observations in {case}")
    audit = json.loads((folder / "constraint_audit.json").read_text())
    require(read_csv(folder / "candidate_coverage.csv") == coverage_rows, "Candidate coverage report differs")
    pairs = [(pair["predecessor"], pair["trigger"]) for pair in audit["prerequisites"]]
    require(len(pairs) == len(set(pairs)) and set(pairs) == {(a, b) for a in alphabet for b in alphabet if a != b},
            "Missing, duplicated or unexpected prerequisite pair")
    bounded = [b["activity"] for b in audit["occurrence_bounds"]]
    require(len(bounded) == len(set(bounded)) and set(bounded) == alphabet, "Incomplete occurrence bound inventory")
    accepted = []
    for pair in audit["prerequisites"]:
        triggers = [e for e in gt if e["activity"] == pair["trigger"]]
        failures = [e for e in triggers if not any(
            earlier["activity"] == pair["predecessor"] and int(earlier["end_frame_exclusive"]) <= int(e["start_frame"])
            for earlier in by_case[e["case_id"]])]
        active_cases = {e["case_id"] for e in triggers}
        require(pair["violation_count"] == len(failures), "Wrong prerequisite event violation count")
        require(pair["violated_cases"] == len({e["case_id"] for e in failures}), "Wrong prerequisite case violation count")
        require(pair["activated_events"] == len(triggers) and pair["activated_cases"] == len(active_cases), "Wrong activation count")
        require(pair["vacuous_cases"] == len(cases) - len(active_cases), "Wrong vacuity count")
        require(pair["active_in_all_cases"] == (active_cases == case_set), "Wrong universal activation flag")
        require(pair["accepted"] == bool(triggers and not failures), "Wrong accepted prerequisite flag")
        if pair["accepted"]:
            accepted.append((pair["predecessor"], pair["trigger"]))
        if failures:
            counterexample = pair["first_counterexample"]
            require(counterexample["trigger_event_id"] in {e["event_id"] for e in failures}, "Invalid counterexample")
    require(accepted == [(p["predecessor"], p["trigger"]) for p in audit["accepted_prerequisites"]], "Accepted rule inventory differs")
    for bound in audit["occurrence_bounds"]:
        counts = {case: sum(e["activity"] == bound["activity"] for e in by_case[case]) for case in case_ids}
        require(bound["per_case_counts"] == counts, "Occurrence counts differ")
        require(bound["minimum"] == min(counts.values()) and bound["maximum"] == max(counts.values()), "Wrong empirical bound")
    templates = json.loads((folder / "constraints.json").read_text())["constraints"]
    pre_templates = [t for t in templates if t["kind"] == "prerequisite"]
    require([(p["predecessor_activities"][0], p["trigger_activity"]) for p in pre_templates] == accepted, "Template rules differ from audit")
    occurrence_templates = [t for t in templates if t["kind"] == "occurrence_bound"]
    require([(t["activities"][0], t["lower"], t["upper"]) for t in occurrence_templates] ==
            [(b["activity"], b["minimum"], b["maximum"]) for b in audit["occurrence_bounds"]], "Bound templates differ")
    witnessed = []
    by_rule = {t["id"]: t for t in pre_templates}
    for witness in read_csv(folder / "prerequisite_witnesses.csv"):
        a, b = positions[witness["predecessor_event_id"]], positions[witness["trigger_event_id"]]
        rule = by_rule[witness["constraint_id"]]
        require(a["case_id"] == b["case_id"] == witness["case_id"], "Cross-case witness")
        require(a["activity"] in rule["predecessor_activities"] and b["activity"] == rule["trigger_activity"], "Wrong witness activities")
        require(int(a["end_frame_exclusive"]) <= int(b["start_frame"]), "Late witness")
        witnessed.append((witness["constraint_id"], b["event_id"]))
    expected_witnesses = {(t["id"], e["event_id"]) for t in pre_templates for e in gt if e["activity"] == t["trigger_activity"]}
    require(set(witnessed) == expected_witnesses and len(witnessed) == len(expected_witnesses), "Incomplete or duplicate witnesses")
    ns = {"x": "http://www.xes-standard.org/"}
    for name in ("ground_truth.xes", "uncertain_log.xes.gz"):
        raw = (folder / name).read_bytes()
        root = ET.fromstring(gzip.decompress(raw) if name.endswith(".gz") else raw)
        traces = root.findall("x:trace", ns)
        require(len(traces) == len(cases), "XES omitted empty cases")
        count = 0
        for trace in traces:
            for event in trace.findall("x:event", ns):
                values = {e.get("key"): e.get("value") for e in event}
                expected = positions[values["event_id"]]
                stamp = datetime.fromisoformat(values["time:timestamp"].replace("Z", "+00:00"))
                seconds = (stamp - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()
                require(abs(seconds * 25 - int(expected["start_frame"])) < 1e-7, "Wrong frame-to-time conversion")
                count += 1
        require(count == len(gt), "XES event count differs")
    return {"cases": len(cases), "events": len(gt), "candidates": score_count,
            "gt_covered_observations": covered, "gt_candidate_coverage": covered / len(gt) if gt else None,
            "prerequisite_pairs_audited": len(audit["prerequisites"]), "accepted_prerequisites": len(accepted),
            "occurrence_bounds": len(audit["occurrence_bounds"]), "witnesses": len(witnessed)}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    study = Path(args[0]) if args else Path("inputs/reference")
    study = study if study.is_absolute() else ROOT / study
    inventory = json.loads((study / "artifact_manifest.json").read_text())["files"]
    for relative, expected in inventory.items():
        path = study / relative
        require(path.resolve().is_relative_to(study.resolve()), "Unsafe result manifest path")
        require(path.is_file() and digest(path) == expected["sha256"], f"Changed or missing result: {relative}")
    cohorts = {name: verify_cohort(study / name) for name in ("full", "selected") if (study / name).exists()}
    if "selected" in cohorts:
        ids = set(json.loads((study / "requested_variant_selection.json").read_text())["selected_case_ids"])
        for name in ("ground_truth.csv", "uncertain_log.csv.gz"):
            full = read_csv(study / "full" / name)
            selected = read_csv(study / "selected" / name)
            require([e for e in full if e["case_id"] in ids] == selected, "Variant filtering changed rows or misaligned logs")
    print(json.dumps({"status": "PASS", "hash_checked_files": len(inventory), "cohorts": cohorts,
                      "scope": "Export integrity, exact event/count semantics, witnesses, aligned scores and XES clocks. No raw model-inference reproduction."}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(f"ERROR: {error}") from error
