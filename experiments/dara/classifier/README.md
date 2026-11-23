# Generate the scored activity candidates

The matching experiment needs possible activities and their scores for each observation. The classifier reads the wearable sensor samples inside the observation boundaries from the ground truth CSV. It uses the case’s recording session to split training and test data, and the ground truth activity labels of training observations to count neighbor votes. The candidate features are BLE signal, motion and duration. [Classifier and worked example](../../../README.md#how-the-classifier-generates-scored-activity-candidates)

## Recorded inputs for matching and constraint ranking

Reviewers can run the downstream experiments directly from these small files.

| File | When it is used | Contents |
|---|---|---|
| [fusion_top10_candidates.csv.gz](reference/fusion_top10_candidates.csv.gz) | Final matching and classifier-only baseline | Ten candidates for each of the 4,984 observations, scored with the observation’s entire session held out. Each row contains `observation_id,rank,activity_id,weight`. Rank starts at 1. Divide the integer weight by 181 for the classifier score. |
| [nested_scores.json.gz](reference/nested_scores.json.gz) | Ranking individual process constraints | Ten candidates per observation for each of its five validation predictions. Read the compressed JSON by outer test session, case ID and observation ID. Each value is a list of ten `[activity_id, weight]` pairs in rank order. The classifier trained on the four sessions other than the outer test session and the validation observation’s session. |

## Rebuild directly from the wearable recordings

From the repository root, use Python 3.11 and place the following **DaRA v1** files in `datasets/dara-retrieval/raw/`. Leave both archives compressed. Together they require about 1.03 GB. The ground truth observation CSV is included. To rebuild that CSV too, follow the dataset guide. [DaRA v1 files](https://zenodo.org/records/10468175#files) · [Ground truth log generation](../../../datasets/dara-retrieval/README.md#rebuild-from-zenodo)

| Sensor archive | SHA-256 of the v1 download |
|---|---|
| `BLE__Data_and_Revised_Annotations.zip` | `7c380ad018a32d0988a9d705d37c5880be436469fab7db77097835bda9c7d269` |
| `IMU__Data_and_Revised_Annotations.zip` | `bb43788e9d4e1ad19785a6776417d4962190ac97526e6ec54c5d5305df303597` |

```sh
python3.11 -m venv .venv-dara
source .venv-dara/bin/activate
python -m pip install -r experiments/dara/classifier/requirements.txt
python experiments/dara/classifier/reproduce.py \
  --raw-dir datasets/dara-retrieval/raw \
  --output-dir reproduced/dara/classifier
```

For a regenerated log, add `--log datasets/dara-retrieval/rebuilt/dara_retrieval_gt.csv`. For already downloaded archives, point `--raw-dir` at their directory. The program reads one sensor set per worker from the ZIPs. The sensor and video synchronization anchors come from Table 8.1 of the DaRA documentation. [Synchronization anchors](sync_anchors.csv) · [Feature extraction](features.py) · [Classifier](reproduce.py)

Each session takes one turn as the final test. The classifier fits feature scales and selects the 15 nearest training observations. For constraint ranking it repeats the calculation five more times per outer test session, reserving a second session for validation. The paper uses the same 31 CC10 activity IDs in every split. An activity with `v` votes has weight `10*v+1`, including weight 1 for a zero-vote activity. Ties in distance use training-row order (worker, then start frame). Ties in votes use ascending activity ID.

The script prints the final top-1, top-3 and top-10 ground truth counts (**3,395**, **4,414** and **4,734** of **4,984**) and checks both decompressed output files against the recorded experiment. This checks all **49,840** final candidate entries and all **249,200** inner-validation candidate entries, including their ranks and weights. A successful run writes the verified candidate files under `--output-dir` for downstream use.

The synchronization table and candidate files derive from DaRA v1 and carry its CC BY-NC 4.0 data license. The reproduction code uses the repository's MIT license. [Data attribution](../../../datasets/dara-retrieval/DATA-LICENSE.md) · [Software license](../../../LICENSE)
