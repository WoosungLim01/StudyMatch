"""
StudyMatch — sample data generator.

Produces synthetic-but-internally-consistent data for the StudyMatch spec:
students, personality survey results, availability, academic profiles,
study types (4 theory-defined types, soft membership via a Gaussian
mixture anchored at the theory centers), a pairwise compatibility
matrix (weighted 6-axis similarity), ILP-optimized study groups of 4-5,
group membership, individual/group match recommendations, course
global-chat activity, and post-formation outcome feedback.

This is sample/demo data only. The pipeline it runs is the real one:
  survey -> score_axes() -> 6-dim vector
     -> (display) algorithm/clustering.py: study type + strength % + motivation badge
     -> (matching) algorithm/compatibility.py -> algorithm/grouping.py ILP
Archetypes are never fed into matching - see algorithm/clustering.py.

Personality survey: each synthetic student gets 24 raw Likert answers (the
same "Version 3" instrument real respondents see in ui/survey.html — item
bank + reverse-coding in ../algorithm/scoring.py), not hand-picked axis
values directly. Each student's 6-axis target is one draw from a population
distribution calibrated on real data (real means, spreads, and cross-axis
correlations from a published MSLQ validation study and the IPIP Big Five
dataset — see REAL_AXIS_STATS below and docs/SYNTHETIC_DATA.md for the full
derivation and citations), not an invented archetype template. Raw item
answers are then drawn around that target using each axis's own real
item-noise SD, and scored with the exact same score_axes() the live
/api/survey endpoint uses, so synthetic and real students go through an
identical pipeline.

Academic profiles now carry only course_confidence/target_grade —
per-topic strong/weak/can_help/needs_help tracking (and the shared `topic`
table it needed) was removed; see README.md.

Run (from this directory):  python generate_sample_data.py
Output: ./sample/*.json

Shared matching math (weighted_similarity, pair_compatibility, etc.) lives in
../algorithm/compatibility.py so add_student.py's and app.py's incremental
paths use the exact same formulas — see that module's docstring.
"""

import json
import random
import sys
from pathlib import Path
from statistics import mean

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for `algorithm`
from algorithm.clustering import TYPES, classify, family_scores, fit_model
from algorithm.compatibility import TRAITS, pair_compatibility, preferred_role_for
from algorithm.grouping import form_groups as ilp_form_groups, random_baseline, total_score
from algorithm.quality import response_flag
from algorithm.scoring import SURVEY_ITEMS, reverse_code, score_axes

random.seed(42)
np.random.seed(42)

OUT = Path(__file__).parent / "sample"
OUT.mkdir(exist_ok=True)

# Matching uses the full personality vector as one weighted similarity signal
# (see algorithm/compatibility.weighted_similarity()).

ROLES = ["Organizer", "Explainer", "Problem Solver", "Listener", "Motivator", "Flexible/No Preference"]

# ---------------------------------------------------------------------------
# 1. Universities / Courses
# ---------------------------------------------------------------------------

university = {"university_id": "psu", "name": "Penn State University", "location": "University Park, PA"}

courses = [
    {
        "course_id": "psu-cmpsc465-001-fa26",
        "university_id": "psu",
        "course_code": "CMPSC 465",
        "course_title": "Data Structures and Algorithms",
        "section": "001",
        "semester": "Fall 2026",
        "topic_pool": [
            "Graph Algorithms", "Dynamic Programming", "Proofs & Correctness",
            "Greedy Algorithms", "Divide and Conquer", "NP-Completeness",
            "Big-O Analysis", "Recursion", "Sorting & Searching", "Network Flow",
        ],
        # shared "campus rhythm" of common study windows most students draw from
        "popular_slots": [
            ("Mon", 18, 21), ("Wed", 18, 21), ("Tue", 14, 17),
            ("Thu", 14, 17), ("Sun", 16, 20), ("Mon", 19, 22), ("Wed", 19, 22),
        ],
    },
    {
        "course_id": "psu-math230-002-fa26",
        "university_id": "psu",
        "course_code": "MATH 230",
        "course_title": "Calculus and Vector Analysis",
        "section": "002",
        "semester": "Fall 2026",
        "topic_pool": [
            "Multivariable Limits", "Partial Derivatives", "Double Integrals",
            "Triple Integrals", "Vector Fields", "Lagrange Multipliers",
            "Line Integrals", "Green's Theorem", "Parametric Surfaces",
        ],
        "popular_slots": [
            ("Mon", 19, 22), ("Wed", 19, 22), ("Sat", 10, 14), ("Tue", 18, 21),
        ],
    },
]

# ---------------------------------------------------------------------------
# 2. Students
# ---------------------------------------------------------------------------

FIRST_NAMES = [
    "Alex", "Emma", "Sarah", "Kevin", "Maya", "Jordan", "Priya", "Liam",
    "Noah", "Olivia", "Ethan", "Ava", "Wei", "Fatima", "Diego", "Grace",
    "Marcus", "Chloe", "Ravi", "Hannah", "Tyler", "Zoe", "Daniel", "Isabella",
    "Josh", "Nina", "Carlos", "Lily", "Sam", "Aisha", "Ben", "Julia",
    "Omar", "Ken", "Rachel", "Victor", "Amara", "Leo",
]
LAST_NAMES = [
    "Nguyen", "Smith", "Patel", "Johnson", "Kim", "Garcia", "Chen", "Brown",
    "Davis", "Rodriguez", "Wilson", "Martinez", "Lee", "Walker", "Hall",
    "Young", "King", "Wright", "Lopez", "Hill", "Scott", "Green", "Baker",
    "Adams", "Nelson", "Carter", "Mitchell", "Perez", "Roberts", "Turner",
    "Phillips", "Campbell", "Parker", "Evans", "Edwards", "Collins", "Stewart", "Morris",
]
MAJORS = ["Computer Science", "Data Science", "Computer Engineering", "Math", "Information Sciences & Technology", "Statistics"]
YEARS = ["Freshman", "Sophomore", "Junior", "Senior"]
GENDERS = ["Woman", "Man", "Non-binary", "Prefer not to say"]

# ---------------------------------------------------------------------------
# Real-data-calibrated population model (replaces the old hand-picked
# "5 hidden archetype templates" generator). Every synthetic student's 6-axis
# target is one draw from a population distribution whose means, spreads, and
# cross-axis correlations come from real published/measured data, not
# invented numbers - see docs/SYNTHETIC_DATA.md for the full derivation and
# the real datasets cited (MSLQ-CL validation study, IPIP Big Five).
#
# Two independent blocks (no real joint data links them - see
# docs/SYNTHETIC_DATA.md's "Known limitations"):
#
# Block 1 - planning/reliability/structure/intensity, calibrated from
# Fatima, Pallath & Hong (2025) "Validation of the MSLQ among clinical
# clerkship students in Malaysia," PLOS ONE (questionary_data/), N=349,
# Tables 3-4: real subscale means/SDs (rescaled from the paper's 7-point
# scale to our 5-point one) and real inter-subscale correlations.
#   planning     <- Metacognitive Self-Regulation
#   reliability  <- Effort Regulation
#   structure    <- Organisation
#   intensity    <- Self-Efficacy + Task Value (combined per their item split)
#
# Block 2 - session_mode/collaboration, calibrated from the IPIP Big Five
# Factor Markers dataset (openpsychometrics.org/_rawdata/BIG5.zip), N=19,718,
# already on a native 1-5 scale:
#   session_mode  <- Extraversion (proxy - no MSLQ or other real dataset
#                     measures "talks problems out loud / wants an agenda")
#   collaboration <- Agreeableness (proxy - closest real measure of
#                     group-helping orientation available)

REAL_AXIS_STATS = {
    # axis: (population mean, population SD, within-axis item-noise SD) - all on the 1-5 scale.
    "planning":      (3.533, 0.613, 0.683),
    "reliability":   (3.453, 0.700, 0.875),
    "structure":     (3.673, 0.653, 0.679),
    "intensity":     (3.764, 0.527, 0.500),
    "session_mode":  (3.011, 0.922, 0.982),
    "collaboration": (3.845, 0.715, 0.885),
}

# Real correlations within each block (Pearson, from the sources above);
# cross-block correlation is 0 - no real data links the two sources.
MSLQ_AXES = ["planning", "reliability", "structure", "intensity"]
MSLQ_CORR = np.array([
    # planning  reliability structure  intensity
    [1.000,     0.482,      0.679,     0.000],
    [0.482,     1.000,      0.421,     0.000],
    [0.679,     0.421,      1.000,     0.000],
    [0.000,     0.000,      0.000,     1.000],
])
BIG5_AXES = ["session_mode", "collaboration"]
BIG5_CORR = np.array([
    [1.000, 0.334],
    [0.334, 1.000],
])


def _cov_from_corr(axes, corr):
    sds = np.array([REAL_AXIS_STATS[a][1] for a in axes])
    return corr * np.outer(sds, sds)


_MSLQ_MEAN = np.array([REAL_AXIS_STATS[a][0] for a in MSLQ_AXES])
_MSLQ_COV = _cov_from_corr(MSLQ_AXES, MSLQ_CORR)
_BIG5_MEAN = np.array([REAL_AXIS_STATS[a][0] for a in BIG5_AXES])
_BIG5_COV = _cov_from_corr(BIG5_AXES, BIG5_CORR)


def sample_axis_targets():
    """One synthetic student's 6 'true' axis targets, drawn from the real-data-
    calibrated population distribution (not a discrete archetype template)."""
    mslq_draw = np.clip(np.random.multivariate_normal(_MSLQ_MEAN, _MSLQ_COV), 1.0, 5.0)
    big5_draw = np.clip(np.random.multivariate_normal(_BIG5_MEAN, _BIG5_COV), 1.0, 5.0)
    return dict(zip(MSLQ_AXES, mslq_draw)) | dict(zip(BIG5_AXES, big5_draw))

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PERIODS = ["Morning", "Afternoon", "Evening", "Night"]
LOCATIONS = ["Library", "Dorm/Apartment", "Study Lounge", "Coffee Shop", "Online"]
ONLINE_PREF = ["in_person", "online", "hybrid"]
DURATIONS = [60, 90, 120]
GRADES = ["A", "A-", "B+", "B"]

students, course_membership, personality_rows, survey_response_rows, availability_rows, academic_rows = [], [], [], [], [], []

sid_counter = 1


def clip_round(v):
    return int(round(min(5, max(1, v))))


def sample_survey_responses():
    """
    24 raw 1-5 Likert answers for one synthetic student. The 6-axis target is
    one draw from the real-data-calibrated population model above; each item
    is then drawn around its axis's target using that axis's own real
    item-noise SD (not one flat invented constant), and stored exactly as a
    real respondent's answer would be: reverse-worded items get the mirrored
    value, so score_axes() run on this raw data recovers (up to noise) the
    intended axis mean — same round-trip a real /api/survey submission goes
    through.
    """
    target = sample_axis_targets()
    responses = {}
    for item in SURVEY_ITEMS:
        _, _, item_noise_sd = REAL_AXIS_STATS[item["axis"]]
        intended = clip_round(np.random.normal(target[item["axis"]], item_noise_sd))
        responses[item["id"]] = reverse_code(intended) if item["reverse"] else intended
    return responses


def sample_availability(student_id, course_id, n_blocks, popular_slots):
    # Real students cluster around a handful of common windows (evenings after
    # class, weekend afternoons). Sample mostly from that shared "campus rhythm"
    # with small per-student jitter, plus an occasional idiosyncratic block, so
    # the resulting availability overlaps enough to actually form groups while
    # still leaving some students genuinely schedule-incompatible.
    k = min(n_blocks, len(popular_slots))
    chosen = random.sample(popular_slots, k=k)
    blocks = []
    for day, start_h, end_h in chosen:
        jitter_start = start_h + random.choice([-1, 0, 0, 0, 1])
        jitter_end = end_h + random.choice([-1, 0, 0, 0, 1])
        jitter_start = max(7, jitter_start)
        jitter_end = min(23, max(jitter_start + 1, jitter_end))
        blocks.append({"day": day, "start_time": f"{jitter_start:02d}:00", "end_time": f"{jitter_end:02d}:00"})
    if random.random() < 0.25:
        d = random.choice(DAYS)
        s = random.randint(8, 20)
        blocks.append({"day": d, "start_time": f"{s:02d}:00", "end_time": f"{min(23, s + 2):02d}:00"})
    period = "Evening" if any(int(b["start_time"][:2]) >= 17 for b in blocks) else "Afternoon"
    return {
        "student_id": student_id,
        "course_id": course_id,
        "blocks": blocks,
        "preferred_study_period": period,
        "preferred_session_duration": random.choice(DURATIONS),
        "preferred_sessions_per_week": random.randint(1, 3),
        "preferred_location": random.choice(LOCATIONS),
        "online_vs_in_person_preference": random.choice(ONLINE_PREF),
    }


def sample_academic(student_id, course_id):
    return {
        "student_id": student_id,
        "course_id": course_id,
        "course_confidence": random.randint(2, 5),
        "target_grade": random.choice(GRADES),
    }


def make_student(course, n_blocks_range, looking_for_group=True):
    global sid_counter
    sid = f"stu_{sid_counter:04d}"
    sid_counter += 1
    name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
    student = {
        "student_id": sid,
        "name": name,
        "year": random.choice(YEARS),
        "gender": random.choice(GENDERS),
        "major": random.choice(MAJORS),
        "course": course["course_code"],
        "course_section": course["section"],
        "looking_for_group": looking_for_group,
    }
    students.append(student)
    course_membership.append({
        "student_id": sid, "course_id": course["course_id"],
        "section": course["section"], "semester": course["semester"],
    })
    responses = sample_survey_responses()
    personality_rows.append({"student_id": sid, "course_id": course["course_id"], **score_axes(responses)})
    for item_id, val in responses.items():
        survey_response_rows.append({"student_id": sid, "course_id": course["course_id"], "item_number": item_id, "response": val})
    availability_rows.append(sample_availability(sid, course["course_id"], random.randint(*n_blocks_range), course["popular_slots"]))
    academic_rows.append(sample_academic(sid, course["course_id"]))
    return sid


cmpsc = courses[0]
math230 = courses[1]

# 27 = 3x5 + 3x4 and 9 = 5 + 4: both split exactly into groups of 4-5, and
# each leaves some 4-person groups with an open seat - the live intake
# demo's starting point (a new signup joins the best-fitting one; see
# ../algorithm/placement.py).
cmpsc_students = [make_student(cmpsc, (3, 4)) for _ in range(27)]
math_students = [make_student(math230, (2, 4)) for _ in range(9)]

# ---------------------------------------------------------------------------
# 3. Study types — the 4 fixed theory types (algorithm/clustering.py), with
#    membership from a Gaussian mixture over the 2 family scores, anchored
#    at the theory centers (theory model as-is below clustering.MIN_FIT_N
#    students). Plus a response-quality flag.
#    DISPLAY LAYER ONLY: nothing below section 3 reads archetype_id/strength.
# ---------------------------------------------------------------------------

type_model = fit_model(np.array([family_scores(row) for row in personality_rows], dtype=float))

responses_by_id = {}
for r in survey_response_rows:
    responses_by_id.setdefault(r["student_id"], {})[r["item_number"]] = r["response"]

name_by_id = {tid: name for tid, name, *_ in TYPES}
for row in personality_rows:
    result = classify(row, type_model)
    row["archetype_id"] = result["archetype_id"]
    row["archetype"] = name_by_id[result["archetype_id"]]
    row["archetype_strength"] = result["strength"]
    row["response_flag"] = response_flag(responses_by_id[row["student_id"]], atypical=result["atypical"])
    # a lightweight self-reported role preference, correlated with traits but distinct from archetype
    top_role = preferred_role_for(row)
    row["preferred_role"] = top_role if random.random() > 0.15 else "Flexible/No Preference"

archetypes = []
for c in type_model["components"]:
    members = [r for r in personality_rows if r["archetype_id"] == c["archetype_id"]]
    archetypes.append({
        "archetype_id": c["archetype_id"],
        "name": c["name"],
        "description": c["description"],
        "member_count": len(members),
        # descriptive: members' average per axis (the model itself is 2-D, below)
        "centroid_traits_1to5": {t: (round(mean(r[t] for r in members), 2) if members else None) for t in TRAITS},
        "weight": round(c["weight"], 6),
        "component": {"mean": [round(v, 6) for v in c["mean"]],
                      "covariance": [[round(v, 6) for v in row] for row in c["covariance"]]},
    })
archetype_model_meta = {k: type_model[k] for k in ("source", "n_fit", "covariance_type", "loglik_threshold", "note")}

# ---------------------------------------------------------------------------
# 4. Availability overlap + compatibility helpers — see ../algorithm/compatibility.py
# ---------------------------------------------------------------------------

personality_by_id = {r["student_id"]: r for r in personality_rows}
availability_by_id = {r["student_id"]: r for r in availability_rows}

# ---------------------------------------------------------------------------
# 5. Pairwise compatibility matrix (within-course only — Stage 1 filter)
#
# schedule_compatible / weekly_overlap_minutes are still computed and stored
# per pair (valid input data), but no longer exclude a pair from matching —
# see pair_score() just below.
# ---------------------------------------------------------------------------

pairwise = []
for course_students in (cmpsc_students, math_students):
    for i in range(len(course_students)):
        for j in range(i + 1, len(course_students)):
            a, b = course_students[i], course_students[j]
            score, overlap, breakdown = pair_compatibility(
                personality_by_id[a], personality_by_id[b],
                availability_by_id[a], availability_by_id[b],
            )
            pairwise.append({
                "student_a": a, "student_b": b,
                "schedule_compatible": overlap > 0,
                "weekly_overlap_minutes": overlap,
                "compatibility_score": score,
                "breakdown": breakdown,
            })

pair_score_lookup = {}
for p in pairwise:
    pair_score_lookup[(p["student_a"], p["student_b"])] = p
    pair_score_lookup[(p["student_b"], p["student_a"])] = p


def pair_score(a, b):
    # No schedule gate — time no longer factors into matching (still recorded
    # per pair in schedule_compatible / weekly_overlap_minutes above, just unused here).
    return pair_score_lookup[(a, b)]["compatibility_score"]


# ---------------------------------------------------------------------------
# 6. Group formation — ILP (algorithm/grouping.py), per course, groups of 4-5
#    maximizing total within-group compatibility (step 4b: raw vectors only).
# ---------------------------------------------------------------------------

def group_pair_scores(members):
    # No pair is ever excluded anymore (pair_score has no schedule gate), so
    # this just collects every within-group pairwise similarity score.
    scores = []
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            scores.append(pair_score(members[i], members[j]))
    return scores


def group_score(members):
    """
    group_score = average pairwise similarity across the group. No
    diversity/"balance" reward — that was a differences-based signal (spread
    across leadership/talkativeness/assertiveness/helpfulness) and we only
    want similarity now, same as the pairwise formula above.
    """
    scores = group_pair_scores(members)
    avg = mean(scores)
    worst = min(scores)
    return {"group_score": round(avg, 1), "avg_pairwise": round(avg, 1), "worst_pairwise": round(worst, 1)}


def form_groups(course_students, target_looking_ids):
    """
    ILP partition of the course's looking-for-group students into groups of
    4-5 (see algorithm/grouping.py). Anyone the ILP can't place (only when the
    headcount doesn't split into 4s and 5s) is left unassigned and gets
    recommendations below, same as a live signup that finds no room.
    """
    pool = sorted(s for s in course_students if s in target_looking_ids)
    groups, leftover, info = ilp_form_groups(pool, pair_score)
    ilp_info.append((len(pool), groups, info))
    return groups, leftover


ilp_info = []  # (pool size, groups, solver info) per course, for the summary print

# Everyone looks for a group in this batch.
cmpsc_groups, cmpsc_unassigned = form_groups(cmpsc_students, set(cmpsc_students))
math_groups, math_unassigned = form_groups(math_students, set(math_students))

all_unassigned = cmpsc_unassigned | math_unassigned

# ---------------------------------------------------------------------------
# 7. Groups / group_membership output
# ---------------------------------------------------------------------------

groups_out, group_membership_out, match_data_out = [], [], []
group_counter = 1
match_counter = 1


def role_for_member(member_id, group_members):
    row = personality_by_id[member_id]
    ranks = sorted(group_members, key=lambda m: (-personality_by_id[m]["reliability"], m))
    if member_id == ranks[0] and row["reliability"] >= 4:
        return "Organizer"
    if row["collaboration"] >= 4:
        return "Explainer"
    if row["intensity"] >= 4:
        return "Problem Solver"
    if row["session_mode"] <= 2:
        return "Listener"
    return "Flexible/No Preference"


def emit_groups(course, groups):
    global group_counter, match_counter
    for n, g in enumerate(groups, start=1):
        gscore = group_score(g)
        gid = f"grp_{group_counter:03d}"
        group_counter += 1
        name = f"{course['course_code']} Group {n}"  # same scheme as algorithm/placement.group_name_for()
        groups_out.append({
            "group_id": gid,
            "course_id": course["course_id"],
            "group_name": name,
            "max_members": 5,
            "current_members": len(g),
            "created_at": "2026-08-25T14:00:00Z",
            **gscore,
        })
        for m in g:
            group_membership_out.append({
                "group_id": gid, "student_id": m,
                "joined_at": "2026-08-25T14:00:00Z",
                "group_role": role_for_member(m, g),
            })
        # a match_data record per member documenting the recommendation that formed the group
        for m in g:
            match_data_out.append({
                "match_id": f"match_{match_counter:04d}",
                "student_id": m,
                "recommended_group_id": gid,
                "compatibility_score": round(mean([pair_score(m, o) for o in g if o != m]), 1),
                "accepted": True,
                "rejected": False,
                "timestamp": "2026-08-25T13:55:00Z",
            })
            match_counter += 1


emit_groups(cmpsc, cmpsc_groups)
emit_groups(math230, math_groups)

# students still looking for a group get "recruit me" style recommendations:
# the up-to-3 under-capacity groups in their course where their mean
# compatibility with the members is highest (individual -> group matching, section 14)
for sid in sorted(all_unassigned):
    course = cmpsc if sid in cmpsc_students else math230
    candidate_groups = [g for g in groups_out if g["course_id"] == course["course_id"]]
    eligible = []
    for g in candidate_groups:
        members = [m["student_id"] for m in group_membership_out if m["group_id"] == g["group_id"]]
        if len(members) < 5:
            eligible.append((round(mean([pair_score(sid, o) for o in members]), 1), g["group_id"]))
    for score, gid in sorted(eligible, key=lambda e: (-e[0], e[1]))[:3]:
        match_data_out.append({
            "match_id": f"match_{match_counter:04d}",
            "student_id": sid,
            "recommended_group_id": gid,
            "compatibility_score": score,
            "accepted": False,
            "rejected": False,
            "timestamp": "2026-09-05T10:00:00Z",
        })
        match_counter += 1

# ---------------------------------------------------------------------------
# 8. Course global chat (lightweight sample activity)
# ---------------------------------------------------------------------------

CHAT_TEMPLATES = [
    ("question", "Anyone understand how {topic} works for problem set 3? I'm stuck on part b."),
    ("answer", "For {topic}, the trick is to draw it out first — happy to hop on a call if that helps."),
    ("question", "Is the {topic} section going to be on the midterm?"),
    ("answer", "Yeah professor mentioned {topic} is fair game, review the slides from week 4."),
    ("social", "Anyone want to form a group for the final project? Still looking!"),
    ("social", "{course} Group 1 is holding an open review session Thursday 7pm in the library if anyone wants to join."),
]

chat_messages = []
msg_id = 1
for course in courses:
    course_all_students = cmpsc_students if course is cmpsc else math_students
    for _ in range(40 if course is cmpsc else 15):
        sender = random.choice(course_all_students)
        kind, template = random.choice(CHAT_TEMPLATES)
        topic = random.choice(course["topic_pool"])
        chat_messages.append({
            "message_id": f"msg_{msg_id:04d}",
            "course_id": course["course_id"],
            "student_id": sender,
            "type": kind,
            "text": template.format(topic=topic, course=course["course_code"]),
            "upvotes": random.randint(0, 12) if kind == "answer" else random.randint(0, 4),
            "timestamp": f"2026-09-{random.randint(1, 8):02d}T{random.randint(9, 23):02d}:{random.randint(0, 59):02d}:00Z",
        })
        msg_id += 1

# ---------------------------------------------------------------------------
# 9. Group feedback (outcome data — section 16)
# ---------------------------------------------------------------------------

feedback_rows = []
for g in groups_out:
    members = [m["student_id"] for m in group_membership_out if m["group_id"] == g["group_id"]]
    # groups with higher group_score tend to produce better outcomes, plus noise —
    # this is what lets a future model recover "does our heuristic actually predict success?"
    base_satisfaction = 2.0 + 3.0 * (g["group_score"] / 100)
    for m in members:
        satisfaction = clip_round(np.random.normal(base_satisfaction, 0.7))
        left = random.random() < max(0, (65 - g["group_score"]) / 300)
        feedback_rows.append({
            "group_id": g["group_id"],
            "student_id": m,
            "satisfaction_score": satisfaction,
            "meetings_attended": random.randint(2, 8) if not left else random.randint(0, 2),
            "meetings_per_week": random.choice([1, 2]),
            "weeks_in_group": 2,
            "left_group": left,
            "would_match_again": satisfaction >= 4 and not left,
            "perceived_personality_fit": clip_round(np.random.normal(base_satisfaction, 0.8)),
            "group_productivity": clip_round(np.random.normal(base_satisfaction, 0.8)),
            "group_chat_activity": random.choice(["low", "medium", "high"]),
            "peer_helpfulness_rating": clip_round(np.random.normal(base_satisfaction, 0.9)),
            "peer_reliability_rating": clip_round(np.random.normal(base_satisfaction, 0.9)),
            "timestamp": "2026-09-08T09:00:00Z",
        })

# ---------------------------------------------------------------------------
# 10. Write output
# ---------------------------------------------------------------------------

def dump(name, obj):
    with open(OUT / name, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


dump("university.json", university)
dump("courses.json", [{k: v for k, v in c.items()} for c in courses])
dump("students.json", students)
dump("course_membership.json", course_membership)
dump("personality_profiles.json", personality_rows)
dump("survey_responses.json", survey_response_rows)
dump("archetypes.json", archetypes)
dump("archetype_model.json", archetype_model_meta)
dump("availability.json", availability_rows)
dump("academic_profiles.json", academic_rows)
dump("pairwise_compatibility.json", pairwise)
dump("groups.json", groups_out)
dump("group_membership.json", group_membership_out)
dump("match_data.json", match_data_out)
dump("course_chat_messages.json", chat_messages)
dump("group_feedback.json", feedback_rows)

print(f"Students: {len(students)} (CMPSC465={len(cmpsc_students)}, MATH230={len(math_students)})")
print(f"Study types (model: {type_model['source']}"
      f"{', ' + type_model['note'] if type_model['note'] else ''}): "
      f"{[(a['name'], a['member_count']) for a in archetypes]}")
print(f"Response flags: {[(r['student_id'], r['response_flag']) for r in personality_rows if r['response_flag']] or 'none'}")
for n_pool, groups, info in ilp_info:
    if not groups:
        continue
    ilp_total = total_score(groups, pair_score)
    rand_total = random_baseline(groups, pair_score)
    n_pairs = sum(len(g) * (len(g) - 1) // 2 for g in groups)
    print(f"  ILP n={n_pool}: {info['status']}, total={ilp_total:.1f} (bound {info['bound']}), "
          f"avg pair {ilp_total / n_pairs:.1f} vs random {rand_total / n_pairs:.1f}")
print(f"Groups formed: {len(groups_out)}")
for g in groups_out:
    mem = [m['student_id'] for m in group_membership_out if m['group_id'] == g['group_id']]
    print(f"  {g['group_id']} ({g['course_id'].split('-')[1]}) '{g['group_name']}' n={len(mem)} score={g['group_score']}")
print(f"Still looking for group: {len(all_unassigned)}")
print(f"Pairwise records: {len(pairwise)}")
print(f"Chat messages: {len(chat_messages)}")
print(f"Feedback rows: {len(feedback_rows)}")
