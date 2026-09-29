"""
StudyMatch — shared matching math.

PLACEHOLDER NOTICE: pair_compatibility() (and therefore group formation in
generate_sample_data.py / algorithm/placement.py) is currently RANDOM, not a
real matching algorithm — see pair_compatibility()'s docstring. The real
algorithm is being built separately (Woosung) on top of the 6-axis survey
data in personality_profile; see docs/Woosung.md for the handoff.

similarity_component() (real personality-axis math) is kept and still used
for nearest_archetype() — archetype labeling is descriptive/informational,
not a matching decision, so it isn't randomized.

TRAITS is the 6 axes produced by the entry survey (planning, session_mode,
reliability, structure, intensity, collaboration) — see
algorithm/scoring.py for the 24-item Likert instrument and reverse-coding
that produces them from raw survey answers. Sourced from there so the axis
list has one owner.
"""

import random
from statistics import mean

from algorithm.scoring import AXES as TRAITS


def to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def weekly_overlap_minutes(avail_list):
    """Total overlapping minutes/week across ALL students in avail_list (same day required)."""
    by_day = {}
    for a in avail_list:
        for b in a["blocks"]:
            by_day.setdefault(b["day"], []).append((to_minutes(b["start_time"]), to_minutes(b["end_time"])))
    total = 0
    for day, spans in by_day.items():
        if len(spans) < len(avail_list):
            continue  # not everyone has a block this day
        start = max(s for s, _ in spans)
        end = min(e for _, e in spans)
        if end > start:
            total += end - start
    return total


def similarity_component(pa, pb):
    """
    Mean closeness across all 6 survey axes (1-5 scale). Used by
    nearest_archetype() for archetype labeling — NOT used by
    pair_compatibility() right now, which is a random placeholder (see its
    docstring).
    """
    sims = [1 - abs(pa[t] - pb[t]) / 4 for t in TRAITS]
    return mean(sims)


def study_style_component(av_a, av_b, overlap_minutes):
    """Informational only — NOT part of compatibility_score. See module docstring."""
    overlap_score = min(overlap_minutes / 240, 1.0)  # 4 hrs/week -> full score
    dur_sim = 1 - abs(av_a["preferred_session_duration"] - av_b["preferred_session_duration"]) / 60
    dur_sim = max(0, min(1, dur_sim))
    loc_match = 1.0 if av_a["preferred_location"] == av_b["preferred_location"] else 0.4
    onl_a, onl_b = av_a["online_vs_in_person_preference"], av_b["online_vs_in_person_preference"]
    onl_match = 1.0 if onl_a == onl_b else (0.6 if "hybrid" in (onl_a, onl_b) else 0.2)
    return mean([overlap_score, dur_sim, loc_match, onl_match])


def pair_compatibility(pa, pb, av_a, av_b):
    """
    PLACEHOLDER — compatibility_score is a random number for now, not
    computed from personality. Group FORMATION doesn't even use this score to
    decide anything (generate_sample_data.form_groups() and
    placement.run_placement() both just shuffle-and-chunk) - it only exists so
    pairwise_compatibility / group_score / match_data have *something* in
    them until the real algorithm (Woosung, see docs/Woosung.md) replaces it.

    study_style is still computed for real from availability data and
    reported in `breakdown` (kept for whenever real scoring comes back).
    """
    overlap = weekly_overlap_minutes([av_a, av_b])
    style = study_style_component(av_a, av_b, overlap)
    score = round(random.uniform(40, 95), 1)
    return score, overlap, {
        "similarity": score,
        "study_style": round(style * 100, 1),
    }


def preferred_role_for(traits):
    """
    Deterministic top-role pick from an axis-score dict (the same scoring
    generate_sample_data.py uses). Callers that want the ~15% "Flexible/No
    Preference" override apply their own randomness on top of this — kept
    out of here so this stays pure and reusable.

    Axis -> role mapping (redesigned for the 6-axis MSLQ-informed survey,
    replacing the old leadership/talkativeness/helpfulness-based version):
      Organizer      <- plans ahead AND likes structured sessions
      Explainer      <- learns by explaining / answering others' questions
      Problem Solver <- confident tackling hard material (self-efficacy)
      Listener       <- prefers quiet/independent work over talking through problems
      Motivator      <- reliable, follows through on commitments
    """
    scores = {
        "Organizer": (traits["planning"] + traits["structure"]) / 2,
        "Explainer": traits["collaboration"],
        "Problem Solver": traits["intensity"],
        "Listener": 6 - traits["session_mode"],
        "Motivator": traits["reliability"],
    }
    return max(scores, key=scores.get)


def nearest_archetype(traits, archetypes):
    """
    Assign a NEW student to whichever existing archetype's centroid they're
    most similar to (same similarity_component() used everywhere else) —
    deliberately NOT a re-clustering. Re-fitting KMeans over fake+real people
    together would reshuffle archetype_id for students who didn't change,
    which is exactly what the incremental workflow is meant to avoid.

    archetypes: list of dicts with "archetype_id" and "centroid_traits_1to5".
    Returns the archetype_id of the closest centroid.
    """
    best_id, best_sim = None, -1.0
    for a in archetypes:
        sim = similarity_component(traits, a["centroid_traits_1to5"])
        if sim > best_sim:
            best_sim, best_id = sim, a["archetype_id"]
    return best_id
