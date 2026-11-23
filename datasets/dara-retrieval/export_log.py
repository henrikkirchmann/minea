#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Export the MINEA paper's DaRA retrieval ground truth from Zenodo v1."""
import argparse
import csv
import hashlib
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
ARCHIVE = "Video__Revised_Annotations.zip"
ARCHIVE_SHA256 = "6dad2ef0302c4c3b5e47c5dd1d64e262e4b1d50470594e1f556e66847ecfebfe"
# Computed independently from the fixed-ten-rule experiment's activity_labels.csv.
REFERENCE_SHA256 = "c6bd7fdfe8525726da04fe5a27df9e6a403d242aa21db430b03c11cfa9162393"
SOURCE_DOI = "https://doi.org/10.5281/zenodo.10468175"
DATA_LICENSE = "https://creativecommons.org/licenses/by-nc/4.0/"
SOURCES = dict(zip(range(155, 164), (
    "office", "cart_area", "cardboard_area", "base", "packing_area",
    "issuing_receiving", "connecting_path", "cross_aisle", "aisle",
)))
CLOCK_ORIGIN = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Run:
    session: int
    worker: str
    scenario: int
    order: str
    start: int
    end: int


def case_windows():
    with (HERE / "run_windows.csv").open(newline="", encoding="utf-8") as stream:
        runs = [Run(int(r["session"]), r["worker"], int(r["scenario"]), r["order"],
                    int(r["first_frame_1based"]) - 1, int(r["last_frame_1based"]))
                for r in csv.DictReader(stream)]
    by_worker = defaultdict(list)
    counters = Counter()
    for r in sorted(runs, key=lambda r: (r.session, r.start, r.worker)):
        counters[r.session, r.order] += 1
        execution = counters[r.session, r.order]
        case = f"session{r.session:02d}_order{r.order}_execution{execution:02d}"
        by_worker[r.worker].append((case, execution, r))
    return by_worker


class Track:
    """One video annotation per frame. Store distinct multi-label states once."""

    def __init__(self, archive, category, worker):
        member, = [n for n in archive.namelist()
                   if f"__{category}_" in n and n.endswith(f"__{worker}.csv")]
        with archive.open(member) as stream:
            header, = csv.reader([stream.readline().decode("utf-8-sig")])
            self.names = {int(key[2:]): name for key, name in (c.split("|", 1) for c in header)}
            rows = stream.read().splitlines()
        # The v1 archive uses binary CSV rows with only a handful of distinct states.
        row_ids = {row: i for i, row in enumerate(dict.fromkeys(rows))}
        self.frames = bytes(map(row_ids.__getitem__, rows))
        self.states = []
        for row in row_ids:
            flags = row.split(b",")
            if len(flags) != len(header) or any(v not in (b"0", b"1") for v in flags):
                raise ValueError(f"Invalid binary annotation in {member}")
            self.states.append(tuple(n for n, flag in zip(self.names, flags) if flag == b"1"))

    def single(self, state):
        code, = self.states[state]
        return code

    def constant_label(self, start, end):
        state = self.frames[start]
        if self.frames.count(bytes([state]), start, end) != end - start:
            raise ValueError(f"Case attribute changes between frames {start} and {end}")
        code = self.single(state)
        return code, self.names[code]


def spans(frames, start, end):
    """Maximal equal-state intervals clipped to [start, end)."""
    left = start
    for right in range(start + 1, end):
        if frames[right] != frames[left]:
            yield left, right, frames[left]
            left = right
    yield left, end, frames[left]


def zone_lookup(track):
    @lru_cache(maxsize=None)
    def lookup(state):
        codes = track.states[state]
        area, *detail = codes
        if area not in SOURCES:
            raise ValueError(f"Missing completion-area mapping for CC11 {codes}")
        if area <= 160 and not detail:
            name = track.names[area]
        elif area in (161, 162) and len(detail) == 1:
            name = track.names[detail[0]]
            if area == 162:
                name = f"Cross aisle {name}"
        elif area == 163 and len(detail) == 2:
            name = f"Aisle {track.names[detail[0]]} ({track.names[detail[1]]})"
        else:
            raise ValueError(f"Unrecognized CC11 zone {codes}")
        zone = "z" + "-".join(str(n) for n in (detail or [area]))
        return area, zone, name
    return lookup


def timestamp(session, frame):
    # Exactly 2997/100 fps. Round once to the nearest microsecond.
    us = (frame * 100_000_000 + 1498) // 2997
    value = CLOCK_ORIGIN + timedelta(days=session - 1, microseconds=us)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def extract_trace(case, execution, run, tracks, zone):
    order, tech, high, mid, low, location = (tracks[n] for n in range(6, 12))
    if not 0 <= run.start < run.end <= len(low.frames):
        raise ValueError(f"Invalid video window for {case}")
    _, order_name = order.constant_label(run.start, run.end)
    high_id, process = high.constant_label(run.start, run.end)
    tech_id, technology = tech.constant_label(run.start, run.end)
    if order_name != run.order or high_id != 110:
        raise ValueError(f"CC06 order / CC08 retrieval disagree with documented run {case}")
    trace = {
        "concept:name": case, "dara:session": run.session, "dara:worker": run.worker,
        "dara:scenario": run.scenario, "dara:order_id": run.order, "dara:execution": execution,
        "dara:process_id": f"CL{high_id}", "dara:process": process,
        "dara:technology_id": f"CL{tech_id}", "dara:technology": technology,
        "dara:run_start_frame": run.start, "dara:run_end_frame": run.end,
    }
    events = []
    for index, (a, b, state) in enumerate(spans(low.frames, run.start, run.end), 1):
        activity = low.single(state)
        stage = mid.single(mid.frames[b - 1])
        first_area, first_zone, first_name = zone(location.frames[a])
        last_area, last_zone, last_name = zone(location.frames[b - 1])
        stage_path = " ".join(f"CL{mid.single(s)}@{lo - a}" for lo, _, s in spans(mid.frames, a, b))
        zone_path = " ".join(f"{zone(s)[1]}@{lo - a}" for lo, _, s in spans(location.frames, a, b))
        events.append({
            "concept:name": low.names[activity], "dara:activity_id": f"CL{activity}",
            "dara:observation_id": f"{case}__activation{index:04d}", "dara:event_index": index,
            "start_timestamp": timestamp(run.session, a), "time:timestamp": timestamp(run.session, b),
            "lifecycle:transition": "complete", "org:resource": run.worker,
            "dara:start_frame": a, "dara:end_frame": b, "dara:duration_s": round((b-a)*100/2997, 6),
            "dara:stage_id": f"CL{stage}", "dara:stage": mid.names[stage], "dara:stage_path": stage_path,
            "dara:area_start_id": f"CL{first_area}", "dara:area_start": location.names[first_area],
            "dara:area_end_id": f"CL{last_area}", "dara:area_end": location.names[last_area],
            "dara:zone_start_id": first_zone, "dara:zone_start": first_name,
            "dara:zone_end_id": last_zone, "dara:zone_end": last_name,
            "dara:zone_path": zone_path, "dara:source": SOURCES[last_area],
        })
    return trace, events


def extract(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError(f"{path} differs from the pinned DaRA v1 annotation ZIP")
    traces = []
    with ZipFile(path) as archive:
        for worker, runs in sorted(case_windows().items()):
            tracks = {i: Track(archive, f"CC{i:02d}", worker) for i in range(6, 12)}
            if len({len(t.frames) for t in tracks.values()}) != 1:
                raise ValueError(f"Frame counts disagree for {worker}")
            zone = zone_lookup(tracks[11])
            for case, execution, run in runs:
                traces.append(extract_trace(case, execution, run, tracks, zone))
    traces.sort(key=lambda pair: pair[0]["concept:name"])
    return traces


def verify_reference(traces):
    digest = hashlib.sha256()
    for _, events in traces:
        for e in events:
            fields = [e[k] for k in ("dara:observation_id", "dara:start_frame", "dara:end_frame",
                                     "dara:activity_id", "dara:source")]
            digest.update(("\t".join(map(str, fields)) + "\n").encode("utf-8"))
    if digest.hexdigest() != REFERENCE_SHA256:
        raise ValueError("IDs, frames, activities or sources differ from the paper reference")


def write_csv(traces, path):
    trace, events = traces[0]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["case:" + k for k in trace] + list(events[0]),
                                lineterminator="\n")
        writer.writeheader()
        for trace, events in traces:
            case = {"case:" + k: v for k, v in trace.items()}
            writer.writerows({**case, **e} for e in events)


def attributes(node, values):
    for key, value in values.items():
        if key in ("time:timestamp", "start_timestamp"):
            kind = "date"
        elif isinstance(value, int):
            kind = "int"
        elif isinstance(value, float):
            kind = "float"
        else:
            kind = "string"
        ET.SubElement(node, kind, key=key, value=str(value))


def write_xes(traces, path):
    root = ET.Element("log", {"xmlns": "http://www.xes-standard.org/", "xes.version": "1.0",
                              "xes.features": "nested-attributes"})
    for name, prefix in [("Concept", "concept"), ("Time", "time"), ("Organizational", "org"),
                         ("Lifecycle", "lifecycle")]:
        ET.SubElement(root, "extension", name=name, prefix=prefix,
                      uri=f"http://www.xes-standard.org/{name.lower()}.xesext")
    ET.SubElement(root, "classifier", name="Activity", keys="concept:name")
    attributes(root, {"concept:name": "DaRA single-order retrieval ground truth",
                      "lifecycle:model": "standard", "dara:dataset": SOURCE_DOI,
                      "dara:attribution": "Niemann et al. (2026), DaRA v1; MINEA retrieval interval export.",
                      "dara:license": DATA_LICENSE,
                      "dara:clock": "Synthetic UTC origin 1970-01-01 plus session-1 days; video at 29.97 fps."})
    for trace, events in traces:
        node = ET.SubElement(root, "trace")
        attributes(node, trace)
        for e in events:
            attributes(ET.SubElement(node, "event"), e)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=HERE/"raw",
                        help=f"directory containing {ARCHIVE} (default: raw/ beside script)")
    parser.add_argument("--output-dir", type=Path, default=HERE/"logs",
                        help="destination for both log formats (default: logs/ beside script)")
    args = parser.parse_args()
    source = args.input_dir / ARCHIVE
    if not source.is_file():
        parser.error(f"Download {ARCHIVE} from {SOURCE_DOI} and place it at {source}")
    traces = extract(source)
    verify_reference(traces)
    dest = args.output_dir
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        files = []
        for suffix, write in (("csv", write_csv), ("xes", write_xes)):
            path = Path(tmp) / f"dara_retrieval_gt.{suffix}"
            write(traces, path)
            files.append(path)
        for path in files:
            path.replace(dest/path.name)
    print(f"Verified {len(traces)} cases and {sum(len(e) for _, e in traces):,} events. Logs in {dest}")


if __name__ == "__main__":
    main()
