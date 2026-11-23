"""Reproduce the DaRA experiments from released candidate scores or the raw archives."""

import argparse
import filecmp
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent
DATASET = HERE.parents[1] / "datasets" / "dara-retrieval"


def run(script, *arguments):
    print(f"\nRunning {script.name} in {script.parent.name}", flush=True)
    subprocess.run([sys.executable, str(script), *map(str, arguments)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="directory for the regenerated inputs, selections and tables")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--check-recorded", action="store_true",
                        help="recompute the paper's results from the included selections and measurements "
                             "using only the Python standard library")
    source.add_argument("--raw-dir", type=Path, help="directory containing the DaRA v1 video "
                        "annotation, BLE and IMU ZIPs; also rebuilds the event logs and scores")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output == HERE or output == DATASET:
        parser.error("Choose an output directory distinct from the packaged experiment and dataset.")

    if args.check_recorded:
        run(HERE / "results" / "verify.py", "--output-dir", output / "results")
        run(HERE / "coordination" / "verify.py")
        print(f"\nVerified the recorded DaRA results. The table and metrics are in {output / 'results'}.")
        return

    log = DATASET / "logs" / "dara_retrieval_gt.csv"
    scores = HERE / "classifier" / "reference"
    if args.raw_dir:
        raw = args.raw_dir.resolve()
        for filename in ("Video__Revised_Annotations.zip", "BLE__Data_and_Revised_Annotations.zip",
                         "IMU__Data_and_Revised_Annotations.zip"):
            if not (raw / filename).is_file():
                parser.error(f"Missing archive: {raw / filename}")
        run(DATASET / "export_log.py", "--input-dir", raw, "--output-dir", output / "logs")
        for name in ("dara_retrieval_gt.csv", "dara_retrieval_gt.xes"):
            if not filecmp.cmp(DATASET / "logs" / name, output / "logs" / name, shallow=False):
                raise SystemExit(f"Regenerated log differs from the released file: {name}")
        log = output / "logs" / log.name
        scores = output / "classifier"
        run(HERE / "classifier" / "reproduce.py", "--log", log, "--raw-dir", raw,
            "--output-dir", scores)

    candidates = scores / "fusion_top10_candidates.csv.gz"
    rules = output / "constraints"
    matching = output / "matching"
    run(HERE / "constraints" / "mine_constraints.py", "--log", log,
        "--nested-scores", scores / "nested_scores.json.gz", "--output-dir", rules)
    for filename in ("common_rules.csv", "selected_rules.csv", "rule_templates.json"):
        recorded = (HERE / "constraints" / filename).read_text(encoding="utf-8")
        if (rules / filename).read_text(encoding="utf-8") != recorded:
            raise SystemExit(f"Regenerated constraint artifact differs from the released file: {filename}")
    templates = rules / "rule_templates.json"
    run(HERE / "matching" / "run.py", "--log", log, "--candidates", candidates,
        "--constraints", templates, "--output-dir", matching)
    run(HERE / "results" / "verify.py", "--log", log, "--candidates", candidates,
        "--rules", rules / "selected_rules.csv", "--rerun", matching / "selections.csv",
        "--require-full-rerun", "--output-dir", output / "results")
    run(HERE / "coordination" / "verify.py", "--coordination", matching / "coordination.csv",
        "--require-full-rerun")
    print(f"\nVerified the DaRA reproduction. Files are in {output}.")


if __name__ == "__main__":
    main()
