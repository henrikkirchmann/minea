"""Independent HiGHS optimization for a single area or a pooled order."""
from collections import defaultdict
import warnings

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, csr_matrix, vstack


def canonical_labels(candidates, constraints):
    """Optimize score, then top choices, then the sequence of candidate ranks."""
    positions = {candidate["id"]: j for j, candidate in enumerate(candidates)}
    weights = np.array([int(181 * c["score"]) for c in candidates])
    ranks = np.arange(len(candidates)).reshape(-1, 10)
    row_indices, columns, values, bounds = [], [], [], []
    for i, row in enumerate(constraints):
        bounds.append(int(row["upper"]))
        for name, coef in row["coefficients"].items():
            row_indices.append(i)
            columns.append(positions[name])
            values.append(int(coef))

    rows = coo_matrix((values, (row_indices, columns)),
                      shape=(len(bounds), len(candidates))).tocsc()
    lower = np.full(len(bounds), -np.inf)
    upper = np.array(bounds)
    bit_lower = np.zeros(len(candidates))
    bit_upper = np.ones(len(candidates))

    def maximize(preference):
        with warnings.catch_warnings():
            # SciPy forwards the native 'threads' option to HiGHS.
            warnings.filterwarnings("ignore", message="Unrecognized options detected:.*threads.*",
                                    category=RuntimeWarning)
            result = milp(-preference, integrality=np.ones(len(candidates)),
                          bounds=Bounds(bit_lower, bit_upper),
                          constraints=LinearConstraint(rows, lower, upper),
                          options={"threads": 1, "mip_rel_gap": 0.0})
        if result.status != 0:
            raise RuntimeError(result.message)
        chosen = np.rint(result.x).astype(int)
        totals = rows @ chosen
        if (np.max(np.abs(result.x - chosen)) > 1e-6
                or np.any(totals < lower) or np.any(totals > upper)
                or np.any(chosen < bit_lower) or np.any(chosen > bit_upper)
                or abs(preference @ chosen + result.mip_dual_bound) > 1e-4):
            raise RuntimeError("HiGHS returned an invalid or uncertified selection")
        return chosen

    best = maximize(weights)
    if not np.all(best[ranks[:, 0]]):
        score = weights @ best
        rows = vstack([rows, csr_matrix(weights)], format="csc")
        lower, upper = np.r_[lower, score], np.r_[upper, score]
        first = np.zeros_like(weights)
        first[ranks[:, 0]] = 1
        best = maximize(first)
        top_count = first @ best
        rows = vstack([rows, csr_matrix(first)], format="csc")
        lower, upper = np.r_[lower, top_count], np.r_[upper, top_count]

        # Optimize five digits per block, then fix them before continuing.
        for offset in range(0, len(ranks), 5):
            block = ranks[offset:offset + 5]
            if not np.all(best[block[:, 0]]):
                preference = np.zeros_like(weights)
                for j, group in enumerate(block):
                    preference[group] = 11 ** (len(block) - j - 1) * np.arange(10, 0, -1)
                best = maximize(preference)
            bit_lower[block] = bit_upper[block] = best[block]
    return {candidates[group[0]]["observation"]:
            next((candidates[j]["label"] for j in group if best[j]), "") for group in ranks}


def solve(model):
    candidates_by_source = defaultdict(list)
    rows_by_source = defaultdict(list)
    for candidate in model["candidates"]:
        candidates_by_source[candidate["owner"]].append(candidate)
    for row in model["rows"]:
        if row["owner"] is not None:
            rows_by_source[row["owner"]].append(row)
    local = {}
    for source, candidates in candidates_by_source.items():
        local.update(canonical_labels(candidates, rows_by_source[source]))
    central = canonical_labels(model["candidates"], model["rows"])
    return local, central
