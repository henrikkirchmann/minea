"""Finite message-state reference for the manuscript's process-rule constructors.

The input contains only completed cases, with no constraint linking an included
case to an excluded one. These closure conditions are supplied by the application.
No networking, timing, or privacy guarantee is implemented. Dictionaries exposed
by Construction are audit views; only shared row fragments reach the simulated
coordinator. Exact arithmetic is used throughout.
"""
from dataclasses import dataclass, field
from fractions import Fraction
from collections import Counter, defaultdict
import json
import random


def rational(value):
    return value if isinstance(value, Fraction) else Fraction(str(value))


def row_identity(rule_id, side):
    """Injective serialization of a rule identity and its inequality side.

    Text concatenation is unsafe: a rule named 'foo:lower' must differ
    from the lower-cardinality row of the rule named 'foo'.
    """
    if not isinstance(rule_id, str) or side not in {"body", "lower", "upper"}:
        raise ValueError("invalid structured row identity")
    return json.dumps([rule_id, side], separators=(",", ":"))


@dataclass(frozen=True)
class Candidate:
    id: str
    owner: str
    observation: str
    case: str
    label: str
    start: Fraction
    end: Fraction
    score: Fraction

    def __post_init__(self):
        for name in ("start", "end", "score"):
            object.__setattr__(self, name, rational(getattr(self, name)))
        if self.start > self.end:
            raise ValueError("candidate start exceeds completion")


@dataclass(frozen=True)
class Rule:
    id: str
    kind: str
    case: str
    trigger: str | None = None
    labels: frozenset = field(default_factory=frozenset)
    lower: int | None = None
    upper: int | None = None
    lo: Fraction = Fraction(0)
    hi: Fraction | None = None

    def __post_init__(self):
        object.__setattr__(self, "labels", frozenset(self.labels))
        object.__setattr__(self, "lo", rational(self.lo))
        if self.hi is not None:
            object.__setattr__(self, "hi", rational(self.hi))
        if self.kind not in {"prerequisite", "cardinality", "uniqueness", "response"}:
            raise ValueError("unsupported template")
        if self.lo < 0 or (self.hi is not None and self.hi < self.lo):
            raise ValueError("invalid time range")
        if self.kind == "response" and self.hi is None:
            raise ValueError("bounded response needs finite deadline")
        for bound in (self.lower, self.upper):
            if bound is not None and (int(bound) != bound or bound < 0):
                raise ValueError("cardinality bounds must be nonnegative integers")
        if self.kind == "cardinality" and self.lower is None and self.upper is None:
            raise ValueError("cardinality needs at least one bound")
        if self.kind == "uniqueness" and len(self.labels) != 1:
            raise ValueError("designated uniqueness requires one label")


@dataclass(frozen=True)
class TriggerHeader:
    """Lookup fields received by candidate holders; no score or observation.

    Anchor is trigger start for a prerequisite and completion for a response.
    The rule supplies the accepted labels and the temporal bounds separately.
    """
    id: str
    anchor: Fraction


@dataclass(frozen=True)
class Row:
    id: str
    coefficients: tuple
    bound: Fraction
    owner: str | None

    @property
    def rhs(self):
        return self.bound

    def to_dict(self):
        return {"id": self.id, "coefficients": dict(self.coefficients),
                "upper": self.bound, "rhs": self.bound, "owner": self.owner}


class Incomplete(RuntimeError):
    pass


class ReplySet:
    """Receive one immutable logical answer from every expected source."""
    def __init__(self, expected):
        self.expected = frozenset(expected)
        self.received = {}
        self.duplicates = 0

    def receive(self, source, value):
        if source not in self.expected:
            raise ValueError("unexpected sender")
        if source in self.received:
            if self.received[source] != value:
                raise ValueError("conflicting duplicate")
            self.duplicates += 1
        self.received[source] = value

    def complete(self):
        if set(self.received) != self.expected:
            raise Incomplete("expected source reply missing")
        return dict(self.received)


@dataclass
class Construction:
    candidates: tuple
    rows: tuple
    directories: dict
    messages: dict
    states: dict
    upload_log: tuple

    @property
    def local_rows(self):
        return tuple(r for r in self.rows if r.owner is not None)

    @property
    def shared_rows(self):
        return tuple(r for r in self.rows if r.owner is None and r.coefficients)

    @property
    def constants(self):
        return tuple(r for r in self.rows if not r.coefficients)

    @property
    def infeasible_constant(self):
        return any(r.bound < 0 for r in self.constants)

    def to_dict(self):
        return {"candidates": [vars(v) for v in self.candidates],
                "rows": [r.to_dict() for r in self.rows],
                "directories": self.directories, "messages": self.messages}


def _candidate(value):
    if isinstance(value, Candidate):
        return value
    value = dict(value)
    if "score" not in value:
        value["score"] = value.pop("weight")
    return Candidate(**value)


def _rule(value):
    return value if isinstance(value, Rule) else Rule(**value)


def _deliver(messages, receiver, rng, duplicate, count, kind):
    deliveries = list(messages)
    count[kind + "_logical"] += len(deliveries)
    if duplicate:
        deliveries += list(deliveries)
    rng.shuffle(deliveries)
    for sender, payload in deliveries:
        receiver.receive(sender, payload)
    count[kind + "_deliveries"] += len(deliveries)
    count["duplicate_deliveries"] += receiver.duplicates


def _local_fragment(rule, local_candidates, trigger):
    """Executed at one owner, without other owners' candidate records."""
    if rule.kind in {"prerequisite", "response"} and not isinstance(trigger, TriggerHeader):
        raise TypeError("lookup requires a header, not a remote candidate record")
    result = {}
    for u in local_candidates:
        if u.case != rule.case:
            continue
        if rule.kind in {"cardinality", "uniqueness"}:
            if u.label in rule.labels:
                result[u.id] = Fraction(1)
            continue
        if u.id == trigger.id:
            result[u.id] = Fraction(1)
            continue
        if u.label not in rule.labels:
            continue
        # The configured interval measures response completion. A response
        # that starts within the interval but finishes after it is ineligible.
        if rule.kind == "response" and u.start < trigger.anchor:
            continue
        age = trigger.anchor - u.end if rule.kind == "prerequisite" else u.end - trigger.anchor
        if age >= rule.lo and (rule.hi is None or age <= rule.hi):
            result[u.id] = Fraction(-1)
    return tuple(sorted(result.items()))


def instantiate(candidates, rules, sources=None, cases=None, cutoff=Fraction(100),
                seed=0, duplicate=True, batch_start=Fraction(0)):
    """Construct rows, with complete advertising and two-stage row settlement.

    Cases include candidate-free configured cases. The simulated registrar sees
    source presence only; singleton fragments remain local. Returned local rows
    are an audit view used by the local reference oracles, not a wire transcript.
    All supplied rules apply to completed cases. A response is enforced even
    when its deadline exceeds cutoff: no later observation for that case will
    arrive. The caller certifies case completion, complete supplied observations,
    and absence of constraint links to excluded cases; these cannot be inferred
    from candidate records. Visible candidate times are checked against the batch.
    """
    candidates = tuple(_candidate(v) for v in candidates)
    candidate_map = {v.id: v for v in candidates}
    if len(candidate_map) != len(candidates):
        raise ValueError("candidate identifiers must be unique")
    cutoff, batch_start = rational(cutoff), rational(batch_start)
    if batch_start > cutoff:
        raise ValueError("batch start exceeds cutoff")
    if any(v.start < batch_start or v.end > cutoff for v in candidates):
        raise ValueError("candidate outside completed-case batch window")
    source_set = frozenset(sources if sources is not None else (v.owner for v in candidates))
    if any(v.owner not in source_set for v in candidates):
        raise ValueError("unknown candidate owner")
    raw_rules = tuple(_rule(r) for r in rules)
    rule_map = {}
    count = Counter()
    for rule in raw_rules:
        if rule.id in rule_map:
            if rule_map[rule.id] != rule:
                raise ValueError("conflicting rule identity")
            count["duplicate_rule_requests"] += 1
        rule_map[rule.id] = rule
    case_set = frozenset(cases if cases is not None else
                         {v.case for v in candidates} | {r.case for r in raw_rules})
    if any(v.case not in case_set for v in candidates) or any(r.case not in case_set for r in raw_rules):
        raise ValueError("case missing from frozen catalog")
    local = {k: tuple(v for v in candidates if v.owner == k) for k in source_set}
    rng = random.Random(seed)
    directories = {}
    for j in sorted(case_set):
        advertisements = ReplySet(source_set)
        _deliver([(k, any(v.case == j for v in local[k])) for k in sorted(source_set)],
                 advertisements, rng, duplicate, count, "advertisement")
        advertised = advertisements.complete()
        directories[j] = tuple(sorted(k for k, present in advertised.items() if present))
    rows, states, uploads = [], {}, []
    for rule in sorted(rule_map.values(), key=lambda r: r.id):
        header = None
        if rule.kind in {"prerequisite", "response"}:
            if rule.trigger not in candidate_map:
                raise ValueError("rule trigger is not a supplied candidate")
            trigger = candidate_map[rule.trigger]
            if trigger.case != rule.case:
                raise ValueError("trigger case mismatch")
            header = TriggerHeader(trigger.id, trigger.start if rule.kind == "prerequisite" else trigger.end)
        states[rule.id] = "DISCOVERING"
        # Sources retain these fragments. The registrar receives only booleans.
        fragments = {k: _local_fragment(rule, local[k], header) for k in directories[rule.case]}
        presence = ReplySet(directories[rule.case])
        count["query_logical"] += len(presence.expected)
        _deliver([(k, bool(fragments[k])) for k in sorted(presence.expected)],
                 presence, rng, duplicate, count, "presence_reply")
        present = presence.complete()
        owners = tuple(sorted(k for k, yes in present.items() if yes))
        coefficients = {}
        if len(owners) >= 2:
            states[rule.id] = "WAITING_FRAGMENTS"
            received = ReplySet(owners)
            _deliver([(k, fragments[k]) for k in owners], received, rng, duplicate, count, "shared_fragment")
            for k, fragment in received.complete().items():
                for candidate_id, coefficient in fragment:
                    if candidate_map[candidate_id].owner != k or candidate_id in coefficients:
                        raise ValueError("invalid fragment ownership")
                    coefficients[candidate_id] = coefficient
                uploads.append((rule.id, k, fragment))
            placement = None
            states[rule.id] = "SETTLED_SHARED"
        elif owners:
            placement = owners[0]
            coefficients = dict(fragments[placement])
            states[rule.id] = "SETTLED_LOCAL"
        else:
            placement = None
            states[rule.id] = "SETTLED_CONSTANT"
        if rule.kind in {"prerequisite", "response"}:
            specs = [(row_identity(rule.id, "body"), Fraction(1), Fraction(0))]
        else:
            lower = rule.lower if rule.kind == "cardinality" else None
            upper = rule.upper if rule.kind == "cardinality" else 1
            specs = []
            if lower is not None:
                specs.append((row_identity(rule.id, "lower"), Fraction(-1), -Fraction(lower)))
            if upper is not None:
                specs.append((row_identity(rule.id, "upper"), Fraction(1), Fraction(upper)))
        for row_id, sign, bound in specs:
            rows.append(Row(row_id, tuple(sorted((v, sign * a) for v, a in coefficients.items())), bound, placement))
        count["settled_rule_instances"] += 1
        count["installation_logical"] += 1
    # All supplied config rules and all candidate-triggered requests are known.
    # This finite reference executes every rule before declaring construction done.
    count["local_rows"] = sum(r.owner is not None for r in rows)
    count["shared_rows"] = sum(r.owner is None and bool(r.coefficients) for r in rows)
    count["constant_rows"] = sum(not r.coefficients for r in rows)
    count["shared_nonzeros"] = sum(len(r.coefficients) for r in rows if r.owner is None)
    return Construction(candidates, tuple(rows), directories, dict(count), states, tuple(uploads))


def dependency_components(candidates, local_rows, cases):
    """Case-level decomposition from complete local row scopes.

    The supported shared templates stay within one case. A new cross-case shared
    template would also have to contribute its case edges here before separation.
    """
    candidate_map = {v.id: v for v in map(_candidate, candidates)}
    graph = {j: set() for j in cases}
    for row in local_rows:
        scope = {candidate_map[v].case for v, a in row.coefficients if a}
        for j in scope:
            graph[j].update(scope - {j})
    components, unseen = [], set(graph)
    while unseen:
        stack, component = [min(unseen)], set()
        while stack:
            j = stack.pop()
            if j in component:
                continue
            component.add(j)
            stack.extend(graph[j] - component)
        unseen -= component
        components.append(tuple(sorted(component)))
    return tuple(components)
