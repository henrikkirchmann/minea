#!/usr/bin/env python3
"""Run a reproducible sequential construction/matching experiment.

Both algorithms use exactly the same original score values and numerical
constraints. Central upload is counted separately from solver work. Each
result is checked against an independent encoder before it is saved.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
from fractions import Fraction
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import sys
import time

from minea_ikea.reference import (compare_construction, components_from_rows,
                                encode_centrally, validate_selection)

ROOT = Path(__file__).resolve().parent


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)


def read_json(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def upload_centrally(instance):
    """Copy each source's records to a separate central input, without GT."""
    by_id = {c["id"]: c for c in instance["candidates"]}
    messages = []
    for source in instance["sources"]:
        candidates = [dict(c) for c in instance["candidates"] if c["owner"] == source]
        exclusions = []
        for row in instance["given_rows"]:
            if row["kind"] == "assignment":
                continue  # The receiver derives these from observation membership.
            owners = {by_id[v]["owner"] for v, coefficient in row["terms"].items() if coefficient}
            if len(owners) != 1:
                raise ValueError("Baseline input requires nonempty given exclusions with one owner")
            if source in owners:
                exclusions.append({**row, "terms": dict(row["terms"])})
        messages.append({"source": source, "candidates": candidates, "given_rows": exclusions})
    uploaded = {k: instance[k] for k in ("cases", "sources", "case_hosts", "prerequisites", "occurrence_bounds")}
    uploaded["candidates"] = sorted([c for m in messages for c in m["candidates"]], key=lambda c: c["id"])
    uploaded["given_rows"] = [r for m in messages for r in m["given_rows"]]
    observations = {}
    for c in uploaded["candidates"]:
        row = observations.setdefault(c["observation_id"], {
            "id": f"assignment:{c['observation_id']}", "kind": "assignment",
            "case_id": c["case_id"], "terms": {}, "upper": 1})
        row["terms"][c["id"]] = 1
    uploaded["given_rows"].extend(observations.values())
    metrics = {"upload_messages": len(messages), "candidate_records": len(uploaded["candidates"]),
               "score_values": len(uploaded["candidates"]),
               "given_exclusion_rows": sum(len(m["given_rows"]) for m in messages),
               "given_coefficient_terms": sum(len(r["terms"]) for m in messages for r in m["given_rows"]),
               "per_source": {str(m["source"]): {"candidate_records": len(m["candidates"]),
                               "given_exclusion_rows": len(m["given_rows"])} for m in messages},
               "scope": "One logical upload per source: all candidate records and scores, plus given exclusions. Fixed templates and case roster are common configuration. No GT labels, raw frames, packets or byte counts."}
    return uploaded, metrics


def check_matching_result(instance, rows, result):
    """Feasibility and objective checks do not trust the solver's status."""
    if result["status"] not in {"optimal", "infeasible", "limited", "unknown"}:
        raise ValueError("Unknown matching termination status")
    if result.get("selected_ids") is not None:
        check = validate_selection(instance, rows, result["selected_ids"])
        if not check["feasible"]:
            raise ValueError(f"Returned matching violates rows: {check['violations'][:5]}")
        if result.get("objective") is None or Fraction(check["objective"]) != Fraction(result["objective"]):
            raise ValueError("Returned objective differs from the original exact scores")
        if result.get("lower_bound") is None or Fraction(result["lower_bound"]) != Fraction(check["objective"]):
            raise ValueError("Incumbent objective and lower bound disagree")
        if result["status"] == "infeasible":
            raise ValueError("Infeasible status contradicts a returned feasible selection")
    else:
        if result.get("objective") is not None or result.get("lower_bound") is not None:
            raise ValueError("A finite incumbent bound requires its complete selection")
        check = {"feasible": None, "scope": "No complete matching returned"}
    lower, upper = result.get("lower_bound"), result.get("upper_bound")
    if lower is not None and upper is not None and Fraction(lower) > Fraction(upper):
        raise ValueError("Inverted objective bounds")
    if result["status"] == "optimal":
        if result.get("selected_ids") is None or lower is None or upper is None:
            raise ValueError("Optimal status requires a complete selection and closed bounds")
        if not Fraction(lower) == Fraction(upper) == Fraction(result["objective"]):
            raise ValueError("Optimal status without equal certified bounds")
    return check


def check_comparison(central, distributed, feasible_reference_score=None):
    """Check both directions, including interrupted runs and known GT feasibility."""
    finite_lower, finite_upper = [], []
    for result in (central, distributed):
        if result.get("lower_bound") is not None:
            finite_lower.append(Fraction(result["lower_bound"]))
        if result.get("upper_bound") is not None:
            finite_upper.append(Fraction(result["upper_bound"]))
        if feasible_reference_score is not None:
            if result["status"] == "infeasible":
                raise ValueError("Solver reports infeasible although GT is verified feasible")
            if result.get("upper_bound") is not None and Fraction(result["upper_bound"]) < Fraction(feasible_reference_score):
                raise ValueError("Certified upper bound excludes the feasible GT score")
    if finite_lower and finite_upper and max(finite_lower) > min(finite_upper):
        raise ValueError("Compared incumbent and certified upper bounds contradict each other")
    for exact, other in ((central, distributed), (distributed, central)):
        if exact["status"] != "optimal":
            continue
        optimum = Fraction(exact["objective"])
        if other["status"] == "infeasible":
            raise ValueError("Compared solver feasibility conclusions disagree")
        lower, upper = other.get("lower_bound"), other.get("upper_bound")
        if (lower is not None and Fraction(lower) > optimum) or (upper is not None and Fraction(upper) < optimum):
            raise ValueError("Compared bounds exclude the independently computed optimum")
    if central["status"] == distributed["status"] == "optimal":
        if Fraction(central["objective"]) != Fraction(distributed["objective"]):
            raise ValueError("Central and distributed exact optimal scores disagree")
        return "PASS"
    return "not_both_optimal"


def record_optimum(optimal, seed, component_count, value):
    value = Fraction(value)
    key = (seed, component_count)
    if key in optimal and optimal[key] != value:
        raise ValueError("Exact optima differ across K")
    for (other_seed, other_count), other_value in optimal.items():
        if other_seed != seed:
            continue
        if ((other_count > component_count and other_value < value)
                or (other_count < component_count and other_value > value)):
            raise ValueError("Adding exclusions increased the exact optimum")
    optimal[key] = value


def numerical_fingerprint(instance, rows):
    return fingerprint({"candidates": [{k: v for k, v in c.items() if k != "owner"}
                                       for c in sorted(instance["candidates"], key=lambda c: c["id"])],
                        "rows": rows})


def flatten_counts(value, prefix=""):
    """Only scalar numeric counters go into the compact stage CSV."""
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            yield from flatten_counts(item, name)
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            yield name, item


def write_report(output, summaries):
    lines = ["# Construction and matching benchmark", "",
        "This is a sequential simulation of the paper's logical protocol, with exact rational scores. "
        "Elapsed times are single-machine observations; no distributed speedup is inferred.", "",
        "The central baseline receives all candidates and given exclusions once. Both methods use "
        "the same constraints, component decomposition, exact solver, and case-based execution order. "
        "No GT warm start is supplied. Limits are separate, equal time budgets per method and condition; "
        "the distributed method additionally has its recorded search-node cap.", "",
        "`optimal` means exact solver bounds closed and returned selections passed independent checks. "
        "`limited` and `unknown` do not establish an optimum. `not_run` denotes construction-only conditions.", "",
        "| Condition | K | Components | Central | Distributed | Central completed components | Distributed completed components | Distributed visited / queried nodes |",
        "|---|---:|---:|---|---|---:|---:|---:|"]
    stage_lines = ["", "## Construction work", "",
        "These columns have different units: logical deliveries, full candidate records, and coefficient terms. "
        "They are not byte counts and are not added into a communication-cost score.", "",
        "| Condition | Owner registrations | Case edges | Election rank deliveries | Lookup deliveries | Shared rows | Shared coefficient terms | Central candidate records |",
        "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for summary in summaries:
        folder = output / summary["condition"]
        matching = {}
        for method in ("central", "distributed"):
            path = folder / f"{method}_matching.json.gz"
            matching[method] = read_json(path) if path.exists() else {"components": [], "metrics": {}}
        completed = {method: sum(c["status"] == "optimal" for c in r["components"])
                     for method, r in matching.items()}
        metrics = matching["distributed"]["metrics"]
        lines.append(f"| {summary['condition']} | {summary['sources']} | {summary['components']} | "
                     f"{summary['central_status']} | {summary['distributed_status']} | "
                     f"{completed['central']} | {completed['distributed']} | "
                     f"{metrics.get('visited_nodes', '—')} / {metrics.get('queried_nodes', '—')} |")
        stages = read_json(folder / "construction.json.gz")["metrics"]["stages"]
        lookup = stages["intra_case_row_construction"]
        stage_lines.append(f"| {summary['condition']} | {stages['candidate_owner_discovery']['directory_entries']} | "
                           f"{stages['case_edge_discovery']['unique_undirected_edges']} | "
                           f"{stages['coordinator_election']['rank_transmissions']} | "
                           f"{lookup['lookup_requests']} | {lookup['shared_rows']} | "
                           f"{lookup['transferred_coefficient_terms']} | {summary['candidates']} |")
    lines.extend(stage_lines)
    lines.extend(["", "## Rechecking", "",
        "Read `protocol.json` for budgets and conventions, `counts.csv` for named counters, "
        "and each condition's compressed instance, construction, central rows, and solver outputs. "
        "A result's component records retain exact incumbent/bound fractions and termination reasons. "
        "Complete traces are included only when `--trace` was requested.", "",
        "The offline verifier checks hashes, model equality, feasible selections, bounds consistency, "
        "and logical counts. It does not independently prove Z3's optimality conclusions from a formal proof artifact. "
        "Small exhaustive tests supply a separate optimality oracle.", ""])
    (output / "REPORT.md").write_text("\n".join(lines))


def run_condition(instance, folder, *, construction_only=False, time_limit=30.0,
                  node_limit=1000, trace=False):
    from minea_ikea.construction import construct
    folder.mkdir(parents=True)
    write_json(folder / "instance.json.gz", instance)
    started = time.perf_counter()
    construction = construct(instance, trace=trace)
    construction_seconds = time.perf_counter() - started
    checks = {"construction": compare_construction(instance, construction)}
    uploaded, upload_metrics = upload_centrally(instance)
    reference_rows = encode_centrally(uploaded)
    components = components_from_rows(uploaded, reference_rows)
    if "gt_selected" in instance and instance["gt_selected"]:
        checks["ground_truth"] = validate_selection(instance, reference_rows, instance["gt_selected"])
        if not checks["ground_truth"]["feasible"]:
            raise ValueError("Ground-truth reference is no longer feasible")
    rows_hash = numerical_fingerprint(instance, reference_rows)
    write_json(folder / "construction.json.gz", construction)
    write_json(folder / "central_rows.json.gz", reference_rows)
    write_json(folder / "central_upload.json", upload_metrics)
    distributed = central = {"status": "not_run"}
    if not construction_only:
        from minea_ikea.matching import match_central, match_distributed
        # Each method receives its own equal per-condition budget. Times are sequential.
        central = match_central(uploaded, rows=reference_rows, components=components,
                                time_limit=time_limit, trace=trace)
        checks["central_matching"] = check_matching_result(instance, reference_rows, central)
        distributed = match_distributed(instance, construction, time_limit=time_limit,
                                        node_limit=node_limit, trace=trace)
        checks["distributed_matching"] = check_matching_result(instance, reference_rows, distributed)
        checks["optimal_score_agreement"] = check_comparison(
            central, distributed, checks.get("ground_truth", {}).get("objective"))
        write_json(folder / "central_matching.json.gz", central)
        write_json(folder / "distributed_matching.json.gz", distributed)
    summary = {"metadata": instance.get("metadata", {}), "numerical_model_sha256": rows_hash,
               "cases": len(instance["cases"]), "sources": len(instance["sources"]),
               "components": len(components), "candidates": len(instance["candidates"]),
               "component_case_sizes": [len(c["case_ids"]) for c in components],
               "component_candidate_sizes": [len(c["candidate_ids"]) for c in components],
               "source_candidate_counts": dict(Counter(str(c["owner"]) for c in instance["candidates"])),
               "construction_sequential_seconds": construction_seconds,
               "central_status": central["status"], "distributed_status": distributed["status"],
               "central_objective": central.get("objective"), "distributed_objective": distributed.get("objective"),
               "checks": checks}
    write_json(folder / "summary.json", summary)
    return summary


def integers(text):
    result = [int(x.strip()) for x in text.split(",")]
    if not result or min(result) < 0 or len(result) != len(set(result)):
        raise argparse.ArgumentTypeError("Use distinct nonnegative comma-separated integers")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "inputs/reference/full")
    parser.add_argument("--instance", type=Path, help="Use a hand-auditable standalone instance JSON instead of generating a grid.")
    parser.add_argument("--sources", type=integers, default=[1, 2, 4, 8])
    parser.add_argument("--components", type=integers, default=[116, 58, 29, 15, 8, 4, 2, 1])
    parser.add_argument("--seeds", type=integers, default=[0])
    parser.add_argument("--max-sources", type=int, default=8)
    parser.add_argument("--construction-only", action="store_true")
    parser.add_argument("--time-limit", type=float, default=30.0, help="Seconds for each algorithm per condition, shared across its components.")
    parser.add_argument("--node-limit", type=int, default=1000, help="Total distributed search-node budget per condition.")
    parser.add_argument("--trace", action="store_true", help="Save complete logical transcripts; useful for small examples.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not math.isfinite(args.time_limit) or args.time_limit < 0 or args.node_limit < 0 or args.max_sources < 1:
        parser.error("Limits must be nonnegative and max-sources positive")
    if min(args.sources) < 1 or min(args.components) < 1:
        parser.error("Source and component counts must be positive")
    if any(args.max_sources % k for k in args.sources):
        parser.error("Every source count must divide max-sources")
    dataset = None
    if not args.instance:
        from minea_ikea.instances import load_dataset, generate_plan, build_instance, validate_plan
        dataset = load_dataset(args.input)
        if max(args.components) > len(dataset["cases"]):
            parser.error("Component count exceeds the retained case count")
    else:
        # Read early so a missing or malformed manual input does not create an output.
        manual_instance = read_json(args.instance)
    output = args.output or ROOT / "results/runs" / ("benchmark_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ"))
    output = output.resolve()
    if output.exists():
        parser.error("Output already exists; choose a fresh directory")
    output.mkdir(parents=True)
    protocol = {"created_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
                "platform": platform.platform(), "arguments": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
                "execution": "Sequential simulation on one machine; logical records, not network packets; no distributed speedup claim.",
                "score_policy": "Exact rational values of original stored decimal scores; no normalization or rounding.",
                "baseline": "All sources upload all candidates and given exclusions once; central encoder constructs rows and exact solver uses the same case decomposition.",
                "lower_bound_rows": "Omit only zero occurrence lower bounds; retain empty upper rows.",
                "initial_incumbent": "None; GT is independently verified but not supplied to either solver as a warm start."}
    write_json(output / "protocol.json", protocol)
    snapshot = output / "implementation_snapshot"
    files_to_snapshot = [ROOT / "benchmark.py", ROOT / "requirements.txt", *sorted((ROOT / "minea_ikea").glob("*.py"))]
    for path in files_to_snapshot:
        target = snapshot / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    summaries, same_models, optimal = [], {}, {}

    def conditions():
        # Stream one condition at a time, including when all 116 C values are tested.
        if args.instance:
            yield "manual", manual_instance
        else:
            for seed in args.seeds:
                plan = generate_plan(dataset, seed, args.max_sources)
                write_json(output / f"plan_seed{seed}.json.gz", plan)
                write_json(output / f"plan_checks_seed{seed}.json", validate_plan(dataset, plan))
                for source_count in args.sources:
                    for component_count in args.components:
                        instance = build_instance(dataset, plan, source_count, component_count)
                        yield f"seed{seed}_K{source_count}_C{component_count}", instance

    for name, instance in conditions():
        print(f"Running {name}…", flush=True)
        summary = run_condition(instance, output / name, construction_only=args.construction_only,
                                time_limit=args.time_limit, node_limit=args.node_limit, trace=args.trace)
        summary["condition"] = name
        metadata = instance.get("metadata", {})
        seed = metadata.get("seed", 0)
        key = (seed, summary["components"])
        previous = same_models.setdefault(key, summary["numerical_model_sha256"])
        if previous != summary["numerical_model_sha256"]:
            raise ValueError("Changing K changed the numerical optimization model")
        if summary["central_status"] == "optimal":
            record_optimum(optimal, seed, summary["components"], summary["central_objective"])
        if summary["distributed_status"] == "optimal":
            record_optimum(optimal, seed, summary["components"], summary["distributed_objective"])
        summaries.append(summary)
        write_json(output / "summary.json", summaries)
        print(f"  construction verified; central={summary['central_status']}; distributed={summary['distributed_status']}", flush=True)
    records = []
    for summary in summaries:
        folder = output / summary["condition"]
        objects = {"construction": read_json(folder / "construction.json.gz")["metrics"],
                   "central_upload": read_json(folder / "central_upload.json")}
        for method in ("central", "distributed"):
            path = folder / f"{method}_matching.json.gz"
            if path.exists():
                objects[method + "_matching"] = read_json(path).get("metrics", {})
        for stage, values in objects.items():
            for metric, value in flatten_counts(values):
                records.append({"condition": summary["condition"], "stage": stage, "metric": metric, "value": value})
    with (output / "counts.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["condition", "stage", "metric", "value"])
        writer.writeheader(); writer.writerows(records)
    write_report(output, summaries)
    files = {str(p.relative_to(output)): {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
             for p in sorted(output.rglob("*")) if p.is_file()}
    write_json(output / "artifact_manifest.json", {"files": files})
    print(json.dumps({"output": str(output), "conditions": len(summaries),
                      "central_statuses": dict(Counter(s["central_status"] for s in summaries)),
                      "distributed_statuses": dict(Counter(s["distributed_status"] for s in summaries))}, indent=2))
    return summaries


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(f"ERROR: {error}") from error
