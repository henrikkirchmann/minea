#!/usr/bin/env python3
"""Rebuild the six held-out and thirty inner-validation DaRA candidate lists."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import tempfile
from pathlib import Path

import numpy as np
from scipy.spatial.distance import cdist

from features import DATASET, HERE, extract, load_observations


FINAL = "fusion_top10_candidates.csv.gz"
NESTED = "nested_scores.json.gz"
# Complete CC10 vocabulary from DaRA v1, including unobserved activities.
LABELS = [f"CL{code}" for code in range(124, 155)]
K = 15
WIDTH = 10


def squared_distances(block, train, test):
    block = np.asarray(block, dtype=np.float64)
    training = block[train]
    center = training.mean(axis=0)
    scale = training.std(axis=0)
    scale[scale < 1e-8] = 1
    return cdist((block[test] - center) / scale, (training - center) / scale,
                 metric="sqeuclidean")


def score(radio, motion, targets, train, test):
    distance = squared_distances(radio[:, :-1], train, test)
    distance += squared_distances(motion, train, test) * (342 / 54)
    distance *= 0.5
    distance += squared_distances(radio[:, -1:], train, test)
    nearest = np.argsort(distance, axis=1, kind="stable")[:, :K]
    neighbor_labels = targets[train][nearest]
    votes = np.zeros((len(test), len(LABELS)), dtype=np.int8)
    np.add.at(votes, (np.arange(len(test))[:, None], neighbor_labels), 1)
    ranked = np.argsort(-votes, axis=1, kind="stable")[:, :WIDTH]
    return ranked, 10 * np.take_along_axis(votes, ranked, axis=1).astype(np.int16) + 1


def predictions(rows, radio, motion):
    sessions = np.array([row.session for row in rows])
    targets = np.array([LABELS.index(row.label) for row in rows])
    unique = sorted(set(map(int, sessions)))
    final_codes = np.empty((len(rows), WIDTH), dtype=int)
    final_weights = np.empty_like(final_codes)
    nested = {}
    for held_out in unique:
        train = np.flatnonzero(sessions != held_out)
        test = np.flatnonzero(sessions == held_out)
        final_codes[test], final_weights[test] = score(radio, motion, targets, train, test)
        validation_lists = {}
        for validation in unique:
            if validation == held_out:
                continue
            fit = np.flatnonzero((sessions != held_out) & (sessions != validation))
            check = np.flatnonzero(sessions == validation)
            codes, weights = score(radio, motion, targets, fit, check)
            for i, indices, values in zip(check, codes, weights):
                validation_lists[i] = [[LABELS[j], int(w)] for j, w in zip(indices, values)]
        cases = {}
        for i in sorted(validation_lists, key=lambda i: rows[i].id):
            row = rows[i]
            cases.setdefault(row.case, {})[row.id] = validation_lists[i]
        nested[str(held_out)] = cases
        print(f"Scored session {held_out} and the five validation sessions", flush=True)

    for width in (1, 3, 10):
        hits = np.any(final_codes[:, :width] == targets[:, None], axis=1).sum()
        print(f"Ground truth in top {width}: {hits}/{len(rows)}")
    return final_codes, final_weights, nested


def write_scores(directory, rows, codes, weights, nested):
    # Fixed gzip headers make regenerated archives repeatable with the same zlib.
    with (directory / FINAL).open("wb") as raw, gzip.GzipFile(
            fileobj=raw, filename="", mode="wb", mtime=0) as compressed:
        with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("observation_id", "rank", "activity_id", "weight"))
            for i in sorted(range(len(rows)), key=lambda i: rows[i].id):
                for rank, (code, weight) in enumerate(zip(codes[i], weights[i]), 1):
                    writer.writerow((rows[i].id, rank, LABELS[code], int(weight)))
    with (directory / NESTED).open("wb") as raw, gzip.GzipFile(
            fileobj=raw, filename="", mode="wb", mtime=0) as compressed:
        with io.TextIOWrapper(compressed, encoding="utf-8") as stream:
            json.dump(nested, stream, separators=(",", ":"))


def content_hash(path):
    with gzip.open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").digest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DATASET / "raw",
                        help="Directory containing the original BLE and IMU ZIP archives")
    parser.add_argument("--log", type=Path, default=DATASET / "logs/dara_retrieval_gt.csv",
                        help="Ground truth CSV produced by datasets/dara-retrieval/export_log.py")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="Destination for the two regenerated candidate files")
    args = parser.parse_args()
    rows = load_observations(args.log)
    radio, motion = extract(args.raw_dir, rows)
    codes, weights, nested = predictions(rows, radio, motion)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output_dir) as temporary:
        staged = Path(temporary)
        write_scores(staged, rows, codes, weights, nested)
        for name in (FINAL, NESTED):
            if content_hash(staged / name) != content_hash(HERE / "reference" / name):
                raise ValueError(f"Regenerated {name} differs from the paper's recorded candidates")
        for name in (FINAL, NESTED):
            (staged / name).replace(args.output_dir / name)
    print(f"Verified both candidate files against the recorded experiment in {args.output_dir}")


if __name__ == "__main__":
    main()
