"""Independent randomized end-to-end tests against complete enumeration."""

from fractions import Fraction
import json
from pathlib import Path
import random
import unittest

from benchmark import check_matching_result, upload_centrally
from minea_ikea.construction import construct
from minea_ikea.matching import match_central, match_distributed
from minea_ikea.reference import (compare_construction, components_from_rows,
                                encode_centrally, exhaustive_optimum)


def tiny(seed):
    rng = random.Random(seed)
    instance = {"cases": ["j0", "j1"], "sources": [0, 1, 2],
                "case_hosts": {"j0": 0, "j1": 1}, "candidates": [], "given_rows": [],
                "prerequisites": [{"id": "p", "trigger_activity": "B", "predecessor_activities": ["A"]}],
                "occurrence_bounds": [{"id": "a", "activities": ["A"], "lower": rng.choice([0, 0, 1]), "upper": rng.randrange(3)}],
                "metadata": {}}
    # Keep malformed lower>upper out of a test of matching, rather than validation.
    instance["occurrence_bounds"][0]["upper"] = max(instance["occurrence_bounds"][0]["upper"], instance["occurrence_bounds"][0]["lower"])
    for case in instance["cases"]:
        for i in range(2):
            observation, source = f"{case}:{i}", rng.randrange(3)
            ids = []
            for activity in ("A", "B"):
                identifier = f"{observation}:{activity}"
                ids.append(identifier)
                instance["candidates"].append({"id": identifier, "observation_id": observation,
                    "case_id": case, "activity": activity, "start": 2*i, "end": 2*i+1,
                    "owner": source, "score": str(Fraction(rng.randrange(10), 10))})
            instance["given_rows"].append({"id": "assignment:"+observation, "kind": "assignment",
                "case_id": case, "terms": dict.fromkeys(ids, 1), "upper": 1})
    # Add a real source-local inter-case row only when co-location permits it.
    pairs = [(a, b) for a in instance["candidates"] for b in instance["candidates"]
             if a["case_id"] == "j0" and b["case_id"] == "j1" and a["owner"] == b["owner"]]
    if pairs and seed % 2:
        a, b = rng.choice(pairs)
        instance["given_rows"].append({"id": "exclusion", "kind": "exclusion", "case_id": None,
                                       "terms": {a["id"]: 1, b["id"]: 1}, "upper": 1})
    return instance


class IndependentIntegrationTests(unittest.TestCase):
    def test_24_seeded_models_agree_with_all_81_assignments(self):
        for seed in range(24):
            with self.subTest(seed=seed):
                instance = tiny(seed)
                construction = construct(instance, trace=True)
                compare_construction(instance, construction)
                rows = encode_centrally(instance)
                exhaustive = exhaustive_optimum(instance, rows)
                central = match_central(instance, rows=rows, components=components_from_rows(instance, rows), time_limit=10)
                distributed = match_distributed(instance, construction, time_limit=10, node_limit=2000)
                for result in (central, distributed):
                    self.assertEqual(result["status"], exhaustive["status"])
                    self.assertEqual(result["objective"], exhaustive["objective"])
                    check_matching_result(instance, rows, result)
                m = distributed["metrics"]
                self.assertEqual(m["optimization_requests"], m["optimization_replies"])
                self.assertEqual(m["source_calls"], m["optimization_requests"])
                self.assertEqual(m["retention_requests"], m["retention_confirmations"])

    def test_paper_example_has_five_visits_and_exact_optimum_six(self):
        path = Path(__file__).resolve().parents[1] / "examples/paper_example.json"
        instance = json.loads(path.read_text())
        construction = construct(instance, trace=True)
        compare_construction(instance, construction)
        result = match_distributed(instance, construction, trace=True, time_limit=10)
        self.assertEqual(result["objective"], "6")
        self.assertEqual(result["metrics"]["visited_nodes"], 5)
        self.assertEqual(result["metrics"]["queried_nodes"], 4)
        self.assertEqual(result["metrics"]["source_calls"], 8)

    def test_central_upload_reconstructs_rows_and_contains_no_gt(self):
        instance = tiny(3)
        instance["gt_selected"] = ["private-audit-only"]
        uploaded, counts = upload_centrally(instance)
        self.assertNotIn("gt_selected", uploaded)
        self.assertEqual(encode_centrally(uploaded), encode_centrally(instance))
        self.assertEqual(counts["candidate_records"], 8)
        self.assertEqual(counts["upload_messages"], 3)

    def test_zero_node_budget_is_not_reported_as_infeasible_or_optimal(self):
        instance = tiny(0)
        result = match_distributed(instance, construct(instance), node_limit=0, time_limit=10)
        self.assertEqual(result["status"], "limited")
        self.assertIsNone(result["selected_ids"])
        self.assertEqual(result["metrics"]["source_calls"], 0)


if __name__ == "__main__":
    unittest.main()
