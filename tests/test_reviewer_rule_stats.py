"""Independent miniature examples for reviewer-facing mining statistics."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reviewer_rule_stats", ROOT / "reviewer/rule_stats.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def event(case, name, activity, start, end):
    return {"case_id": case, "event_id": name, "activity": activity,
            "start_frame": start, "end_frame_exclusive": end}


class RuleStatisticsTests(unittest.TestCase):
    def test_adjacency_reuse_and_vacuous_case_are_distinct(self):
        result = module.recompute_gt([event("a", "p", "P", 0, 2), event("a", "t1", "T", 2, 3),
                                     event("a", "t2", "T", 4, 5)], ["a", "empty"], ["P", "T", "Absent"])
        pair = next(p for p in result["pairs"] if (p["predecessor"], p["trigger"]) == ("P", "T"))
        self.assertTrue(pair["accepted"])
        self.assertEqual((pair["activated_cases"], pair["activated_events"], pair["vacuous_cases"]), (1, 2, 1))
        self.assertFalse(pair["active_in_all_cases"])
        absent = next(p for p in result["pairs"] if (p["predecessor"], p["trigger"]) == ("P", "Absent"))
        self.assertTrue(absent["satisfied"])
        self.assertFalse(absent["accepted"])
        self.assertFalse(absent["nonvacuous"])
        bound = next(b for b in result["bounds"] if b["activity"] == "T")
        self.assertEqual((bound["minimum"], bound["maximum"]), (0, 2))

    def test_overlapping_or_other_case_predecessor_does_not_support(self):
        result = module.recompute_gt([event("a", "p", "P", 0, 4), event("a", "t", "T", 2, 3),
                                     event("b", "p2", "P", 0, 1), event("c", "t2", "T", 5, 6)],
                                    ["a", "b", "c"], ["P", "T"])
        pair = next(p for p in result["pairs"] if p["predecessor"] == "P")
        self.assertEqual((pair["violation_count"], pair["violated_cases"]), (2, 2))
        self.assertEqual(pair["first_counterexample"]["reason"], "no_predecessor_completed_by_trigger_start")
        self.assertFalse(pair["accepted"])

    def test_candidate_row_includes_all_supporters_and_forbids_unsupported_trigger(self):
        candidates = [{"id": "p1", "activity": "P", "case_id": "a", "start": 0, "end": 1},
                      {"id": "p2", "activity": "P", "case_id": "a", "start": 1, "end": 2},
                      {"id": "t1", "activity": "T", "case_id": "a", "start": 2, "end": 3},
                      {"id": "t2", "activity": "T", "case_id": "b", "start": 2, "end": 3}]
        rows = module.candidate_rows({"id": "p", "kind": "prerequisite", "predecessor_activities": ["P"],
                                      "trigger_activity": "T"}, candidates, ["a", "b"])
        self.assertEqual(rows[0]["terms"], {"t1": 1, "p1": -1, "p2": -1})
        self.assertEqual(rows[1]["terms"], {"t2": 1})
        bounds = module.candidate_rows({"id": "b", "kind": "occurrence_bound", "activities": ["P"],
                                        "lower": 0, "upper": 2}, candidates, ["a", "b"])
        self.assertEqual(len(bounds), 2)
        self.assertEqual(bounds[1]["terms"], {})

    def test_ranking_uses_events_before_ids(self):
        records = [{"id": "a", "support_cases": 4, "support_events": 5},
                   {"id": "b", "support_cases": 4, "support_events": 6},
                   {"id": "c", "support_cases": 5, "support_events": 5}]
        self.assertEqual(module.rank_records(records), {"c": 1, "b": 2, "a": 3})

    def test_full_recount_matches_frozen_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            report = module.generate(ROOT, Path(folder) / "data")
            s = report["summary"]
            self.assertEqual((s["tested_pairs"], s["accepted_prerequisites"], s["rejected_pairs"]), (992, 41, 951))
            self.assertEqual((s["purely_vacuous_pairs"], s["accepted_active_in_all_cases"], s["positive_minima"]), (0, 0, 0))
            self.assertEqual(s["selected_instantiated_rows"], 831)
            self.assertTrue(all(report["checks"].values()))
            self.assertTrue((Path(folder) / "RULES.md").is_file())

    def test_protected_output_rejected(self):
        with self.assertRaisesRegex(ValueError, "frozen evidence"):
            module.generate(ROOT, ROOT / "inputs/reference/full")

    def test_changed_frozen_audit_is_rejected_before_reporting(self):
        original = module.read_json

        def altered(path):
            value = original(path)
            if Path(path).name == "constraint_audit.json":
                value["prerequisites"][0]["violation_count"] += 1
            return value

        with tempfile.TemporaryDirectory() as folder, patch.object(module, "read_json", side_effect=altered):
            with self.assertRaisesRegex(ValueError, "pair tests differ"):
                module.generate(ROOT, Path(folder) / "data")
            self.assertFalse((Path(folder) / "data/rule_stats.json").exists())


if __name__ == "__main__":
    unittest.main()
