#!/usr/bin/env python3
"""Recount GT mining and candidate-row statistics without importing producer code.

The catalogue is descriptive, in-sample evidence. No optimizer is invoked.
``generate(root, output)`` writes JSON/CSVs into output and RULES.md into its
parent. Output must remain outside the preserved inputs and results trees.
"""

import argparse
from collections import Counter, defaultdict
import csv
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path


SELECTED = {"prerequisites": ["pre_019", "pre_036", "pre_023"],
            "occurrence_bounds": ["occ_031", "occ_021"]}
ROOT = Path(__file__).resolve().parents[1]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_json(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def read_csv(path):
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def recompute_gt(events, cases, activities):
    """Enumerate all distinct ordered label pairs using the literal semantics.

    Unlike the producer's earliest-predecessor shortcut, test each trigger
    against its complete set of same-case eligible supporters.
    """
    require(cases and len(cases) == len(set(cases)), "Case roster must be nonempty and unique")
    cases = sorted(cases)
    alphabet = sorted(activities)
    require(len(alphabet) == len(set(alphabet)), "Activity vocabulary contains duplicates")
    by_case = {case: [] for case in cases}
    seen = set()
    for original in events:
        event = dict(original)
        require(event["case_id"] in by_case, "GT event is outside the case roster")
        require(event["activity"] in alphabet, "GT activity is outside the vocabulary")
        key = event["case_id"], event["event_id"]
        require(key not in seen, "Duplicate GT event")
        seen.add(key)
        for name in ("start_frame", "end_frame_exclusive"):
            event[name] = int(event[name])
        require(0 <= event["start_frame"] < event["end_frame_exclusive"], "Invalid half-open GT interval")
        by_case[event["case_id"]].append(event)
    for values in by_case.values():
        values.sort(key=lambda e: (e["start_frame"], e["end_frame_exclusive"], e["event_id"]))
    counts = {case: Counter(e["activity"] for e in by_case[case]) for case in cases}
    pairs, bounds = [], []
    for activity in alphabet:
        per_case = {case: counts[case][activity] for case in cases}
        low, high = min(per_case.values()), max(per_case.values())
        informative = [case for case in cases if len(by_case[case]) > high]
        bounds.append({"activity": activity, "minimum": low, "maximum": high,
            "per_case_counts": per_case,
            "minimum_witness_case_ids": [c for c in cases if per_case[c] == low],
            "maximum_witness_case_ids": [c for c in cases if per_case[c] == high],
            "positive_minimum": low > 0, "informative_maximum": bool(informative),
            "maximum_trivial_against_event_positions": not informative,
            "maximum_informative_case_ids": informative,
            "observed_in_cases": sum(n > 0 for n in per_case.values()),
            "total_occurrences": sum(per_case.values())})
    for predecessor in alphabet:
        for trigger in alphabet:
            if predecessor == trigger:
                continue
            active = [c for c in cases if counts[c][trigger]]
            total = sum(counts[c][trigger] for c in cases)
            violations, failed, counterexample, witness = 0, [], None, None
            for case in active:
                supporters = [e for e in by_case[case] if e["activity"] == predecessor]
                supporters.sort(key=lambda e: (e["end_frame_exclusive"], e["start_frame"], e["event_id"]))
                bad = False
                for event in (e for e in by_case[case] if e["activity"] == trigger):
                    eligible = [s for s in supporters if s["end_frame_exclusive"] <= event["start_frame"]]
                    if eligible:
                        if witness is None:
                            witness = {"case_id": case, "predecessor_event_id": eligible[0]["event_id"],
                                "trigger_event_id": event["event_id"],
                                "predecessor_end_frame_exclusive": eligible[0]["end_frame_exclusive"],
                                "trigger_start_frame": event["start_frame"],
                                "eligible_supporters": len(eligible)}
                    else:
                        violations += 1
                        bad = True
                        if counterexample is None:
                            first = supporters[0] if supporters else None
                            counterexample = {"case_id": case, "trigger_event_id": event["event_id"],
                                "trigger_start_frame": event["start_frame"],
                                "trigger_end_frame_exclusive": event["end_frame_exclusive"],
                                "predecessor_events_in_case": len(supporters),
                                "earliest_predecessor_event_id": first["event_id"] if first else None,
                                "earliest_predecessor_end_frame_exclusive": first["end_frame_exclusive"] if first else None,
                                "reason": "predecessor_absent" if first is None else "no_predecessor_completed_by_trigger_start"}
                if bad:
                    failed.append(case)
            pairs.append({"predecessor": predecessor, "trigger": trigger,
                "satisfied": violations == 0, "nonvacuous": total > 0,
                "accepted": total > 0 and violations == 0,
                "activated_cases": len(active), "activated_events": total,
                "activated_case_ids": active, "vacuous_cases": len(cases) - len(active),
                "active_in_all_cases": len(active) == len(cases),
                "satisfied_events": total - violations, "satisfied_cases": len(cases) - len(failed),
                "satisfied_activated_cases": len(active) - len(failed),
                "violation_count": violations, "violated_cases": len(failed),
                "violation_case_ids": failed, "first_counterexample": counterexample,
                "witness_example": witness})
    return {"pairs": pairs, "bounds": bounds, "by_case": by_case, "counts": counts}


def candidate_rows(template, candidates, cases):
    """Independently expand a singleton template, including empty upper rows."""
    rows = []
    if template["kind"] == "prerequisite":
        require(len(template["predecessor_activities"]) == 1, "Expected singleton predecessor")
        require(template.get("min_delay") is None and template.get("max_delay") is None,
                "Unexpected delay restriction in the mined template")
        predecessor = template["predecessor_activities"][0]
        for trigger in candidates:
            if trigger["activity"] != template["trigger_activity"]:
                continue
            supporters = [c for c in candidates if c["case_id"] == trigger["case_id"]
                          and c["activity"] == predecessor and c["end"] <= trigger["start"]]
            rows.append({"id": f"pre:{template['id']}:{trigger['id']}", "kind": "prerequisite",
                         "terms": {trigger["id"]: 1, **{c["id"]: -1 for c in supporters}},
                         "upper": 0, "case_id": trigger["case_id"]})
    else:
        require(template["kind"] == "occurrence_bound" and len(template["activities"]) == 1,
                "Expected singleton occurrence bound")
        for case in sorted(cases):
            ids = [c["id"] for c in candidates if c["case_id"] == case and c["activity"] == template["activities"][0]]
            rows.append({"id": f"upper:{template['id']}:{case}", "kind": "occurrence_upper",
                         "terms": {v: 1 for v in ids}, "upper": template["upper"], "case_id": case})
            if template["lower"] > 0:
                rows.append({"id": f"lower:{template['id']}:{case}", "kind": "occurrence_lower",
                             "terms": {v: -1 for v in ids}, "upper": -template["lower"], "case_id": case})
    return rows


def rank_records(records):
    return {r["id"]: i for i, r in enumerate(sorted(records,
        key=lambda r: (-r["support_cases"], -r["support_events"], r["id"])), 1)}


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True, separators=(",", ":"))
                             if isinstance(v, (dict, list)) else v for k, v in row.items()})


def generate(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    for protected in (root / "inputs", root / "results"):
        require(not (output == protected or protected in output.parents), "Output cannot overwrite frozen evidence")
    paths = {"gt": "inputs/reference/full/ground_truth.csv", "cases": "inputs/reference/full/cases.csv",
        "uncertain": "inputs/reference/full/uncertain_log.csv.gz", "templates": "inputs/reference/full/constraints.json",
        "audit": "inputs/reference/full/constraint_audit.json", "selection": "inputs/provenance/selection_protocol.json",
        "rankings": "inputs/provenance/support_rankings.json",
        "instance": "results/benchmark_sweep/preparation/instances/seed0_K1_C116.json.gz",
        "rows": "results/benchmark_sweep/construction/seed0_K1_C116/central_rows.json.gz"}
    sources = {p: {"sha256": hashlib.sha256((root / p).read_bytes()).hexdigest(), "bytes": (root / p).stat().st_size}
               for p in paths.values()}
    events, roster = read_csv(root / paths["gt"]), read_csv(root / paths["cases"])
    cases = sorted(r["case_id"] for r in roster)
    case_group = {r["case_id"]: r["process_group"] for r in roster}
    templates = read_json(root / paths["templates"])["constraints"]
    prereq_templates = [t for t in templates if t["kind"] == "prerequisite"]
    bound_templates = [t for t in templates if t["kind"] == "occurrence_bound"]
    alphabet = sorted(t["activities"][0] for t in bound_templates)
    recomputed = recompute_gt(events, cases, alphabet)
    audit = read_json(root / paths["audit"])
    pairs = recomputed["pairs"]
    require([{k: v for k, v in p.items() if k != "witness_example"} for p in pairs] == audit["prerequisites"],
            "Recomputed pair tests differ from the frozen audit")
    accepted = [p for p in pairs if p["accepted"]]
    require([{k: v for k, v in p.items() if k != "witness_example"} for p in accepted] == audit["accepted_prerequisites"],
            "Accepted-rule audit differs")
    require(recomputed["bounds"] == audit["occurrence_bounds"], "Recomputed bounds differ from frozen audit")
    expected_pre = [(p["predecessor"], p["trigger"]) for p in accepted]
    require([(t["predecessor_activities"][0], t["trigger_activity"]) for t in prereq_templates] == expected_pre,
            "Frozen template catalogue differs from accepted GT rules")
    require([t["id"] for t in prereq_templates] == [f"pre_{i:03d}" for i in range(1, len(accepted) + 1)], "Prerequisite IDs differ")
    require([t["id"] for t in bound_templates] == [f"occ_{i:03d}" for i in range(1, len(alphabet) + 1)], "Bound IDs differ")
    for template, pair in zip(prereq_templates, accepted):
        require(template["activated_cases"] == pair["activated_cases"] and template["activated_events"] == pair["activated_events"]
                and template["active_in_all_cases"] == pair["active_in_all_cases"], "Template support differs")
    for template, bound in zip(bound_templates, recomputed["bounds"]):
        require(template["activities"] == [bound["activity"]] and (template["lower"], template["upper"]) ==
                (bound["minimum"], bound["maximum"]), "Bound template differs from GT counts")
    instance = read_json(root / paths["instance"])
    require(sorted(instance["cases"]) == cases, "Frozen candidate instance has a different case roster")
    candidates = instance["candidates"]
    uncertain = read_csv(root / paths["uncertain"])
    gt_by_id = {e["event_id"]: e for e in events}
    require(len(gt_by_id) == len(events), "GT event IDs must be globally unique for these exports")
    require(len(uncertain) == len(events) and {o["event_id"] for o in uncertain} == set(gt_by_id),
            "Uncertain observations differ from the GT population")
    for observation in uncertain:
        truth = gt_by_id[observation["event_id"]]
        require(all(observation[k] == truth[k] for k in ("case_id", "start_frame", "end_frame_exclusive")),
                "Uncertain observation interval differs from GT")
    source_candidates = {(o["event_id"], o["case_id"], int(o["start_frame"]), int(o["end_frame_exclusive"]), a, Fraction(s))
                         for o in uncertain for a, s in json.loads(o["scores"], parse_float=str, parse_int=str).items()}
    frozen_candidates = {(c["observation_id"], c["case_id"], c["start"], c["end"], c["activity"], Fraction(c["score"])) for c in candidates}
    require(len(candidates) == len(frozen_candidates) and frozen_candidates == source_candidates,
            "Frozen candidate rows differ from the prepared uncertain log")
    selection = read_json(root / paths["selection"])
    require(selection["selection"] == SELECTED, "Active five-template selection changed")
    require(selection["ground_truth_sha256"] == sources[paths["gt"]]["sha256"], "Selection protocol points to different GT")
    groups = []
    for group in sorted(set(case_group.values())):
        ids = [c for c in cases if case_group[c] == group]
        groups.append({"name": group, "cases": len(ids), "events": sum(len(recomputed["by_case"][c]) for c in ids)})

    def group_support(activity):
        result = {}
        for group in groups:
            ids = [c for c in cases if case_group[c] == group["name"]]
            active = sum(recomputed["counts"][c][activity] > 0 for c in ids)
            result[group["name"]] = {"cases": len(ids), "support_cases": active,
                "support_events": sum(recomputed["counts"][c][activity] for c in ids),
                "vacuous_cases": len(ids) - active, "case_support_fraction": active / len(ids)}
        return result

    selected_rows, pre_records, bound_records = [], [], []
    for template, pair in zip(prereq_templates, accepted):
        rows = candidate_rows(template, candidates, cases)
        sizes = [len(r["terms"]) - 1 for r in rows]
        selected = template["id"] in SELECTED["prerequisites"]
        if selected:
            selected_rows.extend(rows)
        example = next((r for r in rows if len(r["terms"]) > 1), rows[0] if rows else None)
        pre_records.append({"id": template["id"], "selected": selected, "rank": 0,
            "predecessor": pair["predecessor"], "trigger": pair["trigger"],
            "description": f"Each selected {pair['trigger']} needs some earlier selected {pair['predecessor']} in the same case.",
            "support_cases": pair["activated_cases"], "support_events": pair["activated_events"],
            "case_support_fraction": pair["activated_cases"] / len(cases),
            "event_support_fraction": pair["activated_events"] / len(events),
            "vacuous_cases": pair["vacuous_cases"], "vacuous_fraction": pair["vacuous_cases"] / len(cases),
            "group_support": group_support(pair["trigger"]), "witness_example": pair["witness_example"],
            "candidate_rows": {"rows": len(rows), "no_supporter_rows": sizes.count(0),
                               "min_supporters": min(sizes, default=0), "max_supporters": max(sizes, default=0),
                               "supporter_cardinality_counts": dict(sorted(Counter(sizes).items())), "example": example}})
    candidate_positions = defaultdict(set)
    for candidate in candidates:
        candidate_positions[candidate["activity"], candidate["case_id"]].add(candidate["observation_id"])
    for template, bound in zip(bound_templates, recomputed["bounds"]):
        activity = bound["activity"]
        selected = template["id"] in SELECTED["occurrence_bounds"]
        rows = candidate_rows(template, candidates, cases)
        if selected:
            selected_rows.extend(rows)
        potential = [c for c in cases if len(candidate_positions[activity, c]) > template["upper"]]
        bound_records.append({"id": template["id"], "selected": selected, "rank": 0, "activity": activity,
            "lower": bound["minimum"], "upper": bound["maximum"], "support_cases": bound["observed_in_cases"],
            "support_events": bound["total_occurrences"], "zero_cases": sum(n == 0 for n in bound["per_case_counts"].values()),
            "case_support_fraction": bound["observed_in_cases"] / len(cases),
            "maximum_witness_case_ids": bound["maximum_witness_case_ids"], "minimum_witness_case_ids": bound["minimum_witness_case_ids"],
            "group_support": group_support(activity), "candidate_potential_violation_cases": len(potential),
            "candidate_potential_violation_case_ids": potential,
            "max_available_candidate_positions": max(len(candidate_positions[activity, c]) for c in cases),
            "candidate_rows": {"upper_rows": len(cases), "empty_upper_rows": sum(not r["terms"] for r in rows if r["kind"] == "occurrence_upper"),
                               "lower_rows": len(cases) if template["lower"] > 0 else 0,
                               "example": next(r for r in rows if r["case_id"] == bound["maximum_witness_case_ids"][0])}})
    rankings = read_json(root / paths["rankings"])
    for family, records in (("prerequisites", pre_records), ("occurrence_bounds", bound_records)):
        ranks = rank_records(records)
        for record in records:
            record["rank"] = ranks[record["id"]]
        ordered = sorted(records, key=lambda r: r["rank"])
        require([(r["id"], r["support_cases"], r["support_events"]) for r in ordered] ==
                [(r["id"], r["support_cases"], r["support_events"]) for r in rankings[family]], "Frozen support rankings differ")
        require([r["id"] for r in ordered[:len(SELECTED[family])]] == SELECTED[family], "Five-rule support selection differs")
        require(instance[family] == [t for t in templates if t["id"] in SELECTED[family]], "Frozen active templates differ")
    original_rows = read_json(root / paths["rows"])
    saved_generated = [r for r in original_rows if r["kind"] != "assignment"]
    require(sorted(selected_rows, key=lambda r: r["id"]) == sorted(saved_generated, key=lambda r: r["id"]),
            "Independent selected-template expansion differs from frozen candidate rows")
    tests = [{"predecessor": p["predecessor"], "trigger": p["trigger"], "accepted": p["accepted"],
              "purely_vacuous": not p["nonvacuous"], "support_cases": p["activated_cases"], "support_events": p["activated_events"],
              "violations": p["violation_count"], "violated_cases": p["violated_cases"], "vacuous_cases": p["vacuous_cases"],
              "reason": "accepted_no_violations" if p["accepted"] else "no_trigger_events" if not p["nonvacuous"] else "unsupported_trigger_events",
              "counterexample": p["first_counterexample"]} for p in pairs]
    summary = {"cases": len(cases), "events": len(events), "activities": len(alphabet), "tested_pairs": len(pairs),
        "accepted_prerequisites": len(accepted), "rejected_pairs": sum(not p["accepted"] for p in pairs),
        "purely_vacuous_pairs": sum(not p["nonvacuous"] for p in pairs),
        "accepted_active_in_all_cases": sum(p["active_in_all_cases"] for p in accepted),
        "occurrence_bounds": len(bound_records), "positive_minima": sum(b["lower"] > 0 for b in bound_records),
        "selected_ids": SELECTED, "selected_instantiated_rows": len(selected_rows),
        "selected_prerequisite_rows": sum(r["kind"] == "prerequisite" for r in selected_rows),
        "selected_upper_rows": sum(r["kind"] == "occurrence_upper" for r in selected_rows),
        "assignment_rows": sum(r["kind"] == "assignment" for r in original_rows),
        "selected_empty_upper_rows": sum(not r["terms"] for r in selected_rows if r["kind"] == "occurrence_upper"),
        "minimum_accepted_support_cases": min(p["support_cases"] for p in pre_records),
        "maximum_accepted_support_cases": max(p["support_cases"] for p in pre_records)}
    data = {"schema_version": 1,
        "scope": "Independent recount from prepared GT and comparison with frozen mining/template/ranking records; no raw annotation review, held-out validation, solver execution, or claim that every mined rule is active in the sweep.",
        "source_files": sources, "summary": summary, "groups": groups,
        "denominators": {"case_support_fraction": "support cases / all 116 retained cases", "event_support_fraction": "trigger events / all 1856 GT events",
            "group_case_support_fraction": "support cases / retained cases of that furniture group",
            "candidate_potential_violation_cases": "Distinct observations admitting this label exceed the upper bound; ignores other templates, so this is not a feasible counterexample to the complete model."},
        "checks": {"all_pair_tests_match_frozen_audit": True, "all_bounds_match_frozen_audit": True,
                   "catalogue_matches_recomputed_acceptance": True, "rankings_and_five_rule_selection_match": True,
                   "candidate_semantics_match_prepared_uncertain_log": True, "selected_rows_match_frozen_central_rows": True},
        "prerequisites": pre_records, "occurrence_bounds": bound_records, "prerequisite_tests": tests,
        "examples": {"witness": next(r for r in pre_records if r["id"] == "pre_019"),
                     "failed_rule": next(t for t in tests if not t["accepted"] and t["counterexample"])}}
    output.mkdir(parents=True, exist_ok=True)
    (output / "rule_stats.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_csv(output / "prerequisites.csv", pre_records)
    _write_csv(output / "occurrence_bounds.csv", bound_records)
    _write_csv(output / "prerequisite_tests.csv", tests)
    (output.parent / "RULES.md").write_text(render_markdown(data), encoding="utf-8")
    return data


def render_markdown(data):
    s = data["summary"]
    lines = ["# Every mined rule and what it means", "",
        "Ground truth (GT) is the reference activity annotation supplied with IKEA ASM. Here, each case is an assembly recording and each observation is a continuous GT activity segment. "
        "Segments labelled NA (‘No Annotation’) have been removed to simplify matching to annotated activity observations. "
        "See [data sources and their roles](../../docs/SOURCES.md) for the original dataset, earlier uncertain-log conversion and citations.", "",
        f"The prepared GT contains **{s['events']} segments in {s['cases']} cases**, covering {s['activities']} non-NA activities. "
        f"Testing all {s['activities']} × {s['activities']-1} ordered distinct-label pairs gives **{s['tested_pairs']} prerequisite tests**: "
        f"{s['accepted_prerequisites']} accepted, {s['rejected_pairs']} rejected, and {s['purely_vacuous_pairs']} with no trigger anywhere. "
        f"There are also {s['occurrence_bounds']} singleton occurrence bounds. Only **three prerequisites and two bounds** are active in the paper sweep.", "",
        "This catalogue was recomputed directly from the prepared GT by `reviewer/rule_stats.py`, without importing the production miner or invoking a solver. "
        "Every pair outcome, bound, catalogue membership, support ranking and selected candidate row was compared with frozen evidence. "
        "The input is still the same annotated cohort: this is an independent calculation, not independent data, human review, or validation on unseen cases.", "",
        "## Prerequisite semantics and vacuity", "",
        "For predecessor activity A and trigger B, require for **every** GT event b labelled B an event a in the **same case** with label A and `end(a) ≤ start(b)`. "
        "Intervals are half-open, so adjacent endpoints qualify. The predecessor need not be immediately previous, and one event can support multiple triggers. "
        "A pair is accepted only if it has at least one trigger in the population and no unsupported trigger.", "",
        "A case with no B satisfies the statement vacuously. **None of the 41 accepted prerequisites has a trigger in all 116 cases**, although each holds throughout the cohort. "
        "All 32 labels occur somewhere, explaining the zero entirely vacuous pair tests. Accepted-rule case support ranges from "
        f"{s['minimum_accepted_support_cases']} to {s['maximum_accepted_support_cases']} cases. Low support and furniture-specific absence are visible below; "
        "do not read 116 satisfied cases as 116 observed confirmations.", "",
        "For candidates, each trigger candidate v becomes a row `x_v − Σ x_u ≤ 0`, where u ranges over **all** eligible same-case predecessor candidates. "
        "Without supporters the row is `x_v ≤ 0`. Support in the table concerns GT triggers, not candidate rows or classifier confidence.", "",
        "## Why these five templates are active", "",
        "The full set of 41 prerequisites and 32 occurrence bounds made preliminary distributed B&B reach the 300-second limit before completing the log, "
        "even with 116 independent cases and two sources. We therefore reduced the rule set for practical runtime, keeping all cases and candidates. "
        "The same five rules are fixed throughout the sweep and for both matching methods. The [selection protocol](../../inputs/provenance/selection_protocol.json) records this decision.", "",
        "Within each family, rank by descending number of GT cases with the trigger/activity, then descending GT event count, then ascending template ID. "
        "Take three prerequisites (`pre_019`, `pre_036`, `pre_023`) and two bounds (`occ_031`, `occ_021`). "
        "The two shelf-attachment prerequisites tie at 56 cases/57 events and ID resolves their order; shelf pickup has 54 cases/57 events. "
        "Both selected bound activities occur in 87 cases; spin leg has 362 events and pick up leg has 338. "
        "Removing rules changes the matching problem. The results concern this smaller constraint model; five is not claimed to be the best rule count, "
        "and the reduction is not a speedup on the original problem or a selection validated on unseen cases.", "",
        f"At K=1, C=116, the five templates expand to **{s['selected_instantiated_rows']} rows**: "
        f"{s['selected_prerequisite_rows']} trigger rows and {s['selected_upper_rows']} case-specific upper rows, including {s['selected_empty_upper_rows']} empty upper rows. "
        f"The {s['assignment_rows']} observation-assignment rows are additional. Template counts and row counts must not be interchanged. "
        "Other K values preserve numerical rows; coupling adds the declared exclusions.", "",
        "## All 41 accepted prerequisites", "",
        "`Active` means used in the sweep. Rank is the support-selection rank. Cases use denominator 116; events are GT trigger occurrences. "
        "Vacuous cases have no trigger. Group support lists activated cases / retained cases for each furniture group: "
        "; ".join(f"{g['name']} ({g['cases']} cases)" for g in data["groups"]) + ". "
        "Candidate rows/supporters describe how that template would expand in the frozen candidates, including inactive templates. "
        "The supporter range includes zero when some trigger candidate is forbidden.", "",
        "| ID | Active | Rank | Earlier predecessor → trigger | GT cases | GT events | Vacuous cases | Furniture-group support | Candidate rows; supporter range |",
        "|---|---|---:|---|---:|---:|---:|---|---|" ]
    for r in data["prerequisites"]:
        group = "; ".join(f"{g}: {v['support_cases']}/{v['cases']}" for g, v in r["group_support"].items())
        c = r["candidate_rows"]
        lines.append(f"| {r['id']} | {'yes' if r['selected'] else 'no'} | {r['rank']} | {r['predecessor']} → {r['trigger']} | {r['support_cases']}/116 ({r['case_support_fraction']:.1%}) | {r['support_events']} | {r['vacuous_cases']} | {group} | {c['rows']}; {c['min_supporters']}–{c['max_supporters']} |")
    lines += ["", "For a weak-support example, `pre_004` (**align side panel holes with front panel dowels → lay down side panel**) "
        "has only one trigger in one case; the other 115 cases are vacuous. Group-wise support makes clear that some activity pairs concern "
        "only a furniture subset. Whole-cohort validity does not supply observations from the groups where the trigger never occurs.", "",
        "### Selected candidate-row expansion", "",
        "GT trigger counts and proposed candidate-trigger counts differ because non-GT alternatives can also propose a trigger. "
        "The following rows are checked directly against the frozen K1/C116 central encoding. The example is one complete literal row; "
        "all listed predecessor IDs have coefficient −1, the trigger ID has +1, and the right-hand side is zero.", "",
        "| Template | Instantiated trigger rows | Rows with no supporter | Example trigger | Eligible supporter IDs |",
        "|---|---:|---:|---|---|"]
    for r in data["prerequisites"]:
        if r["selected"]:
            c = r["candidate_rows"]
            row = c["example"]
            trigger = next(v for v, coefficient in row["terms"].items() if coefficient == 1)
            supporters = ", ".join(v for v, coefficient in row["terms"].items() if coefficient == -1)
            lines.append(f"| {r['id']} | {c['rows']} | {c['no_supporter_rows']} | {trigger} | {supporters} |")
    lines += ["", "No-supporter counts are counts of rows, not necessarily distinct candidate IDs: the same shelf-attachment candidate can trigger both prerequisites.",
        "", "## All 32 occurrence bounds", "",
        "For each activity A, count its GT segments in every retained case, including zero counts; the minimum and maximum become the lower and upper bound. "
        "**Every lower bound is zero.** The current encoder omits these vacuous lower rows and emits one upper row per case, including rows with no candidate terms. "
        "These are observed segment-count extrema, not numbers of physical parts or laws for unseen assemblies.", "",
        "`Potential excess cases` counts cases whose distinct observations admitting that activity exceed the bound. Such a choice respects observation assignment alone; "
        "other templates can prevent it. This column is not a full-model feasibility or nonredundancy proof. Maximum-witness IDs identify cases attaining the GT maximum.", "",
        "| ID | Active | Rank | Activity | GT lower–upper | GT support cases | GT events | Zero cases | Maximum-witness cases | Potential excess cases |",
        "|---|---|---:|---|---|---:|---:|---:|---|---:|"]
    for r in data["occurrence_bounds"]:
        lines.append(f"| {r['id']} | {'yes' if r['selected'] else 'no'} | {r['rank']} | {r['activity']} | {r['lower']}–{r['upper']} | {r['support_cases']}/116 | {r['support_events']} | {r['zero_cases']} | {', '.join(r['maximum_witness_case_ids'])} | {r['candidate_potential_violation_cases']} |")
    w = data["examples"]["witness"]["witness_example"]
    failure = data["examples"]["failed_rule"]
    f = failure["counterexample"]
    lines += ["", "## Concrete checks", "",
        f"Accepted example `pre_019`: event `{w['predecessor_event_id']}` (**pick up leg**) ends at {w['predecessor_end_frame_exclusive']}; "
        f"`{w['trigger_event_id']}` (**attach shelf to table**) starts at {w['trigger_start_frame']}. "
        "Both belong to case 0, so the temporal prerequisite is satisfied. This example alone does not establish the all-event claim; the recount checks every trigger.", "",
        f"Rejected pair **{failure['predecessor']} → {failure['trigger']}**: `{f['trigger_event_id']}` in case {f['case_id']} starts at {f['trigger_start_frame']}. "
        f"The case contains {f['predecessor_events_in_case']} predecessor events, so this trigger has no eligible supporter. "
        f"Across the cohort this pair has {failure['violations']} unsupported triggers in {failure['violated_cases']} cases. "
        "All rejected pairs and their first counterexamples are included below.", "",
        "## Data and verification boundaries", "",
        "- [All rule statistics and source hashes](data/rule_stats.json): full group denominators, example candidate rows, supporter-cardinality distributions and witness IDs.",
        "- [41 prerequisites](data/prerequisites.csv) and [32 bounds](data/occurrence_bounds.csv): sortable complete catalogues with the active flag.",
        "- [All 992 prerequisite tests](data/prerequisite_tests.csv): acceptance, activation, vacuity, violation counts, reasons and counterexamples.",
        "- [Experimental scope](../EXPERIMENT.md) and [manual review procedure](../MANUAL_REVIEW.md).", "",
        "Scores/candidate labels use GT assistance, the rules use in-sample GT, and furniture groups are descriptive strata rather than independent validation sets. "
        "No rule is described as universal because it holds in these traces. No new optimizer run or algorithm change is part of this report.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/reviewer/data")
    args = parser.parse_args()
    data = generate(ROOT, args.output)
    print(json.dumps({"status": "PASS", "output": str(args.output.resolve()), "summary": data["summary"]}, indent=2))


if __name__ == "__main__":
    main()
