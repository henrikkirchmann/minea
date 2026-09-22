"""Round-trip checks of exported clocks, labels, scores, and case membership."""

import csv
from datetime import datetime
import gzip
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from minea_ikea.exports import write_csv, write_xes


NS = {"x": "http://www.xes-standard.org/"}


def attributes(element):
    return {child.get("key"): child.get("value") for child in element if child.get("key")}


class ExportRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.cases = [
            {"case_id": "0", "case_name": 'Furniture/assembly, "ä"', "process_group": "Furniture"},
            {"case_id": "1", "case_name": "Furniture/NA-only", "process_group": "Furniture"},
        ]
        self.gt = [{"case_id": "0", "case_name": self.cases[0]["case_name"],
                    "event_id": "case0:frames58-61", "start_frame": 58,
                    "end_frame_exclusive": 61, "duration_frames": 3,
                    "activity": "pick up leg"}]
        self.uncertain = [{**self.gt[0], "top_activity": "tighten leg",
                           "scores": {"pick up leg": 0.1, "tighten leg": 0.2},
                           "removed_na_score": 0.7, "remaining_score_mass": 0.3,
                           # Deliberately present in memory: exporting uncertainty
                           # must not leak this label as a reference attribute.
                           "gt_label_name": "pick up leg"}]

    def export_xes(self, filename, rows, uncertain=False):
        path = self.root / filename
        write_xes(path, rows, self.cases, uncertain=uncertain)
        content = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
        return ET.fromstring(content)

    def test_xes_dates_encode_frame_seconds_and_half_open_duration(self):
        root = self.export_xes("ground_truth.xes", self.gt)
        event = root.find("x:trace/x:event", NS)
        values = attributes(event)
        start = datetime.fromisoformat(values["time:timestamp"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(values["time:end_timestamp"].replace("Z", "+00:00"))
        self.assertEqual(start.timestamp(), 2.32, "Frame 58 at 25 fps is 2.32 seconds, not 58 seconds")
        self.assertEqual(end.timestamp(), 2.44)
        self.assertAlmostEqual((end - start).total_seconds(), 3 / 25)
        self.assertEqual(int(values["end_frame_exclusive"]) - int(values["start_frame"]),
                         int(values["duration_frames"]))

    def test_gt_and_uncertain_xes_preserve_empty_trace_and_observation_identity(self):
        certain = self.export_xes("ground_truth.xes", self.gt)
        uncertain = self.export_xes("uncertain.xes.gz", self.uncertain, uncertain=True)
        observations = []
        for root in (certain, uncertain):
            traces = root.findall("x:trace", NS)
            by_case = {attributes(trace)["concept:name"]: trace for trace in traces}
            self.assertEqual(set(by_case), {"0", "1"})
            self.assertEqual(len(by_case["1"].findall("x:event", NS)), 0)
            self.assertEqual(attributes(by_case["0"])["case:name"], self.cases[0]["case_name"])
            observations.append({(attributes(trace)["concept:name"], attributes(event)["event_id"],
                                  attributes(event)["start_frame"], attributes(event)["end_frame_exclusive"])
                                 for trace in traces for event in trace.findall("x:event", NS)})
        self.assertEqual(observations[0], observations[1])
        self.assertEqual(len(observations[0]), 1)

    def test_uncertain_xes_exports_model_label_without_gt_reference_attribute(self):
        root = self.export_xes("uncertain.xes.gz", self.uncertain, uncertain=True)
        values = attributes(root.find("x:trace/x:event", NS))
        # This observation is deliberately misclassified, making accidental use
        # of GT as concept:name observable without relying on an output snapshot.
        self.assertEqual(values["concept:name"], "tighten leg")
        self.assertNotEqual(values["concept:name"], self.gt[0]["activity"])
        self.assertNotIn("activity", values)
        self.assertFalse(any(key.startswith("gt") or "ground_truth" in key for key in values))
        # GT remains one alternative in the score vector, which is intentional;
        # no other event attribute should identify it as the known true label.
        self.assertFalse(any(value == self.gt[0]["activity"] for key, value in values.items()
                             if key != "scores_json"))
        scores = json.loads(values["scores_json"])
        self.assertEqual(scores, {"pick up leg": 0.1, "tighten leg": 0.2})
        self.assertNotIn("NA", scores)
        self.assertAlmostEqual(sum(scores.values()), 0.3)
        self.assertAlmostEqual(sum(scores.values()) + float(values["removed_na_score"]), 1.0)

    def test_certain_xes_exports_gt_without_prediction_scores(self):
        root = self.export_xes("certain.xes", self.gt)
        values = attributes(root.find("x:trace/x:event", NS))
        self.assertEqual(values["concept:name"], "pick up leg")
        self.assertNotIn("scores_json", values)
        self.assertNotIn("removed_na_score", values)

    def test_csv_gzip_roundtrip_preserves_unicode_nested_scores_and_original_magnitudes(self):
        fields = ["event_id", "case_id", "case_name", "start_frame", "end_frame_exclusive",
                  "duration_frames", "top_activity", "scores", "removed_na_score", "remaining_score_mass"]
        plain = self.root / "uncertain.csv"
        compressed = self.root / "uncertain.csv.gz"
        write_csv(plain, self.uncertain, fields)
        write_csv(compressed, self.uncertain, fields)
        self.assertEqual(gzip.decompress(compressed.read_bytes()), plain.read_bytes())
        with gzip.open(compressed, "rt", newline="", encoding="utf-8") as stream:
            recovered = list(csv.DictReader(stream))
        self.assertEqual(len(recovered), 1)
        row = recovered[0]
        self.assertEqual(row["case_name"], self.cases[0]["case_name"])
        self.assertEqual(json.loads(row["scores"]), self.uncertain[0]["scores"])
        self.assertEqual(row["top_activity"], "tighten leg")
        self.assertEqual(int(row["end_frame_exclusive"]) - int(row["start_frame"]), 3)
        self.assertNotIn("activity", row)
        self.assertNotIn("gt_label_name", row)
        self.assertAlmostEqual(float(row["remaining_score_mass"]), 0.3)


if __name__ == "__main__":
    unittest.main()
