"""Sequential execution of the paper's logical construction protocol.

Sources retain their own candidates and row fragments. Case agents discover
directories and contributors; coordinators receive coefficients only for shared
rows. All counters are incremented by executed actions, before any batching or
presolve. This module deliberately has no dependency on a central encoder.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import combinations


STAGES = (
    "candidate_owner_discovery", "case_edge_discovery", "coordinator_election",
    "notification_registration", "intra_case_row_construction",
    "construction_completion",
)
_COMMON_COUNTS = (
    "messages", "payload_records", "coefficient_terms", "colocated_messages",
    "cross_host_messages",
)
_STAGE_COUNTS = {
    STAGES[0]: ("source_case_registrations", "directory_entries"),
    STAGES[1]: (
        "given_local_rows", "given_local_terms", "given_empty_rows",
        "given_empty_checks_passed", "given_empty_checks_failed",
        "type2_rows", "edge_announcements", "unique_undirected_edges",
        "duplicate_announcements", "duplicate_edge_reports",
    ),
    STAGES[2]: ("configured_rounds", "rank_transmissions"),
    STAGES[3]: (
        "directory_notifications", "case_agent_registrations", "source_registrations",
    ),
    STAGES[4]: (
        "trigger_requests", "bound_initiations", "omitted_zero_lower_rows",
        "lookup_requests", "positive_presence_replies", "negative_presence_replies",
        "retained_fragments", "retained_coefficient_terms", "shared_fragment_transfers",
        "transferred_coefficient_terms", "local_rows", "shared_rows", "empty_rows",
        "empty_row_checks", "empty_row_checks_passed", "empty_row_checks_failed",
    ),
    STAGES[5]: (
        "placement_instructions", "local_placement_instructions",
        "shared_transfer_instructions", "shared_row_announcements",
        "row_storage_acknowledgments", "case_agent_completion_records",
        "coordinators_ready", "coordinators_infeasible",
    ),
}


def _integer(value, label, nonnegative=False):
    if type(value) is not int or (nonnegative and value < 0):
        raise ValueError(f"{label} must be an exact {'nonnegative ' if nonnegative else ''}integer")
    return value


def _identifier(value, label):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _empty_counts():
    return {
        stage: Counter({name: 0 for name in _COMMON_COUNTS + _STAGE_COUNTS[stage]})
        for stage in STAGES
    }


def _add_counts(target, other):
    for stage in STAGES:
        for key, value in other[stage].items():
            target[stage][key] += value


def _summarize(stages):
    totals = Counter()
    for stage in STAGES:
        for key, value in stages[stage].items():
            totals[key] += value
    return {"stages": {s: dict(stages[s]) for s in STAGES}, "totals": dict(totals)}


def _maxima(records):
    result = _empty_counts()
    totals = Counter()
    for record in records.values():
        for stage in STAGES:
            for key, value in record["stages"][stage].items():
                result[stage][key] = max(result[stage][key], value)
        for key, value in record["totals"].items():
            totals[key] = max(totals[key], value)
    return {"stages": {s: dict(result[s]) for s in STAGES}, "totals": dict(totals)}


class _Ledger:
    """Count deliveries/actions as they happen, then attribute them to winners."""

    def __init__(self, cases, sources, trace):
        self.stages = _empty_counts()
        self.by_case = {case: _empty_counts() for case in cases}
        self.physical_hosts = {source: Counter() for source in sources}
        self.trace_enabled = trace
        self.trace = []
        self.message_count = 0
        self.round = 0

    def count(self, stage, key, case=None, amount=1):
        self.stages[stage][key] += amount
        if case is not None:
            self.by_case[case][stage][key] += amount

    def send(self, stage, kind, sender, receiver, payload, case, terms=0, stage_round=1):
        self.message_count += 1
        colocated = sender["host"] == receiver["host"]
        for name, amount in (
            ("messages", 1), ("payload_records", 1), ("coefficient_terms", terms),
            ("colocated_messages" if colocated else "cross_host_messages", 1),
        ):
            self.count(stage, name, case, amount)
        self.physical_hosts[sender["host"]]["messages_sent"] += 1
        self.physical_hosts[sender["host"]]["coefficient_terms_sent"] += terms
        self.physical_hosts[receiver["host"]]["messages_received"] += 1
        self.physical_hosts[receiver["host"]]["coefficient_terms_received"] += terms
        if colocated:
            self.physical_hosts[sender["host"]]["colocated_deliveries"] += 1
        if self.trace_enabled:
            self.trace.append({
                "sequence": self.message_count, "stage": stage, "round": self.round,
                "stage_round": stage_round, "kind": kind, "sender": sender,
                "receiver": receiver, "case_id": case, "payload": payload,
                "payload_records": 1, "coefficient_terms": terms,
                "colocated": colocated,
            })

    def finish(self, components, case_components, rounds):
        component_counts = {item["id"]: _empty_counts() for item in components}
        for case, counts in self.by_case.items():
            _add_counts(component_counts[case_components[case]], counts)
        host_counts = {source: _empty_counts() for source in self.physical_hosts}
        for component in components:
            _add_counts(host_counts[component["coordinator"]], component_counts[component["id"]])
        # Configured rounds measure a common logical clock, not additive work.
        for counts in component_counts.values():
            counts[STAGES[2]]["configured_rounds"] = rounds
        coordinator_hosts = {item["coordinator"] for item in components}
        for host, counts in host_counts.items():
            counts[STAGES[2]]["configured_rounds"] = rounds if host in coordinator_hosts else 0
        per_component = {key: _summarize(value) for key, value in component_counts.items()}
        per_host = {str(key): _summarize(value) for key, value in host_counts.items()}
        for message in self.trace:
            message["component_id"] = case_components.get(message["case_id"])
        result = _summarize(self.stages)
        result.update({
            "per_component": per_component, "per_host": per_host,
            "physical_hosts": {str(key): dict(value) for key, value in self.physical_hosts.items()},
            "maxima": {"per_component": _maxima(per_component), "per_host": _maxima(per_host)},
            "counting_convention": (
                "One directed role-to-role delivery is one message and one payload record, "
                "including co-located roles; coefficient terms are counted separately. "
                "Per-host work sums components assigned to that coordinator host. "
                "Configured rounds are a shared clock and are not additive."
            ),
        })
        return result


@dataclass
class _Source:
    host: int
    candidates: dict = field(default_factory=dict)
    by_case: dict = field(default_factory=lambda: defaultdict(dict))
    given_rows: dict = field(default_factory=dict)
    rows: dict = field(default_factory=dict)
    fragments: dict = field(default_factory=dict)
    components: dict = field(default_factory=dict)

    @property
    def role(self):
        return {"role": "source", "id": str(self.host), "host": self.host}

    def lookup(self, request):
        """The only candidate search used by row construction is source-local."""
        terms = {}
        for candidate in self.by_case.get(request["case_id"], {}).values():
            if request["kind"] == "prerequisite":
                if candidate["id"] == request["trigger_id"]:
                    terms[candidate["id"]] = 1
                elif candidate["activity"] in request["activities"]:
                    delay = request["trigger_start"] - candidate["end"]
                    if delay >= request.get("min_delay", 0) and (
                        request.get("max_delay") is None or delay <= request["max_delay"]
                    ):
                        terms[candidate["id"]] = -1
            elif candidate["activity"] in request["activities"]:
                terms[candidate["id"]] = 1 if request["kind"] == "occurrence_upper" else -1
        self.fragments[request["id"]] = terms
        return bool(terms)


@dataclass
class _CaseAgent:
    case: str
    host: int
    directory: set = field(default_factory=set)
    neighbors: dict = field(default_factory=dict)
    rank: tuple = field(init=False)
    requests: dict = field(default_factory=dict)
    presence: dict = field(default_factory=dict)
    completed_rows: set = field(default_factory=set)
    failed_rows: set = field(default_factory=set)

    def __post_init__(self):
        self.rank = (self.host, self.case)

    @property
    def role(self):
        return {"role": "case_agent", "id": self.case, "host": self.host}


@dataclass
class _Coordinator:
    id: str
    host: int
    winning_case: str
    cases: set = field(default_factory=set)
    sources: set = field(default_factory=set)
    announced_rows: dict = field(default_factory=dict)
    fragments: dict = field(default_factory=lambda: defaultdict(dict))
    rows: dict = field(default_factory=dict)
    case_completions: dict = field(default_factory=dict)
    given_rows_valid: bool = True

    @property
    def role(self):
        return {"role": "coordinator", "id": self.id, "host": self.host}


def _prepare(instance):
    cases = [_identifier(case, "case ID") for case in instance["cases"]]
    source_ids = [_integer(source, "source ID", True) for source in instance["sources"]]
    if len(set(cases)) != len(cases) or len(set(source_ids)) != len(source_ids):
        raise ValueError("Case and source IDs must be unique")
    sources = {source: _Source(source) for source in sorted(source_ids)}
    agents = {}
    for case in sorted(cases):
        host = _integer(instance["case_hosts"][case], "case-agent host", True)
        if host not in sources:
            raise ValueError(f"Unknown case-agent host {host}")
        agents[case] = _CaseAgent(case, host)
    owners, candidate_cases, observations = {}, {}, {}
    for original in sorted(instance["candidates"], key=lambda item: item["id"]):
        candidate = dict(original)
        ident = _identifier(candidate["id"], "candidate ID")
        case = candidate["case_id"]
        owner = _integer(candidate["owner"], "candidate owner", True)
        if ident in owners:
            raise ValueError(f"Duplicate candidate ID {ident}; ownership must be unique")
        if owner not in sources or case not in agents:
            raise ValueError(f"Unknown candidate owner or case for {ident}")
        start = _integer(candidate["start"], "candidate start")
        end = _integer(candidate["end"], "candidate end")
        if end < start:
            raise ValueError(f"Candidate interval ends before its start: {ident}")
        observation = _identifier(candidate["observation_id"], "observation ID")
        _identifier(candidate["activity"], "activity ID")
        if observation in observations and observations[observation] != (owner, case):
            raise ValueError(f"Observation {observation} must have one owner and case")
        observations[observation] = (owner, case)
        owners[ident], candidate_cases[ident] = owner, case
        sources[owner].candidates[ident] = candidate
        sources[owner].by_case[case][ident] = candidate
    rows = {}
    row_scopes = {}
    for original in sorted(instance.get("given_rows", []), key=lambda item: item["id"]):
        ident = _identifier(original["id"], "row ID")
        if ident in rows:
            raise ValueError(f"Duplicate row ID {ident}")
        if original["kind"] not in {"assignment", "exclusion"}:
            raise ValueError("Given rows must be assignment or exclusion rows")
        terms = {}
        for candidate, coefficient in sorted(original["terms"].items()):
            _integer(coefficient, "row coefficient")
            if candidate not in owners:
                raise ValueError(f"Unknown candidate {candidate} in row {ident}")
            if coefficient:
                terms[candidate] = coefficient
        row = {
            "id": ident, "kind": original["kind"], "terms": terms,
            "upper": _integer(original["upper"], "row upper bound"),
            "case_id": original.get("case_id"),
        }
        if row["case_id"] is not None and row["case_id"] not in agents:
            raise ValueError(f"Unknown row case {row['case_id']}")
        row_sources = {owners[candidate] for candidate in terms}
        if len(row_sources) > 1:
            raise ValueError(f"Given row {ident} is not local to one source")
        scope = sorted({candidate_cases[candidate] for candidate in terms})
        if not scope and row["case_id"] is not None:
            scope = [row["case_id"]]
        if not scope:
            raise ValueError(f"Empty given row {ident} needs an explicit case_id")
        source = next(iter(row_sources)) if row_sources else agents[scope[0]].host
        sources[source].given_rows[ident] = row
        sources[source].rows[ident] = row
        rows[ident], row_scopes[ident] = row, scope
    for category in ("prerequisites", "occurrence_bounds"):
        templates = instance.get(category, [])
        identifiers = [_identifier(item["id"], "template ID") for item in templates]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError(f"Duplicate {category} template ID")
        for template in templates:
            if category == "prerequisites":
                _identifier(template["trigger_activity"], "trigger activity")
                for activity in template["predecessor_activities"]:
                    _identifier(activity, "predecessor activity")
                for key in ("min_delay", "max_delay"):
                    if template.get(key) is not None:
                        _integer(template[key], key, True)
            else:
                for activity in template["activities"]:
                    _identifier(activity, "occurrence activity")
                for key in ("lower", "upper"):
                    if template.get(key) is not None:
                        _integer(template[key], f"occurrence {key}", True)
    return sources, agents, rows, row_scopes


def _row(request, terms):
    return {
        "id": request["id"], "kind": request["kind"],
        "terms": dict(sorted(terms.items())), "upper": request["upper"],
        "case_id": request["case_id"],
    }


def construct(instance: dict, trace: bool = False) -> dict:
    """Execute discovery, election, lookup, storage, and completion rounds.

    ``rows`` retains checked empty rows, including any failed positive minimum.
    An infeasible result is completed construction with ``status='infeasible'``;
    it must not be sent to matching as a ready model. Scores are never changed.
    ``per_host`` attributes a component's work to its coordinator's physical host;
    ``physical_hosts`` separately reports where messages were sent and received.
    """
    sources, agents, rows, given_scopes = _prepare(instance)
    ledger = _Ledger(agents, sources, trace)
    contributors, row_owners, empty_checks = {}, {}, {}
    failed_empty_rows = set()

    # Owner discovery: a source sends one identity for each case it holds.
    stage = STAGES[0]
    ledger.round += 1
    for source in sources.values():
        for case in sorted(source.by_case):
            agent = agents[case]
            ledger.send(stage, "source_case_registration", source.role, agent.role,
                        {"case_id": case, "source": source.host}, case)
            ledger.count(stage, "source_case_registrations", case)
            agent.directory.add(source.host)
            ledger.count(stage, "directory_entries", case)

    # Edge reports are generated by local row owners, then deduplicated by agents.
    stage = STAGES[1]
    ledger.round += 1
    for source in sources.values():
        for ident, row in source.given_rows.items():
            scope = sorted({source.candidates[candidate]["case_id"] for candidate in row["terms"]})
            if not scope:
                scope = given_scopes[ident]
            ledger.count(stage, "given_local_rows", scope[0])
            ledger.count(stage, "given_local_terms", scope[0], len(row["terms"]))
            contributors[ident] = [source.host] if row["terms"] else []
            row_owners[ident] = {
                "classification": "given_local" if row["terms"] else "empty",
                "source": source.host if row["terms"] else None, "case_id": scope[0],
            }
            if not row["terms"]:
                ledger.count(stage, "given_empty_rows", scope[0])
                empty_checks[ident] = row["upper"] >= 0
                ledger.count(stage, "given_empty_checks_passed" if empty_checks[ident] else
                             "given_empty_checks_failed", scope[0])
                if not empty_checks[ident]:
                    failed_empty_rows.add(ident)
                    agents[scope[0]].failed_rows.add(ident)
            if len(scope) > 1:
                ledger.count(stage, "type2_rows", scope[0])
            for left, right in combinations(scope, 2):
                for case, other in ((left, right), (right, left)):
                    agent = agents[case]
                    ledger.send(stage, "edge_announcement", source.role, agent.role, {
                        "row_id": ident, "case_id": case, "neighbor": other,
                        "neighbor_host": agents[other].host,
                    }, case)
                    ledger.count(stage, "edge_announcements", case)
                    duplicate = other in agent.neighbors
                    if duplicate:
                        ledger.count(stage, "duplicate_announcements", case)
                    if case == left:
                        ledger.count(stage, "duplicate_edge_reports" if duplicate else
                                     "unique_undirected_edges", case)
                    agent.neighbors[other] = agents[other].host

    # Snapshot every rank before sending. Processing an inbox never changes a
    # message already sent in this round, even in this sequential simulator.
    stage = STAGES[2]
    election_rounds = max(0, len(agents) - 1)
    for iteration in range(1, election_rounds + 1):
        ledger.round += 1
        ledger.count(stage, "configured_rounds")
        snapshot = {case: agent.rank for case, agent in agents.items()}
        inboxes = {case: [] for case in agents}
        for case, agent in agents.items():
            for neighbor in sorted(agent.neighbors):
                ledger.send(stage, "rank_transmission", agent.role, agents[neighbor].role,
                            {"rank": list(snapshot[case]), "coordinator": snapshot[case][0]},
                            case, stage_round=iteration)
                ledger.count(stage, "rank_transmissions", case)
                inboxes[neighbor].append(snapshot[case])
        for case, agent in agents.items():
            agent.rank = min([snapshot[case]] + inboxes[case])

    # Winning pairs distinguish disconnected components sharing a physical host.
    coordinators, case_components = {}, {}
    for case, agent in agents.items():
        host, winner = agent.rank
        ident = f"component:{host}:{winner}"
        case_components[case] = ident
        if ident not in coordinators:
            coordinators[ident] = _Coordinator(ident, host, winner)
    for owner in row_owners.values():
        owner["component_id"] = case_components[owner.pop("case_id")]

    stage = STAGES[3]
    ledger.round += 1
    for case, agent in agents.items():
        coordinator = coordinators[case_components[case]]
        for owner in sorted(agent.directory):
            source = sources[owner]
            ledger.send(stage, "directory_notification", agent.role, source.role, {
                "case_id": case, "component_id": coordinator.id,
                "coordinator": coordinator.host,
            }, case)
            ledger.count(stage, "directory_notifications", case)
            source.components[case] = coordinator.id
    ledger.round += 1
    for case, agent in agents.items():
        coordinator = coordinators[case_components[case]]
        ledger.send(stage, "case_agent_registration", agent.role, coordinator.role,
                    {"case_id": case, "component_id": coordinator.id}, case, stage_round=2)
        ledger.count(stage, "case_agent_registrations", case)
        coordinator.cases.add(case)
    for source in sources.values():
        # The directory notifications, not shared-row ownership, establish membership.
        for ident in sorted(set(source.components.values())):
            coordinator = coordinators[ident]
            valid = all(
                row_id not in failed_empty_rows
                for row_id in source.given_rows
                if row_owners[row_id]["component_id"] == ident
            )
            ledger.send(stage, "source_registration", source.role, coordinator.role, {
                "source": source.host, "component_id": ident, "given_rows_valid": valid,
            }, coordinator.winning_case, stage_round=2)
            ledger.count(stage, "source_registrations", coordinator.winning_case)
            coordinator.sources.add(source.host)
            coordinator.given_rows_valid &= valid

    # Request round: only source-owned triggers initiate prerequisites. Agents
    # initiate each specified occurrence row, even with an empty directory.
    stage = STAGES[4]
    ledger.round += 1
    requested_ids = set(rows)

    def request(agent, record):
        if record["id"] in requested_ids:
            raise ValueError(f"Duplicate generated row ID {record['id']}")
        requested_ids.add(record["id"])
        agent.requests[record["id"]] = record
        agent.presence[record["id"]] = {}

    prerequisites = sorted(instance.get("prerequisites", []), key=lambda item: item["id"])
    for source in sources.values():
        for candidate in source.candidates.values():
            for template in prerequisites:
                if candidate["activity"] != template["trigger_activity"]:
                    continue
                case = candidate["case_id"]
                record = {
                    "id": f"pre:{template['id']}:{candidate['id']}",
                    "kind": "prerequisite", "case_id": case, "upper": 0,
                    "template_id": template["id"], "trigger_id": candidate["id"],
                    "trigger_owner": source.host, "trigger_start": candidate["start"],
                    "activities": sorted(set(template["predecessor_activities"])),
                    "min_delay": template.get("min_delay") or 0,
                    "max_delay": template.get("max_delay"),
                }
                ledger.send(stage, "trigger_request", source.role, agents[case].role, record, case)
                ledger.count(stage, "trigger_requests", case)
                request(agents[case], record)
    for case, agent in agents.items():
        for template in sorted(instance.get("occurrence_bounds", []), key=lambda item: item["id"]):
            for direction in ("upper", "lower"):
                bound = template.get(direction)
                if bound is None:
                    continue
                if direction == "lower" and bound == 0:
                    ledger.count(stage, "omitted_zero_lower_rows", case)
                    continue
                record = {
                    "id": f"{direction}:{template['id']}:{case}",
                    "kind": f"occurrence_{direction}", "case_id": case,
                    "upper": bound if direction == "upper" else -bound,
                    "template_id": template["id"],
                    "activities": sorted(set(template["activities"])),
                }
                ledger.count(stage, "bound_initiations", case)
                request(agent, record)

    # Each query concerns one row. Upper and lower rows never share a query.
    ledger.round += 1
    pending_replies = []
    for case, agent in agents.items():
        for record in agent.requests.values():
            for owner in sorted(agent.directory):
                source = sources[owner]
                ledger.send(stage, "lookup_request", agent.role, source.role, record, case, stage_round=2)
                ledger.count(stage, "lookup_requests", case)
                present = source.lookup(record)
                pending_replies.append((case, record["id"], owner, present))
                if present:
                    ledger.count(stage, "retained_fragments", case)
                    ledger.count(stage, "retained_coefficient_terms", case,
                                 len(source.fragments[record["id"]]))
    ledger.round += 1
    for case, ident, owner, present in pending_replies:
        ledger.send(stage, "presence_reply", sources[owner].role, agents[case].role,
                    {"row_id": ident, "present": present}, case, stage_round=3)
        ledger.count(stage, "positive_presence_replies" if present else "negative_presence_replies", case)
        agents[case].presence[ident][owner] = present

    # Decide placements only after every directory member replied. No fragment
    # data has crossed a role boundary before this point.
    ledger.round += 1
    shared_transfers, acknowledgments = [], []
    for case, agent in agents.items():
        coordinator = coordinators[case_components[case]]
        for ident, record in agent.requests.items():
            if set(agent.presence[ident]) != agent.directory:
                raise RuntimeError(f"Incomplete presence replies for {ident}")
            owners = sorted(owner for owner, present in agent.presence[ident].items() if present)
            contributors[ident] = owners
            row_owners[ident] = {
                "classification": "empty" if not owners else "local" if len(owners) == 1 else "shared",
                "source": None if not owners else owners[0] if len(owners) == 1 else coordinator.host,
                "component_id": coordinator.id,
            }
            if not owners:
                row = _row(record, {})
                rows[ident] = row
                valid = 0 <= row["upper"]
                empty_checks[ident] = valid
                agent.completed_rows.add(ident)
                if not valid:
                    agent.failed_rows.add(ident)
                    failed_empty_rows.add(ident)
                for key in ("empty_rows", "empty_row_checks",
                            "empty_row_checks_passed" if valid else "empty_row_checks_failed"):
                    ledger.count(stage, key, case)
            elif len(owners) == 1:
                source = sources[owners[0]]
                ledger.send(STAGES[5], "store_local_row", agent.role, source.role, {
                    "row_id": ident, "kind": record["kind"], "case_id": case, "upper": record["upper"],
                }, case)
                for key in ("placement_instructions", "local_placement_instructions"):
                    ledger.count(STAGES[5], key, case)
                source.rows[ident] = _row(record, source.fragments[ident])
                rows[ident] = source.rows[ident]
                ledger.count(stage, "local_rows", case)
                acknowledgments.append((source.role, case, ident))
            else:
                ledger.send(STAGES[5], "shared_row_announcement", agent.role, coordinator.role, {
                    "row_id": ident, "kind": record["kind"], "case_id": case,
                    "upper": record["upper"], "contributors": owners,
                }, case)
                ledger.count(STAGES[5], "shared_row_announcements", case)
                coordinator.announced_rows[ident] = (record, set(owners))
                for owner in owners:
                    ledger.send(STAGES[5], "send_fragment_instruction", agent.role, sources[owner].role, {
                        "row_id": ident, "component_id": coordinator.id,
                        "coordinator": coordinator.host,
                    }, case)
                    for key in ("placement_instructions", "shared_transfer_instructions"):
                        ledger.count(STAGES[5], key, case)
                    shared_transfers.append((case, ident, owner))

    ledger.round += 1
    for case, ident, owner in shared_transfers:
        source = sources[owner]
        coordinator = coordinators[case_components[case]]
        fragment = source.fragments[ident]
        ledger.send(stage, "shared_fragment", source.role, coordinator.role,
                    {"row_id": ident, "terms": dict(sorted(fragment.items()))},
                    case, terms=len(fragment), stage_round=5)
        ledger.count(stage, "shared_fragment_transfers", case)
        ledger.count(stage, "transferred_coefficient_terms", case, len(fragment))
        coordinator.fragments[ident][owner] = fragment.copy()
        record, expected = coordinator.announced_rows[ident]
        if set(coordinator.fragments[ident]) == expected:
            assembled = {}
            for received in coordinator.fragments[ident].values():
                if assembled.keys() & received.keys():
                    raise RuntimeError(f"Duplicate candidate ownership in shared row {ident}")
                assembled.update(received)
            coordinator.rows[ident] = _row(record, assembled)
            rows[ident] = coordinator.rows[ident]
            ledger.count(stage, "shared_rows", case)
            acknowledgments.append((coordinator.role, case, ident))

    stage = STAGES[5]
    ledger.round += 1
    for sender, case, ident in acknowledgments:
        ledger.send(stage, "row_storage_acknowledgment", sender, agents[case].role,
                    {"row_id": ident, "stored": True}, case, stage_round=3)
        ledger.count(stage, "row_storage_acknowledgments", case)
        agents[case].completed_rows.add(ident)
    ledger.round += 1
    for case, agent in agents.items():
        if set(agent.requests) != agent.completed_rows:
            raise RuntimeError(f"Case {case} has uncompleted row requests")
        coordinator = coordinators[case_components[case]]
        success = not agent.failed_rows
        ledger.send(stage, "case_agent_completion", agent.role, coordinator.role, {
            "case_id": case, "success": success, "failed_empty_rows": sorted(agent.failed_rows),
        }, case, stage_round=4)
        ledger.count(stage, "case_agent_completion_records", case)
        coordinator.case_completions[case] = success

    components = []
    for ident, coordinator in sorted(coordinators.items()):
        if set(coordinator.case_completions) != coordinator.cases:
            raise RuntimeError(f"Component {ident} has missing case completions")
        ready = coordinator.given_rows_valid and all(coordinator.case_completions.values())
        ledger.count(stage, "coordinators_ready" if ready else "coordinators_infeasible",
                     coordinator.winning_case)
        # Candidate membership is an output audit of registered source state;
        # it is not a central row encoding or an extra protocol message.
        candidate_ids = sorted(
            candidate["id"] for owner in coordinator.sources
            for candidate in sources[owner].candidates.values()
            if sources[owner].components[candidate["case_id"]] == ident
        )
        components.append({
            "id": ident, "case_ids": sorted(coordinator.cases),
            "sources": sorted(coordinator.sources), "coordinator": coordinator.host,
            "candidate_ids": candidate_ids, "status": "ready" if ready else "infeasible",
        })
    return {
        "rows": [rows[ident] for ident in sorted(rows)], "components": components,
        "status": "infeasible" if failed_empty_rows else "ready",
        "failed_empty_rows": sorted(failed_empty_rows), "empty_row_checks": dict(sorted(empty_checks.items())),
        "directories": {case: sorted(agent.directory) for case, agent in agents.items()},
        "neighbors": {case: dict(sorted(agent.neighbors.items())) for case, agent in agents.items()},
        "contributors": dict(sorted(contributors.items())), "row_owners": dict(sorted(row_owners.items())),
        "requests": [record for agent in agents.values() for record in agent.requests.values()],
        "retained_fragments": [
            {"row_id": ident, "source": source.host, "terms": dict(sorted(terms.items()))}
            for source in sources.values() for ident, terms in sorted(source.fragments.items()) if terms
        ],
        "metrics": ledger.finish(components, case_components, election_rounds),
        "trace": ledger.trace,
    }
