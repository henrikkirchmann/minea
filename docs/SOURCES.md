# Data sources and how we use them

[Main README](../README.md) · [Data preparation and mined rules](reviewer/README.md) · [Inter-case constraints and source placement](coupling/README.md)

This page collects source citations and attribution. The linked setup guides
explain the preparation and experiment step by step.

The evaluation builds on three separate contributions: the original IKEA ASM
dataset, our earlier conversion of its classifier outputs into uncertain event
logs, and the matching experiment in this folder.

## Original recordings, annotations and recognition models

Yizhak Ben-Shabat, Xin Yu, Fatemeh Saleh, Dylan Campbell,
Cristian Rodriguez-Opazo, Hongdong Li and Stephen Gould (2021).
**The IKEA ASM Dataset: Understanding People Assembling Furniture Through
Actions, Objects and Pose.** Proceedings of the IEEE/CVF Winter Conference on
Applications of Computer Vision (WACV), pp. 847–859.
[Paper and official BibTeX](https://openaccess.thecvf.com/content/WACV2021/html/Ben-Shabat_The_IKEA_ASM_Dataset_Understanding_People_Assembling_Furniture_Through_Actions_WACV_2021_paper.html).

- [IKEA ASM project website](https://ikeaasm.github.io/): the recordings,
  annotations, dataset description and download information.
- [Original authors' repository](https://github.com/IkeaASM/IKEA_ASM_Dataset):
  the dataset tools, recognition benchmarks and links to pretrained models.
- [Action-recognition benchmark](https://github.com/IkeaASM/IKEA_ASM_Dataset/tree/master/action):
  the recognition models evaluated on these recordings, including P3D.

The videos show people assembling furniture. The reference activity annotations
identify what activity takes place and its start and end frames. We call this
reference **ground truth (GT)**. One assembly recording is a case; a continuous
segment with one reference activity becomes an observation in this experiment.
We use the **117 recordings in the IKEA ASM test dataset**, because the
dataset authors provide classifier scores for this set. These are 117 cases,
not 117 different people or the entire IKEA ASM dataset. The availability of
per-frame predictions for the test set is also documented in our earlier
published work cited below.

**NA means “No Annotation”** in the original paper's activity list
([Table 11 in the authors' preprint](https://arxiv.org/pdf/2007.00394v1#page=16)).
It identifies intervals without an annotated activity from the dataset's action
set. A recording also contains time outside its labelled actions, so it needs
such a label. This does not establish that the person is motionless. The label
`other` is a separate activity class and remains in our prepared logs.

## Our earlier uncertain-log conversion

Henrik Kirchmann, Stephan A. Fahrenkrog-Petersen, Xixi Lu and Matthias Weidlich
(2026). **Distributional similarity between activities in certain and
uncertain event data.** Process Science 3, article 21.
[Published article](https://doi.org/10.1007/s44311-026-00055-7).

The accompanying
[IKEA_ASM_UncertainEventLogs repository](https://github.com/henrikkirchmann/IKEA_ASM_UncertainEventLogs)
converts the original authors' released model predictions and activity
annotations into event logs. Its exports retain several possible activity
labels and their classifier scores instead of keeping only the highest-scoring
label. This provides the scored candidates needed by our matching model.

This experiment uses the repository at
[commit `f8403649a508584d661edee3b8fb0c231f6c7a78`](https://github.com/henrikkirchmann/IKEA_ASM_UncertainEventLogs/tree/f8403649a508584d661edee3b8fb0c231f6c7a78),
with exact input hashes in [source_manifest.json](../source_manifest.json).
Specifically, its `gt_aligned` export starts from frames with a GT activity
label and a classifier score for each possible activity. Consecutive frames
with the same GT label form one segment, represented as an observation with
that activity and the segment's start and end. For each activity separately,
its scores across the segment's frames are averaged into one candidate score.
Thus the GT determines the segment boundaries, and the classifier determines
the scores. The [data-preparation guide](reviewer/README.md#gt-aligned-export-from-frames-to-observations)
shows this step with an illustrative example and explains the frame boundaries.
The repository also contains observations formed from consecutive predictions
(`pred_merged`). We use those exports to check the original frame-accuracy
counts; they do not define this experiment's observation boundaries.

## Why P3D and why this dataset?

P3D is an existing video activity-recognition model evaluated in the IKEA ASM
benchmark. The original authors made recognition-model outputs available for
the test recordings; our earlier repository makes them usable as scored event
data. We reuse these outputs without training a new classifier. Among the ten
supplied model exports, P3D has the highest frame accuracy when GT-NA frames
are excluded: **183,638 / 276,058 = 66.52%**. See the
[recorded comparison](../inputs/reference/model_selection.csv).

This combination is useful here: a real assembly process gives understandable
activity labels; model scores provide uncertain candidates; and GT lets us
align the observations, identify the reference candidate and mine constraints.
The matching experiments therefore do not require a new computer-vision study.

## What this evaluation changes

We remove GT-NA segments and omit NA from the candidate activities. This is a
deliberate simplification: we study matching activity candidates for annotated
assembly observations, without also evaluating how to identify unannotated
intervals in the video. Removing those segments uses GT information. Case 38
then becomes empty and is excluded. The remaining 116 cases contain 1,856
observations. Each observation retains three candidates, inserting GT as the
third when necessary, with the original scores and no renormalization.

GT has three roles: it defines observation boundaries, supplies the reference
activity label used by the candidate policy, and supplies traces for mining
prerequisites and occurrence bounds. The uncertain log supplies the candidate
choices and scores on which matching operates. This is a controlled experiment
using GT assistance, rather than an evaluation of recognition on unseen data.

With the full set of 41 prerequisites and 32 occurrence bounds, preliminary
distributed B&B matching reached its 300-second limit before completing the
log, even with independent cases at two sources. For practical runtime, we
therefore selected three prerequisites and two occurrence bounds by GT support
and kept that same subset throughout the sweep. All cases and candidates were
retained. This changes the constraint model; the results concern this smaller
model, and five rules are not claimed to be an optimal choice. The decision is
recorded in the [selection protocol](../inputs/provenance/selection_protocol.json).

Source pages checked on 21 September 2026. Reusable citations are in
[references.bib](../references.bib). Dataset attribution and licensing are
described in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Rebuild inputs from the earlier log exports

The main experiment uses the included prepared inputs. Rebuilding them is
optional. To start from the released uncertain-log exports instead, run the
following commands from the project root after the
[installation steps](../README.md#install):

```sh
python run.py --output results/runs/input-rebuild --accuracy-scope non_na --top-k 3 --candidate-policy top-k-gt --variant-coverage 1.0 --drop-empty-cases
python verify.py results/runs/input-rebuild
```

The runner downloads and checks the exact files pinned by
[source_manifest.json](../source_manifest.json), prepares the logs and mines the
rules. It reuses the supplied segment-averaged scores; it does not retrain a
classifier or reprocess video frames. `--upstream-dir /path/to/checkout --offline`
can reuse a local export checkout whose files match the pinned hashes. New
outputs do not replace the frozen inputs.

This step mines the full intra-case rule set. The
[matching sweep](../README.md#rebuild-and-rerun-the-experiment) uses the five
selected rules described above.
