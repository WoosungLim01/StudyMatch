"""
StudyMatch — shared matching math (step 4b of the pipeline: raw vectors only).

pair_compatibility() scores two students from their 6 continuous survey-axis
values (algorithm/scoring.py) as a WEIGHTED SIMILARITY on a 0-100 scale:
homogeneous matching on purpose — StudyMatch is opt-in, and students use it
to find people who study the way they do and care as much as they do.

The two "motivation" axes (reliability, intensity) are weighted above the
four "style" axes (see AXIS_WEIGHTS): a gap in how seriously two people take
the course hurts a study group more than a gap in, say, how structured they
like sessions to be.

ARCHITECTURE RULE — do not break: archetype labels / soft memberships from
algorithm/clustering.py are a DISPLAY layer only and must never be passed
into anything in this module. Collapsing a 6-dim vector into one discrete
label throws away exactly the information matching needs.

TRAITS is the 6 axes produced by the entry survey (planning, session_mode,
reliability, structure, intensity, collaboration) — see
algorithm/scoring.py for the 24-item Likert instrument and reverse-coding
that produces them from raw survey answers. Sourced from there so the axis
list has one owner.
"""

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


# Motivation axes (reliability, intensity) count 1.5x; style axes 1x.
AXIS_WEIGHTS = {
    "planning": 1.0,
    "session_mode": 1.0,
    "reliability": 1.5,
    "structure": 1.0,
    "intensity": 1.5,
    "collaboration": 1.0,
}

AXIS_RANGE = 4.0  # axis scores live on 1-5


def weighted_similarity(pa, pb, weights=None):
    """
    Weighted mean closeness across the 6 survey axes, in [0, 1]:
    1 = identical on every axis, 0 = opposite ends of every axis.
    pa/pb are RAW continuous axis-score dicts - never archetype labels.
    """
    weights = weights or AXIS_WEIGHTS
    total_w = sum(weights[t] for t in TRAITS)
    return sum(weights[t] * (1 - abs(pa[t] - pb[t]) / AXIS_RANGE) for t in TRAITS) / total_w


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
    compatibility_score = 100 * weighted_similarity() of the two students'
    6-axis survey vectors. This is the number the ILP group former
    (algorithm/grouping.py) maximizes within each group.

    study_style (availability overlap, session length, location) is still
    computed and reported in `breakdown`, but deliberately NOT part of the
    score - schedule isn't a matching input right now.
    """
    overlap = weekly_overlap_minutes([av_a, av_b])
    style = study_style_component(av_a, av_b, overlap)
    score = round(weighted_similarity(pa, pb) * 100, 1)
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
