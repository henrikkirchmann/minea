"""Deterministic, import-friendly event-log views of the frozen observations.

``generate(root, output)`` writes CSV and XES interchange views, a
usage note, a portable ZIP and a source-comparison manifest. It performs no
candidate selection, score conversion, preparation, optimization or matching.
Only the standard library is needed.
"""

import csv
from datetime import datetime, timedelta
from decimal import Decimal
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile


EPOCH = datetime(1970, 1, 1)
FRAME_MILLISECONDS = 40
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
COMMON_FIELDS = ("case:concept:name", "concept:name", "start_timestamp", "time:timestamp",
                 "lifecycle:transition", "event_id", "case_name", "duration_seconds",
                 "start_frame", "end_frame_exclusive", "duration_frames")
SCORE_MASS_FIELDS = ("removed_na_score", "discarded_non_na_score_mass", "remaining_score_mass")
SCORE_FIELDS = ("probs_json",) + SCORE_MASS_FIELDS
IDENTITY_FIELDS = ("case_id", "event_id", "case_name", "start_frame", "end_frame_exclusive", "duration_frames")
NS = "http://www.xes-standard.org/"
USAGE = """IKEA ASM event-log downloads

Each log contains the same 1,856 observations in 116 cases, after removal of
GT-NA segments. One case is one assembly recording. An observation is one
GT-aligned activity segment, not one video frame.

Files
  ground_truth.xes / ground_truth.csv: reference (GT) activity per observation.
  uncertain_log.xes.gz / uncertain_log.csv: the same uncertain log in two
    formats. The activity is the highest-scoring candidate; all three
    candidate scores remain in the probs_json event attribute. A conventional
    activity-based analysis sees the highest-score view, not solved matching.

Fields are already mapped
  Case: trace concept:name in XES; case:concept:name in CSV / PM4Py data frames.
  Activity: event concept:name (GT or highest-scoring candidate).
  Completion: time:timestamp, at the exclusive segment end.
  Start: start_timestamp, the PM4Py interval convention (additional XES date
    attribute, not a standard XES Time-extension attribute).
  Lifecycle: lifecycle:transition = complete; one event per observation.
  Scores: probs_json, a JSON string mapping candidate activity names to their
    original scores. This reuses the payload name from our earlier repository.
  Other attributes: event_id, frame boundaries, duration, case name and
    score-mass bookkeeping. The uncertain files have no separate GT label.

XES records case, activity and timestamp roles explicitly, so XES importers
do not need manual column mapping. CSV uses the default PM4Py column names;
other CSV importers may still ask users to confirm their roles.

PM4Py example (run in the extracted download folder; requires pm4py)
  import json
  import pm4py
  log = pm4py.read_xes("uncertain_log.xes.gz")
  candidates = json.loads(log.iloc[0]["probs_json"])

Alternatively, load either CSV without custom column mappings:
  import pandas as pd
  log = pm4py.format_dataframe(pd.read_csv("uncertain_log.csv"))
  candidates = json.loads(log.iloc[0]["probs_json"])

probs_json preserves the prepared score text without rounding or
renormalization. Ordinary process-mining algorithms use concept:name;
uncertainty-aware analysis must explicitly read the score payload.
The prepared inputs use GT segmentation and GT-assisted candidate retention;
these logs are not an unassisted recognition evaluation.

Timing
Both formats use a synthetic 1970-01-01 UTC origin and 25 frames/second:
each frame equals exactly 40 milliseconds. end_frame_exclusive is the first
frame outside the segment, and time:timestamp uses that exclusive endpoint.
duration_seconds equals (end_frame_exclusive - start_frame) / 25 exactly.
Clocks are relative to each recording. Equal dates across cases do not show
actual concurrency or shared-resource use between recordings.

Download representation versus frozen experiment inputs
The frozen XES stores the segment start in time:timestamp, its end in the
custom time:end_timestamp, and scores in scores_json. These downloads map
the SAME intervals to start_timestamp / time:timestamp (completion), and
rename the payload to probs_json. Frozen experiment files are not changed.
The original retained score values, activity labels, cases and observations
are unchanged. No preparation, rule mining or matching is rerun.

PM4Py field conventions:
https://processintelligence.solutions/app/static/api/2.7.17/api/pm4py.utils.html
PM4Py XES import:
https://github.com/process-intelligence-solutions/pm4py/blob/release/docs/source/api.rst
"""


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _digest(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _read_csv(raw, compressed=False):
    text = (gzip.decompress(raw) if compressed else raw).decode("utf-8")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    return list(reader), reader.fieldnames


def _timestamp(frame):
    value = EPOCH + timedelta(milliseconds=int(frame) * FRAME_MILLISECONDS)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _csv_view(rows, activity_field, uncertain=False):
    fields = COMMON_FIELDS + (SCORE_FIELDS if uncertain else ())
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fields, lineterminator="\n")
    writer.writeheader()
    for source in rows:
        milliseconds = int(source["duration_frames"]) * FRAME_MILLISECONDS
        seconds, remainder = divmod(milliseconds, 1000)
        row = {key: source[key] for key in IDENTITY_FIELDS if key != "case_id"}
        row.update({"case:concept:name": source["case_id"], "concept:name": source[activity_field],
                    "start_timestamp": _timestamp(source["start_frame"]),
                    "time:timestamp": _timestamp(source["end_frame_exclusive"]),
                    "lifecycle:transition": "complete", "duration_seconds": f"{seconds}.{remainder:03d}"})
        if uncertain:
            row["probs_json"] = source["scores"]
            row.update({key: source[key] for key in SCORE_MASS_FIELDS})
        writer.writerow(row)
    return stream.getvalue().encode("utf-8")


def _validate_csv(raw, source, activity_field, uncertain=False):
    """Read exported text back; check time differences with integer microseconds."""
    rows, fields = _read_csv(raw)
    _require(fields == list(COMMON_FIELDS + (SCORE_FIELDS if uncertain else ())), "Unexpected export columns")
    _require(len(rows) == len(source) == 1856, "Expected 1,856 exported observation rows")
    _require(len({r["case:concept:name"] for r in rows}) == 116, "Expected 116 exported cases")
    _require(len({r["event_id"] for r in rows}) == 1856, "Duplicate exported event ID")
    for exported, original in zip(rows, source):
        _require(exported["case:concept:name"] == original["case_id"] and
                 all(exported[key] == original[key] for key in IDENTITY_FIELDS if key != "case_id"),
                 "Observation identity or order changed")
        _require(exported["concept:name"] == original[activity_field] and exported["concept:name"] != "NA", "Activity changed or is NA")
        _require(exported["lifecycle:transition"] == "complete", "Expected one completed event per observation")
        start, end, duration = (int(original[key]) for key in ("start_frame", "end_frame_exclusive", "duration_frames"))
        _require(0 <= start < end and end - start == duration, "Invalid source frame interval")
        for key, frame in (("start_timestamp", start), ("time:timestamp", end)):
            _require(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", exported[key]) is not None,
                     "Unexpected timestamp format")
            elapsed = datetime.fromisoformat(exported[key][:-1]) - datetime(1970, 1, 1)
            microseconds = (elapsed.days * 86400 + elapsed.seconds) * 1000000 + elapsed.microseconds
            _require(microseconds == frame * 1000000 // 25, "Incorrect frame-to-date conversion")
        _require(Decimal(exported["duration_seconds"]) * 25 == duration, "Incorrect duration conversion")
        if uncertain:
            _require(exported["probs_json"] == original["scores"] and
                     all(exported[key] == original[key] for key in SCORE_MASS_FIELDS), "Original score text changed")
            scores = json.loads(exported["probs_json"], parse_float=Decimal, parse_int=Decimal)
            _require(len(scores) == 3 and "NA" not in scores, "Expected three non-NA candidates")
            _require(all(value.is_finite() and value >= 0 for value in scores.values()), "Invalid candidate score")
            _require(exported["concept:name"] == min(scores, key=lambda label: (-scores[label], label)),
                     "Recorded top activity differs from exact score ordering")
    return {"event_rows": len(rows), "case_count": len({r["case:concept:name"] for r in rows}),
            "unique_event_ids": 1856, "source_order_and_identity_preserved": True,
            "labels_match_source_field": activity_field, "NA_activity_count": 0,
            "all_frame_date_and_duration_conversions_exact": True,
            "score_text_unchanged": True if uncertain else None,
            "no_GT_label_column": True if uncertain else None}


def _xes_view(raw, compressed=False):
    """Map existing observation intervals to completion events; preserve payloads."""
    ET.register_namespace("", NS)
    log = ET.fromstring(gzip.decompress(raw) if compressed else raw)
    extension = ET.Element(f"{{{NS}}}extension", name="Lifecycle", prefix="lifecycle",
                           uri="http://www.xes-standard.org/lifecycle.xesext")
    log.insert(2, extension)
    metadata = ET.Element(f"{{{NS}}}string", key="download_time_semantics",
                          value="One completion event per observation; time:timestamp=end exclusive; start_timestamp=start (PM4Py interval convention).")
    first_trace = next(index for index, child in enumerate(log) if child.tag == f"{{{NS}}}trace")
    log.insert(first_trace, metadata)
    for event in log.findall(f"{{{NS}}}trace/{{{NS}}}event"):
        attrs = {item.get("key"): item for item in event}
        start, end = attrs["time:timestamp"], attrs["time:end_timestamp"]
        start.set("key", "start_timestamp")
        end.set("key", "time:timestamp")
        ET.SubElement(event, f"{{{NS}}}string", key="lifecycle:transition", value="complete")
        if "scores_json" in attrs:
            attrs["scores_json"].set("key", "probs_json")
    ET.indent(log, space="  ")
    content = ET.tostring(log, encoding="utf-8", xml_declaration=True)
    return gzip.compress(content, mtime=0) if compressed else content


def _validate_xes(raw, source, activity_field, compressed=False):
    ns = "{http://www.xes-standard.org/}"
    log = ET.fromstring(gzip.decompress(raw) if compressed else raw)
    by_id = {row["event_id"]: row for row in source}
    cases, seen = set(), set()
    for trace in log.findall(f"{ns}trace"):
        attributes = {item.get("key"): item.get("value") for item in trace if item.tag != f"{ns}event"}
        case = attributes["concept:name"]
        _require(case not in cases, "Repeated XES case trace")
        cases.add(case)
        for event in trace.findall(f"{ns}event"):
            values = {item.get("key"): item.get("value") for item in event}
            identifier = values["event_id"]
            _require(identifier not in seen and identifier in by_id, "Repeated or unknown XES event")
            seen.add(identifier)
            original = by_id[identifier]
            _require(case == original["case_id"] and attributes["case:name"] == original["case_name"], "XES case identity differs")
            _require(values["concept:name"] == original[activity_field], "XES activity differs")
            _require(all(values[key] == original[key] for key in ("start_frame", "end_frame_exclusive", "duration_frames")),
                     "XES frame fields differ")
            _require(values["start_timestamp"] == _timestamp(original["start_frame"]) and
                     values["time:timestamp"] == _timestamp(original["end_frame_exclusive"]), "XES interval differs")
            _require(values["lifecycle:transition"] == "complete", "XES lifecycle differs")
            _require("time:end_timestamp" not in values and "scores_json" not in values, "Unmapped XES field")
            if activity_field == "top_activity":
                _require(values["probs_json"] == original["scores"], "XES score text differs")
                _require(all(values[key] == original[key] for key in SCORE_MASS_FIELDS), "XES score mass differs")
    _require(seen == set(by_id) and len(cases) == 116, "XES population differs from CSV")
    return {"event_rows": len(seen), "case_count": len(cases), "identity_labels_and_frames_match_source_CSV": True,
            "timestamps_match_source_intervals": True, "scores_payload_matches_source": activity_field == "top_activity"}


def _zip_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, files[name])
    return stream.getvalue()


def generate(root, output):
    """Create downloads and return the deterministic manifest (no machine paths)."""
    root, output = Path(root).resolve(), Path(output).resolve()
    folder = root / "inputs/reference/full"
    names = ("ground_truth.csv", "uncertain_log.csv.gz", "ground_truth.xes", "uncertain_log.xes.gz")
    inputs = {f"inputs/reference/full/{name}": (folder / name).read_bytes() for name in names}
    protocol_name = "inputs/reference/protocol.json"
    inputs[protocol_name] = (root / protocol_name).read_bytes()
    _require(json.loads(inputs[protocol_name])["frames_per_second"] == 25, "Frozen inputs must specify 25 fps")
    gt, _ = _read_csv(inputs["inputs/reference/full/ground_truth.csv"])
    uncertain, _ = _read_csv(inputs["inputs/reference/full/uncertain_log.csv.gz"], compressed=True)
    _require([{key: row[key] for key in IDENTITY_FIELDS} for row in gt] ==
             [{key: row[key] for key in IDENTITY_FIELDS} for row in uncertain], "GT and uncertain observation populations differ")
    payloads = {
        "ground_truth.csv": _csv_view(gt, "activity"),
        "uncertain_log.csv": _csv_view(uncertain, "top_activity", uncertain=True),
        "ground_truth.xes": _xes_view(inputs["inputs/reference/full/ground_truth.xes"]),
        "uncertain_log.xes.gz": _xes_view(inputs["inputs/reference/full/uncertain_log.xes.gz"], compressed=True),
        "USAGE.txt": USAGE.encode("utf-8"),
    }
    checks = {
        "ground_truth.csv": _validate_csv(payloads["ground_truth.csv"], gt, "activity"),
        "uncertain_log.csv": _validate_csv(payloads["uncertain_log.csv"], uncertain, "top_activity", uncertain=True),
        "ground_truth.xes": _validate_xes(payloads["ground_truth.xes"], gt, "activity"),
        "uncertain_log.xes.gz": _validate_xes(payloads["uncertain_log.xes.gz"], uncertain, "top_activity", compressed=True),
    }
    archive_members = sorted(payloads)
    payloads["ikea-asm-event-logs.zip"] = _zip_bytes(payloads)
    with zipfile.ZipFile(io.BytesIO(payloads["ikea-asm-event-logs.zip"])) as archive:
        _require(archive.namelist() == archive_members, "Unexpected archive member order")
        for info in archive.infolist():
            _require(info.date_time == ZIP_DATE and archive.read(info.filename) == payloads[info.filename],
                     "Archive member bytes or metadata differ")
    roles = {"ground_truth.csv": "GT events with standard case/activity/completion columns and PM4Py start_timestamp.",
             "uncertain_log.csv": "Uncertain events with score-argmax activity and original probs_json payload, no GT label column.",
             "ground_truth.xes": "GT XES with standard case/activity/completion attributes and PM4Py start_timestamp.",
             "uncertain_log.xes.gz": "Uncertain XES with score-argmax activity and original scores as probs_json payload.",
             "USAGE.txt": "Import mapping, file roles, duration and case-relative-clock explanations.",
             "ikea-asm-event-logs.zip": "Portable bundle of both CSVs, both XES files, and USAGE.txt."}
    manifest = {"schema_version": 2, "producer": {"file": "reviewer/event_logs.py", **_digest(Path(__file__).read_bytes())},
        "input_files": {name: _digest(raw) for name, raw in sorted(inputs.items())},
        "output_files": {name: {**_digest(raw), "role": roles[name], **checks.get(name, {})}
                         for name, raw in sorted(payloads.items())},
        "timing": {"frames_per_second": 25, "milliseconds_per_frame": 40,
                   "synthetic_epoch": "1970-01-01T00:00:00.000Z", "timestamp_format": "ISO 8601 UTC, millisecond precision",
                   "start_attribute": "start_timestamp", "completion_attribute": "time:timestamp",
                   "end_semantics": "exclusive", "scope": "Separate case-relative recording clocks; no observed intercase concurrency."},
        "attribute_mapping": {"case_XES_trace": "concept:name", "case_CSV": "case:concept:name",
                              "activity": "concept:name", "score_payload": "probs_json",
                              "lifecycle:transition": "complete", "start_timestamp": "PM4Py convention; additional XES date attribute"},
        "download_adaptation": "Map frozen XES start time:timestamp to start_timestamp, end time:end_timestamp to completion time:timestamp, and scores_json to probs_json. No observation or score changes.",
        "validation": {"status": "PASS", "events_per_log": 1856, "cases_per_log": 116,
                       "GT_and_uncertain_observation_identity_equal": True, "all_CSV_rows_compared_to_source": True,
                       "XES_observations_intervals_and_scores_preserved": True, "ZIP_member_bytes_checked": True,
                       "no_matching_or_data_preparation_run": True,
                       "scope": "Source/export comparison and format checks. Consumer import checks are recorded separately in provenance/."},
        "zip": {"members": archive_members, "member_date": "1980-01-01 00:00:00",
                "compression": "stored; avoids compressor-version variation", "permissions": "0644"}}
    output.mkdir(parents=True, exist_ok=True)
    for name, raw in payloads.items():
        (output / name).write_bytes(raw)
        _require((output / name).read_bytes() == raw, f"Saved download bytes differ: {name}")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return manifest
