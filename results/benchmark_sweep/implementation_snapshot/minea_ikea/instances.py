"""Fixed prepared data and reproducible controlled inter-case instances.

The prepared files are inputs, not a new mining or candidate-selection step.
Candidate scores retain their original JSON numeric tokens.  All identifiers,
except the seeded merge/placement decisions, depend only on sorted input data.

``generate_plan`` constructs the *whole* hierarchy before ownership is assigned.
``build_instance`` then takes a bridge prefix and coarsens that fixed ownership.
Semantic certificate checks below do not import the staged row constructor or
an optimizer: they evaluate selected events against the original templates.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from copy import deepcopy
import csv
from decimal import Decimal
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path
import random


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _score_strings(raw):
    """Validate with Decimal, retaining even the original exponent spelling."""
    values = json.loads(raw, parse_float=Decimal, parse_int=Decimal,
                        object_pairs_hook=_unique_object)
    if not isinstance(values, dict) or not values:
        raise ValueError("Each observation needs a nonempty score object")
    for activity, value in values.items():
        if not isinstance(activity, str) or not activity:
            raise ValueError("Candidate activities must be nonempty strings")
        if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
            raise ValueError(f"Candidate score is not a finite nonnegative number: {activity!r}")
    # A second numeric-token parse preserves 1e-05 as 1e-05, for example,
    # whereas str(Decimal('1e-05')) would return '0.00001'.
    return json.loads(raw, parse_float=str, parse_int=str,
                      object_pairs_hook=_unique_object)


def _csv_rows(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fingerprint(dataset):
    """Identity of the numerical model, independent of owners and metadata."""
    model = {name: dataset[name] for name in (
        "cases", "prerequisites", "occurrence_bounds", "given_rows", "gt_selected")}
    model["candidates"] = [
        {key: value for key, value in candidate.items() if key != "owner"}
        for candidate in dataset["candidates"]
    ]
    return hashlib.sha256(json.dumps(model, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def _positive_integer(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _check_dataset(dataset):
    cases = dataset["cases"]
    if not cases or any(not isinstance(case, str) or not case for case in cases):
        raise ValueError("cases must be nonempty strings in a nonempty list")
    if len(cases) != len(set(cases)):
        raise ValueError("Duplicate case ID")
    candidates = dataset["candidates"]
    candidate_ids = set()
    observations = {}
    labels = set()
    for candidate in candidates:
        identifier = candidate["id"]
        if not isinstance(identifier, str) or not identifier or identifier in candidate_ids:
            raise ValueError("Candidate IDs must be unique nonempty strings")
        candidate_ids.add(identifier)
        if candidate["case_id"] not in cases:
            raise ValueError(f"Candidate has an unknown case: {identifier}")
        if not isinstance(candidate["activity"], str) or not candidate["activity"]:
            raise ValueError("Candidate activities must be nonempty strings")
        for key in ("start", "end"):
            if isinstance(candidate[key], bool) or not isinstance(candidate[key], int):
                raise ValueError("Frame boundaries must be integers")
        if candidate["start"] < 0 or candidate["end"] <= candidate["start"]:
            raise ValueError("Candidate intervals must be nonempty and nonnegative")
        score = candidate["score"]
        if not isinstance(score, str):
            raise ValueError("Candidate scores must be original decimal strings")
        numeric = Decimal(score)
        if not numeric.is_finite() or numeric < 0:
            raise ValueError("Candidate scores must be finite and nonnegative")
        observation = candidate["observation_id"]
        if not isinstance(observation, str) or not observation:
            raise ValueError("Observation IDs must be nonempty strings")
        identity = (candidate["case_id"], candidate["start"], candidate["end"])
        if observation in observations and observations[observation] != identity:
            raise ValueError(f"Observation alternatives disagree on identity: {observation}")
        observations[observation] = identity
        label = (observation, candidate["activity"])
        if label in labels:
            raise ValueError(f"Duplicate activity at observation: {observation}")
        labels.add(label)
    templates = dataset["prerequisites"] + dataset["occurrence_bounds"]
    if len({template["id"] for template in templates}) != len(templates):
        raise ValueError("Duplicate constraint template ID")
    for template in dataset["prerequisites"]:
        if not template["trigger_activity"] or not template["predecessor_activities"]:
            raise ValueError("Prerequisite templates need a trigger and predecessors")
    for template in dataset["occurrence_bounds"]:
        lower, upper = template["lower"], template["upper"]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (lower, upper)):
            raise ValueError("Occurrence bounds must be integers")
        if lower < 0 or upper < lower:
            raise ValueError("Occurrence bounds must satisfy 0 <= lower <= upper")
    row_ids = set()
    for row in dataset["given_rows"]:
        if row["id"] in row_ids:
            raise ValueError("Duplicate given-row ID")
        row_ids.add(row["id"])
        if row["kind"] not in ("assignment", "exclusion"):
            raise ValueError(f"Unknown given-row kind: {row['kind']}")
        if not set(row["terms"]).issubset(candidate_ids):
            raise ValueError(f"Unknown candidate in row: {row['id']}")
        if any(isinstance(value, bool) or not isinstance(value, int)
               for value in [row["upper"], *row["terms"].values()]):
            raise ValueError("Given-row coefficients and upper bounds must be integers")
    gt = dataset["gt_selected"]
    if len(gt) != len(set(gt)) or not set(gt).issubset(candidate_ids):
        raise ValueError("GT must contain unique known candidate IDs")
    by_id = {candidate["id"]: candidate for candidate in candidates}
    counts = Counter(by_id[identifier]["observation_id"] for identifier in gt)
    if set(counts) != set(observations) or any(count != 1 for count in counts.values()):
        raise ValueError("GT must select exactly one candidate at every observation")


def load_dataset(folder: Path) -> dict:
    """Read an already prepared population without filtering or renormalizing."""
    folder = Path(folder)
    uncertain_path = folder / "uncertain_log.csv.gz"
    if not uncertain_path.exists():
        uncertain_path = folder / "uncertain_log.csv"
    paths = [folder / "cases.csv", folder / "ground_truth.csv", uncertain_path,
             folder / "constraints.json"]
    cases = sorted(row["case_id"] for row in _csv_rows(paths[0]))
    certain = _csv_rows(paths[1])
    uncertain = _csv_rows(paths[2])
    constraints = json.loads(paths[3].read_text(encoding="utf-8"), parse_float=Decimal)["constraints"]
    gt_events = {}
    for event in certain:
        if event["event_id"] in gt_events:
            raise ValueError(f"Duplicate GT event ID: {event['event_id']}")
        gt_events[event["event_id"]] = event
    observed_ids = set()
    candidates, assignments, gt_selected = [], [], []
    uncertain.sort(key=lambda event: (event["case_id"], int(event["start_frame"]),
                                      int(event["end_frame_exclusive"]), event["event_id"]))
    for event in uncertain:
        observation = event["event_id"]
        if observation in observed_ids:
            raise ValueError(f"Duplicate uncertain observation ID: {observation}")
        observed_ids.add(observation)
        if observation not in gt_events:
            raise ValueError(f"Uncertain observation is missing from GT: {observation}")
        truth = gt_events[observation]
        if (event["case_id"], int(event["start_frame"]), int(event["end_frame_exclusive"])) != (
                truth["case_id"], int(truth["start_frame"]), int(truth["end_frame_exclusive"])):
            raise ValueError(f"GT and uncertain observation identities differ: {observation}")
        scores = _score_strings(event["scores"])
        if truth["activity"] not in scores:
            raise ValueError(f"GT label is missing from prepared candidates: {observation}")
        terms = {}
        for activity in sorted(scores):
            identifier = f"v{len(candidates):06d}"
            candidates.append({
                "id": identifier, "observation_id": observation,
                "case_id": event["case_id"], "activity": activity,
                "start": int(event["start_frame"]), "end": int(event["end_frame_exclusive"]),
                "score": scores[activity], "owner": 0,
            })
            terms[identifier] = 1
            if activity == truth["activity"]:
                gt_selected.append(identifier)
        assignments.append({"id": f"assignment:{observation}", "kind": "assignment",
                            "terms": terms, "upper": 1, "case_id": event["case_id"]})
    if observed_ids != set(gt_events):
        raise ValueError("GT and uncertain logs contain different observation populations")
    if any(template["kind"] not in ("prerequisite", "occurrence_bound") for template in constraints):
        raise ValueError("The input contains an unsupported constraint template")
    policy_path = folder / "candidate_policy.json"
    if policy_path.exists():
        paths.append(policy_path)
    dataset = {
        "cases": cases, "sources": [0], "case_hosts": {case: 0 for case in cases},
        "candidates": candidates,
        "prerequisites": [template for template in constraints if template["kind"] == "prerequisite"],
        "occurrence_bounds": [template for template in constraints if template["kind"] == "occurrence_bound"],
        "given_rows": assignments, "gt_selected": gt_selected,
        "metadata": {"input_folder": str(folder.resolve()),
                     "input_hashes": {path.name: _sha256(path) for path in paths},
                     "score_convention": "Exact original JSON decimal tokens; no rounding or normalization.",
                     "case_order": "Lexicographic case ID.",
                     "candidate_order": "Case ID, start, end, observation ID, activity; all lexicographic except integer times.",
                     "population_filter_applied": False,
                     "zero_lower_bound_convention": "Preserve templates; omit zero lower rows only during row construction."},
    }
    _check_dataset(dataset)
    violations = semantic_violations(dataset, gt_selected)
    if violations:
        raise ValueError(f"Prepared GT violates fixed constraints: {violations[:3]}")
    by_id = {candidate["id"]: candidate for candidate in candidates}
    dataset["metadata"].update({
        "case_count": len(cases), "observation_count": len(observed_ids),
        "candidate_count": len(candidates), "prerequisite_template_count": len(dataset["prerequisites"]),
        "occurrence_bound_template_count": len(dataset["occurrence_bounds"]),
        "empty_case_ids": sorted(set(cases) - {candidate["case_id"] for candidate in candidates}),
        "gt_score": str(sum((Fraction(by_id[identifier]["score"]) for identifier in gt_selected), Fraction())),
        "dataset_fingerprint": _fingerprint(dataset),
    })
    return dataset


def _case_violations(case, selected, prerequisites, bounds):
    """Evaluate event semantics, without converting templates into linear rows."""
    violations = []
    observation_counts = Counter(candidate["observation_id"] for candidate in selected)
    for observation, count in observation_counts.items():
        if count > 1:
            violations.append({"kind": "assignment", "case_id": case,
                               "observation_id": observation, "selected_count": count})
    by_activity = defaultdict(list)
    for candidate in selected:
        by_activity[candidate["activity"]].append(candidate)
    for template in prerequisites:
        supporters = [candidate for activity in template["predecessor_activities"]
                      for candidate in by_activity[activity]]
        for trigger in by_activity[template["trigger_activity"]]:
            if not any(supporter["observation_id"] != trigger["observation_id"]
                       and supporter["end"] <= trigger["start"] for supporter in supporters):
                violations.append({"kind": "prerequisite", "case_id": case,
                                   "template_id": template["id"], "trigger_id": trigger["id"]})
    for template in bounds:
        count = sum(candidate["activity"] in template["activities"] for candidate in selected)
        if not template["lower"] <= count <= template["upper"]:
            violations.append({"kind": "occurrence_bound", "case_id": case,
                               "template_id": template["id"], "count": count,
                               "lower": template["lower"], "upper": template["upper"]})
    return violations


def semantic_violations(instance: dict, selected) -> list[dict]:
    """Pure feasibility check against event rules and explicit given rows.

    Empty selections are allowed by assignment constraints.  Positive occurrence
    minima, if present, still apply to every case, including empty cases.
    """
    selected = list(selected)
    chosen = set(selected)
    candidates = {candidate["id"]: candidate for candidate in instance["candidates"]}
    violations = []
    if len(chosen) != len(selected):
        violations.append({"kind": "duplicate_selected_candidate"})
    unknown = chosen - candidates.keys()
    if unknown:
        violations.append({"kind": "unknown_selected_candidate", "candidate_ids": sorted(unknown)})
    by_case = {case: [] for case in instance["cases"]}
    for identifier in sorted(chosen - unknown):
        candidate = candidates[identifier]
        by_case[candidate["case_id"]].append(candidate)
    for case, events in by_case.items():
        violations.extend(_case_violations(case, events, instance["prerequisites"], instance["occurrence_bounds"]))
    for row in instance["given_rows"]:
        value = sum(coefficient for identifier, coefficient in row["terms"].items() if identifier in chosen)
        if value > row["upper"]:
            violations.append({"kind": row["kind"], "row_id": row["id"], "value": value, "upper": row["upper"]})
    return violations


def _safe_replacements(dataset):
    """Audit every single-GT-swap using only its affected semantic case/rows."""
    gt = set(dataset["gt_selected"])
    by_case = defaultdict(list)
    truth_at = {}
    for candidate in dataset["candidates"]:
        if candidate["id"] in gt:
            by_case[candidate["case_id"]].append(candidate)
            truth_at[candidate["observation_id"]] = candidate["id"]
    rows_at = defaultdict(list)
    row_values = []
    for index, row in enumerate(dataset["given_rows"]):
        row_values.append(sum(value for identifier, value in row["terms"].items() if identifier in gt))
        for identifier in row["terms"]:
            rows_at[identifier].append(index)
    safe, checked = [], 0
    rejected = Counter()
    for candidate in sorted(dataset["candidates"], key=lambda item: item["id"]):
        incoming = candidate["id"]
        if incoming in gt:
            continue
        checked += 1
        outgoing = truth_at[candidate["observation_id"]]
        events = [event for event in by_case[candidate["case_id"]] if event["id"] != outgoing] + [candidate]
        violations = _case_violations(candidate["case_id"], events, dataset["prerequisites"], dataset["occurrence_bounds"])
        for index in set(rows_at[outgoing]) | set(rows_at[incoming]):
            row = dataset["given_rows"][index]
            if row_values[index] - row["terms"].get(outgoing, 0) + row["terms"].get(incoming, 0) > row["upper"]:
                violations.append({"kind": row["kind"]})
        if violations:
            rejected.update({violation["kind"] for violation in violations})
        else:
            safe.append({"observation_id": candidate["observation_id"], "case_id": candidate["case_id"],
                         "gt_candidate_id": outgoing, "replacement_candidate_id": incoming})
    eligible = defaultdict(set)
    for swap in safe:
        eligible[swap["case_id"]].add(swap["observation_id"])
    counts = {case: len(eligible[case]) for case in sorted(dataset["cases"])}
    return safe, {"checked_alternatives": checked, "safe_alternatives": len(safe),
                  "unsafe_alternatives": checked - len(safe),
                  "rejected_by_semantic_kind": dict(sorted(rejected.items())),
                  "eligible_observations": sum(counts.values()),
                  "eligible_observations_by_case": counts,
                  "minimum_eligible_observations_per_case": min(counts.values())}


def generate_plan(dataset: dict, seed: int, max_sources: int = 8) -> dict:
    """Generate a seeded full binary hierarchy and fixed ownership placement.

    No minimum of seven observations is imposed: that is a sufficient argument
    for the 116-case data, not a requirement for small examples.  An exhausted
    component instead produces an explicit endpoint error at its actual merge.
    """
    _positive_integer(max_sources, "max_sources")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    _check_dataset(dataset)
    violations = semantic_violations(dataset, dataset["gt_selected"])
    if violations:
        raise ValueError(f"GT violates fixed constraints: {violations[:3]}")
    safe_swaps, audit = _safe_replacements(dataset)
    safe_at = defaultdict(list)
    candidates = {candidate["id"]: candidate for candidate in dataset["candidates"]}
    observation_cases = {candidate["observation_id"]: candidate["case_id"] for candidate in dataset["candidates"]}
    for swap in safe_swaps:
        safe_at[swap["observation_id"]].append(swap)
    rng = random.Random(seed)
    permutation = sorted(dataset["cases"])
    rng.shuffle(permutation)
    components = [[case] for case in permutation]
    unused = set(safe_at)
    bridges, level = [], 0
    while len(components) > 1:
        level += 1
        next_components = []
        for offset in range(0, len(components), 2):
            if offset + 1 == len(components):
                next_components.append(components[offset])
                continue
            left, right = components[offset:offset + 2]
            pools = [sorted(observation for observation in unused if observation_cases[observation] in component)
                     for component in (left, right)]
            for component, pool in zip((left, right), pools):
                if not pool:
                    raise ValueError(f"No unused eligible observation endpoint at level {level} in component {component}")
            left_observation, right_observation = (rng.choice(pool) for pool in pools)
            unused.difference_update((left_observation, right_observation))
            orientation = rng.randrange(2)
            a, b = ((left_observation, right_observation) if orientation == 0
                    else (right_observation, left_observation))
            swap = rng.choice(safe_at[b])
            gt_a = safe_at[a][0]["gt_candidate_id"]
            identifier = f"bridge:{len(bridges):06d}"
            bridges.append({
                "id": identifier, "level": level, "left_cases": list(left), "right_cases": list(right),
                "orientation": "left_to_right" if orientation == 0 else "right_to_left",
                "a_observation_id": a, "b_observation_id": b,
                "a_case_id": candidates[gt_a]["case_id"], "b_case_id": swap["case_id"],
                "gt_candidate_id": gt_a, "replacement_candidate_id": swap["replacement_candidate_id"],
                "terms": {gt_a: 1, swap["replacement_candidate_id"]: 1}, "upper": 1,
                "witness": {"changed_observation_id": b,
                            "removed_candidate_id": swap["gt_candidate_id"],
                            "selected_candidate_id": swap["replacement_candidate_id"]},
            })
            next_components.append(sorted(left + right))
        components = next_components
    endpoints = {observation for bridge in bridges
                 for observation in (bridge["a_observation_id"], bridge["b_observation_id"])}
    blocks = [{"id": f"block:{index:06d}",
               "observation_ids": sorted((bridge["a_observation_id"], bridge["b_observation_id"]))}
              for index, bridge in enumerate(bridges)]
    for observation in sorted(set(observation_cases) - endpoints):
        blocks.append({"id": f"block:{len(blocks):06d}", "observation_ids": [observation]})
    block_order = [block["id"] for block in blocks]
    rng.shuffle(block_order)
    observation_weights = Counter(candidate["observation_id"] for candidate in dataset["candidates"])
    block_weights = {block["id"]: sum(observation_weights[observation] for observation in block["observation_ids"])
                     for block in blocks}
    source_loads, placement = [0] * max_sources, {}
    for identifier in block_order:
        owner = min(range(max_sources), key=lambda source: (source_loads[source], source))
        placement[identifier] = owner
        source_loads[owner] += block_weights[identifier]
    owners = {}
    for block in blocks:
        block["owner"] = placement[block["id"]]
        for observation in block["observation_ids"]:
            owners[observation] = block["owner"]
    plan = {
        "schema_version": 1, "seed": seed, "max_sources": max_sources,
        "dataset_fingerprint": _fingerprint(dataset), "case_permutation": permutation,
        "safe_swaps": safe_swaps, "safe_replacement_audit": audit, "bridges": bridges,
        "ownership_blocks": blocks, "block_order": block_order,
        "observation_owners": dict(sorted(owners.items())),
        "case_hosts": {case: index % max_sources for index, case in enumerate(sorted(dataset["cases"]))},
        "metadata": {"case_count": len(permutation), "observation_count": len(observation_cases),
                     "candidate_count": len(candidates), "levels": level, "bridge_count": len(bridges),
                     "ownership_block_count": len(blocks), "two_observation_blocks": len(bridges),
                     "singleton_blocks": len(blocks) - len(bridges),
                     "sufficient_per_case_endpoint_bound": level,
                     "all_cases_meet_sufficient_endpoint_bound": audit["minimum_eligible_observations_per_case"] >= level,
                     "ownership_policy": "Seed-shuffle full-plan blocks; choose the least candidate-loaded source, ties lowest source ID.",
                     "max_source_candidate_counts": source_loads,
                     "max_source_candidate_count_imbalance": max(source_loads) - min(source_loads),
                     "ownership_coarsening": "owner // (max_sources // source_count), for divisors of max_sources.",
                     "host_policy": "Cycle sorted case IDs through max_sources; coarsen identically to ownership.",
                     "rng": "Python random.Random(seed); permutation, level-order endpoints/orientation/replacement, then block order."},
    }
    plan["validation"] = validate_plan(dataset, plan)
    return plan


def _component_details(cases, bridges):
    adjacency = {case: set() for case in cases}
    for bridge in bridges:
        a, b = bridge["a_case_id"], bridge["b_case_id"]
        adjacency[a].add(b)
        adjacency[b].add(a)

    def distances(start):
        result, queue = {start: 0}, deque([start])
        while queue:
            node = queue.popleft()
            for neighbor in sorted(adjacency[node]):
                if neighbor not in result:
                    result[neighbor] = result[node] + 1
                    queue.append(neighbor)
        return result

    pending, result = set(cases), []
    while pending:
        start = min(pending)
        reached = distances(start)
        farthest = max(reached, key=lambda case: (reached[case], case))
        result.append({"id": start, "cases": sorted(reached), "size": len(reached),
                       "diameter": max(distances(farthest).values()),
                       "edge_count": sum(len(adjacency[case]) for case in reached) // 2})
        pending.difference_update(reached)
    return result


def validate_plan(dataset: dict, plan: dict) -> dict:
    """Independently recertify swaps and every witness against the full plan.

    Raise ValueError on any failed certificate.  Checking every other bridge,
    including later ones, makes each nonredundancy claim independent of prefix.
    """
    _check_dataset(dataset)
    if plan["dataset_fingerprint"] != _fingerprint(dataset):
        raise ValueError("Plan belongs to a different dataset")
    gt = set(dataset["gt_selected"])
    if semantic_violations(dataset, gt):
        raise ValueError("GT violates fixed semantic rules")
    actual_safe, audit = _safe_replacements(dataset)
    if plan["safe_swaps"] != actual_safe or plan["safe_replacement_audit"] != audit:
        raise ValueError("Safe-swap inventory does not match the semantic audit")
    safe_pairs = {(swap["observation_id"], swap["replacement_candidate_id"]) for swap in actual_safe}
    by_id = {candidate["id"]: candidate for candidate in dataset["candidates"]}
    observation_ids = {candidate["observation_id"] for candidate in dataset["candidates"]}
    _positive_integer(plan["max_sources"], "max_sources")
    bridges = plan["bridges"]
    if len(bridges) != len(dataset["cases"]) - 1:
        raise ValueError("Full plan must have one fewer bridges than cases")
    permutation = plan["case_permutation"]
    if len(permutation) != len(dataset["cases"]) or set(permutation) != set(dataset["cases"]):
        raise ValueError("Case permutation does not cover the dataset exactly")
    components = [[case] for case in permutation]
    endpoints, position, level = set(), 0, 0
    while len(components) > 1:
        level += 1
        next_components = []
        for offset in range(0, len(components), 2):
            if offset + 1 == len(components):
                next_components.append(components[offset])
                continue
            left, right = components[offset:offset + 2]
            bridge = bridges[position]
            position += 1
            if bridge["id"] != f"bridge:{position - 1:06d}":
                raise ValueError("Bridge IDs are not unique level-order IDs")
            if bridge["level"] != level or bridge["left_cases"] != left or bridge["right_cases"] != right:
                raise ValueError("Bridge does not follow the adjacent-pair hierarchy")
            a, b = bridge["a_observation_id"], bridge["b_observation_id"]
            if a == b or a in endpoints or b in endpoints:
                raise ValueError("Bridge observation endpoints must be fresh")
            endpoints.update((a, b))
            gt_a, replacement = bridge["gt_candidate_id"], bridge["replacement_candidate_id"]
            if gt_a not in gt or replacement in gt:
                raise ValueError("Bridge must join a GT candidate and a non-GT candidate")
            if by_id[gt_a]["observation_id"] != a or by_id[replacement]["observation_id"] != b:
                raise ValueError("Bridge candidate and observation identities disagree")
            a_case, b_case = by_id[gt_a]["case_id"], by_id[replacement]["case_id"]
            if (a_case, b_case) != (bridge["a_case_id"], bridge["b_case_id"]):
                raise ValueError("Bridge candidate and case identities disagree")
            if bridge["orientation"] == "left_to_right":
                valid_orientation = a_case in left and b_case in right
            elif bridge["orientation"] == "right_to_left":
                valid_orientation = a_case in right and b_case in left
            else:
                valid_orientation = False
            if not valid_orientation:
                raise ValueError("Bridge does not connect its two declared components")
            if not any(observation == a for observation, _ in safe_pairs) or (b, replacement) not in safe_pairs:
                raise ValueError("Bridge endpoint is not an eligible safe replacement observation")
            if bridge["terms"] != {gt_a: 1, replacement: 1} or bridge["upper"] != 1:
                raise ValueError("Bridge scope must contain exactly its two declared variables")
            witness = bridge["witness"]
            removed, selected = witness["removed_candidate_id"], witness["selected_candidate_id"]
            if (witness["changed_observation_id"] != b or selected != replacement or removed not in gt
                    or by_id[removed]["observation_id"] != b):
                raise ValueError("Witness is not the declared single GT swap")
            changed = gt - {removed} | {selected}
            if semantic_violations(dataset, changed):
                raise ValueError("Bridge witness violates a fixed semantic rule")
            violated = [other["id"] for other in bridges
                        if sum(value for identifier, value in other["terms"].items() if identifier in changed) > other["upper"]]
            if violated != [bridge["id"]]:
                raise ValueError("Witness must violate exactly its bridge in the entire full plan")
            next_components.append(sorted(left + right))
        components = next_components
    if any(sum(value for identifier, value in bridge["terms"].items() if identifier in gt) > bridge["upper"]
           for bridge in bridges):
        raise ValueError("GT violates a synthetic bridge")
    blocks = plan["ownership_blocks"]
    flat = [observation for block in blocks for observation in block["observation_ids"]]
    if len(flat) != len(set(flat)) or set(flat) != observation_ids:
        raise ValueError("Ownership blocks must partition every observation")
    block_ids = [block["id"] for block in blocks]
    if len(block_ids) != len(set(block_ids)) or sorted(plan["block_order"]) != sorted(block_ids):
        raise ValueError("Recorded block order must contain every block exactly once")
    expected_blocks = {frozenset((bridge["a_observation_id"], bridge["b_observation_id"])) for bridge in bridges}
    expected_blocks.update(frozenset((observation,)) for observation in observation_ids - endpoints)
    if {frozenset(block["observation_ids"]) for block in blocks} != expected_blocks:
        raise ValueError("Ownership blocks do not match the full plan")
    observation_weights = Counter(candidate["observation_id"] for candidate in dataset["candidates"])
    block_weights = {block["id"]: sum(observation_weights[observation] for observation in block["observation_ids"])
                     for block in blocks}
    source_loads, placement = [0] * plan["max_sources"], {}
    for identifier in plan["block_order"]:
        owner = min(range(plan["max_sources"]), key=lambda source: (source_loads[source], source))
        placement[identifier] = owner
        source_loads[owner] += block_weights[identifier]
    expected_owners = {}
    for block in blocks:
        if block["owner"] != placement[block["id"]]:
            raise ValueError("Block placement does not follow its recorded load-balancing order")
        expected_owners.update({observation: block["owner"] for observation in block["observation_ids"]})
    if plan["observation_owners"] != expected_owners:
        raise ValueError("Observation ownership differs from ownership blocks")
    if plan["case_hosts"] != {case: index % plan["max_sources"] for index, case in enumerate(sorted(dataset["cases"]))}:
        raise ValueError("Case-agent hosts do not follow the fixed host policy")
    return {"valid": True, "gt_feasible": True, "checked_alternatives": audit["checked_alternatives"],
            "checked_safe_swaps": len(actual_safe), "checked_witnesses": len(bridges),
            "fresh_endpoint_observations": len(endpoints), "ownership_block_count": len(blocks),
            "full_plan_component_count": len(_component_details(dataset["cases"], bridges)),
            "witnesses_satisfy_all_other_synthetic_rows": True}


def build_instance(dataset: dict, plan: dict, source_count: int, component_count: int) -> dict:
    """Take a hierarchy prefix while reusing full-plan ownership and hosts."""
    _positive_integer(source_count, "source_count")
    _positive_integer(component_count, "component_count")
    if plan["max_sources"] % source_count:
        raise ValueError("source_count must divide max_sources")
    if component_count > len(dataset["cases"]):
        raise ValueError("component_count cannot exceed the number of cases")
    if plan["dataset_fingerprint"] != _fingerprint(dataset):
        raise ValueError("Plan belongs to a different dataset")
    width = plan["max_sources"] // source_count
    bridges = plan["bridges"][:len(dataset["cases"]) - component_count]
    instance = deepcopy(dataset)
    instance["sources"] = list(range(source_count))
    instance["case_hosts"] = {case: plan["case_hosts"][case] // width for case in dataset["cases"]}
    for candidate in instance["candidates"]:
        candidate["owner"] = plan["observation_owners"][candidate["observation_id"]] // width
    instance["given_rows"].extend({"id": bridge["id"], "kind": "exclusion",
                                   "terms": dict(bridge["terms"]), "upper": bridge["upper"], "case_id": None}
                                  for bridge in bridges)
    details = _component_details(dataset["cases"], bridges)
    if len(details) != component_count:
        raise ValueError("Bridge prefix does not have the requested number of components")
    instance["metadata"].update({
        "seed": plan["seed"], "source_count": source_count, "max_sources": plan["max_sources"],
        "component_count": component_count, "bridge_count": len(bridges),
        "case_count": len(dataset["cases"]), "candidate_count": len(dataset["candidates"]),
        "observation_count": len(plan["observation_owners"]), "components": details,
        "component_sizes": [component["size"] for component in details],
        "component_diameters": [component["diameter"] for component in details],
        "ownership_block_count": len(plan["ownership_blocks"]),
        "ownership_uses_full_plan": True, "source_coarsening_group_size": width,
        "source_candidate_counts": [sum(candidate["owner"] == source for candidate in instance["candidates"])
                                    for source in instance["sources"]],
    })
    return instance
