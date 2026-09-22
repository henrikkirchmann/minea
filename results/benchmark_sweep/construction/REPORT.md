# Construction and matching benchmark

This is a sequential simulation of the paper's logical protocol, with exact rational scores. Elapsed times are single-machine observations; no distributed speedup is inferred.

The central baseline receives all candidates and given exclusions once. Both methods use the same constraints, component decomposition, exact solver, and case-based execution order. No GT warm start is supplied. Limits are separate, equal time budgets per method and condition; the distributed method additionally has its recorded search-node cap.

`optimal` means exact solver bounds closed and returned selections passed independent checks. `limited` and `unknown` do not establish an optimum. `not_run` denotes construction-only conditions.

| Condition | K | Components | Central | Distributed | Central completed components | Distributed completed components | Distributed visited / queried nodes |
|---|---:|---:|---|---|---:|---:|---:|
| seed0_K1_C116 | 1 | 116 | not_run | not_run | 0 | 0 | — / — |
| seed0_K1_C58 | 1 | 58 | not_run | not_run | 0 | 0 | — / — |
| seed0_K1_C29 | 1 | 29 | not_run | not_run | 0 | 0 | — / — |
| seed0_K1_C15 | 1 | 15 | not_run | not_run | 0 | 0 | — / — |
| seed0_K1_C8 | 1 | 8 | not_run | not_run | 0 | 0 | — / — |
| seed0_K1_C4 | 1 | 4 | not_run | not_run | 0 | 0 | — / — |
| seed0_K1_C2 | 1 | 2 | not_run | not_run | 0 | 0 | — / — |
| seed0_K1_C1 | 1 | 1 | not_run | not_run | 0 | 0 | — / — |
| seed0_K2_C116 | 2 | 116 | not_run | not_run | 0 | 0 | — / — |
| seed0_K2_C58 | 2 | 58 | not_run | not_run | 0 | 0 | — / — |
| seed0_K2_C29 | 2 | 29 | not_run | not_run | 0 | 0 | — / — |
| seed0_K2_C15 | 2 | 15 | not_run | not_run | 0 | 0 | — / — |
| seed0_K2_C8 | 2 | 8 | not_run | not_run | 0 | 0 | — / — |
| seed0_K2_C4 | 2 | 4 | not_run | not_run | 0 | 0 | — / — |
| seed0_K2_C2 | 2 | 2 | not_run | not_run | 0 | 0 | — / — |
| seed0_K2_C1 | 2 | 1 | not_run | not_run | 0 | 0 | — / — |
| seed0_K4_C116 | 4 | 116 | not_run | not_run | 0 | 0 | — / — |
| seed0_K4_C58 | 4 | 58 | not_run | not_run | 0 | 0 | — / — |
| seed0_K4_C29 | 4 | 29 | not_run | not_run | 0 | 0 | — / — |
| seed0_K4_C15 | 4 | 15 | not_run | not_run | 0 | 0 | — / — |
| seed0_K4_C8 | 4 | 8 | not_run | not_run | 0 | 0 | — / — |
| seed0_K4_C4 | 4 | 4 | not_run | not_run | 0 | 0 | — / — |
| seed0_K4_C2 | 4 | 2 | not_run | not_run | 0 | 0 | — / — |
| seed0_K4_C1 | 4 | 1 | not_run | not_run | 0 | 0 | — / — |
| seed0_K8_C116 | 8 | 116 | not_run | not_run | 0 | 0 | — / — |
| seed0_K8_C58 | 8 | 58 | not_run | not_run | 0 | 0 | — / — |
| seed0_K8_C29 | 8 | 29 | not_run | not_run | 0 | 0 | — / — |
| seed0_K8_C15 | 8 | 15 | not_run | not_run | 0 | 0 | — / — |
| seed0_K8_C8 | 8 | 8 | not_run | not_run | 0 | 0 | — / — |
| seed0_K8_C4 | 8 | 4 | not_run | not_run | 0 | 0 | — / — |
| seed0_K8_C2 | 8 | 2 | not_run | not_run | 0 | 0 | — / — |
| seed0_K8_C1 | 8 | 1 | not_run | not_run | 0 | 0 | — / — |

## Construction work

These columns have different units: logical deliveries, full candidate records, and coefficient terms. They are not byte counts and are not added into a communication-cost score.

| Condition | Owner registrations | Case edges | Election rank deliveries | Lookup deliveries | Shared rows | Shared coefficient terms | Central candidate records |
|---|---:|---:|---:|---:|---:|---:|---:|
| seed0_K1_C116 | 116 | 0 | 0 | 831 | 0 | 0 | 5568 |
| seed0_K1_C58 | 116 | 58 | 13340 | 831 | 0 | 0 | 5568 |
| seed0_K1_C29 | 116 | 87 | 20010 | 831 | 0 | 0 | 5568 |
| seed0_K1_C15 | 116 | 101 | 23230 | 831 | 0 | 0 | 5568 |
| seed0_K1_C8 | 116 | 108 | 24840 | 831 | 0 | 0 | 5568 |
| seed0_K1_C4 | 116 | 112 | 25760 | 831 | 0 | 0 | 5568 |
| seed0_K1_C2 | 116 | 114 | 26220 | 831 | 0 | 0 | 5568 |
| seed0_K1_C1 | 116 | 115 | 26450 | 831 | 0 | 0 | 5568 |
| seed0_K2_C116 | 232 | 0 | 0 | 1662 | 734 | 6850 | 5568 |
| seed0_K2_C58 | 232 | 58 | 13340 | 1662 | 734 | 6850 | 5568 |
| seed0_K2_C29 | 232 | 87 | 20010 | 1662 | 734 | 6850 | 5568 |
| seed0_K2_C15 | 232 | 101 | 23230 | 1662 | 734 | 6850 | 5568 |
| seed0_K2_C8 | 232 | 108 | 24840 | 1662 | 734 | 6850 | 5568 |
| seed0_K2_C4 | 232 | 112 | 25760 | 1662 | 734 | 6850 | 5568 |
| seed0_K2_C2 | 232 | 114 | 26220 | 1662 | 734 | 6850 | 5568 |
| seed0_K2_C1 | 232 | 115 | 26450 | 1662 | 734 | 6850 | 5568 |
| seed0_K4_C116 | 457 | 0 | 0 | 3288 | 758 | 6922 | 5568 |
| seed0_K4_C58 | 457 | 58 | 13340 | 3288 | 758 | 6922 | 5568 |
| seed0_K4_C29 | 457 | 87 | 20010 | 3288 | 758 | 6922 | 5568 |
| seed0_K4_C15 | 457 | 101 | 23230 | 3288 | 758 | 6922 | 5568 |
| seed0_K4_C8 | 457 | 108 | 24840 | 3288 | 758 | 6922 | 5568 |
| seed0_K4_C4 | 457 | 112 | 25760 | 3288 | 758 | 6922 | 5568 |
| seed0_K4_C2 | 457 | 114 | 26220 | 3288 | 758 | 6922 | 5568 |
| seed0_K4_C1 | 457 | 115 | 26450 | 3288 | 758 | 6922 | 5568 |
| seed0_K8_C116 | 808 | 0 | 0 | 5840 | 763 | 6936 | 5568 |
| seed0_K8_C58 | 808 | 58 | 13340 | 5840 | 763 | 6936 | 5568 |
| seed0_K8_C29 | 808 | 87 | 20010 | 5840 | 763 | 6936 | 5568 |
| seed0_K8_C15 | 808 | 101 | 23230 | 5840 | 763 | 6936 | 5568 |
| seed0_K8_C8 | 808 | 108 | 24840 | 5840 | 763 | 6936 | 5568 |
| seed0_K8_C4 | 808 | 112 | 25760 | 5840 | 763 | 6936 | 5568 |
| seed0_K8_C2 | 808 | 114 | 26220 | 5840 | 763 | 6936 | 5568 |
| seed0_K8_C1 | 808 | 115 | 26450 | 5840 | 763 | 6936 | 5568 |

## Rechecking

Read `protocol.json` for budgets and conventions, `counts.csv` for named counters, and each condition's compressed instance, construction, central rows, and solver outputs. A result's component records retain exact incumbent/bound fractions and termination reasons. Complete traces are included only when `--trace` was requested.

The offline verifier checks hashes, model equality, feasible selections, bounds consistency, and logical counts. It does not independently prove Z3's optimality conclusions from a formal proof artifact. Small exhaustive tests supply a separate optimality oracle.
