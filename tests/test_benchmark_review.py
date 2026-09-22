"""Independent cross-module checks, including malformed result certificates."""

from collections import Counter
from copy import deepcopy
from fractions import Fraction
from itertools import product
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark import check_matching_result, main, upload_centrally
from minea_ikea.construction import construct
from minea_ikea.instances import build_instance, generate_plan, semantic_violations
from minea_ikea.reference import compare_construction, encode_centrally, validate_selection
from tests.test_instances import toy_dataset


def constrained_toy():
    dataset = toy_dataset(2, 2)
    dataset["prerequisites"] = [{"id": "requires_a", "trigger_activity": "B",
                                 "predecessor_activities": ["A"]}]
    dataset["occurrence_bounds"] = [
        {"id": "a", "activities": ["A"], "lower": 0, "upper": 2},
        {"id": "b", "activities": ["B"], "lower": 0, "upper": 1},
        {"id": "absent", "activities": ["absent"], "lower": 0, "upper": 0},
    ]
    return dataset


class UploadAndEncodingReviewTests(unittest.TestCase):
    def test_central_upload_has_identical_scores_and_model_without_ground_truth(self):
        dataset = constrained_toy()
        plan = generate_plan(dataset, 918)
        for sources in (1, 2, 4, 8):
            original = build_instance(dataset, plan, sources, 1)
            before = deepcopy(original)
            uploaded, counts = upload_centrally(original)
            self.assertNotIn("gt_selected", uploaded)
            self.assertNotIn("metadata", uploaded)
            self.assertEqual(uploaded["candidates"], original["candidates"])
            self.assertEqual(encode_centrally(uploaded), encode_centrally(original))
            self.assertEqual(counts["upload_messages"], sources)
            self.assertEqual(counts["candidate_records"], len(original["candidates"]))
            self.assertEqual(counts["score_values"], len(original["candidates"]))
            self.assertEqual(counts["given_exclusion_rows"], 1)
            self.assertEqual(counts["given_coefficient_terms"], 2)
            self.assertEqual(original, before)

    def test_all_toy_assignments_agree_with_independent_event_semantics(self):
        dataset = constrained_toy()
        plan = generate_plan(dataset, 18)
        instance = build_instance(dataset, plan, 4, 1)
        constructed = construct(instance)
        self.assertEqual(compare_construction(instance, constructed)["status"], "PASS")
        uploaded, _ = upload_centrally(instance)
        rows = encode_centrally(uploaded)
        choices = {}
        scores = {}
        for candidate in instance["candidates"]:
            choices.setdefault(candidate["observation_id"], [None]).append(candidate["id"])
            scores[candidate["id"]] = Fraction(candidate["score"])
        feasible = 0
        for assignment in product(*choices.values()):
            selected = [identifier for identifier in assignment if identifier is not None]
            semantic = not semantic_violations(instance, selected)
            encoded = validate_selection(instance, rows, selected)
            self.assertEqual(encoded["feasible"], semantic)
            self.assertEqual(Fraction(encoded["objective"]), sum((scores[identifier] for identifier in selected), Fraction()))
            feasible += semantic
        self.assertGreater(feasible, 0)
        self.assertLess(feasible, 4 ** 4)

    def test_complete_trace_matches_counted_deliveries_and_source_membership(self):
        dataset = constrained_toy()
        instance = build_instance(dataset, generate_plan(dataset, 182), 4, 1)
        result = construct(instance, trace=True)
        trace = result["trace"]
        metrics = result["metrics"]
        self.assertEqual(len(trace), metrics["totals"]["messages"])
        self.assertEqual(sum(message["coefficient_terms"] for message in trace),
                         metrics["totals"]["coefficient_terms"])
        by_kind = Counter(message["kind"] for message in trace)
        self.assertEqual(by_kind["edge_announcement"], 2)
        self.assertEqual(by_kind["rank_transmission"], 2 * (len(instance["cases"]) - 1))
        expected_sources = {candidate["owner"] for candidate in instance["candidates"]}
        self.assertEqual(by_kind["source_registration"], len(expected_sources))
        self.assertEqual(result["components"][0]["sources"], sorted(expected_sources))
        stages = metrics["stages"]["intra_case_row_construction"]
        self.assertEqual(stages["lookup_requests"], stages["positive_presence_replies"] + stages["negative_presence_replies"])
        self.assertEqual(stages["retained_fragments"], stages["positive_presence_replies"])
        self.assertEqual(stages["shared_fragment_transfers"], by_kind["shared_fragment"])
        self.assertEqual(stages["transferred_coefficient_terms"],
                         sum(message["coefficient_terms"] for message in trace if message["kind"] == "shared_fragment"))
        self.assertEqual(stages["omitted_zero_lower_rows"], len(instance["cases"]) * len(instance["occurrence_bounds"]))
        self.assertEqual(stages["empty_rows"], len(instance["cases"]))


class ResultCertificateReviewTests(unittest.TestCase):
    def setUp(self):
        self.instance = toy_dataset(1, 1, ("A",))
        self.rows = encode_centrally(self.instance)
        self.good = {"status": "limited", "selected_ids": self.instance["gt_selected"],
                     "objective": "1/10", "lower_bound": "1/10", "upper_bound": "1/5"}

    def test_correct_limited_incumbent_is_accepted(self):
        self.assertTrue(check_matching_result(self.instance, self.rows, self.good)["feasible"])

    def test_limited_lower_bound_must_match_the_returned_incumbent(self):
        bad = self.good | {"lower_bound": "1/20"}
        with self.assertRaises(ValueError):
            check_matching_result(self.instance, self.rows, bad)

    def test_finite_upper_bound_cannot_exclude_a_returned_feasible_incumbent(self):
        bad = self.good | {"lower_bound": "0", "upper_bound": "1/20"}
        with self.assertRaises(ValueError):
            check_matching_result(self.instance, self.rows, bad)

    def test_infeasible_status_cannot_accompany_a_feasible_selection(self):
        bad = self.good | {"status": "infeasible"}
        with self.assertRaises(ValueError):
            check_matching_result(self.instance, self.rows, bad)


class SweepCheckReviewTests(unittest.TestCase):
    def test_optimum_monotonicity_check_is_independent_of_component_order(self):
        dataset = toy_dataset(2, 1)

        def impossible_results(instance, folder, **kwargs):
            components = instance["metadata"]["component_count"]
            return {"components": components, "central_status": "optimal",
                    "distributed_status": "limited", "central_objective": "2" if components == 1 else "1",
                    "numerical_model_sha256": str(components)}

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "invalid_sweep"
            with patch("minea_ikea.instances.load_dataset", return_value=dataset), \
                    patch("benchmark.run_condition", side_effect=impossible_results), \
                    patch("benchmark.read_json", return_value={"metrics": {}}):
                with self.assertRaises(ValueError):
                    main(["--sources", "1", "--components", "1,2", "--construction-only",
                          "--output", str(output)])


if __name__ == "__main__":
    unittest.main()
