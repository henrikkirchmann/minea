#!/usr/bin/env python3
"""Export verified sweep tables and the paper's Figure 3 as a vector PDF.

The Python plotting toolchain is Matplotlib with TeX Live for Libertine labels.
No optimizer is called. Censored work is labelled as partial work, never as
the cost of reaching an optimum. One central measurement per C stays one row.
"""

import argparse
import csv
import hashlib
from pathlib import Path

from benchmark import read_json, write_json

ROOT = Path(__file__).resolve().parent
KS = [1, 2, 4, 8]
CS = [116, 58, 29, 15, 8, 4, 2, 1]
STAGES = ["candidate_owner_discovery", "case_edge_discovery", "coordinator_election",
          "notification_registration", "intra_case_row_construction", "construction_completion"]
def csv_write(path, records):
    fields = list(dict.fromkeys(key for record in records for key in record))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def collect_structure(study):
    records = []
    for k in KS:
        for c in CS:
            name = f"seed0_K{k}_C{c}"
            folder = study / "construction" / name
            instance = read_json(folder / "instance.json.gz")
            construction = read_json(folder / "construction.json.gz")
            upload = read_json(folder / "central_upload.json")
            owners = {v["id"]: v["owner"] for v in instance["candidates"]}
            shared = [r for r in construction["rows"] if len({owners[v] for v in r["terms"]}) > 1]
            interface = {v for r in shared for v in r["terms"]}
            sizes = [len(interface.intersection(component["candidate_ids"]))
                     for component in construction["components"]]
            stage = construction["metrics"]["stages"]["intra_case_row_construction"]
            records.append({"condition": name, "sources": k, "components": c,
                "cases": 116, "observations": 1856, "candidates": 5568, "bridges": 116 - c,
                "local_generated_rows": stage["local_rows"], "shared_generated_rows": stage["shared_rows"],
                "empty_generated_rows": stage["empty_rows"], "interface_variables": len(interface),
                "maximum_component_interface": max(sizes),
                "maximum_cases_in_component": max(len(p["case_ids"]) for p in construction["components"]),
                "maximum_candidates_in_component": max(len(p["candidate_ids"]) for p in construction["components"]),
                "lookup_requests": stage["lookup_requests"],
                "shared_coefficient_terms": stage["transferred_coefficient_terms"],
                "logical_deliveries": construction["metrics"]["totals"]["messages"],
                "cross_host_deliveries": construction["metrics"]["totals"]["cross_host_messages"],
                "central_upload_messages": upload["upload_messages"],
                "central_candidate_records": upload["candidate_records"],
                **{s + "_deliveries": construction["metrics"]["stages"][s]["messages"] for s in STAGES}})
    return records


def collect_matching(study, allow_missing=False):
    records = []
    protocol = read_json(study / "protocol.json")
    for job in protocol["jobs"]:
        folder = study / "jobs" / job["id"]
        if allow_missing and not (folder / "resources.json").exists():
            continue
        record = read_json(folder / "job.json")
        if record["execution_status"] != "complete":
            raise ValueError("Figures require completed job records, including valid limited results")
        result = read_json(folder / "result.json.gz")
        usage = read_json(folder / "resources.json")
        parts = result["components"]
        started_key = "visited_nodes" if job["method"] == "distributed" else "central_solver_calls"
        unstarted = [p for p in parts if p["metrics"].get(started_key, 0) == 0]
        records.append({"job": job["id"], "condition": job["condition"], "method": job["method"],
            "sources": int(job["condition"].split("_K")[1].split("_C")[0]),
            "components": len(parts), "status": result["status"],
            "optimal_components": sum(p["status"] == "optimal" for p in parts),
            "cases_in_optimal_components": sum(len(p["case_ids"]) for p in parts if p["status"] == "optimal"),
            "root_solved_components": sum(p["status"] == "optimal" and p["metrics"]["visited_nodes"] == 1 for p in parts)
                if job["method"] == "distributed" else None,
            "components_with_incumbent": sum(p["selected_ids"] is not None for p in parts),
            "unstarted_components": len(unstarted),
            "cases_in_unstarted_components": sum(len(p["case_ids"]) for p in unstarted),
            "complete_matching": result["selected_ids"] is not None,
            "objective": result["objective"], "lower_bound": result["lower_bound"],
            "upper_bound": result["upper_bound"], "relative_gap": result["relative_gap"],
            "elapsed_seconds": result["elapsed_seconds"], "peak_rss_bytes": usage["peak_rss_bytes"],
            **result["metrics"]})
    return records


def collect_component_rows(study):
    """Readable per-component evidence, including the sequential execution order."""
    records = []
    for job in read_json(study / "protocol.json")["jobs"]:
        result = read_json(study / "jobs" / job["id"] / "result.json.gz")
        for index, part in enumerate(result["components"], 1):
            records.append({"job": job["id"], "condition": job["condition"], "method": job["method"],
                "execution_index": index, "component": part["id"],
                "case_ids": "|".join(part["case_ids"]), "cases": len(part["case_ids"]),
                "status": part["status"], "reason": part["reason"],
                "has_feasible_selection": part["selected_ids"] is not None,
                "candidate_count": part["candidate_count"], "participating_sources": len(part["sources"]),
                "interface_variables": part["interface_variable_count"],
                **{key: part[key] for key in ("objective", "lower_bound", "lower_bound_kind",
                    "upper_bound", "upper_bound_kind", "relative_gap")},
                **{key: part["metrics"][key] for key in ("visited_nodes", "optimization_requests",
                    "source_calls", "central_solver_calls", "z3_checks")}})
    return records


def coverage_groups(matching):
    """Combine equal plotted outcomes without claiming equal time or search work."""
    if len(matching) != 40:
        raise ValueError('The overview requires all 40 recorded jobs')
    distributed = {(r['sources'], r['components']): r for r in matching if r['method'] == 'distributed'}
    central = {r['components']: r for r in matching if r['method'] == 'central'}
    # Group only exactly equal coverage AND termination status, never timings or work.
    groups = {}
    for k in [None, *KS]:
        records = [central.get(c) if k is None else distributed.get((k, c)) for c in CS]
        if any(r is None for r in records):
            raise ValueError('The overview requires all 40 recorded jobs')
        signature = tuple((r['cases_in_optimal_components'], r['status']) for r in records)
        groups.setdefault(signature, {'sources': [], 'records': records})['sources'].append(k)
    return list(groups.values())


def _structural_grid(structural):
    """Require one valid construction record for every plotted condition."""
    expected = {(k, c) for k in KS for c in CS}
    at = {}
    for row in structural:
        for field in ('sources', 'components', 'lookup_requests', 'interface_variables',
                      'maximum_component_interface'):
            value = row.get(field)
            if type(value) is not int or value < 0:
                raise ValueError(f'Structural field {field} must be a nonnegative integer')
        key = row['sources'], row['components']
        if key not in expected:
            raise ValueError(f'Unexpected structural grid point {key}')
        if key in at:
            raise ValueError(f'Duplicate structural grid point {key}')
        if row['maximum_component_interface'] > row['interface_variables']:
            raise ValueError(f'Maximum component interface exceeds total interface variables at {key}')
        at[key] = row
    missing = expected.difference(at)
    if missing:
        raise ValueError(f'The overview requires all {len(expected)} structural grid points; missing {sorted(missing)}')
    return at


def overview_data(structural, matching):
    """Retain every individual value underlying the paper's two figure panels."""
    at = _structural_grid(structural)
    return {
        'component_interface_panel': [{'sources': k,
            'points': [{'components': c,
                **{metric: at[k,c][metric] for metric in ('maximum_component_interface', 'interface_variables')}}
                for c in CS]} for k in KS],
        'coverage_groups': [{'members': ['central' if k is None else f'distributed_K{k}' for k in g['sources']],
            'points': [{key: r[key] for key in ('components', 'cases_in_optimal_components', 'status')}
                       for r in g['records']]} for g in coverage_groups(matching)],
        'scope': 'Groups share plotted case coverage and completion status only; they can differ in time, work and solved-case identities.'}


def render_figures(overview, figures):
    # Keep plotting dependencies optional for data verification and solver tests.
    from plot_sweep import export_figures
    return export_figures(overview, figures)


def render_report(structural, matching, verification):
    completed_distributed = sum(r["status"] == "optimal" for r in matching if r["method"] == "distributed")
    completed_central = sum(r["status"] == "optimal" for r in matching if r["method"] == "central")
    rows = ["# Fixed-profile IKEA source/component sweep", "",
        "The full grid uses 116 cases, 1,856 observations and 5,568 candidates throughout. "
        "The five GT-supported templates, original scores, full merge hierarchy, source assignment and matching algorithms are fixed. "
        "K changes nested ownership; C adds a prefix of source-local, GT-feasible, independently witnessed cross-case exclusions.", "",
        "There are 32 distributed conditions and eight actual centralized reference measurements. "
        "Central results are reused across K only after verifying identical numerical models; they are not independent repetitions. "
        "Every matching method runs in a fresh process, with 300 seconds and a 100,000-node distributed cap. "
        "This is one seed and one run per job, on an interactive M1 Pro host with 16 GB RAM. "
        "Timings are descriptive and do not estimate deployed latency, communication overhead or parallel speedup.", "",
        f"All {len(structural)} constructed models passed the independent row checks. "
        f"Distributed matching completed {completed_distributed}/32 configurations optimally; "
        f"the central reference completed {completed_central}/8 numerical models. "
        "Completed comparison pairs agree in exact objective. Every limited run remains in the tables and Figure 3 coverage summary.", "",
        "| K | C | Distributed status | Optimal components | Cases in optimal components | Complete matching | Nodes visited | Source solve requests | Seconds |",
        "|---:|---:|---|---:|---:|---|---:|---:|---:|"]
    for r in sorted((r for r in matching if r["method"] == "distributed"), key=lambda r: (r["sources"], -r["components"])):
        rows.append(f"| {r['sources']} | {r['components']} | {r['status']} | {r['optimal_components']}/{r['components']} | "
            f"{r['cases_in_optimal_components']}/116 | {'yes' if r['complete_matching'] else 'no'} | {r['visited_nodes']} | "
            f"{r['optimization_requests']} | {r['elapsed_seconds']:.2f} |")
    rows.extend(["", "## Actual centralized measurements", "",
        "| C | Status | Optimal components | Complete matching | Seconds |", "|---:|---|---:|---|---:|"])
    for r in sorted((r for r in matching if r["method"] == "central"), key=lambda r: -r["components"]):
        rows.append(f"| {r['components']} | {r['status']} | {r['optimal_components']}/{r['components']} | "
                    f"{'yes' if r['complete_matching'] else 'no'} | {r['elapsed_seconds']:.2f} |")
    rows.extend(["", "## Interpretation and reproducibility", "",
        "Figure 3(a) summarizes the largest component interface by the arithmetic mean across two, four and eight sources. "
        "These are source-count settings, not repeated experimental trials; their values differ by at most 28 variables at each recorded component count. "
        "The central and one-source reference has no inter-source matching interface. "
        "Figure 3(b) groups only exactly equal case coverage and completion status; runtime and search work can differ. "
        "All plotted markers are filled, and the saved tables retain termination status. "
        "Counts in limited runs are work observed before stopping, not total work to an optimum. "
        "An optimal component covers every case in it; the figure reports the number of covered cases out of 116, avoiding changing component-count denominators. "
        "Coverage is specific to sequential case-ID order and the shared whole-run budget: a hard early component can leave easier later components unvisited. "
        "A component incumbent does not constitute a complete event log. Missing global incumbents or infinite bounds are not zero-valued solutions.", "",
        "Construction reports logical role-to-role deliveries, including co-located roles. Candidate records, coefficient terms and protocol requests have different meanings and are not combined into a byte-cost score. "
        "The central baseline uploads every candidate and its original score; its upload counts are recorded for each K in construction.csv.", "",
        "The candidate set uses GT boundaries and inserts a missing GT label by replacing the third-ranked candidate. "
        "Templates were mined on the same cohort and the reduced profile was chosen after a full-model calibration failed to complete within its budget. "
        "These are exploratory controlled protocol experiments, not held-out recognition accuracy or a representative deployment workload.", "",
        f"Offline verification: {verification['status']}; {verification['matching_jobs_verified']} matching jobs, "
        f"{verification['within_model_component_comparisons']} within-model component comparisons. "
        "Saved large-instance optimality conclusions still rely on Z3; exact returned-selection feasibility and objective sums are independently checked. "
        "No full node transcripts were requested.", "",
        "`construction.csv`, `matching.csv`, `components.csv`, `summary.json`, `verification.json`, and `overview_data.json` retain the reported evidence. "
        "Only the current paper figure is exported: `figures/ikea-overview.pdf` and its editable PGF source. "
        "All tables and figure files are regenerated from the unchanged saved sweep; the original producer snapshots remain with that sweep. "
        "The component table records execution order, case IDs, termination reasons, incumbents and bounds; matching.csv separately counts unstarted components and their cases. "
        "Regenerate with `python3 analyze_sweep.py --input results/benchmark_sweep --output paper_output/ikea_sweep` (install requirements-figures.txt; TeX Live required).", ""])
    return "\n".join(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "results/benchmark_sweep")
    parser.add_argument("--output", type=Path, default=ROOT / "paper_output/ikea_sweep")
    args = parser.parse_args()
    study, output = args.input.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    figures = output / "figures"
    figures.mkdir(exist_ok=True)
    from verify_sweep import verify_sweep
    verification = verify_sweep(study)
    if verification["status"] != "PASS":
        raise ValueError("Complete verified sweep required for final matching figures")
    structural = collect_structure(study)
    csv_write(output / "construction.csv", structural)
    matching = collect_matching(study)
    overview = overview_data(structural, matching)
    write_json(output / 'overview_data.json', overview)
    csv_write(output / "matching.csv", matching)
    csv_write(output / "components.csv", collect_component_rows(study))
    write_json(output / "summary.json", {"construction": structural, "matching": matching})
    write_json(output / "verification.json", verification)
    (output / "REPORT.md").write_text(render_report(structural, matching, verification))
    macros = {
        "IkeaDistributedOptimal": sum(r["status"] == "optimal" for r in matching if r["method"] == "distributed"),
        "IkeaCentralOptimal": sum(r["status"] == "optimal" for r in matching if r["method"] == "central"),
        "IkeaComponentComparisons": verification["within_model_component_comparisons"],
        "IkeaPeakMemoryGiB": f"{max(r['peak_rss_bytes'] for r in matching)/1024**3:.2f}",
    }
    (output / "numbers.tex").write_text("% Generated only from a complete verified sweep.\n" +
        "\n".join("\\newcommand{\\" + key + "}{" + str(value) + "}" for key, value in macros.items()) + "\n")
    rendering = render_figures(overview, figures)
    try:
        study_label = str(study.relative_to(ROOT))
    except ValueError:
        study_label = str(study)
    write_json(output / "figure_provenance.json", {
        **rendering,
        "complete_matching_sweep": True,
        "study": study_label,
        "construction_manifest_sha256": hashlib.sha256((study / "construction/artifact_manifest.json").read_bytes()).hexdigest(),
        "analysis_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "style": "Python/Matplotlib vector PDF; embedded manuscript Libertine fonts. Aligned axes show mean largest component interface and budgeted case coverage, with reversed log component axes and solid lines distinguished by color and marker shape.",
        "censoring": "Uniformly filled markers report optimal-component case coverage within the whole-log budget. Termination status and work counts remain in matching.csv; partial work is not extrapolated. Coverage depends on component order and unresolved cases can include unvisited components.",
        "overview_grouping": "Panel (a) shows the arithmetic mean across two, four and eight sources, not repeated trials; their largest-interface values differ by at most 28 variables at any recorded component setting. Panel (b) groups only exactly equal per-component-setting case coverage and completion status; runtime and search work may differ. Individual component-interface values and group membership are in overview_data.json."})
    from sweep import manifest
    manifest(output)
    print(f"Verified figure output: {output}")


if __name__ == "__main__":
    main()
