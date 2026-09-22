"""Transparent CSV/JSON and XES outputs for human and programmatic inspection."""

from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime, timedelta, timezone
import gzip
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _cell(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) if isinstance(value, (dict, list)) else value


def write_csv(path, records, fields=None):
    path = Path(path)
    records = list(records)
    fields = fields or (list(records[0]) if records else [])
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows({key: _cell(row.get(key, "")) for key in fields} for row in records)
    content = text.getvalue().encode("utf-8")
    path.write_bytes(gzip.compress(content, mtime=0) if path.suffix == ".gz" else content)


def write_xes(path, rows, cases, uncertain=False, fps=25):
    """XES dates encode RELATIVE case time at fps; clocks do not imply concurrency."""
    ns = "http://www.xes-standard.org/"
    ET.register_namespace("", ns)
    def element(tag, **attrs):
        return ET.Element(f"{{{ns}}}{tag}", attrs)
    def attr(parent, kind, key, value):
        ET.SubElement(parent, f"{{{ns}}}{kind}", key=key, value=str(value))
    log = element("log", **{"xes.version": "1.0", "xes.features": "nested-attributes"})
    log.append(element("extension", name="Concept", prefix="concept", uri="http://www.xes-standard.org/concept.xesext"))
    log.append(element("extension", name="Time", prefix="time", uri="http://www.xes-standard.org/time.xesext"))
    log.append(element("classifier", name="Activity", keys="concept:name"))
    attr(log, "string", "concept:name", "IKEA ASM GT-aligned uncertain scores" if uncertain else "IKEA ASM ground truth")
    attr(log, "int", "frames_per_second", fps)
    attr(log, "string", "clock_semantics", "Case-relative video time; epoch is synthetic; no observed inter-case concurrency.")
    if uncertain:
        attr(log, "string", "score_semantics", "Original mean frame scores after candidate selection; not renormalized. concept:name is the score argmax. See candidate_policy.json for score-only or GT-enriched selection.")
    by_case = defaultdict(list)
    for row in rows:
        by_case[row["case_id"]].append(row)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    for case in cases:
        trace = element("trace")
        attr(trace, "string", "concept:name", case["case_id"])
        attr(trace, "string", "case:name", case["case_name"])
        attr(trace, "string", "process_group", case["process_group"])
        for row in by_case[case["case_id"]]:
            event = element("event")
            attr(event, "string", "concept:name", row["top_activity"] if uncertain else row["activity"])
            attr(event, "string", "event_id", row["event_id"])
            for name in ("start_frame", "end_frame_exclusive", "duration_frames"):
                attr(event, "int", name, row[name])
            for key, boundary in (("time:timestamp", "start_frame"), ("time:end_timestamp", "end_frame_exclusive")):
                stamp = epoch + timedelta(seconds=row[boundary] / fps)
                attr(event, "date", key, stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"))
            if uncertain:
                attr(event, "string", "scores_json", json.dumps(row["scores"], separators=(",", ":")))
                attr(event, "float", "removed_na_score", row["removed_na_score"])
                attr(event, "float", "discarded_non_na_score_mass", row.get("discarded_non_na_score_mass", 0.0))
                attr(event, "float", "remaining_score_mass", row["remaining_score_mass"])
            trace.append(event)
        log.append(trace)
    ET.indent(log, space="  ")
    content = ET.tostring(log, encoding="utf-8", xml_declaration=True)
    path = Path(path)
    path.write_bytes(gzip.compress(content, mtime=0) if path.suffix == ".gz" else content)


def build_templates(mined):
    rules = []
    for i, rule in enumerate(mined["accepted_prerequisites"], 1):
        rules.append({"id": f"pre_{i:03d}", "kind": "prerequisite", "trigger_activity": rule["trigger"],
                      "predecessor_activities": [rule["predecessor"]], "applies_to": "each_retained_case",
                      "condition": "predecessor.end_frame_exclusive <= trigger.start_frame",
                      "activated_cases": rule["activated_cases"], "activated_events": rule["activated_events"],
                      "active_in_all_cases": rule["active_in_all_cases"]})
    for i, bound in enumerate(mined["occurrence_bounds"], 1):
        rules.append({"id": f"occ_{i:03d}", "kind": "occurrence_bound", "activities": [bound["activity"]],
                      "lower": bound["minimum"], "upper": bound["maximum"],
                      "applies_to": "each_retained_case", "positive_minimum": bound["positive_minimum"]})
    return {"schema_version": 1, "scope": "Rules discovered on this GT population; descriptive in-sample constraints.",
            "semantics": "Prerequisite existence, not immediate succession; at-most-one activity per observation. Occurrences count original non-NA GT segments, not physical objects.",
            "constraints": rules}


def prerequisite_witnesses(events, mined):
    by_case = defaultdict(list)
    for event in events:
        by_case[event["case_id"]].append(event)
    witnesses = []
    for i, rule in enumerate(mined["accepted_prerequisites"], 1):
        for case, case_events in sorted(by_case.items()):
            supporters = [e for e in case_events if e["activity"] == rule["predecessor"]]
            for trigger in (e for e in case_events if e["activity"] == rule["trigger"]):
                earlier = [e for e in supporters if e["end_frame_exclusive"] <= trigger["start_frame"]]
                if not earlier:
                    raise ValueError("Accepted prerequisite has no witness")
                witness = min(earlier, key=lambda e: (e["end_frame_exclusive"], e["event_id"]))
                witnesses.append({"constraint_id": f"pre_{i:03d}", "case_id": case,
                                  "predecessor": rule["predecessor"], "trigger": rule["trigger"],
                                  "predecessor_event_id": witness["event_id"], "trigger_event_id": trigger["event_id"],
                                  "predecessor_end_frame_exclusive": witness["end_frame_exclusive"],
                                  "trigger_start_frame": trigger["start_frame"]})
    return witnesses


def export_cohort(folder, events, uncertain, cases, mined, variants, top_k=3, candidate_policy="top-k"):
    folder = Path(folder)
    folder.mkdir()
    event_fields = ["event_id", "case_id", "case_name", "start_frame", "end_frame_exclusive", "duration_frames", "activity"]
    write_csv(folder / "ground_truth.csv", events, event_fields)
    uncertain = [{**row, "discarded_non_na_score_mass": row.get("discarded_non_na_score_mass", 0.0)} for row in uncertain]
    score_fields = event_fields[:-1] + ["top_activity", "scores", "removed_na_score", "discarded_non_na_score_mass", "remaining_score_mass"]
    write_csv(folder / "uncertain_log.csv.gz", uncertain, score_fields)
    write_csv(folder / "cases.csv", cases)
    write_xes(folder / "ground_truth.xes", events, cases)
    write_xes(folder / "uncertain_log.xes.gz", uncertain, cases, uncertain=True)
    write_json(folder / "constraints.json", build_templates(mined))
    write_json(folder / "constraint_audit.json", mined)
    write_json(folder / "candidate_policy.json", {"top_k": top_k, "candidate_policy": candidate_policy,
               "activity_vocabulary": mined["metadata"]["activities"],
               "ordering": "Descending original non-NA mean score; lexicographic activity name breaks ties.",
               "renormalized": False, "gt_label_insertion": candidate_policy == "top-k-gt",
               "gt_rule": "Replace the lowest-ranked retained candidate with GT only if GT is absent; preserve original score."
                          if candidate_policy == "top-k-gt" else "No GT-based candidate changes."})
    coverage = [{"event_id": a["event_id"], "case_id": a["case_id"], "gt_activity": a["activity"],
                 "gt_retained": a["activity"] in b["scores"],
                 "retained_rank": (sorted(b["scores"], key=lambda label: (-b["scores"][label], label)).index(a["activity"]) + 1)
                                  if a["activity"] in b["scores"] else ""}
                for a, b in zip(events, uncertain)]
    write_csv(folder / "candidate_coverage.csv", coverage)
    write_csv(folder / "prerequisites.csv", mined["accepted_prerequisites"])
    write_csv(folder / "all_prerequisite_pairs.csv", mined["prerequisites"])
    write_csv(folder / "occurrence_bounds.csv", mined["occurrence_bounds"])
    write_csv(folder / "occurrence_counts_by_case.csv", [
        {"case_id": case["case_id"], "case_name": case["case_name"],
         **{b["activity"]: b["per_case_counts"][case["case_id"]] for b in mined["occurrence_bounds"]}} for case in cases])
    write_csv(folder / "prerequisite_witnesses.csv", prerequisite_witnesses(events, mined))
    write_csv(folder / "variants.csv", variants["variants"])
    write_json(folder / "variant_selection.json", variants)


def markdown_report(summary, board, mined, variant_preview):
    best = next(r for r in board if r["model_id"] == summary["selected_model"])
    selection = "explicit model override" if summary.get("model_override") else f"highest {summary['accuracy_scope']} frame accuracy"
    oracle = summary["candidate_policy"] == "top-k-gt"
    candidate_description = ("Start with the highest-scoring non-NA candidates and replace the last with GT only when GT is missing."
                             if oracle else "Keep the highest-scoring non-NA candidates without GT-based changes.")
    lines = ["# IKEA ASM constraint discovery", "",
             f"Selected model: **{summary['selected_model']}**; selection method: **{selection}**.", "",
             f"Non-NA frame accuracy: {best['correct_non_na_frames']:,}/{best['non_na_frames']:,} = **{best['accuracy_non_na_frames']:.4%}**.",
             f"Unmodified model GT-segment top-one accuracy after removing NA alternatives: {best['correct_non_na_segments_after_na_removal']:,}/{best['non_na_segments']:,} = **{best['accuracy_non_na_segments_after_na_removal']:.4%}**. This is a different metric.", "",
             f"The full cohort has **{summary['case_count']} cases**, including **{summary['empty_case_count']} empty after NA removal**, and **{summary['event_count']:,} observations**. Each keeps **{min(summary['top_k'], summary['activity_count'])} non-NA candidates** from a vocabulary of {summary['activity_count']} activities, without renormalization (**{summary['candidate_count']:,} candidates**).",
             f"Candidate policy: **{summary['candidate_policy']}**. {candidate_description} Original scores are unchanged.",
             f"GT is available in **{summary['gt_covered_observations']:,}/{summary['event_count']:,} observations ({summary['gt_candidate_coverage']:.4%})**. GT replacements: **{summary['gt_replacement_count']}**; see `candidate_replacements.csv` and `full/candidate_coverage.csv`.",
             "This is an **oracle candidate setting**: 100% coverage is supplied by construction, not achieved by the classifier."
                if oracle else "This is a score-only candidate setting; missing GT labels are not inserted.",
             f"Found **{len(mined['accepted_prerequisites'])} nonvacuous prerequisites** with no violations, **{len(mined['occurrence_bounds'])} singleton occurrence bounds**, and **{mined['metadata']['positive_minimum_count']} positive universal minima**.", "",
             "A rule holding in every case can be vacuously satisfied in cases without its trigger. The activation columns below show the distinction.", "",
             "## Model comparison", "", "| Model | Non-NA frame accuracy | All-frame accuracy |", "|---|---:|---:|"]
    for row in sorted(board, key=lambda r: -r["accuracy_non_na_frames"]):
        lines.append(f"| {row['model_id']} | {row['accuracy_non_na_frames']:.4%} | {row['accuracy_all_frames']:.4%} |")
    lines += ["", "## All accepted prerequisites", "",
              "Each trigger requires some earlier same-case predecessor. The predecessor need not immediately precede it and can support several triggers.", "",
              "| Predecessor | Trigger | Activated cases | Trigger events |", "|---|---|---:|---:|"]
    for r in sorted(mined["accepted_prerequisites"], key=lambda r: (-r["activated_cases"], r["predecessor"], r["trigger"])):
        lines.append(f"| {r['predecessor']} | {r['trigger']} | {r['activated_cases']}/{summary['case_count']} | {r['activated_events']} |")
    lines += ["", "## Occurrence bounds", "", "Counts include zero occurrences in every retained case. They are empirical segment-count limits, not resource capacities or verified physical laws.", "",
              "| Activity | Minimum per case | Maximum per case | Cases with activity |", "|---|---:|---:|---:|"]
    for b in mined["occurrence_bounds"]:
        lines.append(f"| {b['activity']} | {b['minimum']} | {b['maximum']} | {b['observed_in_cases']} |")
    v = variant_preview["metadata"]
    lines += ["", "## Variant filtering", "",
              f"There are **{v['total_variant_count']} exact GT sequence variants**. A most-frequent-variant target of 80%, including all frequency ties at the cutoff, retains **{v['selected_case_count']}/{v['total_case_count']} cases ({v['actual_coverage']:.1%})**.",
              "Filtering always applies the identical case-ID set to GT and uncertain logs. It never splits a variant or changes its events. A target does not guarantee exact coverage.", "",
              "## Audit and interpretation", "",
              "- GT segmentation and NA removal use annotations; this is an oracle-segmentation experiment.",
              "- Scores reuse the pinned upstream arithmetic averages of per-frame probabilities. NA is removed before ranking; ties use activity-name order. Candidate selection follows the declared policy; retained and inserted scores are unchanged, with no second softmax or renormalization.",
              "- Frame accuracy is exactly reconstructed by intersecting GT runs with constant-prediction runs, rather than confusing argmax-of-mean accuracy with per-frame accuracy.",
              "- All model GT annotations agree; weighted score totals agree across the two upstream segmentations; the separate certain XES has matching non-NA events.",
              "- Original frame probabilities, raw annotation alignment and model inference are not rerun by this project.",
              "- Model selection and rule discovery use this released test cohort. These are descriptive, in-sample results; future recognition claims need separately mined/trained and evaluated cohorts.",
              ("- GT supplies event boundaries, NA removal, discovered constraints and guaranteed candidate coverage. The full GT assignment is representable and satisfies the mined intra-case constraints, but need not maximize model scores."
               if oracle else "- GT supplies event boundaries, NA removal and discovered constraints. Score-only candidate pruning may remove GT labels, making the full GT assignment unrepresentable."),
              "- No real ownership, inter-case concurrency, or resource conflicts are inferred. See docs/CONTROLLED_INTERCASE.md for a later controlled overlay design.", "",
              "## Files to inspect", "",
              "Start with `full/ground_truth.csv`, `full/uncertain_log.csv.gz`, `full/prerequisites.csv`, `full/prerequisite_witnesses.csv`, and `full/occurrence_counts_by_case.csv`. Every failed pair has a counterexample in `full/all_prerequisite_pairs.csv`. `full/constraints.json` is the machine-readable template list.", ""]
    return "\n".join(lines)
