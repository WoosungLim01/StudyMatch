"""
Scoring and consistency-check step (§3 steps 1–2).

score_axis()              → continuous per-student vector (NOT binary/categorical)
response_consistency_check() → flag low-effort responders before clustering

Design rule (§3 critical): this module outputs raw continuous axis scores.
Archetype labels are assigned downstream in clustering.py and must NEVER
flow back into this module or into matching.py.
"""

import numpy as np
from typing import Dict, List, Tuple
from synthetic import SURVEY_ITEMS, AXES

# ── Reverse-coding constant ────────────────────────────────────────────────
_LIKERT_MAX = 6
_LIKERT_MIN = 1
_REVERSE_CONSTANT = _LIKERT_MAX + _LIKERT_MIN  # = 7 for a 6-point scale


def reverse_code(raw: int) -> int:
    return _REVERSE_CONSTANT - raw


def score_axis(raw_responses: Dict[str, int]) -> Dict[str, float]:
    """
    Average per-axis item scores after reverse-coding.

    Returns axis scores in [1, 6] (Likert space).
    Normalization to [0, 1] happens inside compatibility(), not here,
    to keep the output interpretable in survey units.
    """
    axis_items: Dict[str, List[float]] = {ax: [] for ax in AXES}

    for item in SURVEY_ITEMS:
        raw = raw_responses[item["id"]]
        score = reverse_code(raw) if item["reverse"] else float(raw)
        axis_items[item["axis"]].append(score)

    return {ax: float(np.mean(vals)) for ax, vals in axis_items.items()}


# ── Consistency check thresholds ───────────────────────────────────────────
_STRAIGHTLINE_SD_THRESHOLD = 0.35   # very low SD → likely straight-liner
# Note: noise_level=0.4 → σ≈0.48 for middling students, so 0.35 avoids false positives
_REVERSE_INCONSISTENCY_GAP = 2.0    # axis-level disagreement threshold (Likert units)


def response_consistency_check(raw_responses: Dict[str, int]) -> Dict:
    """
    Flag responses that suggest low effort or inattention.

    Returns:
      flag_low_effort: bool
      issues:          list of human-readable issue strings
      response_sd:     overall SD of raw responses (diagnostic)
    """
    raw_vals = list(raw_responses.values())
    sd = float(np.std(raw_vals))
    issues = []

    # 1. Straight-line detector
    if sd < _STRAIGHTLINE_SD_THRESHOLD:
        issues.append(f"Straight-liner (SD={sd:.2f} < {_STRAIGHTLINE_SD_THRESHOLD})")

    # 2. Reverse-item inconsistency per axis
    for ax in AXES:
        fwd_items = [
            float(raw_responses[it["id"]])
            for it in SURVEY_ITEMS
            if it["axis"] == ax and not it["reverse"]
        ]
        rev_items = [
            float(raw_responses[it["id"]])
            for it in SURVEY_ITEMS
            if it["axis"] == ax and it["reverse"]
        ]
        if not fwd_items or not rev_items:
            continue

        fwd_mean = np.mean(fwd_items)
        # After reverse-coding the reverse items, they should agree with fwd items
        rev_recoded_mean = np.mean([reverse_code(int(r)) for r in rev_items])
        gap = abs(fwd_mean - rev_recoded_mean)

        if gap > _REVERSE_INCONSISTENCY_GAP:
            issues.append(
                f"Inconsistent on '{ax}' axis (forward={fwd_mean:.1f}, "
                f"reverse-recoded={rev_recoded_mean:.1f}, gap={gap:.1f})"
            )

    return {
        "flag_low_effort": len(issues) > 0,
        "issues": issues,
        "response_sd": round(sd, 3),
    }


def run_pipeline(students: List[Dict]) -> List[Dict]:
    """
    Score and consistency-check a list of student records.

    Input:  raw student records from generate_cohort()
    Output: same records enriched with axis_scores + consistency fields.

    NEVER passes true_axis_scores forward — that field stays on the record
    untouched so the caller can route it to the Oracle path if needed.
    """
    results = []
    for s in students:
        axis_scores = score_axis(s["raw_responses"])
        consistency = response_consistency_check(s["raw_responses"])
        results.append({
            **s,
            "axis_scores": axis_scores,       # SCORING PATH (used by ILP)
            "consistency": consistency,
            # true_axis_scores stays on the record → ORACLE PATH, untouched
        })
    return results
