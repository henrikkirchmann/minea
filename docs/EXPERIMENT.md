# Matching protocol and recorded results

[Main README: setup and running the code](../README.md) ·
[Data preparation and mined rules](reviewer/README.md) ·
[Inter-case constraints and source placement](coupling/README.md)

This document specifies how the prepared configurations are solved and how to
read the results. The two setup guides explain the inputs, five selected rules,
merge tree and source placement. The recorded sweep uses source counts
**K = 1, 2, 4, 8**, component counts **C = 116, 58, 29, 15, 8, 4, 2, 1**, and
**seed 0**. Candidates, scores and the mined rule subset are fixed; changing C
adds inter-case exclusions, while changing K changes their distribution.

## Matching protocol and figure

There are **40 actual matching jobs**: 32 distributed settings and eight central settings. One central run per C uses K=1; its result is reused across K only after numerical equivalence is checked. Both methods use exact rational Z3 optimization with `z3-solver==4.15.4.0`. Neither receives a GT warm start. The central baseline receives candidates and scores and independently encodes the same constraints.

Each job runs in a fresh process. Components are processed sequentially in a fixed case-based order within one **300-second budget for the whole log**. Distributed jobs additionally have a **100,000-node cap**. Limits are cooperative; an outer 390-second watchdog records execution errors. Construction and audits are outside matching time. Recorded jobs ran on an M1 Pro with 16 GB RAM. This is a single-machine simulation with one seed and one run per job, not a parallel-performance or timing-speedup experiment.

The [overview](../paper_output/ikea_sweep/figures/ikea-overview.pdf) shows:

- The largest component interface, averaged arithmetically over K=2,4,8. An interface contains candidate decisions in constraints spanning sources. This mean is across source settings, not repeated trials.
- Cases belonging to components solved optimally within the budget. A limited component's incumbent does not count as a solved component; unstarted components remain in the 116-case denominator. Identical solved-case curves do not imply identical search work or solved-case identities.

All multi-source settings solve 116 cases at C=116, 46 at C=58, eight at C=29, and zero at C≤15. Central and one-source matching finish all settings. Limited runs are retained rather than represented as completed 300-second results.

## Evidence and verification limits

[Recorded sweep files](../results/benchmark_sweep/) retain the preparation, construction, jobs, protocol, hashes, and measured implementation snapshots. Active scripts use the clean package's paths; preserved snapshots identify the measured code. [Extraction provenance](../provenance/extraction.json) records the copied subset.

Offline verification checks file integrity, model equivalence, exact feasibility and score arithmetic, exclusion witnesses, reported bounds, and protocol accounting. It does not rerun optimization or independently certify historical elapsed times. Large-instance optimality still relies on recorded Z3 conclusions; full search-node traces were disabled. An automated PASS does not mean a human reviewed the dataset or claims. Use the [manual review guide](MANUAL_REVIEW.md) to record that work separately.

Upstream identity and hashes remain in [source_manifest.json](../source_manifest.json). Raw upstream exports are not bundled here. Dataset attribution and usage terms remain in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md); the original-code MIT license does not replace the dataset's terms.
