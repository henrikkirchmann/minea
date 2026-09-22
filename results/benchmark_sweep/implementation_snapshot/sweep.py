#!/usr/bin/env python3
"""Run the fixed reduced-model grid with one fresh process per matcher.

Central optimization is measured once per component setting at K=1. Equal
numerical fingerprints justify using that reference at other K; upload counts
are still constructed separately for every K. No matching algorithm is changed.
"""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import sys
import time

from benchmark import (check_comparison, check_matching_result, flatten_counts,
                       read_json, run_condition, upload_centrally, write_json,
                       write_report)

ROOT = Path(__file__).resolve().parent
SOURCES = [1, 2, 4, 8]
COMPONENTS = [116, 58, 29, 15, 8, 4, 2, 1]


def utc():
    return datetime.now(timezone.utc).isoformat()


def manifest(folder):
    files = {p.relative_to(folder).as_posix(): {
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p != folder / "artifact_manifest.json"}
    write_json(folder / "artifact_manifest.json", {"files": files})


def jobs():
    records = []

    def add(method, source, count):
        identifier = (f"central_C{count}" if method == "central"
                      else f"distributed_K{source}_C{count}")
        if not any(r["id"] == identifier for r in records):
            records.append({"id": identifier, "method": method,
                            "condition": f"seed0_K{source}_C{count}"})

    # The merged check is part of the grid, not a discarded pilot.
    add("central", 1, 58)
    add("distributed", 2, 58)
    for count in COMPONENTS:
        add("central", 1, count)
        for source in SOURCES:
            add("distributed", source, count)
    return records


def prepare(output):
    from sweep_instances import prepare_sweep
    output.mkdir(parents=True)
    prepare_sweep(output / "preparation")
    producers = [ROOT / "sweep.py", ROOT / "sweep_instances.py", ROOT / "benchmark.py",
                 ROOT / "requirements.txt", *sorted((ROOT / "minea_ikea").glob("*.py"))]
    hashes = {}
    for source in producers:
        relative = source.relative_to(ROOT)
        target = output / "implementation_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[relative.as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
    protocol = {
        "created_utc": utc(), "grid": {"sources": SOURCES, "components": COMPONENTS, "seeds": [0]},
        "time_limit_seconds": 300, "node_limit": 100000,
        "worker_watchdog_seconds": 390, "jobs": jobs(), "producer_sha256": hashes,
        "python": sys.version, "platform": platform.platform(),
        "execution": "Sequential jobs; each matching method has its own fresh Python process and solver context. Construction and audits are outside matching time. No network or parallel speedup claim.",
        "central_reference": "One actual central run for each C at K=1, reused only after verifying identical numerical models across K. These are eight measurements, not 32 independent baseline runs. Each K retains its own measured construction and central-upload logical counts.",
        "merged_check": "The first central C58 and distributed K2,C58 jobs are retained grid observations. A valid solver limit does not change the remaining grid, template selection, budgets, or traversal.",
        "candidate_and_constraint_policy": "The fixed prepared candidates, exact scores and five GT-support-selected templates from the published reduced retry; original seed-0 full merge plan and ownership preserved.",
        "limits": "Each matching job receives 300 seconds. Distributed jobs additionally receive 100000 nodes. Cooperative limits may overrun briefly. An outer 390-second watchdog records an execution error rather than fabricating a solver result.",
        "replication": "One fixed seed and one run per matching job. Descriptive logical-work and completion study, without statistical or timing-speedup claims.",
        "initial_incumbent": "None. GT is checked separately and never supplied as a warm start.",
    }
    write_json(output / "protocol.json", protocol)
    study = output / "construction"
    study.mkdir()
    write_json(study / "protocol.json", {
        "created_utc": utc(), "arguments": {"sources": SOURCES, "components": COMPONENTS,
            "seeds": [0], "trace": False, "construction_only": True},
        "execution": protocol["execution"], "scope": "Construction only; matcher outputs live in the parent jobs directory."})
    for source in [ROOT / "benchmark.py", ROOT / "requirements.txt", *sorted((ROOT / "minea_ikea").glob("*.py"))]:
        target = study / "implementation_snapshot" / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    summaries, counts = [], []
    for source in SOURCES:
        for count in COMPONENTS:
            name = f"seed0_K{source}_C{count}"
            instance = read_json(output / "preparation" / "instances" / f"{name}.json.gz")
            summary = run_condition(instance, study / name, construction_only=True)
            summary["condition"] = name
            summaries.append(summary)
            for stage, values in {
                "construction": read_json(study / name / "construction.json.gz")["metrics"],
                "central_upload": read_json(study / name / "central_upload.json")}.items():
                counts.extend({"condition": name, "stage": stage, "metric": metric, "value": value}
                              for metric, value in flatten_counts(values))
    write_json(study / "summary.json", summaries)
    with (study / "counts.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["condition", "stage", "metric", "value"])
        writer.writeheader()
        writer.writerows(counts)
    write_report(study, summaries)
    manifest(study)
    from verify_benchmark import verify_study
    write_json(output / "construction_verification.json", verify_study(study))
    print("All 32 construction conditions independently verified", flush=True)
    return protocol


def assert_producers(protocol):
    for relative, digest in protocol["producer_sha256"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Producer changed during sweep: {relative}")


def worker(output, identifier):
    protocol = read_json(output / "protocol.json")
    assert_producers(protocol)
    job = next(j for j in protocol["jobs"] if j["id"] == identifier)
    folder = output / "jobs" / identifier
    started = time.perf_counter()
    began = utc()
    try:
        condition = output / "construction" / job["condition"]
        instance = read_json(condition / "instance.json.gz")
        construction = read_json(condition / "construction.json.gz")
        rows = read_json(condition / "central_rows.json.gz")
        from minea_ikea.matching import match_central, match_distributed
        from minea_ikea.reference import components_from_rows
        if job["method"] == "central":
            uploaded, _ = upload_centrally(instance)
            result = match_central(uploaded, rows=rows,
                components=components_from_rows(uploaded, rows),
                time_limit=protocol["time_limit_seconds"], trace=False)
        else:
            result = match_distributed(instance, construction,
                time_limit=protocol["time_limit_seconds"], node_limit=protocol["node_limit"], trace=False)
        checks = check_matching_result(instance, rows, result)
        write_json(folder / "result.json.gz", result)
        write_json(folder / "job.json", {**job, "execution_status": "complete", "returncode": 0,
            "started_utc": began, "completed_utc": utc(), "checks": checks})
    finally:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        factor = 1 if sys.platform == "darwin" else 1024
        write_json(folder / "resources.json", {
            "measurement": "resource.getrusage(RUSAGE_SELF)", "platform": sys.platform,
            "peak_rss_raw": usage.ru_maxrss,
            "peak_rss_raw_unit": "bytes" if sys.platform == "darwin" else "KiB",
            "peak_rss_bytes": int(usage.ru_maxrss * factor),
            "user_cpu_seconds": usage.ru_utime, "system_cpu_seconds": usage.ru_stime,
            "elapsed_seconds": time.perf_counter() - started,
            "scope": "One fresh method process: input loading, matching, feasibility audit and result serialization; excludes construction, other jobs and other applications. Matching elapsed_seconds is recorded separately in result.json.gz."})


def run(output, protocol):
    completed = []
    for index, job in enumerate(protocol["jobs"], 1):
        assert_producers(protocol)
        folder = output / "jobs" / job["id"]
        record_path = folder / "job.json"
        if record_path.exists():
            record = read_json(record_path)
            if record["execution_status"] != "complete":
                raise ValueError(f"Previous job execution error requires investigation: {job['id']}")
        else:
            folder.mkdir(parents=True, exist_ok=False)
            print(f"[{index}/40] Starting {job['id']} ({job['condition']})", flush=True)
            began = utc()
            with (folder / "run.log").open("w") as log:
                try:
                    process = subprocess.run([sys.executable, "-u", str(ROOT / "sweep.py"),
                        "--output", str(output), "--worker-job", job["id"]], cwd=ROOT,
                        stdout=log, stderr=subprocess.STDOUT,
                        timeout=protocol["worker_watchdog_seconds"])
                    error = None if process.returncode == 0 else f"Worker exit {process.returncode}"
                    returncode = process.returncode
                except subprocess.TimeoutExpired:
                    error, returncode = "Outer worker watchdog expired", None
            if error:
                write_json(record_path, {**job, "execution_status": "execution_error", "returncode": returncode,
                    "started_utc": began, "completed_utc": utc(), "error": error})
                manifest(output)
                raise ValueError(f"{job['id']}: {error}; retained artifacts require review")
            record = read_json(record_path)
        result = read_json(folder / "result.json.gz")
        count = int(job["condition"].split("_C")[1])
        if job["method"] == "distributed":
            central = read_json(output / "jobs" / f"central_C{count}" / "result.json.gz")
            check_comparison(central, result)
            central_parts = {tuple(c["case_ids"]): c for c in central["components"]}
            for component in result["components"]:
                check_comparison(central_parts[tuple(component["case_ids"])], component)
        optimal = sum(c["status"] == "optimal" for c in result["components"])
        completed.append(job["id"])
        write_json(output / "progress.json", {"updated_utc": utc(), "completed": completed,
            "total_jobs": len(protocol["jobs"]), "last_job": job["id"], "last_status": result["status"]})
        print(f"[{index}/40] {job['id']}: {result['status']}, {optimal}/{count} optimal components, "
              f"{result['elapsed_seconds']:.2f}s", flush=True)
    manifest(output)
    print("All 40 matching jobs finished; ready for independent sweep verification", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--worker-job", help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.worker_job:
        worker(output, args.worker_job)
        return
    if args.resume:
        protocol = read_json(output / "protocol.json")
    else:
        if output.exists():
            parser.error("Choose a fresh output directory, or --resume an existing sweep")
        protocol = prepare(output)
    if args.prepare_only:
        manifest(output)
    else:
        run(output, protocol)


if __name__ == "__main__":
    main()
