"""
StudyMatch — group formation as an ILP (OR-Tools CP-SAT).

Given one course's pool of unassigned students and pair_score(a, b) (the
0-100 compatibility from algorithm/compatibility.py), partition them into
groups of 4-5 that MAXIMIZE the total within-group pairwise compatibility:

    maximize   sum_g sum_{i<j} score(i,j) * [i and j both in g]
    subject to each student in at most one group
               every opened group has 4 or 5 members
               exactly max_coverable(n) students are placed

Why ILP and not a genetic algorithm (Garcia-Velez et al., 2018): at this
scope (one course, tens to a few hundred students) an exact solver gives a
provable optimum (or a bounded gap within the time limit), is reproducible,
and expresses the constraints natively instead of as fitness penalties.

Only students from the SAME course are ever passed in together (callers
scope the pool per course). There is intentionally NO inter-group
balancing/fairness term: this is intra-group similarity only - see README
"Known limitations" for the echo-chamber tradeoff this accepts.

Because the objective sums pairs, a 5-group contributes 10 pairs and a
4-group 6, so the optimum naturally prefers 5s and uses 4s only where the
headcount forces it.
"""

import random
from itertools import combinations

from ortools.sat.python import cp_model

GROUP_MIN = 4
GROUP_MAX = 5
SCORE_SCALE = 100        # CP-SAT needs integers: 0-100 score -> 0-10000
DETERMINISTIC_TIME = 20.0  # CP-SAT work units; ~4s wall for a 27-student course
NUM_WORKERS = 8


def max_coverable(n):
    """Largest m <= n expressible as 4a + 5b (0 if none). Every n >= 12 is fully coverable."""
    for m in range(n, 0, -1):
        if any((m - GROUP_MAX * b) % GROUP_MIN == 0 for b in range(m // GROUP_MAX + 1)):
            return m
    return 0


def form_groups(student_ids, pair_score, deterministic_time=DETERMINISTIC_TIME):
    """
    Returns (groups, leftover, info):
      groups   - list of member-id lists (each sorted), sizes 4-5
      leftover - set of ids the ILP couldn't place (only when n is 1-3, 6, 7 or 11)
      info     - {"status", "objective", "bound", "solve_time_s"}; objective == bound
                 means the grouping is proven optimal
    Leftovers are handed back to the caller's remainder policy
    (algorithm/placement.py) rather than being forced into an undersized group.
    """
    ids = sorted(student_ids)
    n = len(ids)
    m = max_coverable(n)
    if m == 0:
        return [], set(ids), {"status": "SKIPPED", "objective": 0.0, "bound": None, "solve_time_s": 0.0}

    G = m // GROUP_MIN  # most groups that could ever be opened
    model = cp_model.CpModel()

    # Symmetry breaking: label groups by their lowest-index member, so student
    # i can only sit in groups 0..i. Every partition has exactly one such
    # labeling, so no solution is lost.
    x = {(i, g): model.NewBoolVar(f"x_{i}_{g}") for i in range(n) for g in range(min(i + 1, G))}
    used = [model.NewBoolVar(f"used_{g}") for g in range(G)]

    for i in range(n):
        model.Add(sum(x[i, g] for g in range(min(i + 1, G))) <= 1)
    for g in range(G):
        members = [x[i, g] for i in range(g, n)]
        model.Add(sum(members) >= GROUP_MIN * used[g])
        model.Add(sum(members) <= GROUP_MAX * used[g])
        if g + 1 < G:
            model.Add(used[g] >= used[g + 1])
    model.Add(sum(x.values()) == m)

    # z[i,j,g] = 1 only if both i and j are in g. Scores are non-negative and
    # maximized, so upper-bounding z by each x is enough.
    objective = []
    zvars = {}
    pairs_of = {}                       # (i, g) -> every z touching student i in group g
    pairs_in = [[] for _ in range(G)]   # g -> every z in group g
    for i, j in combinations(range(n), 2):
        w = int(round(pair_score(ids[i], ids[j]) * SCORE_SCALE))
        if w <= 0:
            continue
        for g in range(min(i + 1, G)):  # i < j, so i's range is the binding one
            z = zvars[i, j, g] = model.NewBoolVar(f"z_{i}_{j}_{g}")
            model.AddImplication(z, x[i, g])
            model.AddImplication(z, x[j, g])
            pairs_of.setdefault((i, g), []).append(z)
            pairs_of.setdefault((j, g), []).append(z)
            pairs_in[g].append(z)
            objective.append(w * z)
    # Valid cuts that tighten the LP bound a lot: a student has at most
    # GROUP_MAX-1 partners in their group, and a group at most C(5,2) pairs.
    for (i, g), zs in pairs_of.items():
        model.Add(sum(zs) <= (GROUP_MAX - 1) * x[i, g])
    for g in range(G):
        model.Add(sum(pairs_in[g]) <= (GROUP_MAX * (GROUP_MAX - 1) // 2) * used[g])
    model.Maximize(sum(objective))

    # Warm start from a fast heuristic, and keep it as a floor: whatever the
    # solver returns within the time budget is never worse than this.
    heuristic = _heuristic_groups(ids, pair_score, m)
    _add_hint(model, x, zvars, used, heuristic, G)

    solver = cp_model.CpSolver()
    # Deterministic budget (not wall-clock) + interleaved workers = the same
    # input always yields the same groups, on any machine.
    solver.parameters.max_deterministic_time = deterministic_time
    solver.parameters.max_time_in_seconds = 10 * deterministic_time  # safety net only
    solver.parameters.num_workers = NUM_WORKERS
    solver.parameters.interleave_search = True
    solver.parameters.random_seed = 0
    status = solver.Solve(model)
    solved = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    heuristic_groups = [sorted(ids[i] for i in grp) for grp in heuristic]
    info = {
        "status": solver.StatusName(status),
        "objective": round(total_score(heuristic_groups, pair_score), 1),
        "bound": round(solver.BestObjectiveBound() / SCORE_SCALE, 1) if solved else None,
        "solve_time_s": round(solver.WallTime(), 2),
    }
    groups = heuristic_groups
    if solved:
        ilp_groups = []
        for g in range(G):
            members = sorted(ids[i] for i in range(g, n) if solver.Value(x[i, g]))
            if members:
                ilp_groups.append(members)
        ilp_total = total_score(ilp_groups, pair_score)
        if ilp_total >= info["objective"]:
            groups, info["objective"] = ilp_groups, round(ilp_total, 1)
        else:
            info["status"] += " (heuristic kept)"

    placed = {s for grp in groups for s in grp}
    return groups, set(ids) - placed, info


def _heuristic_groups(ids, pair_score, m):
    """
    Greedy (seed each group with the best remaining pair, grow it by whoever
    adds the most), then pairwise-swap local search until no swap between two
    groups - or between a group and the unplaced leftovers - improves the
    total. Returns groups of indices into ids.
    """
    n = len(ids)
    sc = [[pair_score(ids[a], ids[b]) if a != b else 0.0 for b in range(n)] for a in range(n)]
    remaining = set(range(n))
    groups = []
    for size in _group_sizes(m):
        i, j = max(combinations(sorted(remaining), 2), key=lambda p: sc[p[0]][p[1]])
        grp = [i, j]
        remaining -= {i, j}
        while len(grp) < size:
            k = max(sorted(remaining), key=lambda c: sum(sc[c][o] for o in grp))
            grp.append(k)
            remaining.discard(k)
        groups.append(grp)
    pools = groups + [sorted(remaining)]  # last pool = leftovers (no score)

    def gain(a, b, pa, pb):
        """Score change from swapping student a (in pools[pa]) with b (in pools[pb])."""
        d = 0.0
        if pa < len(groups):
            d += sum(sc[b][o] - sc[a][o] for o in pools[pa] if o != a)
        if pb < len(groups):
            d += sum(sc[a][o] - sc[b][o] for o in pools[pb] if o != b)
        return d

    improved = True
    while improved:
        improved = False
        for pa in range(len(groups)):
            for pb in range(pa + 1, len(pools)):
                for a in list(pools[pa]):
                    for b in list(pools[pb]):
                        if gain(a, b, pa, pb) > 1e-9:
                            pools[pa][pools[pa].index(a)] = b
                            pools[pb][pools[pb].index(b)] = a
                            improved = True
                            break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break
    return [sorted(g) for g in groups]


def _add_hint(model, x, zvars, used, groups, G):
    # Relabel by lowest member index so the hint satisfies the symmetry breaking.
    groups = sorted(groups, key=min)
    assign = {i: g for g, grp in enumerate(groups) for i in grp}
    for (i, g), var in x.items():
        model.AddHint(var, assign.get(i) == g)
    for (i, j, g), var in zvars.items():
        model.AddHint(var, assign.get(i) == g and assign.get(j) == g)
    for g in range(G):
        model.AddHint(used[g], g < len(groups))


def _group_sizes(m):
    """Most 5s possible, the rest 4s (the ILP optimum's usual shape)."""
    for fives in range(m // GROUP_MAX, -1, -1):
        if (m - GROUP_MAX * fives) % GROUP_MIN == 0:
            return [GROUP_MAX] * fives + [GROUP_MIN] * ((m - GROUP_MAX * fives) // GROUP_MIN)
    return []


def total_score(groups, pair_score):
    return sum(pair_score(a, b) for grp in groups for a, b in combinations(grp, 2))


def random_baseline(groups, pair_score, trials=200, seed=0):
    """
    Mean total score of random partitions with the SAME group sizes over the
    SAME students - the "is the ILP actually doing anything?" comparison.
    """
    rng = random.Random(seed)
    people = [s for grp in groups for s in grp]
    sizes = [len(grp) for grp in groups]
    totals = []
    for _ in range(trials):
        rng.shuffle(people)
        shuffled, k = [], 0
        for size in sizes:
            shuffled.append(people[k:k + size])
            k += size
        totals.append(total_score(shuffled, pair_score))
    return sum(totals) / len(totals)
