"""Deterministic, descriptive constraint mining for a certain segmented log.

Input events have ``event_id``, ``case_id``, ``activity``, ``start_frame`` and
``end_frame_exclusive``. Times are integer frame boundaries of nonempty
half-open intervals. One event has one ground-truth activity. Event IDs must
be unique within a case; supplied case IDs include cases with no kept events.

``mine_constraints`` returns a JSON-serializable dictionary containing:

* ``metadata``: population and rule counts, and the stated semantics.
* ``prerequisites``: every ordered pair of distinct activities. ``predecessor``
  A is required for ``trigger`` B iff *every B event* has an A event in the
  same case whose end is <= B's start. It need not immediately precede B.
  ``satisfied`` includes vacuous satisfaction, whereas
  ``accepted_prerequisites`` excludes pairs with no trigger events. Records
  expose activated/vacuous case counts, event and case violation counts,
  activated case IDs, violation case IDs, and the first counterexample.
  ``active_in_all_cases`` is stronger than validity throughout the log.
* ``occurrence_bounds``: one singleton bound per activity, with ``minimum``
  and ``maximum`` counts over ALL supplied cases, per-case counts and witness
  case IDs. A maximum is ``informative_maximum`` when some trace has more
  event positions than that maximum. This is relative to the at-most-one-
  label-per-position baseline, assuming the activity is available at those
  positions; it is not a claim about an unseen process or a pruned candidate
  model. ``positive_minimum`` distinguishes useful minima from zero.

``select_variant_cases`` returns ``selected_case_ids``, ``variants`` and
``metadata``. Variants are exact activity sequences, sorted by descending
case count then lexicographically. Whole frequency ties at the coverage
cutoff are included, so actual coverage may exceed the requested fraction.
Each variant record has rank, activities, count, case_ids and selected.
Empty cases have the empty sequence. Events are ordered by start, end, and
event ID; repeated labels are NEVER coalesced, including after NA removal.

These are observations about the supplied population. Mining on evaluation
ground truth is appropriate for in-sample model construction, not evidence
of predictive generalization or independently supplied process knowledge.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from math import ceil, isfinite
from typing import Any, Iterable, Mapping, Sequence


def _prepare(
    events: Iterable[Mapping[str, Any]], case_ids: Iterable[str]
) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    """Check the explicit population and produce a stable temporal ordering."""
    cases = list(case_ids)
    if not cases:
        raise ValueError("case_ids must contain at least one case")
    if any(not isinstance(case_id, str) for case_id in cases):
        raise ValueError("case_ids must be strings")
    if len(set(cases)) != len(cases):
        raise ValueError("case_ids must be unique")
    cases.sort()
    by_case: dict[str, list[dict[str, Any]]] = {case_id: [] for case_id in cases}
    identities: set[tuple[str, str]] = set()
    fields = {"event_id", "case_id", "activity", "start_frame", "end_frame_exclusive"}
    for original in events:
        missing = fields.difference(original)
        if missing:
            raise ValueError(f"Event is missing required fields: {sorted(missing)}")
        event = dict(original)
        case_id = event["case_id"]
        if case_id not in by_case:
            raise ValueError(f"Event refers to a case absent from case_ids: {case_id!r}")
        activity = event["activity"]
        if not isinstance(activity, str) or not activity:
            raise ValueError("Event activity must be a nonempty string")
        for name in ("start_frame", "end_frame_exclusive"):
            if not isinstance(event[name], int) or isinstance(event[name], bool):
                raise ValueError(f"{name} must be an integer frame boundary")
        if event["start_frame"] < 0 or event["end_frame_exclusive"] <= event["start_frame"]:
            raise ValueError("Events must have nonempty, nonnegative half-open intervals")
        event["event_id"] = str(event["event_id"])
        identity = (case_id, event["event_id"])
        if identity in identities:
            raise ValueError(f"Duplicate event_id within a case: {identity!r}")
        identities.add(identity)
        by_case[case_id].append(event)
    for case_events in by_case.values():
        case_events.sort(
            key=lambda event: (
                event["start_frame"], event["end_frame_exclusive"], event["event_id"]
            )
        )
    return cases, by_case


def mine_constraints(
    events: Iterable[Mapping[str, Any]],
    case_ids: Iterable[str],
    activities: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Audit singleton prerequisites and empirical occurrence bounds."""
    cases, by_case = _prepare(events, case_ids)
    observed = {event["activity"] for values in by_case.values() for event in values}
    if activities is None:
        alphabet = sorted(observed)
    else:
        if any(not isinstance(activity, str) or not activity for activity in activities):
            raise ValueError("activities must contain nonempty strings")
        alphabet = sorted(set(activities))
        if not observed.issubset(alphabet):
            raise ValueError("activities omits one or more observed ground-truth labels")

    counts = {
        case_id: Counter(event["activity"] for event in by_case[case_id])
        for case_id in cases
    }
    by_activity = {
        case_id: {
            activity: [event for event in by_case[case_id] if event["activity"] == activity]
            for activity in alphabet
        }
        for case_id in cases
    }
    bounds = []
    for activity in alphabet:
        per_case = {case_id: counts[case_id][activity] for case_id in cases}
        minimum, maximum = min(per_case.values()), max(per_case.values())
        informative_cases = [case_id for case_id in cases if len(by_case[case_id]) > maximum]
        bounds.append({
            "activity": activity,
            "minimum": minimum,
            "maximum": maximum,
            "per_case_counts": per_case,
            "minimum_witness_case_ids": [case_id for case_id in cases if per_case[case_id] == minimum],
            "maximum_witness_case_ids": [case_id for case_id in cases if per_case[case_id] == maximum],
            "positive_minimum": minimum > 0,
            "informative_maximum": bool(informative_cases),
            "maximum_trivial_against_event_positions": not informative_cases,
            "maximum_informative_case_ids": informative_cases,
            "observed_in_cases": sum(value > 0 for value in per_case.values()),
            "total_occurrences": sum(per_case.values()),
        })

    prerequisites = []
    for predecessor in alphabet:
        for trigger in alphabet:
            if predecessor == trigger:
                continue
            active_cases = [case_id for case_id in cases if counts[case_id][trigger] > 0]
            active_events = sum(counts[case_id][trigger] for case_id in cases)
            violations = 0
            violated_cases: list[str] = []
            first_counterexample = None
            for case_id in active_cases:
                supporters = by_activity[case_id][predecessor]
                earliest = min(
                    supporters,
                    key=lambda event: (event["end_frame_exclusive"], event["start_frame"], event["event_id"]),
                    default=None,
                )
                case_failed = False
                for event in by_activity[case_id][trigger]:
                    # With one activity per event and predecessor != trigger,
                    # the earlier event cannot be the trigger observation.
                    supported = earliest is not None and earliest["end_frame_exclusive"] <= event["start_frame"]
                    if supported:
                        continue
                    violations += 1
                    case_failed = True
                    if first_counterexample is None:
                        first_counterexample = {
                            "case_id": case_id,
                            "trigger_event_id": event["event_id"],
                            "trigger_start_frame": event["start_frame"],
                            "trigger_end_frame_exclusive": event["end_frame_exclusive"],
                            "predecessor_events_in_case": len(supporters),
                            "earliest_predecessor_event_id": earliest["event_id"] if earliest else None,
                            "earliest_predecessor_end_frame_exclusive": earliest["end_frame_exclusive"] if earliest else None,
                            "reason": "predecessor_absent" if earliest is None else "no_predecessor_completed_by_trigger_start",
                        }
                if case_failed:
                    violated_cases.append(case_id)
            prerequisites.append({
                "predecessor": predecessor,
                "trigger": trigger,
                "satisfied": violations == 0,
                "nonvacuous": active_events > 0,
                "accepted": active_events > 0 and violations == 0,
                "activated_cases": len(active_cases),
                "activated_events": active_events,
                "activated_case_ids": active_cases,
                "vacuous_cases": len(cases) - len(active_cases),
                "active_in_all_cases": len(active_cases) == len(cases),
                "satisfied_events": active_events - violations,
                "satisfied_cases": len(cases) - len(violated_cases),
                "satisfied_activated_cases": len(active_cases) - len(violated_cases),
                "violation_count": violations,
                "violated_cases": len(violated_cases),
                "violation_case_ids": violated_cases,
                "first_counterexample": first_counterexample,
            })
    accepted = [record for record in prerequisites if record["accepted"]]
    return {
        "metadata": {
            "case_count": len(cases),
            "event_count": sum(len(values) for values in by_case.values()),
            "empty_case_ids": [case_id for case_id in cases if not by_case[case_id]],
            "activity_count": len(alphabet),
            "activities": alphabet,
            "prerequisite_pair_count": len(prerequisites),
            "accepted_prerequisite_count": len(accepted),
            "accepted_active_in_all_cases_count": sum(record["active_in_all_cases"] for record in accepted),
            "positive_minimum_count": sum(record["positive_minimum"] for record in bounds),
            "informative_maximum_count": sum(record["informative_maximum"] for record in bounds),
            "prerequisite_semantics": "Every trigger has some same-case predecessor ending no later than its start; not necessarily immediately preceding.",
            "interval_semantics": "Integer frame boundaries, nonempty half-open [start_frame, end_frame_exclusive).",
            "scope": "Descriptive bounds and rules on the supplied ground-truth population; not held-out validation.",
        },
        "prerequisites": prerequisites,
        "accepted_prerequisites": accepted,
        "occurrence_bounds": bounds,
    }


def select_variant_cases(
    events: Iterable[Mapping[str, Any]], case_ids: Iterable[str], coverage: float = 1.0
) -> dict[str, Any]:
    """Select most frequent complete GT variants, including cutoff ties."""
    if isinstance(coverage, bool) or not isinstance(coverage, (int, float)) or not isfinite(coverage):
        raise ValueError("coverage must be a finite number in (0, 1]")
    if not 0 < coverage <= 1:
        raise ValueError("coverage must be in (0, 1]")
    cases, by_case = _prepare(events, case_ids)
    members: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for case_id in cases:
        members[tuple(event["activity"] for event in by_case[case_id])].append(case_id)
    ordered = sorted(members.items(), key=lambda item: (-len(item[1]), item[0]))
    target_count = ceil(coverage * len(cases))
    cumulative = 0
    cutoff_frequency = 0
    for _, variant_cases in ordered:
        cumulative += len(variant_cases)
        if cumulative >= target_count:
            cutoff_frequency = len(variant_cases)
            break
    variants = [
        {
            "rank": index + 1,
            "activities": list(sequence),
            "count": len(variant_cases),
            "case_ids": variant_cases,
            "selected": len(variant_cases) >= cutoff_frequency,
        }
        for index, (sequence, variant_cases) in enumerate(ordered)
    ]
    selected = sorted(case_id for variant in variants if variant["selected"] for case_id in variant["case_ids"])
    return {
        "selected_case_ids": selected,
        "variants": variants,
        "metadata": {
            "requested_coverage": float(coverage),
            "actual_coverage": len(selected) / len(cases),
            "target_case_count": target_count,
            "total_case_count": len(cases),
            "selected_case_count": len(selected),
            "excluded_case_ids": [case_id for case_id in cases if case_id not in set(selected)],
            "total_variant_count": len(variants),
            "selected_variant_count": sum(variant["selected"] for variant in variants),
            "cutoff_frequency": cutoff_frequency,
            "tie_policy": "Include every exact-sequence variant tied at the cutoff frequency.",
            "variant_semantics": "Exact ordered GT activity sequence after NA removal; adjacent equal labels are not merged; empty cases are included.",
            "ordering": "Descending variant frequency, then lexicographic activity sequence.",
        },
    }
