"""Recompute the DaRA event and trace results from observation-level selections."""

import argparse
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
METHODS = ("prediction", "local", "minea", "central")
REPORTED_EDITS = dict(zip(METHODS, (1581, 1553, 1445, 1445)))
REPORTED_VIOLATING_CASES = dict(zip(METHODS, (51, 49, 0, 0)))


def csv_rows(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        yield from csv.DictReader(stream)


def check(condition, message):
    if not condition:
        raise ValueError(message)


def index_rows(path, column):
    rows = {}
    for row in csv_rows(path):
        key = row[column]
        check(key and key not in rows, f"{path}: empty or repeated {column} {key!r}")
        rows[key] = row
    return rows


def ground_truth(path):
    rows = index_rows(path, "dara:observation_id")
    cases = defaultdict(list)
    for obs_id, row in rows.items():
        cases[row["case:concept:name"]].append(obs_id)
    for case, ids in cases.items():
        ids.sort(key=lambda key: int(rows[key]["dara:start_frame"]))
        previous_end = -1
        for index, key in enumerate(ids, 1):
            row = rows[key]
            start, end = int(row["dara:start_frame"]), int(row["dara:end_frame"])
            check(previous_end <= start < end and index == int(row["dara:event_index"]),
                  f"{case}: inconsistent observation order or overlapping interval at {key}")
            previous_end = end
    return rows, cases


def candidate_scores(path):
    candidates = defaultdict(dict)
    for row in csv_rows(path):
        obs_id, label = row["observation_id"], row["activity_id"]
        options = candidates[obs_id]
        rank, weight = int(row["rank"]), int(row["weight"])
        check(rank == len(options) + 1 and label not in options and weight > 0,
              f"{obs_id}: invalid candidate at rank {rank}")
        options[label] = weight
    for obs_id, options in candidates.items():
        ordered = sorted(options, key=lambda label: (-options[label], label))
        check(len(options) == 10 and list(options) == ordered,
              f"{obs_id}: expected ten candidates in classifier rank order")
    return candidates


def edit_distance(a, b):
    """Unit-cost Levenshtein distance, retaining repeated activities."""
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def violations(labels, ids, truth, candidates, rules):
    """Check failed rows at their actual scope, determined by the candidate owners."""
    failures = set()
    for rule in rules:
        trigger = rule["trigger_or_capped_id"]
        if rule["query_type"] == "upper":
            if labels.count(trigger) > int(rule["maximum"]):
                owners = {truth[i]["dara:source"] for i in ids if trigger in candidates[i]}
                failures.add("shared" if len(owners) > 1 else "local")
            continue
        check(rule["query_type"] == "prerequisite", f"Unexpected constraint {rule['rule_id']}")
        prerequisite = rule["prerequisite_id"]
        prior_owners = set()
        for obs_id, label in zip(ids, labels):
            if label == prerequisite:
                break   # This completed observation supports every later trigger in the run.
            source = truth[obs_id]["dara:source"]
            if label == trigger:
                failures.add("shared" if prior_owners - {source} else "local")
            if prerequisite in candidates[obs_id]:
                prior_owners.add(source)
    return failures


def compare_rerun(path, selections, cases, require_full):
    rerun = index_rows(path, "observation_id")
    check(rerun and rerun.keys() <= selections.keys(), "Rerun has no rows or contains unknown observations")
    if require_full:
        check(rerun.keys() == selections.keys(), "A full rerun must cover all 53 cases and 4,984 observations")
    count = 0
    for case, ids in cases.items():
        if rerun.keys().isdisjoint(ids):
            continue
        check(all(i in rerun for i in ids), f"Rerun contains an incomplete case: {case}")
        for i in ids:
            for method in METHODS:
                check(rerun[i][method] == selections[i][method],
                      f"{i}: {method} rerun {rerun[i][method]!r}, recorded {selections[i][method]!r}")
        count += 1
    case_word = "case" if count == 1 else "cases"
    print(f"Rerun matches every recorded selection for {len(rerun):,} observations in {count} complete {case_word}.")
    return rerun


def verify(args):
    truth, cases = ground_truth(args.log)
    selected = index_rows(args.selections, "observation_id")
    candidates = candidate_scores(args.candidates)
    rules = list(csv_rows(args.rules))
    bounds = index_rows(HERE / "recorded_objectives.csv", "case_id")
    paper = index_rows(HERE / "paper_activity_table.csv", "activity_id")
    named = {r["trigger_or_capped_id"] for r in rules} | {r["prerequisite_id"] for r in rules if r["prerequisite_id"]}
    check(named == set(paper) - {"ALL"} and len(rules) == 10, "Constraint activities differ from the paper table")
    check(truth.keys() == selected.keys() == candidates.keys(), "Observation IDs differ between input files")
    check(cases.keys() == bounds.keys(), "Cases differ from the recorded solver results")
    if args.rerun:
        # Use fresh selections for each reproduced case after checking equality.
        selected.update(compare_rerun(args.rerun, selected, cases, args.require_full_rerun))
    actual = Counter(r["dara:activity_id"] for r in truth.values())
    predicted = {m: Counter() for m in METHODS}
    correct = {m: Counter() for m in METHODS}
    edits, violations_by_method = Counter(), Counter()
    coverage = Counter()
    missed_handovers = []
    case_metrics = []

    for case in sorted(cases):
        ids = cases[case]
        gold = [truth[i]["dara:activity_id"] for i in ids]
        check(not violations(gold, ids, truth, candidates, rules), f"Ground truth violates a constraint in {case}")
        for i, label in zip(ids, gold):
            ranked = list(candidates[i])
            for k in (1, 3, 10):
                coverage[k] += label in ranked[:k]
            check(selected[i]["prediction"] == ranked[0], f"Classifier-only selection differs from rank one at {i}")
            check(selected[i]["minea"] == selected[i]["central"], f"Distributed/central labels differ at {i}")

        record = {"case_id": case, "observations": len(ids),
                  "sources": len({truth[i]["dara:source"] for i in ids})}
        for method in METHODS:
            labels = [selected[i][method] for i in ids]
            score = 0
            for i, label in zip(ids, labels):
                check(label in candidates[i], f"{method} selected an unavailable activity at {i}: {label!r}")
                score += candidates[i][label]
            check(score == int(bounds[case][method]), f"{case}: {method} score differs from solver output")
            if method == "minea":
                check(score == int(bounds[case]["minea_upper_bound"]), f"{case}: optimal bound differs")
            failed = violations(labels, ids, truth, candidates, rules)
            if method == "local":
                check("local" not in failed, f"Source-local selection violates a local row in {case}")
            distance = edit_distance(labels, gold)
            record[method + "_edits"] = distance
            record[method + "_score_numerator"] = score
            record[method + "_violates_constraints"] = int(bool(failed))
            edits[method] += distance
            violations_by_method[method] += bool(failed)
            predicted[method].update(labels)
            correct[method].update(a for a, b in zip(gold, labels) if a == b)
        case_metrics.append(record)

        # Cases where jointly enforcing the constraints lost a correct handover
        # and neither prerequisite appeared earlier in the abstracted trace.
        earlier = set()
        for i, label in zip(ids, gold):
            if (label == selected[i]["local"] == "CL130" and selected[i]["minea"] != "CL130"
                    and earlier.isdisjoint({"CL146", "CL148"})):
                missed_handovers.append(i)
            earlier.add(selected[i]["minea"])

    check(len(cases) == 53 and len(truth) == 4984 and len(actual) == 29, "Unexpected cohort")
    check((min(r["sources"] for r in case_metrics), max(r["sources"] for r in case_metrics)) == (6, 9),
          "Unexpected range of sources per run")
    check(dict(coverage) == {1: 3395, 3: 4414, 10: 4734}, "Classifier coverage differs from the paper")
    check(dict(edits) == REPORTED_EDITS and dict(violations_by_method) == REPORTED_VIOLATING_CASES,
          f"Trace metrics differ: {dict(edits)}, {dict(violations_by_method)}")
    check(len(missed_handovers) == 3, f"Unexpected set of missed handovers: {missed_handovers}")
    activity_names = {r["dara:activity_id"]: r["concept:name"] for r in truth.values()}
    by_activity = {label: activity_metrics(label, activity_names[label], [label], actual, predicted, correct)
                   for label in sorted(actual)}
    all_metrics = [row for rows in by_activity.values() for row in rows]
    by_activity["ALL"] = activity_metrics("ALL", "Ten named activities (micro)", named,
                                          actual, predicted, correct)
    metrics = [row for label in paper for row in by_activity[label]]
    check_paper_metrics(metrics, paper)
    summary = dict(cases=len(cases), observations=len(truth), candidate_coverage=dict(coverage),
                   edits=dict(edits), orders_violating_constraints=dict(violations_by_method),
                   named_activity_support=sum(actual[a] for a in named), handover_examples=missed_handovers)
    check(summary["named_activity_support"] == 3867, "Unexpected support of named activities")
    saved = edits["local"] - edits["minea"]
    reduction = 100 * saved / edits["local"]
    quality = {(r["activity_id"], r["method"]): r for r in metrics}
    improvements = sum(quality[a, "minea"]["f1"] > quality[a, "local"]["f1"] for a in named)
    local, minea = quality["ALL", "local"], quality["ALL", "minea"]
    fewer_fp = local["fp"] - minea["fp"]
    fewer_fn = local["fn"] - minea["fn"]
    summary["minea_vs_source_local"] = dict(trace_edits_saved=saved, percent_fewer_trace_edits=reduction,
                                            named_activities_with_higher_f1=improvements,
                                            fewer_false_positives=fewer_fp, fewer_false_negatives=fewer_fn)
    for method, tp, fp in [("local", 503, 607), ("minea", 502, 601)]:
        other = set(actual) - named
        check(sum(correct[method][a] for a in other) == tp and
              sum(predicted[method][a] - correct[method][a] for a in other) == fp,
              f"{method}: counts for the other 19 activities differ from the paper")

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_csv(args.output_dir / "orders.csv", case_metrics)
        write_paper_table(args.output_dir / "paper_activity_table.tex", metrics)
        write_csv(args.output_dir / "all_activity_metrics.csv", all_metrics)
        write_csv(args.output_dir / "activity_metrics.csv", metrics)
        (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(f"Verified {len(cases)} cases, {len(truth):,} observations and all candidate selections.")
    print("Method       Trace edits    Cases violating constraints")
    for method in METHODS:
        print(f"{method:12} {edits[method]:>11,}    {violations_by_method[method]:>3}")
    print(f"MINEA used {saved} fewer trace edits than source-local matching ({reduction:.1f}%).")
    print("Verified every per-activity F1 and count in the paper table.")
    print("Ten-activity micro-F1     " + "   ".join(f"{r['method']}: {r['f1']:.3f}" for r in by_activity["ALL"]))
    print(f"Across the ten constraint activities, F1 improved for {improvements} of {len(named)}. "
          f"MINEA made {fewer_fp} fewer incorrect assignments and missed {fewer_fn} fewer occurrences.")


def activity_metrics(label, name, scope, actual, predicted, correct):
    """Pool observation counts over the given ground truth activity IDs."""
    support = sum(actual[a] for a in scope)
    rows = []
    for method in METHODS:
        tp = sum(correct[method][a] for a in scope)
        fp = sum(predicted[method][a] for a in scope) - tp
        fn = support - tp
        f1 = 2 * tp / (2 * tp + fp + fn)
        rows.append(dict(activity_id=label, activity=name, method=method,
                         support=support, tp=tp, fp=fp, fn=fn, f1=f1))
    return rows


def check_paper_metrics(metrics, paper):
    for row in metrics:
        label, method = row["activity_id"], row["method"]
        reference = paper[label]
        compared = "minea" if method == "central" else method
        check(f"{row['f1']:.3f}" == reference[compared + "_f1"], f"{label}: {method} F1 differs from paper")
        if method != "prediction":
            check(row["tp"] == int(reference[compared + "_tp"]) and row["fp"] == int(reference[compared + "_fp"]),
                  f"{label}: {method} label counts differ from paper")


def write_paper_table(path, metrics):
    """Fill the manuscript layout with scores and counts computed from the selections."""
    activities = defaultdict(dict)
    for row in metrics:
        activities[row["activity_id"]][row["method"]] = row

    def cells(match):
        methods = activities[match.group(1)]
        values = [f"{methods[method]['f1']:.3f}" for method in ("prediction", "local", "minea")]
        for count in ("tp", "fp"):
            local = format(methods["local"][count], ",").replace(",", "{,}")
            minea = format(methods["minea"][count], ",").replace(",", "{,}")
            values.append(rf"${local}\to{minea}$")
        return " & ".join(values)

    layout = (HERE / "paper_activity_table.tex.in").read_text(encoding="utf-8")
    table = re.sub(r"@(CL[0-9]+|ALL)@", cells, layout)
    path.write_text(table, encoding="utf-8")


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=HERE.parents[2] / "datasets/dara-retrieval/logs/dara_retrieval_gt.csv")
    parser.add_argument("--selections", type=Path, default=HERE / "selections.csv")
    parser.add_argument("--candidates", type=Path, default=HERE.parent / "classifier/reference/fusion_top10_candidates.csv.gz")
    parser.add_argument("--rules", type=Path, default=HERE.parent / "constraints/selected_rules.csv")
    parser.add_argument("--rerun", type=Path, help="Also compare complete cases from a fresh matching selections CSV")
    parser.add_argument("--require-full-rerun", action="store_true",
                        help="Require --rerun to include every observation from all 53 cases")
    parser.add_argument("--output-dir", type=Path, help="Write recomputed per-case metrics, F1 table and summary")
    args = parser.parse_args()
    if args.require_full_rerun and not args.rerun:
        parser.error("--require-full-rerun requires --rerun")
    try:
        verify(args)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, f"Verification failed: {error}\n")
