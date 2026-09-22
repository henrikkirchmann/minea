#!/usr/bin/env python3
"""Regenerate the data-preparation guide and statistics from frozen local inputs."""

import argparse
import hashlib
import json
import os
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "docs/reviewer")
    args = parser.parse_args()
    output = args.output.resolve()
    from reviewer import log_stats, rule_stats, diagrams, plots, render, event_logs
    data, assets = output / "data", output / "assets"
    data.mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)
    logs = log_stats.generate(root, data)
    rules = rule_stats.generate(root, data)
    diagrams.generate(assets)
    plots.generate(root, assets, rules)
    event_logs.generate(root, output / "downloads")
    render.generate(root, output, logs, rules)
    # Links to evidence must still resolve when reviewing a fresh output folder.
    if output != root / "docs/reviewer":
        relative_root = Path(os.path.relpath(root, output)).as_posix()
        for path in [output / "index.html", *output.glob("*.md")]:
            content = path.read_text()
            for old, new in [("../../", relative_root + "/"),
                             ("../EXPERIMENT.md", relative_root + "/docs/EXPERIMENT.md"),
                             ("../MANUAL_REVIEW.md", relative_root + "/docs/MANUAL_REVIEW.md")]:
                content = content.replace('"' + old, '"' + new).replace('](' + old, '](' + new)
            path.write_text(content)
    source_files = [root / "review.py", *sorted((root / "reviewer").glob("*.py"))]
    provenance = {"scope": "Descriptive statistics recomputed from frozen local inputs. No data preparation, optimization or matching rerun.",
                  "producer_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}}
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    manifest = output / "artifact_manifest.json"
    files = {str(p.relative_to(output)): {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(output.rglob("*")) if p.is_file() and p != manifest}
    manifest.write_text(json.dumps({"files": files}, indent=2) + "\n")
    print(f"Data-preparation guide generated: {output / 'index.html'}")
    print(f"GitHub-readable guide: {output / 'README.md'}")


if __name__ == "__main__":
    main()
