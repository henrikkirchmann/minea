"""Encode the completed DaRA order for its area sources and coordinator."""
from collections import defaultdict
from fractions import Fraction
import subprocess
import time


def encode(raw):
    groups = defaultdict(list)
    for candidate in raw['candidates']:
        groups[candidate['observation']].append(candidate)
    obs = sorted(groups.values(), key=lambda g: (Fraction(g[0]['start']), g[0]['observation']))
    candidate_ids = []
    for i, group in enumerate(obs):
        assert len(group) == 10
        assert group == sorted(group, key=lambda c: (-Fraction(c['score']), c['label']))
        assert len({(c['owner'],c['start'],c['end']) for c in group}) == 1
        if i:
            assert Fraction(obs[i-1][0]['end']) <= Fraction(group[0]['start'])
        candidate_ids.extend(c['id'] for c in group)
    assert candidate_ids == [c['id'] for c in raw['candidates']]
    position = {candidate_id: k for k, candidate_id in enumerate(candidate_ids)}
    assert len(position) == len(candidate_ids)
    sources = list(dict.fromkeys(group[0]['owner'] for group in obs))
    source_rows = defaultdict(list)
    shared = []
    for row in raw['rows']:
        terms = sorted((position[c],int(v)) for c,v in row['coefficients'].items() if Fraction(v))
        owner_set = {obs[g//10][0]['owner'] for g,_ in terms}
        actual_owner = next(iter(owner_set)) if len(owner_set) == 1 else None
        assert actual_owner == row['owner']
        if actual_owner is None:
            shared.append((int(row['upper']),terms))
        else:
            source_rows[actual_owner].append((row,terms))
    out = [f'{len(obs)} {len(sources)} {len(shared)}']
    for source in sources:
        local = [i for i,group in enumerate(obs) if group[0]['owner'] == source]
        assignments, forbidden, needed = set(), set(), defaultdict(set)
        support_labels = set()
        for row,terms in source_rows[source]:
            upper = int(row['upper'])
            if row['id'].startswith('assignment::'):
                i = terms[0][0]//10
                assert terms == [(10*i+k,1) for k in range(10)] and upper == 1
                assignments.add(i)
                continue
            positive = [g for g,a in terms if a == 1]
            negative = [g for g,a in terms if a == -1]
            assert upper == 0 and len(positive) == 1 and len(terms) == 1 + len(negative)
            trigger, = positive
            if not negative:
                forbidden.add(trigger)
                continue
            labels = {obs[g//10][g%10]['label'] for g in negative}
            assert len(labels) == 1
            support, = labels
            # Check the private row really contains every earlier candidate of the
            # supporter activity, and only those. This makes a single seen bit exact.
            expected = [10*i+k for i in local if i < trigger//10
                        for k,c in enumerate(obs[i]) if c['label'] == support]
            assert negative == expected, (row['id'],negative,expected)
            needed[trigger].add(support)
            support_labels.add(support)
        assert assignments == set(local)
        state_bits = {label:1<<j for j,label in enumerate(sorted(support_labels))}
        out.append(f'{len(local)} {len(state_bits)}')
        for i in local:
            data = [i]
            for k,c in enumerate(obs[i]):
                g = 10*i+k
                score = Fraction(c['score']) * 181
                assert score.denominator == 1
                data.extend((score.numerator,state_bits.get(c['label'],0),
                             sum(state_bits[v] for v in needed.get(g,())),int(g in forbidden)))
            out.append(' '.join(map(str,data)))
    for upper, terms in shared:
        flattened = [upper,len(terms)]
        for g,a in terms: flattened.extend((g,a))
        out.append(' '.join(map(str,flattened)))
    return '\n'.join(out)+'\n', obs, sources


def solve(model, binary):
    config, observations, _ = encode(model)
    start = time.monotonic()
    completed = subprocess.run([str(binary)], input=config, text=True,
                               stdout=subprocess.PIPE, check=True)
    elapsed = time.monotonic() - start
    statistics, solution = completed.stdout.splitlines()
    combined, nodes, rounds, misses, ties, comparisons = map(int, statistics.split())
    digits = list(map(int, solution.split()))
    if len(digits) != len(observations) or any(d < 0 or d > 10 for d in digits):
        raise ValueError("Invalid ranks in coordinator output")
    labels = [group[10 - d]['label'] if d else ''
              for group, d in zip(observations, digits, strict=True)]
    chosen = [group[10 - d] for group, d in zip(observations, digits, strict=True) if d]
    units = sum(181 * candidate['score'] for candidate in chosen)
    if units * (len(digits) + 1) + digits.count(10) != combined:
        raise ValueError("Returned selections disagree with the coordinator objective")
    selected = {candidate['id'] for candidate in chosen}
    for row in model['rows']:
        lhs = sum(a for name, a in row['coefficients'].items() if name in selected)
        if lhs > row['upper']:
            raise ValueError(f"Returned selections violate {row['id']}")
    return labels, dict(visited_nodes=nodes, queried_nodes=rounds, source_cache_misses=misses,
                        compared_tied_bounds=ties, private_handle_comparisons=comparisons,
                        seconds=elapsed)
