# Rerun matching for a retrieval order

Every method receives the same ten scored activity candidates for each observation. The observation's case, start and end frames, and completion-area source come from the event log. The ground truth activities are used later to evaluate the resulting abstracted traces. [Event log](../../../datasets/dara-retrieval/README.md) · [Scored candidates](../classifier/README.md) · [Constraint mining and ranking](../constraints/README.md)

## Run one order

From the repository root, use Python 3.11 and a C++17 compiler (Clang or GCC). Install the DaRA dependencies in your Python environment. The matching baselines use NumPy and SciPy's bundled HiGHS solver. The runner builds the native MINEA executable in a temporary directory. Set `CXX` to the compiler executable if it is installed under a name other than `c++`.

```sh
python3 -m pip install -r experiments/dara/classifier/requirements.txt
python3 experiments/dara/matching/run.py \
  --case session01_order2904_execution02 \
  --output-dir reproduced/dara/example
```

Open `reproduced/dara/example/selections.csv` and find observation `session01_order2904_execution02__activation0013`. In this aisle observation the classifier gave *Moving to the Next Position* (`CL137`) and *Retrieving Items* (`CL139`) equal scores of 71/181. The classifier and source-local matching select the first-ranked `CL137`. With the order's constraints enforced across sources, MINEA and centralized matching select `CL139`. You can join the row to the event log on `dara:observation_id` to see the worker, zone and ground truth activity.

## What each method solves

| Output column | Decision |
|---|---|
| `prediction` | Select the classifier's first-ranked candidate at each observation. |
| `local` | Each participating warehouse area independently maximizes the score of its selected candidates subject to its source-local constraints. Combine the resulting activity selections in time order. |
| `minea` | Each area solves its own problem. When their proposed selections violate a shared constraint, the coordinator branches on a candidate involved in the conflict and requests an updated solution from its owner. Search continues until the shared constraints are satisfied and the optimum is certified. |
| `central` | An independent integer programming solver pools the candidates and enforces all source-local and shared constraints for the order in one model. |

The ten process constraints are enforced together in the two global methods. An occurrence bound limits the number of selected candidates for an activity in the order. A prerequisite permits a trigger candidate only if a supporting candidate was selected in the same order and its observation ended by the trigger's start. A constraint instance is source-local when all its terms belong to one area. An observation may receive at most one activity, and an empty selection is permitted. The CSV represents an omission with an empty activity field.

All three matching methods first maximize the sum of selected classifier scores. Among equally scoring assignments, they maximize the number of first-ranked choices. If another tie remains, they prefer the better candidate at the earliest observation where the assignments differ, with omission ranked last. Source-local matching applies this preference within each area's own observations. MINEA and centralized matching independently solve the same global problem with the same preference, and the runner checks their agreement observation by observation. [Source ownership and constraint construction](model.py) · [Distributed row construction](constructors.py) · [Area and coordinator search](distributed.cc) · [Independent local and centralized solvers](baselines.py)

## Rerun and verify all 53 orders

```sh
python3 experiments/dara/matching/run.py --workers 4 --output-dir reproduced/dara/matching
python3 experiments/dara/results/verify.py --rerun reproduced/dara/matching/selections.csv --require-full-rerun
python3 experiments/dara/coordination/verify.py --coordination reproduced/dara/matching/coordination.csv --require-full-rerun
```

The Python runner solves one order at a time by default. `--workers 4` solves up to four different orders in parallel. A four-worker run in the review environment took about 30 seconds to compile the solver and match all 4,984 observations from the supplied scores. The per-order `seconds` in `coordination.csv` measures the native MINEA subprocess only. Wall time depends on hardware and concurrent work. [Recorded coordination counts and timings](../coordination/README.md)

The default inputs are the released log, scored candidates and ten selected constraint templates. To use freshly generated inputs, supply `--log PATH` for the event CSV, `--candidates PATH` for the ranked CSV (plain or gzip) and `--constraints PATH` for the JSON templates. The runner rebuilds each order's candidate assignments and constraint rows from these inputs before solving. Both the selected labels and five search counters can be compared to the original experiment for a single order or the full cohort. [Evaluation and output definitions](../results/README.md)
