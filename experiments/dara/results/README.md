# Verify the DaRA event and trace results

From the repository root, run the following with Python 3.9 or newer. It uses the standard library and the files included in this checkout.

```sh
python3 experiments/dara/results/verify.py --output-dir reproduced/dara/results
```

The verifier joins the four recorded selections and the classifier candidates to the ground truth using `dara:observation_id`. For each retrieval order, it sorts the observations by start frame, checks the source-local and cross-source constraints against the selected activities and counts the unit-cost Levenshtein edits to the ground truth activity sequence. For each method, it adds the selected candidate weights and checks the score for every order against the original solver output. Both global methods attain the recorded optimal bound and select the same activity on every observation.

| Method | Total trace edits | Orders violating a constraint | Micro-F1 for the ten activities in the constraints |
|---|---:|---:|---:|
| Classifier only | 1,581 | 51 | 0.749 |
| Source-local matching | 1,553 | 49 | 0.754 |
| MINEA | 1,445 | 0 | 0.781 |
| Centralized matching | 1,445 | 0 | 0.781 |

## Generate the table in the paper

The command above writes `paper_activity_table.tex` in the output directory. It recreates the manuscript's caption, headings, ten activity rows and combined row. The three F1 columns report classifier only, source-local checks, and MINEA with all checks. MINEA and the centralized solver share the third column because they selected identical labels. The last two columns show the change from source-local checks to MINEA in correctly assigned events (true positives) and incorrectly assigned events (false positives).

For each activity and method, the script counts true positives (TP), false positives (FP) and false negatives (FN) across all 4,984 observations. It computes **F1 = 2TP / (2TP + FP + FN)**. For the combined row it sums the counts across the ten activities named in the constraints before computing micro-F1. For example, MINEA has 3,027 true positives, 854 false positives and 840 false negatives across those ten activities, giving 0.781 after rounding. The numeric cells come from these counts. The template supplies the manuscript's wording and layout. [Calculation and table generator](verify.py) · [LaTeX template](paper_activity_table.tex.in)

Use `\input{reproduced/dara/results/paper_activity_table.tex}` in a LaTeX document that loads `booktabs` and `caption` and defines the manuscript's `\tool` macro (for example, `\newcommand{\tool}{\textsc{Minea}}`).

| Generated file | Contents |
|---|---|
| `paper_activity_table.tex` | Ready-to-include table, with F1 rounded to three decimals as in the paper. |
| `activity_metrics.csv` | Ground truth support, TP, FP, FN and unrounded F1 for all four methods on each of the ten activities, plus their micro-F1. |
| `all_activity_metrics.csv` | The same per-activity measures for every one of the 29 observed activities and all four methods. |
| `orders.csv` | Per-order edit counts, selected scores and constraint violations. |
| `summary.json` | Classifier coverage, total edits, constraint violations, differences between MINEA and source-local matching, and the observations for three missed handovers. |

## Inputs

| File | Origin and contents |
|---|---|
| [selections.csv](selections.csv) | Four recorded activity IDs for each of the 4,984 observations. The `prediction`, `local` and `central` columns come from the respective baseline runs. The `minea` column comes from the distributed run’s selected observation–activity pairs. All runs used common tie-breaking. |
| [recorded_objectives.csv](recorded_objectives.csv) | Original per-order scores for all four methods and the final distributed-search upper bound. All entries are exact integer numerators with denominator 181. |
| [paper_activity_table.csv](paper_activity_table.csv) | F1 values rounded to three decimals and source-local/MINEA assignment counts transcribed from the manuscript’s activity table. The verifier computes each value independently from the full selections and ground truth. |
| [Ground truth event log](../../../datasets/dara-retrieval/logs/dara_retrieval_gt.csv) | Ground truth activity, observation ID, times, case and owning source. |
| [Scored candidates](../classifier/reference/fusion_top10_candidates.csv.gz) | Ranked activity IDs and score numerators from the six held-out sessions. |
| [Ten selected constraints](../constraints/selected_rules.csv) | Prerequisites and occurrence bounds used for all 53 orders. |

## Check a fresh matching run

Pass the matching runner’s `selections.csv` to `--rerun`. The following example assumes the runner wrote to `reproduced/dara/matching/`.

```sh
python3 experiments/dara/results/verify.py \
  --rerun reproduced/dara/matching/selections.csv
```

This compares every observation and method in the new output to the recorded selections. A run can cover one order, several complete orders, or the full set. An incomplete order, duplicate or unknown observation ID, or differing selection fails the check. Add `--require-full-rerun` to require all 53 orders. The verifier uses the fresh selections for every reproduced case when computing the metrics and uses recorded selections for any remaining cases. The flags `--log`, `--rules` and `--candidates` can point the same checks at regenerated inputs. The [matching runner](../matching/README.md) performs fresh optimization.
