# File inventory and validation

This folder records the origin and verification of the material accompanying
the paper evaluation. Start with the [main README](../README.md) to review the
setup, Figure 3, result tables and code.

| File | What it establishes |
| --- | --- |
| [release_validation.json](release_validation.json) | Checks run on the cleaned release: tests, prepared inputs, saved results, figures, links and file integrity. |
| [release_tests.log](release_tests.log) | Output of the release's automated test suite. |
| [file_manifest.json](file_manifest.json) | Every retained file's purpose, byte size and SHA-256, excluding the inventory itself. |
| [extraction.json](extraction.json) | Origin and original hash of files copied when this standalone project was created. These source paths are historical, not runtime dependencies. |
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

Superseded documentation-check reports and development logs were removed from
the upload folder after a complete local backup. The current release report
consolidates the applicable checks. Automated checks do not constitute human
review; the [manual walkthrough](../docs/MANUAL_REVIEW.md) provides that review
procedure.
