"""
ILP group formation via OR-Tools CP-SAT (§3 step 6, §4).

Design rules enforced here (§3 critical):
  - compatibility() accepts ONLY raw continuous axis vectors (step 4b).
  - Archetype labels (step 4a) are NEVER passed into this module.
  - No inter-group balancing — intra-group similarity maximization only (§6/7).

Algorithm choice rationale (§4):
  ILP over GA because: provable optimum, deterministic, native constraint
  expression. GA is the right tool at larger scale; our scope (tens–hundreds
  of students, fixed group size 4–5) fits exact solvers.

Three result sets are returned:
  ilp_result    — our algorithm (scored vectors, ILP-optimal)
  random_result — random baseline (same scored vectors, random assignment)
  oracle_result — upper bound (true noise-free vectors, ILP-optimal)
"""

import math
import random
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
from ortools.sat.python import cp_model

from synthetic import AXES, DEFAULT_AXIS_WEIGHTS

# ──────────────────────────────────────────────────────────────────────────────
#  Compatibility function  (step 4b — raw continuous vectors only)
# ──────────────────────────────────────────────────────────────────────────────

def compatibility(
    vec_i: Dict[str, float],
    vec_j: Dict[str, float],
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """
    Weighted similarity between two continuous axis vectors.

    Inputs MUST be raw axis score dicts (from score_axis() or true_axis_scores).
    Archetype labels must NEVER be passed here — they collapse the rich
    continuous vector into a single discrete label, losing information.

    Score in [0, 1]: 1 = identical on all axes, 0 = maximum distance.
    Axes are normalized to [0,1] before distance computation.
    """
    if weights is None:
        weights = DEFAULT_AXIS_WEIGHTS

    total_w = sum(weights.values())
    weighted_sim = 0.0

    for ax in AXES:
        norm_i = (vec_i[ax] - 1.0) / 5.0
        norm_j = (vec_j[ax] - 1.0) / 5.0
        sim = 1.0 - abs(norm_i - norm_j)
        weighted_sim += weights.get(ax, 1.0) * sim

    return weighted_sim / total_w


def build_compat_matrix(
    students: List[Dict],
    vector_key: str,
    weights: Optional[Dict[str, float]] = None,
) -> np.ndarray:
    """Build an N×N pairwise compatibility matrix using vector_key field."""
    n = len(students)
    mat = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            c = compatibility(students[i][vector_key], students[j][vector_key], weights)
            mat[i, j] = mat[j, i] = c
    return mat


# ──────────────────────────────────────────────────────────────────────────────
#  Random baseline
# ──────────────────────────────────────────────────────────────────────────────

def random_groups(
    students: List[Dict],
    compat_matrix: np.ndarray,
    group_size_max: int = 5,
    seed: int = 0,
) -> Dict:
    n = len(students)
    ids = list(range(n))
    random.seed(seed)
    random.shuffle(ids)

    G = math.ceil(n / group_size_max)
    groups = []
    total = 0.0

    for g in range(G):
        members = ids[g * group_size_max: (g + 1) * group_size_max]
        if not members:
            continue
        score = sum(
            compat_matrix[members[a], members[b]]
            for a in range(len(members))
            for b in range(a + 1, len(members))
        )
        groups.append({
            "group_id": g,
            "members":      [students[m]["id"]   for m in members],
            "member_names": [students[m]["name"] for m in members],
            "group_compat": round(float(score), 4),
        })
        total += score

    return {"groups": groups, "total_compat": round(float(total), 4)}


# ──────────────────────────────────────────────────────────────────────────────
#  Greedy solution (used as ILP starting hint)
# ──────────────────────────────────────────────────────────────────────────────

def _greedy_assignment(
    n: int,
    G: int,
    group_size_max: int,
    compat_matrix: np.ndarray,
    weights: Optional[Dict[str, float]] = None,
) -> List[int]:
    """
    Build a greedy group assignment by iteratively adding the highest-compat
    student to each partially-filled group.  Used as a warm-start hint for ILP.
    """
    assignment = [-1] * n
    group_sizes = [0] * G
    # Sort students by their average compat (most "compatible" students placed first)
    avg_compat = [float(np.mean(compat_matrix[i])) for i in range(n)]
    order = sorted(range(n), key=lambda i: -avg_compat[i])

    for i in order:
        if assignment[i] >= 0:
            continue
        # Pick the group with most remaining capacity and best avg compat to this student
        best_g, best_c = -1, -1.0
        for g in range(G):
            if group_sizes[g] >= group_size_max:
                continue
            members_in_g = [j for j in range(n) if assignment[j] == g]
            mean_c = float(np.mean([compat_matrix[i, j] for j in members_in_g])) if members_in_g else 0.5
            if mean_c > best_c:
                best_c, best_g = mean_c, g
        if best_g == -1:
            best_g = next(g for g in range(G) if group_sizes[g] < group_size_max)
        assignment[i] = best_g
        group_sizes[best_g] += 1

    return assignment


# ──────────────────────────────────────────────────────────────────────────────
#  ILP solver (OR-Tools CP-SAT) — compact formulation
# ──────────────────────────────────────────────────────────────────────────────

_SCALE        = 10_000   # scale floats to integers for CP-SAT
_COMPAT_PRUNE = 0.40     # skip pairs below this compat in the objective (sparse opt)
#   0.40 keeps same-archetype pairs (compat ≈ 0.7–0.95) and prunes cross-archetype
#   pairs (compat ≈ 0.2–0.5), dramatically reducing the variable count.


def ilp_groups(
    students: List[Dict],
    compat_matrix: np.ndarray,
    group_size_min: int = 4,
    group_size_max: int = 5,
    time_limit_s: float = 30.0,
    weights: Optional[Dict[str, float]] = None,
) -> Dict:
    """
    CP-SAT ILP: maximize intra-group compatibility.

    Compact formulation (no z[i,j,g] per-group variables):
      assign[i]   ∈ {0..G-1}   — group index for student i
      members[i][g] ∈ {0,1}   — student i is in group g (linked to assign[i])
      same[i,j]  ∈ {0,1}     — students i and j are in the same group

      Maximize:  Σ_{i<j, compat>prune} compat[i,j] * same[i,j]
      Subject to:
        AddExactlyOne(members[i])            ∀i
        assign[i]==g → members[i][g]==1      ∀i,g  (via OnlyEnforceIf)
        4 ≤ Σ_i members[i][g] ≤ 5           ∀g
        assign[i]==assign[j] → same[i,j]==1  (via OnlyEnforceIf + maximization)

    Warm-started from a greedy hint to speed up initial feasible solution.

    No inter-group fairness constraint — intentional (§6/7).
    """
    n = len(students)
    G = math.ceil(n / group_size_max)

    model = cp_model.CpModel()

    # ── Assignment IntVars ─────────────────────────────────────────────────
    assign = [model.NewIntVar(0, G - 1, f"a_{i}") for i in range(n)]

    # ── Member BoolVars (linked to assign) ────────────────────────────────
    # members[i][g] = 1 iff student i is in group g
    # Enforced via: "if members[i][g]=1 then assign[i]=g" + ExactlyOne
    members = [[model.NewBoolVar(f"m_{i}_{g}") for g in range(G)] for i in range(n)]
    for i in range(n):
        model.AddExactlyOne(members[i])
        for g in range(G):
            model.Add(assign[i] == g).OnlyEnforceIf(members[i][g])
            # Reverse: if assign[i]!=g then members[i][g]=0, enforced by ExactlyOne

    # ── Group size constraints ─────────────────────────────────────────────
    for g in range(G):
        group_count = sum(members[i][g] for i in range(n))
        model.Add(group_count >= group_size_min)
        model.Add(group_count <= group_size_max)

    # ── Pairwise objective (one BoolVar per pair, not per pair-per-group) ─
    # same[i,j] = 1 iff assign[i] == assign[j].
    # For maximization with compat ≥ 0: solver sets same=1 whenever assign[i]==assign[j].
    obj_terms = []
    same_vars: Dict[Tuple[int, int], object] = {}

    for i in range(n):
        for j in range(i + 1, n):
            c = float(compat_matrix[i, j])
            if c < _COMPAT_PRUNE:
                continue
            c_int = int(c * _SCALE)
            same = model.NewBoolVar(f"s_{i}_{j}")
            model.Add(assign[i] == assign[j]).OnlyEnforceIf(same)
            same_vars[(i, j)] = same
            obj_terms.append(c_int * same)

    model.Maximize(sum(obj_terms))

    # ── Symmetry breaking: fix first G students to distinct groups ────────
    # For any feasible solution, a relabeling exists where student g is in
    # group g (for g=0..G-1), so this constraint loses no optimal solutions.
    for g in range(min(G, n)):
        model.Add(assign[g] == g)
        model.AddHint(assign[g], g)
        for gg in range(G):
            model.AddHint(members[g][gg], 1 if gg == g else 0)

    # ── Greedy warm-start hint (remaining students) ────────────────────────
    hint = _greedy_assignment(n, G, group_size_max, compat_matrix, weights)
    # Override first G to match symmetry-break
    for g in range(min(G, n)):
        hint[g] = g
    for i in range(min(G, n), n):
        model.AddHint(assign[i], hint[i])
        for g in range(G):
            model.AddHint(members[i][g], 1 if hint[i] == g else 0)
    for (i, j), sv in same_vars.items():
        model.AddHint(sv, 1 if hint[i] == hint[j] else 0)

    # ── Solve ─────────────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers  = 4

    t0 = time.time()
    status = solver.Solve(model)
    elapsed = time.time() - t0

    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "groups": [],
            "total_compat": 0.0,
            "solve_time_s": round(elapsed, 3),
            "status": status_name,
        }

    # ── Extract result ─────────────────────────────────────────────────────
    assignment = [solver.Value(assign[i]) for i in range(n)]

    groups = []
    total = 0.0
    for g in range(G):
        mbrs = [i for i in range(n) if assignment[i] == g]
        if not mbrs:
            continue
        score = sum(
            compat_matrix[mbrs[a], mbrs[b]]
            for a in range(len(mbrs))
            for b in range(a + 1, len(mbrs))
        )
        groups.append({
            "group_id":    g,
            "members":      [students[m]["id"]   for m in mbrs],
            "member_names": [students[m]["name"] for m in mbrs],
            "group_compat": round(float(score), 4),
        })
        total += score

    return {
        "groups":        groups,
        "total_compat":  round(float(total), 4),
        "solve_time_s":  round(elapsed, 3),
        "status":        status_name,
    }


# ──────────────────────────────────────────────────────────────────────────────
#  Public entry point
# ──────────────────────────────────────────────────────────────────────────────

def run_matching(
    scored_students: List[Dict],
    axis_weights: Optional[Dict[str, float]] = None,
    group_size_min: int = 4,
    group_size_max: int = 5,
    time_limit_s: float = 30.0,
) -> Dict:
    """
    Run ILP, random baseline, and Oracle for one cohort.

    - ILP and random use 'axis_scores'     (step 4b — scored from survey)
    - Oracle uses      'true_axis_scores'  (ORACLE PATH — noise-free latent vector)

    Archetype labels from clustering are NOT accepted or used here.
    """
    n = len(scored_students)
    student_ids = [s["id"] for s in scored_students]

    # ── Compatibility matrices ─────────────────────────────────────────────
    compat_scored = build_compat_matrix(scored_students, "axis_scores",      axis_weights)
    compat_oracle = build_compat_matrix(scored_students, "true_axis_scores", axis_weights)

    # ── Solve ──────────────────────────────────────────────────────────────
    ilp_res    = ilp_groups(scored_students, compat_scored,  group_size_min, group_size_max, time_limit_s, axis_weights)
    random_res = random_groups(scored_students, compat_scored, group_size_max)
    oracle_res = ilp_groups(scored_students, compat_oracle,  group_size_min, group_size_max, time_limit_s, axis_weights)

    return {
        "student_ids":   student_ids,
        "ilp_result":    ilp_res,
        "random_result": random_res,
        "oracle_result": oracle_res,
        "compat_matrix": compat_scored.tolist(),
    }
