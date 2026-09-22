# Upstream provenance and notices

The original recordings, annotations and recognition benchmark are credited to
Yizhak Ben-Shabat, Xin Yu, Fatemeh Saleh, Dylan Campbell,
Cristian Rodriguez-Opazo, Hongdong Li and Stephen Gould:
**The IKEA ASM Dataset: Understanding People Assembling Furniture Through
Actions, Objects and Pose.** WACV 2021, pp. 847–859.
[Original paper](https://openaccess.thecvf.com/content/WACV2021/html/Ben-Shabat_The_IKEA_ASM_Dataset_Understanding_People_Assembling_Furniture_Through_Actions_WACV_2021_paper.html),
[project website](https://ikeaasm.github.io/), and
[official code and model resources](https://github.com/IkeaASM/IKEA_ASM_Dataset).

The uncertain event-log conversion builds on Henrik Kirchmann,
Stephan A. Fahrenkrog-Petersen, Xixi Lu and Matthias Weidlich (2026),
**Distributional similarity between activities in certain and uncertain event
data.** *Process Science* 3, article 21.
[Published article](https://doi.org/10.1007/s44311-026-00055-7).
That earlier work and its export repository provide the input provenance;
the matching experiment and synthetic construction in this folder are separate
changes. Reusable source citations are in [references.bib](references.bib) and
[CITATION.cff](CITATION.cff).

This project consumes files from
https://github.com/henrikkirchmann/IKEA_ASM_UncertainEventLogs at commit
`f8403649a508584d661edee3b8fb0c231f6c7a78`. `source_manifest.json` identifies
every downloaded input by exact path, size and SHA-256. The input downloads
are cached locally and excluded from the new repository by `.gitignore`.

The certain and uncertain logs, model counts, trace statistics, discovered
rules, and benchmark instances are derived from those upstream data. The
[official IKEA ASM dataset page](https://ikeaasm.github.io/#license), checked
on 19 September 2026, identifies the dataset and benchmarks as
[Creative Commons Attribution-NonCommercial 4.0 International](https://creativecommons.org/licenses/by-nc/4.0/).
Retain that license, attribution and provenance for the derived records.
The new project's MIT license applies to its original code, not the dataset.

Changes made here include removal of NA segments and case 38, selection of
three candidate labels with GT insertion when needed, conversion to half-open
frame intervals, mining of process constraints, and synthetic ownership and
cross-case exclusions. Original retained score tokens are preserved. These
changes are described in the README and recorded with the corresponding data;
the original authors do not endorse this modified benchmark.

The upstream `LICENSE.txt`, also retrieved and hash-checked by the runner,
contains the following notice:

> The IKEA ASM Dataset: Understanding People Assembling Furniture through Actions, Objects and Pose
>
> Copyright (c) 2020, Yizhak Ben-Shabat, Dylan Campbell, Fatemeh Saleh,
> Cristian Rodriguez, Hongdong Li, Stephen Gould, ANU, ACRV

It licenses software and associated documentation under MIT. Its full text
is preserved in `licenses/IKEA_ASM_CODE_LICENSE.txt`. No upstream training or
network code is incorporated into this project's own implementation. The
upstream aggregation scripts are downloaded as provenance for the reused
averages, with their original notice retained.

Original dataset/project: https://ikeaasm.github.io/

Uncertain event-log export and supplied artifact repository:
https://github.com/henrikkirchmann/IKEA_ASM_UncertainEventLogs
