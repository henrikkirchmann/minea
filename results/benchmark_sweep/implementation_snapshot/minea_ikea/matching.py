"""Sequential, auditable execution of the paper's distributed matching protocol.

This is a logical-message simulator, not a networking or parallel-speedup model.
Sources retain their complete selections; the coordinator receives only exact
local scores, interface values, and selection identifiers.  Shared rows are
omitted from local solves.  Search begins without an incumbent, uses an infinite
root bound, and visits the zero child first in fixed candidate-ID order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
import time
from typing import Any, Mapping

from .solver import (
    fraction_string, make_deadline, prepare_model,
    solve_exact, solver_provenance, trivial_upper_bound,
)


_COUNT_NAMES = (
    "visited_nodes", "nodes_pruned_before_query", "bound_prunes_before_query",
    "fully_fixed_shared_row_prunes", "queried_nodes", "fully_evaluated_nodes",
    "partial_query_nodes", "inexact_query_nodes", "branch_operations",
    "max_unresolved_frontier", "source_calls", "z3_checks", "exact_local_solves_completed",
    "local_optimal_replies", "local_infeasible_replies", "local_limited_replies",
    "local_unknown_replies", "interrupted_source_calls", "optimization_requests",
    "optimization_replies", "pending_optimization_requests", "fixed_values_sent",
    "response_interface_values", "shared_rows_checked", "shared_rows_violated",
    "shared_rows_checked_prequery", "shared_rows_checked_returned",
    "bound_prunes_after_query", "local_infeasibility_prunes", "feasible_nodes",
    "feasible_incumbents", "retention_requests", "retention_confirmations",
    "pending_retention_requests",
    "event_emission_records", "central_solver_calls", "empty_rows_checked",
    "violated_empty_rows",
)


def _metrics() -> dict[str, int]:
    return dict.fromkeys(_COUNT_NAMES, 0)


def _get(value: Any, name: str) -> Any:
    return value[name] if isinstance(value, Mapping) else getattr(value, name)


def _gap(lower: Fraction | None, upper: Fraction | None, status: str) -> dict:
    finite = lower is not None and upper is not None and status != "infeasible"
    if finite and upper < lower:
        raise RuntimeError("Certified upper bound lies below a feasible incumbent")
    absolute = upper - lower if finite else None
    return {
        "absolute_gap": fraction_string(absolute),
        "relative_gap": fraction_string(absolute / max(Fraction(1), abs(lower))) if finite else None,
        "gap_definition": "(upper_bound - lower_bound) / max(1, abs(lower_bound))",
        "gap_status": "infeasible" if status == "infeasible" else "finite" if finite else "no_incumbent_or_infinite_upper_bound",
    }


def _bound_fields(lower: Fraction | None, upper: Fraction | None, status: str) -> dict:
    return {
        "objective": fraction_string(lower), "lower_bound": fraction_string(lower),
        "upper_bound": fraction_string(upper),
        "lower_bound_kind": "finite" if lower is not None else "negative_infinity",
        "upper_bound_kind": "negative_infinity" if status == "infeasible" else "finite" if upper is not None else "positive_infinity",
        **_gap(lower, upper, status),
    }


def _prepare(instance: Mapping, rows: Any, components: Any) -> tuple[list[dict], list[dict], list[dict]]:
    """Validate the supplied partition and derive row locality from true owners."""
    candidates, rows, _ = prepare_model(instance["candidates"], rows)
    by_id = {candidate["id"]: candidate for candidate in candidates}
    cases = set(instance["cases"])
    if len(cases) != len(instance["cases"]):
        raise ValueError("Duplicate case IDs")
    source_ids = set(instance["sources"])
    for candidate in candidates:
        if candidate["owner"] not in source_ids or candidate["case_id"] not in cases:
            raise ValueError("Candidate owner or case is absent from the instance")
    prepared = []
    seen_cases, seen_candidates, seen_components = set(), set(), set()
    for original in components:
        component = dict(original)
        identifier = component["id"]
        if not isinstance(identifier, str) or identifier in seen_components:
            raise ValueError("Component IDs must be unique strings")
        seen_components.add(identifier)
        component_cases = set(component["case_ids"])
        component_ids = set(component["candidate_ids"])
        if len(component_cases) != len(component["case_ids"]) or len(component_ids) != len(component["candidate_ids"]):
            raise ValueError("Repeated case or candidate inside a component")
        if seen_cases & component_cases or seen_candidates & component_ids:
            raise ValueError("Components must be a disjoint partition")
        if not component_cases <= cases or not component_ids <= by_id.keys():
            raise ValueError("Component contains an unknown case or candidate")
        if component_ids != {candidate["id"] for candidate in candidates if candidate["case_id"] in component_cases}:
            raise ValueError("A component must contain every candidate of its cases")
        sources = sorted(set(component["sources"]))
        owners = {by_id[candidate_id]["owner"] for candidate_id in component_ids}
        if set(sources) != owners:
            raise ValueError("Participating sources must be exactly the owners of component candidates")
        seen_cases.update(component_cases)
        seen_candidates.update(component_ids)
        component.update(
            case_ids=sorted(component_cases), candidate_ids=sorted(component_ids), sources=sources,
            candidates=[by_id[candidate_id] for candidate_id in sorted(component_ids)],
            rows=[], shared_rows=[], local_rows={source: [] for source in sources},
        )
        prepared.append(component)
    if seen_cases != cases or seen_candidates != by_id.keys():
        raise ValueError("Components must cover every case and candidate, including empty cases")
    # Coordinator-derived IDs change when ownership/hosts are coarsened across
    # K.  Ordering by those IDs would change the timeout prefix of an otherwise
    # identical numerical model.  Both methods instead use canonical case sets.
    prepared.sort(key=lambda component: tuple(component["case_ids"]))
    component_by_candidate = {identifier: component for component in prepared for identifier in component["candidate_ids"]}
    empty_rows = []
    for row in rows:
        if not row["terms"]:
            empty_rows.append(row)
            continue
        placements = {component_by_candidate[identifier]["id"] for identifier in row["terms"]}
        if len(placements) != 1:
            raise ValueError(f"Row {row['id']!r} crosses supplied components")
        component = component_by_candidate[next(iter(row["terms"]))]
        component["rows"].append(row)
        owners = {by_id[identifier]["owner"] for identifier in row["terms"]}
        if len(owners) == 1:
            component["local_rows"][next(iter(owners))].append(row)
        else:
            component["shared_rows"].append(row)
    for component in prepared:
        component["interface_ids"] = sorted({identifier for row in component["shared_rows"] for identifier in row["terms"]})
    return candidates, empty_rows, prepared


def _base(component: dict) -> dict:
    interface = set(component["interface_ids"])
    return {
        "id": component["id"], "case_ids": component["case_ids"],
        "sources": component["sources"], "coordinator": component.get("coordinator"),
        "candidate_count": len(component["candidates"]),
        "local_row_count": sum(len(rows) for rows in component["local_rows"].values()),
        "shared_row_count": len(component["shared_rows"]),
        "interface_variable_count": len(interface), "interface_ids": component["interface_ids"],
        "local_sizes": {
            str(source): {
                "candidate_count": sum(candidate["owner"] == source for candidate in component["candidates"]),
                "local_row_count": len(component["local_rows"][source]),
                "local_coefficient_terms": sum(len(row["terms"]) for row in component["local_rows"][source]),
                "interface_variable_count": sum(candidate["owner"] == source and candidate["id"] in interface for candidate in component["candidates"]),
            } for source in component["sources"]
        },
    }


@dataclass
class _Budget:
    deadline: float | None
    node_limit: int | None
    visited: int = 0

    def reason(self) -> str | None:
        if self.deadline is not None and time.monotonic() >= self.deadline:
            return "condition_time_limit"
        if self.node_limit is not None and self.visited >= self.node_limit:
            return "condition_node_limit"
        return None


@dataclass
class _Node:
    identifier: int
    fixings: dict[str, int]
    upper: Fraction | None  # None means +infinity, never zero or unknown optimum.


@dataclass
class _Source:
    identifier: int
    candidates: list[dict]
    rows: list[dict]
    interface_ids: list[str]
    current: tuple[str, tuple[str, ...]] | None = None
    retained: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def query(self, token: str, fixings: dict, deadline: float | None) -> tuple[dict, dict]:
        result = solve_exact(self.candidates, self.rows, fixings=fixings, deadline=deadline)
        reply = {"source": self.identifier, "status": result["status"], "reason": result["reason"]}
        if result["status"] == "optimal" and result["certified_optimal"]:
            # Copy before any subsequent optimization can replace current state.
            self.current = (token, tuple(result["selected_ids"]))
            selected = set(self.current[1])
            reply.update(
                objective=result["objective"], selection_id=token,
                interface_values={identifier: int(identifier in selected) for identifier in self.interface_ids},
            )
        return reply, result

    def retain(self, token: str) -> dict:
        if self.current is None or self.current[0] != token:
            raise RuntimeError("A retention request did not identify the stored local selection")
        self.retained[token] = tuple(self.current[1])
        return {"source": self.identifier, "selection_id": token, "confirmed": True}

    def emit(self, token: str) -> list[str]:
        """Actual protocol event emission; call only after global feasibility."""
        return list(self.retained[token])

    def retained_snapshot(self, token: str) -> list[str]:
        """Observer-only result inspection, with no protocol emission action."""
        return list(self.retained[token])


def _record_checks(rows: list[dict], values: dict[str, int], metrics: dict, phase: str) -> tuple[list[str], list[str]]:
    checked, violated = [], []
    for row in rows:
        checked.append(row["id"])
        if sum(coefficient * values[identifier] for identifier, coefficient in row["terms"].items()) > row["upper"]:
            violated.append(row["id"])
    metrics["shared_rows_checked"] += len(checked)
    metrics["shared_rows_violated"] += len(violated)
    metrics[f"shared_rows_checked_{phase}"] += len(checked)
    return checked, violated


def _distributed_component(component: dict, budget: _Budget, epoch: str, want_trace: bool) -> dict:
    metrics = _metrics()
    metrics["max_unresolved_frontier"] = 1
    candidates_by_source = {source: [] for source in component["sources"]}
    owners = {}
    for candidate in component["candidates"]:
        candidates_by_source[candidate["owner"]].append(candidate)
        owners[candidate["id"]] = candidate["owner"]
    interfaces_by_source = {source: [] for source in component["sources"]}
    for identifier in component["interface_ids"]:
        interfaces_by_source[owners[identifier]].append(identifier)
    sources = {
        source: _Source(
            source, candidates_by_source[source], component["local_rows"][source],
            interfaces_by_source[source],
        ) for source in component["sources"]
    }
    stack = [_Node(0, {}, None)]
    next_node = 1
    incumbent = None
    incumbent_tokens = {}
    incumbent_history, transcript, solver_calls = [], [], []
    root_relaxation = None
    stop_reason = None
    stop_status = None
    while stack:
        if budget.reason() is not None:
            stop_reason, stop_status = budget.reason(), "limited"
            break
        node = stack.pop()
        budget.visited += 1
        metrics["visited_nodes"] += 1
        record = {
            "event": "node", "epoch": epoch, "component_id": component["id"],
            "node_id": node.identifier, "visit": metrics["visited_nodes"],
            "fixings": dict(node.fixings), "inherited_upper_bound": fraction_string(node.upper),
            "inherited_upper_bound_kind": "finite" if node.upper is not None else "positive_infinity",
            "incumbent_before": fraction_string(incumbent), "requests": [], "replies": [],
        }
        if want_trace:
            transcript.append(record)
        if incumbent is not None and node.upper is not None and node.upper <= incumbent:
            metrics["nodes_pruned_before_query"] += 1
            metrics["bound_prunes_before_query"] += 1
            record["outcome"] = "pruned_inherited_bound"
            continue
        fixed_rows = [row for row in component["shared_rows"] if row["terms"].keys() <= node.fixings.keys()]
        checked, violated = _record_checks(fixed_rows, node.fixings, metrics, "prequery")
        record.update(prequery_rows_checked=checked, prequery_violated_rows=violated)
        if violated:
            metrics["nodes_pruned_before_query"] += 1
            metrics["fully_fixed_shared_row_prunes"] += 1
            record["outcome"] = "pruned_fully_fixed_shared_row"
            continue
        if budget.deadline is not None and time.monotonic() >= budget.deadline:
            stack.append(node)
            stop_reason, stop_status = "condition_time_limit", "limited"
            record["outcome"] = "interrupted_before_query"
            break

        # Dispatch ALL participating-source requests before sequential execution.
        # A deadline can leave sent requests pending; sent and replied counts
        # therefore remain distinct on partial nodes.
        requests = []
        for source, state in sources.items():
            owned = {candidate["id"] for candidate in state.candidates}
            fixed = {identifier: value for identifier, value in node.fixings.items() if identifier in owned}
            requests.append({"epoch": epoch, "component_id": component["id"], "node_id": node.identifier, "source": source, "fixings": fixed})
        metrics["queried_nodes"] += 1
        metrics["optimization_requests"] += len(requests)
        metrics["fixed_values_sent"] += sum(len(request["fixings"]) for request in requests)
        record["requests"] = requests
        replies = []
        for request in requests:
            if budget.deadline is not None and time.monotonic() >= budget.deadline:
                break
            source = request["source"]
            token = f"{epoch}/{component['id']}/node:{node.identifier}/source:{source}"
            metrics["source_calls"] += 1
            reply, solution = sources[source].query(token, request["fixings"], budget.deadline)
            reply.update(epoch=epoch, component_id=component["id"], node_id=node.identifier)
            replies.append(reply)
            metrics["optimization_replies"] += 1
            metrics["z3_checks"] += int(solution["solver_started"])
            status = reply["status"]
            metrics[f"local_{status}_replies"] += 1
            if status == "infeasible" or (status == "optimal" and solution["certified_optimal"]):
                metrics["exact_local_solves_completed"] += 1
            else:
                metrics["interrupted_source_calls"] += 1
            metrics["response_interface_values"] += len(reply.get("interface_values", {}))
            solver_calls.append({
                "node_id": node.identifier, "source": source, "status": status,
                "reason": solution["reason"], "solver_started": solution["solver_started"],
                "elapsed_seconds": solution["elapsed_seconds"],
                "statistics": solution["solver_statistics"],
                "optimality_certificate": solution["optimality_certificate"],
            })
        record["replies"] = replies
        if len(replies) < len(requests):
            metrics["partial_query_nodes"] += 1
            stack.append(node)
            stop_reason, stop_status = "condition_time_limit_pending_source_requests", "limited"
            record["outcome"] = "interrupted_partial_query"
            break
        metrics["fully_evaluated_nodes"] += 1
        if any(reply["status"] == "infeasible" for reply in replies):
            metrics["local_infeasibility_prunes"] += 1
            record["outcome"] = "pruned_local_infeasibility"
            continue
        incomplete = [reply for reply in replies if reply["status"] != "optimal" or "selection_id" not in reply]
        if incomplete:
            metrics["inexact_query_nodes"] += 1
            stack.append(node)
            stop_status = "limited" if any(reply["status"] == "limited" for reply in incomplete) else "unknown"
            stop_reason = "local_solve_without_exact_certificate"
            record["outcome"] = "interrupted_inexact_local_solve"
            break
        summed = sum((Fraction(reply["objective"]) for reply in replies), Fraction())
        node.upper = summed if node.upper is None else min(node.upper, summed)
        if node.identifier == 0:
            root_relaxation = summed
        record.update(local_optimum_sum=str(summed), tightened_upper_bound=str(node.upper))
        if incumbent is not None and node.upper <= incumbent:
            metrics["bound_prunes_after_query"] += 1
            record["outcome"] = "pruned_local_bound"
            continue
        interface_values = {identifier: value for reply in replies for identifier, value in reply["interface_values"].items()}
        checked, violated = _record_checks(component["shared_rows"], interface_values, metrics, "returned")
        record.update(returned_rows_checked=checked, returned_violated_rows=violated)
        if not violated:
            if summed > node.upper:
                raise RuntimeError("A feasible local combination exceeds its inherited certified bound")
            metrics["feasible_nodes"] += 1
            metrics["retention_requests"] += len(sources)
            confirmations = [sources[reply["source"]].retain(reply["selection_id"]) for reply in replies]
            confirmed = sum(
                confirmation.get("confirmed") is True
                and confirmation.get("source") == reply["source"]
                and confirmation.get("selection_id") == reply["selection_id"]
                for confirmation, reply in zip(confirmations, replies)
            )
            metrics["retention_confirmations"] += confirmed
            record["retention_confirmations"] = confirmations
            if confirmed != len(sources):
                stack.append(node)
                stop_status, stop_reason = "unknown", "retention_not_confirmed_by_every_source"
                record["outcome"] = "interrupted_retention"
                break
            # Install only after EVERY source has confirmed this exact snapshot.
            incumbent = summed
            incumbent_tokens = {reply["source"]: reply["selection_id"] for reply in replies}
            metrics["feasible_incumbents"] += 1
            incumbent_history.append({"node_id": node.identifier, "visit": metrics["visited_nodes"], "objective": str(incumbent), "selection_ids": {str(source): token for source, token in incumbent_tokens.items()}})
            record.update(outcome="feasible_incumbent", retention_confirmations=confirmations, incumbent_after=str(incumbent))
            continue
        branch = next((identifier for identifier in component["interface_ids"] if identifier not in node.fixings), None)
        if branch is None:
            raise RuntimeError("A fully fixed violated shared row escaped the prequery check")
        zero = _Node(next_node, {**node.fixings, branch: 0}, node.upper)
        one = _Node(next_node + 1, {**node.fixings, branch: 1}, node.upper)
        next_node += 2
        stack.extend([one, zero])
        metrics["branch_operations"] += 1
        metrics["max_unresolved_frontier"] = max(metrics["max_unresolved_frontier"], len(stack))
        record.update(outcome="branched", branch_variable=branch, child_node_ids=[zero.identifier, one.identifier])

    metrics["pending_optimization_requests"] = metrics["optimization_requests"] - metrics["optimization_replies"]
    metrics["pending_retention_requests"] = metrics["retention_requests"] - metrics["retention_confirmations"]
    if not stack:
        status = "optimal" if incumbent is not None else "infeasible"
        reason = "search_exhausted"
        upper = incumbent
    else:
        status, reason = stop_status or "unknown", stop_reason or "unresolved_search"
        upper = None if any(node.upper is None for node in stack) else max([node.upper for node in stack] + ([incumbent] if incumbent is not None else []))
    selected = None if incumbent is None else sorted(identifier for source, token in incumbent_tokens.items() for identifier in sources[source].retained_snapshot(token))
    return {
        **_base(component), "status": status, "reason": reason,
        "selected_ids": selected, **_bound_fields(incumbent, upper, status),
        "root_upper_bound": None, "root_upper_bound_kind": "positive_infinity",
        "root_relaxation_bound": fraction_string(root_relaxation),
        "incumbent_history": incumbent_history, "metrics": metrics, "trace": transcript,
        "solver_calls": solver_calls,
        # Runtime-only state is consumed and removed by _aggregate.  It allows
        # actual emission to wait until a complete feasible global log exists.
        "_emission_sources": [(sources[source], token) for source, token in incumbent_tokens.items()],
        "unresolved_node_count": len(stack),
        "unresolved_nodes": [{"node_id": node.identifier, "fixings": node.fixings, "upper_bound": fraction_string(node.upper), "upper_bound_kind": "finite" if node.upper is not None else "positive_infinity"} for node in stack],
    }


def _unstarted(component: dict, reason: str, *, status: str = "limited", central: bool = False) -> dict:
    upper = trivial_upper_bound(component["candidates"]) if central else None
    return {
        **_base(component), "status": status, "reason": reason, "selected_ids": None,
        **_bound_fields(None, upper, status), "metrics": _metrics(), "trace": [],
        "solver_calls": [], "incumbent_history": [], "unresolved_node_count": 1,
        "unresolved_nodes": [{"node_id": 0, "fixings": {}, "upper_bound": fraction_string(upper), "upper_bound_kind": "finite" if upper is not None else "positive_infinity"}],
        "root_upper_bound": fraction_string(upper), "root_upper_bound_kind": "finite" if upper is not None else "positive_infinity",
        "root_relaxation_bound": None,
    }


def _aggregate(method: str, components: list[dict], empty_rows: list[dict], started: float, want_trace: bool, provenance: dict) -> dict:
    bad_empty = [row["id"] for row in empty_rows if row["upper"] < 0]
    if bad_empty or any(component["status"] == "infeasible" for component in components):
        status = "infeasible"
    elif all(component["status"] == "optimal" for component in components):
        status = "optimal"
    elif any(component["status"] == "limited" for component in components):
        status = "limited"
    else:
        status = "unknown"
    feasible = status != "infeasible" and all(component["selected_ids"] is not None for component in components)
    selected = sorted(identifier for component in components for identifier in component["selected_ids"]) if feasible else None
    # Coordinators know component incumbent scores, not private candidate scores.
    # The separate reference verifier recomputes the emitted selection's score.
    lower = sum((Fraction(component["objective"]) for component in components), Fraction()) if feasible else None
    upper = None if status == "infeasible" or any(component["upper_bound"] is None for component in components) else sum((Fraction(component["upper_bound"]) for component in components), Fraction())
    emissions = []
    for component in components:
        emission_sources = component.pop("_emission_sources", [])
        if not feasible:
            continue
        if method == "distributed":
            emitted = []
            for source, token in emission_sources:
                records = source.emit(token)
                emitted.extend(records)
                component["metrics"]["event_emission_records"] += len(records)
                emissions.append({"event": "event_emission", "component_id": component["id"], "source": source.identifier, "selection_id": token, "records": len(records), "selected_ids": records})
            if sorted(emitted) != component["selected_ids"]:
                raise RuntimeError("Actual event emission differs from the retained incumbent")
        else:
            component["metrics"]["event_emission_records"] = len(component["selected_ids"])
            emissions.append({"event": "event_emission", "component_id": component["id"], "emitter": "central", "records": len(component["selected_ids"]), "selected_ids": component["selected_ids"]})
    metrics = _metrics()
    for component in components:
        for key, value in component["metrics"].items():
            metrics[key] = max(metrics[key], value) if key == "max_unresolved_frontier" else metrics[key] + value
    metrics["empty_rows_checked"] = len(empty_rows)
    metrics["violated_empty_rows"] = len(bad_empty)
    transcript = []
    if want_trace:
        transcript.append({"event": "empty_row_checks", "row_ids": [row["id"] for row in empty_rows], "violated_row_ids": bad_empty})
        transcript.extend(record for component in components for record in component["trace"])
        transcript.extend(emissions)
    return {
        "method": method, "status": status, "selected_ids": selected,
        **_bound_fields(lower, upper, status), "components": components,
        "component_count": len(components), "metrics": metrics, "trace": transcript,
        "empty_row_violations": bad_empty, "elapsed_seconds": time.monotonic() - started,
        "solver_provenance": provenance,
        "component_execution_order_policy": "lexicographic tuple of sorted case IDs; independent of component IDs, coordinator hosts, source placement, and K",
        "component_execution_order": [component["case_ids"] for component in components],
        "metric_conventions": {
            "unit": "logical actions and records, not network packets or bytes",
            "source_calls": "started source query functions, including interrupted calls",
            "z3_checks": "actual optimizer.check invocations",
            "fully_evaluated_nodes": "nodes for which every participating source returned a reply",
            "pending_optimization_requests": "sent requests without replies at termination",
            "fixed_values_sent": "only the recipient source's owned fixed interface values",
            "response_interface_values": "all interface values in certified-optimal source replies",
            "max_unresolved_frontier": "maximum frontier in any one sequentially searched component",
            "event_emission_records": "final retained selections emitted only when all components supply a feasible global selection",
            "solver_statistics": "kept separately in components[*].solver_calls, never protocol counters",
        },
    }


def match_distributed(instance: Mapping, construction: Any, *, time_limit: float | None = 60.0, node_limit: int | None = 10000, trace: bool = False) -> dict:
    """Execute the paper's plain B&B with one time/node budget for the condition."""
    started = time.monotonic()
    deadline = make_deadline(time_limit, start=started)
    if node_limit is not None and (isinstance(node_limit, bool) or not isinstance(node_limit, int) or node_limit < 0):
        raise ValueError("node_limit must be a nonnegative integer or None")
    candidates, empty_rows, components = _prepare(instance, _get(construction, "rows"), _get(construction, "components"))
    budget = _Budget(deadline, node_limit)
    epoch = str(instance.get("metadata", {}).get("epoch", "benchmark-epoch-1"))
    results = []
    empty_infeasible = any(row["upper"] < 0 for row in empty_rows)
    for component in components:
        if empty_infeasible:
            results.append(_unstarted(component, "global_empty_row_contradiction", status="unknown"))
        elif budget.reason() is not None:
            results.append(_unstarted(component, budget.reason()))
        else:
            results.append(_distributed_component(component, budget, epoch, trace))
    result = _aggregate("distributed", results, empty_rows, started, trace, solver_provenance())
    result.update(
        time_limit_seconds=time_limit, node_limit=node_limit,
        search_policy={"candidate_order": "lexicographic candidate ID", "traversal": "depth first, zero before one", "initial_incumbent": "negative_infinity", "initial_root_bound": "positive_infinity", "warm_start": "none", "branch_variables": "shared-row interface only"},
    )
    result["elapsed_seconds"] = time.monotonic() - started
    return result


def _central_component(component: dict, deadline: float | None, want_trace: bool) -> dict:
    solution = solve_exact(component["candidates"], component["rows"], deadline=deadline)
    metrics = _metrics()
    metrics["central_solver_calls"] = 1
    metrics["z3_checks"] = int(solution["solver_started"])
    lower = Fraction(solution["objective"]) if solution["objective"] is not None else None
    upper = Fraction(solution["upper_bound"]) if solution["upper_bound"] is not None else None
    root_upper = trivial_upper_bound(component["candidates"])
    return {
        **_base(component), "status": solution["status"], "reason": solution["reason"],
        "selected_ids": solution["selected_ids"], **_bound_fields(lower, upper, solution["status"]),
        "metrics": metrics, "root_upper_bound": str(root_upper), "root_upper_bound_kind": "finite",
        "root_relaxation_bound": None,
        "trace": [{"event": "central_solve", "component_id": component["id"], "status": solution["status"], "objective": solution["objective"], "upper_bound": solution["upper_bound"]}] if want_trace else [],
        "solver_calls": [{"status": solution["status"], "reason": solution["reason"], "elapsed_seconds": solution["elapsed_seconds"], "solver_started": solution["solver_started"], "statistics": solution["solver_statistics"], "optimality_certificate": solution["optimality_certificate"]}],
        "incumbent_history": [{"objective": solution["objective"]}] if lower is not None else [],
        "unresolved_node_count": 0 if solution["status"] in ("optimal", "infeasible") else 1,
        "unresolved_nodes": [],
    }


def match_central(instance: Mapping, *, rows: Any, components: Any, time_limit: float | None = 60.0, trace: bool = False) -> dict:
    """Optimize independently encoded rows after uploading all candidates once.

    The caller supplies the independently central encoding and the SAME component
    partition used in the distributed condition.  Candidate uploads contain
    scores and event metadata, not raw frame data.  Fixed process templates are
    assumed known; given non-assignment rows are separately uploaded once.
    """
    started = time.monotonic()
    deadline = make_deadline(time_limit, start=started)
    candidates, empty_rows, prepared = _prepare(instance, rows, components)
    empty_infeasible = any(row["upper"] < 0 for row in empty_rows)
    results = []
    for component in prepared:
        if empty_infeasible:
            results.append(_unstarted(component, "global_empty_row_contradiction", status="unknown", central=True))
        elif deadline is not None and time.monotonic() >= deadline:
            results.append(_unstarted(component, "condition_time_limit", central=True))
        else:
            results.append(_central_component(component, deadline, trace))
    result = _aggregate("central", results, empty_rows, started, trace, solver_provenance())
    given = [row for row in instance.get("given_rows", []) if row.get("kind") not in ("assignment", "assignment_upper", "assignment_lower")]
    owners = {candidate["id"]: candidate["owner"] for candidate in candidates}
    by_source = {
        str(source): {
            "candidate_records": sum(candidate["owner"] == source for candidate in candidates),
            "score_records": sum(candidate["owner"] == source for candidate in candidates),
            "metadata_records": sum(candidate["owner"] == source for candidate in candidates),
            "given_row_records": 0, "given_row_coefficient_terms": 0,
        } for source in instance["sources"]
    }
    unowned_given_rows = 0
    for row in given:
        row_owners = {owners[identifier] for identifier, coefficient in row["terms"].items() if coefficient}
        if len(row_owners) == 1:
            counts = by_source[str(next(iter(row_owners)))]
            counts["given_row_records"] += 1
            counts["given_row_coefficient_terms"] += sum(bool(coefficient) for coefficient in row["terms"].values())
        else:
            unowned_given_rows += 1
    upload = {
        "logical_messages": len(instance["sources"]),
        "candidate_records": len(candidates), "score_records": len(candidates),
        "metadata_records": len(candidates), "raw_frame_records": 0,
        "given_row_records": len(given),
        "given_row_coefficient_terms": sum(sum(bool(coefficient) for coefficient in row["terms"].values()) for row in given),
        "given_rows_without_unique_source": unowned_given_rows,
        "fixed_prerequisite_templates": len(instance.get("prerequisites", [])),
        "fixed_occurrence_templates": len(instance.get("occurrence_bounds", [])),
        "records_by_source": by_source,
        "candidate_fields": ["id", "observation_id", "case_id", "activity", "start", "end", "score", "owner"],
        "assignment_rows": "reconstructed centrally from uploaded observation IDs",
        "template_knowledge": "fixed prerequisite and occurrence templates known centrally",
        "unit": "logical records; score and metadata counts are fields within candidate records, not additional messages",
    }
    result.update(time_limit_seconds=time_limit, central_upload=upload)
    result["metrics"].update(candidate_upload_records=len(candidates), candidate_upload_messages=len(instance["sources"]), score_upload_records=len(candidates), metadata_upload_records=len(candidates), raw_frame_upload_records=0, given_row_upload_records=len(given), given_row_upload_coefficient_terms=upload["given_row_coefficient_terms"])
    if trace:
        result["trace"].insert(0, {"event": "central_upload", **upload})
    result["elapsed_seconds"] = time.monotonic() - started
    return result
