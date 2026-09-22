"""Independent protocol review: actual emissions and interrupted certificates."""

import importlib.util
import unittest
from unittest.mock import patch

import minea_ikea.matching as matching


def _candidate(ident, case, owner, score, observation=None):
    return {
        "id": ident, "observation_id": observation or ident, "case_id": case,
        "owner": owner, "activity": ident, "start": 0, "end": 1, "score": score,
    }


def _two_components(impossible_second=False):
    candidates = [_candidate("a-choice", "a", 0, "1"), _candidate("b-choice", "b", 0, "1")]
    rows = [
        {"id": f"assignment:{case}-choice", "kind": "assignment", "terms": {f"{case}-choice": 1},
         "upper": 1, "case_id": case}
        for case in ("a", "b")
    ]
    if impossible_second:
        rows.append({"id": "impossible-b", "kind": "exclusion", "terms": {"b-choice": 1},
                     "upper": -1, "case_id": "b"})
    instance = {
        "cases": ["a", "b"], "sources": [0], "case_hosts": {"a": 0, "b": 0},
        "candidates": candidates, "given_rows": rows, "prerequisites": [],
        "occurrence_bounds": [], "metadata": {},
    }
    components = [
        {"id": f"component:0:{case}", "case_ids": [case], "sources": [0], "coordinator": 0,
         "candidate_ids": [f"{case}-choice"]}
        for case in ("a", "b")
    ]
    return instance, {"rows": rows, "components": components}


def _branching_component():
    # Root relaxation 7 violates t <= r. At r=t=0 the incumbent is a, worth 3.
    # The remaining r=1 node has inherited upper bound 7 and true optimum 6.
    candidates = [_candidate("a", "c", 0, "3", "o"),
                  _candidate("r", "c", 0, "2", "o"),
                  _candidate("t", "c", 1, "4")]
    rows = [
        {"id": "assignment:o", "kind": "assignment", "terms": {"a": 1, "r": 1},
         "upper": 1, "case_id": "c"},
        {"id": "assignment:t", "kind": "assignment", "terms": {"t": 1},
         "upper": 1, "case_id": "c"},
        {"id": "pre:p:t", "kind": "prerequisite", "terms": {"t": 1, "r": -1},
         "upper": 0, "case_id": "c"},
    ]
    instance = {
        "cases": ["c"], "sources": [0, 1], "case_hosts": {"c": 0}, "candidates": candidates,
        "given_rows": rows[:2], "prerequisites": [], "occurrence_bounds": [], "metadata": {},
    }
    construction = {"rows": rows, "components": [
        {"id": "component:0:c", "case_ids": ["c"], "sources": [0, 1], "coordinator": 0,
         "candidate_ids": ["a", "r", "t"]}
    ]}
    return instance, construction


@unittest.skipUnless(importlib.util.find_spec("z3"), "requires the pinned z3-solver dependency")
class MatchingReviewTests(unittest.TestCase):
    def _with_observed_emissions(self, instance, construction, **options):
        emissions = []
        original = matching._Source.emit

        def observe(source, token):
            selected = original(source, token)
            emissions.append({"source": source.identifier, "token": token, "selected_ids": selected})
            return selected

        with patch.object(matching._Source, "emit", observe):
            result = matching.match_distributed(instance, construction, time_limit=None, trace=True, **options)
        actual_records = sum(len(item["selected_ids"]) for item in emissions)
        self.assertEqual(result["metrics"]["event_emission_records"], actual_records)
        traced = [event for event in result["trace"] if event["event"] == "event_emission"]
        self.assertEqual(sum(event["records"] for event in traced), actual_records)
        self.assertEqual(len(traced), len(emissions))
        return result, emissions

    def test_actual_emissions_are_counted_for_a_complete_global_selection(self):
        result, emissions = self._with_observed_emissions(*_two_components(), node_limit=None)
        self.assertEqual(result["status"], "optimal")
        self.assertEqual(result["selected_ids"], ["a-choice", "b-choice"])
        self.assertEqual(len(emissions), 2)
        self.assertEqual(result["metrics"]["event_emission_records"], 2)

    def test_a_later_infeasible_component_prevents_all_actual_emissions(self):
        result, emissions = self._with_observed_emissions(*_two_components(True), node_limit=None)
        self.assertEqual([component["status"] for component in result["components"]], ["optimal", "infeasible"])
        self.assertEqual(result["status"], "infeasible")
        self.assertIsNone(result["selected_ids"])
        self.assertEqual(emissions, [])

    def test_unstarted_component_prevents_emission_of_a_partial_global_selection(self):
        result, emissions = self._with_observed_emissions(*_two_components(), node_limit=1)
        self.assertEqual([component["status"] for component in result["components"]], ["optimal", "limited"])
        self.assertEqual(result["status"], "limited")
        self.assertIsNone(result["selected_ids"])
        self.assertEqual(emissions, [])

    def test_partial_query_preserves_the_old_retained_incumbent_and_active_bound(self):
        instance, construction = _branching_component()
        original_query = matching._Source.query
        original_emit = matching._Source.emit
        clock = {"now": 0.0, "queries": 0}
        emitted = []

        def interrupted_query(source, token, fixings, deadline):
            response = original_query(source, token, fixings, deadline)
            clock["queries"] += 1
            if clock["queries"] == 7:
                # Source 0 has switched current to r=1, but the old a selection
                # must stay retained. Source 1's eighth request remains pending.
                self.assertEqual(source.identifier, 0)
                self.assertEqual(fixings, {"r": 1})
                clock["now"] = 2.0
            return response

        def observe_emit(source, token):
            values = original_emit(source, token)
            emitted.extend(values)
            return values

        with patch.object(matching.time, "monotonic", lambda: clock["now"]), \
                patch.object(matching._Source, "query", interrupted_query), \
                patch.object(matching._Source, "emit", observe_emit):
            result = matching.match_distributed(instance, construction, time_limit=1, node_limit=None, trace=True)

        self.assertEqual(result["status"], "limited")
        self.assertEqual(result["selected_ids"], ["a"])
        self.assertEqual(emitted, ["a"])
        self.assertEqual((result["lower_bound"], result["upper_bound"]), ("3", "7"))
        metrics = result["metrics"]
        self.assertEqual(metrics["optimization_requests"], 8)
        self.assertEqual(metrics["optimization_replies"], 7)
        self.assertEqual(metrics["pending_optimization_requests"], 1)
        self.assertEqual(metrics["partial_query_nodes"], 1)
        self.assertEqual(metrics["fully_evaluated_nodes"], 3)
        self.assertEqual(metrics["event_emission_records"], len(emitted))
        self.assertEqual(result["components"][0]["unresolved_nodes"][0]["fixings"], {"r": 1})


if __name__ == "__main__":
    unittest.main()
