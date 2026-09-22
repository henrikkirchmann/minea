#!/usr/bin/env python3
"""Check the frozen factorial sweep offline; no construction or solver is run.

Central results are checked against their actual K=1 instances. Reuse at other
K requires identical numerical fingerprints and corresponding case partitions.
Saved large-instance solver optimality claims still rely on the exact backend.
"""

import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from benchmark import check_comparison, check_matching_result, numerical_fingerprint, record_optimum
from minea_ikea.instances import load_dataset, validate_plan
from minea_ikea.reference import encode_centrally, validate_selection
from sweep_instances import _audit_grid, SELECTED_IDS
from verify_benchmark import _equal, _manifest, _read, _require, _safe_path, _verify_matching, verify_study

ROOT = Path(__file__).resolve().parent


def verify_sweep(path, allow_incomplete=False):
    root = Path(path).resolve()
    if allow_incomplete:
        manifest_count = None
    else:
        manifest_count = len(_manifest(root))
    protocol = _read(root / "protocol.json")
    grid = {"sources": [1, 2, 4, 8], "components": [116, 58, 29, 15, 8, 4, 2, 1], "seeds": [0]}
    _equal(protocol["grid"], grid, "Declared factorial grid")
    _equal((protocol["time_limit_seconds"], protocol["node_limit"]), (300, 100000), "Declared matching limits")
    for name, digest in protocol["producer_sha256"].items():
        saved = _safe_path(root / "implementation_snapshot", name)
        _equal(hashlib.sha256(saved.read_bytes()).hexdigest(), digest, f"Producer snapshot {name}")
    prep = root / "preparation"
    _manifest(prep)
    instances = {record["condition"]: _read(_safe_path(prep, record["instance"]))
                 for record in _read(prep / "index.json")["conditions"]}
    dataset = load_dataset(ROOT / "inputs/reference/full")
    plan = _read(prep / "plan_seed0.json.gz")
    validate_plan(dataset, plan)  # Validate the original hierarchy against its original model.
    selected = _read(prep / "selection_protocol.json")
    _equal(selected["selection"], SELECTED_IDS, "Frozen template selection")
    retry = _read(ROOT / "inputs/provenance/selected_instance.json.gz")
    preparation_check = _audit_grid(instances, dataset, plan, SELECTED_IDS, retry)
    saved_preparation = _read(prep / "validation.json")
    # JSON normalizes integer object keys used for source-count dictionaries.
    for key, value in json.loads(json.dumps(preparation_check)).items():
        _equal(saved_preparation[key], value, f"Saved preparation audit {key}")
    construction_check = verify_study(root / "construction")
    conditions = {s["condition"]: s for s in _read(root / "construction/summary.json")}
    _equal(set(instances), set(conditions), "Preparation/construction condition coverage")
    for name, instance in instances.items():
        _equal(_read(root / "construction" / name / "instance.json.gz"), instance,
               f"Prepared versus constructed instance {name}")
    expected = {f"central_C{c}": ("central", f"seed0_K1_C{c}") for c in grid["components"]}
    expected.update({f"distributed_K{k}_C{c}": ("distributed", f"seed0_K{k}_C{c}")
                     for k in grid["sources"] for c in grid["components"]})
    jobs = protocol["jobs"]
    _equal(len(jobs), 40, "Number of declared matching jobs")
    _equal({j["id"]: (j["method"], j["condition"]) for j in jobs}, expected, "Declared job coverage")
    reports, missing, errors, central, optima = {}, [], [], {}, {}
    # Check the eight actual centralized measurements first, regardless of run order.
    ordered = sorted(jobs, key=lambda j: (j["method"] != "central", j["id"]))
    component_comparisons = 0
    for job in ordered:
        folder = _safe_path(root / "jobs", job["id"])
        record_path = folder / "job.json"
        if not record_path.exists():
            missing.append(job["id"])
            continue
        record = _read(record_path)
        for key in ("id", "method", "condition"):
            _equal(record[key], job[key], f"Job identity {key}")
        if record["execution_status"] == "execution_error":
            errors.append({"id": job["id"], "error": record.get("error")})
            continue
        _equal((record["execution_status"], record["returncode"]), ("complete", 0), "Worker completion")
        instance = instances[job["condition"]]
        condition = root / "construction" / job["condition"]
        rows = encode_centrally(instance)
        construction = _read(condition / "construction.json.gz")
        result = _read(folder / "result.json.gz")
        report = _verify_matching(instance, rows, construction, result, job["method"], False)
        _equal(record["checks"], check_matching_result(instance, rows, result), "Saved exact selection check")
        _equal(result["time_limit_seconds"], 300, "Worker time limit")
        if job["method"] == "distributed":
            _equal(result["node_limit"], 100000, "Distributed node limit")
        gt = validate_selection(instance, rows, instance["gt_selected"])
        _require(gt["feasible"], "Ground truth became infeasible")
        check_comparison(result, result, gt["objective"])
        usage = _read(folder / "resources.json")
        _equal(usage["measurement"], "resource.getrusage(RUSAGE_SELF)", "Memory measurement")
        factor = 1 if usage["platform"] == "darwin" else 1024
        _equal(usage["peak_rss_raw_unit"], "bytes" if factor == 1 else "KiB", "Memory unit")
        _equal(usage["peak_rss_bytes"], int(factor * usage["peak_rss_raw"]), "Memory conversion")
        count = len(result["components"])
        fingerprint = numerical_fingerprint(instance, rows)
        if result["status"] == "optimal":
            record_optimum(optima, 0, count, result["objective"])
        if job["method"] == "central":
            central[count] = (result, fingerprint)
            _equal(result["central_upload"]["candidate_records"], 5568, "Central candidate records")
            _equal(result["central_upload"]["logical_messages"], 1, "Canonical central upload messages")
        elif count in central:
            reference, reference_fingerprint = central[count]
            _equal(fingerprint, reference_fingerprint, "Central-reference numerical equivalence")
            check_comparison(reference, result, gt["objective"])
            reference_parts = {tuple(c["case_ids"]): c for c in reference["components"]}
            _equal(set(reference_parts), {tuple(c["case_ids"]) for c in result["components"]},
                   "Central-reference case partition")
            for component in result["components"]:
                check_comparison(reference_parts[tuple(component["case_ids"] )], component)
                component_comparisons += 1
        elif not allow_incomplete:
            _require(False, "Missing actual central reference")
        reports[job["id"]] = {**report, "condition": job["condition"], "method": job["method"],
            "optimal_components": sum(c["status"] == "optimal" for c in result["components"]),
            "cases_in_optimal_components": sum(len(c["case_ids"]) for c in result["components"] if c["status"] == "optimal"),
            "complete_matching": result["selected_ids"] is not None,
            "objective": result["objective"], "elapsed_seconds": result["elapsed_seconds"],
            "peak_rss_bytes": usage["peak_rss_bytes"], "numerical_model_sha256": fingerprint}
    actual_folders = {p.name for p in (root / "jobs").iterdir() if p.is_dir()} if (root / "jobs").exists() else set()
    _require(actual_folders <= set(expected), "Undeclared matching job folders")
    if not allow_incomplete:
        _require(not missing and len(reports) + len(errors) == 40, "Incomplete matching sweep")
    status = "EXECUTION_ERRORS" if errors else "INCOMPLETE" if missing else "PASS"
    return {"status": status, "files_verified": manifest_count,
        "construction": construction_check, "preparation_condition_count": preparation_check["condition_count"],
        "matching_jobs_verified": len(reports), "central_measurements": len(central),
        "within_model_component_comparisons": component_comparisons,
        "jobs": reports, "missing_jobs": missing, "execution_errors": errors,
        "same_model_optima_and_monotonicity": "PASS",
        "scope": "No optimizer or distributed constructor was rerun. Exact row feasibility, original score arithmetic, stored solver bounds and protocol accounting checked. Eight actual central measurements supply equivalent-model references, not 32 independent baseline observations.",
        "optimality_scope": "Large-instance optimality relies on the recorded exact Z3 conclusions. Full node traces are disabled; saved final selections and certificate arithmetic are independently checked."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    report = verify_sweep(args.folder, args.allow_incomplete)
    print(json.dumps(report, indent=2))
    if report["status"] == "EXECUTION_ERRORS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
