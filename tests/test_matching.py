"""Paper transcript, message accounting, retained snapshots, and cutoffs."""

from copy import deepcopy
from fractions import Fraction
from itertools import product
import json
import random
import unittest
from unittest.mock import patch

from minea_ikea.matching import _Source, match_central, match_distributed
from minea_ikea.solver import solve_exact


def candidate(identifier, score, owner=0, case="c"):
    return {"id": identifier, "observation_id": identifier, "case_id": case, "activity": identifier, "start": 0, "end": 1, "score": str(score), "owner": owner}


def row(identifier, terms, upper, kind="fixture", case="c"):
    return {"id": identifier, "kind": kind, "case_id": case, "terms": terms, "upper": upper}


def fixture(candidates, rows, cases=None, component_cases=None, sources=None):
    cases = sorted({item["case_id"] for item in candidates}) if cases is None else cases
    sources = sorted({item["owner"] for item in candidates}) if sources is None else sources
    instance = {"cases": cases, "sources": sources, "case_hosts": {case: 0 for case in cases}, "candidates": candidates, "given_rows": rows, "prerequisites": [], "occurrence_bounds": [], "gt_selected": [item["id"] for item in candidates], "metadata": {}}
    groups = [cases] if component_cases is None else component_cases
    components = []
    for index, group in enumerate(groups):
        owned = [item for item in candidates if item["case_id"] in group]
        components.append({"id": f"component:{index}", "case_ids": group, "coordinator": 0, "candidate_ids": [item["id"] for item in owned], "sources": sorted({item["owner"] for item in owned})})
    return instance, {"rows": rows, "components": components}


def paper_fixture():
    return fixture(
        [candidate("r", 2), candidate("a", 3), candidate("t", 4, 1)],
        [row("registration_or_assessment", {"r": 1, "a": 1}, 1), row("triage_requires_registration", {"t": 1, "r": -1}, 0)],
    )


def brute_score(candidates, rows):
    best = None
    for bits in product((0, 1), repeat=len(candidates)):
        assignment = dict(zip([item["id"] for item in candidates], bits))
        if all(sum(coefficient * assignment[identifier] for identifier, coefficient in constraint["terms"].items()) <= constraint["upper"] for constraint in rows):
            score = sum((Fraction(item["score"]) * assignment[item["id"]] for item in candidates), Fraction())
            best = score if best is None else max(best, score)
    return best


class MatchingTests(unittest.TestCase):
    def test_paper_five_node_transcript_and_hand_counted_metrics(self):
        instance, construction = paper_fixture()
        before = deepcopy(instance)
        result = match_distributed(instance, construction, trace=True)
        self.assertEqual(instance, before)
        self.assertEqual((result["status"], result["objective"], result["selected_ids"]), ("optimal", "6", ["r", "t"]))
        nodes = [event for event in result["trace"] if event["event"] == "node"]
        self.assertEqual([node["fixings"] for node in nodes], [{}, {"r": 0}, {"r": 0, "t": 0}, {"r": 0, "t": 1}, {"r": 1}])
        self.assertEqual([node["outcome"] for node in nodes], ["branched", "branched", "feasible_incumbent", "pruned_fully_fixed_shared_row", "feasible_incumbent"])
        self.assertEqual([entry["objective"] for entry in result["components"][0]["incumbent_history"]], ["3", "6"])
        self.assertNotIn("t", nodes[4]["fixings"])
        self.assertIsNone(nodes[0]["incumbent_before"])
        self.assertEqual(nodes[0]["inherited_upper_bound_kind"], "positive_infinity")
        expected = {"visited_nodes": 5, "queried_nodes": 4, "fully_evaluated_nodes": 4, "source_calls": 8, "optimization_requests": 8, "optimization_replies": 8, "pending_optimization_requests": 0, "branch_operations": 2, "nodes_pruned_before_query": 1, "fully_fixed_shared_row_prunes": 1, "bound_prunes_before_query": 0, "bound_prunes_after_query": 0, "fixed_values_sent": 4, "response_interface_values": 8, "shared_rows_checked": 6, "shared_rows_violated": 3, "feasible_incumbents": 2, "retention_requests": 4, "retention_confirmations": 4, "event_emission_records": 2, "max_unresolved_frontier": 3}
        for key, value in expected.items():
            with self.subTest(counter=key):
                self.assertEqual(result["metrics"][key], value)
        for node in nodes:
            for reply in node["replies"]:
                self.assertNotIn("selected_ids", reply)
        self.assertEqual(result["relative_gap"], "0")
        json.dumps(result, allow_nan=False)

    def test_all_sources_including_multiple_local_only_sources_are_queried(self):
        instance, construction = fixture(
            [candidate("a", "-0.5", 0), candidate("b", "3.25", 1), candidate("c", "1.25", 2)],
            [row("require_a", {"a": -1}, -1), row("b_cap", {"b": 1}, 1)],
        )
        result = match_distributed(instance, construction, trace=True)
        self.assertEqual(result["objective"], "4")
        self.assertEqual(result["metrics"]["source_calls"], 3)
        self.assertEqual(result["metrics"]["optimization_requests"], 3)
        self.assertEqual(result["metrics"]["retention_requests"], 3)
        self.assertEqual(result["metrics"]["response_interface_values"], 0)
        self.assertEqual(result["components"][0]["interface_variable_count"], 0)

    def test_negative_optimum_is_not_pruned_by_a_zero_initial_incumbent(self):
        instance, construction = fixture([candidate("x", "-0.125")], [row("must_select", {"x": -1}, -1)])
        result = match_distributed(instance, construction)
        self.assertEqual((result["status"], result["objective"]), ("optimal", "-1/8"))

    def test_global_empty_row_precheck_never_queries_a_source(self):
        instance, construction = fixture([candidate("x", 1)], [row("empty_ok", {}, 2), row("empty_bad", {}, -1)])
        result = match_distributed(instance, construction)
        self.assertEqual(result["status"], "infeasible")
        self.assertEqual(result["empty_row_violations"], ["empty_bad"])
        self.assertEqual(result["metrics"]["empty_rows_checked"], 2)
        self.assertEqual(result["metrics"]["source_calls"], 0)
        self.assertEqual(result["components"][0]["status"], "unknown")
        self.assertEqual(result["upper_bound_kind"], "negative_infinity")

    def test_empty_case_with_no_candidates_is_a_feasible_zero_component(self):
        instance, construction = fixture([], [row("empty_ok", {}, 0)], cases=["c"], sources=[0])
        result = match_distributed(instance, construction)
        self.assertEqual((result["status"], result["objective"], result["selected_ids"]), ("optimal", "0", []))
        self.assertEqual(result["metrics"]["source_calls"], 0)

    def test_infeasible_source_does_not_skip_other_source_queries(self):
        instance, construction = fixture([candidate("x", 1, 0), candidate("y", 2, 1)], [row("impossible", {"x": 1}, -1)])
        result = match_distributed(instance, construction)
        self.assertEqual(result["status"], "infeasible")
        self.assertEqual(result["metrics"]["source_calls"], 2)
        self.assertEqual(result["metrics"]["local_infeasible_replies"], 1)
        self.assertEqual(result["metrics"]["optimization_replies"], 2)

    def test_node_cutoff_has_a_feasible_incumbent_and_valid_global_gap(self):
        instance, construction = paper_fixture()
        result = match_distributed(instance, construction, node_limit=3)
        self.assertEqual(result["status"], "limited")
        self.assertEqual(result["selected_ids"], ["a"])
        self.assertEqual((result["lower_bound"], result["upper_bound"], result["relative_gap"]), ("3", "7", "4/3"))
        self.assertLessEqual(Fraction(result["lower_bound"]), brute_score(instance["candidates"], construction["rows"]))
        self.assertGreaterEqual(Fraction(result["upper_bound"]), brute_score(instance["candidates"], construction["rows"]))
        self.assertEqual(result["metrics"]["visited_nodes"], 3)

    def test_zero_budget_has_no_gt_warmstart(self):
        instance, construction = paper_fixture()
        result = match_distributed(instance, construction, node_limit=0)
        self.assertEqual(result["status"], "limited")
        self.assertIsNone(result["selected_ids"])
        self.assertIsNone(result["upper_bound"])
        self.assertEqual(result["upper_bound_kind"], "positive_infinity")
        self.assertEqual(result["metrics"]["source_calls"], 0)

    def test_unknown_query_cannot_replace_retained_snapshot_or_tighten_bound(self):
        instance, construction = paper_fixture()
        call_count = 0

        def interrupted(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = solve_exact(*args, **kwargs)
            if call_count == 8:
                result.update(status="unknown", reason="test interruption", certified_optimal=False)
            return result

        with patch("minea_ikea.matching.solve_exact", side_effect=interrupted):
            result = match_distributed(instance, construction, trace=True)
        self.assertEqual(result["status"], "unknown")
        # Source 0's current query now selects r, but the retained incumbent is a.
        self.assertEqual(result["selected_ids"], ["a"])
        self.assertEqual((result["lower_bound"], result["upper_bound"]), ("3", "7"))
        self.assertEqual(result["metrics"]["local_unknown_replies"], 1)
        self.assertEqual(result["metrics"]["retention_confirmations"], 2)

    def test_incumbent_requires_retention_confirmation_from_every_source(self):
        instance, construction = fixture([candidate("a", 1, 0), candidate("b", 2, 1)], [])
        original = _Source.retain

        def fail_one_confirmation(source, token):
            result = original(source, token)
            if source.identifier == 0:
                result["confirmed"] = False
            return result

        with patch.object(_Source, "retain", fail_one_confirmation):
            result = match_distributed(instance, construction)
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["selected_ids"])
        self.assertEqual(result["upper_bound"], "3")
        self.assertEqual(result["metrics"]["retention_requests"], 2)
        self.assertEqual(result["metrics"]["retention_confirmations"], 1)
        self.assertEqual(result["metrics"]["pending_retention_requests"], 1)
        self.assertEqual(result["metrics"]["feasible_incumbents"], 0)

    def test_deadline_leaves_sent_requests_pending_and_does_not_fake_replies(self):
        instance, construction = fixture([candidate("a", 1, 0), candidate("b", 2, 1), candidate("c", 3, 2)], [])
        clock = [0.0]

        def first_reply(*args, **kwargs):
            result = solve_exact(*args, **kwargs)
            clock[0] = 100.0
            return result

        with patch("minea_ikea.matching.time.monotonic", side_effect=lambda: clock[0]), patch("minea_ikea.matching.solve_exact", side_effect=first_reply):
            result = match_distributed(instance, construction, time_limit=10)
        self.assertEqual(result["status"], "limited")
        self.assertEqual(result["metrics"]["optimization_requests"], 3)
        self.assertEqual(result["metrics"]["source_calls"], 1)
        self.assertEqual(result["metrics"]["optimization_replies"], 1)
        self.assertEqual(result["metrics"]["pending_optimization_requests"], 2)
        self.assertEqual(result["metrics"]["partial_query_nodes"], 1)
        self.assertIsNone(result["upper_bound"])

    def test_node_budget_covers_all_components_and_skipped_cases_stay_unsolved(self):
        instance, construction = fixture([candidate("a", 1, case="a"), candidate("b", 2, case="b")], [], component_cases=[["a"], ["b"]])
        result = match_distributed(instance, construction, node_limit=1)
        self.assertEqual(result["status"], "limited")
        self.assertEqual([component["status"] for component in result["components"]], ["optimal", "limited"])
        self.assertIsNone(result["objective"])
        self.assertIsNone(result["selected_ids"])
        self.assertEqual(result["metrics"]["event_emission_records"], 0)

    def test_component_optima_sum_and_central_receives_all_candidate_records(self):
        candidates = [candidate("a1", 5, 0, "a"), candidate("a2", 4, 0, "a"), candidate("b", 2, 1, "b")]
        rows = [row("assignment:a", {"a1": 1, "a2": 1}, 1, kind="assignment", case="a"), row("cap_b", {"b": 1}, 1, kind="exclusion", case="b")]
        instance, construction = fixture(candidates, rows, component_cases=[["a"], ["b"]])
        distributed = match_distributed(instance, construction)
        central = match_central(instance, rows=rows, components=construction["components"])
        self.assertEqual(distributed["objective"], "7")
        self.assertEqual(central["objective"], "7")
        upload = central["central_upload"]
        self.assertEqual((upload["logical_messages"], upload["candidate_records"], upload["score_records"]), (2, 3, 3))
        self.assertEqual(upload["records_by_source"]["0"]["candidate_records"], 2)
        self.assertEqual(upload["given_row_records"], 1)
        self.assertEqual(upload["given_row_coefficient_terms"], 1)
        self.assertEqual(upload["raw_frame_records"], 0)
        self.assertEqual(central["metrics"]["central_solver_calls"], 2)
        self.assertEqual(central["metrics"]["source_calls"], 0)

    def test_central_deadline_is_for_the_whole_condition(self):
        instance, construction = fixture([candidate("a", 1, case="a"), candidate("b", 2, case="b")], [], component_cases=[["a"], ["b"]])
        clock = [0.0]

        def first_component(*args, **kwargs):
            result = solve_exact(*args, **kwargs)
            clock[0] = 100.0
            return result

        with patch("minea_ikea.matching.time.monotonic", side_effect=lambda: clock[0]), patch("minea_ikea.matching.solve_exact", side_effect=first_component):
            result = match_central(instance, rows=[], components=construction["components"], time_limit=10)
        self.assertEqual(result["status"], "limited")
        self.assertEqual([component["status"] for component in result["components"]], ["optimal", "limited"])
        self.assertIsNone(result["selected_ids"])
        self.assertEqual(result["upper_bound"], "3")
        self.assertEqual(result["metrics"]["central_solver_calls"], 1)

    def test_host_relabelling_preserves_component_order_under_budgets(self):
        instance, construction = fixture(
            [candidate("a", 1, 0, "a"), candidate("b", 2, 1, "b")], [],
            component_cases=[["a"], ["b"]],
        )
        for hosts in ({"a": 1, "b": 0}, {"a": 0, "b": 1}):
            relabelled = deepcopy(construction)
            local_instance = deepcopy(instance)
            local_instance["case_hosts"] = hosts
            for component in relabelled["components"]:
                case = component["case_ids"][0]
                component["coordinator"] = hosts[case]
                component["id"] = f"component:{hosts[case]}:{case}"
            # Deliberately supply host order; matching must normalize by cases.
            relabelled["components"].sort(key=lambda component: component["id"])
            distributed = match_distributed(local_instance, relabelled, node_limit=1)
            clock = [0.0]

            def first_component(*args, **kwargs):
                result = solve_exact(*args, **kwargs)
                clock[0] = 100.0
                return result

            with patch("minea_ikea.matching.time.monotonic", side_effect=lambda: clock[0]), patch("minea_ikea.matching.solve_exact", side_effect=first_component):
                central = match_central(local_instance, rows=[], components=relabelled["components"], time_limit=10)
            for method, result in (("distributed", distributed), ("central", central)):
                with self.subTest(hosts=hosts, method=method):
                    self.assertEqual(result["status"], "limited")
                    self.assertEqual(result["component_execution_order"], [["a"], ["b"]])
                    self.assertIn("independent", result["component_execution_order_policy"])
                    self.assertEqual([component["status"] for component in result["components"]], ["optimal", "limited"])
                    self.assertEqual(result["components"][0]["objective"], "1")
                    self.assertIsNone(result["selected_ids"])

    def test_ties_and_random_shared_rows_agree_with_independent_enumeration(self):
        generator = random.Random(7701)
        for trial in range(18):
            candidates = [candidate(f"x{index}", Fraction(generator.randint(-2, 4), 10), index % 3) for index in range(6)]
            rows = [row(f"r{index}", {item["id"]: generator.choice((-1, 0, 1)) for item in candidates}, generator.randint(-1, 2)) for index in range(4)]
            instance, construction = fixture(candidates, rows)
            expected = brute_score(candidates, rows)
            distributed = match_distributed(instance, construction)
            central = match_central(instance, rows=rows, components=construction["components"])
            with self.subTest(trial=trial):
                if expected is None:
                    self.assertEqual(distributed["status"], "infeasible")
                    self.assertEqual(central["status"], "infeasible")
                else:
                    self.assertEqual(distributed["status"], "optimal")
                    self.assertEqual(central["status"], "optimal")
                    self.assertEqual(Fraction(distributed["objective"]), expected)
                    self.assertEqual(Fraction(central["objective"]), expected)

    def test_rejects_invalid_component_partition(self):
        instance, construction = paper_fixture()
        construction["components"][0]["sources"] = [0]
        with self.assertRaisesRegex(ValueError, "Participating sources"):
            match_distributed(instance, construction)


if __name__ == "__main__":
    unittest.main()
