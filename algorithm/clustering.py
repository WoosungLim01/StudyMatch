"""
StudyMatch — study-type classification. DISPLAY LAYER ONLY.

Hybrid design: the TYPES are fixed by theory, the MEMBERSHIP is computed by a
Gaussian mixture.

    survey -> score_axes() -> 6 axis scores
                 |
                 +-- 2 family scores --> 4-type GMM --> "Study Captain 72%" (display)
                 +-- intensity -----> motivation badge "High Drive"         (display)
                 +-- all 6 ---------> pair_compatibility() -> ILP groups    (matching)

Why the 4 types (k fixed, not discovered): the 24 items were built on the
MSLQ split of learning STRATEGIES vs MOTIVATION, which groups the 6 axes as
  Self-regulation = planning + structure + reliability  (MSLQ metacognitive
                    self-regulation, organization, effort regulation)
  Social mode     = session_mode + collaboration        (StudyMatch items)
  Motivation      = intensity                            (MSLQ self-efficacy + task value)
Types are the 2x2 of the two STYLE families, and the mixture lives in that
same 2-D space: each student's self-regulation and social-mode FAMILY
SCORES (the mean of the family's axes). Working on family means rather than
the 5 raw axes matters: axes inside a family are strongly correlated
(planning/structure/reliability ~0.9), and treating them as independent
dimensions would count the same evidence three times and push every
membership to ~100%. Motivation is a level (more is better), not a style,
so it is shown as a separate badge rather than baked into a type name - and
it already weighs 1.5x in matching.

Why a GMM on top of fixed types (instead of hard cutoffs at 3.0):
  - soft membership: a student near a boundary is "55% / 45%", not flipped
    by a 0.02 difference
  - cutoffs follow the real response distribution (self-report surveys skew
    high), because component means move to where people actually are
  - each type's spread, and how the two families co-vary, are learned
    (full 2x2 covariance per type)
  - log-likelihood flags profiles that fit no type well (see quality.py)

Big-data workflow: fit ONCE on a random sample (<= FIT_SAMPLE_MAX rows), store
the model (archetype + model_meta tables), then classify each new student
against the stored model - O(1) per student, no full-data pass. Re-fit
occasionally with data/refit_archetypes.py.

Label stability: components are initialized at the theory centers
(means_init), and after fitting each component must still sit closest to
its OWN theory center. If not (or a component collapses), the fit is
rejected and the theory model is kept, so a label never silently changes
meaning. Below MIN_FIT_N students there is too little data to fit reliably
(the mixture has 23 parameters); the theory model (theory centers, equal
weights, fixed spread - cutoffs at 3.0 with a soft edge) is used as-is.

Nothing in this module may be imported by compatibility.py / grouping.py.
"""

import math

import numpy as np
from sklearn.mixture import GaussianMixture

SELF_REG_AXES = ("planning", "structure", "reliability")
SOCIAL_AXES = ("session_mode", "collaboration")
FAMILIES = [SELF_REG_AXES, SOCIAL_AXES]   # model dimensions, in this order
MOTIVATION_AXIS = "intensity"

HIGH, LOW = 4.0, 2.0            # theory centers: one point either side of the scale midpoint
THEORY_SD = 0.75                 # theory model's spread per family score (1-5 scale)
MOTIVATION_CUTOFF = 3.0

MIN_FIT_N = 200                  # ~10 students per model parameter; below this, theory model
FIT_SAMPLE_MAX = 20_000          # fit on a random sample of at most this many students
MIN_COMPONENT_WEIGHT = 0.02      # a fitted type holding <2% of people counts as collapsed
REG_COVAR = 0.05                 # variance floor (sd ~0.22): family scores move in ~0.1-0.2 steps
ATYPICAL_PERCENTILE = 2.5        # bottom 2.5% log-likelihood of the fit sample = "atypical"

# id, name, description, self-regulation high?, social high?
TYPES = [
    ("arch_captain", "Study Captain",
     "Comes prepared with a plan and keeps sessions on track - happy to lead and explain out loud.",
     True, True),
    ("arch_architect", "Focused Architect",
     "Organized and dependable, but prefers to work things out quietly and bring answers to the group.",
     True, False),
    ("arch_explorer", "Collaborative Explorer",
     "Goes with the flow and learns by talking problems through together, not by following a checklist.",
     False, True),
    ("arch_sprinter", "Independent Sprinter",
     "Works in focused solo bursts, often close to deadlines, rather than on a fixed schedule.",
     False, False),
]


THEORY_CENTERS = np.array([[HIGH if sr else LOW, HIGH if so else LOW] for _, _, _, sr, so in TYPES])


def family_scores(traits):
    """[self-regulation, social mode]: the mean of each family's axis scores."""
    return np.array([sum(traits[a] for a in fam) / len(fam) for fam in FAMILIES], dtype=float)


def motivation_badge(intensity):
    return "High Drive" if intensity >= MOTIVATION_CUTOFF else "Steady Pace"


# ─────────────────────────────────────────────────────────────
#  Model
# ─────────────────────────────────────────────────────────────
#
# A model is a plain dict so it can be stored in / loaded from the DB:
#   {"source": "theory" | "fitted", "n_fit", "covariance_type", "note",
#    "loglik_threshold": float | None,
#    "components": [{"archetype_id", "name", "description",
#                    "weight", "mean": [2], "covariance": [[2x2]]}]}
#   (mean/covariance are over the 2 family scores, see family_scores())

def theory_model():
    cov = (np.eye(len(FAMILIES)) * THEORY_SD ** 2).tolist()
    return {
        "source": "theory", "n_fit": 0, "covariance_type": "theory", "note": None,
        "loglik_threshold": None,
        "components": [
            {"archetype_id": tid, "name": name, "description": desc,
             "weight": 1 / len(TYPES), "mean": THEORY_CENTERS[k].tolist(), "covariance": cov}
            for k, (tid, name, desc, _, _) in enumerate(TYPES)
        ],
    }


def fit_model(X, random_state=42):
    """
    X: (n, 2) family-score array (see family_scores()). Returns a fitted model, or the theory model
    (with "note" saying why) when there's too little data or the fit fails
    the label-stability check. loglik_threshold is always set from X when
    X is non-empty, so atypical-profile flagging works either way.
    """
    X = np.asarray(X, dtype=float)
    n = len(X)
    if n > FIT_SAMPLE_MAX:
        X = X[np.random.default_rng(random_state).choice(n, FIT_SAMPLE_MAX, replace=False)]

    model = theory_model()
    if n < MIN_FIT_N:
        model["note"] = f"only {n} students (< {MIN_FIT_N}) - using theory model"
    else:
        gm = GaussianMixture(
            n_components=len(TYPES), covariance_type="full", reg_covar=REG_COVAR,
            means_init=THEORY_CENTERS, weights_init=np.full(len(TYPES), 1 / len(TYPES)),
            random_state=random_state,
        ).fit(X)
        problem = _stability_problem(gm)
        if problem:
            model["note"] = f"fit rejected ({problem}) - using theory model"
        else:
            for k, c in enumerate(model["components"]):
                c["weight"] = float(gm.weights_[k])
                c["mean"] = gm.means_[k].tolist()
                c["covariance"] = gm.covariances_[k].tolist()
            model.update(source="fitted", n_fit=len(X), covariance_type="full")

    if len(X):
        model["loglik_threshold"] = float(np.percentile(log_likelihood(model, X), ATYPICAL_PERCENTILE))
    return model


def _stability_problem(gm):
    """None if every fitted component still represents its own theory type."""
    for k, (_, name, _, _, _) in enumerate(TYPES):
        nearest = int(np.argmin(np.linalg.norm(THEORY_CENTERS - gm.means_[k], axis=1)))
        if nearest != k:
            return f"'{name}' drifted toward '{TYPES[nearest][1]}'"
        if gm.weights_[k] < MIN_COMPONENT_WEIGHT:
            return f"'{name}' collapsed (weight {gm.weights_[k]:.3f})"
    return None


# ─────────────────────────────────────────────────────────────
#  Scoring against a stored model
# ─────────────────────────────────────────────────────────────

def _component_log_densities(model, X):
    """(n, k) array of log(weight_k * N(x; mean_k, cov_k))."""
    X = np.atleast_2d(np.asarray(X, dtype=float))
    d = X.shape[1]
    out = np.empty((len(X), len(model["components"])))
    for k, c in enumerate(model["components"]):
        mu = np.asarray(c["mean"], dtype=float)
        cov = np.asarray(c["covariance"], dtype=float)
        _, logdet = np.linalg.slogdet(cov)
        diff = X - mu
        maha = np.einsum("ij,ij->i", diff, np.linalg.solve(cov, diff.T).T)
        out[:, k] = math.log(c["weight"]) - 0.5 * (d * math.log(2 * math.pi) + logdet + maha)
    return out


def log_likelihood(model, X):
    """Per-row mixture log-likelihood: how well each profile fits ANY type."""
    lp = _component_log_densities(model, X)
    m = lp.max(axis=1, keepdims=True)
    return (m + np.log(np.exp(lp - m).sum(axis=1, keepdims=True))).ravel()


def posterior(model, X):
    """(n, k) soft membership, rows sum to 1."""
    lp = _component_log_densities(model, X)
    p = np.exp(lp - lp.max(axis=1, keepdims=True))
    return p / p.sum(axis=1, keepdims=True)


def classify(traits, model):
    """
    One student -> {"archetype_id", "strength" (0-100), "membership" {id: %},
    "badge", "atypical"}.
    """
    x = family_scores(traits)
    p = posterior(model, x)[0]
    k = int(p.argmax())
    ll = float(log_likelihood(model, x)[0])
    threshold = model.get("loglik_threshold")
    return {
        "archetype_id": model["components"][k]["archetype_id"],
        "strength": round(float(p[k]) * 100, 1),
        "membership": {c["archetype_id"]: round(float(pi) * 100, 1) for c, pi in zip(model["components"], p)},
        "badge": motivation_badge(traits[MOTIVATION_AXIS]),
        "atypical": threshold is not None and ll < threshold,
    }
