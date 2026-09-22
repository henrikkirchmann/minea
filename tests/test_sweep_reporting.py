"""Reporting invariants: component interfaces, coverage and incomplete runs."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analyze_sweep import CS, KS, collect_component_rows, collect_matching, coverage_groups, main, overview_data
from benchmark import write_json


class SweepReportingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.job = {"id": "distributed_K2_C3", "method": "distributed", "condition": "seed0_K2_C3"}
        write_json(self.root / "protocol.json", {"jobs": [self.job]})
        self.folder = self.root / "jobs" / self.job["id"]
        self.folder.mkdir(parents=True)
        write_json(self.folder / "job.json", {"execution_status": "complete"})
        write_json(self.folder / "resources.json", {"peak_rss_bytes": 1024})
        self.result = {
            "status": "limited", "selected_ids": None, "objective": None,
            "lower_bound": None, "upper_bound": None, "relative_gap": None,
            "elapsed_seconds": 300, "metrics": {"optimization_requests": 25, "visited_nodes": 14},
            "components": [
                {"case_ids": ["A", "B"], "status": "optimal", "selected_ids": ["a", "b"],
                 "metrics": {"visited_nodes": 1}},
                {"case_ids": ["C"], "status": "limited", "selected_ids": ["c"],
                 "metrics": {"visited_nodes": 13}},
                {"case_ids": [str(i) for i in range(113)], "status": "limited", "selected_ids": None,
                 "metrics": {"visited_nodes": 0}},
            ],
        }
        self.save_result()

    def save_result(self):
        write_json(self.folder / "result.json.gz", self.result)

    def test_coverage_counts_cases_not_components_or_incumbents(self):
        row, = collect_matching(self.root)
        self.assertEqual(row["optimal_components"], 1)
        self.assertEqual(row["cases_in_optimal_components"], 2)
        self.assertEqual(row["components_with_incumbent"], 2)
        self.assertEqual(row["unstarted_components"], 1)
        self.assertEqual(row["cases_in_unstarted_components"], 113)
        self.assertEqual(row["root_solved_components"], 1)
        self.assertFalse(row["complete_matching"])
        for key in ("objective", "lower_bound", "upper_bound", "relative_gap"):
            self.assertIsNone(row[key])
        self.assertEqual(row["optimization_requests"], 25)

    def test_missing_jobs_are_only_allowed_in_explicit_preview(self):
        (self.folder / "resources.json").unlink()
        self.assertEqual(collect_matching(self.root, allow_missing=True), [])
        with self.assertRaises(FileNotFoundError):
            collect_matching(self.root)

    def test_component_table_preserves_unvisited_cases_and_infinite_bounds(self):
        for index, part in enumerate(self.result["components"]):
            part.update(id=f"part_{index}", reason="test_limit" if part["status"] == "limited" else "test_optimum",
                candidate_count=3 * len(part["case_ids"]), sources=[0, 1], interface_variable_count=2,
                objective=None, lower_bound=None, lower_bound_kind="negative_infinity",
                upper_bound=None, upper_bound_kind="positive_infinity", relative_gap=None)
            part["metrics"].update(optimization_requests=0, source_calls=0, central_solver_calls=0, z3_checks=0)
        self.save_result()
        rows = collect_component_rows(self.root)
        self.assertEqual([r["execution_index"] for r in rows], [1, 2, 3])
        self.assertEqual([r["cases"] for r in rows], [2, 1, 113])
        self.assertEqual(rows[0]["case_ids"], "A|B")
        self.assertEqual(rows[-1]["visited_nodes"], 0)
        self.assertFalse(rows[-1]["has_feasible_selection"])
        self.assertEqual(rows[-1]["upper_bound_kind"], "positive_infinity")
        self.assertIsNone(rows[-1]["upper_bound"])

    def test_execution_failure_is_not_plotted_as_solver_timeout(self):
        write_json(self.folder / "job.json", {"execution_status": "execution_error"})
        with self.assertRaisesRegex(ValueError, "completed job records"):
            collect_matching(self.root, allow_missing=True)

    def test_central_reference_keeps_one_actual_measurement(self):
        central = {"id": "central_C3", "method": "central", "condition": "seed0_K1_C3"}
        write_json(self.root / "protocol.json", {"jobs": [central, self.job]})
        folder = self.root / "jobs" / central["id"]
        folder.mkdir()
        write_json(folder / "job.json", {"execution_status": "complete"})
        write_json(folder / "resources.json", {"peak_rss_bytes": 2048})
        write_json(folder / "result.json.gz", self.result)
        rows = collect_matching(self.root)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(r["method"] == "central" for r in rows), 1)
        self.assertIsNone(rows[0]["root_solved_components"])

    def test_final_figure_pipeline_refuses_incomplete_verification(self):
        with patch("sys.argv", ["analyze_sweep.py", "--input", str(self.root), "--output", str(self.root / "output")]), \
             patch("verify_sweep.verify_sweep", return_value={"status": "INCOMPLETE"}), \
             patch("analyze_sweep.render_figures") as render_figures:
            with self.assertRaisesRegex(ValueError, "Complete verified sweep"):
                main()
            render_figures.assert_not_called()


class CoverageGroupingTests(unittest.TestCase):
    def records(self):
        rows = []
        for source in (None, 1, 2, 4, 8):
            for c, covered in zip(CS, (116, 46, 8, 0, 0, 0, 0, 0)):
                completed = source in (None, 1) or c == 116
                rows.append({'method': 'central' if source is None else 'distributed',
                    'sources': source or 1, 'components': c,
                    'cases_in_optimal_components': 116 if completed else covered,
                    'status': 'optimal' if completed else 'limited',
                    'elapsed_seconds': (source or 1) * 10, 'visited_nodes': (source or 1) * 100})
        return rows

    def test_equal_coverage_preserves_members_despite_different_work(self):
        groups = coverage_groups(self.records())
        self.assertEqual([g['sources'] for g in groups], [[None, 1], [2, 4, 8]])
        self.assertEqual(sum(len(g['sources']) * len(g['records']) for g in groups), 40)

    def test_changed_coverage_or_status_cannot_be_hidden_in_a_group(self):
        rows = self.records()
        for row in rows:
            if row['sources'] == 4 and row['components'] == 58:
                row['cases_in_optimal_components'] = 48
            if row['sources'] == 8 and row['components'] == 58:
                row['status'] = 'unknown'
        self.assertEqual([g['sources'] for g in coverage_groups(rows)], [[None, 1], [2], [4], [8]])

    def test_incomplete_grid_cannot_be_summarized_as_final_coverage(self):
        with self.assertRaisesRegex(ValueError, 'all 40'):
            coverage_groups(self.records()[:-1])

    def structural_records(self):
        rows = []
        for k in KS:
            for c in CS:
                total = 0 if k == 1 else 17 * k
                rows.append({'sources': k, 'components': c, 'lookup_requests': 83 * k,
                    'interface_variables': total,
                    'maximum_component_interface': (total + c - 1) // c})
        return rows

    def test_component_interface_panel_preserves_each_condition_and_zero_interfaces(self):
        structural = self.structural_records()
        data = overview_data(list(reversed(structural)), self.records())
        self.assertEqual(set(data), {'component_interface_panel', 'coverage_groups', 'scope'})
        panel = data['component_interface_panel']
        self.assertEqual([group['sources'] for group in panel], KS)
        for group in panel:
            self.assertEqual([point['components'] for point in group['points']], CS)
        plotted = {(group['sources'], point['components']): point
                   for group in panel for point in group['points']}
        self.assertEqual(len(plotted), len(structural))
        for row in structural:
            point = plotted[row['sources'], row['components']]
            self.assertEqual(point['maximum_component_interface'], row['maximum_component_interface'])
            self.assertEqual(point['interface_variables'], row['interface_variables'])
        self.assertTrue(all(point['maximum_component_interface'] == 0 for point in panel[0]['points']))

    def test_changed_component_size_does_not_change_coverage_or_other_conditions(self):
        structural = self.structural_records()
        before = overview_data(structural, self.records())
        changed = next(row for row in structural if row['sources'] == 4 and row['components'] == 15)
        changed['maximum_component_interface'] += 1
        after = overview_data(structural, self.records())
        self.assertEqual(after['coverage_groups'], before['coverage_groups'])
        self.assertEqual(after['scope'], before['scope'])
        differences = [(old_group['sources'], old_point['components'])
                       for old_group, new_group in zip(before['component_interface_panel'], after['component_interface_panel'])
                       for old_point, new_point in zip(old_group['points'], new_group['points'])
                       if old_point != new_point]
        self.assertEqual(differences, [(changed['sources'], changed['components'])])

    def test_overview_requires_every_structural_grid_point(self):
        structural = [row for row in self.structural_records()
                      if (row['sources'], row['components']) != (4, 29)]
        with self.assertRaisesRegex(ValueError, 'all 32 structural grid points'):
            overview_data(structural, self.records())

    def test_duplicate_or_unexpected_structural_points_cannot_be_dropped(self):
        for extra_point in (False, True):
            with self.subTest(extra_point=extra_point):
                structural = self.structural_records()
                if extra_point:
                    structural.append(dict(structural[0]))
                else:
                    structural[-1] = dict(structural[0])
                with self.assertRaisesRegex(ValueError, 'Duplicate structural grid point'):
                    overview_data(structural, self.records())
        structural = self.structural_records()
        structural[-1]['sources'] = max(KS) + 1
        with self.assertRaisesRegex(ValueError, 'Unexpected structural grid point'):
            overview_data(structural, self.records())

    def test_structural_panel_counts_are_integers_and_maximum_does_not_exceed_total(self):
        for field in ('sources', 'components', 'lookup_requests', 'interface_variables',
                      'maximum_component_interface'):
            for invalid in (-1, True, 1.5, '1', None):
                with self.subTest(field=field, invalid=invalid):
                    structural = self.structural_records()
                    structural[0][field] = invalid
                    with self.assertRaisesRegex(ValueError, 'nonnegative integer'):
                        overview_data(structural, self.records())
        structural = self.structural_records()
        structural[-1]['maximum_component_interface'] = structural[-1]['interface_variables'] + 1
        with self.assertRaisesRegex(ValueError, 'exceeds total interface variables'):
            overview_data(structural, self.records())


if __name__ == "__main__":
    unittest.main()
