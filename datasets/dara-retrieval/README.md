# DaRA warehouse retrieval event log

This is the ground truth event log used to evaluate MINEA on DaRA. Each case is one worker’s execution of a retrieval order. In the experiment, each continuous interval of a low-level process activity is one **observation**. The log records one event per observation, labeled with its ground truth activity, such as **Retrieving Items** or **Attaching Shipping Label**. The CSV and XES contain the same **53 traces, 4,984 events and 29 observed activity classes**.

| File | Use |
|---|---|
| [dara_retrieval_gt.xes](logs/dara_retrieval_gt.xes) | Open directly in a process-mining tool. The XES event classifier uses `concept:name` as the activity label. |
| [dara_retrieval_gt.csv](logs/dara_retrieval_gt.csv) | UTF-8, comma-separated, one row per event. Select `case:concept:name`, `concept:name` and `time:timestamp` as the case, activity and completion time. |
| [export_log.py](export_log.py) | Rebuild both files from the revised DaRA annotations using Python 3.9 or newer with its standard library. |
| [run_windows.csv](run_windows.csv) | The 53 source windows, transcribed from DaRA's published scenario tables with their original one-based frame numbers. |
| [DATA-LICENSE.md](DATA-LICENSE.md) | Dataset attribution, terms for sharing the logs and description of the conversion. Keep with redistributed copies. |

## Which executions are in the log?

DaRA v1 records retrieval and storage in a warehouse laboratory, with 18 participants across six recording sessions. Several workers can perform different runs during the same session. The authors provide wearable inertial and Bluetooth beacon data, synchronized video, revised frame annotations and warehouse management records. The exporter reads the ground truth activities from the revised video annotations. [DaRA dataset](https://doi.org/10.5281/zenodo.10468175) · [Dataset paper and process diagrams](https://doi.org/10.3390/s26020739)

The matching experiment takes each observation’s order, interval boundaries and ending area from DaRA. A simple 15-nearest-neighbor classifier uses the wearable readings and interval duration to supply the same ten scored activity candidates per observation to all four methods. We compare each method’s abstracted trace with the ground truth activity sequence in this log. [How the classifier generates scored activity candidates](../../README.md#how-the-classifier-generates-scored-activity-candidates)

Of the 79 documented runs, scenarios 1–3 are single-order retrievals. Scenarios 4–6 concern storage, scenario 7 combines two orders in one retrieval run, and scenario 8 combines two orders in storage. Subject S11 has no recorded scenario 3. The selection is identical to the paper's 53 cases.

| Scenario | Customer order ID (reused) | Recorded technology (CC07) | Cases | Events |
|---|---|---|---:|---:|
| 1 | 2904 | List and Pen | 18 | 1,721 |
| 2 | 2905 | Portable Data Terminal | 18 | 1,707 |
| 3 | 2906 | List and Glove Scanner | 17 | 1,556 |

A **case ID** identifies an execution. For example, `session01_order2904_execution01` is the run of order 2904 by S02 in session 1. Execution numbers start at one within each (session, order ID) pair. Runs are numbered by ascending documented start frame, breaking ties by worker ID. The worker is a case attribute and the event resource. Reused order IDs support comparisons between workers performing the same order. Grouping cases solely by order ID would collapse the entire log to three traces.

## Rebuild from Zenodo

Use **version 1**, DOI **10.5281/zenodo.10468175**. From the repository root, change into this directory, download the annotation ZIP into `raw/` and leave it compressed. The ZIP is the only upstream download required by the exporter. The checked-in run table supplies the documented boundaries. [Zenodo file list](https://zenodo.org/records/10468175#files)

```sh
cd datasets/dara-retrieval
mkdir -p raw
curl --fail --location --retry 3 \
  'https://zenodo.org/records/10468175/files/Video__Revised_Annotations.zip?download=1' \
  --output raw/Video__Revised_Annotations.zip
python3 export_log.py --output-dir rebuilt
cmp rebuilt/dara_retrieval_gt.csv logs/dara_retrieval_gt.csv
cmp rebuilt/dara_retrieval_gt.xes logs/dara_retrieval_gt.xes
```

Both comparisons finish silently on a byte-for-byte match. Plain `python3 export_log.py` writes both files to `logs/`. For an existing download, pass `--input-dir /path/to/zenodo-files`. The exporter checks the archive's SHA-256 before extracting events.

| Zenodo filename | Purpose |
|---|---|
| `Video__Revised_Annotations.zip` (5.2 MB) | Required. The exporter reads worker-specific frame tables CC06 through CC11, including their label names. Zenodo MD5 **8e5c8444653434c7eacfd8678fb57593**. |
| `Documentation.pdf` | Optional audit. Page 84, Tables 9.1 and 9.2 give session membership, scenario sequence and run bounds. Chapter 2 defines the label categories. Chapter 8 documents the clocks. |
| `Scheme_Files.zip` | Optional label dictionaries for browsing the full DaRA vocabulary, including activities absent from this cohort. |
| `BLE__Data_and_Revised_Annotations.zip`, `IMU__Data_and_Revised_Annotations.zip` | Separate inputs to the paper's sensor classifier. Regenerating the ground truth requires neither archive. |
| `WMS__movement_data.csv`, original video archives | Additional material for studying scans or video. Neither supplies event rows to this log. |

## How one event is constructed

1. Select the worker and scenario window from the run table. If Table 9.2 gives inclusive frames `[first, last]`, use zero-based CSV rows `[first - 1, last)`. Check that every included frame has exactly the expected CC06 order and CC08 Retrieval label. Verify CC07 is constant before assigning it to the case.
2. Within that window, group maximal consecutive frames carrying the same revised **CC10 Low-Level Process** label. Start a new event when CC10 changes or a new case begins. Preserve the source labels for waiting, other and unknown activities. Each event receives the original observation ID, for example `session01_order2904_execution01__activation0001`.
3. Read **CC09 Mid-Level Process** and **CC11 Location – Human** on the same frames. Store the final stage and the start/end locations as directly usable attributes. Also encode every stage and zone change with its frame offset inside the event. The source that owns the observation is the macro area on frame `end_frame - 1`. A worker can spend most of an activity in another area.
4. Emit one completion event with two timestamps. Sorting by event index or start frame reproduces the ground truth activity sequence for the order. Adjacent events meet at a shared frame boundary. A lifecycle start/complete pair would double the number of log entries.

Across the log, **32 events change stage and 2,470 change zone**. The [path attributes](#how-to-read-the-path-attributes) record these changes within a single activity event.

## Attributes and clocks

**Trace attributes** appear once per trace in XES. CSV repeats them with a `case:` prefix. For example, XES trace `dara:order_id` becomes CSV `case:dara:order_id`.

| XES trace key | Meaning |
|---|---|
| `concept:name` | Stable case ID, shared with the paper's order models. |
| `dara:session`, `dara:scenario`, `dara:execution` | Integer recording session, published scenario number and within-session/order execution number. |
| `dara:order_id`, `dara:worker` | Original order identifier (string) and released worker pseudonym, e.g. `2904`, `S02`. |
| `dara:process_id`, `dara:process` | High-level CC08 ID and label, `CL110` and `Retrieval` throughout this cohort. |
| `dara:technology_id`, `dara:technology` | CC07 ID and label for the information technology used in this run. |
| `dara:run_start_frame`, `dara:run_end_frame` | Zero-based frame window for the entire case, end exclusive. |

**Event attributes** use the same names in both formats.

| Event key | Meaning |
|---|---|
| `concept:name`, `dara:activity_id` | Ground truth CC10 activity label and stable activity ID. Use the label for discovery and the ID to compare selected activities with the ground truth. |
| `dara:observation_id`, `dara:event_index` | Unique join key into the MINEA experiment and one-based chronological position in the case. |
| `start_timestamp`, `time:timestamp`, `lifecycle:transition` | Start, completion and the value `complete`. Both timestamps are XES dates. |
| `dara:start_frame`, `dara:end_frame`, `dara:duration_s` | Exact interval boundaries in the session video and duration in seconds rounded to six decimals. |
| `org:resource` | Worker pseudonym from the trace. |
| `dara:stage_id`, `dara:stage`, `dara:stage_path` | CC09 stage ID and name at the last included frame, plus the sequence of stages and the frame at which each begins within the event. |
| `dara:area_start_id`, `dara:area_start`, `dara:area_end_id`, `dara:area_end` | CC11 macro-area ID and original area name at the first and last included frames. |
| `dara:zone_start_id`, `dara:zone_start`, `dara:zone_end_id`, `dara:zone_end` | Finer CC11 zone ID and readable name at the same two frames. |
| `dara:zone_path` | Sequence of visited zone IDs and the frame at which each visit begins within the event. Revisits are preserved. |
| `dara:source` | Identifier of the source that owns this observation in the replay. Each source represents a warehouse area. The workers wore the sensors. |

**Time semantics.** DaRA supplies a synchronized video frame clock at 29.97 frames/s within each session. To represent it as XES dates, session 1 uses 1970-01-01 at 00:00 UTC as frame zero, session 2 uses 1970-01-02, and so on. Add `frame × 100 / 2997` seconds, rounded to the nearest microsecond. These dates are synthetic. Durations, case ordering and overlap within one session are meaningful. Calendar dates, shift start times and gaps between sessions cannot be inferred. The exact duration can always be recovered from the frame columns.

### How to read the path attributes

In both `dara:stage_path` and `dara:zone_path`, each entry has the form `id@offset`. The **onset offset** is the number of video frames elapsed since **this event** began. Every path starts at `@0`, the event's first frame. A label applies from its offset up to, but excluding, the next offset. The final label applies through the event's last included frame (`dara:end_frame - 1`). To find the frame in the recording, add the offset to `dara:start_frame`. To find the elapsed time in seconds, divide the offset by 29.97.

| Example from the log | How to read it |
|---|---|
| Stage path `CL115@0 CL116@22` (event 49 of `session01_order2904_execution03`) | This 47-frame event starts at frame 57823. **Picking - Travel Time** covers the first 22 frames. **Picking - Pick Time** begins at frame 57845, about 0.73 seconds into the event, and covers the remaining 25 frames. |
| Zone path `z168@0 z172-177@197` (event 9 of `session01_order2904_execution01`) | The worker spends the first 197 frames in **Cross aisle 1–2**, then enters **Aisle 1 (Front)** and stays there for the remaining 45 frames. |

For a stage-level trace, expand the stage paths to their frame boundaries and merge adjoining equal stages within a case.

### Warehouse areas and zones

DaRA's CC11 hierarchy distinguishes nine macro areas and, within three of them, finer locations. The 24 zone IDs below can occur in a path. Matching uses the nine macro areas as sources. For example, `z172-177` (aisle 1 front) and `z172-178` (aisle 1 back) both belong to the `aisle` source.

The warehouse map follows worker S04 through order 2904 in session 2, execution 3. Its layout adapts Figure 2.42 of the DaRA documentation. The animation reads the ground truth activity from `concept:name` and highlights the current zone from `dara:zone_path`. Each offset determines the frame at which the highlight changes, including moves within an observation. For example, observation 95, *Handing Over Packed Cardboard Boxes*, starts in the packing area and ends in the issuing/receiving area. The latter owns the observation in the replay. [Vector warehouse map](figures/warehouse_route.svg) · [Animated route](figures/warehouse_route_replay.svg) · [DaRA documentation and attribution](DATA-LICENSE.md)

To regenerate both SVGs, run `python3 datasets/dara-retrieval/figures/plot_warehouse_route.py` from the repository root. The script reads the ground truth CSV and the included zone geometry. To view the animation directly, open `warehouse_route_replay.svg` in a browser. [Zone geometry](figures/warehouse_zones.json) · [Figure generator](figures/plot_warehouse_route.py)

| CC11 macro area | MINEA source | Zone IDs and meaning |
|---|---|---|
| CL155 Office | `office` | `z155` |
| CL156 Cart Area | `cart_area` | `z156` |
| CL157 Cardboard Box Area | `cardboard_area` | `z157` |
| CL158 Base | `base` | `z158` |
| CL159 Packing/Sorting Area | `packing_area` | `z159` |
| CL160 Issuing/Receiving Area | `issuing_receiving` | `z160` |
| CL161 Path | `connecting_path` | `z164` office, `z165` cardboard box area, `z166` cart area, `z167` issuing area |
| CL162 Cross Aisle Path | `cross_aisle` | `z168` aisles 1–2, `z169` 2–3, `z170` 3–4, `z171` 4–5 |
| CL163 Aisle Path | `aisle` | `z172` through `z176` denote aisles 1 through 5, each followed by `-177` for front or `-178` for back. Example: `z174-178` is the back of aisle 3. |

## Reviewer checks

The intervals cover 2,125,250 frames. Trace lengths range from 41 to 118 events. All 29 observed CC10 classes and all nine completion areas are retained. For each event, the exporter verifies its observation ID, frame boundaries, CC10 activity ID and source against a SHA-256 fingerprint computed independently from the experiment with ten fixed process constraints. The fingerprint covers the following five tab-separated fields, sorted by case ID and numeric event index, UTF-8 with one LF per record.

```text
observation_id    start_frame    end_frame    activity_id    source
c6bd7fdfe8525726da04fe5a27df9e6a403d242aa21db430b03c11cfa9162393
```

For a process-mining import with PM4Py (optional), run this in the directory containing this README.

```python
import pm4py

log = pm4py.read_xes("logs/dara_retrieval_gt.xes", return_legacy_log_object=True)
assert len(log) == 53
assert sum(len(trace) for trace in log) == 4984
assert len({event["concept:name"] for trace in log for event in trace}) == 29
```

To evaluate an abstracted trace, join the selected activities to the ground truth events on `dara:observation_id` and sort by `dara:event_index` within each case. Compare the selected activity IDs with the ground truth activity sequence in `dara:activity_id` using unit-cost Levenshtein distance. Summing over cases gives 1,581 edits for the classifier-only baseline, 1,553 for source-local matching and 1,445 each for MINEA and the centralized solver under common tie-breaking. CC08, CC09 and the detailed CC11 paths are included as event-log context. The classifier uses BLE, IMU and interval duration. You can rerun all four methods from the included candidate scores, or regenerate those scores from the wearable archives. [Reproduce the DaRA evaluation](../../experiments/dara/README.md)

## Attribution and reuse

The CSV, XES and run windows are derived from Friedrich Niemann and colleagues' DaRA v1 and distributed under **CC BY-NC 4.0**. The exporter uses the repository's MIT software license. Please cite DaRA when using the log and include the data notice when sharing these files. [Attribution and changes](DATA-LICENSE.md) · [Dataset DOI](https://doi.org/10.5281/zenodo.10468175) · [Dataset paper](https://doi.org/10.3390/s26020739)
