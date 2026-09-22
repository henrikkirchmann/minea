"""Small independently understood reference logs for mining semantics."""

import json
import unittest

from minea_ikea.mining import mine_constraints, select_variant_cases


def event(case_id, number, activity, start, end):
    return {
        "event_id": f"e{number}", "case_id": case_id, "activity": activity,
        "start_frame": start, "end_frame_exclusive": end,
    }


def rule(result, predecessor, trigger):
    return next(item for item in result["prerequisites"] if item["predecessor"] == predecessor and item["trigger"] == trigger)


def bound(result, activity):
    return next(item for item in result["occurrence_bounds"] if item["activity"] == activity)


class MiningTests(unittest.TestCase):
    def test_existential_not_immediate_and_repeated_triggers(self):
        events = [event("c", 1, "A", 0, 1), event("c", 2, "C", 1, 2), event("c", 3, "B", 2, 3), event("c", 4, "B", 4, 5)]
        result = mine_constraints(events, ["c"])
        self.assertTrue(rule(result, "A", "B")["accepted"])
        self.assertEqual(rule(result, "A", "B")["activated_events"], 2)
        self.assertFalse(rule(result, "B", "A")["accepted"])

    def test_each_trigger_requires_support_even_if_later_triggers_have_it(self):
        events = [event("c", 1, "B", 0, 1), event("c", 2, "A", 1, 2), event("c", 3, "B", 2, 3)]
        record = rule(mine_constraints(events, ["c"]), "A", "B")
        self.assertEqual(record["violation_count"], 1)
        self.assertEqual(record["satisfied_events"], 1)
        self.assertEqual(record["first_counterexample"]["trigger_event_id"], "e1")

    def test_exact_boundary_is_eligible_but_overlap_is_not(self):
        touching = [event("c", 1, "A", 0, 2), event("c", 2, "B", 2, 3)]
        overlapping = [event("c", 1, "A", 0, 3), event("c", 2, "B", 2, 4)]
        self.assertTrue(rule(mine_constraints(touching, ["c"]), "A", "B")["accepted"])
        self.assertFalse(rule(mine_constraints(overlapping, ["c"]), "A", "B")["accepted"])

    def test_same_interval_and_same_observation_cannot_supply_support(self):
        events = [event("c", 1, "A", 0, 2), event("c", 2, "B", 0, 2)]
        self.assertFalse(rule(mine_constraints(events, ["c"]), "A", "B")["accepted"])
        events[1]["event_id"] = events[0]["event_id"]
        with self.assertRaisesRegex(ValueError, "Duplicate event_id"):
            mine_constraints(events, ["c"])

    def test_predecessor_in_another_case_does_not_support_trigger(self):
        result = mine_constraints([event("a", 1, "A", 0, 1), event("b", 1, "B", 2, 3)], ["a", "b"])
        record = rule(result, "A", "B")
        self.assertEqual(record["violation_count"], 1)
        self.assertEqual(record["first_counterexample"]["reason"], "predecessor_absent")

    def test_absent_and_empty_cases_contribute_zero_to_minimum(self):
        events = [event("a", 1, "A", 0, 1), event("a", 2, "A", 2, 3), event("b", 1, "B", 0, 1)]
        result = mine_constraints(events, ["a", "b", "empty"], ["A", "B", "never"])
        record = bound(result, "A")
        self.assertEqual((record["minimum"], record["maximum"]), (0, 2))
        self.assertEqual(record["per_case_counts"], {"a": 2, "b": 0, "empty": 0})
        self.assertEqual(record["minimum_witness_case_ids"], ["b", "empty"])
        self.assertFalse(record["positive_minimum"])
        self.assertEqual(bound(result, "never")["maximum"], 0)

    def test_vacuity_is_reported_and_never_accepted_without_any_trigger(self):
        events = [event("a", 1, "A", 0, 1), event("a", 2, "B", 1, 2)]
        result = mine_constraints(events, ["a", "empty"], ["A", "B", "never"])
        record = rule(result, "A", "B")
        self.assertTrue(record["accepted"])
        self.assertFalse(record["active_in_all_cases"])
        self.assertEqual((record["activated_cases"], record["vacuous_cases"]), (1, 1))
        vacuous = rule(result, "A", "never")
        self.assertTrue(vacuous["satisfied"])
        self.assertFalse(vacuous["accepted"])

    def test_cycles_are_rejected_when_first_occurrence_lacks_support(self):
        events = [event("c", 1, "A", 0, 1), event("c", 2, "B", 1, 2), event("c", 3, "A", 2, 3)]
        result = mine_constraints(events, ["c"])
        self.assertTrue(rule(result, "A", "B")["accepted"])
        self.assertFalse(rule(result, "B", "A")["accepted"])
        self.assertFalse(any(item["predecessor"] == item["trigger"] for item in result["prerequisites"]))

    def test_informative_maximum_compared_with_event_positions(self):
        events = [event("c", 1, "A", 0, 1), event("c", 2, "B", 1, 2)]
        self.assertTrue(bound(mine_constraints(events, ["c"]), "A")["informative_maximum"])
        only_a = [event("c", 1, "A", 0, 1), event("c", 2, "A", 1, 2)]
        self.assertFalse(bound(mine_constraints(only_a, ["c"]), "A")["informative_maximum"])

    def test_reject_unknown_case_and_invalid_intervals(self):
        with self.assertRaisesRegex(ValueError, "absent from case_ids"):
            mine_constraints([event("unknown", 1, "A", 0, 1)], ["c"])
        with self.assertRaisesRegex(ValueError, "nonempty"):
            mine_constraints([event("c", 1, "A", 1, 1)], ["c"])

    def test_serializable_and_input_order_independent(self):
        events = [event("b", 2, "B", 2, 3), event("b", 1, "A", 0, 1), event("a", 1, "A", 0, 1)]
        left = mine_constraints(events, ["b", "a"])
        right = mine_constraints(list(reversed(events)), ["a", "b"])
        self.assertEqual(left, right)
        self.assertEqual(json.loads(json.dumps(left)), left)


class VariantTests(unittest.TestCase):
    def test_cutoff_ties_are_all_included_and_case_ids_can_align_both_logs(self):
        # Frequencies 3, 2, 2, 1: a 50% request needs the second group and
        # includes its tie too, giving seven cases rather than four or five.
        labels = {"a1": "A", "a2": "A", "a3": "A", "b1": "B", "b2": "B", "c1": "C", "c2": "C", "d1": "D"}
        events = [event(case_id, 1, activity, 0, 1) for case_id, activity in labels.items()]
        selection = select_variant_cases(events, list(labels), coverage=0.5)
        self.assertEqual(selection["selected_case_ids"], ["a1", "a2", "a3", "b1", "b2", "c1", "c2"])
        self.assertEqual(selection["metadata"]["actual_coverage"], 7 / 8)
        kept = set(selection["selected_case_ids"])
        certain_ids = {item["case_id"] for item in events if item["case_id"] in kept}
        uncertain_ids = {item["case_id"] for item in reversed(events) if item["case_id"] in kept}
        self.assertEqual(certain_ids, uncertain_ids)

    def test_all_unique_variants_keep_every_case_even_at_eighty_percent(self):
        events = [event(f"c{i}", 1, str(i), 0, 1) for i in range(10)]
        result = select_variant_cases(events, [f"c{i}" for i in range(10)], 0.8)
        self.assertEqual(result["metadata"]["actual_coverage"], 1.0)

    def test_empty_variant_and_no_coalescing_after_na_removal(self):
        events = [event("double", 1, "A", 0, 1), event("double", 2, "A", 3, 4), event("single", 1, "A", 0, 1)]
        result = select_variant_cases(events, ["double", "empty", "single"])
        self.assertEqual([item["activities"] for item in result["variants"]], [[], ["A"], ["A", "A"]])
        self.assertEqual(result["selected_case_ids"], ["double", "empty", "single"])

    def test_non_tied_threshold_selects_whole_variants(self):
        events = [event(f"a{i}", 1, "A", 0, 1) for i in range(4)] + [event("b", 1, "B", 0, 1)]
        result = select_variant_cases(events, [item["case_id"] for item in events], 0.8)
        self.assertEqual(result["selected_case_ids"], ["a0", "a1", "a2", "a3"])

    def test_invalid_coverage(self):
        for coverage in (0, -0.1, 1.1, float("nan"), float("inf"), True):
            with self.subTest(coverage=coverage):
                with self.assertRaises(ValueError):
                    select_variant_cases([], ["empty"], coverage)


if __name__ == "__main__":
    unittest.main()
