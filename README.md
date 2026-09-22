# IKEA ASM evaluation for MINEA

This project contains the data, code and recorded results for the IKEA ASM
evaluation and Figure 3 of the **ICPM 2027 submission “Keep the Reads at Home:
Data-Minimizing Event Abstraction under Cross-Source Constraints”** by
**Henrik Kirchmann, Arik Senderovich and Matthias Weidlich**. Start with the
experimental setup below; the rest of this README explains the folder and
how to run the code.

## Experimental setup

We evaluate how the number of sources and constraints coupling otherwise
independent cases affect the size of coordinated matching problems and the
ability of B&B to solve them within a fixed time budget.

We use the **117 assembly recordings in the IKEA ASM test dataset**, because
this is the set for which the dataset authors provide classifier scores.
Each frame has a reference activity label—its **ground truth (GT)**—and a score
for each candidate activity. Our earlier uncertain-log repository groups
consecutive frames with the same GT label into one observation and averages
each activity's scores over those frames. We reuse its P3D export. Removing
NA (No Annotation) segments and the resulting empty case 38 leaves **116 cases
and 1,856 observations**.

Each observation has three scored candidates. These candidates and their
scores, three mined prerequisites and two occurrence bounds stay fixed.
The five-rule subset was chosen for practical runtime after the full mined
set reached the 300-second matching limit. We vary **source count
K = 1, 2, 4, 8** and **component count C = 116, 58, 29, 15, 8, 4, 2, 1**.
Synthetic inter-case constraints join cases in a tree of merges; their
candidate decisions stay on the same source. The central baseline collects
all candidates and scores. Matching receives 300 seconds for the entire log
per configuration, run sequentially on an M1 Pro with 16 GB RAM.

This is a controlled matching experiment with one seed and GT assistance.
It does not assess recognition accuracy on unseen data or parallel speedup.

Read the two experimental setup guides in order for all details explained:

1. **[Data preparation and intra-case constraints](docs/reviewer/README.md)** — why we use
   the test set and P3D, how frames become GT-aligned observations, candidate
   selection, NA removal, log statistics, and how the five intra-case constraints are mined.
2. **[Inter-case constraints and source placement](docs/coupling/README.md)** —
   how one constraint joins two cases, how the tree reduces the number of
   components, and how placement keeps each added constraint local to a source.

The [matching protocol and recorded results](docs/EXPERIMENT.md) specify the
budgets, execution order and interpretation of Figure 3. Open the
[vector figure](paper_output/ikea_sweep/figures/ikea-overview.pdf) or
[numerical results](paper_output/ikea_sweep/REPORT.md).

Data attribution: [IKEA ASM paper (Ben-Shabat et al., 2021)](https://openaccess.thecvf.com/content/WACV2021/html/Ben-Shabat_The_IKEA_ASM_Dataset_Understanding_People_Assembling_Furniture_Through_Actions_WACV_2021_paper.html),
[dataset website](https://ikeaasm.github.io/), and our
[uncertain-log repository](https://github.com/henrikkirchmann/IKEA_ASM_UncertainEventLogs)
associated with [Kirchmann et al. (2026)](https://doi.org/10.1007/s44311-026-00055-7).
Full references, the original authors' code and the pinned export version are
in [sources and citations](docs/SOURCES.md).

## Download event logs

[Download all event logs (ZIP)](docs/reviewer/downloads/ikea-asm-event-logs.zip),
or choose the [GT log (XES)](docs/reviewer/downloads/ground_truth.xes),
[uncertain log (XES.GZ)](docs/reviewer/downloads/uncertain_log.xes.gz),
[GT log (CSV)](docs/reviewer/downloads/ground_truth.csv), or
[uncertain log (CSV)](docs/reviewer/downloads/uncertain_log.csv).
All contain the experiment's 116 cases and 1,856 observations.

Case, activity and time are already mapped for process-mining tools such as
PM4Py. XES uses `concept:name` on traces for cases and on events for activities;
CSV uses `case:concept:name` and `concept:name`. Each observation is one
completed event, with `time:timestamp` at its segment end and `start_timestamp`
for its start (PM4Py's convention).

The GT files show the reference activities. In both uncertain formats,
`concept:name` is the highest-scoring candidate, not a constrained matching
result. All three candidates and their unchanged scores are preserved as JSON
payload in `probs_json`, following our earlier repository. See the
[format description and comparison with the older exports](docs/reviewer/README.md#download-event-logs)
and [loading examples](docs/reviewer/downloads/USAGE.txt).

## Project folder

| Location | Purpose |
| --- | --- |
| `docs/reviewer/` | Data-preparation guide, searchable HTML version, log statistics, complete rule catalogue and CSV/JSON tables. |
| `docs/reviewer/downloads/` | Experiment-aligned XES logs, CSV views with start/end times, and a ZIP download. |
| `docs/coupling/` | Inter-case constraint, merge-tree and source-placement guide. |
| `docs/EXPERIMENT.md` | Matching protocol, measured quantities and interpretation of the recorded results. |
| `inputs/reference/` | Prepared GT and uncertain logs, rule audits, model comparison and candidate-replacement records. |
| `inputs/provenance/` | Frozen merge plan, rule-selection records and the inputs needed to verify them. |
| `minea_ikea/` | Data preparation, constraint encoding, distributed construction and matching implementation. |
| `results/benchmark_sweep/` | Recorded study: 32 constructions, 32 distributed matching jobs, eight central jobs, code snapshots and file hashes. |
| `paper_output/ikea_sweep/` | Figure 3, plotting data, numerical report and the paper's evaluation fragment. |
| `tests/`, `examples/` | Automated checks and the small integration-test example. |
| `review.py`, `reviewer/` | Generators for the data guide, statistics and vector illustrations. |
| `provenance/` | Current release checks, source provenance, and an inventory explaining each retained file. |

The included files suffice for the commands below; the original workspace and
paper are not required. Raw videos, downloaded upstream exports, earlier
pilot results and a Python environment are not bundled. The original 73 mined
rules remain in the inputs so the frozen merge plan can be checked; only the
five documented rules are applied in the sweep.

The recorded sweep is preserved as one evidence folder. Some instances and
code snapshots occur twice because the verifier compares preparation with
construction and checks the code used for the recorded runs. These copies and
the original manifests are retained for that purpose. Development caches and
superseded documentation-check reports are excluded from this release.

## Code entry points

| Part of the evaluation | Code |
| --- | --- |
| Prepare observations and mine intra-case constraints | [run.py](run.py), [data.py](minea_ikea/data.py), [mining.py](minea_ikea/mining.py). |
| Add inter-case constraints and assign sources | [sweep_instances.py](sweep_instances.py), [instances.py](minea_ikea/instances.py). |
| Construct the distributed matching model | [construction.py](minea_ikea/construction.py). |
| Match candidates and run the central baseline | [matching.py](minea_ikea/matching.py), [solver.py](minea_ikea/solver.py), [benchmark.py](benchmark.py). |
| Run the 32 configurations and 40 matching jobs | [sweep.py](sweep.py). |
| Verify the saved results independently | [verify_sweep.py](verify_sweep.py), [verify_benchmark.py](verify_benchmark.py), [reference.py](minea_ikea/reference.py). |
| Produce Figure 3 and its tables | [analyze_sweep.py](analyze_sweep.py), [plot_sweep.py](plot_sweep.py). |
| Produce the data guide and event-log downloads | [review.py](review.py), [reviewer/](reviewer/). |

## Install

Run these commands from this project folder. Python 3.10 or later is required;
the recorded study used Python 3.11.
The matching runner uses POSIX resource accounting and runs on macOS or Linux
(including a Linux environment under Windows). PM4Py is optional for reading
the exported logs; it is not a dependency of the experiment.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Check the included data and results

```sh
python -m unittest discover -s tests -v
python verify.py
python verify_sweep.py results/benchmark_sweep
```

These commands check the included logs and rules, saved file hashes,
construction equivalence, matching feasibility, objective values and bounds.
They do not rerun matching. Saved large-instance optimality claims rely on the
exact Z3 backend; checking its recorded results is not an independent proof
replay. The [manual review walkthrough](docs/MANUAL_REVIEW.md) gives concrete
observations, rules and configurations to inspect yourself.

## Rebuild and rerun the experiment

Use a fresh output directory. First prepare all 32 configurations and run
construction; then start the matching sweep:

```sh
python sweep.py --prepare-only --output results/reproduction
python sweep.py --resume --output results/reproduction
python verify_sweep.py results/reproduction
```

The second command runs 40 matching jobs sequentially: 32 distributed settings
and one central run for each of eight component counts. Each has a 300-second
budget for the whole log; distributed B&B also has a 100,000-node cap. The sum
of these budgets is 3 h 20 min, plus construction, checking and process overhead.
Limits are cooperative and can overrun slightly. Timings and the number of
cases solved within the limit may vary between runs and machines.

Use `results/reproduction` for new runs. The included `results/benchmark_sweep`
records the original experiment and its measured code snapshots.
Rebuilding the prepared inputs is optional; see
[rebuilding inputs from the earlier log exports](docs/SOURCES.md#rebuild-inputs-from-the-earlier-log-exports).

## Regenerate the data guide and statistics

```sh
python -m pip install -r requirements-figures.txt
python review.py
```

This regenerates [the data-preparation guide](docs/reviewer/README.md), its
[offline HTML version](docs/reviewer/index.html), the rule catalogue, five
vector illustrations and all descriptive CSV/JSON tables from local inputs.
It also prepares the downloadable event-log bundle and CSV views.
Open the HTML file in a browser after downloading the folder; GitHub displays
its source. No raw download, TeX installation or matching rerun is needed.
The [metric dictionary](docs/reviewer/DATA_DICTIONARY.md) defines the statistics.
The inter-case and source-placement guide is maintained separately. Regenerate
its checked example with `python -m reviewer.coupling`.

## Regenerate Figure 3

Install the optional plotting dependency and TeX Live with `pdflatex`, Libertine
and `newtxmath`. Viewing the included PDF requires none of these dependencies.

```sh
python -m pip install -r requirements-figures.txt
python analyze_sweep.py --input results/benchmark_sweep --output paper_output/reproduction
```

This checks the saved sweep and generates Figure 3 as a vector PDF and PGF,
along with plotting data, a report and LaTeX numbers. To plot a new run, use
`--input results/reproduction`. The included `evaluation.tex` is a paper-section
snapshot for inclusion in the manuscript; the plotting command does not edit it.

## License and citation

The original evaluation code is released under the [MIT license](LICENSE).
The event logs and other dataset-derived records are based on IKEA ASM and
remain subject to its
[Creative Commons Attribution-NonCommercial 4.0 International terms](https://creativecommons.org/licenses/by-nc/4.0/),
as stated on the [dataset website](https://ikeaasm.github.io/#license).
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) records the source attribution,
license scope and changes made to the data.

When reusing these inputs, please cite the original IKEA ASM dataset paper and
our earlier uncertain-event-log work linked above. Reusable citations are in
[references.bib](references.bib) and [CITATION.cff](CITATION.cff).
