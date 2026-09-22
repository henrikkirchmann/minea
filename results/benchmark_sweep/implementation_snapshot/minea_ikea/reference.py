"""Independent central encoding and small exhaustive checks.

This module does not call the distributed construction, matching, or solver.
The central baseline receives candidate records and locally given exclusions;
assignment and intra-case rows are reconstructed here from their definitions.
Scores are exact rationals of the stored decimal text, with no quantization.
"""

from collections import defaultdict
from fractions import Fraction
from itertools import product
from math import prod


def validate_instance(instance):
    """Reject malformed inputs before either compared algorithm runs."""
    cases, sources = instance["cases"], instance["sources"]
    if len(cases) != len(set(cases)) or len(sources) != len(set(sources)):
        raise ValueError("Duplicate case or source")
    if set(instance["case_hosts"]) != set(cases):
        raise ValueError("Every case must have exactly one agent host")
    if not set(instance["case_hosts"].values()).issubset(sources):
        raise ValueError("Unknown case-agent host")
    by_id, observations = {}, {}
    for c in instance["candidates"]:
        if c["id"] in by_id:
            raise ValueError("Duplicate candidate ID")
        by_id[c["id"]] = c
        if c["case_id"] not in cases or c["owner"] not in sources:
            raise ValueError("Unknown candidate case or source")
        if any(not isinstance(c[k], int) or isinstance(c[k], bool) for k in ("start", "end")):
            raise ValueError("Frame boundaries must be integers")
        if isinstance(c["score"], (bool, float)):
            raise ValueError("Scores must preserve exact decimal text or integer values, not binary floats")
        if not 0 <= c["start"] <= c["end"] or Fraction(c["score"]) < 0:
            raise ValueError("Invalid interval or negative score")
        observation = (c["case_id"], c["owner"], c["start"], c["end"])
        old = observations.setdefault(c["observation_id"], observation)
        if old != observation:
            raise ValueError("Observation alternatives differ in owner, case or interval")
    for row in instance["given_rows"]:
        unknown = set(row["terms"]) - set(by_id)
        if unknown:
            raise ValueError(f"Unknown candidate in row {row['id']}: {unknown}")
        owners = {by_id[v]["owner"] for v, a in row["terms"].items() if a}
        if len(owners) > 1:
            raise ValueError("Given local row spans several sources")
    ids = [r["id"] for r in instance["given_rows"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate given row ID")
    return by_id


def encode_centrally(instance):
    """Apply the process definitions directly to the uploaded candidate set."""
    validate_instance(instance)
    candidates = instance["candidates"]
    by_observation, by_case = defaultdict(list), defaultdict(list)
    for c in candidates:
        by_observation[c["observation_id"]].append(c)
        by_case[c["case_id"]].append(c)
    rows = []
    for observation, alternatives in sorted(by_observation.items()):
        rows.append({"id": f"assignment:{observation}", "kind": "assignment",
                     "terms": {c["id"]: 1 for c in alternatives}, "upper": 1,
                     "case_id": alternatives[0]["case_id"]})
    expected_assignments = {r["id"]: canonical_row(r) for r in rows}
    given_assignments = {r["id"]: canonical_row(r) for r in instance["given_rows"]
                         if r["kind"] == "assignment"}
    if expected_assignments != given_assignments:
        raise ValueError("Given assignment rows do not encode every observation exactly once")
    for row in instance["given_rows"]:
        if row["kind"] != "assignment":
            rows.append(canonical_row(row))
    for template in instance["prerequisites"]:
        allowed = set(template["predecessor_activities"])
        for trigger in candidates:
            if trigger["activity"] != template["trigger_activity"]:
                continue
            terms = {trigger["id"]: 1}
            for predecessor in by_case[trigger["case_id"]]:
                delay = trigger["start"] - predecessor["end"]
                if (predecessor["id"] != trigger["id"]
                        and predecessor["activity"] in allowed and delay >= 0
                        and (template.get("min_delay") is None or delay >= template["min_delay"])
                        and (template.get("max_delay") is None or delay <= template["max_delay"])):
                    terms[predecessor["id"]] = -1
            rows.append({"id": f"pre:{template['id']}:{trigger['id']}",
                         "kind": "prerequisite", "terms": terms, "upper": 0,
                         "case_id": trigger["case_id"]})
    for template in instance["occurrence_bounds"]:
        activities = set(template["activities"])
        for case in instance["cases"]:
            members = [c["id"] for c in by_case[case] if c["activity"] in activities]
            if template.get("upper") is not None:
                rows.append({"id": f"upper:{template['id']}:{case}",
                             "kind": "occurrence_upper", "terms": {v: 1 for v in members},
                             "upper": template["upper"], "case_id": case})
            if (template.get("lower") or 0) > 0:
                rows.append({"id": f"lower:{template['id']}:{case}",
                             "kind": "occurrence_lower", "terms": {v: -1 for v in members},
                             "upper": -template["lower"], "case_id": case})
    result = sorted((canonical_row(r) for r in rows), key=lambda r: r["id"])
    if len({r["id"] for r in result}) != len(result):
        raise ValueError("Duplicate constructed row ID")
    return result


def canonical_row(row):
    terms = {}
    for variable, coefficient in row["terms"].items():
        if not isinstance(coefficient, int) or isinstance(coefficient, bool):
            raise ValueError("This benchmark requires integer row coefficients")
        if coefficient:
            terms[variable] = coefficient
    if not isinstance(row["upper"], int) or isinstance(row["upper"], bool):
        raise ValueError("This benchmark requires integer row bounds")
    return {"id": row["id"], "kind": row["kind"], "terms": dict(sorted(terms.items())),
            "upper": row["upper"], "case_id": row.get("case_id")}


def components_from_rows(instance, rows):
    """Central graph traversal, independent of distributed rank propagation."""
    candidates = {c["id"]: c for c in instance["candidates"]}
    neighbors = {case: set() for case in instance["cases"]}
    for row in rows:
        cases = {candidates[v]["case_id"] for v, a in row["terms"].items() if a}
        for a in cases:
            neighbors[a].update(cases - {a})
    unseen, components = set(neighbors), []
    while unseen:
        start = min(unseen)
        pending, members = [start], set()
        while pending:
            case = pending.pop()
            if case in members:
                continue
            members.add(case)
            pending.extend(neighbors[case] - members)
        unseen.difference_update(members)
        winning = min((instance["case_hosts"][case], case) for case in members)
        owned = [c for c in candidates.values() if c["case_id"] in members]
        components.append({"id": f"component:{winning[0]}:{winning[1]}",
                           "case_ids": sorted(members), "coordinator": winning[0],
                           "sources": sorted({c["owner"] for c in owned}),
                           "candidate_ids": sorted(c["id"] for c in owned)})
    return sorted(components, key=lambda c: c["id"])


def validate_selection(instance, rows, selected):
    """Check a claimed solution with integer rows and rational score sums."""
    selected = list(selected)
    candidates = {c["id"]: c for c in instance["candidates"]}
    if len(selected) != len(set(selected)) or not set(selected).issubset(candidates):
        raise ValueError("Repeated or unknown selected candidate")
    chosen = set(selected)
    violations = [r["id"] for r in rows
                  if sum(a for v, a in r["terms"].items() if v in chosen) > r["upper"]]
    score = sum((Fraction(candidates[v]["score"]) for v in selected), Fraction())
    observations = {c["observation_id"] for c in candidates.values()}
    chosen_observations = [candidates[v]["observation_id"] for v in selected]
    if len(set(chosen_observations)) != len(chosen_observations):
        violations.append("at_most_one_per_observation")
    return {"feasible": not violations, "violations": violations, "objective": str(score),
            "selected_observations": len(set(chosen_observations)),
            "omitted_observations": len(observations - set(chosen_observations))}


def compare_construction(instance, constructed):
    expected = encode_centrally(instance)
    actual = sorted((canonical_row(r) for r in constructed["rows"]), key=lambda r: r["id"])
    if actual != expected:
        want, got = {r["id"]: r for r in expected}, {r["id"]: r for r in actual}
        differences = [key for key in sorted(set(want) | set(got)) if want.get(key) != got.get(key)]
        raise ValueError(f"Distributed rows differ from independent encoding: {differences[:5]}")
    components = components_from_rows(instance, expected)
    fields = ("id", "case_ids", "sources", "coordinator", "candidate_ids")
    actual_components = [{k: c[k] for k in fields} for c in constructed["components"]]
    actual_components.sort(key=lambda c: c["id"])
    if actual_components != components:
        raise ValueError("Distributed election/components differ from central graph traversal")
    by_id = {c["id"]: c for c in instance["candidates"]}
    for row in actual:
        owners = {by_id[v]["owner"] for v in row["terms"]}
        if row["kind"] == "exclusion" and len(owners) != 1:
            raise ValueError("Synthetic inter-case row is not source-local")
    failed_empty = sorted(r["id"] for r in actual if not r["terms"] and r["upper"] < 0)
    if constructed["status"] != ("infeasible" if failed_empty else "ready"):
        raise ValueError("Incorrect construction feasibility status")
    return {"status": "PASS", "rows": len(actual), "components": len(components),
            "coefficients": sum(len(r["terms"]) for r in actual),
            "empty_rows": sum(not r["terms"] for r in actual),
            "failed_empty_rows": failed_empty}


def exhaustive_optimum(instance, rows, max_observations=10, max_assignments=1_100_000):
    """Enumerate zero-or-one choices per observation; used only on small tests."""
    observations = defaultdict(list)
    for c in instance["candidates"]:
        observations[c["observation_id"]].append(c["id"])
    choices = [[None, *sorted(v)] for _, v in sorted(observations.items())]
    if len(choices) > max_observations or prod(map(len, choices)) > max_assignments:
        raise ValueError("Instance exceeds the exhaustive verification limit")
    best, selected, checked = None, None, 0
    for assignment in product(*choices):
        current = [v for v in assignment if v is not None]
        report = validate_selection(instance, rows, current)
        checked += 1
        if report["feasible"] and (best is None or Fraction(report["objective"]) > best):
            best, selected = Fraction(report["objective"]), current
    return {"status": "optimal" if best is not None else "infeasible",
            "objective": str(best) if best is not None else None,
            "selected_ids": selected, "assignments_checked": checked}
