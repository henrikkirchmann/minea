"""Exact binary optimization, with a deliberately narrow certification boundary.

Scores enter as their original decimal strings and are converted to ``Fraction``.
Z3 receives integer variables and rational constants.  Neither a floating-point
gap nor an unfinished optimizer model is accepted as an exact local optimum.
The matching protocol must inspect ``certified_optimal`` before using a score as
a local upper bound.  A feasible model returned on interruption is only a primal
solution; the accompanying upper bound is the elementary binary relaxation.
"""

from __future__ import annotations

from fractions import Fraction
from importlib import metadata
import math
import time
from typing import Any, Iterable, Mapping


def fraction_string(value: Fraction | int | None) -> str | None:
    """Serialize exact finite values; infinity is represented separately."""
    return None if value is None else str(Fraction(value))


def score_fraction(value: Any) -> Fraction:
    """Do not silently turn a binary floating-point score into input data."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Fraction)):
        raise ValueError("Scores must be original decimal strings, integers, or Fractions")
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"Invalid finite exact score: {value!r}") from exc


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def prepare_model(
    candidates: Iterable[Mapping[str, Any]], rows: Iterable[Mapping[str, Any]],
    fixings: Mapping[str, int] | None = None,
) -> tuple[list[dict], list[dict], dict[str, int]]:
    """Copy and validate the small common numerical schema without changing it."""
    items = [dict(candidate) for candidate in candidates]
    identifiers = [candidate["id"] for candidate in items]
    if any(not isinstance(identifier, str) for identifier in identifiers):
        raise ValueError("Candidate IDs must be strings")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Duplicate candidate IDs")
    items.sort(key=lambda candidate: candidate["id"])
    known = set(identifiers)
    for candidate in items:
        score_fraction(candidate["score"])
    normalized_rows = []
    row_ids = set()
    for original in rows:
        row = dict(original)
        identifier = row["id"]
        if not isinstance(identifier, str) or identifier in row_ids:
            raise ValueError("Row IDs must be unique strings")
        row_ids.add(identifier)
        terms = {}
        for variable, coefficient in row["terms"].items():
            if variable not in known:
                raise ValueError(f"Row {identifier!r} refers to unknown candidate {variable!r}")
            coefficient = _integer(coefficient, "Row coefficient")
            if coefficient:
                terms[variable] = coefficient
        row["terms"] = dict(sorted(terms.items()))
        row["upper"] = _integer(row["upper"], "Row upper bound")
        normalized_rows.append(row)
    normalized_rows.sort(key=lambda row: row["id"])
    fixed = {}
    for identifier, value in (fixings or {}).items():
        if identifier not in known:
            raise ValueError(f"Fixing refers to unknown candidate {identifier!r}")
        if _integer(value, "Fixed value") not in (0, 1):
            raise ValueError("Fixed values must be zero or one")
        fixed[identifier] = value
    return items, normalized_rows, dict(sorted(fixed.items()))


def selection_is_feasible(
    candidates: Iterable[Mapping[str, Any]], rows: Iterable[Mapping[str, Any]],
    selected_ids: Iterable[str], fixings: Mapping[str, int] | None = None,
) -> bool:
    """Check a proposed assignment using Python integers, independently of Z3."""
    known = {candidate["id"] for candidate in candidates}
    selected = set(selected_ids)
    return (
        selected <= known
        and all(int(identifier in selected) == value for identifier, value in (fixings or {}).items())
        and all(
            sum(coefficient for identifier, coefficient in row["terms"].items() if identifier in selected)
            <= row["upper"]
            for row in rows
        )
    )


def selected_score(candidates: Iterable[Mapping[str, Any]], selected_ids: Iterable[str]) -> Fraction:
    selected = set(selected_ids)
    return sum((score_fraction(candidate["score"]) for candidate in candidates if candidate["id"] in selected), Fraction())


def trivial_upper_bound(
    candidates: Iterable[Mapping[str, Any]], fixings: Mapping[str, int] | None = None,
) -> Fraction:
    """A certified bound obtained by dropping all rows, including on timeout."""
    fixed = fixings or {}
    return sum((
        score_fraction(candidate["score"]) * fixed[candidate["id"]]
        if candidate["id"] in fixed else max(Fraction(), score_fraction(candidate["score"]))
        for candidate in candidates
    ), Fraction())


def make_deadline(time_limit: float | None, *, start: float | None = None) -> float | None:
    if time_limit is None:
        return None
    if isinstance(time_limit, bool) or not isinstance(time_limit, (int, float)):
        raise ValueError("time_limit must be nonnegative seconds or None")
    if not math.isfinite(time_limit) or time_limit < 0:
        raise ValueError("time_limit must be finite and nonnegative")
    return (time.monotonic() if start is None else start) + time_limit


def solver_provenance() -> dict:
    try:
        version = metadata.version("z3-solver")
    except metadata.PackageNotFoundError:
        version = "not installed"
    return {
        "name": "Z3 Optimize",
        "package": "z3-solver",
        "version": version,
        "variables": "integer variables constrained to {0,1}",
        "score_arithmetic": "Fraction(original score string); exact Z3 rational coefficients",
        "optimality_test": "sat and rational lower == upper == independently recomputed feasible model score",
        "tie_policy": "Z3 native optimal model; variables and rows inserted in lexicographic ID order; tied labels may differ",
        "score_rounding": "none",
        "warm_start": "none",
        "interrupted_upper_bound": "sum of positive unfixed scores plus fixed contributions; never an exact local optimum",
        "deadline_policy": "one caller deadline including model construction; remaining milliseconds passed to Z3",
        "api_reference": "https://z3prover.github.io/api/html/classz3py_1_1_optimize_objective.html",
    }


def _rational(value: Any, z3: Any) -> Fraction | None:
    value = z3.simplify(value)
    if z3.is_int_value(value):
        return Fraction(value.as_long())
    if z3.is_rational_value(value):
        return Fraction(value.numerator_as_long(), value.denominator_as_long())
    # Infinity, epsilon expressions, and approximate/algebraic values are not
    # finite rational certificates.  Do not parse a decimal approximation.
    return None


def solve_exact(
    candidates: Iterable[Mapping[str, Any]], rows: Iterable[Mapping[str, Any]], *,
    fixings: Mapping[str, int] | None = None, time_limit: float | None = None,
    deadline: float | None = None,
) -> dict:
    """Maximize an exact rational score subject to integer binary rows.

    ``deadline`` is an absolute ``time.monotonic()`` value.  It allows many
    component/source solves to share one condition budget.  If both limits are
    supplied, the earlier deadline wins.  Bounds and objectives are JSON-safe
    fraction strings.  On ``unknown`` or ``limited``, a returned feasible model
    is useful as a central primal solution, but is NEVER a certified local
    optimum for the distributed protocol.
    """
    started = time.monotonic()
    relative_deadline = make_deadline(time_limit, start=started)
    if relative_deadline is not None:
        deadline = relative_deadline if deadline is None else min(deadline, relative_deadline)
    items, constraints, fixed = prepare_model(candidates, rows, fixings)
    upper = trivial_upper_bound(items, fixed)
    result = {
        "status": "limited", "reason": "deadline_before_solver", "selected_ids": None,
        "objective": None, "lower_bound": None, "upper_bound": str(upper),
        "lower_bound_kind": "negative_infinity", "upper_bound_kind": "finite",
        "upper_bound_source": "trivial_binary_relaxation", "certified_optimal": False,
        "feasibility_checked": False, "solver_started": False, "solver_statistics": {},
        "solver_reported_lower_bound": None, "solver_reported_upper_bound": None,
        "optimality_certificate": None,
    }

    def finish() -> dict:
        result["elapsed_seconds"] = time.monotonic() - started
        return result

    if deadline is not None and time.monotonic() >= deadline:
        return finish()
    try:
        import z3
    except ImportError as exc:
        raise RuntimeError("Install the pinned z3-solver dependency before matching") from exc

    optimizer = z3.Optimize()
    variables = {candidate["id"]: z3.Int(f"x_{index}") for index, candidate in enumerate(items)}
    for variable in variables.values():
        optimizer.add(variable >= 0, variable <= 1)
    for row in constraints:
        lhs = z3.Sum([coefficient * variables[identifier] for identifier, coefficient in row["terms"].items()]) if row["terms"] else z3.IntVal(0)
        optimizer.add(lhs <= row["upper"])
    for identifier, value in fixed.items():
        optimizer.add(variables[identifier] == value)
    terms = []
    for candidate in items:
        weight = score_fraction(candidate["score"])
        terms.append(z3.RealVal(f"{weight.numerator}/{weight.denominator}") * variables[candidate["id"]])
    objective = optimizer.maximize(z3.Sum(terms) if terms else z3.RealVal(0))
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining < 0.001:
            result["reason"] = "deadline_during_model_construction"
            return finish()
        # Z3 interprets zero as unlimited, so never pass a rounded zero timeout.
        optimizer.set(timeout=min(2**32 - 1, max(1, int(remaining * 1000))))
    result["solver_started"] = True
    outcome = optimizer.check()
    result["solver_statistics"] = {key: value for key, value in optimizer.statistics()}
    if outcome == z3.unsat:
        result.update(
            status="infeasible", reason="proved_unsatisfiable", upper_bound=None,
            upper_bound_kind="negative_infinity", upper_bound_source="unsatisfiability_proof",
            optimality_certificate={"check_result": "unsat"},
        )
        return finish()

    # The public OptimizeObjective API exposes exact lower/upper expressions:
    # https://z3prover.github.io/api/html/classz3py_1_1_optimize_objective.html
    reported_lower = reported_upper = None
    try:
        raw_lower, raw_upper = objective.lower(), objective.upper()
        result["solver_reported_lower_bound"] = str(raw_lower)
        result["solver_reported_upper_bound"] = str(raw_upper)
        reported_lower, reported_upper = _rational(raw_lower, z3), _rational(raw_upper, z3)
    except z3.Z3Exception:
        pass
    try:
        model = optimizer.model()
        values = {identifier: model.eval(variable, model_completion=True) for identifier, variable in variables.items()}
        if all(z3.is_int_value(value) and value.as_long() in (0, 1) for value in values.values()):
            selected = [identifier for identifier, value in values.items() if value.as_long() == 1]
            if selection_is_feasible(items, constraints, selected, fixed):
                score = selected_score(items, selected)
                result.update(selected_ids=selected, objective=str(score), lower_bound=str(score), lower_bound_kind="finite", feasibility_checked=True)
    except z3.Z3Exception:
        pass
    if outcome == z3.sat and result["objective"] is not None:
        score = Fraction(result["objective"])
        if reported_lower is not None and reported_lower == reported_upper == score:
            result.update(
                status="optimal", reason="exact_bound_equality", upper_bound=str(score),
                upper_bound_source="exact_solver_certificate", certified_optimal=True,
                optimality_certificate={
                    "check_result": "sat", "lower": str(reported_lower),
                    "upper": str(reported_upper), "recomputed_objective": str(score),
                    "equality_verified": True,
                },
            )
            return finish()
    reason = optimizer.reason_unknown() if outcome == z3.unknown else "optimizer_did_not_supply_exact_bound_equality"
    limited = "timeout" in reason.lower() or ("canceled" in reason.lower() and deadline is not None) or (deadline is not None and time.monotonic() >= deadline)
    result.update(status="limited" if limited else "unknown", reason=reason)
    return finish()
