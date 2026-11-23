# Reproduce the DaRA process constraints

From the repository root, run the following with Python 3.9 or newer. The script reads the included ground truth event log and inner-validation candidate scores, mines the constraints, ranks them, and compares all three outputs with the recorded files. It uses the Python standard library.

```sh
python3 experiments/dara/constraints/mine_constraints.py
```

| Recorded file | What to check |
|---|---|
| [common_rules.csv](common_rules.csv) | All 172 common constraints in ranking order, including eligibility, threshold, total edits saved, and the gain and number of supporting orders in each fold. |
| [selected_rules.csv](selected_rules.csv) | The eight prerequisites and two occurrence bounds used for all 53 orders in the matching experiment. |
| [rule_templates.json](rule_templates.json) | The same ten constraints in the form used to construct the matching problem. A prerequisite names its earlier activity in `labels` and its later activity in `trigger`. |

## Which sessions train the classifier and which score a constraint?

DaRA has six recording sessions. Hold one session out and mine the ground truth activity sequences in the other five. For example, when session 2 is held out, the training sessions are 1, 3, 4, 5 and 6. Within those five, predict session 1 from sessions 3–6, then rotate the validation session. Each order receives one validation prediction in each of its five training sets. This gives **265 predicted sequences for 53 orders** to rank the constraints. The outer test session and inner validation session both stay out of the classifier training for each prediction. [Classifier inputs and training](../classifier/README.md)

For each outer training set, consider a prerequisite `A before B` when B occurs and every order containing B contains A before its first B. For each activity, the maximum number of occurrences in a single order gives a candidate bound. Keep the 141 prerequisites that held in all six outer training sets. For each of the 31 CC10 activity classes, take the largest of the six maxima as its fixed bound. Of the 141 common prerequisites, 133 had their later activity in every four-session training split and qualified for selection.

## How does one constraint earn its rank?

Start with the classifier’s top candidate for each observation and measure the unit-cost Levenshtein distance to the ground truth activity sequence for that order. Then apply **one constraint** to the same candidates, maximizing their total selected score. When total scores tie, retain as many first choices as possible, then prefer the better candidate rank at the earliest differing observation. The single-constraint decoders use chronological observation order. The packaged log has nonoverlapping intervals within each case.

Subtract the new distance from the classifier-only distance and sum the edits saved over the 265 validation sequences. For example, the bound of two occurrences of *Transporting to the Packaging/Sorting Area* saved 181 edits when applied alone. Sort by total edits saved, then by the number of distinct orders containing the later or capped activity, then by constraint ID. Select the eight highest-ranked eligible prerequisites and two highest-ranked bounds. This is a **retrospective selection across all six sessions**. Final matching enforces the fixed set together using candidate scores from five-session classifier fits. [Evaluation design](../../../README.md#how-we-mined-and-selected-the-process-constraints)

## Use regenerated inputs

The following command writes fresh outputs under `reproduced/dara/constraints/`. Substitute the paths from the log exporter and classifier to use your regenerated inputs.

```sh
python3 experiments/dara/constraints/mine_constraints.py \
  --log datasets/dara-retrieval/logs/dara_retrieval_gt.csv \
  --nested-scores experiments/dara/classifier/reference/nested_scores.json.gz \
  --output-dir reproduced/dara/constraints
```

The nested JSON keys identify the outer test session, case ID and observation ID, in that order. Each observation has ten `[activity ID, score numerator]` entries with a common denominator of 181. Ground truth activities come from `dara:activity_id` in the CSV, matched to the predictions by `dara:observation_id`. [Ground truth event log](../../../datasets/dara-retrieval/README.md)
