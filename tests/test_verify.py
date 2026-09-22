"""The separate result checker must reject incomplete or false discovered rules."""

import json
from pathlib import Path
import tempfile
import unittest

from minea_ikea.exports import export_cohort, write_csv
from minea_ikea.mining import mine_constraints, select_variant_cases
from verify import read_csv, verify_cohort


class ResultVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "full"
        cases = [{"case_id": "1", "case_name": "table/1", "process_group": "table"},
                 {"case_id": "2", "case_name": "table/2", "process_group": "table"}]
        gt = [{"event_id": "1-a", "case_id": "1", "case_name": "table/1", "start_frame": 0,
               "end_frame_exclusive": 1, "duration_frames": 1, "activity": "A"},
              {"event_id": "1-b", "case_id": "1", "case_name": "table/1", "start_frame": 2,
               "end_frame_exclusive": 3, "duration_frames": 1, "activity": "B"}]
        uncertain = [{**{k: v for k, v in event.items() if k != "activity"},
                      "scores": {"A": 0.2, "B": 0.5}, "top_activity": "B",
                      "removed_na_score": 0.3, "remaining_score_mass": 0.7} for event in gt]
        mined = mine_constraints(gt, ["1", "2"], ["A", "B"])
        variants = select_variant_cases(gt, ["1", "2"])
        export_cohort(self.folder, gt, uncertain, cases, mined, variants)

    def mutate_audit(self, function):
        path = self.folder / "constraint_audit.json"
        audit = json.loads(path.read_text())
        function(audit)
        path.write_text(json.dumps(audit))

    def test_valid_export_including_empty_case_passes(self):
        result = verify_cohort(self.folder)
        self.assertEqual((result["cases"], result["events"], result["accepted_prerequisites"]), (2, 2, 1))

    def test_omitting_rejected_pairs_does_not_masquerade_as_complete_audit(self):
        self.mutate_audit(lambda audit: audit.update(prerequisites=audit["accepted_prerequisites"]))
        with self.assertRaisesRegex(ValueError, "prerequisite pair"):
            verify_cohort(self.folder)

    def test_false_occurrence_minimum_is_rejected(self):
        self.mutate_audit(lambda audit: audit["occurrence_bounds"][0].update(minimum=1))
        with self.assertRaisesRegex(ValueError, "empirical bound"):
            verify_cohort(self.folder)

    def test_oracle_policy_requires_gt_in_every_candidate_set(self):
        path = self.folder / "candidate_policy.json"
        policy = json.loads(path.read_text())
        policy.update(candidate_policy="top-k-gt", gt_label_insertion=True, top_k=1)
        path.write_text(json.dumps(policy))
        log_path = self.folder / "uncertain_log.csv.gz"
        rows = read_csv(log_path)
        for row in rows:
            row["scores"] = {"B": 0.5}
            row["remaining_score_mass"] = 0.5
            row["discarded_non_na_score_mass"] = 0.2
        write_csv(log_path, rows)
        with self.assertRaisesRegex(ValueError, "Oracle candidate policy omitted GT"):
            verify_cohort(self.folder)


if __name__ == "__main__":
    unittest.main()
