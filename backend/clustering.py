"""
GMM clustering step (§3 steps 3–4).

Key design rules from §3:
  - N archetypes is DISCOVERED from data via BIC + silhouette, never hard-coded.
  - predict_proba() produces soft membership (4a) → display layer only.
  - The raw continuous vector (4b) goes to matching — archetype labels do NOT.

Archetype labels (step 4a) terminate here: they are returned for the UI display
layer and must never be passed into compatibility() or the ILP solver.
"""

import numpy as np
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import silhouette_score
from typing import List, Dict, Tuple, Optional

from synthetic import AXES

# Range over which to search for optimal number of components
_K_MIN = 2
_K_MAX = 8

# Axis-level labels used to auto-generate archetype names from mean vectors
_AXIS_HIGH_LABELS = {
    "planning":      "Planner",
    "environment":   "Quiet",
    "collaboration": "Social",
    "flexibility":   "Flexible",
    "feedback":      "Feedback-seeker",
    "motivation":    "Achiever",
}
_AXIS_LOW_LABELS = {
    "planning":      "Crammer",
    "environment":   "Buzzy",
    "collaboration": "Solo",
    "flexibility":   "Rigid",
    "feedback":      "Self-directed",
    "motivation":    "Casual",
}


def _auto_name(mean_vec: Dict[str, float]) -> str:
    """Generate a descriptive archetype name from its mean axis vector."""
    sorted_axes = sorted(AXES, key=lambda a: abs(mean_vec[a] - 0.5), reverse=True)
    top1, top2 = sorted_axes[0], sorted_axes[1]

    def label(ax: str) -> str:
        return _AXIS_HIGH_LABELS[ax] if mean_vec[ax] >= 0.5 else _AXIS_LOW_LABELS[ax]

    return f"{label(top1)} {label(top2)}"


def run_clustering(
    scored_students: List[Dict],
    k_min: int = _K_MIN,
    k_max: int = _K_MAX,
    random_state: int = 42,
) -> Dict:
    """
    Fit GMMs over k ∈ [k_min, k_max], select optimal k via BIC (lower=better)
    and silhouette score (higher=better), then return soft memberships.

    Returns a dict with:
      n_optimal         — chosen number of archetypes
      bic_curve         — list of {k, bic} for the BIC plot
      silhouette_curve  — list of {k, silhouette}
      archetypes        — list of archetype descriptors (DISPLAY LAYER ONLY)
      student_clusters  — soft membership per student (DISPLAY LAYER ONLY)

    The archetype_id and soft_membership fields in student_clusters are for
    the UI display ONLY.  matching.py uses axis_scores, not these labels.
    """
    # Normalize axis scores to [0, 1] for GMM (avoids axis-scale bias)
    X = np.array([
        [s["axis_scores"][ax] for ax in AXES]
        for s in scored_students
    ])
    scaler = MinMaxScaler()
    X_norm = scaler.fit_transform(X)

    n = len(scored_students)
    # Cap k_max: at least 8 students per archetype on average keeps GMM stable
    k_max_eff = min(k_max, max(k_min, n // 8), n - 1)

    bic_curve = []
    sil_curve = []
    models: Dict[int, GaussianMixture] = {}

    for k in range(k_min, k_max_eff + 1):
        gm = GaussianMixture(
            n_components=k,
            covariance_type="full",
            random_state=random_state,
            n_init=3,
        )
        gm.fit(X_norm)
        bic = gm.bic(X_norm)
        labels = gm.predict(X_norm)

        sil = float(silhouette_score(X_norm, labels)) if k > 1 and len(set(labels)) > 1 else 0.0

        bic_curve.append({"k": k, "bic": round(float(bic), 2)})
        sil_curve.append({"k": k, "silhouette": round(sil, 4)})
        models[k] = gm

    # Select k: best BIC (elbow heuristic) cross-checked with silhouette
    best_k = _select_k(bic_curve, sil_curve)
    best_gm = models[best_k]

    # Soft membership (step 4a) — DISPLAY LAYER ONLY
    proba = best_gm.predict_proba(X_norm)          # shape (n, best_k)
    hard_labels = best_gm.predict(X_norm)           # shape (n,)

    # Build archetype descriptors from GMM means (in normalized space)
    means_norm = best_gm.means_                      # shape (best_k, n_axes)
    archetypes = []
    for k_idx in range(best_k):
        mean_dict = {ax: float(means_norm[k_idx, ax_i]) for ax_i, ax in enumerate(AXES)}
        archetypes.append({
            "archetype_id": k_idx,
            "name": _auto_name(mean_dict),          # label for display only
            "mean_normalized": mean_dict,
            # Convert back to Likert space for readability
            "mean_likert": {
                ax: round(float(scaler.inverse_transform(means_norm[[k_idx]])[0][ax_i]), 2)
                for ax_i, ax in enumerate(AXES)
            },
            "n_members": int(np.sum(hard_labels == k_idx)),
        })

    # Per-student cluster info (step 4a → display layer)
    student_clusters = []
    for i, s in enumerate(scored_students):
        primary_k = int(hard_labels[i])
        soft = {k_idx: round(float(proba[i, k_idx]), 4) for k_idx in range(best_k)}
        strength = round(float(proba[i, primary_k]) * 100, 1)

        student_clusters.append({
            "id": s["id"],
            "name": s["name"],
            "primary_archetype_id": primary_k,
            # ── DISPLAY LAYER ONLY (step 4a) ─────────────────────────────
            # Do NOT pass primary_archetype_id or soft_membership into matching.py.
            # matching.py receives axis_scores (step 4b), not these labels.
            "soft_membership": soft,
            "strength_pct": strength,
        })

    return {
        "n_optimal": best_k,
        "bic_curve": bic_curve,
        "silhouette_curve": sil_curve,
        "archetypes": archetypes,        # display layer
        "student_clusters": student_clusters,  # display layer
    }


def _select_k(bic_curve: List[Dict], sil_curve: List[Dict]) -> int:
    """
    Heuristic: pick k with lowest BIC; if the silhouette peak is at a
    different k and its BIC is within 5 % of the minimum, prefer the
    silhouette peak (tends to avoid over-segmentation).
    """
    bics = [(d["k"], d["bic"]) for d in bic_curve]
    sils = [(d["k"], d["silhouette"]) for d in sil_curve]

    best_bic_k = min(bics, key=lambda x: x[1])[0]
    best_sil_k = max(sils, key=lambda x: x[1])[0]
    min_bic = min(b for _, b in bics)

    # BIC at the silhouette peak
    bic_at_sil_k = next(b for k, b in bics if k == best_sil_k)

    if bic_at_sil_k <= min_bic * 1.05:
        return best_sil_k
    return best_bic_k
