"""Independent examples for the scientific data transformations (standard library only)."""

from copy import deepcopy
import csv
import hashlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from minea_ikea.data import (
    choose_model,
    ensure_inputs,
    frame_accuracy,
    prepare_logs,
    read_segments,
    score_conservation_error,
    verify_reference_xes,
)


def runs(labels, case_id="0", case_name="Furniture/example"):
    """Encode a known frame sequence; the accuracy oracle remains the frame sequence."""
    rows = []
    for frame, label in enumerate(labels):
        if rows and rows[-1]["activity"] == label:
            rows[-1]["end_frame_exclusive"] = frame + 1
            rows[-1]["duration_frames"] += 1
        else:
            rows.append({"case_id": case_id, "case_name": case_name,
                         "start_frame": frame, "end_frame_exclusive": frame + 1,
                         "duration_frames": 1, "activity": label})
    return rows


class DataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write_csv(self, rows, name="segments.csv"):
        path = self.root / name
        fields = list(dict.fromkeys(key for row in rows for key in row))
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return path

    @staticmethod
    def csv_row(start=0, last=0, label="A", scores=None, **changes):
        row = {"case_id": "0", "case_name": "Furniture/example",
               "start_timestamp": start, "end_timestamp": last,
               "duration_frames": last - start + 1, "gt_label_name": label,
               "avg_probs_json": json.dumps(scores or {"NA": 0.1, "A": 0.6, "B": 0.3})}
        row.update(changes)
        return row

    def test_interval_sweep_matches_all_tiny_frame_sequences(self):
        # Exhaustively vary segment boundaries, equality, NA frames, and one-frame runs.
        for length in range(1, 4):
            sequences = list(itertools.product(("NA", "A", "B"), repeat=length))
            for gt in sequences:
                if set(gt) == {"NA"}:
                    continue
                for pred in sequences:
                    with self.subTest(gt=gt, pred=pred):
                        result = frame_accuracy(runs(gt), runs(pred))
                        expected = {
                            "frames": length,
                            "correct_frames": sum(a == b for a, b in zip(gt, pred)),
                            "non_na_frames": sum(a != "NA" for a in gt),
                            "correct_non_na_frames": sum(a == b and a != "NA" for a, b in zip(gt, pred)),
                        }
                        self.assertEqual({key: result[key] for key in expected}, expected)

    def test_per_case_counts_use_independent_video_clocks(self):
        gt = runs(["A", "NA"]) + runs(["B", "B", "A"], "1", "Other/example")
        pred = runs(["A", "A"]) + runs(["B", "A", "A"], "1", "Other/example")
        result = frame_accuracy(gt, pred)
        self.assertEqual(result["frames"], 5)
        self.assertEqual(result["correct_frames"], 3)
        self.assertEqual(result["non_na_frames"], 4)
        self.assertEqual(result["correct_non_na_frames"], 3)
        self.assertEqual([row["frames"] for row in result["per_case"]], [2, 3])

    def test_inclusive_frame_end_becomes_exclusive_without_losing_last_frame(self):
        path = self.write_csv([self.csv_row(), self.csv_row(1, 3, "B")])
        rows = read_segments(path)
        self.assertEqual([(r["start_frame"], r["end_frame_exclusive"], r["duration_frames"])
                          for r in rows], [(0, 1, 1), (1, 4, 3)])

    def test_segment_mean_argmax_is_not_frame_accuracy(self):
        # A scores [0.6, 0.6, 0.0], B scores [0.4, 0.4, 1.0]: two correct
        # frame decisions, but the mean selects B for the one ground-truth A event.
        path = self.write_csv([self.csv_row(0, 2, "A", {"NA": 0.0, "A": 0.4, "B": 0.6},
                                           pred_label_name="B")])
        gt = read_segments(path)
        pred = runs(["A", "A", "B"])
        result = frame_accuracy(gt, pred)
        self.assertEqual(result["correct_frames"], 2)
        self.assertAlmostEqual(result["accuracy_non_na_frames"], 2 / 3)
        events, uncertain, _ = prepare_logs(gt)
        self.assertEqual(events[0]["activity"], "A")
        self.assertEqual(uncertain[0]["top_activity"], "B")

    def test_score_conservation_uses_frame_duration_weights(self):
        gt = runs(["A", "A", "A"])
        gt[0]["scores"] = {"NA": 0.0, "A": 0.4, "B": 0.6}
        pred = runs(["A", "A", "B"])
        pred[0]["scores"] = {"NA": 0.0, "A": 0.6, "B": 0.4}
        pred[1]["scores"] = {"NA": 0.0, "A": 0.0, "B": 1.0}
        self.assertLess(score_conservation_error(gt, pred), 1e-14)
        # An unweighted mean of the two prediction segments would be A=0.3.
        changed = deepcopy(gt)
        changed[0]["scores"] = {"NA": 0.0, "A": 0.3, "B": 0.7}
        with self.assertRaisesRegex(ValueError, "conservation"):
            score_conservation_error(changed, pred)

    def test_na_removal_preserves_scores_intervals_and_empty_case(self):
        gt = runs(["A", "NA", "A"]) + runs(["NA", "NA"], "1", "Other/empty")
        for row in gt:
            row["scores"] = {"NA": 0.7, "A": 0.2, "B": 0.1}
        original = deepcopy(gt)
        events, uncertain, cases = prepare_logs(gt)
        self.assertEqual(gt, original, "Preparation must not alter upstream rows")
        self.assertEqual(len(events), 2, "Removing NA must not merge the two A segments")
        self.assertEqual([(r["start_frame"], r["end_frame_exclusive"]) for r in events],
                         [(0, 1), (2, 3)])
        self.assertEqual([r["event_id"] for r in events], [r["event_id"] for r in uncertain])
        for row in uncertain:
            self.assertEqual(row["scores"], {"A": 0.2, "B": 0.1})
            self.assertEqual(row["removed_na_score"], 0.7)
            self.assertAlmostEqual(row["remaining_score_mass"], 0.3)
        self.assertEqual({r["case_id"] for r in cases}, {"0", "1"})
        self.assertEqual(cases[1]["total_frames"], 2)
        self.assertFalse(any(r["case_id"] == "1" for r in events))

    def test_top_three_excludes_na_without_renormalizing_or_inserting_gt(self):
        gt = runs(["A"])
        gt[0]["scores"] = {"NA": 0.4, "A": 0.01, "B": 0.2, "C": 0.15, "D": 0.14, "E": 0.1}
        events, uncertain, _ = prepare_logs(gt, candidate_policy="top-k")
        self.assertEqual(events[0]["activity"], "A")
        self.assertEqual(uncertain[0]["scores"], {"B": 0.2, "C": 0.15, "D": 0.14})
        self.assertNotIn("A", uncertain[0]["scores"], "GT must not be forced into the candidates")
        self.assertAlmostEqual(uncertain[0]["remaining_score_mass"], 0.49)
        self.assertAlmostEqual(uncertain[0]["discarded_non_na_score_mass"], 0.11)
        self.assertEqual(uncertain[0]["removed_na_score"], 0.4)

    def test_oracle_replaces_only_third_candidate_with_original_gt_score(self):
        gt = runs(["A"])
        gt[0]["scores"] = {"NA": 0.4, "A": 0.01, "B": 0.2, "C": 0.15, "D": 0.14, "E": 0.1}
        original = deepcopy(gt)
        _, uncertain, _ = prepare_logs(gt)
        self.assertEqual(uncertain[0]["scores"], {"B": 0.2, "C": 0.15, "A": 0.01})
        self.assertEqual(uncertain[0]["top_activity"], "B")
        self.assertAlmostEqual(uncertain[0]["remaining_score_mass"], 0.36)
        self.assertAlmostEqual(uncertain[0]["discarded_non_na_score_mass"], 0.24)
        self.assertEqual(uncertain[0]["removed_na_score"], 0.4)
        self.assertEqual(gt, original)

    def test_oracle_leaves_top_three_unchanged_if_gt_is_already_present(self):
        for activity in ("A", "B", "C"):
            gt = runs([activity])
            gt[0]["scores"] = {"NA": 0.4, "A": 0.3, "B": 0.2, "C": 0.09, "D": 0.01}
            with self.subTest(activity=activity):
                self.assertEqual(prepare_logs(gt), prepare_logs(gt, candidate_policy="top-k"))

    def test_oracle_retains_zero_gt_score_and_uses_deterministic_cutoff_tie(self):
        gt = runs(["Z"])
        gt[0]["scores"] = {"NA": 0.4, "D": 0.2, "C": 0.2, "B": 0.2, "Z": 0.0}
        _, uncertain, _ = prepare_logs(gt)
        self.assertEqual(list(uncertain[0]["scores"]), ["B", "C", "Z"])
        self.assertEqual(uncertain[0]["scores"]["Z"], 0.0)

    def test_unknown_candidate_policy_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "candidate_policy"):
            prepare_logs([], candidate_policy="unknown")

    def test_top_three_cutoff_ties_use_label_names_not_input_order(self):
        gt = runs(["A"])
        gt[0]["scores"] = {"NA": 0.2, "D": 0.2, "C": 0.2, "B": 0.2, "A": 0.2}
        _, uncertain, _ = prepare_logs(gt)
        self.assertEqual(list(uncertain[0]["scores"]), ["A", "B", "C"])
        for invalid in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                prepare_logs(gt, invalid)

    def test_reference_xes_can_omit_na_only_case_but_cannot_duplicate_events(self):
        gt = runs(["A"]) + runs(["NA"], "1", "Other/empty")
        for row in gt:
            row["scores"] = {"NA": 0.1, "A": 0.9}
        events, _, cases = prepare_logs(gt)
        event_xml = """<event>
          <date key="time:timestamp" value="1970-01-01T00:00:00Z"/>
          <int key="segment:start_timestamp" value="0"/>
          <int key="segment:end_timestamp" value="0"/>
          <string key="concept:name" value="A"/>
        </event>"""
        def write_xes(event_count):
            path = self.root / "reference.xes"
            path.write_text('<log xmlns="http://www.xes-standard.org/"><trace>'
                            '<string key="concept:name" value="0"/>'
                            + event_xml * event_count + '</trace></log>')
            return path
        result = verify_reference_xes(write_xes(1), events, cases)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["empty_cases_omitted_from_upstream_xes"], ["1"])
        for event_count in (0, 2):
            with self.subTest(event_count=event_count), self.assertRaises(ValueError):
                verify_reference_xes(write_xes(event_count), events, cases)

    def test_accuracy_scope_can_change_selected_model(self):
        gt = runs(["NA", "NA", "A", "B"])
        all_best = frame_accuracy(gt, runs(["NA", "NA", "A", "A"]))
        non_na_best = frame_accuracy(gt, runs(["A", "A", "A", "B"]))
        leaderboard = [{"model_id": "all-best", **all_best}, {"model_id": "non-na-best", **non_na_best}]
        self.assertEqual(choose_model(leaderboard, "all"), "all-best")
        self.assertEqual(choose_model(leaderboard, "non_na"), "non-na-best")

    def test_invalid_coverage_and_duration_are_rejected(self):
        invalid_logs = {
            "missing_initial_frame": [self.csv_row(1, 2)],
            "gap": [self.csv_row(), self.csv_row(2, 3)],
            "overlap": [self.csv_row(0, 2), self.csv_row(2, 3)],
            "duplicate": [self.csv_row(), self.csv_row()],
            "wrong_duration": [self.csv_row(0, 1, duration_frames=1)],
            "negative_frame": [self.csv_row(-1, 0)],
            "reverse_interval": [self.csv_row(2, 1)],
            "case_name_change": [self.csv_row(), self.csv_row(1, 1, case_name="Other/name")],
        }
        for name, rows in invalid_logs.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                read_segments(self.write_csv(rows, name + ".csv"))

    def test_incompatible_gt_and_prediction_are_rejected(self):
        gt = runs(["A", "B"])
        invalid = {
            "missing_case": runs(["A", "B"], "1"),
            "wrong_name": runs(["A", "B"], case_name="Other/name"),
            "truncated": runs(["A"]),
            "extra_frame": runs(["A", "B", "A"]),
        }
        for name, pred in invalid.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                frame_accuracy(gt, pred)
        with self.assertRaises(ValueError):
            frame_accuracy(runs(["NA"]), runs(["NA"]))

    def test_invalid_scores_and_stored_top_label_are_rejected(self):
        invalid = {
            "negative": {"NA": 0.1, "A": 1.0, "B": -0.1},
            "nan": {"NA": 0.1, "A": float("nan"), "B": 0.9},
            "infinite": {"NA": 0.1, "A": float("inf"), "B": 0.9},
            "boolean": {"NA": 0.0, "A": True, "B": 0.0},
            "wrong_mass": {"NA": 0.1, "A": 0.1, "B": 0.1},
            "missing_na": {"A": 0.6, "B": 0.4},
            "missing_gt": {"NA": 0.6, "B": 0.4},
        }
        for name, scores in invalid.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                read_segments(self.write_csv([self.csv_row(scores=scores)], name + ".csv"))
        with self.assertRaises(ValueError):
            read_segments(self.write_csv([self.csv_row(pred_label_name="B")]))

    def test_pinned_source_checksum_copy_and_cache_reject_corruption(self):
        source = self.root / "source"
        project = self.root / "project"
        source.mkdir()
        project.mkdir()
        payload = b"a small pinned scientific input\n"
        (source / "input.csv").write_bytes(payload)
        manifest = {"commit": "fixture", "files": [{"path": "input.csv",
                    "sha256": hashlib.sha256(payload).hexdigest()}]}
        (project / "source_manifest.json").write_text(json.dumps(manifest))
        _, cache = ensure_inputs(project, upstream_dir=source)
        self.assertEqual((cache / "input.csv").read_bytes(), payload)
        (cache / "input.csv").write_bytes(payload + b"changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            ensure_inputs(project, offline=True)
        (cache / "input.csv").unlink()
        (source / "input.csv").write_bytes(b"different source bytes")
        with self.assertRaisesRegex(ValueError, "checksum"):
            ensure_inputs(project, upstream_dir=source)
        self.assertFalse((cache / "input.csv").exists())
        self.assertEqual(list(cache.glob("*.part")), [])

    def test_missing_offline_input_and_unsafe_manifest_path_are_rejected(self):
        manifest = {"commit": "fixture", "files": [{"path": "missing.csv", "sha256": "0" * 64}]}
        (self.root / "source_manifest.json").write_text(json.dumps(manifest))
        with self.assertRaises(FileNotFoundError):
            ensure_inputs(self.root, offline=True)
        manifest["files"][0]["path"] = "../outside.csv"
        (self.root / "source_manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            ensure_inputs(self.root, offline=True)


if __name__ == "__main__":
    unittest.main()
