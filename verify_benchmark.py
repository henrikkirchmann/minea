#!/usr/bin/env python3
"""Verify saved benchmark artifacts offline, using only the standard library.

This checks file integrity, the independently encoded model, exact feasibility
and objective arithmetic, recorded bounds, and logical accounting.  A saved Z3
optimality claim is not itself an independently checkable proof: small models
are additionally enumerated, while larger optimality claims still rely on the
recorded exact solver.  Neither construction nor any solver is rerun here.
"""

from collections import Counter, defaultdict
from copy import deepcopy
from fractions import Fraction
from itertools import combinations, product
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath

from benchmark import check_comparison, check_matching_result, numerical_fingerprint, record_optimum
from minea_ikea.instances import validate_plan
from minea_ikea.reference import (canonical_row, compare_construction, components_from_rows,
                                encode_centrally, exhaustive_optimum, validate_selection)


ROOT = Path(__file__).resolve().parent
STAGES = (
    "candidate_owner_discovery", "case_edge_discovery", "coordinator_election",
    "notification_registration", "intra_case_row_construction", "construction_completion",
)
COMMON = ("messages", "payload_records", "coefficient_terms", "colocated_messages", "cross_host_messages")
COUNTERS = (
    ("source_case_registrations", "directory_entries"),
    ("given_local_rows", "given_local_terms", "given_empty_rows", "given_empty_checks_passed",
     "given_empty_checks_failed", "type2_rows", "edge_announcements", "unique_undirected_edges",
     "duplicate_announcements", "duplicate_edge_reports"),
    ("configured_rounds", "rank_transmissions"),
    ("directory_notifications", "case_agent_registrations", "source_registrations"),
    ("trigger_requests", "bound_initiations", "omitted_zero_lower_rows", "lookup_requests",
     "positive_presence_replies", "negative_presence_replies", "retained_fragments",
     "retained_coefficient_terms", "shared_fragment_transfers", "transferred_coefficient_terms",
     "local_rows", "shared_rows", "empty_rows", "empty_row_checks", "empty_row_checks_passed",
     "empty_row_checks_failed"),
    ("placement_instructions", "local_placement_instructions", "shared_transfer_instructions",
     "shared_row_announcements", "row_storage_acknowledgments", "case_agent_completion_records",
     "coordinators_ready", "coordinators_infeasible"),
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _equal(actual, expected, label):
    _require(actual == expected, f"{label} differs from its independently computed value")


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite_json(value):
    raise ValueError(f"Nonfinite JSON number: {value}")


def _read(path):
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return json.loads(raw, object_pairs_hook=_unique_json, parse_constant=_nonfinite_json)


def _safe_path(root, name):
    _require(isinstance(name, str) and name and "\\" not in name, "Unsafe artifact path")
    relative = PurePosixPath(name)
    _require(not relative.is_absolute() and all(part not in (".", "..") for part in relative.parts),
             f"Unsafe artifact path: {name}")
    target = root.joinpath(*relative.parts)
    _require(target.resolve().is_relative_to(root), f"Artifact path escapes the study: {name}")
    return target


def _manifest(root):
    manifest_path = root / "artifact_manifest.json"
    _require(manifest_path.is_file(), "Missing artifact_manifest.json")
    records = _read(manifest_path)["files"]
    _require(isinstance(records, dict), "Manifest files must be an object")
    for name, record in records.items():
        path = _safe_path(root, name)
        _require(path.is_file() and not path.is_symlink(), f"Missing or symlinked artifact: {name}")
        raw = path.read_bytes()
        _equal(len(raw), record["bytes"], f"Artifact size {name}")
        _equal(hashlib.sha256(raw).hexdigest(), record["sha256"], f"Artifact hash {name}")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    _equal(actual, set(records) | {"artifact_manifest.json"}, "Manifest coverage")
    return records


def _counts():
    return {stage: Counter(dict.fromkeys(COMMON + names, 0)) for stage, names in zip(STAGES, COUNTERS)}


def _summary(stages):
    totals = Counter()
    for counts in stages.values():
        totals.update(counts)
    return {"stages": {stage: dict(counts) for stage, counts in stages.items()}, "totals": dict(totals)}


def _verify_construction(instance, construction, rows, trace_required):
    """Derive logical work algebraically from row scope and actual ownership."""
    report = compare_construction(instance, construction)
    candidates = {candidate["id"]: candidate for candidate in instance["candidates"]}
    components = components_from_rows(instance, rows)
    component_at = {case: component for component in components for case in component["case_ids"]}
    hosts = instance["case_hosts"]
    directories = {case: sorted({candidate["owner"] for candidate in candidates.values()
                                if candidate["case_id"] == case}) for case in instance["cases"]}
    _equal(construction["directories"], directories, "Case directories")
    stages, by_case = _counts(), {case: _counts() for case in instance["cases"]}
    physical = {source: Counter() for source in instance["sources"]}

    def count(stage, name, case=None, amount=1):
        stages[stage][name] += amount
        if case is not None:
            by_case[case][stage][name] += amount

    def delivery(stage, sender, receiver, case, amount=1, terms=0):
        for name, value in (("messages", amount), ("payload_records", amount),
                            ("coefficient_terms", amount * terms),
                            ("colocated_messages" if sender == receiver else "cross_host_messages", amount)):
            count(stage, name, case, value)
        for host, name in ((sender, "messages_sent"), (receiver, "messages_received")):
            physical[host][name] += amount
        physical[sender]["coefficient_terms_sent"] += amount * terms
        physical[receiver]["coefficient_terms_received"] += amount * terms
        if sender == receiver:
            physical[sender]["colocated_deliveries"] += amount

    for case, directory in directories.items():
        for owner in directory:
            count(STAGES[0], "source_case_registrations", case)
            count(STAGES[0], "directory_entries", case)
            delivery(STAGES[0], owner, hosts[case], case)
    given = {row["id"]: canonical_row(row) for row in instance["given_rows"]}
    all_rows = {row["id"]: row for row in rows}
    generated = {identifier: row for identifier, row in all_rows.items() if identifier not in given}
    contributors, placements, empty_checks, fragments = {}, {}, {}, {}
    edges, neighbors = set(), {case: set() for case in instance["cases"]}
    # Source/row ordering determines which case is charged for a repeated edge.
    ordered_given = sorted(given.values(), key=lambda row: (
        next((candidates[identifier]["owner"] for identifier in row["terms"]), hosts.get(row["case_id"], -1)), row["id"]))
    for row in ordered_given:
        scope = sorted({candidates[identifier]["case_id"] for identifier in row["terms"]})
        if not scope:
            scope = [row["case_id"]]
        case = scope[0]
        owners = sorted({candidates[identifier]["owner"] for identifier in row["terms"]})
        owner = owners[0] if owners else hosts[case]
        contributors[row["id"]] = owners
        placements[row["id"]] = {"classification": "given_local" if owners else "empty",
                                   "source": owner if owners else None, "component_id": component_at[case]["id"]}
        count(STAGES[1], "given_local_rows", case)
        count(STAGES[1], "given_local_terms", case, len(row["terms"]))
        if not owners:
            valid = row["upper"] >= 0
            empty_checks[row["id"]] = valid
            count(STAGES[1], "given_empty_rows", case)
            count(STAGES[1], "given_empty_checks_passed" if valid else "given_empty_checks_failed", case)
        if len(scope) > 1:
            count(STAGES[1], "type2_rows", case)
        for left, right in combinations(scope, 2):
            duplicate = (left, right) in edges
            count(STAGES[1], "duplicate_edge_reports" if duplicate else "unique_undirected_edges", left)
            for endpoint, other in ((left, right), (right, left)):
                count(STAGES[1], "edge_announcements", endpoint)
                if duplicate:
                    count(STAGES[1], "duplicate_announcements", endpoint)
                delivery(STAGES[1], owner, hosts[endpoint], endpoint)
                neighbors[endpoint].add(other)
            edges.add((left, right))
    _equal(construction["neighbors"], {case: {other: hosts[other] for other in sorted(values)}
                                        for case, values in neighbors.items()}, "Case neighbors")
    rounds = max(0, len(instance["cases"]) - 1)
    count(STAGES[2], "configured_rounds", amount=rounds)
    for case, others in neighbors.items():
        for other in others:
            count(STAGES[2], "rank_transmissions", case, rounds)
            if rounds:
                delivery(STAGES[2], hosts[case], hosts[other], case, rounds)
    for case, directory in directories.items():
        coordinator = component_at[case]["coordinator"]
        for owner in directory:
            count(STAGES[3], "directory_notifications", case)
            delivery(STAGES[3], hosts[case], owner, case)
        count(STAGES[3], "case_agent_registrations", case)
        delivery(STAGES[3], hosts[case], coordinator, case)
    for component in components:
        winner = min(component["case_ids"], key=lambda case: (hosts[case], case))
        for owner in component["sources"]:
            count(STAGES[3], "source_registrations", winner)
            delivery(STAGES[3], owner, component["coordinator"], winner)
    requests = {request["id"]: request for request in construction["requests"]}
    _equal(len(requests), len(construction["requests"]), "Unique construction request IDs")
    _equal(set(requests), set(generated), "Requested row coverage")
    for identifier, row in generated.items():
        case, request = row["case_id"], requests[identifier]
        coordinator = component_at[case]["coordinator"]
        for key in ("id", "kind", "case_id", "upper"):
            _equal(request[key], row[key], f"Request {identifier} {key}")
        owners = sorted({candidates[variable]["owner"] for variable in row["terms"]})
        contributors[identifier] = owners
        placements[identifier] = {"classification": "empty" if not owners else "local" if len(owners) == 1 else "shared",
                                  "source": None if not owners else owners[0] if len(owners) == 1 else coordinator,
                                  "component_id": component_at[case]["id"]}
        if row["kind"] == "prerequisite":
            template = next(item for item in instance["prerequisites"] if item["id"] == request["template_id"])
            trigger = candidates[request["trigger_id"]]
            _equal(identifier, f"pre:{template['id']}:{trigger['id']}", "Prerequisite request ID")
            _equal(trigger["activity"], template["trigger_activity"], "Request trigger activity")
            _equal(request["activities"], sorted(set(template["predecessor_activities"])), "Request predecessor activities")
            _equal((request["trigger_owner"], request["trigger_start"]), (trigger["owner"], trigger["start"]), "Request trigger identity")
            count(STAGES[4], "trigger_requests", case)
            delivery(STAGES[4], trigger["owner"], hosts[case], case)
        else:
            count(STAGES[4], "bound_initiations", case)
        for owner in directories[case]:
            present = owner in owners
            count(STAGES[4], "lookup_requests", case)
            count(STAGES[4], "positive_presence_replies" if present else "negative_presence_replies", case)
            delivery(STAGES[4], hosts[case], owner, case)
            delivery(STAGES[4], owner, hosts[case], case)
            if present:
                terms = {variable: value for variable, value in row["terms"].items() if candidates[variable]["owner"] == owner}
                fragments[(identifier, owner)] = terms
                count(STAGES[4], "retained_fragments", case)
                count(STAGES[4], "retained_coefficient_terms", case, len(terms))
        if not owners:
            empty_checks[identifier] = row["upper"] >= 0
            for key in ("empty_rows", "empty_row_checks", "empty_row_checks_passed" if row["upper"] >= 0 else "empty_row_checks_failed"):
                count(STAGES[4], key, case)
            continue
        count(STAGES[4], "local_rows" if len(owners) == 1 else "shared_rows", case)
        count(STAGES[5], "row_storage_acknowledgments", case)
        if len(owners) == 1:
            for key in ("placement_instructions", "local_placement_instructions"):
                count(STAGES[5], key, case)
            delivery(STAGES[5], hosts[case], owners[0], case)
            delivery(STAGES[5], owners[0], hosts[case], case)
        else:
            count(STAGES[5], "shared_row_announcements", case)
            delivery(STAGES[5], hosts[case], coordinator, case)
            delivery(STAGES[5], coordinator, hosts[case], case)
            for owner in owners:
                terms = len(fragments[(identifier, owner)])
                for key in ("placement_instructions", "shared_transfer_instructions"):
                    count(STAGES[5], key, case)
                delivery(STAGES[5], hosts[case], owner, case)
                count(STAGES[4], "shared_fragment_transfers", case)
                count(STAGES[4], "transferred_coefficient_terms", case, terms)
                delivery(STAGES[4], owner, coordinator, case, terms=terms)
    zero_minima = sum(template.get("lower") == 0 for template in instance["occurrence_bounds"])
    for case in instance["cases"]:
        count(STAGES[4], "omitted_zero_lower_rows", case, zero_minima)
        count(STAGES[5], "case_agent_completion_records", case)
        delivery(STAGES[5], hosts[case], component_at[case]["coordinator"], case)
    for component in components:
        winner = min(component["case_ids"], key=lambda case: (hosts[case], case))
        failed = any(not valid and placements[identifier]["component_id"] == component["id"] for identifier, valid in empty_checks.items())
        count(STAGES[5], "coordinators_infeasible" if failed else "coordinators_ready", winner)
    _equal(construction["contributors"], contributors, "Row contributors")
    _equal(construction["row_owners"], placements, "Row placements")
    _equal(construction["empty_row_checks"], empty_checks, "Empty-row checks")
    saved_fragments = {(item["row_id"], item["source"]): item["terms"] for item in construction["retained_fragments"]}
    _equal(len(saved_fragments), len(construction["retained_fragments"]), "Unique retained fragments")
    _equal(saved_fragments, fragments, "Retained source fragments")
    metrics = construction["metrics"]
    expected = _summary(stages)
    for key in ("stages", "totals"):
        _equal(metrics[key], expected[key], f"Construction {key}")
    component_counts = {}
    host_counts = {str(source): _counts() for source in instance["sources"]}
    for component in components:
        aggregate = _counts()
        for case in component["case_ids"]:
            for stage in STAGES:
                aggregate[stage].update(by_case[case][stage])
        aggregate[STAGES[2]]["configured_rounds"] = rounds
        component_counts[component["id"]] = _summary(aggregate)
        for stage in STAGES:
            host_counts[str(component["coordinator"])][stage].update(aggregate[stage])
    coordinator_hosts = {str(component["coordinator"]) for component in components}
    for host, counts in host_counts.items():
        counts[STAGES[2]]["configured_rounds"] = rounds if host in coordinator_hosts else 0
    host_counts = {host: _summary(value) for host, value in host_counts.items()}
    _equal(metrics["per_component"], component_counts, "Construction per-component attribution")
    _equal(metrics["per_host"], host_counts, "Construction per-coordinator-host attribution")
    _equal(metrics["physical_hosts"], {str(host): dict(values) for host, values in physical.items()}, "Physical-host deliveries")
    for category, records in (("per_component", component_counts), ("per_host", host_counts)):
        maxima = {"stages": {}, "totals": {}}
        for stage in STAGES:
            maxima["stages"][stage] = {key: max((record["stages"][stage][key] for record in records.values()), default=0)
                                      for key in stages[stage]}
        maxima["totals"] = {key: max((record["totals"][key] for record in records.values()), default=0) for key in expected["totals"]}
        _equal(metrics["maxima"][category], maxima, f"Construction maxima {category}")
    if trace_required or construction["trace"]:
        _verify_construction_trace(instance, construction, contributors, fragments, component_at, directories, neighbors, rounds)
    return report


def _verify_construction_trace(instance, construction, contributors, fragments, component_at, directories, neighbors, rounds):
    trace = construction["trace"]
    _equal(len(trace), construction["metrics"]["totals"]["messages"], "Construction transcript length")
    observed = {stage: Counter(dict.fromkeys(COMMON, 0)) for stage in STAGES}
    presence, lookup, transferred, rank_deliveries = Counter(), Counter(), Counter(), Counter()
    ranks = {case: (instance["case_hosts"][case], case) for case in instance["cases"]}
    rank_snapshots = {}
    for iteration in range(1, rounds + 1):
        rank_snapshots[iteration] = ranks
        ranks = {case: min([ranks[case]] + [ranks[other] for other in neighbors[case]]) for case in ranks}
    for index, message in enumerate(trace, 1):
        _equal(message["sequence"], index, "Construction transcript sequence")
        stage, payload = message["stage"], message["payload"]
        sender, receiver = message["sender"], message["receiver"]
        _require(stage in observed, "Unknown transcript stage")
        colocated = sender["host"] == receiver["host"]
        _equal(message["colocated"], colocated, "Transcript colocation")
        _equal(message["component_id"], component_at[message["case_id"]]["id"], "Transcript component")
        _equal(message["payload_records"], 1, "Transcript payload count")
        terms = len(payload["terms"]) if message["kind"] == "shared_fragment" else 0
        _equal(message["coefficient_terms"], terms, "Transcript coefficient count")
        observed[stage].update({"messages": 1, "payload_records": 1, "coefficient_terms": terms,
                                "colocated_messages" if colocated else "cross_host_messages": 1})
        if message["kind"] == "presence_reply":
            key = (payload["row_id"], sender["host"])
            _equal(payload["present"], sender["host"] in contributors[payload["row_id"]], "Presence reply")
            _equal(set(payload), {"row_id", "present"}, "Presence reply privacy")
            presence[key] += 1
        elif message["kind"] == "lookup_request":
            lookup[(payload["id"], receiver["host"])] += 1
        elif message["kind"] == "shared_fragment":
            key = (payload["row_id"], sender["host"])
            _equal(payload["terms"], fragments[key], "Transferred fragment")
            transferred[key] += 1
        elif message["kind"] == "rank_transmission":
            iteration, case, other = message["stage_round"], sender["id"], receiver["id"]
            _require(iteration in rank_snapshots and other in neighbors[case], "Invalid rank delivery")
            _equal(payload["rank"], list(rank_snapshots[iteration][case]), "Synchronous election rank")
            rank_deliveries[(iteration, case, other)] += 1
    for stage in STAGES:
        _equal(dict(observed[stage]), {key: construction["metrics"]["stages"][stage][key] for key in COMMON}, f"Transcript {stage} counts")
    expected_lookups = Counter((request["id"], owner) for request in construction["requests"] for owner in directories[request["case_id"]])
    _equal(lookup, expected_lookups, "Lookup transcript coverage")
    _equal(presence, expected_lookups, "Presence transcript coverage")
    _equal(transferred, Counter(key for key in fragments if len(contributors[key[0]]) > 1), "Shared-fragment transcript coverage")
    _equal(rank_deliveries, Counter((iteration, case, other) for iteration in range(1, rounds + 1)
                                    for case, others in neighbors.items() for other in others), "Election transcript coverage")


def _verify_matching(instance, rows, construction, result, method, trace_required):
    check_matching_result(instance, rows, result)
    _equal(result["method"], method, "Matching method")
    expected_components = {component["id"]: component for component in construction["components"]}
    parts = {component["id"]: component for component in result["components"]}
    _equal(len(parts), len(result["components"]), "Unique matching components")
    _equal(set(parts), set(expected_components), "Matching component coverage")
    candidates = {candidate["id"]: candidate for candidate in instance["candidates"]}
    aggregates = Counter()
    global_selection = []
    for identifier, part in parts.items():
        expected = expected_components[identifier]
        for key in ("case_ids", "sources", "coordinator"):
            _equal(part[key], expected[key], f"Matching component {key}")
        members = set(expected["candidate_ids"])
        component_rows = [row for row in rows if row["terms"] and set(row["terms"]) <= members]
        subinstance = {"candidates": [candidates[variable] for variable in sorted(members)]}
        check_matching_result(subinstance, component_rows, part)
        if part["selected_ids"] is not None:
            global_selection.extend(part["selected_ids"])
        shared = [row for row in component_rows if len({candidates[variable]["owner"] for variable in row["terms"]}) > 1]
        interface = sorted({variable for row in shared for variable in row["terms"]})
        _equal(part["interface_ids"], interface, "Matching interface variables")
        _equal(part["shared_row_count"], len(shared), "Shared matching rows")
        _equal(part["local_row_count"], len(component_rows) - len(shared), "Local matching rows")
        _equal(part["candidate_count"], len(members), "Component candidate count")
        _equal(part["interface_variable_count"], len(interface), "Interface count")
        local_sizes = {}
        for source in part["sources"]:
            owned_rows = [row for row in component_rows
                          if {candidates[variable]["owner"] for variable in row["terms"]} == {source}]
            local_sizes[str(source)] = {
                "candidate_count": sum(candidates[variable]["owner"] == source for variable in members),
                "local_row_count": len(owned_rows),
                "local_coefficient_terms": sum(len(row["terms"]) for row in owned_rows),
                "interface_variable_count": sum(candidates[variable]["owner"] == source for variable in interface),
            }
        _equal(part["local_sizes"], local_sizes, "Source-local optimization model sizes")
        metrics = part["metrics"]
        _require(all(type(value) is int and value >= 0 for value in metrics.values()), "Matching counters must be nonnegative integers")
        for key, value in metrics.items():
            aggregates[key] = max(aggregates[key], value) if key == "max_unresolved_frontier" else aggregates[key] + value
        calls = part["solver_calls"]
        _equal(metrics["z3_checks"], sum(call["solver_started"] is True for call in calls), "Recorded optimizer invocations")
        if method == "distributed":
            count = len(part["sources"])
            for actual, expected_value, label in (
                (metrics["source_calls"], len(calls), "Source-call records"),
                (metrics["source_calls"], metrics["optimization_replies"], "Source replies"),
                (metrics["optimization_requests"], count * metrics["queried_nodes"], "Participating-source requests"),
                (metrics["pending_optimization_requests"], metrics["optimization_requests"] - metrics["optimization_replies"], "Pending source requests"),
                (metrics["queried_nodes"], metrics["fully_evaluated_nodes"] + metrics["partial_query_nodes"], "Query completion accounting"),
                (metrics["nodes_pruned_before_query"], metrics["bound_prunes_before_query"] + metrics["fully_fixed_shared_row_prunes"], "Pre-query prunes"),
                (metrics["exact_local_solves_completed"], metrics["local_optimal_replies"] + metrics["local_infeasible_replies"], "Exact local replies"),
                (metrics["interrupted_source_calls"], metrics["local_limited_replies"] + metrics["local_unknown_replies"], "Interrupted source calls"),
                (metrics["shared_rows_checked"], metrics["shared_rows_checked_prequery"] + metrics["shared_rows_checked_returned"], "Shared-row phases"),
                (metrics["retention_requests"], count * metrics["feasible_nodes"], "Retention requests"),
                (metrics["feasible_incumbents"], len(part["incumbent_history"]), "Incumbent records"),
            ):
                _equal(actual, expected_value, label)
            _require(metrics["visited_nodes"] >= metrics["queried_nodes"] + metrics["nodes_pruned_before_query"], "Visited-node accounting is inconsistent")
            _require(metrics["retention_confirmations"] <= metrics["retention_requests"], "Too many retention confirmations")
            for status in ("optimal", "infeasible", "limited", "unknown"):
                _equal(metrics[f"local_{status}_replies"], sum(call["status"] == status for call in calls), f"Local {status} replies")
            if "pending_retention_requests" in metrics:
                _equal(metrics["pending_retention_requests"], metrics["retention_requests"] - metrics["retention_confirmations"], "Pending retention requests")
            if trace_required or part["trace"]:
                _verify_search_trace(part, candidates, shared)
        else:
            _equal(metrics["central_solver_calls"], len(calls), "Central solver-call records")
    _equal(result["component_count"], len(parts), "Matching component count")
    empty = [row for row in rows if not row["terms"]]
    bad_empty = [row["id"] for row in empty if row["upper"] < 0]
    if bad_empty or any(part["status"] == "infeasible" for part in parts.values()):
        expected_status = "infeasible"
    elif all(part["status"] == "optimal" for part in parts.values()):
        expected_status = "optimal"
    elif any(part["status"] == "limited" for part in parts.values()):
        expected_status = "limited"
    else:
        expected_status = "unknown"
    _equal(result["status"], expected_status, "Aggregated matching status")
    complete = expected_status != "infeasible" and all(part["selected_ids"] is not None for part in parts.values())
    _equal(result["selected_ids"] is not None, complete, "Complete global incumbent availability")
    if complete:
        _equal(sorted(global_selection), sorted(result["selected_ids"]), "Global selected candidates")
    upper = None if expected_status == "infeasible" or any(part["upper_bound"] is None for part in parts.values()) else sum(
        (Fraction(part["upper_bound"]) for part in parts.values()), Fraction())
    _equal(Fraction(result["upper_bound"]) if result["upper_bound"] is not None else None, upper, "Aggregated upper bound")
    for record in [result, *parts.values()]:
        if record.get("lower_bound") is not None and record.get("upper_bound") is not None and record["status"] != "infeasible":
            difference = Fraction(record["upper_bound"]) - Fraction(record["lower_bound"])
            if "absolute_gap" in record:
                _equal(Fraction(record["absolute_gap"]), difference, "Exact absolute gap")
            if "relative_gap" in record:
                _equal(Fraction(record["relative_gap"]), difference / max(Fraction(1), abs(Fraction(record["lower_bound"]))), "Exact relative gap")
    aggregates["empty_rows_checked"] = len(empty)
    aggregates["violated_empty_rows"] = sum(row["upper"] < 0 for row in empty)
    for key, value in aggregates.items():
        _equal(result["metrics"][key], value, f"Aggregated matching counter {key}")
    _equal(result["metrics"]["event_emission_records"], len(result["selected_ids"] or []), "Final emitted records")
    if trace_required or result["trace"]:
        empty_records = [record for record in result["trace"] if record["event"] == "empty_row_checks"]
        _equal(len(empty_records), 1, "Global empty-row transcript record")
        _equal(empty_records[0]["row_ids"], [row["id"] for row in empty], "Empty-row transcript scope")
        _equal(empty_records[0]["violated_row_ids"], bad_empty, "Empty-row transcript violations")
        emitted = [record for record in result["trace"] if record["event"] == "event_emission"]
        _equal(sum(record["records"] for record in emitted), result["metrics"]["event_emission_records"], "Emission transcript count")
        _equal(sorted(variable for record in emitted for variable in record["selected_ids"]), sorted(result["selected_ids"] or []), "Emission transcript selection")
        for record in emitted:
            _equal(record["records"], len(record["selected_ids"]), "Emission record length")
            if method == "distributed":
                _require(all(candidates[variable]["owner"] == record["source"] for variable in record["selected_ids"]), "Source emitted another source's candidate")
    return {"status": result["status"], "components_checked": len(parts), "trace_checked": bool(trace_required or result["trace"])}


def _verify_search_trace(part, candidates, shared):
    nodes = part["trace"]
    metrics = part["metrics"]
    _equal(len(nodes), metrics["visited_nodes"], "Search transcript visited nodes")
    if not nodes:
        return
    counted = Counter()
    stack, next_node, maximum = [(0, {})], 1, 1
    by_outcome = {"pruned_inherited_bound": "bound_prunes_before_query",
                  "pruned_fully_fixed_shared_row": "fully_fixed_shared_row_prunes",
                  "pruned_local_bound": "bound_prunes_after_query",
                  "pruned_local_infeasibility": "local_infeasibility_prunes",
                  "interrupted_partial_query": "partial_query_nodes",
                  "interrupted_inexact_local_solve": "inexact_query_nodes",
                  "branched": "branch_operations", "feasible_incumbent": "feasible_incumbents"}
    for visit, node in enumerate(nodes, 1):
        _require(stack, "Search visited a node outside its unresolved frontier")
        expected_id, expected_fixings = stack.pop()
        _equal((node["node_id"], node["fixings"]), (expected_id, expected_fixings), "Depth-first zero-before-one traversal")
        _equal(node["visit"], visit, "Search visit sequence")
        outcome = node["outcome"]
        _require(outcome in by_outcome or outcome in ("interrupted_before_query", "interrupted_retention"), "Unknown search outcome")
        if outcome in by_outcome:
            counted[by_outcome[outcome]] += 1
        if node["requests"]:
            counted["queried_nodes"] += 1
            _equal([request["source"] for request in node["requests"]], part["sources"], "Search request participation")
        replies = node["replies"]
        counted["optimization_requests"] += len(node["requests"])
        counted["optimization_replies"] += len(replies)
        if node["requests"] and len(replies) == len(node["requests"]):
            counted["fully_evaluated_nodes"] += 1
        for request in node["requests"]:
            expected = {variable: value for variable, value in node["fixings"].items() if candidates[variable]["owner"] == request["source"]}
            _equal(request["fixings"], expected, "Source-owned fixed interface values")
            counted["fixed_values_sent"] += len(expected)
        _require(len({reply["source"] for reply in replies}) == len(replies), "Duplicate source reply")
        values = {}
        for reply in replies:
            _require(reply["source"] in part["sources"], "Unknown source reply")
            if reply["status"] == "optimal":
                expected = {variable for variable in part["interface_ids"] if candidates[variable]["owner"] == reply["source"]}
                _equal(set(reply["interface_values"]), expected, "Returned interface coverage")
                _require(all(type(value) is int and value in (0, 1) for value in reply["interface_values"].values()), "Nonbinary interface value")
                values.update(reply["interface_values"])
                counted["response_interface_values"] += len(expected)
            else:
                _require(not {"objective", "interface_values", "selection_id"} & reply.keys(), "Uncertified local reply was used as an exact result")
        if "local_optimum_sum" in node:
            _equal(Fraction(node["local_optimum_sum"]), sum((Fraction(reply["objective"]) for reply in replies), Fraction()), "Returned local optimum sum")
        for phase, available in (("prequery", node["fixings"]), ("returned", values)):
            key = f"{phase}_rows_checked"
            if key not in node:
                continue
            expected_rows = [row for row in shared if phase == "returned" or set(row["terms"]) <= available.keys()]
            _equal(node[key], [row["id"] for row in expected_rows], "Transcript checked shared rows")
            violated = [row["id"] for row in expected_rows if sum(value * available[variable] for variable, value in row["terms"].items()) > row["upper"]]
            _equal(node[f"{phase}_violated_rows"], violated, "Transcript violated shared rows")
            counted[f"shared_rows_checked_{phase}"] += len(expected_rows)
            counted["shared_rows_violated"] += len(violated)
        confirmations = node.get("retention_confirmations", [])
        if confirmations:
            counted["feasible_nodes"] += 1
            counted["retention_requests"] += len(part["sources"])
            counted["retention_confirmations"] += sum(item.get("confirmed") is True for item in confirmations)
            for confirmation, reply in zip(confirmations, replies):
                _equal((confirmation["source"], confirmation["selection_id"]), (reply["source"], reply["selection_id"]), "Retained local selection")
        if outcome == "branched":
            branch = next(variable for variable in part["interface_ids"] if variable not in node["fixings"])
            _equal(node["branch_variable"], branch, "Fixed branch order")
            _equal(node["child_node_ids"], [next_node, next_node + 1], "Child node IDs")
            stack.extend([(next_node + 1, node["fixings"] | {branch: 1}), (next_node, node["fixings"] | {branch: 0})])
            next_node += 2
            maximum = max(maximum, len(stack))
        elif outcome.startswith("interrupted_"):
            stack.append((node["node_id"], node["fixings"]))
            _equal(visit, len(nodes), "Interrupted transcript termination")
    for key in ("queried_nodes", "optimization_requests", "optimization_replies", "fully_evaluated_nodes", "fixed_values_sent",
                "response_interface_values", "shared_rows_checked_prequery", "shared_rows_checked_returned", "shared_rows_violated",
                "retention_requests", "retention_confirmations", "feasible_nodes", *by_outcome.values()):
        _equal(metrics[key], counted[key], f"Search transcript counter {key}")
    _equal(metrics["max_unresolved_frontier"], maximum, "Maximum unresolved frontier")
    _equal([(node["node_id"], node["fixings"]) for node in part["unresolved_nodes"]], stack, "Remaining search frontier")
    _equal(part["unresolved_node_count"], len(stack), "Remaining search node count")


def _verify_upload(instance, metrics):
    candidates = instance["candidates"]
    by_id = {candidate["id"]: candidate for candidate in candidates}
    exclusions = [row for row in instance["given_rows"] if row["kind"] != "assignment"]
    expected = {"upload_messages": len(instance["sources"]), "candidate_records": len(candidates),
                "score_values": len(candidates), "given_exclusion_rows": len(exclusions),
                "given_coefficient_terms": sum(len(row["terms"]) for row in exclusions),
                "per_source": {str(source): {
                    "candidate_records": sum(candidate["owner"] == source for candidate in candidates),
                    "given_exclusion_rows": sum(bool(row["terms"]) and by_id[next(iter(row["terms"]))]["owner"] == source for row in exclusions),
                } for source in instance["sources"]}}
    for key, value in expected.items():
        _equal(metrics[key], value, f"Central upload {key}")


def _verify_plan_condition(instance, plan, cache):
    seed = plan["seed"]
    bridge_ids = {bridge["id"] for bridge in plan["bridges"]}
    base = deepcopy(instance)
    base["given_rows"] = [row for row in base["given_rows"] if row["id"] not in bridge_ids]
    base["sources"], base["case_hosts"] = [0], {case: 0 for case in base["cases"]}
    for candidate in base["candidates"]:
        candidate["owner"] = 0
    model = {key: base[key] for key in ("cases", "candidates", "given_rows", "prerequisites", "occurrence_bounds", "gt_selected")}
    digest = hashlib.sha256(json.dumps(model, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if seed not in cache:
        cache[seed] = (digest, validate_plan(base, plan))
    _equal(digest, cache[seed][0], "Fixed population and intra-case model across conditions")
    sources = len(instance["sources"])
    _require(plan["max_sources"] % sources == 0, "Saved source count does not divide max_sources")
    width = plan["max_sources"] // sources
    for candidate in instance["candidates"]:
        _equal(candidate["owner"], plan["observation_owners"][candidate["observation_id"]] // width, "Full-plan candidate ownership")
    _equal(instance["case_hosts"], {case: plan["case_hosts"][case] // width for case in instance["cases"]}, "Nested case-agent hosts")
    count = instance["metadata"]["component_count"]
    expected = [{"id": bridge["id"], "kind": "exclusion", "terms": bridge["terms"], "upper": bridge["upper"], "case_id": None}
                for bridge in plan["bridges"][:len(instance["cases"]) - count]]
    _equal([row for row in instance["given_rows"] if row["id"] in bridge_ids], expected, "Nested bridge prefix")


def verify_study(path) -> dict:
    """Verify a complete saved study, raising ValueError on a failed check."""
    root = Path(path).resolve()
    manifest = _manifest(root)
    protocol, summaries = _read(root / "protocol.json"), _read(root / "summary.json")
    _require(isinstance(summaries, list) and summaries, "Study must contain at least one completed condition")
    trace_required = protocol.get("arguments", {}).get("trace", False)
    plans = {plan["seed"]: plan for plan in (_read(root / name) for name in manifest
                                          if PurePosixPath(name).name.startswith("plan_seed") and name.endswith(".json.gz"))}
    plan_cache, model_hashes, placements, gt_scores, optima = {}, {}, {}, {}, {}
    results, names, expected_csv = [], set(), []
    from benchmark import flatten_counts
    for summary in summaries:
        name = summary["condition"]
        _require(len(PurePosixPath(name).parts) == 1 and name not in names, "Duplicate or unsafe condition name")
        names.add(name)
        folder = _safe_path(root, name)
        saved_summary = _read(folder / "summary.json")
        _equal({key: value for key, value in summary.items() if key != "condition"}, saved_summary, "Condition summary copies")
        instance = _read(folder / "instance.json.gz")
        _equal(summary["metadata"], instance.get("metadata", {}), "Saved instance metadata")
        construction = _read(folder / "construction.json.gz")
        central_rows = _read(folder / "central_rows.json.gz")
        rows = encode_centrally(instance)
        _equal(central_rows, rows, "Saved central rows")
        construction_report = _verify_construction(instance, construction, rows, trace_required)
        _equal(summary["checks"]["construction"], construction_report, "Saved construction check")
        upload = _read(folder / "central_upload.json")
        _verify_upload(instance, upload)
        components = components_from_rows(instance, rows)
        for key, value in (("cases", len(instance["cases"])), ("sources", len(instance["sources"])),
                           ("candidates", len(instance["candidates"])), ("components", len(components)),
                           ("component_case_sizes", [len(component["case_ids"]) for component in components]),
                           ("component_candidate_sizes", [len(component["candidate_ids"]) for component in components])):
            _equal(summary[key], value, f"Summary {key}")
        _equal(summary["source_candidate_counts"], dict(Counter(str(candidate["owner"]) for candidate in instance["candidates"])), "Summary source sizes")
        digest = numerical_fingerprint(instance, rows)
        _equal(summary["numerical_model_sha256"], digest, "Numerical model fingerprint")
        metadata = instance.get("metadata", {})
        seed, sources, count = metadata.get("seed", 0), len(instance["sources"]), len(components)
        key = (seed, count)
        _equal(model_hashes.setdefault(key, digest), digest, "Same numerical model across K")
        owner_map = {candidate["id"]: candidate["owner"] for candidate in instance["candidates"]}
        _equal(placements.setdefault((seed, sources), (owner_map, instance["case_hosts"])),
               (owner_map, instance["case_hosts"]), "Ownership and hosts fixed across C")
        if seed in plans:
            _verify_plan_condition(instance, plans[seed], plan_cache)
            _equal(count, metadata["component_count"], "Requested component prefix count")
        gt_score = None
        if instance.get("gt_selected"):
            truth = validate_selection(instance, rows, instance["gt_selected"])
            _require(truth["feasible"], "Saved GT violates the model")
            _equal(summary["checks"]["ground_truth"], truth, "Saved GT check")
            gt_score = Fraction(truth["objective"])
            if "gt_score" in metadata:
                _equal(Fraction(metadata["gt_score"]), gt_score, "Metadata exact GT score")
            _equal(gt_scores.setdefault(seed, gt_score), gt_score, "GT score across conditions")
        objects = {"construction": construction["metrics"], "central_upload": upload}
        matching, reports = {}, {}
        for method in ("central", "distributed"):
            result_path = folder / f"{method}_matching.json.gz"
            if not result_path.exists():
                _equal(summary[f"{method}_status"], "not_run", f"Missing {method} matching result")
                continue
            result = _read(result_path)
            reports[method] = _verify_matching(instance, rows, construction, result, method, trace_required)
            _equal(summary["checks"][f"{method}_matching"], check_matching_result(instance, rows, result), f"Saved {method} matching check")
            matching[method] = result
            for field in ("status", "objective"):
                _equal(summary[f"{method}_{field}"], result[field], f"Summary {method} {field}")
            if result["status"] == "optimal":
                record_optimum(optima, seed, count, result["objective"])
            objects[f"{method}_matching"] = result["metrics"]
        if matching:
            _equal(set(matching), {"central", "distributed"}, "Both comparison methods must be saved")
            comparison = check_comparison(matching["central"], matching["distributed"], gt_score)
            if "optimal_score_agreement" in summary["checks"]:
                _equal(summary["checks"]["optimal_score_agreement"], comparison, "Saved matching comparison")
        exhaustive = None
        observations = Counter(candidate["observation_id"] for candidate in instance["candidates"])
        possibilities = 1
        for size in observations.values():
            possibilities *= size + 1
        if matching and len(observations) <= 10 and possibilities <= 100_000:
            exhaustive = exhaustive_optimum(instance, rows, max_assignments=100_000)
            for result in matching.values():
                if result["status"] in ("optimal", "infeasible"):
                    _equal(result["status"], exhaustive["status"], "Exhaustive termination status")
                    _equal(result["objective"], exhaustive["objective"], "Exhaustive exact optimum")
                if exhaustive["objective"] is not None:
                    optimum = Fraction(exhaustive["objective"])
                    _require(result["lower_bound"] is None or Fraction(result["lower_bound"]) <= optimum, "Lower bound exceeds exhaustive optimum")
                    _require(result["upper_bound"] is None or Fraction(result["upper_bound"]) >= optimum, "Upper bound excludes exhaustive optimum")
        for stage, values in objects.items():
            expected_csv.extend((name, stage, metric, str(value)) for metric, value in flatten_counts(values))
        results.append({"condition": name, "construction": "PASS", "matching": reports,
                        "exhaustive_assignments_checked": exhaustive["assignments_checked"] if exhaustive else 0})
    with (root / "counts.csv").open(newline="", encoding="utf-8") as stream:
        saved_csv = [(row["condition"], row["stage"], row["metric"], row["value"]) for row in csv.DictReader(stream)]
    _equal(Counter(saved_csv), Counter(expected_csv), "Exported counter CSV")
    _equal(set(plans), set(plan_cache), "Every saved plan is linked to a verified condition")
    artifact_conditions = {PurePosixPath(name).parts[0] for name in manifest
                           if len(PurePosixPath(name).parts) == 2 and PurePosixPath(name).name == "instance.json.gz"}
    _equal(names, artifact_conditions, "Every saved condition is present in the study summary")
    arguments = protocol.get("arguments", {})
    if not arguments.get("instance") and all(key in arguments for key in ("seeds", "sources", "components")):
        expected_conditions = set(product(arguments["seeds"], arguments["sources"], arguments["components"]))
        actual_conditions = {(summary["metadata"]["seed"], summary["sources"], summary["components"]) for summary in summaries}
        _equal(actual_conditions, expected_conditions, "Declared grid condition coverage")
        _equal(len(summaries), len(expected_conditions), "Unique declared grid conditions")
    for seed, (_, check) in plan_cache.items():
        if "validation" in plans[seed]:
            _equal(plans[seed]["validation"], check, "Saved plan validation report")
        check_path = root / f"plan_checks_seed{seed}.json"
        if check_path.exists():
            _equal(_read(check_path), check, "Saved independent plan checks")
    return {"status": "PASS", "study": str(root), "files_verified": len(manifest),
            "conditions_verified": len(results), "plans_verified": len(plan_cache),
            "plan_checks": {str(seed): check for seed, (_, check) in plan_cache.items()},
            "conditions": results,
            "scope": "Offline standard-library verification of integrity, model equality, exact feasibility/objectives, witness certificates, bounds consistency, ownership, and logical counters; available transcripts are checked.",
            "optimality_scope": "Small saved models are exhaustively enumerated. For larger models, saved Z3 optimality claims are trusted solver claims, not independently reproved optimality certificates. No solver or construction protocol was rerun."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", nargs="?", type=Path, default=ROOT / "results/benchmark_example")
    args = parser.parse_args(argv)
    try:
        report = verify_study(args.study)
    except (ValueError, OSError, KeyError, TypeError, StopIteration) as error:
        parser.exit(1, f"Verification failed: {error}\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


if __name__ == "__main__":
    main()
