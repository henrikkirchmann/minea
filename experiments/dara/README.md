# Reproduce the DaRA evaluation

The evaluation compares four ways of matching the same scored activity candidates to 4,984 observations from 53 retrieval orders. The checkout includes the ground truth event log, classifier scores, constraint rankings, and one recorded selection per observation for each method. Start with the command that answers your review question. All commands below run from the repository root.

| What would you like to check? | Inputs | What runs |
|---|---|---|
| Do the published numbers follow from the recorded selections? | Files in the checkout | Recompute trace edits, the activity F1 table, constraint violations and the summary of the recorded coordination measurements. |
| Do the methods actually choose those activities? | Released classifier scores and ground truth log | Mine and rank the constraints, rebuild each order’s matching model, solve it with all four methods, then compare every selection and the coordination counts. |
| Do the original recordings give the same results? | Three DaRA v1 archives from Zenodo | Regenerate the event logs, encode the wearable readings, refit the classifiers, then run the constraint mining, matching and verification steps above. |

## Check the paper’s results from the recorded selections

Run this first from the repository root. It takes about a second with Python 3.9 or newer and uses the standard library. All inputs are included.

```sh
python3 experiments/dara/reproduce.py --check-recorded --output-dir reproduced/dara
```

The command joins the selected activities, scored candidates and ground truth events by observation ID. It writes the manuscript’s LaTeX table to `reproduced/dara/results/paper_activity_table.tex`, exports per-activity F1 for all 29 observed activities, and counts the unit-cost edits between each abstracted trace and the ground truth activity sequence. It also summarizes the original coordinator measurements. The final line confirms that both checks passed. [Quality measures and table](results/README.md) · [Recorded selections](results/selections.csv) · [Coordination measurements](coordination/README.md)

| Paper result | Expected value |
|---|---:|
| Trace edits, classifier only / source-local matching / MINEA / centralized matching | 1,581 / 1,553 / 1,445 / 1,445 |
| Trace edits saved by MINEA compared with source-local matching | 108 of 1,553 (7.0%) |
| Micro-F1 over the ten activities named in the constraints, in the same method order | 0.749 / 0.754 / 0.781 / 0.781 |
| Orders with identical MINEA and centralized activity selections | 53 of 53 |
| Median coordination rounds / local solves per order | 1,177 / 227 |

## Rerun matching on all 53 orders

Use Python 3.11 and a C++17 compiler available as `c++` (or set `CXX` to its executable). The following commands set up the tested Python package versions and run the experiment. They use the released final candidate scores for matching and the separate validation candidate scores for ranking constraints.

```sh
python3.11 -m venv .venv-dara
. .venv-dara/bin/activate
python -m pip install -r experiments/dara/classifier/requirements.txt
python experiments/dara/reproduce.py --output-dir reproduced/dara
```

The run compares the complete constraint ranking and the selected templates, checks all 19,936 method selections (four per observation), regenerates the quality tables, and compares the deterministic coordination counts for each order. It reports the new elapsed times alongside the recorded measurements from the paper’s Apple M1 Pro. Exact elapsed times depend on the machine and workload. [Constraint mining and ranking](constraints/README.md) · [Matching methods and tie-breaking](matching/README.md)

To inspect just the office example used in the main README, run the following in the same environment.

```sh
python experiments/dara/matching/run.py --case session02_order2904_execution03 --output-dir reproduced/dara-s04
python experiments/dara/results/verify.py --rerun reproduced/dara-s04/selections.csv
python experiments/dara/coordination/verify.py --coordination reproduced/dara-s04/coordination.csv
```

## Start from DaRA’s original recordings

Download these three ZIPs from **DaRA v1** into `datasets/dara-retrieval/raw/` and leave them compressed. Together they occupy about 1 GiB. You can also point `--raw-dir` to an existing download directory. [Zenodo file list](https://zenodo.org/records/10468175#files)

| Archive | Used for |
|---|---|
| `Video__Revised_Annotations.zip` | Rebuild the CSV and XES ground truth event logs using the included order windows. |
| `BLE__Data_and_Revised_Annotations.zip` | Obtain signal strengths from the three wearable receivers during each observation. |
| `IMU__Data_and_Revised_Annotations.zip` | Obtain wrist and torso accelerometer and gyroscope readings during each observation. |

```sh
python experiments/dara/reproduce.py \
  --raw-dir datasets/dara-retrieval/raw \
  --output-dir reproduced/dara-from-recordings
```

A full run from the three local ZIP files took about 90 seconds in our test with Python 3.11.9 and Apple Clang. Download and installation time are additional. The runner checks both regenerated logs against the released files. It then reproduces the six final leave-one-session-out classifier predictions and the 30 four-session fits used for constraint ranking. The classifier checks all 49,840 final candidate entries and 249,200 validation entries. The remaining stages consume these regenerated files. [Event log generation and download instructions](../../datasets/dara-retrieval/README.md) · [Classifier implementation and synchronization anchors](classifier/README.md)

## Inspect the outputs

| Folder inside `--output-dir` | Contents |
|---|---|
| `logs/`, `classifier/` | Regenerated ground truth logs and both compressed candidate files when running with `--raw-dir`. |
| `constraints/` | Standalone validation gains for all common constraints, the ten selected constraints and the templates passed to matching. |
| `matching/` | Fresh activity selections for each observation and method, plus per-order coordination measurements. |
| `results/` | The manuscript’s LaTeX activity table, F1 and assignment counts as CSV, per-order edits and the quality summary. |

The outer classifier predicts each observation using only the other five sessions. The fixed set of ten constraints was selected retrospectively using all six sessions. The independent centralized solver and MINEA both apply this same set. The distributed experiment replays the warehouse sources on one computer. [Evaluation design](../../README.md#how-we-mined-and-selected-the-process-constraints) · [Data attribution and license](../../datasets/dara-retrieval/DATA-LICENSE.md)
