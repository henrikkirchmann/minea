# Every mined rule and what it means

Ground truth (GT) is the reference activity annotation supplied with IKEA ASM. Here, each case is an assembly recording and each observation is a continuous GT activity segment. Segments labelled NA (‘No Annotation’) have been removed to simplify matching to annotated activity observations. See [data sources and their roles](../../docs/SOURCES.md) for the original dataset, earlier uncertain-log conversion and citations.

The prepared GT contains **1856 segments in 116 cases**, covering 32 non-NA activities. Testing all 32 × 31 ordered distinct-label pairs gives **992 prerequisite tests**: 41 accepted, 951 rejected, and 0 with no trigger anywhere. There are also 32 singleton occurrence bounds. Only **three prerequisites and two bounds** are active in the paper sweep.

This catalogue was recomputed directly from the prepared GT by `reviewer/rule_stats.py`, without importing the production miner or invoking a solver. Every pair outcome, bound, catalogue membership, support ranking and selected candidate row was compared with frozen evidence. The input is still the same annotated cohort: this is an independent calculation, not independent data, human review, or validation on unseen cases.

## Prerequisite semantics and vacuity

For predecessor activity A and trigger B, require for **every** GT event b labelled B an event a in the **same case** with label A and `end(a) ≤ start(b)`. Intervals are half-open, so adjacent endpoints qualify. The predecessor need not be immediately previous, and one event can support multiple triggers. A pair is accepted only if it has at least one trigger in the population and no unsupported trigger.

A case with no B satisfies the statement vacuously. **None of the 41 accepted prerequisites has a trigger in all 116 cases**, although each holds throughout the cohort. All 32 labels occur somewhere, explaining the zero entirely vacuous pair tests. Accepted-rule case support ranges from 1 to 56 cases. Low support and furniture-specific absence are visible below; do not read 116 satisfied cases as 116 observed confirmations.

For candidates, each trigger candidate v becomes a row `x_v − Σ x_u ≤ 0`, where u ranges over **all** eligible same-case predecessor candidates. Without supporters the row is `x_v ≤ 0`. Support in the table concerns GT triggers, not candidate rows or classifier confidence.

## Why these five templates are active

The full set of 41 prerequisites and 32 occurrence bounds made preliminary distributed B&B reach the 300-second limit before completing the log, even with 116 independent cases and two sources. We therefore reduced the rule set for practical runtime, keeping all cases and candidates. The same five rules are fixed throughout the sweep and for both matching methods. The [selection protocol](../../inputs/provenance/selection_protocol.json) records this decision.

Within each family, rank by descending number of GT cases with the trigger/activity, then descending GT event count, then ascending template ID. Take three prerequisites (`pre_019`, `pre_036`, `pre_023`) and two bounds (`occ_031`, `occ_021`). The two shelf-attachment prerequisites tie at 56 cases/57 events and ID resolves their order; shelf pickup has 54 cases/57 events. Both selected bound activities occur in 87 cases; spin leg has 362 events and pick up leg has 338. Removing rules changes the matching problem. The results concern this smaller constraint model; five is not claimed to be the best rule count, and the reduction is not a speedup on the original problem or a selection validated on unseen cases.

At K=1, C=116, the five templates expand to **831 rows**: 599 trigger rows and 232 case-specific upper rows, including 7 empty upper rows. The 1856 observation-assignment rows are additional. Template counts and row counts must not be interchanged. Other K values preserve numerical rows; coupling adds the declared exclusions.

## All 41 accepted prerequisites

Kallax_Shelf_Drawer (29 cases)`Active` means used in the sweep. Rank is the support-selection rank. Cases use denominator 116; events are GT trigger occurrences. Vacuous cases have no trigger. Group support lists activated cases / retained cases for each furniture group: ; Lack_Coffee_Table (28 cases)`Active` means used in the sweep. Rank is the support-selection rank. Cases use denominator 116; events are GT trigger occurrences. Vacuous cases have no trigger. Group support lists activated cases / retained cases for each furniture group: ; Lack_Side_Table (30 cases)`Active` means used in the sweep. Rank is the support-selection rank. Cases use denominator 116; events are GT trigger occurrences. Vacuous cases have no trigger. Group support lists activated cases / retained cases for each furniture group: ; Lack_TV_Bench (29 cases). Candidate rows/supporters describe how that template would expand in the frozen candidates, including inactive templates. The supporter range includes zero when some trigger candidate is forbidden.

| ID | Active | Rank | Earlier predecessor → trigger | GT cases | GT events | Vacuous cases | Furniture-group support | Candidate rows; supporter range |
|---|---|---:|---|---:|---:|---:|---|---|
| pre_001 | no | 26 | align leg screw with table thread → flip shelf | 2/116 (1.7%) | 3 | 114 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 1/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 1/29 | 5; 11–13 |
| pre_002 | no | 30 | align leg screw with table thread → lay down shelf | 2/116 (1.7%) | 2 | 114 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 2/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 4; 10–13 |
| pre_003 | no | 20 | align leg screw with table thread → push table | 4/116 (3.4%) | 4 | 112 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 1/30; Lack_TV_Bench: 3/29 | 4; 3–8 |
| pre_004 | no | 35 | align side panel holes with front panel dowels → lay down side panel | 1/116 (0.9%) | 1 | 115 | Kallax_Shelf_Drawer: 1/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 1; 2–2 |
| pre_005 | no | 36 | attach drawer side panel → lay down side panel | 1/116 (0.9%) | 1 | 115 | Kallax_Shelf_Drawer: 1/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 1; 7–7 |
| pre_006 | no | 11 | attach drawer side panel → pick up pin | 27/116 (23.3%) | 45 | 89 | Kallax_Shelf_Drawer: 27/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 70; 2–16 |
| pre_007 | no | 27 | flip table top → flip shelf | 2/116 (1.7%) | 3 | 114 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 1/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 1/29 | 5; 0–2 |
| pre_008 | no | 31 | flip table top → lay down shelf | 2/116 (1.7%) | 2 | 114 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 2/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 4; 0–3 |
| pre_009 | no | 37 | lay down back panel → lay down side panel | 1/116 (0.9%) | 1 | 115 | Kallax_Shelf_Drawer: 1/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 1; 1–1 |
| pre_010 | no | 38 | lay down front panel → lay down side panel | 1/116 (0.9%) | 1 | 115 | Kallax_Shelf_Drawer: 1/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 1; 1–1 |
| pre_011 | no | 23 | pick up back panel → lay down back panel | 3/116 (2.6%) | 4 | 113 | Kallax_Shelf_Drawer: 3/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 4; 1–2 |
| pre_012 | no | 39 | pick up back panel → lay down side panel | 1/116 (0.9%) | 1 | 115 | Kallax_Shelf_Drawer: 1/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 1; 1–1 |
| pre_013 | no | 13 | pick up bottom panel → attach drawer back panel | 25/116 (21.6%) | 27 | 91 | Kallax_Shelf_Drawer: 25/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 81; 0–5 |
| pre_014 | no | 6 | pick up bottom panel → insert drawer pin | 29/116 (25.0%) | 48 | 87 | Kallax_Shelf_Drawer: 29/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 92; 1–5 |
| pre_015 | no | 19 | pick up bottom panel → lay down bottom panel | 8/116 (6.9%) | 8 | 108 | Kallax_Shelf_Drawer: 8/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 15; 1–5 |
| pre_016 | no | 17 | pick up bottom panel → position the drawer right side up | 20/116 (17.2%) | 20 | 96 | Kallax_Shelf_Drawer: 20/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 30; 1–5 |
| pre_017 | no | 9 | pick up bottom panel → slide bottom of drawer | 29/116 (25.0%) | 32 | 87 | Kallax_Shelf_Drawer: 29/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 55; 0–5 |
| pre_018 | no | 40 | pick up front panel → lay down side panel | 1/116 (0.9%) | 1 | 115 | Kallax_Shelf_Drawer: 1/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 1; 2–2 |
| pre_019 | yes | 1 | pick up leg → attach shelf to table | 56/116 (48.3%) | 57 | 60 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 28/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 28/29 | 167; 0–16 |
| pre_020 | no | 28 | pick up leg → flip shelf | 2/116 (1.7%) | 3 | 114 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 1/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 1/29 | 5; 8–9 |
| pre_021 | no | 25 | pick up leg → lay down leg | 3/116 (2.6%) | 3 | 113 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 2/28; Lack_Side_Table: 1/30; Lack_TV_Bench: 0/29 | 10; 0–11 |
| pre_022 | no | 32 | pick up leg → lay down shelf | 2/116 (1.7%) | 2 | 114 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 2/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 4; 4–14 |
| pre_023 | yes | 3 | pick up leg → pick up shelf | 54/116 (46.6%) | 57 | 62 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 26/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 28/29 | 265; 0–16 |
| pre_024 | no | 21 | pick up leg → push table | 4/116 (3.4%) | 4 | 112 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 1/30; Lack_TV_Bench: 3/29 | 4; 3–5 |
| pre_025 | no | 33 | pick up shelf → lay down shelf | 2/116 (1.7%) | 2 | 114 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 2/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 4; 1–4 |
| pre_026 | no | 16 | pick up side panel → align side panel holes with front panel dowels | 20/116 (17.2%) | 42 | 96 | Kallax_Shelf_Drawer: 20/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 125; 0–9 |
| pre_027 | no | 14 | pick up side panel → attach drawer back panel | 25/116 (21.6%) | 27 | 91 | Kallax_Shelf_Drawer: 25/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 81; 1–9 |
| pre_028 | no | 7 | pick up side panel → insert drawer pin | 29/116 (25.0%) | 48 | 87 | Kallax_Shelf_Drawer: 29/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 92; 2–9 |
| pre_029 | no | 24 | pick up side panel → lay down back panel | 3/116 (2.6%) | 4 | 113 | Kallax_Shelf_Drawer: 3/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 4; 2–7 |
| pre_030 | no | 41 | pick up side panel → lay down side panel | 1/116 (0.9%) | 1 | 115 | Kallax_Shelf_Drawer: 1/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 1; 5–5 |
| pre_031 | no | 12 | pick up side panel → pick up pin | 27/116 (23.3%) | 45 | 89 | Kallax_Shelf_Drawer: 27/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 70; 2–9 |
| pre_032 | no | 18 | pick up side panel → position the drawer right side up | 20/116 (17.2%) | 20 | 96 | Kallax_Shelf_Drawer: 20/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 30; 2–9 |
| pre_033 | no | 10 | pick up side panel → slide bottom of drawer | 29/116 (25.0%) | 32 | 87 | Kallax_Shelf_Drawer: 29/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 55; 0–8 |
| pre_034 | no | 15 | slide bottom of drawer → attach drawer back panel | 25/116 (21.6%) | 27 | 91 | Kallax_Shelf_Drawer: 25/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 81; 0–4 |
| pre_035 | no | 8 | slide bottom of drawer → insert drawer pin | 29/116 (25.0%) | 48 | 87 | Kallax_Shelf_Drawer: 29/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 92; 1–4 |
| pre_036 | yes | 2 | spin leg → attach shelf to table | 56/116 (48.3%) | 57 | 60 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 28/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 28/29 | 167; 0–17 |
| pre_037 | no | 29 | spin leg → flip shelf | 2/116 (1.7%) | 3 | 114 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 1/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 1/29 | 5; 9–11 |
| pre_038 | no | 34 | spin leg → lay down shelf | 2/116 (1.7%) | 2 | 114 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 2/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 0/29 | 4; 8–11 |
| pre_039 | no | 4 | spin leg → pick up shelf | 54/116 (46.6%) | 57 | 62 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 26/28; Lack_Side_Table: 0/30; Lack_TV_Bench: 28/29 | 265; 0–17 |
| pre_040 | no | 22 | spin leg → push table | 4/116 (3.4%) | 4 | 112 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 0/28; Lack_Side_Table: 1/30; Lack_TV_Bench: 3/29 | 4; 1–6 |
| pre_041 | no | 5 | spin leg → tighten leg | 41/116 (35.3%) | 85 | 75 | Kallax_Shelf_Drawer: 0/29; Lack_Coffee_Table: 14/28; Lack_Side_Table: 10/30; Lack_TV_Bench: 17/29 | 375; 0–16 |

For a weak-support example, `pre_004` (**align side panel holes with front panel dowels → lay down side panel**) has only one trigger in one case; the other 115 cases are vacuous. Group-wise support makes clear that some activity pairs concern only a furniture subset. Whole-cohort validity does not supply observations from the groups where the trigger never occurs.

### Selected candidate-row expansion

GT trigger counts and proposed candidate-trigger counts differ because non-GT alternatives can also propose a trigger. The following rows are checked directly against the frozen K1/C116 central encoding. The example is one complete literal row; all listed predecessor IDs have coefficient −1, the trigger ID has +1, and the right-hand side is zero.

| Template | Instantiated trigger rows | Rows with no supporter | Example trigger | Eligible supporter IDs |
|---|---:|---:|---|---|
| pre_019 | 167 | 13 | v000057 | v000001, v000004, v000007, v000010, v000017, v000019, v000022, v000026, v000028, v000031, v000046, v000049 |
| pre_023 | 265 | 29 | v000055 | v000001, v000004, v000007, v000010, v000017, v000019, v000022, v000026, v000028, v000031, v000046, v000049 |
| pre_036 | 167 | 7 | v000057 | v000008, v000011, v000014, v000020, v000023, v000029, v000032, v000034, v000038, v000041, v000043, v000047, v000050, v000053, v000056 |

No-supporter counts are counts of rows, not necessarily distinct candidate IDs: the same shelf-attachment candidate can trigger both prerequisites.

## All 32 occurrence bounds

For each activity A, count its GT segments in every retained case, including zero counts; the minimum and maximum become the lower and upper bound. **Every lower bound is zero.** The current encoder omits these vacuous lower rows and emits one upper row per case, including rows with no candidate terms. These are observed segment-count extrema, not numbers of physical parts or laws for unseen assemblies.

`Potential excess cases` counts cases whose distinct observations admitting that activity exceed the bound. Such a choice respects observation assignment alone; other templates can prevent it. This column is not a full-model feasibility or nonredundancy proof. Maximum-witness IDs identify cases attaining the GT maximum.

| ID | Active | Rank | Activity | GT lower–upper | GT support cases | GT events | Zero cases | Maximum-witness cases | Potential excess cases |
|---|---|---:|---|---|---:|---:|---:|---|---:|
| occ_001 | no | 4 | align leg screw with table thread | 0–5 | 72/116 | 283 | 44 | 3, 42, 43 | 98 |
| occ_002 | no | 18 | align side panel holes with front panel dowels | 0–4 | 20/116 | 42 | 96 | 113, 91 | 13 |
| occ_003 | no | 16 | attach drawer back panel | 0–2 | 25/116 | 27 | 91 | 113, 94 | 13 |
| occ_004 | no | 14 | attach drawer side panel | 0–4 | 28/116 | 61 | 88 | 108, 91 | 8 |
| occ_005 | no | 5 | attach shelf to table | 0–2 | 56/116 | 57 | 60 | 24 | 28 |
| occ_006 | no | 29 | flip shelf | 0–2 | 2/116 | 3 | 114 | 29 | 0 |
| occ_007 | no | 3 | flip table | 0–3 | 84/116 | 88 | 32 | 34 | 34 |
| occ_008 | no | 8 | flip table top | 0–1 | 36/116 | 36 | 80 | 0, 12, 16, 18, 20, 22, 24, 25, 26, 29, 3, 30, 31, 34, 39, 4, 40, 41, 42, 45, 47, 5, 52, 54, 56, 58, 6, 64, 7, 70, 72, 73, 76, 78, 83, 84 | 17 |
| occ_009 | no | 11 | insert drawer pin | 0–3 | 29/116 | 48 | 87 | 98 | 12 |
| occ_010 | no | 27 | lay down back panel | 0–2 | 3/116 | 4 | 113 | 91 | 0 |
| occ_011 | no | 22 | lay down bottom panel | 0–1 | 8/116 | 8 | 108 | 107, 109, 112, 116, 90, 91, 96, 97 | 1 |
| occ_012 | no | 23 | lay down front panel | 0–1 | 8/116 | 8 | 108 | 100, 101, 103, 106, 91, 92, 93, 99 | 0 |
| occ_013 | no | 28 | lay down leg | 0–1 | 3/116 | 3 | 113 | 29, 51, 61 | 1 |
| occ_014 | no | 30 | lay down shelf | 0–1 | 2/116 | 2 | 114 | 29, 41 | 0 |
| occ_015 | no | 31 | lay down side panel | 0–1 | 1/116 | 1 | 115 | 91 | 0 |
| occ_016 | no | 25 | lay down table top | 0–1 | 6/116 | 6 | 110 | 3, 53, 60, 7, 70, 9 | 0 |
| occ_017 | no | 20 | other | 0–3 | 16/116 | 23 | 100 | 0, 94 | 3 |
| occ_018 | no | 17 | pick up back panel | 0–3 | 23/116 | 32 | 93 | 91, 94 | 1 |
| occ_019 | no | 12 | pick up bottom panel | 0–3 | 29/116 | 33 | 87 | 91 | 5 |
| occ_020 | no | 21 | pick up front panel | 0–2 | 12/116 | 13 | 104 | 91 | 0 |
| occ_021 | yes | 2 | pick up leg | 0–5 | 87/116 | 338 | 29 | 19, 29, 39, 61, 9 | 81 |
| occ_022 | no | 15 | pick up pin | 0–3 | 27/116 | 45 | 89 | 98 | 6 |
| occ_023 | no | 6 | pick up shelf | 0–2 | 54/116 | 57 | 62 | 24, 34, 53 | 48 |
| occ_024 | no | 10 | pick up side panel | 0–6 | 29/116 | 65 | 87 | 91 | 3 |
| occ_025 | no | 24 | pick up table top | 0–1 | 8/116 | 8 | 108 | 19, 3, 60, 70, 76, 77, 84, 9 | 0 |
| occ_026 | no | 19 | position the drawer right side up | 0–1 | 20/116 | 20 | 96 | 100, 101, 102, 103, 104, 105, 106, 108, 110, 111, 113, 114, 115, 88, 91, 92, 93, 94, 95, 99 | 4 |
| occ_027 | no | 26 | push table | 0–1 | 4/116 | 4 | 112 | 15, 17, 5, 64 | 0 |
| occ_028 | no | 32 | push table top | 0–1 | 1/116 | 1 | 115 | 49 | 0 |
| occ_029 | no | 9 | rotate table | 0–5 | 34/116 | 61 | 82 | 43, 7 | 7 |
| occ_030 | no | 13 | slide bottom of drawer | 0–2 | 29/116 | 32 | 87 | 106, 113, 91 | 5 |
| occ_031 | yes | 1 | spin leg | 0–8 | 87/116 | 362 | 29 | 58 | 75 |
| occ_032 | no | 7 | tighten leg | 0–5 | 41/116 | 85 | 75 | 43 | 25 |

## Concrete checks

Accepted example `pre_019`: event `case0:frames183-204` (**pick up leg**) ends at 204; `case0:frames2858-3151` (**attach shelf to table**) starts at 2858. Both belong to case 0, so the temporal prerequisite is satisfied. This example alone does not establish the all-event claim; the recount checks every trigger.

Rejected pair **align leg screw with table thread → align side panel holes with front panel dowels**: `case100:frames286-496` in case 100 starts at 286. The case contains 0 predecessor events, so this trigger has no eligible supporter. Across the cohort this pair has 42 unsupported triggers in 20 cases. All rejected pairs and their first counterexamples are included below.

## Data and verification boundaries

- [All rule statistics and source hashes](data/rule_stats.json): full group denominators, example candidate rows, supporter-cardinality distributions and witness IDs.
- [41 prerequisites](data/prerequisites.csv) and [32 bounds](data/occurrence_bounds.csv): sortable complete catalogues with the active flag.
- [All 992 prerequisite tests](data/prerequisite_tests.csv): acceptance, activation, vacuity, violation counts, reasons and counterexamples.
- [Experimental scope](../EXPERIMENT.md) and [manual review procedure](../MANUAL_REVIEW.md).

Scores/candidate labels use GT assistance, the rules use in-sample GT, and furniture groups are descriptive strata rather than independent validation sets. No rule is described as universal because it holds in these traces. No new optimizer run or algorithm change is part of this report.
