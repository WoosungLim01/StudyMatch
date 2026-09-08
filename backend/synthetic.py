"""
Synthetic data generator for StudyMatch.

Generates fake student cohorts with known latent archetypes so the pipeline
can be stress-tested and the Oracle upper-bound can be computed.

Architecture note (from brief §3):
  true_axis_scores  ← ORACLE PATH (noise-free latent vector)
  raw_responses     ← SURVEY PATH → scoring → scored_axis_scores → ILP
  These two paths MUST stay separate through the entire pipeline.
"""

import numpy as np
from typing import List, Dict

# ─────────────────────────────────────────────────────────────
#  Survey schema (18 items, 6 axes, ~half reverse-coded)
# ─────────────────────────────────────────────────────────────
SURVEY_ITEMS = [
    # ── Planning axis ──────────────────────────────────────────
    {"id": "q01", "text": "I plan my study sessions days or weeks in advance.",
     "axis": "planning", "reverse": False},
    {"id": "q02", "text": "Cramming right before a deadline works well for me.",
     "axis": "planning", "reverse": True},
    {"id": "q03", "text": "I follow a consistent weekly study schedule.",
     "axis": "planning", "reverse": False},
    # ── Environment axis ───────────────────────────────────────
    {"id": "q04", "text": "I need quiet surroundings to concentrate effectively.",
     "axis": "environment", "reverse": False},
    {"id": "q05", "text": "Background noise or music helps me study better.",
     "axis": "environment", "reverse": True},
    {"id": "q06", "text": "I prefer private, distraction-free spaces for studying.",
     "axis": "environment", "reverse": False},
    # ── Collaboration axis ─────────────────────────────────────
    {"id": "q07", "text": "Explaining concepts to others helps me understand better.",
     "axis": "collaboration", "reverse": False},
    {"id": "q08", "text": "I prefer to solve problems alone before discussing them.",
     "axis": "collaboration", "reverse": True},
    {"id": "q09", "text": "Group study sessions keep me motivated.",
     "axis": "collaboration", "reverse": False},
    # ── Flexibility axis ───────────────────────────────────────
    {"id": "q10", "text": "I adapt easily when study plans change at the last minute.",
     "axis": "flexibility", "reverse": False},
    {"id": "q11", "text": "It bothers me when group members cancel or reschedule.",
     "axis": "flexibility", "reverse": True},
    # ── Feedback axis ──────────────────────────────────────────
    {"id": "q12", "text": "I actively seek feedback from study partners.",
     "axis": "feedback", "reverse": False},
    {"id": "q13", "text": "I prefer to self-assess rather than ask others for feedback.",
     "axis": "feedback", "reverse": True},
    {"id": "q14", "text": "Regular check-ins with study partners help me stay on track.",
     "axis": "feedback", "reverse": False},
    # ── Motivation axis (highest-weighted, quasi-mandatory) ────
    {"id": "q15", "text": "I aim for the highest grade possible in my courses.",
     "axis": "motivation", "reverse": False},
    {"id": "q16", "text": "I attend every class session unless I'm genuinely ill.",
     "axis": "motivation", "reverse": False},
    {"id": "q17", "text": "I sometimes skip studying when I feel I already know the material.",
     "axis": "motivation", "reverse": True},
    {"id": "q18", "text": "I study for this course even when no exam is coming up.",
     "axis": "motivation", "reverse": False},
]

AXES = ["planning", "environment", "collaboration", "flexibility", "feedback", "motivation"]

# Default axis weights — motivation is highest, per §3 "mandatory tier"
DEFAULT_AXIS_WEIGHTS: Dict[str, float] = {
    "planning":      1.0,
    "environment":   0.8,
    "collaboration": 1.0,
    "flexibility":   0.7,
    "feedback":      0.7,
    "motivation":    1.5,
}

# Latent archetype templates in normalized [0, 1] space.
# 0 = axis-low end (e.g. crammer), 1 = axis-high end (e.g. planner).
_ARCHETYPE_TEMPLATES = [
    {"name": "Dedicated Planner",   "planning": 0.88, "environment": 0.85, "collaboration": 0.50, "flexibility": 0.22, "feedback": 0.55, "motivation": 0.92},
    {"name": "Social Collaborator", "planning": 0.55, "environment": 0.25, "collaboration": 0.92, "flexibility": 0.70, "feedback": 0.85, "motivation": 0.65},
    {"name": "Flexible Crammer",    "planning": 0.15, "environment": 0.45, "collaboration": 0.45, "flexibility": 0.90, "feedback": 0.32, "motivation": 0.25},
    {"name": "Quiet Achiever",      "planning": 0.75, "environment": 0.92, "collaboration": 0.18, "flexibility": 0.38, "feedback": 0.28, "motivation": 0.82},
    {"name": "Relaxed Social",      "planning": 0.30, "environment": 0.32, "collaboration": 0.75, "flexibility": 0.82, "feedback": 0.62, "motivation": 0.35},
]


def _norm_to_likert(v: float) -> float:
    """Map [0, 1] → [1, 6] Likert space."""
    return 1.0 + v * 5.0


def generate_cohort(
    n_students: int = 60,
    noise_level: float = 0.4,        # 0 = noiseless, 1 = high noise
    archetype_separation: float = 0.8,  # 0 = all similar, 1 = very distinct
    low_effort_pct: float = 0.08,    # fraction of noisy/random responders
    n_archetypes: int = 4,           # how many true archetypes to use (2–5)
    seed: int = 42,
) -> List[Dict]:
    """
    Return a list of synthetic student records.

    Each record contains:
      raw_responses     — Likert survey answers (what the scoring step sees)
      true_axis_scores  — ORACLE PATH: noise-free latent vector (never fed to ILP)
      is_low_effort     — whether this student is a noisy/random responder
    """
    rng = np.random.default_rng(seed)

    n_archetypes = max(2, min(n_archetypes, len(_ARCHETYPE_TEMPLATES)))
    templates = _ARCHETYPE_TEMPLATES[:n_archetypes]

    # Pull archetype means toward/away from center based on separation param
    center = 0.5
    adjusted = [
        {ax: center + (t[ax] - center) * archetype_separation for ax in AXES}
        for t in templates
    ]

    n_low = int(n_students * low_effort_pct)
    students = []

    for i in range(n_students):
        is_low_effort = i < n_low

        # ── Latent vector via Dirichlet blending of archetype means ──
        alpha = 5.0 * archetype_separation + 0.5
        weights = rng.dirichlet([alpha] * n_archetypes)
        primary_idx = int(np.argmax(weights))

        true_normalized = {
            ax: float(sum(weights[k] * adjusted[k][ax] for k in range(n_archetypes)))
            for ax in AXES
        }
        # ORACLE PATH: noiseless axis scores in [1, 6]
        true_axis_scores = {ax: _norm_to_likert(true_normalized[ax]) for ax in AXES}

        # ── Generate per-item raw responses ──
        raw_responses: Dict[str, int] = {}
        sigma = noise_level * 1.2  # σ in Likert units

        for item in SURVEY_ITEMS:
            ax = item["axis"]

            if is_low_effort:
                raw = int(rng.integers(1, 7))
            else:
                # Expected raw response accounts for reverse-coding direction
                expected = (7 - true_axis_scores[ax]) if item["reverse"] else true_axis_scores[ax]
                noisy = expected + rng.normal(0, sigma)
                raw = int(np.clip(round(noisy), 1, 6))

            raw_responses[item["id"]] = raw

        students.append({
            "id": i,
            "name": f"Student_{i + 1:03d}",
            "raw_responses": raw_responses,
            # ORACLE PATH — must never be passed into score_axis() or compatibility()
            "true_axis_scores": true_axis_scores,
            "primary_archetype": templates[primary_idx]["name"],
            "archetype_weights": weights.tolist(),
            "is_low_effort": is_low_effort,
        })

    # Shuffle so low-effort students aren't clustered at the front
    rng.shuffle(students)
    for idx, s in enumerate(students):
        s["id"] = idx

    return students
