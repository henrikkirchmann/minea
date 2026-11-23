"""Rerun the four DaRA matching methods on one retrieval order or the full cohort."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import json
import os
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile, TemporaryDirectory

import baselines
import distributed
import model


HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
DEFAULT_LOG = HERE.parents[2] / "datasets/dara-retrieval/logs/dara_retrieval_gt.csv"


def run_case(task):
    case, intervals, candidates, templates, binary = task
    instance = model.build(case, intervals, candidates, templates)
    chosen, counters = distributed.solve(instance, binary)
    local, central = baselines.solve(instance)
    selections = []
    for (_, obs, _, _), label in zip(intervals, chosen, strict=True):
        if label != central[obs]:
            raise ValueError(f"MINEA and independent pooled solver disagree for {obs}")
        selections.append(dict(observation_id=obs, prediction=candidates[obs][0][1],
                               local=local[obs], minea=label, central=central[obs]))
    return selections, dict(case=case, **counters)


def write_csv(path, rows):
    with NamedTemporaryFile(mode="w", encoding="utf-8", newline="", dir=path.parent,
                            delete=False) as stream:
        staged = Path(stream.name)
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    staged.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="one case:concept:name; default: every order")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--candidates", type=Path,
                        default=STUDY / "classifier/reference/fusion_top10_candidates.csv.gz")
    parser.add_argument("--constraints", type=Path, default=STUDY / "constraints/rule_templates.json")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1, help="number of orders to solve in parallel")
    args = parser.parse_args()
    if not __debug__:
        parser.error("Run Python with its default input and encoder checks enabled")
    if args.workers < 1:
        parser.error("--workers must be positive")

    by_case = model.read_observations(args.log)
    candidates = model.read_candidates(args.candidates)
    expected = {obs for group in by_case.values() for _, obs, _, _ in group}
    if expected != set(candidates):
        parser.error("The log and candidate table must contain exactly the same observation IDs")
    if args.case and args.case not in by_case:
        parser.error(f"Unknown case ID: {args.case}")
    cases = [args.case] if args.case else sorted(by_case)
    templates = json.loads(args.constraints.read_text(encoding="utf-8"))

    with TemporaryDirectory(prefix="dara-matching-") as directory:
        binary = Path(directory) / "distributed"
        subprocess.run([os.environ.get("CXX", "c++"), "-O3", "-DNDEBUG", "-std=c++17",
                        str(HERE / "distributed.cc"), "-o", str(binary)], check=True)
        tasks = [(case, by_case[case], {obs: candidates[obs] for _, obs, _, _ in by_case[case]},
                  templates, binary) for case in cases]
        if args.workers == 1 or len(tasks) == 1:
            outcomes = list(map(run_case, tasks))
        else:
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                outcomes = list(pool.map(run_case, tasks))
    selections = [row for group, _ in outcomes for row in group]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "selections.csv", selections)
    write_csv(args.output_dir / "coordination.csv", [counters for _, counters in outcomes])
    unit = "order" if len(cases) == 1 else "orders"
    print(f"Matched {len(selections)} observations in {len(cases)} {unit}. Wrote {args.output_dir}.")


if __name__ == "__main__":
    main()
