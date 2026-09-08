"""
StudyMatch — shared matching math.

Used by BOTH generate_sample_data.py (initial batch generation, fits a fresh
KMeans over the whole population) and add_student.py (incremental: one new
student at a time, assigned to the NEAREST existing archetype centroid rather
than re-clustering everyone). Pulling these out of generate_sample_data.py
means both paths score compatibility with the exact same formula — no risk of
the incremental path silently drifting from the original one.

Matching scope (current decision, same as generate_sample_data.py's docstring):
compatibility is personality-similarity ONLY, across all 14 traits. Time
(availability) is still computed here — study_style_component — but carries
zero weight in pair_compatibility(); it's informational data, not a scoring
input. Academic topic-help tracking was removed entirely (no topic data left
to compute it from) — see README.md.
"""

from statistics import mean

TRAITS = [
    "seriousness", "structure", "accountability", "social_preference",
    "communication_frequency", "competitiveness", "preparation",
    "leadership", "talkativeness", "assertiveness", "helpfulness",
    "collaboration", "study_pace", "patience",
]


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
    The ONLY thing that drives compatibility_score: mean closeness across all
    14 personality traits (1-5 scale). No trait is scored for "reward
    differences" complementarity — a good pair is a similar pair.
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
    compatibility_score = personality similarity only.

    study_style is still computed and reported in `breakdown` (valid input
    data, kept for future use / transparency) but carries zero weight in the
    score.
    """
    overlap = weekly_overlap_minutes([av_a, av_b])
    sim = similarity_component(pa, pb)
    style = study_style_component(av_a, av_b, overlap)
    score = sim
    return round(score * 100, 1), overlap, {
        "similarity": round(sim * 100, 1),
        "study_style": round(style * 100, 1),   # informational only, not scored
    }


def preferred_role_for(traits):
    """
    Deterministic top-role pick from a trait dict (the same scoring
    generate_sample_data.py uses). Callers that want the ~15% "Flexible/No
    Preference" override apply their own randomness on top of this — kept
    out of here so this stays pure and reusable.
    """
    lead, talk, help_, collab = traits["leadership"], traits["talkativeness"], traits["helpfulness"], traits["collaboration"]
    scores = {
        "Organizer": lead, "Explainer": help_, "Problem Solver": collab,
        "Listener": 6 - talk, "Motivator": (lead + talk) / 2,
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
