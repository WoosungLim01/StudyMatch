"""
StudyMatch — sample data generator.

Produces synthetic-but-internally-consistent data for the StudyMatch spec:
students, personality survey results, availability, academic profiles,
derived archetypes (via real KMeans clustering, not hand-labeled), a
pairwise compatibility matrix, randomly-formed 5-person study groups, group
membership, individual/group match recommendations, course global-chat
activity, and post-formation outcome feedback.

This is sample/demo data only.

PLACEHOLDER NOTICE: group formation and compatibility_score are RANDOM right
now, not a real matching algorithm — see algorithm/compatibility.py's and
algorithm/placement.py's docstrings, and docs/Woosung.md for the handoff.
The personality survey pipeline below (24-item Likert -> 6 axis scores) is
real and final; only the matching/grouping step that consumes it is a
placeholder.

Personality survey: each synthetic student gets 24 raw Likert answers (the
same "Version 3" instrument real respondents see in ui/survey.html — item
bank + reverse-coding in ../algorithm/scoring.py), not hand-picked axis
values directly. Raw answers are generated per-item around a hidden
subpopulation's target axis value, then scored with the exact same
score_axes() the live /api/survey endpoint uses, so synthetic and real
students go through an identical pipeline.

Academic profiles now carry only course_confidence/target_grade —
per-topic strong/weak/can_help/needs_help tracking (and the shared `topic`
table it needed) was removed; see README.md.

Run (from this directory):  python generate_sample_data.py
Output: ./sample/*.json

Shared matching math (similarity_component, pair_compatibility, etc.) lives in
../algorithm/compatibility.py so add_student.py's and app.py's incremental
paths use the exact same formulas — see that module's docstring.
"""

import json
import random
import sys
from pathlib import Path
from statistics import mean

import numpy as np
from sklearn.cluster import KMeans

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for `algorithm`
from algorithm.compatibility import TRAITS, pair_compatibility, preferred_role_for
from algorithm.scoring import SURVEY_ITEMS, reverse_code, score_axes

random.seed(42)
np.random.seed(42)

OUT = Path(__file__).parent / "sample"
OUT.mkdir(exist_ok=True)

# Matching uses the full personality vector as one similarity signal — no
# similarity/complementarity trait split anymore (see algorithm/compatibility.similarity_component()).

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

# Hidden generative subpopulations used ONLY to make synthetic survey
# answers internally consistent (correlated), the way real students'
# answers would be. These are NOT exposed anywhere in the output — the
# archetypes in archetypes.json are discovered later by clustering the
# resulting personality_profiles, exactly as section 7 describes.
#
# Target values are per AXIS (not per raw item) - sample_survey_responses()
# below turns each into 4 noisy raw Likert answers per axis, reverse-encoding
# the (R) items exactly like a real respondent's answer would be stored.
#
# These axis-value templates are hand-picked, not derived from or validated
# against any published personality distribution - see ../docs/DATA_GROUNDING.md
# for what real research does and doesn't back in this design (the survey
# ITEMS themselves are now MSLQ-grounded; these hidden subpop targets are not).
SUBPOPULATIONS = {
    "planner":   dict(zip(TRAITS, [4.5, 2.5, 4.0, 4.5, 3.5, 2.5])),
    "connector": dict(zip(TRAITS, [3.0, 4.5, 3.0, 2.5, 3.5, 4.5])),
    "captain":   dict(zip(TRAITS, [4.0, 3.5, 4.5, 4.0, 4.5, 3.5])),
    "loner":     dict(zip(TRAITS, [3.0, 1.5, 3.0, 2.5, 3.0, 1.5])),
    "sprinter":  dict(zip(TRAITS, [1.5, 3.0, 2.5, 1.5, 4.0, 3.0])),
}
SUBPOP_NOISE_SD = 0.65

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


def sample_survey_responses(subpop):
    """
    24 raw 1-5 Likert answers for one synthetic student. Each item is drawn
    centered on its axis's target value for this subpopulation, then stored
    exactly as a real respondent's answer would be: reverse-worded items get
    the mirrored value, so score_axes() run on this raw data recovers (up to
    noise) the intended axis mean — same round-trip a real /api/survey
    submission goes through.
    """
    target = SUBPOPULATIONS[subpop]
    responses = {}
    for item in SURVEY_ITEMS:
        intended = clip_round(np.random.normal(target[item["axis"]], SUBPOP_NOISE_SD))
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
    subpop = random.choice(list(SUBPOPULATIONS.keys()))
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
    responses = sample_survey_responses(subpop)
    personality_rows.append({"student_id": sid, "course_id": course["course_id"], **score_axes(responses)})
    for item_id, val in responses.items():
        survey_response_rows.append({"student_id": sid, "course_id": course["course_id"], "item_number": item_id, "response": val})
    availability_rows.append(sample_availability(sid, course["course_id"], random.randint(*n_blocks_range), course["popular_slots"]))
    academic_rows.append(sample_academic(sid, course["course_id"]))
    return sid


cmpsc = courses[0]
math230 = courses[1]

# Population sizes are deliberately (multiple of 5) + 2 per course, so batch
# group formation (exactly-5 groups, see form_groups()) leaves exactly 2
# people unassigned per course — the live intake demo's starting point.
cmpsc_students = [make_student(cmpsc, (3, 4)) for _ in range(27)]
math_students = [make_student(math230, (2, 4)) for _ in range(7)]

# ---------------------------------------------------------------------------
# 3. Archetypes — discovered via KMeans over the real personality vectors
# ---------------------------------------------------------------------------

vecs = np.array([[row[t] for t in TRAITS] for row in personality_rows], dtype=float)
mu, sigma = vecs.mean(axis=0), vecs.std(axis=0)
sigma[sigma == 0] = 1.0
X = (vecs - mu) / sigma

K = 5
km = KMeans(n_clusters=K, n_init=10, random_state=42).fit(X)
labels = km.labels_

# Name each cluster from its centroid's most distinctive high/low traits
# (z-scored relative to the whole population), picking from a curated,
# game-like name bank keyed by trait signature rather than assigning
# MBTI-style labels by hand.
NAME_BANK = [
    (lambda c: c["planning"] > 0.5 and c["structure"] > 0.5 and c["session_mode"] < 0, "Focused Architect",
     "Plans ahead and keeps things organized, but prefers working things out quietly over talking them through."),
    (lambda c: c["collaboration"] > 0.5 and c["session_mode"] > 0.5, "Collaborative Guide",
     "Learns by explaining and talking problems through out loud; keeps the group engaged."),
    (lambda c: c["reliability"] > 0.5 and c["intensity"] > 0.5 and c["structure"] > 0.3, "Study Captain",
     "Shows up prepared, pushes through hard material, and keeps sessions on track."),
    (lambda c: c["session_mode"] < -0.3 and c["collaboration"] < -0.3, "Independent Strategist",
     "Prefers working things out solo, even inside a group; contributes best async."),
    (lambda c: c["intensity"] > 0.3 and c["planning"] < -0.3 and c["structure"] < -0.3, "Deadline Sprinter",
     "Cares about doing well but ramps up close to deadlines rather than planning ahead."),
    (lambda c: c["reliability"] > 0.3 and c["collaboration"] > 0.3, "Steady Teammate",
     "Dependable and easy to work with; reliably follows through on commitments to the group."),
]
FALLBACK_NAMES = ["Balanced Collaborator", "Quiet Achiever", "Adaptive Studier"]

archetypes = []
used_names = set()
centroids_raw = km.cluster_centers_ * sigma + mu  # back to 1-5 scale
for k in range(K):
    c = {t: km.cluster_centers_[k][i] for i, t in enumerate(TRAITS)}  # z-scored centroid
    chosen = None
    for rule, name, desc in NAME_BANK:
        if name in used_names:
            continue
        if rule(c):
            chosen = (name, desc)
            break
    if chosen is None:
        for fb in FALLBACK_NAMES:
            if fb not in used_names:
                chosen = (fb, "A moderate, well-rounded study profile without an extreme trait signature.")
                break
    used_names.add(chosen[0])
    size = int((labels == k).sum())
    archetypes.append({
        "archetype_id": f"arch_{k}",
        "name": chosen[0],
        "description": chosen[1],
        "member_count": size,
        "centroid_traits_1to5": {t: round(float(centroids_raw[k][i]), 2) for i, t in enumerate(TRAITS)},
    })

label_to_archetype = {k: archetypes[k]["archetype_id"] for k in range(K)}
label_to_name = {k: archetypes[k]["name"] for k in range(K)}
for row, lab in zip(personality_rows, labels):
    row["archetype"] = label_to_name[lab]
    row["archetype_id"] = label_to_archetype[lab]
    # a lightweight self-reported role preference, correlated with traits but distinct from archetype
    top_role = preferred_role_for(row)
    row["preferred_role"] = top_role if random.random() > 0.15 else "Flexible/No Preference"

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
# 6. Group formation — PLACEHOLDER: pure random shuffle-and-chunk.
#
# The real matching algorithm (using the 6-axis personality data collected by
# the survey) is being built separately (Woosung — see docs/Woosung.md).
# pair_score() below still returns a number (algorithm/compatibility.py's
# pair_compatibility() is currently random too), kept only so
# pairwise_compatibility / group_score / match_data have something in them —
# it does NOT drive who ends up in which group.
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
    PLACEHOLDER: pure random shuffle-and-chunk into exactly-5 groups. Any
    remainder (<5) is left in `unassigned` on purpose: population sizes are
    chosen (see below) so each course ends batch generation with exactly 2
    people left over, matching the live intake policy in
    ../algorithm/placement.py (a 1-2 remainder joins an existing group; a 3-4
    remainder becomes its own smaller group) — those 2 are what a real survey
    respondent completes into a group.
    """
    pool = sorted(s for s in course_students if s in target_looking_ids)
    random.shuffle(pool)
    formed = []
    while len(pool) >= 5:
        formed.append(pool[:5])
        pool = pool[5:]
    return formed, set(pool)


# Everyone looks for a group in this batch — the old "leave a few students not
# looking" mechanic is superseded by the exactly-2-unassigned remainder above.
cmpsc_groups, cmpsc_unassigned = form_groups(cmpsc_students, set(cmpsc_students))
math_groups, math_unassigned = form_groups(math_students, set(math_students))

all_unassigned = cmpsc_unassigned | math_unassigned

# ---------------------------------------------------------------------------
# 7. Groups / group_membership output
# ---------------------------------------------------------------------------

GROUP_NAME_POOL = ["The Recursion Rangers", "Big-O Bandits", "Proof Squad", "Late Night Loopers",
                   "Vector Vanguard", "Integral Insurgents", "The Greedy Algorithm", "Tree Traversers",
                   "Study Captains United", "Async Study Crew"]

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
    for g in groups:
        gscore = group_score(g)
        gid = f"grp_{group_counter:03d}"
        group_counter += 1
        name = random.choice(GROUP_NAME_POOL)
        GROUP_NAME_POOL.remove(name)
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

# students still looking for a group get "recruit me" style recommendations
# into existing under-capacity groups — PLACEHOLDER: a random sample of up to
# 3 eligible groups, not ranked by fit (individual -> group matching, section 14)
for sid in sorted(all_unassigned):
    course = cmpsc if sid in cmpsc_students else math230
    candidate_groups = [g for g in groups_out if g["course_id"] == course["course_id"]]
    eligible = []
    for g in candidate_groups:
        members = [m["student_id"] for m in group_membership_out if m["group_id"] == g["group_id"]]
        if len(members) < 5:
            eligible.append((g["group_id"], members))
    picks = random.sample(eligible, k=min(3, len(eligible)))
    for gid, members in picks:
        score = round(mean([pair_score(sid, o) for o in members]), 1)
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
    ("social", "Study Captains United is holding an open review session Thursday 7pm in the library if anyone wants to join."),
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
            "text": template.format(topic=topic),
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
dump("availability.json", availability_rows)
dump("academic_profiles.json", academic_rows)
dump("pairwise_compatibility.json", pairwise)
dump("groups.json", groups_out)
dump("group_membership.json", group_membership_out)
dump("match_data.json", match_data_out)
dump("course_chat_messages.json", chat_messages)
dump("group_feedback.json", feedback_rows)

print(f"Students: {len(students)} (CMPSC465={len(cmpsc_students)}, MATH230={len(math_students)})")
print(f"Archetypes discovered: {[a['name'] for a in archetypes]}")
print(f"Groups formed: {len(groups_out)}")
for g in groups_out:
    mem = [m['student_id'] for m in group_membership_out if m['group_id'] == g['group_id']]
    print(f"  {g['group_id']} ({g['course_id'].split('-')[1]}) '{g['group_name']}' n={len(mem)} score={g['group_score']}")
print(f"Still looking for group: {len(all_unassigned)}")
print(f"Pairwise records: {len(pairwise)}")
print(f"Chat messages: {len(chat_messages)}")
print(f"Feedback rows: {len(feedback_rows)}")
