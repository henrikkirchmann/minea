# Earlier IKEA ASM evaluation records

This directory archives the September 2026 inventory and validation of the IKEA ASM evaluation. Its hashes and test outputs describe that snapshot. To reproduce the current DaRA warehouse retrieval results, follow the [DaRA experiment guide](../experiments/dara/README.md).

| File | What it establishes |
| --- | --- |
| [release_validation.json](release_validation.json) | September 2026 checks of tests, prepared inputs, saved results, figures, links and file integrity. |
| [release_tests.log](release_tests.log) | Output of the automated tests for that snapshot. |
| [file_manifest.json](file_manifest.json) | Purpose, byte size and SHA-256 of each file in the IKEA ASM snapshot, excluding the inventory itself. |
| [extraction.json](extraction.json) | Original paths and hashes of files copied when the IKEA ASM package was assembled. |
| [paper_sources.json](paper_sources.json) | The manuscript and figure versions used when the standalone folder was assembled. |
| [recorded_endpoint_audit.json](recorded_endpoint_audit.json) | Comparison with the recorded code and checks of all 115 synthetic exclusions and their stored single replacements. |
| [standard_event_log_validation.json](standard_event_log_validation.json) | Actual PM4Py import checks of the four downloadable event logs, including every observation, interval and score payload. |

The [recorded sweep](../results/benchmark_sweep/) retains its original
manifests, implementation snapshots and all 40 matching jobs unchanged.
Its verifier checks the candidate models, encoded rows, feasible selections,
scores, bounds and accounting records. Checking those files does not rerun
matching or independently replay a formal proof of Z3 optimality.

The [prepared-input manifest](../inputs/reference/artifact_manifest.json)
inventories the retained inputs; the original preparation protocol is stored
alongside it. The [source manifest](../source_manifest.json) identifies the
pinned upstream exports. The data guide and downloads have their own input
and output hashes under [docs/reviewer/](../docs/reviewer/).

The [September 2026 release report](release_validation.json) consolidates the checks for the IKEA ASM snapshot. To inspect those results by hand, use the [IKEA ASM reviewer walkthrough](../docs/MANUAL_REVIEW.md).
