"""Mine and rank the DaRA process constraints using the paper's nested predictions."""

import argparse
import csv
import gzip
import io
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE.parents[2] / "datasets/dara-retrieval/logs/dara_retrieval_gt.csv"
SCORES = HERE.parent / "classifier/reference/nested_scores.json.gz"

# These two published CC10 classes are absent from the 53 ground truth sequences.
UNOBSERVED = {"CL127": "Collecting Packed Cardboard Boxes",
              "CL152": "Tying Elastic Band Around Cardboard"}


def read_log(path):
    observations = defaultdict(list)
    sessions = {}
    names = dict(UNOBSERVED)
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            case = row["case:concept:name"]
            label = row["dara:activity_id"]
            session = row["case:dara:session"]
            if sessions.setdefault(case, session) != session:
                raise ValueError(f"Case {case} spans sessions")
            names[label] = row["concept:name"]
            observations[case].append((int(row["dara:start_frame"]), int(row["dara:end_frame"]),
                                       row["dara:observation_id"], label))

    for case, events in observations.items():
        events.sort()
        if any(a[1] > b[0] for a, b in zip(events, events[1:])):
            raise ValueError(f"Overlapping observations in {case}")
    return observations, sessions, names


def mine_prerequisites(sequences):
    """Intersect the sets of activities completed before each trigger's first occurrence."""
    preceding = {}
    for sequence in sequences:
        seen = set()
        for label in sequence:
            if label not in seen:
                if label in preceding:
                    preceding[label].intersection_update(seen)
                else:
                    preceding[label] = seen.copy()
                seen.add(label)
    return {(earlier, trigger) for trigger, supports in preceding.items() for earlier in supports}


def rule_id(earlier, trigger):
    # The archived observation-matching models use these two descriptive names.
    if (earlier, trigger) == ("CL124", "CL139"):
        return "retrieve_requires_assignment"
    if earlier is None:
        return "transport_to_pack_upper" if trigger == "CL129" else f"upper_{trigger}"
    return f"prereq_{earlier}_before_{trigger}"


def distance(predicted, truth):
    """Unit-cost Levenshtein distance. Equal endpoints do not affect the result."""
    start = 0
    end_pred = len(predicted)
    end_true = len(truth)
    while start < min(end_pred, end_true) and predicted[start] == truth[start]:
        start += 1
    while end_pred > start and end_true > start and predicted[end_pred-1] == truth[end_true-1]:
        end_pred -= 1
        end_true -= 1
    target = truth[start:end_true]
    prev = list(range(len(target) + 1))
    for i, label in enumerate(predicted[start:end_pred], 1):
        curr = [i]
        for j, actual in enumerate(target, 1):
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j-1] + (label != actual)))
        prev = curr
    return prev[-1]


class RankedOrder:
    """Maximum-score activity sequence subject to a single constraint."""

    def __init__(self, options):
        self.options = options
        self.top = tuple(row[0][0] for row in options)
        self.counts = Counter(self.top)
        self.first = {}
        for index, label in enumerate(self.top):
            self.first.setdefault(label, index)
        self.ranks = [{label: rank for rank, (label, _) in enumerate(row)} for row in options]
        self.suffix_scores = [0] * (len(options) + 1)
        for i in reversed(range(len(options))):
            self.suffix_scores[i] = options[i][0][1] + self.suffix_scores[i + 1]

    def upper_bound(self, label, maximum):
        if self.counts[label] <= maximum:
            return self.top
        matches = [i for i, activity in enumerate(self.top) if activity == label]
        # Keep rank one where changing to rank two would sacrifice most score.
        # Stable sorting favors keeping earlier first choices when margins tie.
        matches.sort(key=lambda i: self.options[i][0][1] - self.options[i][1][1], reverse=True)
        chosen = list(self.top)
        for i in matches[maximum:]:
            chosen[i] = self.options[i][1][0]
        return tuple(chosen)

    def prerequisite(self, earlier, trigger):
        n = len(self.top)
        if self.first.get(trigger, n) >= self.first.get(earlier, n):
            return self.top

        # Before the first earlier activity we can wait or select that activity now.
        # Once selected, every remaining observation may take its first choice.
        waiting = [None] * n
        take_earlier = [False] * n
        score = retained = 0
        for i in reversed(range(n)):
            options = self.options[i]
            other = next(rank for rank, (label, _) in enumerate(options)
                         if label not in (earlier, trigger))
            waiting[i] = options[other][0]
            best = (options[other][1] + score, int(other == 0) + retained, -other)
            rank = self.ranks[i].get(earlier)
            if rank is not None:
                take = (options[rank][1] + self.suffix_scores[i + 1],
                        int(rank == 0) + n - i - 1, -rank)
                if take > best:
                    best = take
                    take_earlier[i] = True
            score, retained, _ = best
        for i, take in enumerate(take_earlier):
            if take:
                return tuple(waiting[:i]) + (earlier,) + self.top[i + 1:]
        return tuple(waiting)


def mine(observations, sessions, names, predictions):
    sequences = {case: tuple(row[3] for row in rows) for case, rows in observations.items()}
    counts = {case: Counter(trace) for case, trace in sequences.items()}
    folds = sorted(set(sessions.values()), key=int)
    if set(folds) != set(predictions):
        raise ValueError("Ground truth sessions differ from the prediction folds")
    training = {s: [c for c in sequences if sessions[c] != s] for s in folds}
    pairs = set.intersection(*(mine_prerequisites(sequences[c] for c in training[s]) for s in folds))
    rules = pairs | {(None, label) for label in names}

    fold_max = {s: {label: max(counts[c][label] for c in training[s]) for label in names}
                for s in folds}
    maximum = {label: max(fold_max[s][label] for s in folds) for label in names}
    support = {label: sum(label in count for count in counts.values()) for label in names}
    fold_support = {s: {label: sum(label in counts[c] for c in training[s]) for label in names}
                    for s in folds}
    gains = {s: Counter() for s in folds}
    eligible = {key: True for key in rules}
    for outer in folds:
        if set(training[outer]) != set(predictions[outer]):
            raise ValueError(f"Unexpected cases in prediction fold {outer}")
        # Validation for one of the five training sessions used the remaining four.
        seen_in_fit = {}
        for validation in set(folds) - {outer}:
            seen_in_fit[validation] = set().union(*(counts[c].keys() for c in training[outer]
                                                   if sessions[c] != validation))
        for case in training[outer]:
            options = predictions[outer][case]
            ids = [row[2] for row in observations[case]]
            if set(ids) != set(options):
                raise ValueError(f"Observation IDs differ in {case}, fold {outer}")
            rows = [options[obs] for obs in ids]
            for row in rows:
                if len(row) != 10 or len({v for v, w in row}) != 10 or any(
                    v not in names or not isinstance(w, int) or w <= 0 for v, w in row
                ) or row != sorted(row, key=lambda entry: (-entry[1], entry[0])):
                    raise ValueError(f"Invalid ranked candidates in {case}, fold {outer}")

            order = RankedOrder(rows)
            truth = sequences[case]
            baseline = distance(order.top, truth)
            errors = {order.top: baseline}
            for earlier, trigger in rules:
                if earlier is None:
                    selected = order.upper_bound(trigger, maximum[trigger])
                elif trigger in seen_in_fit[sessions[case]]:
                    selected = order.prerequisite(earlier, trigger)
                else:
                    eligible[earlier, trigger] = False
                    continue
                if selected not in errors:
                    errors[selected] = distance(selected, truth)
                gains[outer][earlier, trigger] += baseline - errors[selected]

    ranked = []
    for earlier, trigger in rules:
        upper = earlier is None
        row = dict(rule_id=rule_id(earlier, trigger), query_type="upper" if upper else "prerequisite",
                   prerequisite_id=earlier, prerequisite=names.get(earlier), trigger_or_capped_id=trigger,
                   trigger_or_capped_activity=names[trigger], maximum=maximum[trigger] if upper else None,
                   eligible=eligible[earlier, trigger], support_orders=support[trigger],
                   total_edits_saved=sum(gains[s][earlier, trigger] for s in folds))
        for s in folds:
            row[f"fold_{s}_gain"] = gains[s][earlier, trigger]
            row[f"fold_{s}_support_orders"] = fold_support[s][trigger]
            row[f"fold_{s}_observed_max"] = fold_max[s][trigger] if upper else None
        ranked.append(row)
    ranked.sort(key=lambda r: (-r["total_edits_saved"], -r["support_orders"], r["rule_id"]))

    selected = []
    remaining = {"upper": 2, "prerequisite": 8}
    for row in ranked:
        kind = row["query_type"]
        if row["eligible"] and remaining[kind]:
            selected.append(row)
            remaining[kind] -= 1
    if any(remaining.values()):
        raise ValueError("Too few eligible constraints to fill both quotas")
    return ranked, selected


def csv_text(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=LOG, help="ground truth event CSV")
    parser.add_argument("--nested-scores", "--scores", dest="scores", type=Path, default=SCORES,
                        help="nested candidate scores (.json.gz)")
    parser.add_argument("--output-dir", type=Path, help="write regenerated tables and templates here")
    args = parser.parse_args()
    observations, sessions, names = read_log(args.log)
    with gzip.open(args.scores, "rt", encoding="utf-8") as source:
        predictions = json.load(source)
    ranked, selected = mine(observations, sessions, names, predictions)
    templates = []
    for row in selected:
        trigger, earlier = row["trigger_or_capped_id"], row["prerequisite_id"]
        if row["query_type"] == "upper":
            rule = dict(kind="cardinality", labels=[trigger], upper=row["maximum"])
        else:
            rule = dict(kind="prerequisite", trigger=trigger, labels=[earlier])
        templates.append(dict(**rule, id=row["rule_id"]))
    chosen = {row["rule_id"] for row in selected}
    outputs = {
        "common_rules.csv": csv_text([dict(selected=row["rule_id"] in chosen, **row) for row in ranked]),
        "selected_rules.csv": csv_text(selected),
        "rule_templates.json": json.dumps(templates, indent=2) + "\n",
    }
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, content in outputs.items():
            (args.output_dir / name).write_text(content, encoding="utf-8")
    else:
        for name, content in outputs.items():
            if (HERE / name).read_text(encoding="utf-8") != content:
                raise SystemExit(f"Recorded result differs: {name}")
    count = sum(len(cases) for cases in predictions.values())
    print(f"{len(ranked)} common constraints, {len(selected)} selected, {count} validation order predictions.")
    print(f"Results written to {args.output_dir}." if args.output_dir else "All three recorded outputs reproduced.")


if __name__ == "__main__":
    main()
