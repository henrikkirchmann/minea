"""Offline benchmark verification, including corruption with recomputed hashes."""

import csv
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark import flatten_counts, read_json, run_condition, write_json
from minea_ikea.instances import build_instance, generate_plan
from tests.test_instances import toy_dataset
from verify_benchmark import verify_study


MATCH_COUNTERS = """visited_nodes nodes_pruned_before_query bound_prunes_before_query
fully_fixed_shared_row_prunes queried_nodes fully_evaluated_nodes partial_query_nodes
inexact_query_nodes branch_operations max_unresolved_frontier source_calls z3_checks
exact_local_solves_completed local_optimal_replies local_infeasible_replies
local_limited_replies local_unknown_replies interrupted_source_calls optimization_requests
optimization_replies pending_optimization_requests fixed_values_sent response_interface_values
shared_rows_checked shared_rows_violated shared_rows_checked_prequery shared_rows_checked_returned
bound_prunes_after_query local_infeasibility_prunes feasible_nodes feasible_incumbents
retention_requests retention_confirmations pending_retention_requests event_emission_records
central_solver_calls empty_rows_checked violated_empty_rows""".split()


def manifest(folder):
    records = {path.relative_to(folder).as_posix(): {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
    } for path in folder.rglob("*") if path.is_file() and path.name != "artifact_manifest.json"}
    write_json(folder / "artifact_manifest.json", {"files": records})


def export_counts(folder):
    condition = folder / "toy"
    objects = {"construction": read_json(condition / "construction.json.gz")["metrics"],
               "central_upload": read_json(condition / "central_upload.json")}
    for method in ("central", "distributed"):
        path = condition / f"{method}_matching.json.gz"
        if path.exists():
            objects[f"{method}_matching"] = read_json(path)["metrics"]
    with (folder / "counts.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("condition", "stage", "metric", "value"))
        writer.writeheader()
        for stage, values in objects.items():
            for metric, value in flatten_counts(values):
                writer.writerow({"condition": "toy", "stage": stage, "metric": metric, "value": value})


def limited_matching(instance, construction, method):
    """A hand-specified, unstarted run: no optimizer or protocol execution."""
    candidates = {candidate["id"]: candidate for candidate in instance["candidates"]}
    parts = []
    for component in construction["components"]:
        members = set(component["candidate_ids"])
        rows = [row for row in construction["rows"] if row["terms"] and set(row["terms"]) <= members]
        shared = [row for row in rows if len({candidates[variable]["owner"] for variable in row["terms"]}) > 1]
        interface = sorted({variable for row in shared for variable in row["terms"]})
        local_sizes = {}
        for source in component["sources"]:
            owned_rows = [row for row in rows if {candidates[variable]["owner"] for variable in row["terms"]} == {source}]
            local_sizes[str(source)] = {
                "candidate_count": sum(candidates[variable]["owner"] == source for variable in members),
                "local_row_count": len(owned_rows),
                "local_coefficient_terms": sum(len(row["terms"]) for row in owned_rows),
                "interface_variable_count": sum(candidates[variable]["owner"] == source for variable in interface),
            }
        parts.append({"id": component["id"], "case_ids": component["case_ids"],
                      "sources": component["sources"], "coordinator": component["coordinator"],
                      "candidate_count": len(members), "local_row_count": len(rows) - len(shared),
                      "shared_row_count": len(shared), "interface_ids": interface,
                      "interface_variable_count": len(interface), "local_sizes": local_sizes, "status": "limited",
                      "selected_ids": None, "objective": None, "lower_bound": None, "upper_bound": None,
                      "metrics": dict.fromkeys(MATCH_COUNTERS, 0), "trace": [], "solver_calls": [],
                      "incumbent_history": [], "unresolved_node_count": 1,
                      "unresolved_nodes": [{"node_id": 0, "fixings": {}, "upper_bound": None}]})
    metrics = dict.fromkeys(MATCH_COUNTERS, 0)
    metrics["empty_rows_checked"] = sum(not row["terms"] for row in construction["rows"])
    return {"method": method, "status": "limited", "selected_ids": None, "objective": None,
            "lower_bound": None, "upper_bound": None, "components": parts, "component_count": len(parts),
            "metrics": metrics, "trace": [{"event": "empty_row_checks", "row_ids": [row["id"] for row in construction["rows"] if not row["terms"]], "violated_row_ids": []}]}


class OfflineBenchmarkVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name) / "study"
        self.folder.mkdir()
        dataset = toy_dataset(2, 2)
        dataset["prerequisites"] = [{"id": "p", "trigger_activity": "B", "predecessor_activities": ["A"]}]
        dataset["occurrence_bounds"] = [
            {"id": "a", "activities": ["A"], "lower": 0, "upper": 2},
            {"id": "absent", "activities": ["absent"], "lower": 0, "upper": 0},
        ]
        self.plan = generate_plan(dataset, 42, 2)
        self.instance = build_instance(dataset, self.plan, 2, 1)
        self.summary = run_condition(self.instance, self.folder / "toy", construction_only=True, trace=True)
        self.summary["condition"] = "toy"
        write_json(self.folder / "protocol.json", {"arguments": {"trace": True, "construction_only": True}})
        write_json(self.folder / "summary.json", [self.summary])
        write_json(self.folder / "plan_seed42.json.gz", self.plan)
        write_json(self.folder / "plan_checks_seed42.json", self.plan["validation"])
        export_counts(self.folder)
        manifest(self.folder)

    def change(self, name, change):
        path = self.folder / name
        value = read_json(path)
        change(value)
        write_json(path, value)
        manifest(self.folder)

    def add_matching(self):
        construction = read_json(self.folder / "toy/construction.json.gz")
        for method in ("central", "distributed"):
            result = limited_matching(self.instance, construction, method)
            write_json(self.folder / f"toy/{method}_matching.json.gz", result)
            self.summary[f"{method}_status"] = "limited"
            self.summary["checks"][f"{method}_matching"] = {"feasible": None, "scope": "No complete matching returned"}
        self.summary["checks"]["optimal_score_agreement"] = "not_both_optimal"
        write_json(self.folder / "toy/summary.json", {key: value for key, value in self.summary.items() if key != "condition"})
        write_json(self.folder / "summary.json", [self.summary])
        export_counts(self.folder)
        manifest(self.folder)

    def test_valid_study_rechecks_full_plan_and_transcript_without_constructor(self):
        with patch("minea_ikea.construction.construct", side_effect=AssertionError("Verifier reran construction")):
            report = verify_study(self.folder)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["conditions_verified"], 1)
        self.assertEqual(report["plans_verified"], 1)
        self.assertEqual(report["plan_checks"]["42"]["checked_witnesses"], 1)
        self.assertIn("not independently reproved", report["optimality_scope"])

    def test_unstarted_matching_needs_no_solver_and_small_model_is_enumerated(self):
        self.add_matching()
        with patch("minea_ikea.solver.solve_exact", side_effect=AssertionError("Verifier ran a solver")):
            report = verify_study(self.folder)
        self.assertEqual(report["conditions"][0]["exhaustive_assignments_checked"], 256)

    def test_byte_corruption_is_rejected(self):
        path = self.folder / "toy/central_upload.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "Artifact size|Artifact hash"):
            verify_study(self.folder)

    def test_manifest_path_traversal_is_rejected_before_external_read(self):
        path = self.folder / "artifact_manifest.json"
        value = read_json(path)
        value["files"]["../outside"] = {"bytes": 0, "sha256": "0" * 64}
        write_json(path, value)
        with self.assertRaisesRegex(ValueError, "Unsafe artifact path"):
            verify_study(self.folder)

    def test_unlisted_artifact_is_rejected(self):
        (self.folder / "unlisted.txt").write_text("not part of the signed inventory")
        with self.assertRaisesRegex(ValueError, "Manifest coverage"):
            verify_study(self.folder)

    def test_rehashed_false_construction_counter_is_rejected(self):
        self.change("toy/construction.json.gz", lambda value: value["metrics"]["stages"]["intra_case_row_construction"].update(negative_presence_replies=999))
        with self.assertRaisesRegex(ValueError, "Construction stages"):
            verify_study(self.folder)

    def test_rehashed_wrong_presence_reply_is_rejected(self):
        def corrupt(value):
            record = next(message for message in value["trace"] if message["kind"] == "presence_reply")
            record["payload"]["present"] = not record["payload"]["present"]
        self.change("toy/construction.json.gz", corrupt)
        with self.assertRaisesRegex(ValueError, "Presence reply"):
            verify_study(self.folder)

    def test_rehashed_changed_central_row_is_rejected(self):
        self.change("toy/central_rows.json.gz", lambda value: value[0].update(upper=999))
        with self.assertRaisesRegex(ValueError, "Saved central rows"):
            verify_study(self.folder)

    def test_rehashed_false_witness_is_rejected(self):
        self.change("plan_seed42.json.gz", lambda value: value["bridges"][0]["witness"].update(selected_candidate_id=self.instance["gt_selected"][0]))
        with self.assertRaisesRegex(ValueError, "Witness"):
            verify_study(self.folder)

    def test_rehashed_invented_incumbent_bound_without_selection_is_rejected(self):
        self.add_matching()
        self.change("toy/distributed_matching.json.gz", lambda value: value.update(lower_bound="1", objective="1"))
        with self.assertRaisesRegex(ValueError, "finite incumbent bound"):
            verify_study(self.folder)

    def test_rehashed_upper_bound_below_verified_gt_is_rejected(self):
        self.add_matching()
        self.change("toy/distributed_matching.json.gz", lambda value: value.update(upper_bound="0"))
        with self.assertRaisesRegex(ValueError, "upper bound|GT score"):
            verify_study(self.folder)

    def test_rehashed_wrong_exact_objective_is_rejected(self):
        self.add_matching()
        self.change("toy/distributed_matching.json.gz", lambda value: value.update(
            selected_ids=self.instance["gt_selected"], objective="999", lower_bound="999", upper_bound="999"))
        with self.assertRaisesRegex(ValueError, "original exact scores"):
            verify_study(self.folder)

    def test_rehashed_counter_csv_change_is_rejected(self):
        path = self.folder / "counts.csv"
        with path.open(newline="") as stream:
            records = list(csv.DictReader(stream))
        records[0]["value"] = "123456"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("condition", "stage", "metric", "value"))
            writer.writeheader(); writer.writerows(records)
        manifest(self.folder)
        with self.assertRaisesRegex(ValueError, "counter CSV"):
            verify_study(self.folder)

    def test_rehashed_declared_grid_cannot_silently_omit_a_condition(self):
        self.change("protocol.json", lambda value: value["arguments"].update(
            sources=[1, 2], seeds=[42], components=[1]))
        with self.assertRaisesRegex(ValueError, "Declared grid condition coverage"):
            verify_study(self.folder)

    def test_rehashed_false_matching_local_size_is_rejected(self):
        self.add_matching()
        self.change("toy/distributed_matching.json.gz", lambda value: value["components"][0]["local_sizes"]["0"].update(candidate_count=999))
        with self.assertRaisesRegex(ValueError, "Source-local optimization model sizes"):
            verify_study(self.folder)

    def test_rehashed_fabricated_visit_without_transcript_is_rejected(self):
        self.add_matching()
        self.change("toy/distributed_matching.json.gz", lambda value: value["components"][0]["metrics"].update(visited_nodes=1))
        with self.assertRaisesRegex(ValueError, "Search transcript visited nodes"):
            verify_study(self.folder)

    def test_rehashed_false_saved_plan_check_is_rejected(self):
        self.change("plan_checks_seed42.json", lambda value: value.update(checked_witnesses=999))
        with self.assertRaisesRegex(ValueError, "Saved independent plan checks"):
            verify_study(self.folder)


if __name__ == "__main__":
    unittest.main()
