# Coordination rounds, local solves and runtime

Each retrieval order has its own coordinator. The paper used a conflict-directed depth-first search with an exact, warehouse-specific local solver. The coordinator starts with one round querying all participating sources. When a later branch needs an updated local solution, it queries the one source that owns the affected candidate. A repeated query counts as a round even if the source can reuse a cached answer. A cache miss counts as a local solve. [Matching implementation and rerun instructions](../matching/README.md)

From the repository root, verify the reported statistics using Python's standard library.

```sh
python3 experiments/dara/coordination/verify.py
```

The 53 per-order records give median counts of **1,177 rounds and 227 local solves**. On the recorded Apple M1 Pro run, the median elapsed time was 0.040 s and 49 orders finished in under one second. The slowest order, `session06_order2904_execution02`, used 3,194,162 local solves and took 24.211 s (24.2 s in the paper). The records come from the same complete, uncapped searches that produced the distributed selections. [Recorded per-order measurements](recorded.csv)

| Column | Meaning |
|---|---|
| `case` | Retrieval order execution ID shared with the ground truth log. |
| `visited_nodes` | Search nodes counted, including the root and children pruned before querying a source. |
| `queried_nodes` | Coordination rounds, including the initial round and later requests served from cache. |
| `source_cache_misses` | Calls that require the source to solve its local matching problem. |
| `compared_tied_bounds` | Comparisons needed when a node bound ties the incumbent on total score and number of first choices. |
| `private_handle_comparisons` | Source-level comparisons used to resolve those ties in chronological observation order. |
| `seconds` | Per-order wall time around the native matching subprocess, including startup and input/output. Feature scoring and model construction take place beforehand. The replay uses one computer and has no network latency. |

After running matching, point the verifier at the resulting coordination table. For example, if the matching output directory is `reproduced/dara/matching`, use the following command.

```sh
python3 experiments/dara/coordination/verify.py --coordination reproduced/dara/matching/coordination.csv
```

The verifier compares all five integer counters for each supplied case and prints the wall-time summary for your machine. A one-order run checks that case. Add `--require-full-rerun` to require measurements for all 53 orders. The comparison uses exact equality for search counters. Wall times depend on hardware, compiler and concurrent system load.
