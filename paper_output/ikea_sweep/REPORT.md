# Fixed-profile IKEA source/component sweep

The full grid uses 116 cases, 1,856 observations and 5,568 candidates throughout. The five GT-supported templates, original scores, full merge hierarchy, source assignment and matching algorithms are fixed. K changes nested ownership; C adds a prefix of source-local, GT-feasible, independently witnessed cross-case exclusions.

There are 32 distributed conditions and eight actual centralized reference measurements. Central results are reused across K only after verifying identical numerical models; they are not independent repetitions. Every matching method runs in a fresh process, with 300 seconds and a 100,000-node distributed cap. This is one seed and one run per job, on an interactive M1 Pro host with 16 GB RAM. Timings are descriptive and do not estimate deployed latency, communication overhead or parallel speedup.

All 32 constructed models passed the independent row checks. Distributed matching completed 11/32 configurations optimally; the central reference completed 8/8 numerical models. Completed comparison pairs agree in exact objective. Every limited run remains in the tables and Figure 3 coverage summary.

| K | C | Distributed status | Optimal components | Cases in optimal components | Complete matching | Nodes visited | Source solve requests | Seconds |
|---:|---:|---|---:|---:|---|---:|---:|---:|
| 1 | 116 | optimal | 116/116 | 116/116 | yes | 116 | 116 | 2.03 |
| 1 | 58 | optimal | 58/58 | 116/116 | yes | 58 | 58 | 1.98 |
| 1 | 29 | optimal | 29/29 | 116/116 | yes | 29 | 29 | 2.17 |
| 1 | 15 | optimal | 15/15 | 116/116 | yes | 15 | 15 | 2.53 |
| 1 | 8 | optimal | 8/8 | 116/116 | yes | 8 | 8 | 3.34 |
| 1 | 4 | optimal | 4/4 | 116/116 | yes | 4 | 4 | 5.92 |
| 1 | 2 | optimal | 2/2 | 116/116 | yes | 2 | 2 | 12.65 |
| 1 | 1 | optimal | 1/1 | 116/116 | yes | 1 | 1 | 26.69 |
| 2 | 116 | optimal | 116/116 | 116/116 | yes | 5308 | 9350 | 91.91 |
| 2 | 58 | limited | 23/58 | 46/116 | no | 7282 | 13106 | 300.01 |
| 2 | 29 | limited | 2/29 | 8/116 | no | 3854 | 6888 | 300.02 |
| 2 | 15 | limited | 0/15 | 0/116 | no | 1587 | 2770 | 300.02 |
| 2 | 8 | limited | 0/8 | 0/116 | no | 802 | 1392 | 300.03 |
| 2 | 4 | limited | 0/4 | 0/116 | no | 601 | 1048 | 300.01 |
| 2 | 2 | limited | 0/2 | 0/116 | no | 285 | 570 | 300.02 |
| 2 | 1 | limited | 0/1 | 0/116 | no | 63 | 126 | 300.09 |
| 4 | 116 | optimal | 116/116 | 116/116 | yes | 5400 | 18558 | 82.25 |
| 4 | 58 | limited | 23/58 | 46/116 | no | 8375 | 30060 | 300.01 |
| 4 | 29 | limited | 2/29 | 8/116 | no | 4557 | 16344 | 300.01 |
| 4 | 15 | limited | 0/15 | 0/116 | no | 1965 | 6916 | 300.01 |
| 4 | 8 | limited | 0/8 | 0/116 | no | 1015 | 3556 | 300.04 |
| 4 | 4 | limited | 0/4 | 0/116 | no | 683 | 2360 | 300.06 |
| 4 | 2 | limited | 0/2 | 0/116 | no | 363 | 1452 | 300.03 |
| 4 | 1 | limited | 0/1 | 0/116 | no | 113 | 452 | 300.16 |
| 8 | 116 | optimal | 116/116 | 116/116 | yes | 5434 | 34012 | 83.75 |
| 8 | 58 | limited | 23/58 | 46/116 | no | 9018 | 64521 | 300.01 |
| 8 | 29 | limited | 2/29 | 8/116 | no | 5054 | 36496 | 300.02 |
| 8 | 15 | limited | 0/15 | 0/116 | no | 2214 | 15568 | 300.02 |
| 8 | 8 | limited | 0/8 | 0/116 | no | 1175 | 8280 | 300.01 |
| 8 | 4 | limited | 0/4 | 0/116 | no | 724 | 5024 | 300.04 |
| 8 | 2 | limited | 0/2 | 0/116 | no | 385 | 3080 | 300.02 |
| 8 | 1 | limited | 0/1 | 0/116 | no | 150 | 1200 | 300.03 |

## Actual centralized measurements

| C | Status | Optimal components | Complete matching | Seconds |
|---:|---|---:|---|---:|
| 116 | optimal | 116/116 | yes | 1.98 |
| 58 | optimal | 58/58 | yes | 2.06 |
| 29 | optimal | 29/29 | yes | 2.17 |
| 15 | optimal | 15/15 | yes | 2.54 |
| 8 | optimal | 8/8 | yes | 3.31 |
| 4 | optimal | 4/4 | yes | 5.98 |
| 2 | optimal | 2/2 | yes | 12.77 |
| 1 | optimal | 1/1 | yes | 26.72 |

## Interpretation and reproducibility

Figure 3(a) summarizes the largest component interface by the arithmetic mean across two, four and eight sources. These are source-count settings, not repeated experimental trials; their values differ by at most 28 variables at each recorded component count. The central and one-source reference has no inter-source matching interface. Figure 3(b) groups only exactly equal case coverage and completion status; runtime and search work can differ. All plotted markers are filled, and the saved tables retain termination status. Counts in limited runs are work observed before stopping, not total work to an optimum. An optimal component covers every case in it; the figure reports the number of covered cases out of 116, avoiding changing component-count denominators. Coverage is specific to sequential case-ID order and the shared whole-run budget: a hard early component can leave easier later components unvisited. A component incumbent does not constitute a complete event log. Missing global incumbents or infinite bounds are not zero-valued solutions.

Construction reports logical role-to-role deliveries, including co-located roles. Candidate records, coefficient terms and protocol requests have different meanings and are not combined into a byte-cost score. The central baseline uploads every candidate and its original score; its upload counts are recorded for each K in construction.csv.

The candidate set uses GT boundaries and inserts a missing GT label by replacing the third-ranked candidate. Templates were mined on the same cohort and the reduced profile was chosen after a full-model calibration failed to complete within its budget. These are exploratory controlled protocol experiments, not held-out recognition accuracy or a representative deployment workload.

Offline verification: PASS; 40 matching jobs, 932 within-model component comparisons. Saved large-instance optimality conclusions still rely on Z3; exact returned-selection feasibility and objective sums are independently checked. No full node transcripts were requested.

`construction.csv`, `matching.csv`, `components.csv`, `summary.json`, `verification.json`, and `overview_data.json` retain the reported evidence. Only the current paper figure is exported: `figures/ikea-overview.pdf` and its editable PGF source. All tables and figure files are regenerated from the unchanged saved sweep; the original producer snapshots remain with that sweep. The component table records execution order, case IDs, termination reasons, incumbents and bounds; matching.csv separately counts unstarted components and their cases. Regenerate with `python3 analyze_sweep.py --input results/benchmark_sweep --output paper_output/ikea_sweep` (install requirements-figures.txt; TeX Live required).
