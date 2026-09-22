#!/usr/bin/env python3
"""Run the complete auditable input preparation and constraint discovery study.

Python 3.10+; standard library only. From any working directory:
    python3 /path/to/ikea-asm-paper-evaluation/run.py
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import sys

from minea_ikea.data import (audit_models, choose_model, ensure_inputs, prepare_logs,
                             sha256, verify_reference_xes)
from minea_ikea.exports import export_cohort, markdown_report, write_csv, write_json
from minea_ikea.mining import mine_constraints, select_variant_cases

ROOT = Path(__file__).resolve().parent
# IDE users can edit these defaults. Command-line arguments override them.
SETTINGS = {"accuracy_scope": "non_na", "variant_coverage": 1.0,
            "drop_empty_cases": True, "model": None, "top_k": 3, "candidate_policy": "top-k-gt"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-dir", type=Path, help="Copy inputs from an existing upstream checkout; hashes must match the pinned commit.")
    parser.add_argument("--offline", action="store_true", help="Require all pinned inputs to be cached; do not download.")
    parser.add_argument("--output", type=Path, help="Fresh output directory, relative to this project or absolute. Existing directories are rejected.")
    parser.add_argument("--accuracy-scope", choices=("non_na", "all"), default=SETTINGS["accuracy_scope"])
    parser.add_argument("--model", default=SETTINGS["model"], help="Explicit upstream model ID, overriding automatic accuracy selection.")
    parser.add_argument("--top-k", type=int, default=SETTINGS["top_k"], help="Candidate count before and after any GT replacement; start with highest-scoring non-NA labels; no renormalization (default: 3).")
    parser.add_argument("--candidate-policy", choices=("top-k", "top-k-gt"), default=SETTINGS["candidate_policy"],
                        help="Default top-k-gt replaces the last-ranked candidate with GT only when GT is missing. top-k is the score-only baseline. Original scores are preserved.")
    parser.add_argument("--variant-coverage", type=float, default=SETTINGS["variant_coverage"], help="Whole variants covering at least this case fraction (0,1]; include all cutoff ties. Full cohort is always retained as well.")
    parser.add_argument("--drop-empty-cases", action=argparse.BooleanOptionalAction, default=SETTINGS["drop_empty_cases"], help="Exclude cases left empty by GT-NA removal from both logs and mining (default: enabled).")
    args = parser.parse_args(argv)
    if not 0 < args.variant_coverage <= 1:
        parser.error("--variant-coverage must be in (0,1]")
    if args.top_k < 1:
        parser.error("--top-k must be positive")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output = args.output or Path("results/runs") / stamp
    output = output if output.is_absolute() else ROOT / output
    output = output.resolve()
    if output.exists():
        parser.error(f"Output already exists: {output}; use a fresh directory to preserve previous evidence.")
    print("Checking pinned inputs and comparing all ten supplied models…", flush=True)
    manifest, cache = ensure_inputs(ROOT, args.upstream_dir, args.offline)
    leaderboard, loaded = audit_models(manifest, cache)
    model = choose_model(leaderboard, args.accuracy_scope, args.model)
    gt, uncertain, cases = prepare_logs(loaded[model], args.top_k, args.candidate_policy)
    reference = next(item for item in manifest["files"] if item["role"] == "ground_truth_reference")
    source_audit = verify_reference_xes(cache / reference["path"], gt, cases)
    original_case_ids = [c["case_id"] for c in cases]
    nonempty = {e["case_id"] for e in gt}
    excluded_empty = [c["case_id"] for c in cases if c["case_id"] not in nonempty] if args.drop_empty_cases else []
    cases = [c for c in cases if c["case_id"] not in excluded_empty]
    case_ids = [c["case_id"] for c in cases]
    # Mine GT constraints over the complete activity vocabulary, independently
    # of which model alternatives survive the candidate cutoff.
    alphabet = [label for label in loaded[model][0]["scores"] if label != "NA"]
    if [e["event_id"] for e in gt] != [e["event_id"] for e in uncertain]:
        raise ValueError("Certain and uncertain observations are not aligned")
    mined = mine_constraints(gt, case_ids, alphabet)
    full_variants = select_variant_cases(gt, case_ids)
    selection = select_variant_cases(gt, case_ids, args.variant_coverage)
    preview80 = select_variant_cases(gt, case_ids, 0.8)
    output.mkdir(parents=True)
    replacements = []
    if args.candidate_policy == "top-k-gt":
        for row in loaded[model]:
            if row["activity"] == "NA":
                continue
            ranked = sorted((label for label in row["scores"] if label != "NA"),
                            key=lambda label: (-row["scores"][label], label))
            if row["activity"] not in ranked[:args.top_k]:
                dropped = ranked[args.top_k - 1]
                replacements.append({"event_id": f"case{row['case_id']}:frames{row['start_frame']}-{row['end_frame_exclusive']}",
                                     "case_id": row["case_id"], "replaced_activity": dropped,
                                     "replaced_score": row["scores"][dropped], "inserted_gt_activity": row["activity"],
                                     "inserted_original_score": row["scores"][row["activity"]],
                                     "gt_original_non_na_rank": ranked.index(row["activity"]) + 1})
    write_csv(output / "candidate_replacements.csv", replacements,
              ["event_id", "case_id", "replaced_activity", "replaced_score", "inserted_gt_activity", "inserted_original_score", "gt_original_non_na_rank"])
    print(f"Selected {model}; mining {len(gt)} observations across {len(cases)} cases…", flush=True)
    export_cohort(output / "full", gt, uncertain, cases, mined, full_variants, top_k=args.top_k, candidate_policy=args.candidate_policy)
    selected_ids = set(selection["selected_case_ids"])
    if selected_ids != set(case_ids):
        selected_gt = [e for e in gt if e["case_id"] in selected_ids]
        selected_uncertain = [e for e in uncertain if e["case_id"] in selected_ids]
        selected_cases = [c for c in cases if c["case_id"] in selected_ids]
        selected_mined = mine_constraints(selected_gt, selection["selected_case_ids"], alphabet)
        export_cohort(output / "selected", selected_gt, selected_uncertain, selected_cases, selected_mined, selection, top_k=args.top_k, candidate_policy=args.candidate_policy)
    write_json(output / "requested_variant_selection.json", selection)
    write_json(output / "variant_80_percent_preview.json", preview80)
    write_json(output / "model_selection.json", {"selection_metric": args.accuracy_scope, "model_override": args.model,
               "tie_breaking": "Lexicographic model ID on equal integer correct-frame count.",
               "selected_model": model, "models": leaderboard})
    write_csv(output / "model_selection.csv", [{k: v for k, v in r.items() if k != "per_case"} for r in leaderboard])
    write_json(output / "source_audit.json", {**source_audit, "all_model_gt_annotations_identical": True,
               "original_case_ids": original_case_ids, "explicitly_excluded_empty_cases": excluded_empty,
               "score_conservation_by_model": {r["model_id"]: r["max_score_conservation_error"] for r in leaderboard}})
    group_details = {}
    for group in sorted({case["process_group"] for case in cases}):
        members = [c["case_id"] for c in cases if c["process_group"] == group]
        group_mined = mine_constraints([e for e in gt if e["case_id"] in members], members, alphabet)
        group_details[group] = {"scope": "Diagnostic natural furniture group; does not replace full-cohort constraints.",
                                "metadata": group_mined["metadata"],
                                "accepted_prerequisites": group_mined["accepted_prerequisites"],
                                "occurrence_bounds": group_mined["occurrence_bounds"]}
    write_json(output / "furniture_group_diagnostics.json", group_details)
    summary = {"status": "PASS", "selected_model": model, "model_override": args.model, "accuracy_scope": args.accuracy_scope,
               "case_count": len(cases), "nonempty_case_count": len(nonempty),
               "empty_case_count": len(cases) - len(nonempty), "event_count": len(gt),
               "activity_count": len(alphabet), "candidate_count": sum(len(e["scores"]) for e in uncertain),
               "top_k": args.top_k,
               "candidate_policy": args.candidate_policy, "gt_replacement_count": len(replacements),
               "gt_covered_observations": sum(a["activity"] in b["scores"] for a, b in zip(gt, uncertain)),
               "gt_candidate_coverage": sum(a["activity"] in b["scores"] for a, b in zip(gt, uncertain)) / len(gt),
               "removed_na_segments": sum(c["removed_na_segments"] for c in cases),
               "process_groups": dict(Counter(c["process_group"] for c in cases)),
               "mining": mined["metadata"], "requested_variant_selection": selection["metadata"],
               "variant80": preview80["metadata"]}
    write_json(output / "summary.json", summary)
    (output / "REPORT.md").write_text(markdown_report(summary, leaderboard, mined, preview80), encoding="utf-8")
    implementation = [ROOT / "run.py", ROOT / "verify.py", *sorted((ROOT / "minea_ikea").glob("*.py")), ROOT / "source_manifest.json"]
    snapshot = output / "implementation_snapshot"
    for source in implementation:
        dest = snapshot / source.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    write_json(output / "protocol.json", {"created_utc": stamp, "source_repository": manifest["repository"],
               "source_commit": manifest["commit"], "python": sys.version, "platform": platform.platform(),
               "arguments": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()
                             if k not in {"upstream_dir", "output"}},
               "frames_per_second": 25, "time_intervals": "Half-open, per-case frame coordinates.",
               "score_policy": f"Reuse mean frame probabilities, remove NA, keep {args.top_k} candidates with policy {args.candidate_policy}; ties by activity name; no renormalization or score changes. top-k-gt replaces the last retained candidate with GT if GT is absent.",
               "mining_scope": "Entire chosen ground-truth cohort; not independent held-out process knowledge.",
               "implementation_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in implementation}})
    write_json(output / "artifact_manifest.json", {"files": {
        str(p.relative_to(output)): {"sha256": sha256(p), "bytes": p.stat().st_size}
        for p in sorted(output.rglob("*")) if p.is_file()}})
    print(json.dumps({"status": "PASS", "output": str(output), "selected_model": model,
                      "cases": len(cases), "observations": len(gt),
                      "prerequisites": len(mined["accepted_prerequisites"]),
                      "occurrence_bounds": len(mined["occurrence_bounds"]),
                      "positive_minima": mined["metadata"]["positive_minimum_count"],
                      "requested_variant_actual_coverage": selection["metadata"]["actual_coverage"]}, indent=2))
    return summary


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(f"ERROR: {error}") from error
