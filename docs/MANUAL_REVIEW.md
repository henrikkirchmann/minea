# Manual checks for the paper evaluation

This is a review procedure, **not a claim that human review has been completed**. Record the inspected case, event, template, condition, and job IDs; your calculation; its result; and any correction. A few examples establish understanding of those examples, not an estimated error rate for the full dataset.

**Ground truth (GT)** means the supplied reference activity annotations. **NA** means “No Annotation”; these intervals are excluded to simplify the matching task to annotated activity observations. Start with [sources and their roles](SOURCES.md) for the IKEA ASM paper and website, P3D scores and our earlier uncertain-log repository.

## 1. Trace a prepared observation and a GT insertion

Open [ground_truth.csv](../inputs/reference/full/ground_truth.csv) and the corresponding row in [uncertain_log.csv.gz](../inputs/reference/full/uncertain_log.csv.gz), matching by `event_id`. The [certain XES](../inputs/reference/full/ground_truth.xes) and [uncertain XES](../inputs/reference/full/uncertain_log.xes.gz) are alternative views of the same exports, not independent evidence.

For `case0:frames58-171`, verify case 0, start 58, exclusive end 171, duration 113, and GT **flip table top**. The uncertain row should contain exactly three scores, including **flip table top** at `0.7836140354650211`. Check the retained score sum plus `removed_na_score` and `discarded_non_na_score_mass` against the original-vector mass, allowing export rounding.

Then inspect `case0:frames752-780` in [candidate_replacements.csv](../inputs/reference/candidate_replacements.csv). The record reports replacing **pick up leg** (`0.012940730234341962`) with GT **other** (`0.00028126178325952163`), originally fifth among non-NA labels. Confirm the inserted label and unchanged score in the uncertain log. Do not describe this inclusion of GT as prediction accuracy.

The clean package contains derived records, not the original full score vectors. Independently checking original rankings or scores requires the pinned P3D GT-aligned CSV identified by [source_manifest.json](../source_manifest.json). Checking selection of P3D itself requires the ten pinned model exports; [model_selection.csv](../inputs/reference/model_selection.csv) preserves their recorded comparison. Clearly label a check based only on derived exports as such.

## 2. Recount the five active templates

Locate `pre_019`, `pre_036`, `pre_023`, `occ_031`, and `occ_021` in [constraints.json](../inputs/reference/full/constraints.json). The other templates remain for provenance and plan validation; they are not active in the sweep.

For `pre_019`, find the case-0 witness in [prerequisite_witnesses.csv](../inputs/reference/full/prerequisite_witnesses.csv): **pick up leg**, `case0:frames183-204`, supports **attach shelf to table**, `case0:frames2858-3151`. Locate both events in the GT log and check `204 ≤ 2858`. Repeat for a `pre_036` witness (**spin leg** before shelf attachment) and a `pre_023` witness (**pick up leg** before shelf pickup). For a selected trigger candidate, its encoded inequality is `x_trigger − sum(eligible earlier supporters) ≤ 0`; inspect all supporters, not only the one displayed witness.

For the occurrence bounds, independently count **spin leg** segments in case 58: the recorded maximum is eight. Count **pick up leg** segments in case 19: the recorded maximum is five. Compare with [occurrence_counts_by_case.csv](../inputs/reference/full/occurrence_counts_by_case.csv) and [occurrence_bounds.csv](../inputs/reference/full/occurrence_bounds.csv). Check an absent-activity case to understand the zero minimum. These count annotated segments, not physical legs or completed assembly tasks.

The rules hold on the same cohort used to discover them. Their support rankings in [support_rankings.json](../inputs/provenance/support_rankings.json) explain the fixed subset; they do not establish universal domain necessity or held-out validity.

## 3. Check one synthetic link and an ownership change

Compare the prepared [K2/C116 instance](../results/benchmark_sweep/preparation/instances/seed0_K2_C116.json.gz) with [K2/C58](../results/benchmark_sweep/preparation/instances/seed0_K2_C58.json.gz). Confirm identical candidates, score strings, ownership, and five templates. C58 adds the first 58 cross-case exclusions from [plan_seed0.json.gz](../inputs/provenance/plan_seed0.json.gz).

Choose `bridge:000000`. Find its two candidate IDs and case IDs; confirm different cases, a shared owner, coefficients +1, and upper bound 1. Under `gt_selected`, its left side must be at most one. Apply its saved witness by removing `removed_candidate_id` and adding `selected_candidate_id`: its left side must become two. The full claim that every other row remains satisfied requires checking those rows too; the offline verifier performs that complete check.

Compare K2/C58 with [K8/C58](../results/benchmark_sweep/preparation/instances/seed0_K8_C58.json.gz). Candidate semantics and numerical constraints should agree, while K2 owners equal K8 owners divided by four using integer division. This verifies the declared synthetic allocation, not a recovered distributed deployment.

## 4. Reconstruct the two figure panels

For the interface panel, inspect [construction.csv](../paper_output/ikea_sweep/construction.csv) and [overview_data.json](../paper_output/ikea_sweep/overview_data.json). At each C, take `maximum_component_interface` for K=2,4,8 and calculate their arithmetic mean. At C=116 it is 35; at C=1 it is approximately 2,346.7. Keep the largest-component quantity distinct from the total interface. At K=2, the total remains 2,331 while the largest component rises from 35 to 2,331.

For the number of cases in optimally solved components, inspect the compressed result under [distributed_K2_C58](../results/benchmark_sweep/jobs/distributed_K2_C58/) and the matching rows in [components.csv](../paper_output/ikea_sweep/components.csv). Sum `len(case_ids)` only for components with status `optimal`: 23 paired components give **46 cases**. The job is limited; an additional incumbent is not an additional optimal component. Recount the completed [distributed_K2_C116](../results/benchmark_sweep/jobs/distributed_K2_C116/) job, which contributes all 116 cases.

Compare your totals with [matching.csv](../paper_output/ikea_sweep/matching.csv) and the [overview figure](../paper_output/ikea_sweep/figures/ikea-overview.pdf). Inspect the `coverage_groups` records in `overview_data.json` before accepting a shared curve. There are eight actual central jobs, not a separate measured central baseline for each of 32 source/component conditions.

## 5. Record what your checks establish

Use the [recorded protocol](../results/benchmark_sweep/protocol.json) to confirm one seed, fresh method processes, the shared 300-second budget across sequential components, and the distributed 100,000-node cap. Do not interpret logical deliveries as network bytes or sequential time as deployed latency.

Hash checks bind saved content. Exact arithmetic checks feasibility and reported scores. Neither independently proves the origin of the raw data, authenticity of historical timing, or every recorded large-instance optimum. Record unresolved points explicitly alongside completed checks; see [EXPERIMENT.md](EXPERIMENT.md) for the study's scope.
