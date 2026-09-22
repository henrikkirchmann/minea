#!/usr/bin/env python3
"""Recompute descriptive log statistics without a solver or external packages.

The prepared CSVs are the authority for retained observations and scores.
Raw frame-prediction counts are available only as recorded upstream provenance;
they are deliberately separate from agreement of the retained segment labels.
"""

import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction
import gzip
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASS_TOLERANCE = Fraction("0.000001")
RETAINED_MASS_TOLERANCE = Fraction("0.000000000001")


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _csv(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _by_id(rows, key, label):
    result = {row[key]: row for row in rows}
    _require(len(result) == len(rows), f"Duplicate {label}")
    return result


def _scores(raw):
    # JSON number tokens remain strings; no binary float replaces an input score.
    values = json.loads(raw, parse_float=str, parse_int=str, object_pairs_hook=_unique)
    _require(isinstance(values, dict) and values, "Scores must be a nonempty object")
    for label, token in values.items():
        _require(isinstance(label, str) and label and label != "NA", "Invalid retained activity")
        _require(isinstance(token, str), "Scores must be original JSON numbers")
        _require(0 <= Fraction(token) <= 1, "Candidate score outside [0,1]")
    return values


def _rank(scores):
    return sorted(scores, key=lambda activity: (-Fraction(scores[activity]), activity))


def _score_json(scores):
    return "{" + ",".join(json.dumps(label, ensure_ascii=False) + ":" + scores[label]
                           for label in _rank(scores)) + "}"


def ratio(numerator, denominator):
    value = Fraction(numerator, denominator) if denominator else None
    return {"numerator": numerator, "denominator": denominator,
            "fraction": str(value) if value is not None else None,
            "value": float(value) if value is not None else None,
            "percent": float(value * 100) if value is not None else None}


def distribution(values):
    """Linear-interpolated quartiles and population SD, including tiny samples."""
    values = sorted(Fraction(value) for value in values)
    names = ("minimum", "q1", "median", "q3", "maximum", "mean", "population_sd")
    if not values:
        return {"count": 0, **dict.fromkeys(names)}

    def quantile(p):
        position = (len(values) - 1) * p
        lower = position.numerator // position.denominator
        remainder = position - lower
        return values[lower] if not remainder else values[lower] + remainder * (values[lower + 1] - values[lower])

    mean = sum(values, Fraction()) / len(values)
    variance = sum(((value - mean) ** 2 for value in values), Fraction()) / len(values)
    return {"count": len(values), "minimum": float(values[0]),
            "q1": float(quantile(Fraction(1, 4))), "median": float(quantile(Fraction(1, 2))),
            "q3": float(quantile(Fraction(3, 4))), "maximum": float(values[-1]),
            "mean": float(mean), "population_sd": math.sqrt(float(variance))}


def _flat_distribution(prefix, values):
    return {prefix + "_" + key: value for key, value in distribution(values).items()}


def _write_csv(path, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                             if isinstance(value, (list, dict)) else value for key, value in row.items()})


def generate(root, output):
    """Write the nine descriptive-statistics files and return log_stats.json."""
    root, output = Path(root).resolve(), Path(output).resolve()
    reference = root / "inputs/reference"
    full = reference / "full"
    inputs = {}

    def read(path):
        raw = path.read_bytes()
        inputs[path.relative_to(root).as_posix()] = {
            "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        return (json.loads(raw, object_pairs_hook=_unique) if path.suffix == ".json" else _csv(path))

    cases = _by_id(read(full / "cases.csv"), "case_id", "case ID")
    truth = _by_id(read(full / "ground_truth.csv"), "event_id", "GT event ID")
    uncertain_path = full / "uncertain_log.csv.gz"
    if not uncertain_path.exists():
        uncertain_path = full / "uncertain_log.csv"
    uncertain = _by_id(read(uncertain_path), "event_id", "uncertain event ID")
    replacements = _by_id(read(reference / "candidate_replacements.csv"), "event_id", "replacement event ID")
    policy = read(full / "candidate_policy.json")
    protocol = read(reference / "protocol.json")
    source = read(reference / "source_audit.json")
    models = read(reference / "model_selection.json")
    fps = int(protocol["frames_per_second"])
    _require(fps > 0, "Frame rate must be positive")
    _require(set(truth) == set(uncertain), "GT and uncertain event IDs do not align")
    _require(set(replacements) <= set(truth), "Replacement refers to an unknown observation")
    _require(policy["top_k"] == 3 and policy["renormalized"] is False,
             "This report describes exactly three unnormalized candidates")
    _require(policy["gt_label_insertion"] is True, "Expected declared GT insertion policy")
    _require(models["selection_metric"] == "non_na", "Expected non-NA frame model-selection criterion")
    observations, by_case = [], {case: [] for case in cases}
    raw_score_values, mass_errors, remaining_errors = [], [], []
    preinsertion_candidates = Counter()
    for event_id in sorted(truth, key=lambda event: (truth[event]["case_id"],
            int(truth[event]["start_frame"]), int(truth[event]["end_frame_exclusive"]), event)):
        gt, un = truth[event_id], uncertain[event_id]
        case = gt["case_id"]
        _require(case in cases, f"Unknown case: {case}")
        for field in ("case_id", "case_name", "start_frame", "end_frame_exclusive", "duration_frames"):
            _require(gt[field] == un[field], f"GT/uncertain alignment differs: {event_id} {field}")
        _require(gt["case_name"] == cases[case]["case_name"], f"Case name differs: {event_id}")
        start, end, duration = (int(gt[k]) for k in ("start_frame", "end_frame_exclusive", "duration_frames"))
        _require(0 <= start < end <= int(cases[case]["total_frames"]) and duration == end - start,
                 f"Invalid half-open interval: {event_id}")
        scores = _scores(un["scores"])
        labels = _rank(scores)
        _require(len(labels) == 3, f"Expected three candidates: {event_id}")
        _require(gt["activity"] != "NA" and gt["activity"] in scores, f"Missing non-NA GT label: {event_id}")
        _require(labels[0] == un["top_activity"], f"Top activity disagrees with original scores: {event_id}")
        _require(set(labels) <= set(policy["activity_vocabulary"]), "Candidate outside recorded vocabulary")
        original_top3 = dict(scores)
        replacement = replacements.get(event_id)
        if replacement:
            _require(replacement["case_id"] == case and replacement["inserted_gt_activity"] == gt["activity"],
                     f"Replacement identity differs: {event_id}")
            _require(Fraction(replacement["inserted_original_score"]) == Fraction(scores[gt["activity"]]),
                     f"Inserted score changed: {event_id}")
            _require(replacement["replaced_activity"] not in scores, f"Replaced label is still retained: {event_id}")
            original_top3.pop(gt["activity"])
            original_top3[replacement["replaced_activity"]] = replacement["replaced_score"]
            original_rank = int(replacement["gt_original_non_na_rank"])
            _require(3 < original_rank <= len(policy["activity_vocabulary"]), "Invalid recorded original GT rank")
            _require(_rank(original_top3)[-1] == replacement["replaced_activity"],
                     "Replacement did not remove the original third-ranked candidate")
            combined = {**original_top3, gt["activity"]: scores[gt["activity"]]}
            _require(_rank(combined).index(gt["activity"]) == 3, "Inserted GT outranks an original top-three candidate")
        else:
            original_rank = labels.index(gt["activity"]) + 1
        _require(_rank(original_top3)[0] == labels[0], "GT insertion changed the non-NA top prediction")
        preinsertion_candidates.update(original_top3.keys())
        values = [Fraction(scores[label]) for label in labels]
        retained = sum(values, Fraction())
        removed_na = Fraction(un["removed_na_score"])
        discarded = Fraction(un["discarded_non_na_score_mass"])
        remaining = Fraction(un["remaining_score_mass"])
        _require(0 <= removed_na <= 1 and discarded >= 0, "Negative or invalid removed score mass")
        mass_error = abs(retained + removed_na + discarded - 1)
        remaining_error = abs(retained - remaining)
        _require(mass_error <= MASS_TOLERANCE, f"Score mass differs from one by more than 1e-6: {event_id}")
        _require(remaining_error <= RETAINED_MASS_TOLERANCE, f"Recorded retained mass differs: {event_id}")
        mass_errors.append(mass_error)
        remaining_errors.append(remaining_error)
        raw_score_values.extend(values)
        record = {"event_id": event_id, "case_id": case, "process_group": cases[case]["process_group"],
            "start_frame": start, "end_frame_exclusive": end, "duration_frames": duration,
            "duration_seconds": duration / fps, "gt_activity": gt["activity"],
            "candidate_count": len(labels), "candidate_labels": labels,
            "original_scores_json": un["scores"], "pre_insertion_top3_original_scores_json": _score_json(original_top3),
            "top_activity": labels[0], "top_score_original": scores[labels[0]],
            "second_score_original": scores[labels[1]], "top1_minus_top2_margin_exact": str(values[0] - values[1]),
            "gt_score_original": scores[gt["activity"]], "gt_retained_rank": labels.index(gt["activity"]) + 1,
            "gt_original_non_na_rank": original_rank,
            "original_rank_source": "recorded replacement provenance" if replacement else "recomputed within original top three",
            "gt_inserted": bool(replacement), "gt_present_before_insertion": not bool(replacement),
            "replaced_activity": replacement["replaced_activity"] if replacement else None,
            "replaced_score_original": replacement["replaced_score"] if replacement else None,
            "top1_matches_gt": labels[0] == gt["activity"],
            "retained_score_mass_exact": str(retained), "reported_retained_mass_original": un["remaining_score_mass"],
            "pre_insertion_top3_mass_exact": str(sum((Fraction(v) for v in original_top3.values()), Fraction())),
            "removed_na_score_original": un["removed_na_score"],
            "discarded_non_na_mass_original": un["discarded_non_na_score_mass"],
            "absolute_score_mass_residual_exact": str(mass_error),
            "absolute_reported_retained_mass_error_exact": str(remaining_error)}
        observations.append(record)
        by_case[case].append(record)

    def agreement(events):
        return {"top1_segment_agreement": ratio(sum(e["top1_matches_gt"] for e in events), len(events)),
                "duration_weighted_segment_agreement": ratio(
                    sum(e["duration_frames"] for e in events if e["top1_matches_gt"]),
                    sum(e["duration_frames"] for e in events))}

    model_rows = []
    model_ids = _by_id(models["models"], "model_id", "model ID")
    selected_model = models["selected_model"]
    _require(selected_model in model_ids, "Selected model is absent")
    ordered_models = sorted(model_ids.values(), key=lambda m: (-m["correct_non_na_frames"], m["model_id"]))
    if models.get("model_override") is None:
        _require(ordered_models[0]["model_id"] == selected_model, "Selected model does not maximize recorded non-NA frame accuracy")
    original_cases = source["original_case_ids"]
    _require(len(original_cases) == len(set(original_cases)), "Duplicate upstream case ID")
    selected_by_case = _by_id(model_ids[selected_model]["per_case"], "case_id", "model case ID")
    for rank, model in enumerate(ordered_models, 1):
        per_case = _by_id(model["per_case"], "case_id", "model case ID")
        _require(set(per_case) == set(original_cases), "Upstream model case populations differ")
        _require(all(0 <= row["correct_frames"] <= row["frames"]
                     and 0 <= row["correct_non_na_frames"] <= row["non_na_frames"] <= row["frames"]
                     for row in per_case.values()), "Invalid recorded frame counts")
        for field in ("frames", "correct_frames", "non_na_frames", "correct_non_na_frames"):
            _require(sum(row[field] for row in per_case.values()) == model[field], f"Recorded model subtotal differs: {field}")
        _require(model["frames"] == ordered_models[0]["frames"] and model["non_na_frames"] == ordered_models[0]["non_na_frames"],
                 "Frame populations differ between models")
        model_rows.append({"model_id": model["model_id"], "selected": model["model_id"] == selected_model,
            "rank_by_recorded_non_na_frame_accuracy": rank, "raw_case_count": len(per_case),
            **{key: model[key] for key in ("frames", "correct_frames", "non_na_frames", "correct_non_na_frames",
                "non_na_segments", "correct_non_na_segments_original", "correct_non_na_segments_after_na_removal")},
            "raw_all_frame_accuracy": model["correct_frames"] / model["frames"],
            "raw_non_na_frame_accuracy": model["correct_non_na_frames"] / model["non_na_frames"],
            "recorded_segment_agreement_before_na_removal": model["correct_non_na_segments_original"] / model["non_na_segments"],
            "recorded_segment_agreement_after_na_removal": model["correct_non_na_segments_after_na_removal"] / model["non_na_segments"],
            "evidence": "Recorded upstream prediction counts; ratios recomputed here, no raw frame predictions re-evaluated."})
    _require(set(cases) <= set(original_cases), "Retained cases absent from original roster")
    omitted = sorted(set(original_cases) - set(cases))
    _require(omitted == sorted(source["explicitly_excluded_empty_cases"]), "Excluded case IDs differ from source audit")
    _require(all(selected_by_case[c]["non_na_frames"] == 0 for c in omitted), "An excluded case contains non-NA frames")

    case_rows, variants_at, starts, ends = [], defaultdict(list), Counter(), Counter()
    transitions = defaultdict(list)
    for case in sorted(cases):
        meta, events = cases[case], by_case[case]
        for left, right in zip(events, events[1:]):
            _require(left["end_frame_exclusive"] <= right["start_frame"], f"Overlapping GT intervals in case {case}")
            transitions[left["gt_activity"], right["gt_activity"]].append(case)
        labels = [e["gt_activity"] for e in events]
        counts = Counter(labels)
        variants_at[tuple(labels)].append(case)
        if labels:
            starts[labels[0]] += 1
            ends[labels[-1]] += 1
        total_frames = int(meta["total_frames"])
        active_frames = sum(e["duration_frames"] for e in events)
        _require(selected_by_case[case]["frames"] == total_frames and selected_by_case[case]["non_na_frames"] == active_frames,
                 f"Case frame totals disagree with upstream provenance: {case}")
        removed_na_segments = int(meta["removed_na_segments"])
        _require(removed_na_segments >= 0, "Negative removed NA segment count")
        span = events[-1]["end_frame_exclusive"] - events[0]["start_frame"] if events else 0
        metrics = agreement(events)
        case_rows.append({"case_id": case, "case_name": meta["case_name"], "process_group": meta["process_group"],
            "retained_event_count": len(events), "distinct_activities": len(counts),
            "repeat_events_after_first_occurrence": len(events) - len(counts),
            "activities_occurring_more_than_once": sum(n > 1 for n in counts.values()),
            "adjacent_equal_activity_pairs": sum(a == b for a, b in zip(labels, labels[1:])),
            "recording_frames": total_frames, "recording_seconds": total_frames / fps,
            "retained_event_frames": active_frames, "retained_event_seconds": active_frames / fps,
            "retained_span_frames": span, "retained_span_seconds": span / fps,
            "uncovered_na_frames": total_frames - active_frames, "removed_na_segments": removed_na_segments,
            "original_segments_in_this_retained_case": len(events) + removed_na_segments,
            "first_activity": labels[0] if labels else None, "last_activity": labels[-1] if labels else None,
            "gt_insertions": sum(e["gt_inserted"] for e in events),
            "gt_original_top3_retained": sum(e["gt_present_before_insertion"] for e in events),
            "top1_correct_segments": metrics["top1_segment_agreement"]["numerator"],
            "top1_segment_agreement": metrics["top1_segment_agreement"]["value"],
            "frames_in_top1_correct_segments": metrics["duration_weighted_segment_agreement"]["numerator"],
            "duration_weighted_segment_agreement": metrics["duration_weighted_segment_agreement"]["value"],
            "recorded_upstream_correct_non_na_frames": selected_by_case[case]["correct_non_na_frames"],
            "activity_counts": dict(sorted(counts.items())),
            **_flat_distribution("event_duration_frames", [e["duration_frames"] for e in events])})

    variant_rows = []
    frequencies = []
    for index, (sequence, members) in enumerate(sorted(variants_at.items(), key=lambda item: (-len(item[1]), item[0])), 1):
        frequency = len(members)
        frequencies.append(frequency)
        variant_rows.append({"variant_id": f"variant_{index:03d}", "event_count": len(sequence),
            "case_count": frequency, "case_share": frequency / len(cases),
            "cumulative_case_share": sum(frequencies) / len(cases), "singleton": frequency == 1,
            "activity_sequence": list(sequence), "case_ids": sorted(members),
            "process_group_counts": dict(sorted(Counter(cases[c]["process_group"] for c in members).items()))})
    transition_rows = [{"source_activity": left, "target_activity": right, "occurrences": len(members),
        "case_count": len(set(members)), "case_ids": sorted(set(members)),
        "process_group_counts": dict(sorted(Counter(cases[c]["process_group"] for c in members).items()))}
        for (left, right), members in sorted(transitions.items())]
    _require(sum(r["occurrences"] for r in transition_rows) == sum(max(0, len(e) - 1) for e in by_case.values()),
             "Direct-follow totals differ")

    activity_rows = []
    gt_vocabulary = sorted({e["gt_activity"] for e in observations})
    candidate_counts = Counter(a for e in observations for a in e["candidate_labels"])
    for activity in sorted(set(gt_vocabulary) | set(candidate_counts) | set(preinsertion_candidates)):
        events = [e for e in observations if e["gt_activity"] == activity]
        per_case_counts = [sum(e["gt_activity"] == activity for e in by_case[c]) for c in sorted(cases)]
        durations = [e["duration_frames"] for e in events]
        activity_rows.append({"activity": activity, "gt_occurrences": len(events),
            "gt_observation_share": len(events) / len(observations), "cases_with_activity": sum(n > 0 for n in per_case_counts),
            "case_coverage": sum(n > 0 for n in per_case_counts) / len(cases),
            "duration_frames": sum(durations), "duration_seconds": sum(durations) / fps,
            "starts": starts[activity], "ends": ends[activity],
            "retained_candidate_occurrences": candidate_counts[activity],
            "pre_insertion_candidate_occurrences": preinsertion_candidates[activity],
            "top1_predictions": sum(e["top_activity"] == activity for e in observations),
            "gt_insertions": sum(e["gt_inserted"] for e in events),
            "group_event_counts": dict(sorted(Counter(e["process_group"] for e in events).items())),
            "group_duration_frames": {g: sum(e["duration_frames"] for e in events if e["process_group"] == g)
                                      for g in sorted({e["process_group"] for e in events})},
            **_flat_distribution("event_duration_frames", durations),
            **_flat_distribution("occurrences_per_case_including_zeros", per_case_counts)})
    group_rows = []
    for group in sorted({c["process_group"] for c in cases.values()}):
        members = [r for r in case_rows if r["process_group"] == group]
        events = [e for e in observations if e["process_group"] == group]
        metrics = agreement(events)
        group_rows.append({"process_group": group, "case_count": len(members), "case_share": len(members) / len(cases),
            "event_count": len(events), "event_share": len(events) / len(observations),
            "distinct_activities": len({e["gt_activity"] for e in events}),
            "exact_variants": len({tuple(e["gt_activity"] for e in by_case[r["case_id"]]) for r in members}),
            "recording_frames": sum(r["recording_frames"] for r in members),
            "retained_event_frames": sum(e["duration_frames"] for e in events),
            "retained_event_seconds": sum(e["duration_frames"] for e in events) / fps,
            "uncovered_na_frames": sum(r["uncovered_na_frames"] for r in members),
            "removed_na_segments": sum(r["removed_na_segments"] for r in members),
            "gt_insertions": sum(e["gt_inserted"] for e in events),
            "cases_with_gt_insertions": sum(r["gt_insertions"] > 0 for r in members),
            "gt_original_top3_retained": sum(e["gt_present_before_insertion"] for e in events),
            "top1_correct_segments": metrics["top1_segment_agreement"]["numerator"],
            "top1_segment_agreement": metrics["top1_segment_agreement"]["value"],
            "frames_in_top1_correct_segments": metrics["duration_weighted_segment_agreement"]["numerator"],
            "duration_weighted_segment_agreement": metrics["duration_weighted_segment_agreement"]["value"],
            "activity_event_counts": dict(sorted(Counter(e["gt_activity"] for e in events).items())),
            "activity_duration_frames": {a: sum(e["duration_frames"] for e in events if e["gt_activity"] == a)
                                         for a in sorted({e["gt_activity"] for e in events})},
            **_flat_distribution("case_event_count", [r["retained_event_count"] for r in members]),
            **_flat_distribution("event_duration_frames", [e["duration_frames"] for e in events])})

    # Existing exports are independent cross-checks, never the source of these statistics.
    cross_checks = {}
    counts_path = full / "occurrence_counts_by_case.csv"
    if counts_path.exists():
        exported = _by_id(read(counts_path), "case_id", "exported count case")
        _require(set(exported) == set(cases), "Occurrence export case roster differs")
        for case in cases:
            computed = Counter(e["gt_activity"] for e in by_case[case])
            _require({a: int(exported[case][a]) for a in policy["activity_vocabulary"]} ==
                     {a: computed[a] for a in policy["activity_vocabulary"]}, "Occurrence counts disagree with independent export")
        cross_checks["occurrence_counts_by_case.csv"] = {"status": "PASS", "cases": len(cases)}
    bounds_path = full / "occurrence_bounds.csv"
    if bounds_path.exists():
        bounds = read(bounds_path)
        for row in bounds:
            counts = [sum(e["gt_activity"] == row["activity"] for e in by_case[c]) for c in sorted(cases)]
            _require((min(counts), max(counts), sum(counts), sum(n > 0 for n in counts)) ==
                     tuple(int(row[k]) for k in ("minimum", "maximum", "total_occurrences", "observed_in_cases")),
                     "Activity summaries disagree with occurrence-bound export")
        cross_checks["occurrence_bounds.csv"] = {"status": "PASS", "activities": len(bounds)}
    coverage_path = full / "candidate_coverage.csv"
    if coverage_path.exists():
        coverage = _by_id(read(coverage_path), "event_id", "coverage event")
        _require(set(coverage) == set(truth), "Coverage export event roster differs")
        for e in observations:
            row = coverage[e["event_id"]]
            _require(row["gt_retained"] == "True" and row["gt_activity"] == e["gt_activity"]
                     and row["case_id"] == e["case_id"] and int(row["retained_rank"]) == e["gt_retained_rank"],
                     "Candidate coverage disagrees with independent export")
        cross_checks["candidate_coverage.csv"] = {"status": "PASS", "observations": len(observations)}
    model_csv = reference / "model_selection.csv"
    if model_csv.exists():
        exported_models = _by_id(read(model_csv), "model_id", "exported model ID")
        _require(set(exported_models) == set(model_ids), "Model CSV/JSON model rosters differ")
        for row in exported_models.values():
            model = model_ids[row["model_id"]]
            for field in ("frames", "correct_frames", "non_na_frames", "correct_non_na_frames", "non_na_segments",
                          "correct_non_na_segments_original", "correct_non_na_segments_after_na_removal"):
                _require(int(row[field]) == model[field], "Model CSV/JSON recorded counts differ")
        cross_checks["model_selection.csv"] = {"status": "PASS", "models": len(model_ids)}
    summary_path = reference / "summary.json"
    if summary_path.exists():
        summary = read(summary_path)
        expected = {"case_count": len(cases), "event_count": len(observations), "activity_count": len(gt_vocabulary),
            "candidate_count": sum(e["candidate_count"] for e in observations), "gt_replacement_count": len(replacements),
            "removed_na_segments": sum(r["removed_na_segments"] for r in case_rows),
            "process_groups": {r["process_group"]: r["case_count"] for r in group_rows}}
        _require(all(summary[key] == value for key, value in expected.items()), "Recomputed totals disagree with input summary")
        _require(summary["requested_variant_selection"]["total_variant_count"] == len(variant_rows),
                 "Exact variant count differs from original export")
        cross_checks["summary.json"] = {"status": "PASS", "fields": list(expected) + ["total_variant_count"]}
    selected = model_ids[selected_model]
    agreement_metrics = agreement(observations)
    _require(selected["non_na_segments"] == len(observations) and
             selected["correct_non_na_segments_after_na_removal"] == agreement_metrics["top1_segment_agreement"]["numerator"],
             "Selected-model segment count differs from independent log recomputation")

    gt_distributions = {
        "case_event_count": distribution(r["retained_event_count"] for r in case_rows),
        "case_recording_frames": distribution(r["recording_frames"] for r in case_rows),
        "case_recording_seconds": distribution(Fraction(r["recording_frames"], fps) for r in case_rows),
        "case_retained_event_frames": distribution(r["retained_event_frames"] for r in case_rows),
        "case_retained_span_frames": distribution(r["retained_span_frames"] for r in case_rows),
        "case_distinct_activities": distribution(r["distinct_activities"] for r in case_rows),
        "case_repeat_events": distribution(r["repeat_events_after_first_occurrence"] for r in case_rows),
        "case_adjacent_equal_pairs": distribution(r["adjacent_equal_activity_pairs"] for r in case_rows),
        "case_removed_na_segments": distribution(r["removed_na_segments"] for r in case_rows),
        "case_uncovered_na_frames": distribution(r["uncovered_na_frames"] for r in case_rows),
        "event_duration_frames": distribution(e["duration_frames"] for e in observations),
        "event_duration_seconds": distribution(Fraction(e["duration_frames"], fps) for e in observations),
        "variant_case_frequency": distribution(frequencies)}
    score_values = {"retained_candidate_score": raw_score_values,
        "candidate_count_per_observation": [e["candidate_count"] for e in observations],
        **{metric: [Fraction(e[field]) for e in observations] for metric, field in (
            ("retained_score_mass", "retained_score_mass_exact"),
            ("pre_insertion_top3_score_mass", "pre_insertion_top3_mass_exact"),
            ("removed_na_score", "removed_na_score_original"),
            ("discarded_non_na_score_mass", "discarded_non_na_mass_original"),
            ("top_score", "top_score_original"), ("top1_minus_top2_margin", "top1_minus_top2_margin_exact"),
            ("gt_score", "gt_score_original"), ("gt_retained_rank", "gt_retained_rank"),
            ("gt_original_non_na_rank", "gt_original_non_na_rank"))},
        "inserted_gt_original_non_na_rank": [e["gt_original_non_na_rank"] for e in observations if e["gt_inserted"]]}
    score_distributions = {key: distribution(values) for key, values in score_values.items()}
    score_rows = [{"metric": key, "unit": "count" if "count" in key else "rank (one-based)" if "rank" in key else "original score",
                   **value} for key, value in score_distributions.items()]
    target = math.ceil(Fraction(4, 5) * len(cases))
    cumulative, minimum_variants = 0, 0
    for count in frequencies:
        cumulative += count
        minimum_variants += 1
        if cumulative >= target:
            break
    cutoff = frequencies[minimum_variants - 1]
    retained_frames = sum(e["duration_frames"] for e in observations)
    recording_frames = sum(r["recording_frames"] for r in case_rows)
    raw_frames = sum(r["frames"] for r in selected_by_case.values())
    definitions = {
        "cohort": {"calculation": "All rows in cases.csv; raw case roster comes from recorded source audit.",
            "scope": "The 817 removed NA segments concern the 116 retained cases only. The excluded all-NA case has no segment inventory here."},
        "intervals": {"unit": "frames", "calculation": "Half-open [start_frame,end_frame_exclusive); duration=end-start; seconds=frames/recorded frame rate."},
        "case_durations": {"calculation": "recording=whole case; retained_event=sum of non-NA durations; retained_span=last retained end minus first retained start. These are different durations."},
        "repetition": {"calculation": "repeat_events_after_first_occurrence=trace length minus number of distinct labels; adjacent_equal_activity_pairs counts neighboring equal labels in the retained trace."},
        "variants": {"calculation": "Exact ordered GT activity tuples after NA removal, ordered by start/end/event ID; adjacent equal labels are never collapsed. Frequencies sort descending, ties by lexicographic tuple.", "denominator": "retained cases"},
        "direct_follows": {"calculation": "One occurrence for each adjacent pair in a retained case; pairs may cross removed NA gaps. Same-label pairs remain included."},
        "distributions": {"calculation": "Quartile p uses linear interpolation at sorted zero-based position (n-1)*p (Hyndman-Fan type 7). Population SD=sqrt(sum((x-mean)^2)/n), not sample SD. Empty samples yield count0 and null summaries; singleton SD0.", "unit": "Named by each metric; derived statistics are floats, never replacement input scores."},
        "scores": {"calculation": "Original decimal score tokens are parsed as exact fractions. No rescaling, normalization or entropy is computed. observations.csv preserves the original scores JSON and input score strings."},
        "score_mass": {"calculation": "Retained mass=sum of three original scores. Discarded non-NA and removed-NA mass are recorded input fields. Residual=abs(retained+removedNA+discarded-1), not forcibly set to zero.", "validation_tolerances": "1e-6 for unit-mass residual;1e-12 for recorded retained mass versus exact sum. Descriptive input checks only; unrelated to exact solver certification."},
        "original_top3": {"calculation": "For each replacement, remove inserted GT and restore the recorded third label/score. Unreplaced records are already the original top3. Full original GT ranks beyond3 are recorded replacement provenance, not recoverable from three retained scores alone."},
        "top1_segment_agreement": {"calculation": "Highest original non-NA score per retained observation, with lexicographic activity tie-break; compare label with GT.", "denominator": "retained observations", "scope": "Direct recomputation on GT-aligned segments; GT insertion does not alter top1."},
        "duration_weighted_segment_agreement": {"calculation": "Sum duration of segments whose single top1 label equals GT, divided by total retained segment duration.", "denominator": "frames in retained non-NA GT segments", "scope": "This labels each entire segment with one prediction; it is NOT raw frame-prediction accuracy."},
        "upstream_frame_accuracy": {"calculation": "Ratios recomputed from recorded correct-frame/total-frame counts in model_selection.json. Per-case subtotals are verified.", "scope": "Recorded upstream predictions on117 raw cases; raw frame predictions are not included or re-evaluated by this module."},
        "ratios": {"calculation": "Numerator, denominator, exact fraction, decimal value and percent are reported; denominator0 produces null derived ratios."},
        "groups": {"calculation": "process_group is copied from each retained case record; event and frame shares are based on this retained cohort."}}
    result = {"schema_version": 1,
        "scope": "Descriptive statistics of the included GT-assisted test-cohort inputs. No held-out accuracy claim, normalization, matching run or frozen-input modification.",
        "definitions": definitions, "input_hashes": inputs,
        "population": {"raw_case_count_recorded": len(original_cases), "retained_case_count": len(cases),
            "retained_nonempty_case_count": sum(bool(events) for events in by_case.values()),
            "retained_empty_case_count": sum(not events for events in by_case.values()),
            "excluded_case_ids": omitted, "retained_observation_count": len(observations),
            "retained_candidate_count": len(raw_score_values), "frames_per_second_recorded": fps,
            "raw_case_frames_recorded": raw_frames, "retained_case_recording_frames": recording_frames,
            "retained_non_na_event_frames": retained_frames, "retained_case_uncovered_na_frames": recording_frames - retained_frames,
            "excluded_case_frames_recorded": raw_frames - recording_frames,
            "removed_na_segments_in_retained_cases": sum(r["removed_na_segments"] for r in case_rows),
            "original_segments_in_retained_cases": len(observations) + sum(r["removed_na_segments"] for r in case_rows),
            "removed_na_segments_in_all_raw_cases": None, "process_group_count": len(group_rows)},
        "ground_truth": {"activity_count": len(gt_vocabulary), "activity_vocabulary": gt_vocabulary,
            "distributions": gt_distributions, "exact_variant_count": len(variant_rows),
            "singleton_variant_count": sum(n == 1 for n in frequencies), "cases_in_singleton_variants": sum(n for n in frequencies if n == 1),
            "top_variant_case_shares": {str(k): ratio(sum(frequencies[:k]), len(cases)) for k in (1, 3, 5, 10, 20)},
            "eighty_percent_variant_coverage": {"target_cases": target, "minimum_variants_without_tie_expansion": minimum_variants,
                "cutoff_frequency": cutoff, "variants_with_cutoff_ties": sum(n >= cutoff for n in frequencies),
                "case_coverage_with_cutoff_ties": ratio(sum(n for n in frequencies if n >= cutoff), len(cases))},
            "start_activity_counts": dict(sorted(starts.items())), "end_activity_counts": dict(sorted(ends.items())),
            "distinct_direct_follow_pairs": len(transition_rows), "direct_follow_occurrences": sum(r["occurrences"] for r in transition_rows),
            "same_activity_direct_follow_occurrences": sum(r["occurrences"] for r in transition_rows if r["source_activity"] == r["target_activity"]),
            "cases_with_repetition": sum(r["repeat_events_after_first_occurrence"] > 0 for r in case_rows)},
        "uncertain": {"candidate_vocabulary": sorted(candidate_counts), "candidate_vocabulary_size": len(candidate_counts),
            "pre_insertion_candidate_vocabulary": sorted(preinsertion_candidates),
            "recorded_non_na_model_vocabulary": policy["activity_vocabulary"],
            "candidate_count_frequency": {str(k): n for k, n in sorted(Counter(e["candidate_count"] for e in observations).items())},
            "distributions": score_distributions, "gt_insertion_count": len(replacements),
            "cases_with_gt_insertion": sum(r["gt_insertions"] > 0 for r in case_rows),
            "gt_insertion_share": ratio(len(replacements), len(observations)),
            "pre_insertion_top3_gt_coverage": ratio(len(observations) - len(replacements), len(observations)),
            "post_insertion_gt_coverage": ratio(len(observations), len(observations)),
            "pre_insertion_duration_weighted_gt_coverage": ratio(sum(e["duration_frames"] for e in observations if not e["gt_inserted"]), retained_frames),
            "gt_insertions_by_group": {r["process_group"]: r["gt_insertions"] for r in group_rows},
            "gt_original_non_na_rank_frequency": {str(k): n for k, n in sorted(Counter(e["gt_original_non_na_rank"] for e in observations).items())},
            "gt_retained_rank_frequency": {str(k): n for k, n in sorted(Counter(e["gt_retained_rank"] for e in observations).items())},
            **agreement_metrics},
        "model_selection": {"selected_model": selected_model, "models_compared": len(model_ids),
            "criterion": models["selection_metric"], "tie_breaking": models["tie_breaking"],
            "recorded_selected_raw_non_na_frame_accuracy": ratio(selected["correct_non_na_frames"], selected["non_na_frames"]),
            "recorded_selected_raw_all_frame_accuracy": ratio(selected["correct_frames"], selected["frames"]),
            "recorded_selected_segment_agreement_with_na_allowed": ratio(selected["correct_non_na_segments_original"], selected["non_na_segments"]),
            "provenance": "inputs/reference/model_selection.json; recorded upstream count data, ratios and subtotals recomputed."},
        "quality": {"status": "PASS", "aligned_observations_checked": len(observations), "case_intervals_nonoverlapping": True,
            "positive_half_open_durations": True, "candidate_count_exactly_three": True, "gt_present_after_insertion": True,
            "replacement_records_checked": len(replacements), "raw_score_tokens_preserved": True,
            "score_unit_mass_tolerance": str(MASS_TOLERANCE), "reported_retained_mass_tolerance": str(RETAINED_MASS_TOLERANCE),
            "maximum_absolute_score_unit_mass_residual_exact": str(max(mass_errors, default=Fraction())),
            "maximum_absolute_score_unit_mass_residual": float(max(mass_errors, default=Fraction())),
            "maximum_reported_retained_mass_error_exact": str(max(remaining_errors, default=Fraction())),
            "maximum_reported_retained_mass_error": float(max(remaining_errors, default=Fraction())),
            "cross_checks": cross_checks}, "tables": {}}
    tables = {"cases.csv": (case_rows, "One row per retained case; trace, interval, repetition and prediction statistics."),
        "activities.csv": (activity_rows, "One row per GT or pre/post-insertion candidate activity; occurrences, coverage, durations and group breakdowns."),
        "groups.csv": (group_rows, "One row per furniture/process group in the retained cohort."),
        "variants.csv": (variant_rows, "GT case variants: ordered activity sequences, including repeated adjacent labels, with case memberships."),
        "transitions.csv": (transition_rows, "Directly adjacent retained GT activity pairs, including self pairs."),
        "observations.csv": (observations, "Aligned observations with original score tokens and reconstructed pre-insertion top3."),
        "model_comparison.csv": (model_rows, "Recorded upstream model counts and recomputed ratios; distinct from segment-weighted agreement."),
        "score_distributions.csv": (score_rows, "Original-score, mass and rank distributions; no renormalization or entropy.")}
    output.mkdir(parents=True, exist_ok=True)
    for name, (rows, description) in tables.items():
        path = output / name
        _write_csv(path, rows)
        result["tables"][name] = {"rows": len(rows), "description": description,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (output / "log_stats.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/reviewer/data")
    args = parser.parse_args()
    result = generate(ROOT, args.output)
    print(json.dumps({"status": result["quality"]["status"], "output": str(args.output.resolve()),
                      "population": result["population"], "tables": result["tables"]}, indent=2))


if __name__ == "__main__":
    main()
