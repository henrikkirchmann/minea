"""Certification tests with a small, solver-independent binary enumeration."""

from fractions import Fraction
from itertools import product
import json
import random
import unittest
from unittest.mock import patch

import z3

from minea_ikea.solver import solve_exact


def exhaustive(candidates, rows, fixings=None):
    """No solver helpers: enumerate binary vectors and evaluate raw input rows."""
    best, witnesses = None, []
    identifiers = [candidate["id"] for candidate in candidates]
    for bits in product((0, 1), repeat=len(identifiers)):
        values = dict(zip(identifiers, bits))
        if any(values[identifier] != value for identifier, value in (fixings or {}).items()):
            continue
        if any(sum(coefficient * values[identifier] for identifier, coefficient in row["terms"].items()) > row["upper"] for row in rows):
            continue
        objective = sum((Fraction(candidate["score"]) * values[candidate["id"]] for candidate in candidates), Fraction())
        selected = {identifier for identifier, value in values.items() if value}
        if best is None or objective > best:
            best, witnesses = objective, [selected]
        elif objective == best:
            witnesses.append(selected)
    return best, witnesses


def row(identifier, terms, upper):
    return {"id": identifier, "terms": terms, "upper": upper}


class SolverTests(unittest.TestCase):
    def test_decimal_distinction_below_binary_float_resolution(self):
        candidates = [{"id": "a", "score": "0.1000000000000000000000000000000000000001"}, {"id": "b", "score": "0.1"}]
        result = solve_exact(candidates, [row("choice", {"a": 1, "b": 1}, 1)])
        self.assertEqual(result["status"], "optimal")
        self.assertEqual(result["selected_ids"], ["a"])
        self.assertEqual(Fraction(result["objective"]), Fraction(candidates[0]["score"]))
        self.assertEqual(result["lower_bound"], result["upper_bound"])
        self.assertTrue(result["optimality_certificate"]["equality_verified"])
        json.dumps(result, allow_nan=False)

    def test_negative_score_forced_by_negative_coefficient_and_bound(self):
        result = solve_exact([{"id": "x", "score": "-0.125"}], [row("required", {"x": -1}, -1)])
        self.assertEqual((result["status"], result["objective"], result["selected_ids"]), ("optimal", "-1/8", ["x"]))

    def test_empty_models_and_empty_contradictions(self):
        feasible = solve_exact([], [row("vacuous", {}, 0)])
        self.assertEqual((feasible["status"], feasible["objective"], feasible["selected_ids"]), ("optimal", "0", []))
        infeasible = solve_exact([], [row("impossible", {}, -1)])
        self.assertEqual(infeasible["status"], "infeasible")
        self.assertIsNone(infeasible["selected_ids"])

    def test_ties_are_compared_by_objective(self):
        candidates = [{"id": "a", "score": "0.3"}, {"id": "b", "score": "0.30"}]
        rows = [row("choice", {"a": 1, "b": 1}, 1)]
        expected, witnesses = exhaustive(candidates, rows)
        for order in (candidates, list(reversed(candidates))):
            result = solve_exact(order, rows)
            self.assertEqual(Fraction(result["objective"]), expected)
            self.assertIn(set(result["selected_ids"]), witnesses)

    def test_random_small_models_match_exhaustive_binary_oracle(self):
        generator = random.Random(20260919)
        for fixture in range(24):
            candidates = [{"id": f"x{i}", "score": str(Fraction(generator.randint(-4, 8), 10))} for i in range(6)]
            rows = [row(f"r{j}", {candidate["id"]: generator.choice((-2, -1, 0, 1, 2)) for candidate in candidates}, generator.randint(-2, 4)) for j in range(5)]
            fixings = {"x0": fixture % 2} if fixture % 3 == 0 else {}
            expected, witnesses = exhaustive(candidates, rows, fixings)
            result = solve_exact(candidates, rows, fixings=fixings)
            with self.subTest(fixture=fixture):
                if expected is None:
                    self.assertEqual(result["status"], "infeasible")
                else:
                    self.assertEqual(result["status"], "optimal")
                    self.assertEqual(Fraction(result["objective"]), expected)
                    self.assertIn(set(result["selected_ids"]), witnesses)

    def test_zero_budget_is_not_an_optimum_or_a_started_optimizer(self):
        result = solve_exact([{"id": "x", "score": "2.5"}], [], time_limit=0)
        self.assertEqual(result["status"], "limited")
        self.assertFalse(result["certified_optimal"])
        self.assertFalse(result["solver_started"])
        self.assertIsNone(result["objective"])
        self.assertEqual(result["upper_bound"], "5/2")
        self.assertEqual(result["upper_bound_source"], "trivial_binary_relaxation")

    def test_unknown_with_even_equal_reported_bounds_is_not_certified(self):
        original = z3.Optimize

        class UnknownProxy:
            def __init__(self):
                self.inner = original()

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def check(self):
                self.inner.check()
                return z3.unknown

            def reason_unknown(self):
                return "deliberately interrupted test"

        with patch("z3.Optimize", UnknownProxy):
            result = solve_exact([{"id": "x", "score": "5"}, {"id": "y", "score": "4"}], [row("choice", {"x": 1, "y": 1}, 1)])
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["certified_optimal"])
        self.assertEqual(result["objective"], "5")
        self.assertEqual(result["upper_bound"], "9")
        self.assertEqual(result["upper_bound_source"], "trivial_binary_relaxation")

    def test_sat_with_wrong_equal_bounds_is_not_certified(self):
        original = z3.Optimize

        class WrongCertificate:
            def lower(self):
                return z3.RealVal(123)

            def upper(self):
                return z3.RealVal(123)

        class WrongBoundsProxy:
            def __init__(self):
                self.inner = original()

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def maximize(self, expression):
                self.inner.maximize(expression)
                return WrongCertificate()

        with patch("z3.Optimize", WrongBoundsProxy):
            result = solve_exact([{"id": "x", "score": "5"}], [])
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(result["certified_optimal"])
        self.assertEqual(result["objective"], "5")

    def test_rejects_float_scores_and_malformed_numeric_model(self):
        with self.assertRaisesRegex(ValueError, "original decimal strings"):
            solve_exact([{"id": "x", "score": 0.1}], [])
        with self.assertRaisesRegex(ValueError, "integer"):
            solve_exact([{"id": "x", "score": "0.1"}], [row("r", {"x": 0.5}, 1)])
        with self.assertRaisesRegex(ValueError, "unknown candidate"):
            solve_exact([{"id": "x", "score": "1"}], [], fixings={"missing": 0})
        with self.assertRaisesRegex(ValueError, "zero or one"):
            solve_exact([{"id": "x", "score": "1"}], [], fixings={"x": 2})


if __name__ == "__main__":
    unittest.main()
