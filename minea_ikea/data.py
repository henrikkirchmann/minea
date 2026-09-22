"""Pinned upstream inputs, exact frame-accuracy counts, and aligned log preparation.

Upstream endpoints are INCLUSIVE frame indices. Internally intervals are
[start_frame, end_frame_exclusive), in each video's own frame clock.
"""

from __future__ import annotations

from collections import defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_inputs(root, upstream_dir=None, offline=False):
    """Copy or download exactly the files in source_manifest.json; verify all hashes."""
    root = Path(root)
    manifest = json.loads((root / "source_manifest.json").read_text())
    cache = root / "data" / "upstream"
    for item in manifest["files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe manifest path")
        target = cache / relative
        if target.exists():
            if sha256(target) != item["sha256"]:
                raise ValueError(f"Input checksum mismatch: {target}. Remove it and fetch again.")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as out:
            partial = Path(out.name)
            try:
                if upstream_dir is not None:
                    with (Path(upstream_dir) / relative).open("rb") as source:
                        shutil.copyfileobj(source, out)
                elif offline:
                    raise FileNotFoundError(f"Missing cached input: {relative}; fetch once without --offline.")
                else:
                    url = ("https://raw.githubusercontent.com/henrikkirchmann/"
                           f"IKEA_ASM_UncertainEventLogs/{manifest['commit']}/{relative.as_posix()}")
                    print(f"Downloading {relative.name}", flush=True)
                    with urlopen(Request(url, headers={"User-Agent": "minea-ikea-evaluation/0.1"}), timeout=120) as source:
                        shutil.copyfileobj(source, out)
                out.flush()
                if sha256(partial) != item["sha256"]:
                    raise ValueError(f"Downloaded/copied file has wrong checksum: {relative}")
                partial.replace(target)
            finally:
                partial.unlink(missing_ok=True)
    return manifest, cache


def read_segments(path, kind="gt"):
    """Read segment CSV, rejecting missing frames, inconsistent labels or score vectors."""
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    rows = []
    label_key = "gt_label_name" if kind == "gt" else "pred_label_name"
    fields = {"case_id", "case_name", "start_timestamp", "end_timestamp", "duration_frames", label_key}
    if kind == "gt":
        fields.add("avg_probs_json")
    with opener(path, "rt", newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not fields.issubset(reader.fieldnames or []):
            raise ValueError(f"Missing fields in {path.name}: {fields - set(reader.fieldnames or [])}")
        labels = None
        for line, raw in enumerate(reader, start=2):
            start, last, duration = (int(raw[k]) for k in ("start_timestamp", "end_timestamp", "duration_frames"))
            if start < 0 or last < start or duration != last - start + 1:
                raise ValueError(f"Invalid inclusive frame interval at {path.name}:{line}")
            row = {"case_id": str(raw["case_id"]), "case_name": raw["case_name"],
                   "start_frame": start, "end_frame_exclusive": last + 1,
                   "duration_frames": duration, "activity": raw[label_key]}
            if not row["case_id"] or not row["case_name"] or not row["activity"]:
                raise ValueError(f"Empty identity/label at {path.name}:{line}")
            if kind == "gt" or raw.get("avg_probs_json"):
                scores = json.loads(raw["avg_probs_json"])
                if not isinstance(scores, dict) or not scores:
                    raise ValueError("Probability vector must be a nonempty object")
                if labels is None:
                    labels = list(scores)
                if list(scores) != labels or "NA" not in scores or row["activity"] not in scores:
                    raise ValueError(f"Inconsistent activity vector at {path.name}:{line}")
                if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)
                       or v < 0 or v > 1.00001 for v in scores.values()):
                    raise ValueError(f"Invalid probability at {path.name}:{line}")
                if not math.isclose(sum(scores.values()), 1.0, abs_tol=1e-5):
                    raise ValueError(f"Probability mass differs from one at {path.name}:{line}")
                if "pred_label_name" in raw and max(scores, key=scores.get) != raw["pred_label_name"]:
                    raise ValueError(f"Stored top label disagrees with averaged scores at {path.name}:{line}")
                row["scores"] = scores
            rows.append(row)
    validate_complete_intervals(rows)
    return rows


def group_cases(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["case_id"]].append(row)
    return {case: sorted(events, key=lambda e: e["start_frame"]) for case, events in sorted(grouped.items())}


def validate_complete_intervals(rows):
    if not rows:
        raise ValueError("Empty upstream log")
    for case, events in group_cases(rows).items():
        end = 0
        name = events[0]["case_name"]
        for row in events:
            if row["case_name"] != name or row["start_frame"] != end:
                raise ValueError(f"Gap, overlap, duplicate, or inconsistent name in case {case}")
            end = row["end_frame_exclusive"]


def annotation_identity(rows):
    return [(r["case_id"], r["case_name"], r["start_frame"], r["end_frame_exclusive"], r["activity"])
            for case, events in group_cases(rows).items() for r in events]


def frame_accuracy(gt_rows, predicted_rows):
    """Count integer interval intersections; equivalent to comparing every frame label.

Pred-merged segments have CONSTANT original per-frame argmax labels. Their
averaged probabilities are not used here. Accuracy of argmax(segment mean)
would be a different statistic and cannot reconstruct per-frame accuracy.
"""
    gt, pred = group_cases(gt_rows), group_cases(predicted_rows)
    if set(gt) != set(pred):
        raise ValueError("Prediction and GT case sets differ")
    counts = dict(frames=0, correct_frames=0, non_na_frames=0, correct_non_na_frames=0)
    per_case = []
    for case in gt:
        a, b = gt[case], pred[case]
        if a[0]["case_name"] != b[0]["case_name"] or a[-1]["end_frame_exclusive"] != b[-1]["end_frame_exclusive"]:
            raise ValueError(f"Prediction and GT clocks/names differ for case {case}")
        local = dict.fromkeys(counts, 0)
        i = j = 0
        while i < len(a) and j < len(b):
            lo = max(a[i]["start_frame"], b[j]["start_frame"])
            hi = min(a[i]["end_frame_exclusive"], b[j]["end_frame_exclusive"])
            overlap = max(0, hi - lo)
            correct = a[i]["activity"] == b[j]["activity"]
            local["frames"] += overlap
            local["correct_frames"] += overlap * correct
            if a[i]["activity"] != "NA":
                local["non_na_frames"] += overlap
                local["correct_non_na_frames"] += overlap * correct
            a_end, b_end = a[i]["end_frame_exclusive"], b[j]["end_frame_exclusive"]
            i += a_end <= b_end
            j += b_end <= a_end
        if local["frames"] != a[-1]["end_frame_exclusive"]:
            raise ValueError(f"Incomplete intersection coverage for {case}")
        for key, value in local.items():
            counts[key] += value
        per_case.append({"case_id": case, **local})
    if not counts["non_na_frames"]:
        raise ValueError("No non-NA frames for model selection")
    return {**counts, "accuracy_all_frames": counts["correct_frames"] / counts["frames"],
            "accuracy_non_na_frames": counts["correct_non_na_frames"] / counts["non_na_frames"],
            "per_case": per_case}


def audit_models(manifest, cache):
    """Verify all models share the same GT; return both exact-count rankings and data."""
    files = manifest["files"]
    models = sorted({item["model_id"] for item in files if "model_id" in item})
    loaded, leaderboard, reference = {}, [], None
    for model in models:
        paths = {item["role"]: cache / item["path"] for item in files if item.get("model_id") == model}
        gt = read_segments(paths["gt_aligned"], "gt")
        pred = read_segments(paths["pred_merged"], "pred")
        identity = annotation_identity(gt)
        if reference is not None and identity != reference:
            raise ValueError(f"GT annotations differ for model {model}")
        reference = identity
        accuracy = frame_accuracy(gt, pred)
        conservation_error = score_conservation_error(gt, pred)
        non_na = [row for row in gt if row["activity"] != "NA"]
        segment_correct = sum(max(row["scores"], key=row["scores"].get) == row["activity"] for row in non_na)
        def non_na_top(row):
            return max((label for label in row["scores"] if label != "NA"), key=row["scores"].get)
        segment_correct_removed = sum(non_na_top(row) == row["activity"] for row in non_na)
        leaderboard.append({"model_id": model, **accuracy, "max_score_conservation_error": conservation_error,
                            "non_na_segments": len(non_na), "correct_non_na_segments_original": segment_correct,
                            "correct_non_na_segments_after_na_removal": segment_correct_removed,
                            "accuracy_non_na_segments_original": segment_correct / len(non_na),
                            "accuracy_non_na_segments_after_na_removal": segment_correct_removed / len(non_na)})
        loaded[model] = gt
    return leaderboard, loaded


def score_conservation_error(gt_rows, predicted_rows):
    """Compare duration-weighted score totals under two segmentations of each case.

This is an aggregate consistency check, not reconstruction of individual
frame probabilities. All labels, including NA, are included before filtering.
"""
    largest = 0.0
    gt, pred = group_cases(gt_rows), group_cases(predicted_rows)
    for case, events in gt.items():
        labels = list(events[0]["scores"])
        if any(list(event["scores"]) != labels for event in pred[case]):
            raise ValueError(f"Prediction score labels differ in case {case}")
        for label in labels:
            a = math.fsum(event["duration_frames"] * event["scores"][label] for event in events)
            b = math.fsum(event["duration_frames"] * event["scores"][label] for event in pred[case])
            largest = max(largest, abs(a - b))
            if not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-7):
                raise ValueError(f"Probability mass conservation failed for case {case}, {label}")
    return largest


def choose_model(leaderboard, accuracy_scope="non_na", model_id=None):
    if model_id is not None:
        if model_id not in {row["model_id"] for row in leaderboard}:
            raise ValueError(f"Unknown model: {model_id}")
        return model_id
    if accuracy_scope not in {"non_na", "all"}:
        raise ValueError("accuracy_scope must be non_na or all")
    # Denominators are identical across models, verified by audit_models.
    key = "correct_non_na_frames" if accuracy_scope == "non_na" else "correct_frames"
    return sorted(leaderboard, key=lambda row: (-row[key], row["model_id"]))[0]["model_id"]


def prepare_logs(gt_rows, top_k=3, candidate_policy="top-k-gt"):
    """Keep top-k non-NA scores, optionally replacing the last candidate with GT.

    Ties are broken by lexicographic activity name. GT-NA observations are
    removed without resegmenting; the full case roster remains explicit.
    Under top-k-gt, a missing GT label replaces the lowest-ranked retained
    label, with its original model score. Scores are never renormalized.
    """
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise ValueError("top_k must be a positive integer")
    if candidate_policy not in {"top-k", "top-k-gt"}:
        raise ValueError("candidate_policy must be top-k or top-k-gt")
    events, uncertain, cases = [], [], []
    for case, rows in group_cases(gt_rows).items():
        cases.append({"case_id": case, "case_name": rows[0]["case_name"],
                      "process_group": rows[0]["case_name"].split("/")[0],
                      "total_frames": rows[-1]["end_frame_exclusive"],
                      "removed_na_segments": sum(row["activity"] == "NA" for row in rows)})
        for row in rows:
            if row["activity"] == "NA":
                continue
            event_id = f"case{case}:frames{row['start_frame']}-{row['end_frame_exclusive']}"
            common = {key: row[key] for key in ("case_id", "case_name", "start_frame", "end_frame_exclusive", "duration_frames")}
            common["event_id"] = event_id
            ranked = sorted((label for label in row["scores"] if label != "NA"),
                            key=lambda label: (-row["scores"][label], label))
            retained = ranked[:top_k]
            if candidate_policy == "top-k-gt" and row["activity"] not in retained:
                if row["activity"] not in ranked:
                    raise ValueError("GT activity is absent from the original model score vocabulary")
                retained[-1] = row["activity"]
            scores = {label: row["scores"][label] for label in retained}
            discarded = sum(row["scores"][label] for label in ranked if label not in scores)
            events.append({**common, "activity": row["activity"]})
            uncertain.append({**common, "scores": scores, "removed_na_score": row["scores"]["NA"],
                              "discarded_non_na_score_mass": discarded,
                              "remaining_score_mass": sum(scores.values()),
                              "top_activity": max(scores, key=scores.get)})
    return events, uncertain, cases


def verify_reference_xes(path, events, cases):
    """Cross-check the upstream certain log using integer attributes, not its date encoding."""
    root = ET.parse(path).getroot()
    ns = {"x": "http://www.xes-standard.org/"}
    expected = {(e["case_id"], e["start_frame"], e["end_frame_exclusive"], e["activity"]) for e in events}
    actual, seen_cases, event_count = set(), set(), 0
    for trace in root.findall("x:trace", ns):
        attrs = {e.get("key"): e.get("value") for e in trace if e.tag.endswith("string")}
        case = attrs["concept:name"]
        if case in seen_cases:
            raise ValueError("Duplicate trace in reference XES")
        seen_cases.add(case)
        for event in trace.findall("x:event", ns):
            vals = {e.get("key"): e.get("value") for e in event}
            actual.add((case, int(vals["segment:start_timestamp"]), int(vals["segment:end_timestamp"]) + 1,
                        vals["concept:name"]))
            event_count += 1
    nonempty_cases = {e["case_id"] for e in events}
    if actual != expected or event_count != len(expected) or seen_cases != nonempty_cases:
        raise ValueError("GT-aligned CSV does not match the independent upstream no-NA XES export")
    return {"status": "PASS", "nonempty_cases": len(seen_cases), "events": event_count,
            "empty_cases_omitted_from_upstream_xes": sorted({c["case_id"] for c in cases} - seen_cases),
            "scope": "Consistency of two upstream exports; not independent reannotation of videos."}
