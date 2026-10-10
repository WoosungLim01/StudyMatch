"""
Group formation at simulation scale.

Pools of up to ILP_MAX_POOL students use the live ILP (algorithm/grouping.py)
unchanged. That ILP creates a variable for every pair of students in every
possible group, so it can't build a model for a 500-student course; larger
pools use a swap search on the same objective (total within-group pair
score, groups of 4-5): greedy start, then the best single swap between two
groups is applied until no swap helps.
"""

import numpy as np

from algorithm.grouping import _group_sizes, form_groups, max_coverable

ILP_MAX_POOL = 30


def form(pool, S, index, rng):
    """pool: student ids; S: course score matrix (0-100); index: id -> row of S.
    Returns (groups as sorted id lists, leftover ids)."""
    ids = sorted(pool)
    if len(ids) <= ILP_MAX_POOL:
        groups, leftover, _ = form_groups(ids, lambda a, b: float(S[index[a], index[b]]), deterministic_time=3.0)
        return groups, set(leftover)
    rows = [index[s] for s in ids]
    return swap_search(ids, S[np.ix_(rows, rows)], rng), set()


def swap_search(ids, S, rng, max_iters=None):
    n = len(ids)
    sizes = _group_sizes(max_coverable(n))
    assert sum(sizes) == n, "pools this large always split exactly into 4s and 5s"
    S = S.astype(float).copy()
    np.fill_diagonal(S, 0.0)
    G = len(sizes)
    assign = np.full(n, -1)
    count = np.zeros(G, dtype=int)
    M = np.zeros((n, G))                              # M[i, g] = sum of i's scores with members of g
    order = rng.permutation(n)
    for g, s in enumerate(order[:G]):
        assign[s], count[g] = g, 1
        M[:, g] += S[:, s]
    for s in order[G:]:
        open_groups = np.flatnonzero(count < np.array(sizes))
        g = open_groups[np.argmax(M[s, open_groups])]
        assign[s] = g
        count[g] += 1
        M[:, g] += S[:, s]

    for _ in range(max_iters or 50 * n):
        own = M[np.arange(n), assign]
        X = M[:, assign]                              # X[j, i] = j's score with i's group
        gain = X + X.T - 2 * S - own[:, None] - own[None, :]
        gain[assign[:, None] == assign[None, :]] = -np.inf
        i, j = np.unravel_index(np.argmax(gain), gain.shape)
        if gain[i, j] <= 1e-9:
            break
        a, b = assign[i], assign[j]
        M[:, a] += S[:, j] - S[:, i]
        M[:, b] += S[:, i] - S[:, j]
        assign[i], assign[j] = b, a

    return [sorted(ids[k] for k in np.flatnonzero(assign == g)) for g in range(G)]
