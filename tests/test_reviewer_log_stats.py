"""Small, hand-counted tests of the descriptive report, independent of IKEA totals."""

import csv
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from reviewer.log_stats import distribution, generate


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def fixture(root):
    """Two A,A,B traces; one GT insertion, a score tie, and one excluded case."""
    reference = root / "inputs/reference"
    full = reference / "full"
    write_csv(full / "cases.csv", [
        {"case_id": "a", "case_name": "case_a", "process_group": "G1", "total_frames": 10, "removed_na_segments": 3},
        {"case_id": "b", "case_name": "case_b", "process_group": "G2", "total_frames": 8, "removed_na_segments": 1},
    ])
    truth, uncertain = [], []
    segments = [
        ("a1", "a", 1, 3, "A", '{"A":0.4,"B":0.3,"C":0.1}', "A", "0.1", "0.1", "0.8"),
        ("a2", "a", 3, 4, "A", '{"B":0.4,"C":0.3,"A":0.0100}', "B", "0.1", "0.19", "0.71"),
        ("a3", "a", 5, 9, "B", '{"A":0.4,"B":0.3,"C":0.2}', "A", "0.05", "0.05", "0.9"),
        ("b1", "b", 0, 2, "A", '{"A":0.4,"B":0.3,"C":0.1}', "A", "0.1", "0.1", "0.8"),
        ("b2", "b", 2, 3, "A", '{"A":0.4,"B":0.3,"C":0.1}', "A", "0.1", "0.1", "0.8"),
        # JSON key order deliberately disagrees with the lexical tie-break.
        ("b3", "b", 3, 7, "B", '{"B":0.3,"A":0.3,"C":0.2}', "A", "0.1", "0.1", "0.8"),
    ]
    for event, case, start, end, activity, scores, top, na, discarded, retained in segments:
        common = {"event_id": event, "case_id": case, "case_name": "case_" + case,
                  "start_frame": start, "end_frame_exclusive": end, "duration_frames": end - start}
        truth.append({**common, "activity": activity})
        uncertain.append({**common, "top_activity": top, "scores": scores,
                          "removed_na_score": na, "discarded_non_na_score_mass": discarded,
                          "remaining_score_mass": retained})
    write_csv(full / "ground_truth.csv", truth)
    write_csv(full / "uncertain_log.csv", uncertain)
    write_csv(reference / "candidate_replacements.csv", [{
        "event_id": "a2", "case_id": "a", "replaced_activity": "D", "replaced_score": "0.20",
        "inserted_gt_activity": "A", "inserted_original_score": "0.0100", "gt_original_non_na_rank": 4,
    }])
    write_json(full / "candidate_policy.json", {
        "top_k": 3, "renormalized": False, "gt_label_insertion": True, "activity_vocabulary": ["A", "B", "C", "D"],
    })
    write_json(reference / "protocol.json", {"frames_per_second": 25})
    write_json(reference / "source_audit.json", {
        "original_case_ids": ["a", "b", "empty"], "explicitly_excluded_empty_cases": ["empty"],
    })
    write_json(reference / "model_selection.json", {
        "selected_model": "fixture_model", "selection_metric": "non_na", "model_override": None,
        "tie_breaking": "Lexicographic model ID after equal non-NA frame accuracy.",
        "models": [{"model_id": "fixture_model", "frames": 23, "correct_frames": 14,
                    "non_na_frames": 14, "correct_non_na_frames": 12, "non_na_segments": 6,
                    "correct_non_na_segments_original": 3, "correct_non_na_segments_after_na_removal": 3,
                    "per_case": [
                        {"case_id": "a", "frames": 10, "correct_frames": 6, "non_na_frames": 7, "correct_non_na_frames": 6},
                        {"case_id": "b", "frames": 8, "correct_frames": 6, "non_na_frames": 7, "correct_non_na_frames": 6},
                        {"case_id": "empty", "frames": 5, "correct_frames": 2, "non_na_frames": 0, "correct_non_na_frames": 0},
                    ]}],
    })


class DistributionTests(unittest.TestCase):
    def test_type_seven_quartiles_and_population_sd(self):
        result = distribution([4, 1, 3, 2])
        self.assertEqual({key: result[key] for key in ("minimum", "q1", "median", "q3", "maximum", "mean")},
                         {"minimum": 1, "q1": 1.75, "median": 2.5, "q3": 3.25, "maximum": 4, "mean": 2.5})
        self.assertAlmostEqual(result["population_sd"], math.sqrt(1.25))
        self.assertEqual(distribution([0, 10])["q1"], 2.5)
        self.assertEqual(distribution([0, 10])["q3"], 7.5)

    def test_empty_singleton_and_exact_decimal_input(self):
        empty = distribution([])
        self.assertEqual(empty["count"], 0)
        self.assertTrue(all(value is None for key, value in empty.items() if key != "count"))
        self.assertEqual(distribution(["0.1"])["population_sd"], 0)
        self.assertEqual(distribution([Fraction("0.1"), Fraction("0.3")])["mean"], 0.2)


class LogStatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "report"
        fixture(self.root)

    def generate(self):
        return generate(self.root, self.output)

    def mutate_csv(self, relative, mutate):
        path = self.root / relative
        rows = read_csv(path)
        mutate(rows)
        write_csv(path, rows)

    def test_raw_retained_and_na_population_scopes(self):
        result = self.generate()
        population = result["population"]
        for key, expected in {
            "raw_case_count_recorded": 3, "retained_case_count": 2,
            "retained_nonempty_case_count": 2, "retained_empty_case_count": 0,
            "retained_observation_count": 6, "retained_candidate_count": 18,
            "raw_case_frames_recorded": 23, "retained_case_recording_frames": 18,
            "retained_non_na_event_frames": 14, "retained_case_uncovered_na_frames": 4,
            "excluded_case_frames_recorded": 5, "removed_na_segments_in_retained_cases": 4,
            "original_segments_in_retained_cases": 10,
        }.items():
            self.assertEqual(population[key], expected, key)
        self.assertIsNone(population["removed_na_segments_in_all_raw_cases"])
        self.assertEqual(population["excluded_case_ids"], ["empty"])

    def test_exact_variants_self_transitions_and_case_durations(self):
        result = self.generate()
        gt = result["ground_truth"]
        self.assertEqual(gt["exact_variant_count"], 1)
        self.assertEqual(gt["singleton_variant_count"], 0)
        self.assertEqual(gt["start_activity_counts"], {"A": 2})
        self.assertEqual(gt["end_activity_counts"], {"B": 2})
        self.assertEqual(gt["direct_follow_occurrences"], 4)
        self.assertEqual(gt["same_activity_direct_follow_occurrences"], 2)
        self.assertEqual(gt["cases_with_repetition"], 2)
        variants = read_csv(self.output / "variants.csv")
        self.assertEqual(json.loads(variants[0]["activity_sequence"]), ["A", "A", "B"])
        self.assertEqual(variants[0]["case_count"], "2")
        pairs = {(row["source_activity"], row["target_activity"]): int(row["occurrences"])
                 for row in read_csv(self.output / "transitions.csv")}
        self.assertEqual(pairs, {("A", "A"): 2, ("A", "B"): 2})
        cases = {row["case_id"]: row for row in read_csv(self.output / "cases.csv")}
        self.assertEqual(cases["a"]["repeat_events_after_first_occurrence"], "1")
        self.assertEqual(cases["a"]["retained_span_frames"], "8")
        self.assertEqual(cases["a"]["retained_event_frames"], "7")
        self.assertEqual(cases["a"]["recording_frames"], "10")

    def test_original_scores_reconstructed_top3_and_ties(self):
        result = self.generate()
        uncertain = result["uncertain"]
        self.assertEqual(uncertain["gt_insertion_count"], 1)
        self.assertEqual(uncertain["pre_insertion_top3_gt_coverage"]["fraction"], "5/6")
        self.assertEqual(uncertain["post_insertion_gt_coverage"]["fraction"], "1")
        self.assertEqual(uncertain["gt_insertions_by_group"], {"G1": 1, "G2": 0})
        self.assertEqual(uncertain["gt_original_non_na_rank_frequency"], {"1": 3, "2": 2, "4": 1})
        self.assertEqual(uncertain["gt_retained_rank_frequency"], {"1": 3, "2": 2, "3": 1})
        self.assertEqual(uncertain["candidate_vocabulary"], ["A", "B", "C"])
        self.assertEqual(uncertain["pre_insertion_candidate_vocabulary"], ["A", "B", "C", "D"])
        rows = {row["event_id"]: row for row in read_csv(self.output / "observations.csv")}
        self.assertEqual(rows["a2"]["gt_score_original"], "0.0100")
        self.assertEqual(rows["a2"]["original_scores_json"], '{"B":0.4,"C":0.3,"A":0.0100}')
        self.assertEqual(rows["a2"]["pre_insertion_top3_original_scores_json"], '{"B":0.4,"C":0.3,"D":0.20}')
        self.assertEqual(rows["a2"]["replaced_score_original"], "0.20")
        self.assertEqual(rows["b3"]["top_activity"], "A")
        self.assertEqual(rows["b3"]["top1_minus_top2_margin_exact"], "0")
        activities = {row["activity"]: row for row in read_csv(self.output / "activities.csv")}
        self.assertEqual(activities["D"]["retained_candidate_occurrences"], "0")
        self.assertEqual(activities["D"]["pre_insertion_candidate_occurrences"], "1")
        self.assertEqual(sum(int(row["pre_insertion_candidate_occurrences"]) for row in activities.values()), 18)

    def test_segment_duration_weighted_and_raw_frame_agreement_are_distinct(self):
        result = self.generate()
        self.assertEqual(result["uncertain"]["top1_segment_agreement"]["fraction"], "1/2")
        self.assertEqual(result["uncertain"]["duration_weighted_segment_agreement"]["fraction"], "5/14")
        self.assertEqual(result["model_selection"]["recorded_selected_raw_non_na_frame_accuracy"]["fraction"], "6/7")
        self.assertEqual(result["uncertain"]["pre_insertion_duration_weighted_gt_coverage"]["fraction"], "13/14")

    def test_generation_is_deterministic_and_input_files_are_unchanged(self):
        def hashes(folder):
            return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in folder.rglob("*") if path.is_file()}
        before = hashes(self.root / "inputs")
        first = self.generate()
        first_files = hashes(self.output)
        self.assertEqual(first, json.loads((self.output / "log_stats.json").read_text()))
        self.assertEqual(first, self.generate())
        self.assertEqual(first_files, hashes(self.output))
        self.assertEqual(before, hashes(self.root / "inputs"))
        self.assertEqual(set(first["tables"]), {"cases.csv", "activities.csv", "groups.csv", "variants.csv",
                                              "transitions.csv", "observations.csv", "model_comparison.csv", "score_distributions.csv"})
        for name, table in first["tables"].items():
            self.assertEqual(len(read_csv(self.output / name)), table["rows"])
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest(), table["sha256"])

    def test_alignment_and_duplicate_ids_are_rejected(self):
        self.mutate_csv("inputs/reference/full/uncertain_log.csv", lambda rows: rows[0].update(start_frame="0"))
        with self.assertRaisesRegex(ValueError, "alignment differs"):
            self.generate()
        fixture(self.root)
        self.mutate_csv("inputs/reference/full/ground_truth.csv", lambda rows: rows.append(rows[0].copy()))
        with self.assertRaisesRegex(ValueError, "Duplicate GT event ID"):
            self.generate()

    def test_overlapping_intervals_are_rejected_even_when_logs_align(self):
        for name in ("ground_truth.csv", "uncertain_log.csv"):
            self.mutate_csv("inputs/reference/full/" + name,
                            lambda rows: rows[1].update(start_frame="2", duration_frames="2"))
        with self.assertRaisesRegex(ValueError, "Overlapping GT intervals"):
            self.generate()

    def test_mass_errors_and_recorded_subtotal_errors_are_rejected(self):
        self.mutate_csv("inputs/reference/full/uncertain_log.csv",
                        lambda rows: rows[0].update(discarded_non_na_score_mass="0.4"))
        with self.assertRaisesRegex(ValueError, "Score mass differs"):
            self.generate()
        fixture(self.root)
        path = self.root / "inputs/reference/model_selection.json"
        data = json.loads(path.read_text())
        data["models"][0]["correct_non_na_frames"] = 11
        write_json(path, data)
        with self.assertRaisesRegex(ValueError, "Recorded model subtotal differs"):
            self.generate()

    def test_independent_occurrence_export_is_checked(self):
        path = self.root / "inputs/reference/full/occurrence_counts_by_case.csv"
        rows = [{"case_id": case, "A": 2, "B": 1, "C": 0, "D": 0} for case in ("a", "b")]
        write_csv(path, rows)
        result = self.generate()
        self.assertEqual(result["quality"]["cross_checks"][path.name], {"status": "PASS", "cases": 2})
        rows[0]["A"] = 1
        write_csv(path, rows)
        with self.assertRaisesRegex(ValueError, "Occurrence counts disagree"):
            self.generate()


if __name__ == "__main__":
    unittest.main()
