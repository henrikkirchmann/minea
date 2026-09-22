"""Render the same reviewer narrative as GitHub Markdown and an offline HTML guide."""

import csv
import gzip
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


def label(value):
    names = {
        "exact_variant_count": "GT case variants",
        "pre_insertion_top3_gt_coverage": "GT among original top-three candidates",
        "post_insertion_gt_coverage": "GT in final candidate sets",
        "pre_insertion_duration_weighted_gt_coverage": "Frames in segments with GT among original top three",
        "eighty_percent_variant_coverage": "Diagnostic: variants accounting for at least 80% of cases",
        "case_coverage_with_cutoff_ties": "Cases included when retaining all frequency ties",
        "case_event_count": "Observations per case",
        "case_distinct_activities": "Distinct activities per case",
        "event_duration_frames": "Observation duration (frames)",
        "event_duration_seconds": "Observation duration (seconds)",
        "case_recording_frames": "Whole recording per case (frames)",
        "case_recording_seconds": "Whole recording per case (seconds)",
        "top1_segment_agreement": "Highest-score segment agreement with GT",
        "duration_weighted_segment_agreement": "Duration-weighted segment agreement with GT",
    }
    if value in names:
        return names[value]
    result = str(value).replace("_", " ").capitalize()
    for term, display in (("gt", "GT"), ("na", "NA"), ("sd", "SD"), ("id", "ID"), ("ids", "IDs")):
        result = re.sub(r"\b" + term + r"\b", display, result, flags=re.IGNORECASE)
    return result


def fmt(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.5g}"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def scalar_rows(data, prefix=""):
    """Present every scalar summary, keeping metric paths and ratio denominators."""
    rows = []
    for key, value in data.items():
        name = prefix + label(key)
        if key in {"distributions", "vocabulary", "definitions", "input_hashes"}:
            continue
        if isinstance(value, dict) and {"numerator", "denominator", "percent"} <= value.keys():
            rows.append([name, f"{fmt(value['numerator'])} / {fmt(value['denominator'])} ({fmt(value['percent'])}%)"])
        elif isinstance(value, dict):
            rows.extend(scalar_rows(value, name + " › "))
        elif not isinstance(value, list):
            rows.append([name, fmt(value)])
        elif all(isinstance(v, (str, int, float)) for v in value) and len(value) <= 12:
            rows.append([name, ", ".join(map(fmt, value))])
    return rows


class Document:
    def __init__(self):
        self.md, self.html = [], []
        self.counter = 0

    def heading(self, title, anchor, level=2):
        self.md.append(f"{'#' * level} {title}\n")
        self.html.append(f'<h{level} id="{anchor}">{html.escape(title)}</h{level}>')

    def text(self, text, style=""):
        self.md.append(text + "\n")
        self.html.append(f'<p class="{style}">{html.escape(text)}</p>')

    def links(self, links):
        self.md.append(" · ".join(f"[{name}]({path})" for name, path in links) + "\n")
        self.html.append('<p class="links">' + " ".join(f'<a href="{html.escape(path)}">{html.escape(name)} ↗</a>' for name, path in links) + '</p>')

    def steps(self, items):
        self.md.append("\n".join(f"{i}. {text}" for i, text in enumerate(items, 1)) + "\n")
        self.html.append("<ol>" + "".join("<li>" + html.escape(text) + "</li>" for text in items) + "</ol>")

    def image(self, name, alt):
        self.md.append(f"![{alt}](assets/{name})\n")
        self.html.append(f'<figure><a href="assets/{name}"><img src="assets/{name}" alt="{html.escape(alt)}" loading="lazy"></a></figure>')

    def table(self, headers, rows, searchable=False, selected=None):
        def mdcell(v):
            return fmt(v).replace("|", "\\|").replace("\n", " ")
        self.md.append("| " + " | ".join(headers) + " |\n| " + " | ".join("---" for _ in headers) + " |\n" +
                       "\n".join("| " + " | ".join(mdcell(v) for v in row) + " |" for row in rows) + "\n")
        self.counter += 1
        target = f"table-{self.counter}"
        if searchable:
            control = f'<div class="table-controls"><label>Filter rows <input type="search" data-table="{target}" placeholder="Activity, rule ID, case…" aria-label="Filter table rows"></label>'
            if selected is not None:
                control += f'<label class="toggle"><input type="checkbox" data-selected="{target}"> Selected rules only</label>'
            self.html.append(control + '<span class="row-status" aria-live="polite"></span></div>')
        body = []
        for i, row in enumerate(rows):
            chosen = selected is not None and selected[i]
            body.append(f'<tr data-selected="{str(bool(chosen)).lower()}" class="{"chosen" if chosen else ""}">' +
                        "".join('<td>' + html.escape(fmt(v)) + '</td>' for v in row) + '</tr>')
        self.html.append(f'<div class="table-wrap"><table id="{target}"><thead><tr>' +
                         "".join('<th scope="col">' + html.escape(h) + '</th>' for h in headers) +
                         '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div>')

    def details(self, title, rows):
        self.md.append(f"<details>\n<summary>{title}</summary>\n\n")
        self.html.append('<details><summary>' + html.escape(title) + '</summary>')
        self.table(["Metric", "Value"], rows, searchable=True)
        self.md.append("</details>\n")
        self.html.append('</details>')


CSS = """
:root{--ink:#203341;--muted:#526776;--blue:#176b91;--orange:#ad651e;--line:#dce4e9;--soft:#edf4f7}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:78px}body{margin:0;background:#f7f9fb;color:var(--ink);font:16px/1.65 system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
a{color:var(--blue);text-underline-offset:3px}header{background:#123448;color:white;padding:52px max(5vw,24px) 36px}header .inner{max-width:1160px;margin:auto}.eyebrow{letter-spacing:.16em;text-transform:uppercase;font-size:12px;font-weight:700;color:#98cce3}h1{font-size:clamp(30px,4.3vw,54px);line-height:1.12;letter-spacing:-.04em;margin:14px 0}header p{max-width:760px;color:#d0e3ed;font-size:18px}.badges{display:flex;flex-wrap:wrap;gap:10px}.badges span{border:1px solid #416074;border-radius:5px;padding:4px 10px;font-size:12px;color:#d0e3ed}
nav{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--line);display:flex;gap:25px;padding:13px max(5vw,24px);overflow-x:auto;white-space:nowrap;font-size:14px}nav a{color:var(--ink);text-decoration:none;font-weight:600}main{max-width:1160px;margin:auto;padding:28px 24px 64px}.cards{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}.card{padding:18px;background:white;border:1px solid var(--line);border-radius:8px}.card strong{display:block;font-size:28px;letter-spacing:-.03em;color:var(--blue)}.card span{font-size:13px;color:var(--muted)}h2{font-size:29px;line-height:1.25;margin:52px 0 14px;padding-top:18px;border-top:1px solid var(--line);letter-spacing:-.02em}h3{font-size:21px;margin:30px 0 10px}p{max-width:96ch}p.note{background:#fff6e9;border-left:4px solid #d69a4e;padding:16px 20px;max-width:none}.links{display:flex;flex-wrap:wrap;gap:12px}.links a{border:1px solid var(--line);border-radius:5px;background:white;padding:6px 12px;text-decoration:none;font-size:13px}figure{margin:24px 0;padding:10px;background:white;border:1px solid var(--line);border-radius:8px}figure img{display:block;width:100%;height:auto}.table-wrap{overflow:auto;background:white;border:1px solid var(--line);border-radius:6px;margin:14px 0 24px}table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.45}th{text-align:left;background:var(--soft);color:#27485c;position:sticky;top:0;font-size:12px}td,th{padding:10px 13px;border-bottom:1px solid #e7edf1;vertical-align:top}td:first-child{font-weight:550}tbody tr:last-child td{border-bottom:0}tbody tr:hover{background:#f5f9fc}tr.chosen{background:#eaf4f8}tr.chosen td:first-child{border-left:3px solid var(--blue)}.table-controls{display:flex;align-items:center;flex-wrap:wrap;gap:18px;margin:18px 0 0;font-size:13px;color:var(--muted)}input[type=search]{display:block;min-width:240px;padding:9px 12px;border:1px solid #bdccd5;border-radius:5px;font:inherit;margin-top:4px}input[type=checkbox]{accent-color:var(--blue)}.toggle{display:flex;gap:7px;align-items:center}.row-status{margin-left:auto;font-variant-numeric:tabular-nums}details{margin:20px 0;border:1px solid var(--line);padding:15px 18px;border-radius:7px;background:white}summary{cursor:pointer;font-weight:600}code{background:#eaf0f4;padding:2px 5px;border-radius:3px;font-size:.92em}footer{border-top:1px solid var(--line);padding:25px;color:var(--muted);text-align:center;font-size:13px}a:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid #e5a654;outline-offset:3px}
@media(max-width:700px){.cards{grid-template-columns:repeat(2,1fr)}header{padding-top:32px}main{padding:20px 15px}nav{gap:20px}h2{font-size:25px}td,th{padding:9px}.card:last-child{grid-column:span 2}}
@media print{nav,.table-controls{display:none}body{background:white;font-size:11px}main{max-width:none}header{padding:20px}header h1{font-size:30px}h2{break-after:avoid}figure{break-inside:avoid}details{display:block}.cards{grid-template-columns:repeat(5,1fr)}}
"""

JS = """
function filterTable(id){
  const search=document.querySelector('[data-table="'+id+'"]');
  const selected=document.querySelector('[data-selected="'+id+'"]');
  const query=search?search.value.trim().toLowerCase():'';
  const rows=[...document.querySelectorAll('#'+id+' tbody tr')];
  let visible=0;
  rows.forEach(row=>{const show=row.textContent.toLowerCase().includes(query)&&(!selected||!selected.checked||row.dataset.selected==='true');row.hidden=!show;if(show)visible++;});
  const status=search.closest('.table-controls').querySelector('.row-status');
  status.textContent=visible+' / '+rows.length+' rows';
}
document.querySelectorAll('[data-table]').forEach(input=>{input.addEventListener('input',()=>filterTable(input.dataset.table));filterTable(input.dataset.table);});
document.querySelectorAll('input[data-selected]').forEach(input=>input.addEventListener('change',()=>filterTable(input.dataset.selected)));
"""


def generate(root, output, logs, rules):
    root, output = Path(root), Path(output)
    data = output / "data"
    def read_csv(path):
        with path.open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))
    population = read_csv(root / "inputs/reference/full/cases.csv")
    gt = read_csv(root / "inputs/reference/full/ground_truth.csv")
    with gzip.open(root / "inputs/reference/full/uncertain_log.csv.gz", "rt") as stream:
        uncertain = list(csv.DictReader(stream))
    replacements = read_csv(root / "inputs/reference/candidate_replacements.csv")
    by_case = defaultdict(list)
    for event in gt:
        by_case[event["case_id"]].append(event)
    variants = Counter(tuple(e["activity"] for e in sorted(es, key=lambda e: int(e["start_frame"]))) for es in by_case.values())
    selected = [r for r in rules["prerequisites"] if r["selected"]]
    bounds = [r for r in rules["occurrence_bounds"] if r["selected"]]
    n, e = len(population), len(gt)
    doc = Document()
    doc.heading("Data preparation and mined rules", "top", 1)
    doc.text("From classifier-scored video segments to a controlled matching experiment. Ground truth (GT) means the reference activity annotations supplied with IKEA ASM: which activity occurs, and when. This guide explains how these annotations and model scores become matching inputs; every numerical table is generated from the included evidence.")
    doc.links([("Main README · setup and running the code", "../../README.md"),
               ("Next: inter-case constraints and source placement", "../../docs/coupling/README.md"),
               ("HTML version of this guide", "index.html"), ("All rule definitions", "RULES.md"),
               ("Metric definitions", "DATA_DICTIONARY.md"),
               ("Data sources and citations", "../../docs/SOURCES.md"), ("BibTeX references", "../../references.bib")])
    doc.table(["Cases", "GT observations", "Candidate alternatives", "GT case variants", "Mined / used templates"],
              [[n, e, sum(len(json.loads(r["scores"])) for r in uncertain), len(variants), "73 / 5"]])
    doc.text("GT defines the observations, ensures the reference activity is among their candidates, and supplies the traces from which we mine rules. We use this same set of cases throughout. These choices let us study matching under controlled conditions; the results do not measure recognition on unseen videos or show that the rules hold for unseen assemblies.", "note")

    doc.heading("1. How the two logs were created", "pipeline")
    doc.heading("The original dataset and our earlier uncertain log", "data-sources", 3)
    doc.text("The IKEA ASM dataset by Ben-Shabat et al. (WACV 2021) records people assembling furniture. We use its test dataset: 117 assembly recordings for which the dataset authors provide classifier scores. This is why we use the test set for this experiment. One recording is one case; 117 is a count of test cases, not distinct people or the entire IKEA ASM dataset.")
    doc.links([("IKEA ASM paper · Ben-Shabat et al. (2021)", "https://openaccess.thecvf.com/content/WACV2021/html/Ben-Shabat_The_IKEA_ASM_Dataset_Understanding_People_Assembling_Furniture_Through_Actions_WACV_2021_paper.html"),
               ("IKEA ASM website", "https://ikeaasm.github.io/"),
               ("Original authors' repository", "https://github.com/IkeaASM/IKEA_ASM_Dataset")])
    doc.text("Our earlier IKEA_ASM_UncertainEventLogs repository converts these frame-level predictions and annotations into event logs. It keeps possible activity labels and their scores, giving the candidates needed by our matching model. We reuse its GT-aligned export. ‘GT-aligned’ means that changes in the reference activity label determine where observations start and end, as explained below.")
    doc.links([("Our uncertain-log repository", "https://github.com/henrikkirchmann/IKEA_ASM_UncertainEventLogs"),
               ("Earlier work · Kirchmann et al. (2026)", "https://doi.org/10.1007/s44311-026-00055-7"),
               ("Exact export version", "https://github.com/henrikkirchmann/IKEA_ASM_UncertainEventLogs/tree/f8403649a508584d661edee3b8fb0c231f6c7a78")])
    doc.heading("Why P3D scores are available", "p3d", 3)
    doc.text("P3D is an existing video activity-recognition model evaluated by the IKEA ASM authors. Our earlier repository reuses their released predictions for the test recordings. We selected P3D because it has the highest frame accuracy after excluding GT-NA frames among the ten supplied model exports: 66.52%. We reuse the supplied segment averages without training a classifier or rerunning video inference. This combination of a real assembly process, scored candidates and reference labels is why the dataset is useful for this matching experiment.")
    doc.links([("Authors' action-recognition benchmark", "https://github.com/IkeaASM/IKEA_ASM_Dataset/tree/master/action"),
               ("Recorded ten-model comparison", "../../inputs/reference/model_selection.csv")])
    doc.heading("GT-aligned export: from frames to observations", "gt-alignment", 3)
    doc.steps([
        "Start with the frames of one test recording in time order. Each frame has a GT activity label and a classifier score for each possible activity.",
        "Collect consecutive frames with the same GT label into one segment. A change in GT starts a new segment, even if the classifier's highest-scoring activity does not change. A later return to the same GT label is a separate segment.",
        "Represent the segment as one event, called an observation in the matching model. Its case is the recording, its GT activity is the shared label, and its start and end come from the first and last frames in the segment.",
        "For each possible activity separately, add its classifier scores over all frames in the segment and divide by the number of frames. This gives that activity's candidate score for the observation. Average the full score vector before choosing the retained candidates.",
        "Write two aligned logs. The GT log records the observation with its reference activity; the uncertain log records the same observation and time interval with scored candidate activities. This experiment reuses the averages already computed by our earlier repository."
    ])
    doc.text("Illustrative two-activity example, not an IKEA ASM measurement: frames 10–12 have GT activity A, and frames 13–14 have GT activity B. The classifier can disagree with GT within either segment.")
    doc.table(["Frame", "GT activity", "Score for A", "Score for B"],
              [[10, "A", "0.6", "0.4"], [11, "A", "0.9", "0.1"], [12, "A", "0.3", "0.7"],
               [13, "B", "0.2", "0.8"], [14, "B", "0.4", "0.6"]])
    doc.table(["Observation", "Frames [start, end)", "GT activity", "Mean score for A", "Mean score for B"],
              [["First", "[10, 13)", "A", "(0.6 + 0.9 + 0.3) / 3 = 0.6", "(0.4 + 0.1 + 0.7) / 3 = 0.4"],
               ["Second", "[13, 15)", "B", "(0.2 + 0.4) / 2 = 0.3", "(0.8 + 0.6) / 2 = 0.7"]])
    doc.text("The earlier export stores the first and last included frame. Our prepared logs use an exclusive end: frames 10, 11 and 12 become [10, 13), with duration 3 frames. Under the supplied 25-frames-per-second convention, this is 0.40–0.52 seconds; the next observation is 0.52–0.60 seconds. Times are relative to each recording, not a shared clock across cases.")
    doc.heading("What NA means and why we remove it", "na", 3)
    doc.text("NA means ‘No Annotation’ in the original paper's activity list. It labels intervals without an annotated activity from the dataset's action set. A video also contains time outside its labelled actions; NA does not establish that the person is motionless. The separate label ‘other’ remains an activity in our logs.")
    doc.links([('Original activity list · Table 11, activities are in "Description" column', "https://arxiv.org/pdf/2007.00394v1#page=16")])
    doc.text("We remove GT-NA observations and omit NA from the candidate activities as a simplification: we study matching activity candidates for annotated assembly observations, without also evaluating how to identify unannotated intervals. This filtering uses GT. Case 38 contains only NA and is excluded, leaving 116 cases and 1,856 observations. Removing NA does not force a selection: the matching model still permits selecting no candidate for an observation.")
    doc.text("The repository also provides segments formed from consecutive model predictions. We use those exports to recover frame-accuracy counts, not to define this experiment's observations. Surviving GT segment boundaries and repeated activity labels are retained after NA removal. Each GT row and uncertain row has the same event ID, case and frame interval. Intervals are half-open: [start, end), with duration end − start, at 25 frames per second.")
    doc.heading("Three candidates and a feasible GT matching", "candidate-policy", 3)
    doc.text("We limit each observation to three candidates for performance reasons: this limits the number of candidate variables and possible choices the matching algorithm must consider. Three is a practical setting for this controlled experiment under a fixed time budget, not a demonstrated best choice. The same candidate sets are used throughout the sweep.")
    doc.text("For each observation, rank the non-NA activities by their original mean scores. Retain three; only if GT is absent, replace the third with the GT label at its original score. This happens in 353 of 1,856 observations (19.02%). Scores are not renormalized. The GT label is present in all final candidate sets by construction.")
    doc.text("We keep GT to preserve a known complete feasible matching: selecting the reference activity for every observation satisfies the rules mined from GT, and the synthetic inter-case constraints are constructed to preserve that selection. Without insertion, truncating the candidates could remove part of this complete reference solution. This is a simplification for studying matching performance; neither matcher receives the GT selection as a starting solution. The model permits unmatched observations, so GT insertion is not required merely to make some selection feasible.")
    doc.heading("A real observation, before and after GT insertion", "example", 3)
    example = replacements[0]
    event = next(r for r in uncertain if r["event_id"] == example["event_id"])
    scores = json.loads(event["scores"], parse_float=str)
    before = {a: s for a, s in scores.items() if a != example["inserted_gt_activity"]}
    before[example["replaced_activity"]] = example["replaced_score"]
    def ranked(v):
        return sorted(v.items(), key=lambda t: (-float(t[1]), t[0]))
    doc.text(f"Observation {example['event_id']}; GT is “{example['inserted_gt_activity']}”, originally ranked {example['gt_original_non_na_rank']} among non-NA activities. The original top three below are reconstructed from the retained scores and the recorded replacement. Full original score vectors require the pinned upstream export.")
    doc.table(["Rank", "Original top-three label", "Original score", "Final label", "Unchanged score"],
              [[i + 1, a, s, b, t] for i, ((a, s), (b, t)) in enumerate(zip(ranked(before), ranked(scores)))])
    doc.text("The replacement makes the reference activity available to the matcher while preserving its original low score. It does not force the matcher to choose it or increase its score.")
    doc.links([("GT rows", "../../inputs/reference/full/ground_truth.csv"), ("Uncertain rows", "../../inputs/reference/full/uncertain_log.csv.gz"),
               ("Every GT insertion", "../../inputs/reference/candidate_replacements.csv"), ("Pinned upstream files", "../../source_manifest.json")])
    doc.heading("Download event logs", "event-log-downloads", 3)
    doc.text("The downloads below contain this experiment's 116 cases and 1,856 observations in XES and CSV formats for process-mining tools such as PM4Py. Each observation remains one event. The GT log records the reference activity. The uncertain log uses the highest-scoring candidate as its displayed activity and keeps all three candidate activities and their unchanged scores in the probs_json payload attribute, following our earlier repository. That displayed activity is not a constrained matching result; tools must read the payload to use the alternatives.")
    doc.links([("Download all event logs (ZIP)", "downloads/ikea-asm-event-logs.zip"),
               ("GT log (XES)", "downloads/ground_truth.xes"),
               ("Uncertain log (XES.GZ)", "downloads/uncertain_log.xes.gz"),
               ("GT log (CSV)", "downloads/ground_truth.csv"),
               ("Uncertain log (CSV)", "downloads/uncertain_log.csv")])
    doc.text("The case, activity and time mapping is already included. In XES, each trace's concept:name identifies its case and each event's concept:name gives its activity. CSV uses the corresponding PM4Py columns case:concept:name and concept:name. Both formats record time:timestamp at the exclusive segment end and lifecycle:transition as complete. The additional start_timestamp attribute gives the segment start: this is PM4Py's convention, not a standard XES extension. Event IDs, frame intervals and the uncertain log's score-mass attributes are retained as payload.")
    doc.text("PM4Py can load the XES files directly with read_xes. The CSV headers match the default case, activity and completion-time keys of format_dataframe; the loading examples also parse start_timestamp. Reading either format does not run the matching algorithm or interpret probs_json as additional events. On GitHub, open a file and use Download raw file; the ZIP includes all four logs and loading examples.")
    doc.text("All timestamps use elapsed video time at 25 frames per second, placed on a synthetic 1970 date. They do not show actual calendar dates or concurrency between recordings. The interval is half-open: time:timestamp − start_timestamp equals the observation duration. These downloads map the prepared experiment logs to the attributes above; the frozen experiment inputs remain unchanged.")
    doc.links([("Loading examples and attribute descriptions", "downloads/USAGE.txt"),
               ("PM4Py's dataframe attribute conventions", "https://processintelligence.solutions/app/static/api/2.7.17/api/pm4py.utils.html"),
               ("Download contents, hashes and checks", "downloads/manifest.json")])
    doc.heading("Reusing the older event logs", "older-event-logs", 3)
    doc.text("The earlier repository's no-NA GT XES already has the same 116 nonempty cases, 1,856 events and within-case activity sequences. It can be reused for activity order and frequency. Its timestamps, however, encode frame numbers as seconds: frame 58 appears at 58 seconds instead of 58 / 25 = 2.32 seconds. The current exports correct that conversion and use an exclusive end frame; the activities and segments are unchanged.")
    doc.text("The old uncertain logs cannot be substituted unchanged. The prediction-merged logs have different observation boundaries, and the GT-aligned exports retain the original activity-score vectors. This experiment uses GT-aligned observations after NA removal and keeps only three candidates, inserting GT when needed. The downloads above reuse our already prepared experiment logs, preserving these choices and the original retained scores without renormalization. We retain the earlier repository's probs_json payload name for the scores and map the case, activity and time attributes consistently across XES and CSV. These are export-format changes, not changes to the experiment.")
    doc.links([("Earlier repository and export descriptions", "https://github.com/henrikkirchmann/IKEA_ASM_UncertainEventLogs"),
               ("Pinned original no-NA GT XES", "https://github.com/henrikkirchmann/IKEA_ASM_UncertainEventLogs/blob/f8403649a508584d661edee3b8fb0c231f6c7a78/paper_event_logs/ikea_asm/split=test/gt_realisation/ikea_asm__test__gt_realisation__no_na.xes")])
    doc.heading("Data preparation at a glance", "pipeline-overview", 3)
    doc.image("data_pipeline.svg", "Data preparation, distinguishing reused upstream classifier outputs from local GT-assisted log preparation")

    doc.heading("2. The ground-truth log", "ground-truth")
    doc.text("A case is one retained assembly trace; an observation is one annotated activity segment. Durations are segment time or recording time as labeled, not participant labor time. The four furniture groups are retained together. GT case variants preserve the full ordered sequence after NA removal, including adjacent repeated labels.")
    doc.text(f"There are {len(variants)} GT case variants, of which {sum(v == 1 for v in variants.values())} occur once. Case lengths range from {min(map(len, by_case.values()))} to {max(map(len, by_case.values()))} observations. No frequent-variant filtering is applied.")
    groups = read_csv(data / "groups.csv")
    doc.table(["Furniture group", "Cases", "GT observations", "Activities", "GT case variants", "GT insertions", "Highest-score segment agreement"],
              [[r["process_group"].replace("_", " "), int(r["case_count"]), int(r["event_count"]), int(r["distinct_activities"]),
                int(r["exact_variants"]), int(r["gt_insertions"]), f"{int(r['top1_correct_segments'])} / {int(r['event_count'])} ({100 * float(r['top1_segment_agreement']):.2f}%)"] for r in groups])
    distribution_headers = ["Metric", "N", "Min", "Median", "Max", "Mean", "Population SD"]
    def distributions(section):
        hidden = {"case_recording_frames", "case_retained_event_frames", "case_retained_span_frames"}
        return [[label(name), *[s[k] for k in ("count", "minimum", "median", "maximum", "mean", "population_sd")]]
                for name, s in section.get("distributions", {}).items() if name not in hidden]
    doc.table(distribution_headers, distributions(logs["ground_truth"]))
    doc.text("N is the number of cases, observations or variants summarized in that row. Population SD describes their spread around the mean, using denominator N. All time values identify frames or seconds explicitly; the downloadable statistics retain the full detail.")
    doc.links([("All 116 cases", "data/cases.csv"), ("Furniture groups", "data/groups.csv"), ("All GT case variants", "data/variants.csv"),
               ("Directly following activities", "data/transitions.csv")])

    doc.heading("3. The uncertain log", "uncertain")
    doc.image("log_profiles.svg", "A: observations per case; B: segment durations; C: GT rank among the final three candidates; D: original scores split into retained and removed activities")
    doc.text("Panels A and B describe the number of observations per case and their durations. Panels C and D show what the candidate-selection policy leaves in the uncertain log.")
    doc.heading("Panel C: GT rank among the three candidates", "gt-rank", 3)
    ranks = logs["uncertain"]["gt_retained_rank_frequency"]
    original_ranks = logs["uncertain"]["gt_original_non_na_rank_frequency"]
    doc.text(f"For each observation, sort its final three candidates by their unchanged classifier scores and locate the GT activity. Rank 1 means GT has the highest score; rank 3 means it has the lowest of the three. The bars count observations: {ranks['1']:,} at rank 1, {ranks['2']:,} at rank 2 and {ranks['3']:,} at rank 3, totaling {e:,}.")
    doc.text(f"The third bar includes {original_ranks['3']:,} observations where GT was already third and all {len(replacements):,} where we inserted it after it fell outside the original top three. Thus the chart describes the prepared candidate sets after GT insertion; it is not the original classifier's top-three recognition accuracy.")
    doc.heading("Panel D: retained and removed scores", "score-split", 3)
    mass = logs["uncertain"]["distributions"]
    doc.text("For each observation, split the original segment-averaged scores into three sums: scores of the final three candidates, the removed NA score, and scores of all other removed activities. The bar shows the average of each sum over all 1,856 observations, with each observation weighted equally regardless of its duration. NA here is the classifier's score for NA on these retained observations, not the deleted GT-NA segments. A replaced third candidate belongs to the removed activities; an inserted GT candidate belongs to the retained three.")
    doc.text(f"On average, the retained candidates account for {mass['retained_score_mass']['mean']:.3f}, NA for {mass['removed_na_score']['mean']:.3f}, and the other removed activities for {mass['discarded_non_na_score_mass']['mean']:.3f}. Together these are approximately 1; small residuals come from rounding in the released scores. This explains why the three retained scores generally sum to less than 1: we keep their original values without renormalization. These are score sums, not percentages of observations or matching accuracy.")
    doc.heading("Activity frequencies", "activity-frequencies", 3)
    doc.image("activity_profile.svg", "Every activity: GT frequency, frequency among retained candidates, and highest-scoring label frequency; totals differ")
    doc.links([("All activities", "data/activities.csv"), ("Every observation and its original scores", "data/observations.csv"),
               ("All score distributions", "data/score_distributions.csv"), ("Ten-model comparison", "data/model_comparison.csv")])
    doc.details("Model selection: recorded upstream evidence", scalar_rows(logs["model_selection"]))
    models = read_csv(data / "model_comparison.csv")
    doc.table(["Rank", "Model export", "Selected", "Correct non-NA frames / 276,058", "Non-NA frame accuracy", "All-frame accuracy"],
              [[int(r["rank_by_recorded_non_na_frame_accuracy"]), r["model_id"].replace("__", " / "), r["selected"] == "True",
                int(r["correct_non_na_frames"]), f"{100 * float(r['raw_non_na_frame_accuracy']):.2f}%", f"{100 * float(r['raw_all_frame_accuracy']):.2f}%"] for r in models])
    doc.text("The model table uses recorded counts from the original 117-case release: 320,390 total frames and 276,058 non-NA frames. Case 38 contains only NA. It is omitted from the prepared cohort, whose recording-frame total is therefore smaller.")

    doc.heading("4. How the rules were mined", "mining")
    doc.image("rule_mining.svg", "Ground-truth prerequisite tests and empirical occurrence bounds, including the five selected rules")
    doc.text("For every ordered pair of different activities A and B, inspect every GT occurrence of B. Accept A-before-B only if at least one B occurs in the cohort and every B has an A in the same case whose end frame is no later than B's start. The A need not be immediately before B, and one A can support several B events. A case without B satisfies this rule vacuously.")
    doc.text("For each activity, count its GT segments in every retained case, including zeros. The minimum and maximum give its empirical occurrence bound. The zero minima mean no activity is mandatory in every retained trace. These describe this cohort; they are not independently validated physical assembly laws.")
    doc.table(["Rule family", "Examined / mined", "Used in matching", "Meaning of support"],
              [["Prerequisites", "992 ordered pairs tested; 41 accepted", 3, "Cases/events containing the trigger activity"],
               ["Occurrence bounds", "32 activities; 32 bounds", 2, "Cases/events containing the bounded activity"]])
    doc.heading("Why only five rules are used for matching", "runtime-choice", 3)
    doc.text("In a preliminary run with all 41 prerequisites and 32 occurrence bounds, distributed B&B reached the 300-second limit before completing the log, even with 116 independent cases and two sources. We reduced the rule set for practical runtime while retaining all 116 cases and their candidates.")
    doc.text("Within each rule family, rank by descending supported cases, then supported events, then ascending template ID. Take the first three prerequisites and first two bounds. The same five are used by both methods and remain fixed across every source/component setting. Dropping rules changes the matching problem: the sweep evaluates this smaller constraint model, and does not show that five is the best rule count or a speedup on the original full model.")
    doc.heading("The five rules used in the paper", "selected-rules", 3)
    chosen_rows = [[r["id"], f"{r['predecessor']} before every {r['trigger']}", r["support_cases"], r["support_events"], r["vacuous_cases"]] for r in sorted(selected, key=lambda r: r["rank"])]
    chosen_rows += [[r["id"], f"{r['lower']} ≤ count({r['activity']}) ≤ {r['upper']}", r["support_cases"], r["support_events"], r["zero_cases"]] for r in sorted(bounds, key=lambda r: r["rank"])]
    doc.table(["ID", "Rule within each case", "Supported cases / 116", "Supported GT events", "Cases without the trigger/activity"], chosen_rows)
    doc.text("Support measures how often a rule's activity appears, not how often the rule is correct: accepted prerequisites have zero GT violations. None is activated in all 116 cases. All 32 count minima are zero. These distinctions matter when judging how informative the rules are.", "note")
    doc.image("rule_support.svg", "Activation in cases for all 41 accepted prerequisites; selected rules are highlighted")
    doc.details("All rule-mining summary statistics", scalar_rows(rules["summary"]))
    doc.links([("Full rule semantics and witnesses", "RULES.md"), ("All 992 tested pairs", "data/prerequisite_tests.csv"),
               ("Frozen selection protocol", "../../inputs/provenance/selection_protocol.json")])

    doc.heading("5. Every mined rule", "catalogue")
    doc.text("The HTML guide supports text search and a “Selected rules only” filter. Blue rows are used in the paper. CSV files preserve all statistics, including group support and witnesses. The full catalogue remains available for provenance; unselected rules are not applied by the five-template sweep.")
    prereqs = sorted(rules["prerequisites"], key=lambda r: r["rank"])
    doc.heading("All 41 prerequisites", "all-prerequisites", 3)
    doc.table(["Rank", "ID", "Used?", "Prerequisite A", "Trigger B", "Cases with B / 116", "B events", "Cases without B"],
              [[r["rank"], r["id"], r["selected"], r["predecessor"], r["trigger"], r["support_cases"], r["support_events"], r["vacuous_cases"]] for r in prereqs],
              searchable=True, selected=[r["selected"] for r in prereqs])
    all_bounds = sorted(rules["occurrence_bounds"], key=lambda r: r["rank"])
    doc.heading("All 32 occurrence bounds", "all-bounds", 3)
    doc.table(["Rank", "ID", "Used?", "Activity", "Min", "Max", "Positive cases / 116", "GT events", "Zero-count cases"],
              [[r["rank"], r["id"], r["selected"], r["activity"], r["lower"], r["upper"], r["support_cases"], r["support_events"], r["zero_cases"]] for r in all_bounds],
              searchable=True, selected=[r["selected"] for r in all_bounds])
    doc.links([("Prerequisite catalogue CSV", "data/prerequisites.csv"), ("Occurrence-bound catalogue CSV", "data/occurrence_bounds.csv")])

    doc.heading("6. Where the synthetic experiment begins", "experiment")
    doc.text("The prepared logs and five rules are the inputs to the next stage. The assembly data do not supply multiple sources or constraints between cases. We add those synthetically, using a saved hierarchy of pairwise case merges and fixed source placement. The separate coupling guide explains the tree, the candidate exclusions and how the two experimental parameters vary.")
    doc.text("Mined templates and instantiated optimization rows are different counts. A prerequisite creates one inequality for each trigger candidate in a case; an occurrence bound applies to the candidates of its activity in that case. At most one candidate may be selected per observation, and selecting none is permitted. Synthetic exclusions are separate from the 73 mined templates.")
    doc.links([("Next: inter-case constraints and source placement", "../../docs/coupling/README.md"),
               ("Matching protocol and recorded results", "../EXPERIMENT.md"), ("Manual checking guide", "../MANUAL_REVIEW.md"),
               ("Paper Figure 3", "../../paper_output/ikea_sweep/figures/ikea-overview.pdf"), ("Recorded results", "../../paper_output/ikea_sweep/REPORT.md")])

    doc.heading("7. Definitions, checks and downloadable evidence", "evidence")
    doc.details("Input consistency and arithmetic checks", scalar_rows(logs["quality"]))
    doc.details("Independent rule recomputation checks", scalar_rows(rules["checks"]))
    files = sorted(data.glob("*.csv"))
    doc.table(["File", "Rows", "Contents"], [[p.name, len(read_csv(p)), logs.get("tables", {}).get(p.name, {}).get("description", {
        "prerequisites.csv": "Every accepted prerequisite, support and witnesses",
        "occurrence_bounds.csv": "Every empirical count bound, support and witnesses",
        "prerequisite_tests.csv": "All accepted and rejected ordered activity pairs"}.get(p.name, "Generated descriptive statistics"))] for p in files])
    doc.links([(p.name, "data/" + p.name) for p in files] + [("Complete log statistics JSON", "data/log_stats.json"), ("Complete rule statistics JSON", "data/rule_stats.json")])
    doc.text("Regenerate the entire guide with: python review.py. Install requirements-figures.txt for its vector charts. The report reads only included local evidence and does not rerun matching. Every input hash and metric definition is retained with the generated statistics; the guide has its own file manifest. Automated consistency checks do not replace an author's manual review.")
    doc.links([("Metric definitions", "DATA_DICTIONARY.md"), ("Guide file manifest", "artifact_manifest.json"), ("Source-code hashes", "provenance.json")])

    dictionary = ["# Reviewer statistics: definitions and units\n",
                  "Generated from the statistics implementation. Log ratios retain a numerator and denominator in JSON; rule fractions have separate count fields and the denominators defined below. Descriptive decimal displays are rounded, while observation exports preserve the original score strings.\n"]
    for key, value in logs["definitions"].items():
        dictionary.append("## " + label(key) + "\n")
        if isinstance(value, dict):
            dictionary.extend(f"- **{label(k)}:** {fmt(v)}\n" for k, v in value.items())
        else:
            dictionary.append(fmt(value) + "\n")
    dictionary.append("## Rule-statistic units\n\nPrerequisite case support counts cases with at least one trigger; event support counts trigger events. Vacuous cases have no trigger. Bound support counts positive-count cases and occurrences of the bounded activity. Case fractions divide by 116 retained cases; trigger-event fractions divide by 1,856 retained GT events; within-group case fractions divide by that furniture group's retained case count. Candidate-potential violations describe combinations allowed by candidate availability alone, not a returned matching or simultaneous feasibility under all constraints.\n")
    (output / "DATA_DICTIONARY.md").write_text("\n".join(dictionary))
    (output / "README.md").write_text("\n".join(doc.md))
    cards = "".join(f'<div class="card"><strong>{a}</strong><span>{b}</span></div>' for a, b in
                    [("116", "retained assembly cases"), ("1,856", "GT-aligned observations"), ("5,568", "candidate alternatives"), ("73", "mined rule templates"), ("5", "templates used in the paper")])
    nav = "".join(f'<a href="#{a}">{t}</a>' for a, t in [("pipeline", "Data preparation"), ("ground-truth", "GT log"), ("uncertain", "Uncertain log"), ("mining", "Mining"), ("catalogue", "All rules"), ("evidence", "Evidence")])
    document = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>IKEA ASM · Data preparation and mined rules</title><style>' + CSS + '</style></head><body>'
    document += '<header><div class="inner"><div class="eyebrow">MINEA · Evaluation evidence</div><h1>From assembly videos<br>to a matching benchmark</h1><p>A visual, auditable guide to the ground-truth log, uncertain candidates, and every mined rule.</p><div class="badges"><span>Local data · no external services</span><span>Reproducible tables and vector charts</span><span>GT assistance explicitly documented</span></div></div></header><nav aria-label="Guide sections">' + nav + '</nav><main><div class="cards">' + cards + '</div>'
    # The HTML has its own hero title; Markdown retains the document heading.
    document += "".join(piece for piece in doc.html if not piece.startswith('<h1'))
    document += '</main><footer>Generated from the frozen IKEA ASM evaluation inputs · Original experimental results remain unchanged.</footer><script>' + JS + '</script></body></html>'
    (output / "index.html").write_text(document)
