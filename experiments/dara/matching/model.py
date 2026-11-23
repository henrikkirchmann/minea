"""Construct hard inequalities from candidates, event boundaries and completion areas."""
from collections import defaultdict
import csv
from fractions import Fraction
import gzip

from constructors import Candidate, Row, Rule, instantiate


def read_observations(path):
    by_case = defaultdict(list)
    seen = set()
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            obs = row["dara:observation_id"]
            if obs in seen:
                raise ValueError(f"Duplicate observation in event log: {obs}")
            seen.add(obs)
            case = row["case:concept:name"]
            start = Fraction(int(row["dara:start_frame"]) * 100, 2997)
            end = Fraction(int(row["dara:end_frame"]) * 100, 2997)
            by_case[case].append((start, obs, end, row["dara:source"]))
    if not seen:
        raise ValueError("Event log has no observations")
    return {case: sorted(intervals) for case, intervals in by_case.items()}


def read_candidates(path):
    by_id = defaultdict(list)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            by_id[row["observation_id"]].append(
                (int(row["rank"]), row["activity_id"], int(row["weight"])))
    for obs, group in by_id.items():
        group.sort()
        if ([rank for rank, _, _ in group] != list(range(1, 11))
                or len({label for _, label, _ in group}) != 10
                or any(not 1 <= weight <= 181 for _, _, weight in group)
                or group != sorted(group, key=lambda c: (-c[2], c[1]))):
            raise ValueError(f"Expected ten distinct, score-ordered candidates for {obs}")
    return by_id


def build(case, observations, ranked, templates):
    candidates = []
    rows = []
    for start, obs, end, source in observations:
        choices = []
        for _, label, weight in ranked[obs]:
            name = f"{obs}::{label}"
            candidates.append(Candidate(name, source, obs, case, label, start, end,
                                        Fraction(weight, 181)))
            choices.append((name, 1))
        rows.append(Row(f"assignment::{obs}", tuple(choices), 1, source))

    rules = []
    for rule in templates:
        labels = frozenset(rule["labels"])
        if rule["kind"] == "cardinality":
            rules.append(Rule(f"{case}::{rule['id']}", "cardinality", case,
                              labels=labels, upper=rule["upper"]))
        elif rule["kind"] == "prerequisite":
            for candidate in candidates:
                if candidate.label == rule["trigger"]:
                    rules.append(Rule(f"{rule['id']}::{candidate.id}", "prerequisite",
                                      case, trigger=candidate.id, labels=labels))
        else:
            raise ValueError(f"Unsupported DaRA rule kind: {rule['kind']}")

    # The owners return their own fragments. A row spanning owners is shared.
    process = instantiate(candidates, rules, sources=sorted({c.owner for c in candidates}),
                          cases=[case], batch_start=observations[0][0],
                          cutoff=max(end for _, _, end, _ in observations), duplicate=False)
    rows.extend(process.rows)
    return {"candidates": [vars(c) for c in candidates],
            "rows": [r.to_dict() for r in rows]}
