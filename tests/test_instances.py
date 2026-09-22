"""Small semantic counterexamples and fixed-population instance invariants."""

from copy import deepcopy
import csv
from fractions import Fraction
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from minea_ikea.instances import (
    build_instance,
    generate_plan,
    load_dataset,
    semantic_violations,
    validate_plan,
)


def toy_dataset(case_count=5, observations_per_case=3, alternatives=("A", "B", "C")):
    cases = [f"c{index}" for index in range(case_count)]
    candidates, given, gt = [], [], []
    for case in cases:
        for position in range(observations_per_case):
            observation = f"{case}:e{position}"
            terms = {}
            for activity in alternatives:
                identifier = f"v{len(candidates):06d}"
                candidates.append({"id": identifier, "observation_id": observation,
                                   "case_id": case, "activity": activity,
                                   "start": position * 2, "end": position * 2 + 1,
                                   "score": {"A": "0.10", "B": "0.2", "C": "0.3000000000000000001"}[activity],
                                   "owner": 0})
                terms[identifier] = 1
                if activity == "A":
                    gt.append(identifier)
            given.append({"id": f"assignment:{observation}", "kind": "assignment",
                          "terms": terms, "upper": 1, "case_id": case})
    return {"cases": cases, "sources": [0], "case_hosts": {case: 0 for case in cases},
            "candidates": candidates, "prerequisites": [], "occurrence_bounds": [],
            "given_rows": given, "gt_selected": gt, "metadata": {}}


def candidate_id(dataset, observation, activity):
    return next(candidate["id"] for candidate in dataset["candidates"]
                if candidate["observation_id"] == observation and candidate["activity"] == activity)


def write_prepared(folder, reverse=False, include_empty=False):
    """Tiny input in the real prepared format, including lexical score details."""
    certain = [
        {"event_id": "z", "case_id": "b", "start_frame": 4, "end_frame_exclusive": 5, "activity": "A"},
        {"event_id": "a", "case_id": "a", "start_frame": 0, "end_frame_exclusive": 1, "activity": "A"},
    ]
    uncertain = [{key: value for key, value in event.items() if key != "activity"} |
                 {"scores": '{"C":1e-05,"A":0.123456789012345678901234567890123456789,"B":0.2000}'}
                 for event in certain]
    cases = [{"case_id": "b"}, {"case_id": "a"}]
    if include_empty:
        cases.append({"case_id": "empty"})
    for name, rows in (("cases.csv", cases), ("ground_truth.csv", certain), ("uncertain_log.csv", uncertain)):
        if reverse:
            rows = list(reversed(rows))
        with (folder / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (folder / "constraints.json").write_text(json.dumps({"constraints": [
        {"id": "occ_A", "kind": "occurrence_bound", "activities": ["A"], "lower": 0, "upper": 1},
    ]}), encoding="utf-8")


class DatasetLoaderTests(unittest.TestCase):
    def test_original_numeric_tokens_and_stable_candidate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write_prepared(folder)
            first = load_dataset(folder)
            write_prepared(folder, reverse=True)
            second = load_dataset(folder)
        self.assertEqual(first["candidates"], second["candidates"])
        self.assertEqual([candidate["id"] for candidate in first["candidates"]],
                         [f"v{index:06d}" for index in range(6)])
        self.assertEqual([candidate["score"] for candidate in first["candidates"][:3]],
                         ["0.123456789012345678901234567890123456789", "0.2000", "1e-05"])
        self.assertEqual(first["metadata"]["dataset_fingerprint"], second["metadata"]["dataset_fingerprint"])
        self.assertEqual(json.loads(json.dumps(first)), first)
        self.assertEqual(first["given_rows"][0]["id"], "assignment:a")
        self.assertEqual(first["occurrence_bounds"][0]["lower"], 0)
        self.assertIs(type(first["occurrence_bounds"][0]["lower"]), int)

    def test_loader_preserves_population_including_an_explicit_empty_case(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write_prepared(folder, include_empty=True)
            dataset = load_dataset(folder)
        self.assertEqual(dataset["cases"], ["a", "b", "empty"])
        self.assertEqual(dataset["metadata"]["empty_case_ids"], ["empty"])
        self.assertFalse(dataset["metadata"]["population_filter_applied"])

    def test_loader_rejects_missing_gt_candidate_instead_of_repairing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write_prepared(folder)
            path = folder / "ground_truth.csv"
            path.write_text(path.read_text().replace(",A\n", ",missing\n"))
            with self.assertRaisesRegex(ValueError, "GT label is missing"):
                load_dataset(folder)

    def test_loader_rejects_duplicate_score_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write_prepared(folder)
            path = folder / "uncertain_log.csv"
            path.write_text(path.read_text().replace('""B"":0.2000', '""A"":0.2000'))
            with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
                load_dataset(folder)


class SemanticCertificateTests(unittest.TestCase):
    def test_assignment_is_at_most_one_and_never_exactly_one(self):
        dataset = toy_dataset(1, 1)
        self.assertEqual(semantic_violations(dataset, []), [])
        chosen = [candidate_id(dataset, "c0:e0", activity) for activity in ("A", "B")]
        self.assertTrue(any(item["kind"] == "assignment" for item in semantic_violations(dataset, chosen)))

    def test_temporal_boundary_and_removing_a_required_predecessor(self):
        dataset = toy_dataset(1, 2)
        a = candidate_id(dataset, "c0:e0", "A")
        b = candidate_id(dataset, "c0:e1", "B")
        dataset["gt_selected"] = [a, b]
        for candidate in dataset["candidates"]:
            if candidate["observation_id"] == "c0:e0":
                candidate["end"] = 2
        dataset["prerequisites"] = [{"id": "p", "trigger_activity": "B", "predecessor_activities": ["A"]}]
        self.assertEqual(semantic_violations(dataset, [a, b]), [])
        plan = generate_plan(dataset, 1)
        safe = {item["replacement_candidate_id"] for item in plan["safe_swaps"]}
        self.assertNotIn(candidate_id(dataset, "c0:e0", "C"), safe)
        self.assertIn(candidate_id(dataset, "c0:e1", "C"), safe)
        overlap = deepcopy(dataset)
        for candidate in overlap["candidates"]:
            if candidate["observation_id"] == "c0:e0":
                candidate["end"] = 3
        self.assertTrue(any(item["kind"] == "prerequisite" for item in semantic_violations(overlap, [a, b])))

    def test_predecessor_in_another_case_does_not_support_trigger(self):
        dataset = toy_dataset(2, 1)
        dataset["prerequisites"] = [{"id": "p", "trigger_activity": "B", "predecessor_activities": ["A"]}]
        for candidate in dataset["candidates"]:
            if candidate["case_id"] == "c1":
                candidate["start"], candidate["end"] = 2, 3
        chosen = [candidate_id(dataset, "c0:e0", "A"), candidate_id(dataset, "c1:e0", "B")]
        self.assertTrue(any(item["kind"] == "prerequisite" for item in semantic_violations(dataset, chosen)))

    def test_positive_minima_and_absent_activity_upper_bounds_are_semantic(self):
        dataset = toy_dataset(1, 1)
        dataset["occurrence_bounds"] = [{"id": "a", "activities": ["A"], "lower": 1, "upper": 1},
                                        {"id": "b", "activities": ["B"], "lower": 0, "upper": 0},
                                        {"id": "absent", "activities": ["absent"], "lower": 0, "upper": 0}]
        plan = generate_plan(dataset, 2)
        self.assertEqual(plan["safe_swaps"], [])
        self.assertEqual(len(semantic_violations(dataset, [])), 1)
        self.assertEqual(semantic_violations(dataset, dataset["gt_selected"]), [])

    def test_fixed_cross_case_given_rows_are_included_in_swap_audit(self):
        dataset = toy_dataset(2, 1)
        a = candidate_id(dataset, "c0:e0", "A")
        b = candidate_id(dataset, "c1:e0", "B")
        dataset["given_rows"].append({"id": "fixed", "kind": "exclusion", "terms": {a: 1, b: 1},
                                      "upper": 1, "case_id": None})
        plan = generate_plan(dataset, 5)
        self.assertNotIn(b, {swap["replacement_candidate_id"] for swap in plan["safe_swaps"]})


class HierarchyTests(unittest.TestCase):
    def test_two_case_plan_needs_only_one_eligible_observation_per_case(self):
        dataset = toy_dataset(2, 1)
        plan = generate_plan(dataset, 17)
        self.assertEqual(plan["metadata"]["levels"], 1)
        self.assertEqual(len(plan["bridges"]), 1)
        self.assertEqual(len(plan["ownership_blocks"]), 1)
        self.assertEqual(plan["validation"]["checked_witnesses"], 1)

    def test_single_case_without_alternatives_needs_no_endpoint(self):
        dataset = toy_dataset(1, 1, ("A",))
        plan = generate_plan(dataset, 0)
        self.assertEqual(plan["bridges"], [])
        self.assertEqual(build_instance(dataset, plan, 8, 1)["metadata"]["component_diameters"], [0])

    def test_no_available_endpoint_has_an_explicit_error(self):
        for dataset in (toy_dataset(2, 1, ("A",)), toy_dataset(3, 1)):
            with self.subTest(cases=len(dataset["cases"])):
                with self.assertRaisesRegex(ValueError, "No unused eligible observation endpoint at level"):
                    generate_plan(dataset, 0)

    def test_seeded_hierarchy_is_serializable_reproducible_and_fresh(self):
        dataset = toy_dataset()
        plan = generate_plan(dataset, 13)
        self.assertEqual(plan, generate_plan(dataset, 13))
        self.assertEqual(plan, json.loads(json.dumps(plan)))
        self.assertNotEqual(plan["case_permutation"], generate_plan(dataset, 14)["case_permutation"])
        endpoints = [bridge[key] for bridge in plan["bridges"] for key in ("a_observation_id", "b_observation_id")]
        self.assertEqual(len(endpoints), len(set(endpoints)))
        used_per_level = [(bridge["level"], bridge[key]) for bridge in plan["bridges"]
                          for key in ("a_case_id", "b_case_id")]
        self.assertEqual(len(used_per_level), len(set(used_per_level)))

    def test_every_prefix_and_nested_owner_group_preserves_the_model(self):
        dataset = toy_dataset()
        original = deepcopy(dataset)
        plan = generate_plan(dataset, 11)
        expected_owners = {}
        previous_rows = None
        for components in range(5, 0, -1):
            for sources in (1, 2, 4, 8):
                instance = build_instance(dataset, plan, sources, components)
                by_id = {candidate["id"]: candidate for candidate in instance["candidates"]}
                owners = {identifier: candidate["owner"] for identifier, candidate in by_id.items()}
                if sources in expected_owners:
                    self.assertEqual(owners, expected_owners[sources])
                expected_owners[sources] = owners
                self.assertEqual(instance["metadata"]["component_count"], components)
                self.assertEqual(len(instance["metadata"]["components"]), components)
                self.assertEqual(sum(instance["metadata"]["component_sizes"]), 5)
                self.assertEqual(instance["metadata"]["bridge_count"], 5 - components)
                self.assertEqual(semantic_violations(instance, instance["gt_selected"]), [])
                self.assertEqual([(item["id"], item["score"]) for item in instance["candidates"]],
                                 [(item["id"], item["score"]) for item in dataset["candidates"]])
                for row in instance["given_rows"]:
                    self.assertEqual(len({by_id[identifier]["owner"] for identifier in row["terms"]}), 1)
                self.assertEqual(instance["case_hosts"], {case: plan["case_hosts"][case] // (8 // sources)
                                                          for case in dataset["cases"]})
            current_rows = {row["id"] for row in instance["given_rows"]}
            if previous_rows is not None:
                self.assertEqual(len(current_rows - previous_rows), 1)
            previous_rows = current_rows
        for sources in (1, 2, 4):
            self.assertEqual(expected_owners[sources], {key: owner // (8 // sources)
                                                       for key, owner in expected_owners[8].items()})
        self.assertEqual(dataset, original)

    def test_general_divisors_and_invalid_parameters(self):
        dataset = toy_dataset(2, 1)
        plan = generate_plan(dataset, 2, max_sources=6)
        for count in (1, 2, 3, 6):
            self.assertEqual(build_instance(dataset, plan, count, 1)["sources"], list(range(count)))
        for sources, components in ((4, 1), (0, 1), (1, 0), (1, 3), (True, 1)):
            with self.subTest(sources=sources, components=components):
                with self.assertRaises(ValueError):
                    build_instance(dataset, plan, sources, components)

    def test_validation_rejects_bad_witness_scope_placement_and_dataset(self):
        dataset = toy_dataset()
        plan = generate_plan(dataset, 1)
        wrong_witness = deepcopy(plan)
        wrong_witness["bridges"][0]["witness"]["selected_candidate_id"] = dataset["gt_selected"][0]
        with self.assertRaisesRegex(ValueError, "Witness"):
            validate_plan(dataset, wrong_witness)
        wrong_scope = deepcopy(plan)
        extra = next(candidate["id"] for candidate in dataset["candidates"]
                     if candidate["id"] not in wrong_scope["bridges"][0]["terms"])
        wrong_scope["bridges"][0]["terms"][extra] = 1
        with self.assertRaisesRegex(ValueError, "scope"):
            validate_plan(dataset, wrong_scope)
        wrong_placement = deepcopy(plan)
        wrong_placement["ownership_blocks"][0]["owner"] = 99
        with self.assertRaisesRegex(ValueError, "placement"):
            validate_plan(dataset, wrong_placement)
        altered = deepcopy(dataset)
        altered["candidates"][0]["score"] = "0.1001"
        with self.assertRaisesRegex(ValueError, "different dataset"):
            build_instance(altered, plan, 1, 1)


class PreparedPopulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(__file__).resolve().parents[1] / "inputs" / "reference" / "full"
        cls.dataset = load_dataset(cls.folder)
        cls.plan = generate_plan(cls.dataset, 20260919)

    def test_fixed_population_and_independent_safe_swap_counts(self):
        dataset, plan = self.dataset, self.plan
        self.assertEqual(len(dataset["cases"]), 116)
        self.assertNotIn("38", dataset["cases"])
        self.assertEqual(len(dataset["candidates"]), 5568)
        self.assertEqual(len(dataset["given_rows"]), 1856)
        self.assertEqual((len(dataset["prerequisites"]), len(dataset["occurrence_bounds"])), (41, 32))
        self.assertTrue(all(type(bound["lower"]) is int and bound["lower"] == 0 for bound in dataset["occurrence_bounds"]))
        self.assertEqual(plan["safe_replacement_audit"]["safe_alternatives"], 3178)
        self.assertEqual(plan["safe_replacement_audit"]["eligible_observations"], 1723)
        self.assertEqual(plan["safe_replacement_audit"]["minimum_eligible_observations_per_case"], 7)
        self.assertEqual(plan["metadata"]["levels"], 7)
        self.assertEqual(len(plan["bridges"]), 115)
        self.assertEqual(len(plan["ownership_blocks"]), 1741)
        self.assertEqual(plan["metadata"]["singleton_blocks"], 1626)
        self.assertEqual(plan["validation"]["checked_witnesses"], 115)

    def test_all_116_prefixes_and_full_plan_witnesses(self):
        expected_owners = None
        for component_count in range(1, 117):
            instance = build_instance(self.dataset, self.plan, 8, component_count)
            owners = [candidate["owner"] for candidate in instance["candidates"]]
            if expected_owners is None:
                expected_owners = owners
            self.assertEqual(owners, expected_owners)
            self.assertEqual(len(instance["metadata"]["components"]), component_count)
            self.assertEqual(instance["metadata"]["bridge_count"], 116 - component_count)
            self.assertEqual(sum(component["edge_count"] for component in instance["metadata"]["components"]),
                             116 - component_count)
        full = build_instance(self.dataset, self.plan, 8, 1)
        gt = set(full["gt_selected"])
        for bridge in self.plan["bridges"]:
            witness = bridge["witness"]
            changed = gt - {witness["removed_candidate_id"]} | {witness["selected_candidate_id"]}
            failures = semantic_violations(full, changed)
            self.assertEqual([failure.get("row_id") for failure in failures], [bridge["id"]])

    def test_every_score_is_the_original_json_decimal_token(self):
        original = {}
        with gzip.open(self.folder / "uncertain_log.csv.gz", "rt", encoding="utf-8", newline="") as stream:
            for event in csv.DictReader(stream):
                scores = json.loads(event["scores"], parse_float=str, parse_int=str)
                original.update({(event["event_id"], activity): score for activity, score in scores.items()})
        for candidate in self.dataset["candidates"]:
            self.assertEqual(candidate["score"], original[(candidate["observation_id"], candidate["activity"])])
        exact_gt = sum((Fraction(candidate["score"]) for candidate in self.dataset["candidates"]
                        if candidate["id"] in set(self.dataset["gt_selected"])), Fraction())
        self.assertEqual(Fraction(self.dataset["metadata"]["gt_score"]), exact_gt)


if __name__ == "__main__":
    unittest.main()
