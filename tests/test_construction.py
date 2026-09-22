"""Hand-countable executions of the logical construction protocol."""

import copy
import json
import unittest

from minea_ikea.construction import construct


def candidate(ident, case="a", owner=0, activity="A", start=0, end=1, observation=None):
    return {
        "id": ident, "observation_id": observation or f"obs:{ident}",
        "case_id": case, "owner": owner, "activity": activity,
        "start": start, "end": end, "score": "0.5",
    }


def instance(candidates=(), cases=("a",), sources=(0,), hosts=None, prerequisites=(), bounds=(), rows=()):
    return {
        "cases": list(cases), "sources": list(sources),
        "case_hosts": hosts or {case: sources[0] for case in cases},
        "candidates": list(candidates), "prerequisites": list(prerequisites),
        "occurrence_bounds": list(bounds), "given_rows": list(rows),
        "gt_selected": [], "metadata": {},
    }


def exclusion(ident, *candidates):
    return {"id": ident, "kind": "exclusion", "terms": dict.fromkeys(candidates, 1),
            "upper": 1, "case_id": None}


def prerequisite(predecessors=("A",), trigger="B", ident="p", **extra):
    return {"id": ident, "trigger_activity": trigger, "predecessor_activities": list(predecessors), **extra}


def by_id(result):
    return {row["id"]: row for row in result["rows"]}


def messages(result, kind):
    return [message for message in result["trace"] if message["kind"] == kind]


class ConstructionTests(unittest.TestCase):
    def test_election_is_synchronous_and_runs_global_n_minus_one_rounds(self):
        candidates = [candidate(case, case) for case in ("a", "b", "c", "d")]
        rows = [exclusion("ab", "a", "b"), exclusion("bc", "b", "c"), exclusion("cd", "c", "d")]
        result = construct(instance(candidates, ("a", "b", "c", "d", "isolated"), (0, 1, 2, 3, 4),
                                    {"a": 0, "b": 1, "c": 2, "d": 3, "isolated": 4}, rows=rows), trace=True)
        rank_messages = messages(result, "rank_transmission")
        self.assertEqual(len(rank_messages), 24)  # Six directed edges, four rounds, not diameter three.
        self.assertEqual({message["stage_round"] for message in rank_messages}, {1, 2, 3, 4})
        first_b_to_c = next(message for message in rank_messages if message["stage_round"] == 1
                            and message["sender"]["id"] == "b" and message["receiver"]["id"] == "c")
        second_c_to_d = next(message for message in rank_messages if message["stage_round"] == 2
                             and message["sender"]["id"] == "c" and message["receiver"]["id"] == "d")
        third_c_to_d = next(message for message in rank_messages if message["stage_round"] == 3
                            and message["sender"]["id"] == "c" and message["receiver"]["id"] == "d")
        self.assertEqual(first_b_to_c["payload"]["rank"], [1, "b"])
        self.assertEqual(second_c_to_d["payload"]["rank"], [1, "b"])
        self.assertEqual(third_c_to_d["payload"]["rank"], [0, "a"])
        self.assertEqual([component["case_ids"] for component in result["components"]],
                         [["a", "b", "c", "d"], ["isolated"]])
        self.assertEqual(result["metrics"]["stages"]["coordinator_election"]["configured_rounds"], 4)

    def test_duplicate_edges_are_announced_but_neighbors_are_deduplicated(self):
        result = construct(instance([candidate("a", "a"), candidate("b", "b"), candidate("c", "c")],
                                    ("a", "b", "c"), rows=[exclusion("triple", "a", "b", "c"),
                                                              exclusion("repeat", "a", "b")]), trace=True)
        counts = result["metrics"]["stages"]["case_edge_discovery"]
        self.assertEqual(counts["type2_rows"], 2)
        self.assertEqual(counts["edge_announcements"], 8)
        self.assertEqual(counts["unique_undirected_edges"], 3)
        self.assertEqual(counts["duplicate_announcements"], 2)
        self.assertEqual(counts["duplicate_edge_reports"], 1)
        self.assertEqual(len(messages(result, "rank_transmission")), 12)
        self.assertEqual(result["neighbors"]["a"], {"b": 0, "c": 0})

    def test_components_sharing_coordinator_host_remain_distinct_and_work_adds(self):
        result = construct(instance([candidate("a", "a", owner=1), candidate("b", "b", owner=1)],
                                    ("a", "b"), (0, 1), {"a": 0, "b": 0}), trace=True)
        self.assertEqual([component["id"] for component in result["components"]],
                         ["component:0:a", "component:0:b"])
        self.assertEqual([component["sources"] for component in result["components"]], [[1], [1]])
        self.assertEqual(len(messages(result, "source_registration")), 2)
        metrics = result["metrics"]
        component_max = metrics["maxima"]["per_component"]["totals"]["messages"]
        host_max = metrics["maxima"]["per_host"]["totals"]["messages"]
        self.assertEqual(host_max, 2 * component_max)
        self.assertEqual(metrics["per_host"]["0"]["totals"]["messages"], metrics["totals"]["messages"])
        self.assertEqual(metrics["per_host"]["1"]["totals"]["messages"], 0)

    def test_empty_directories_still_initiate_bounds_and_positive_minimum_fails(self):
        result = construct(instance(cases=("empty",), bounds=[
            {"id": "required", "activities": ["A"], "lower": 1, "upper": 2},
            {"id": "optional", "activities": ["Z"], "lower": 0, "upper": 0},
        ]), trace=True)
        rows = by_id(result)
        self.assertEqual(result["directories"], {"empty": []})
        self.assertEqual(result["status"], "infeasible")
        self.assertEqual(result["failed_empty_rows"], ["lower:required:empty"])
        self.assertEqual(rows["lower:required:empty"]["terms"], {})
        self.assertEqual(rows["lower:required:empty"]["upper"], -1)
        self.assertNotIn("lower:optional:empty", rows)
        self.assertEqual(result["components"][0]["sources"], [])
        self.assertEqual(result["components"][0]["status"], "infeasible")
        counts = result["metrics"]["stages"]["intra_case_row_construction"]
        self.assertEqual(counts["bound_initiations"], 3)
        self.assertEqual(counts["lookup_requests"], 0)
        self.assertEqual(counts["empty_row_checks_passed"], 2)
        self.assertEqual(counts["empty_row_checks_failed"], 1)
        self.assertFalse(messages(result, "row_storage_acknowledgment"))
        self.assertFalse(messages(result, "case_agent_completion")[0]["payload"]["success"])

    def test_trigger_without_predecessor_is_local_and_all_directory_sources_reply(self):
        result = construct(instance([candidate("trigger", owner=1, activity="B"),
                                     candidate("irrelevant", owner=2, activity="Z")],
                                    sources=(0, 1, 2), prerequisites=[prerequisite()]), trace=True)
        self.assertEqual(result["directories"]["a"], [1, 2])
        self.assertEqual(by_id(result)["pre:p:trigger"]["terms"], {"trigger": 1})
        self.assertEqual(result["row_owners"]["pre:p:trigger"]["source"], 1)
        self.assertEqual(result["row_owners"]["pre:p:trigger"]["classification"], "local")
        self.assertEqual(result["contributors"]["pre:p:trigger"], [1])
        replies = messages(result, "presence_reply")
        self.assertEqual([reply["payload"]["present"] for reply in replies], [True, False])
        self.assertEqual(len(messages(result, "lookup_request")), 2)
        self.assertEqual(len(messages(result, "source_registration")), 2)
        self.assertFalse(messages(result, "shared_fragment"))
        self.assertEqual(len(messages(result, "store_local_row")), 1)
        self.assertEqual(len(messages(result, "row_storage_acknowledgment")), 1)

    def test_multiple_predecessor_activities_boundary_and_case_filtering(self):
        values = [
            candidate("touching", owner=0, activity="A", end=5),
            candidate("earlier", owner=1, activity="C", end=4),
            candidate("overlap", owner=1, activity="A", end=6),
            candidate("irrelevant", owner=2, activity="Z"),
            candidate("trigger", owner=1, activity="B", start=5, end=7),
            candidate("othercase", case="b", owner=0, activity="A", end=1),
        ]
        result = construct(instance(values, ("a", "b"), (0, 1, 2),
                                    prerequisites=[prerequisite(("A", "C"))]), trace=True)
        self.assertEqual(by_id(result)["pre:p:trigger"]["terms"],
                         {"earlier": -1, "touching": -1, "trigger": 1})
        self.assertEqual(result["contributors"]["pre:p:trigger"], [0, 1])
        self.assertEqual(result["row_owners"]["pre:p:trigger"]["classification"], "shared")
        transfers = messages(result, "shared_fragment")
        self.assertEqual(len(transfers), 2)
        self.assertEqual(sum(item["coefficient_terms"] for item in transfers), 3)
        self.assertTrue(any(item["colocated"] for item in transfers))
        for message in messages(result, "presence_reply"):
            self.assertEqual(set(message["payload"]), {"row_id", "present"})
            self.assertEqual(message["coefficient_terms"], 0)
        completion = messages(result, "row_storage_acknowledgment")[0]
        self.assertGreater(completion["round"], max(item["round"] for item in transfers))

    def test_upper_and_positive_lower_query_separately_and_zero_lower_is_omitted(self):
        result = construct(instance([candidate("a0", owner=0), candidate("a1", owner=1),
                                     candidate("z", owner=2, activity="Z")], sources=(0, 1, 2), bounds=[
            {"id": "both", "activities": ["A"], "lower": 1, "upper": 2},
            {"id": "zero", "activities": ["missing"], "lower": 0, "upper": 0},
        ]), trace=True)
        rows = by_id(result)
        self.assertEqual(rows["upper:both:a"]["terms"], {"a0": 1, "a1": 1})
        self.assertEqual(rows["lower:both:a"]["terms"], {"a0": -1, "a1": -1})
        self.assertEqual(rows["upper:zero:a"]["terms"], {})
        self.assertNotIn("lower:zero:a", rows)
        counts = result["metrics"]["stages"]["intra_case_row_construction"]
        self.assertEqual(counts["bound_initiations"], 3)
        self.assertEqual(counts["lookup_requests"], 9)
        self.assertEqual(counts["positive_presence_replies"], 4)
        self.assertEqual(counts["negative_presence_replies"], 5)
        self.assertEqual(counts["retained_fragments"], 4)
        self.assertEqual(counts["shared_fragment_transfers"], 4)
        self.assertEqual(counts["retained_coefficient_terms"], 4)
        self.assertEqual(counts["transferred_coefficient_terms"], 4)
        self.assertEqual(counts["shared_rows"], 2)
        self.assertEqual(counts["empty_row_checks_passed"], 1)

    def test_local_only_sources_register_and_given_rows_stay_local(self):
        row = {"id": "assignment:o", "kind": "assignment", "terms": {"x": 1, "y": 1},
               "upper": 1, "case_id": "a"}
        original = instance([candidate("x", owner=2, observation="o"),
                             candidate("y", owner=2, observation="o")], sources=(0, 1, 2), rows=[row])
        result = construct(original, trace=True)
        self.assertEqual(result["rows"], [row])
        self.assertEqual(result["components"][0]["sources"], [2])
        self.assertEqual(result["row_owners"][row["id"]]["source"], 2)
        self.assertEqual(len(messages(result, "source_registration")), 1)
        self.assertEqual(result["metrics"]["stages"]["case_edge_discovery"]["given_local_rows"], 1)
        self.assertEqual(result["metrics"]["stages"]["intra_case_row_construction"]["local_rows"], 0)

    def test_message_totals_match_trace_and_colocation_is_not_elided(self):
        result = construct(instance([candidate("p", end=1), candidate("t", activity="B", start=1, end=2)],
                                    prerequisites=[prerequisite()]), trace=True)
        totals = result["metrics"]["totals"]
        self.assertEqual(totals["messages"], len(result["trace"]))
        self.assertEqual(totals["payload_records"], len(result["trace"]))
        self.assertEqual(totals["colocated_messages"], len(result["trace"]))
        self.assertEqual(totals["cross_host_messages"], 0)
        self.assertEqual(totals["coefficient_terms"], 0)
        self.assertEqual(totals["messages"], 10)
        self.assertEqual(totals["retained_coefficient_terms"], 2)
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_own_trigger_never_serves_as_its_own_predecessor(self):
        result = construct(instance([candidate("self", activity="A", start=0, end=0)],
                                    prerequisites=[prerequisite(("A",), "A")]))
        self.assertEqual(by_id(result)["pre:p:self"]["terms"], {"self": 1})

    def test_optional_delay_bounds_are_exact_and_inclusive(self):
        result = construct(instance([
            candidate("too_early", end=1), candidate("max_boundary", end=2),
            candidate("min_boundary", end=4), candidate("too_late", end=5),
            candidate("t", activity="B", start=5, end=6),
        ], prerequisites=[prerequisite(min_delay=1, max_delay=3)]))
        self.assertEqual(by_id(result)["pre:p:t"]["terms"],
                         {"max_boundary": -1, "min_boundary": -1, "t": 1})

    def test_duplicate_ownership_and_nonlocal_given_rows_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "ownership must be unique"):
            construct(instance([candidate("same", owner=0), candidate("same", owner=1)], sources=(0, 1)))
        with self.assertRaisesRegex(ValueError, "one owner"):
            construct(instance([candidate("x", owner=0, observation="o"),
                                candidate("y", owner=1, observation="o")], sources=(0, 1)))
        with self.assertRaisesRegex(ValueError, "not local"):
            construct(instance([candidate("x", owner=0), candidate("y", owner=1)], sources=(0, 1),
                               rows=[exclusion("bad", "x", "y")]))

    def test_coefficients_bounds_and_timestamps_reject_nonintegers(self):
        for value in (True, 1.0, "1"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "exact"):
                    construct(instance([candidate("x")], bounds=[
                        {"id": "bad", "activities": ["A"], "lower": 0, "upper": value}]))
                with self.assertRaisesRegex(ValueError, "exact"):
                    construct(instance([candidate("x", start=value)]))
                row = exclusion("bad", "x")
                row["terms"]["x"] = value
                with self.assertRaisesRegex(ValueError, "exact"):
                    construct(instance([candidate("x")], rows=[row]))

    def test_huge_integer_empty_check_does_not_round(self):
        minimum = 10 ** 200
        result = construct(instance(bounds=[
            {"id": "large", "activities": ["A"], "lower": minimum, "upper": None}]))
        self.assertEqual(result["rows"][0]["upper"], -minimum)
        self.assertEqual(result["status"], "infeasible")

    def test_no_cases_and_no_candidates_is_a_complete_empty_epoch(self):
        result = construct(instance(cases=(), sources=()), trace=True)
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["components"], [])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["metrics"]["totals"]["messages"], 0)
        self.assertEqual(result["metrics"]["totals"]["configured_rounds"], 0)

    def test_input_order_and_trace_collection_do_not_change_results(self):
        original = instance([candidate("a", case="a"), candidate("b", case="b")],
                            cases=("a", "b"), rows=[exclusion("ab", "a", "b")],
                            bounds=[{"id": "bound", "activities": ["A"], "lower": 0, "upper": 1}])
        preserved = copy.deepcopy(original)
        left = construct(original, trace=True)
        original["cases"].reverse()
        original["candidates"].reverse()
        right = construct(original, trace=True)
        self.assertEqual(left, right)
        untraced = construct(preserved)
        self.assertEqual(untraced["trace"], [])
        left["trace"] = []
        self.assertEqual(left, untraced)


if __name__ == "__main__":
    unittest.main()
