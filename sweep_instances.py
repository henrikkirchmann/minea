#!/usr/bin/env python3
"""Prepare the fixed five-template, seed-0, 32-condition sweep without solvers.

``build_sweep_instances()`` returns ``(instances_by_condition, audit)`` in the
declared K-then-C order. ``prepare_sweep(output)`` writes those instances and
their provenance into a fresh directory and returns its ``index.json`` object.
All path parameters are keyword-only, allowing exact copies of the saved input.

The original full-model plan is validated and reused, never regenerated after
removing templates. Its fingerprint still identifies that original model.
Each prepared instance additionally records its active numerical fingerprint.
This helper neither executes distributed construction nor imports a solver.
"""

from collections import Counter
from copy import deepcopy
import argparse
import hashlib
from itertools import combinations
from pathlib import Path

from benchmark import numerical_fingerprint, read_json, write_json
from minea_ikea.instances import build_instance, load_dataset, validate_plan
from minea_ikea.reference import components_from_rows, encode_centrally, validate_selection


ROOT = Path(__file__).resolve().parent
SOURCE_COUNTS = (1, 2, 4, 8)
COMPONENT_COUNTS = (116, 58, 29, 15, 8, 4, 2, 1)
SEED = 0
PROFILE = "gt_support_3_prerequisites_2_count_bounds"
SELECTED_IDS = {"prerequisites": ["pre_019", "pre_036", "pre_023"],
                "occurrence_bounds": ["occ_031", "occ_021"]}
DATA_FOLDER = ROOT / "inputs/reference/full"
PLAN_PATH = ROOT / "inputs/provenance/plan_seed0.json.gz"
SELECTION_PATH = ROOT / "inputs/provenance/selection_protocol.json"
CALIBRATION_INSTANCE_PATH = ROOT / "inputs/provenance/original_instance.json.gz"
RETRY_INSTANCE_PATH = ROOT / "inputs/provenance/selected_instance.json.gz"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _without_metadata(instance):
    return {key: value for key, value in instance.items() if key != "metadata"}


def _selected_templates(dataset, selection):
    return {family: [deepcopy(t) for t in dataset[family] if t["id"] in selection[family]]
            for family in SELECTED_IDS}


def _audit_grid(instances, dataset, plan, selection, retry):
    """Check the prepared grid independently of the instance constructor."""
    names = [f"seed{SEED}_K{k}_C{c}" for k in SOURCE_COUNTS for c in COMPONENT_COUNTS]
    _require(list(instances) == names, "Sweep conditions or declared order differ")
    templates = _selected_templates(dataset, selection)
    owners_by_k, hosts_by_k, model_by_c, components_by_c, checks = {}, {}, {}, {}, {}
    bare_candidates = [{key: value for key, value in candidate.items() if key != "owner"}
                       for candidate in dataset["candidates"]]
    row_cache = {}
    for k in SOURCE_COUNTS:
        for c in COMPONENT_COUNTS:
            name = f"seed{SEED}_K{k}_C{c}"
            instance = instances[name]
            _require(instance["cases"] == dataset["cases"] and instance["sources"] == list(range(k)),
                     f"Case roster or sources changed: {name}")
            _require(instance["gt_selected"] == dataset["gt_selected"], f"GT selection changed: {name}")
            actual_candidates = [{key: value for key, value in candidate.items() if key != "owner"}
                                 for candidate in instance["candidates"]]
            _require(actual_candidates == bare_candidates, f"Candidate content, scores or ordering changed: {name}")
            _require(all(instance[family] == templates[family] for family in templates),
                     f"Active templates or ordering changed: {name}")
            owners = {candidate["id"]: candidate["owner"] for candidate in instance["candidates"]}
            expected = {candidate["id"]: plan["observation_owners"][candidate["observation_id"]] // (8 // k)
                        for candidate in dataset["candidates"]}
            _require(owners == expected, f"Full-plan ownership changed: {name}")
            _require(instance["case_hosts"] == {case: host // (8 // k) for case, host in plan["case_hosts"].items()},
                     f"Full-plan agent hosting changed: {name}")
            _require(owners == owners_by_k.setdefault(k, owners), f"Ownership moved when C changed: {name}")
            _require(instance["case_hosts"] == hosts_by_k.setdefault(k, instance["case_hosts"]),
                     f"Case hosting moved when C changed: {name}")
            bridges = [{"id": b["id"], "kind": "exclusion", "terms": b["terms"], "upper": b["upper"], "case_id": None}
                       for b in plan["bridges"][:116 - c]]
            _require(instance["given_rows"] == dataset["given_rows"] + bridges, f"Full-plan bridge prefix changed: {name}")
            _require(all(len({owners[v] for v in b["terms"]}) == 1 for b in bridges),
                     f"Intercase row is not source-local: {name}")
            rows = encode_centrally(instance)
            gt = validate_selection(instance, rows, instance["gt_selected"])
            _require(gt["feasible"] and gt["objective"] == dataset["metadata"]["gt_score"], f"GT check failed: {name}")
            model = numerical_fingerprint(instance, rows)
            _require(model == model_by_c.setdefault(c, model), f"Numerical model differs across K at C={c}")
            _require(rows == row_cache.setdefault(c, rows), f"Encoded rows differ across K at C={c}")
            components = components_from_rows(instance, rows)
            partition = sorted(tuple(part["case_ids"]) for part in components)
            _require(len(components) == c, f"Independent graph has the wrong component count: {name}")
            _require(partition == components_by_c.setdefault(c, partition), f"Case components differ across K at C={c}")
            by_id = {candidate["id"]: candidate for candidate in instance["candidates"]}
            edges = set()
            for row in rows:
                cases = sorted({by_id[v]["case_id"] for v in row["terms"]})
                edges.update(combinations(cases, 2))
            expected_edges = {tuple(sorted((b["a_case_id"], b["b_case_id"]))) for b in plan["bridges"][:116 - c]}
            _require(edges == expected_edges and len(edges) == 116 - c, f"Hierarchy edges differ: {name}")
            metadata = instance["metadata"]
            _require((metadata["seed"], metadata["source_count"], metadata["component_count"],
                      metadata["bridge_count"], metadata["prerequisite_template_count"],
                      metadata["occurrence_bound_template_count"]) == (0, k, c, 116 - c, 3, 2),
                     f"Active metadata is inconsistent: {name}")
            shared = [row for row in rows if len({owners[v] for v in row["terms"]}) > 1]
            checks[name] = {"sources": k, "components": c, "rows": len(rows),
                "bridges": len(bridges), "unique_intercase_edges": len(edges),
                "numerical_model_sha256": model, "gt_feasible": True, "gt_score": gt["objective"],
                "component_case_sizes": [len(part["case_ids"]) for part in components],
                "shared_rows": len(shared), "interface_variables": len({v for row in shared for v in row["terms"]}),
                "source_candidate_counts": dict(sorted(Counter(owners.values()).items()))}
    _require(_without_metadata(instances["seed0_K2_C116"]) == _without_metadata(retry),
             "K2 C116 differs from the published five-template retry")
    complete = instances["seed0_K1_C1"]
    gt_ids = set(complete["gt_selected"])
    for bridge in plan["bridges"]:
        witness = bridge["witness"]
        chosen = gt_ids - {witness["removed_candidate_id"]} | {witness["selected_candidate_id"]}
        result = validate_selection(complete, row_cache[1], sorted(chosen))
        _require(result["violations"] == [bridge["id"]], f"Reduced-model nonredundancy witness failed: {bridge['id']}")
    return {"status": "PASS", "condition_count": len(checks), "conditions": checks,
            "same_numeric_model_across_sources": True, "same_ownership_across_components": True,
            "nested_source_ownership_and_agent_hosts": True, "unchanged_case_candidate_score_and_gt_content": True,
            "same_K2_C116_as_published_retry_except_metadata": True,
            "unchanged_bridge_hierarchy": True, "checked_reduced_model_nondegeneracy_witnesses": len(plan["bridges"]),
            "validation_scope": "Independent central encoding, exact GT feasibility, graph and placement checks, and every full-plan nonredundancy witness. No construction or solver execution."}


def build_sweep_instances(*, data_folder=DATA_FOLDER, plan_path=PLAN_PATH,
                          selection_path=SELECTION_PATH,
                          calibration_instance_path=CALIBRATION_INSTANCE_PATH,
                          retry_instance_path=RETRY_INSTANCE_PATH):
    """Return all 32 instances plus their independent audit and input provenance.

    Only the five active templates change from the original prepared population.
    K changes ownership/hosting and C selects the saved full-plan bridge prefix.
    Solver budgets and execution order belong to the calling runner.
    """
    paths = {"plan": Path(plan_path).resolve(), "selection_protocol": Path(selection_path).resolve(),
             "calibration_instance": Path(calibration_instance_path).resolve(),
             "retry_instance": Path(retry_instance_path).resolve()}
    selection_protocol = read_json(paths["selection_protocol"])
    _require(selection_protocol["profile"] == PROFILE and selection_protocol["selection"] == SELECTED_IDS,
             "Selection protocol does not declare the fixed five-template profile")
    _require(selection_protocol["seed"] == SEED, "Selection protocol must use seed 0")
    dataset = load_dataset(Path(data_folder))
    _require((len(dataset["cases"]), len(dataset["candidates"]), dataset["metadata"]["observation_count"]) ==
             (116, 5568, 1856), "The fixed prepared population must contain 116 cases, 1856 observations and 5568 candidates")
    plan = read_json(paths["plan"])
    _require((plan["seed"], plan["max_sources"]) == (0, 8), "The saved full plan must use seed 0 and max_sources 8")
    plan_check = validate_plan(dataset, plan)
    calibration, retry = read_json(paths["calibration_instance"]), read_json(paths["retry_instance"])
    _require(_sha256(paths["calibration_instance"]) == selection_protocol["source_instance_sha256"],
             "Selection protocol names a different original calibration instance")
    _require(dataset["metadata"]["input_hashes"]["ground_truth.csv"] == selection_protocol["ground_truth_sha256"],
             "Selection protocol names a different GT input")
    _require(_without_metadata(build_instance(dataset, plan, 2, 116)) == _without_metadata(calibration),
             "Saved plan or prepared cohort differs from the original calibration")
    _require(retry["metadata"]["constraint_subset_retry"] == selection_protocol,
             "Published retry uses a different selection protocol")
    active = _selected_templates(dataset, SELECTED_IDS)
    _require((len(active["prerequisites"]), len(active["occurrence_bounds"])) == (3, 2), "Selected templates are missing or repeated")
    _require(all(t["lower"] == 0 for t in active["occurrence_bounds"]), "Expected zero selected count lower bounds")
    provenance = {"profile": PROFILE, "seed": SEED, "source_counts": list(SOURCE_COUNTS),
        "component_counts": list(COMPONENT_COUNTS), "selection": deepcopy(SELECTED_IDS),
        "source_files": {name: {"path": str(path), "sha256": _sha256(path)} for name, path in paths.items()},
        "prepared_input_folder": str(Path(data_folder).resolve()),
        "prepared_input_hashes": dataset["metadata"]["input_hashes"],
        "original_full_model_dataset_fingerprint": dataset["metadata"]["dataset_fingerprint"],
        "plan_provenance": "Reuse the published original full-model plan without regenerating bridges, endpoints, witnesses, block placement or source coarsening.",
        "selection_provenance": "Freeze the same five templates selected for the exploratory retry; do not rerank by any sweep outcome.",
        "ordering": "K in (1,2,4,8), then C in (116,58,29,15,8,4,2,1); input candidate, template and bridge order preserved. Matching ordering is unchanged and controlled by the existing runner.",
        "score_policy": "Exact original stored decimal strings; no normalization or rounding.",
        "scope": "One seed and a previously chosen weaker constraint model; not evidence about performance on the original 73-template model."}
    instances = {}
    for k in SOURCE_COUNTS:
        for c in COMPONENT_COUNTS:
            instance = build_instance(dataset, plan, k, c)
            instance.update(deepcopy(active))
            instance["metadata"].update({"prerequisite_template_count": 3, "occurrence_bound_template_count": 2,
                "constraint_subset_sweep": {"profile": PROFILE, "selection": deepcopy(SELECTED_IDS),
                    "selection_protocol_sha256": provenance["source_files"]["selection_protocol"]["sha256"],
                    "original_full_plan_sha256": provenance["source_files"]["plan"]["sha256"],
                    "original_full_model_dataset_fingerprint": plan["dataset_fingerprint"],
                    "original_prerequisite_template_count": len(dataset["prerequisites"]),
                    "original_occurrence_bound_template_count": len(dataset["occurrence_bounds"]),
                    "hierarchy_and_ownership_unchanged": True}})
            instances[f"seed{SEED}_K{k}_C{c}"] = instance
    audit = _audit_grid(instances, dataset, plan, SELECTED_IDS, retry)
    for name, instance in instances.items():
        instance["metadata"]["active_numerical_model_sha256"] = audit["conditions"][name]["numerical_model_sha256"]
    audit.update({"provenance": provenance, "original_full_plan_validation": plan_check})
    return instances, audit


def prepare_sweep(output, **paths):
    """Write a fresh preparation directory, returning its runner-friendly index.

    ``index['conditions']`` contains ordered records with ``condition``,
    ``sources``, ``components`` and a relative ``instance`` filename. No matching
    is launched. Existing directories are rejected to protect recorded runs.
    """
    output = Path(output).resolve()
    _require(not output.exists(), f"Choose a fresh sweep preparation directory: {output}")
    instances, audit = build_sweep_instances(**paths)
    output.mkdir(parents=True)
    provenance = audit["provenance"]
    for source, target in (("plan", "plan_seed0.json.gz"), ("selection_protocol", "selection_protocol.json")):
        raw = Path(provenance["source_files"][source]["path"]).read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == provenance["source_files"][source]["sha256"],
                 f"Source changed during preparation: {source}")
        (output / target).write_bytes(raw)
    records = []
    for name, instance in instances.items():
        relative = f"instances/{name}.json.gz"
        write_json(output / relative, instance)
        records.append({"condition": name, "sources": instance["metadata"]["source_count"],
                        "components": instance["metadata"]["component_count"], "instance": relative,
                        "sha256": _sha256(output / relative),
                        "numerical_model_sha256": audit["conditions"][name]["numerical_model_sha256"]})
    index = {"profile": PROFILE, "seed": SEED, "source_counts": list(SOURCE_COUNTS),
             "component_counts": list(COMPONENT_COUNTS), "conditions": records,
             "validation": "validation.json", "provenance": "provenance.json",
             "original_full_plan": "plan_seed0.json.gz", "selection_protocol": "selection_protocol.json"}
    write_json(output / "validation.json", audit)
    write_json(output / "provenance.json", provenance)
    write_json(output / "index.json", index)
    files = {path.relative_to(output).as_posix(): {"sha256": _sha256(path), "bytes": path.stat().st_size}
             for path in sorted(output.rglob("*")) if path.is_file()}
    write_json(output / "artifact_manifest.json", {"files": files})
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    index = prepare_sweep(args.output)
    print(f"Prepared and independently checked {len(index['conditions'])} sweep instances in {args.output.resolve()}")


if __name__ == "__main__":
    main()
