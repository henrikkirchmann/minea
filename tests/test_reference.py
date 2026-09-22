"""Hand-counted central encoding and exhaustive objective checks."""

from copy import deepcopy
from fractions import Fraction
import unittest

from minea_ikea.reference import (components_from_rows, encode_centrally,
                                exhaustive_optimum, validate_instance, validate_selection)


def example():
    candidates = [
        {"id": "a", "observation_id": "o0", "case_id": "j", "activity": "A",
         "start": 0, "end": 1, "score": "0.1", "owner": 0},
        {"id": "b", "observation_id": "o1", "case_id": "j", "activity": "A",
         "start": 2, "end": 3, "score": "0.2", "owner": 1},
        {"id": "t", "observation_id": "o2", "case_id": "j", "activity": "B",
         "start": 3, "end": 4, "score": "0.3", "owner": 1},
    ]
    return {"cases": ["j", "empty"], "sources": [0, 1], "case_hosts": {"j": 0, "empty": 1},
            "candidates": candidates,
            "prerequisites": [{"id": "p", "trigger_activity": "B", "predecessor_activities": ["A"]}],
            "occurrence_bounds": [{"id": "b", "activities": ["A"], "lower": 0, "upper": 1}],
            "given_rows": [{"id": f"assignment:{c['observation_id']}", "kind": "assignment",
                            "terms": {c["id"]: 1}, "upper": 1, "case_id": c["case_id"]}
                           for c in candidates], "gt_selected": [], "metadata": {}}


class CentralReferenceTests(unittest.TestCase):
    def test_all_earlier_supporters_and_boundary_are_encoded(self):
        rows = {r["id"]: r for r in encode_centrally(example())}
        self.assertEqual(rows["pre:p:t"]["terms"], {"a": -1, "b": -1, "t": 1})
        self.assertEqual(rows["upper:b:empty"]["terms"], {})
        self.assertFalse(any(r.startswith("lower:") for r in rows))

    def test_exhaustive_objective_uses_original_decimal_rationals(self):
        instance = example()
        result = exhaustive_optimum(instance, encode_centrally(instance))
        self.assertEqual(result["objective"], "1/2")
        self.assertEqual(result["selected_ids"], ["b", "t"])
        self.assertEqual(result["assignments_checked"], 8)

    def test_positive_bound_on_empty_case_is_infeasible(self):
        instance = example()
        instance["occurrence_bounds"][0]["lower"] = 1
        result = exhaustive_optimum(instance, encode_centrally(instance))
        self.assertEqual(result["status"], "infeasible")

    def test_missing_support_forbids_trigger(self):
        instance = example()
        instance["prerequisites"][0]["predecessor_activities"] = ["absent"]
        rows = encode_centrally(instance)
        self.assertEqual(next(r for r in rows if r["id"] == "pre:p:t")["terms"], {"t": 1})
        self.assertEqual(exhaustive_optimum(instance, rows)["selected_ids"], ["b"])

    def test_components_follow_row_scope_not_common_source(self):
        instance = example()
        components = components_from_rows(instance, encode_centrally(instance))
        self.assertEqual({tuple(c["case_ids"]) for c in components}, {("j",), ("empty",)})

    def test_invalid_observation_split_and_missing_assignment_are_rejected(self):
        instance = example()
        extra = deepcopy(instance["candidates"][0])
        extra.update(id="bad", owner=1)
        instance["candidates"].append(extra)
        with self.assertRaisesRegex(ValueError, "Observation alternatives"):
            validate_instance(instance)
        instance = example()
        instance["given_rows"].pop()
        with self.assertRaisesRegex(ValueError, "assignment rows"):
            encode_centrally(instance)

    def test_selection_feasibility_does_not_depend_on_reported_solver_status(self):
        instance = example()
        result = validate_selection(instance, encode_centrally(instance), ["t"])
        self.assertFalse(result["feasible"])
        self.assertEqual(result["violations"], ["pre:p:t"])
        self.assertEqual(Fraction(result["objective"]), Fraction(3, 10))

    def test_exhaustive_limit_is_explicit(self):
        instance = example()
        with self.assertRaisesRegex(ValueError, "limit"):
            exhaustive_optimum(instance, encode_centrally(instance), max_assignments=7)


if __name__ == "__main__":
    unittest.main()
