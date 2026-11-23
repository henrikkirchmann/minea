"""Verify the paper's recorded coordination statistics and optionally compare a fresh run."""

import argparse
import csv
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from statistics import median


HERE = Path(__file__).resolve().parent
COUNTERS = (
    "visited_nodes", "queried_nodes", "source_cache_misses",
    "compared_tied_bounds", "private_handle_comparisons",
)


@dataclass
class Measurement:
    counts: dict
    seconds: float


def load(path):
    measurements = {}
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        missing = {"case", "seconds", *COUNTERS}.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path} is missing columns {sorted(missing)}")
        for row in reader:
            case = row["case"]
            if not case or case in measurements:
                raise ValueError(f"{path}, line {reader.line_num}: missing or duplicate case {case!r}")
            counts = {key: int(row[key]) for key in COUNTERS}
            seconds = float(row["seconds"])
            if min(counts.values()) < 0 or not isfinite(seconds) or seconds < 0:
                raise ValueError(f"{path}, {case}: invalid counter or elapsed time")
            measurements[case] = Measurement(counts, seconds)
    if not measurements:
        raise ValueError(f"{path} contains no case measurements")
    return measurements


def summary(data):
    slowest = max(data, key=lambda case: data[case].seconds)
    return {
        "cases": len(data),
        "median rounds": median(m.counts["queried_nodes"] for m in data.values()),
        "median local solves": median(m.counts["source_cache_misses"] for m in data.values()),
        "median seconds": round(median(m.seconds for m in data.values()), 3),
        "orders under one second": sum(m.seconds < 1 for m in data.values()),
        "slowest order": slowest,
        "slowest seconds": round(data[slowest].seconds, 3),
        "local solves for slowest order": data[slowest].counts["source_cache_misses"],
    }


def print_summary(label, values):
    print(label)
    for name, value in values.items():
        print(f"  {name}: {value}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordination", type=Path,
                        help="Compare the matching runner's coordination.csv for one or more cases.")
    parser.add_argument("--require-full-rerun", action="store_true",
                        help="Require fresh measurements for every recorded case.")
    args = parser.parse_args()
    if args.require_full_rerun and not args.coordination:
        parser.error("--require-full-rerun requires --coordination")
    recorded = load(HERE / "recorded.csv")
    stats = summary(recorded)
    expected = {
        "cases": 53, "median rounds": 1177, "median local solves": 227,
        "median seconds": 0.040, "orders under one second": 49,
        "slowest order": "session06_order2904_execution02", "slowest seconds": 24.211,
        "local solves for slowest order": 3194162,
    }
    if stats != expected:
        raise ValueError(f"Recorded summary differs from the paper's reference run: {stats}")
    print_summary("Recorded Apple M1 Pro run", stats)

    if args.coordination:
        fresh = load(args.coordination)
        if args.require_full_rerun and fresh.keys() != recorded.keys():
            raise ValueError("Fresh coordination measurements must cover all 53 recorded cases.")
        for case, result in fresh.items():
            if case not in recorded:
                raise ValueError(f"Unrecognized case {case!r}")
            for key in COUNTERS:
                actual = result.counts[key]
                expected_value = recorded[case].counts[key]
                if actual != expected_value:
                    raise ValueError(f"{case}, {key}: expected {expected_value}, got {actual}")
        print(f"All {len(COUNTERS)} search counters match for {len(fresh)} of {len(recorded)} cases.")
        print_summary("Supplied run", summary(fresh))


if __name__ == "__main__":
    main()
