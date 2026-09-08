"""
StudyMatch — sample data generator.

Produces synthetic-but-internally-consistent data for the StudyMatch spec:
students, personality survey results, availability, academic profiles,
derived archetypes (via real KMeans clustering, not hand-labeled), a
pairwise personality-compatibility matrix, greedily-formed 4-5 person
study groups, group membership, individual/group match recommendations,
course global-chat activity, and post-formation outcome feedback.

This is sample/demo data only. The scoring formulas below are the
heuristic placeholders described in the spec (section 11/12) — weights
are explicitly temporary and meant to be replaced by learned weights
once real outcome feedback (group_feedback) accumulates.

Matching scope (current decision): compatibility is personality-similarity
ONLY. Availability/schedule data and academic strong/weak-topic data are
still generated and stored (nothing here is deleted), but neither factors
into compatibility_score or group_score anymore — see similarity_component()
and pair_compatibility() below. There's also no "reward differences"
complementarity term: a good pair is simply a similar one, across the full
14-trait personality vector.

Run:  python generate_sample_data.py
Output: ./sample/*.json

Shared matching math (similarity_component, pair_compatibility, etc.) lives in
matching_lib.py so add_student.py's incremental path uses the exact same
formulas — see that module's docstring.
"""

import json
import random
from pathlib import Path
from statistics import mean

import numpy as np
from sklearn.cluster import KMeans

from matching_lib import (
    TRAITS, weekly_overlap_minutes, pair_compatibility, preferred_role_for,
)

random.seed(42)
np.random.seed(42)

OUT = Path(__file__).parent / "sample"
OUT.mkdir(exist_ok=True)

# Matching uses the full personality vector as one similarity signal — no
# similarity/complementarity trait split anymore (see matching_lib.similarity_component()).
# COMPLEMENT_TRAITS survives only as the set role_for_member() reads to assign
# a group_role label further down; it no longer feeds any score.
COMPLEMENT_TRAITS = ["leadership", "talkativeness", "assertiveness", "helpfulness"]

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
SUBPOPULATIONS = {
    "planner": dict(zip(TRAITS, [4.5, 4.5, 4.0, 2.0, 2.5, 3.0, 4.5, 3.0, 2.0, 2.5, 3.0, 3.0, 2.5, 3.5])),
    "connector": dict(zip(TRAITS, [3.5, 3.0, 3.0, 4.5, 4.5, 2.0, 3.0, 3.5, 4.5, 3.0, 4.5, 4.5, 3.0, 4.5])),
    "captain": dict(zip(TRAITS, [4.0, 4.0, 4.0, 3.0, 3.5, 4.5, 3.5, 4.5, 3.5, 4.5, 3.0, 3.5, 4.0, 2.5])),
    "loner": dict(zip(TRAITS, [3.5, 2.0, 2.0, 1.5, 1.5, 2.5, 2.5, 1.5, 1.5, 2.0, 2.5, 1.5, 3.5, 3.0])),
    "sprinter": dict(zip(TRAITS, [2.5, 1.5, 2.0, 3.5, 3.0, 2.0, 1.5, 2.0, 3.5, 2.5, 3.0, 3.0, 4.5, 3.0])),
}
SUBPOP_NOISE_SD = 0.65

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PERIODS = ["Morning", "Afternoon", "Evening", "Night"]
LOCATIONS = ["Library", "Dorm/Apartment", "Study Lounge", "Coffee Shop", "Online"]
ONLINE_PREF = ["in_person", "online", "hybrid"]
DURATIONS = [60, 90, 120]
GRADES = ["A", "A-", "B+", "B"]

students, course_membership, personality_rows, availability_rows, academic_rows = [], [], [], [], []

sid_counter = 1


def clip_round(v):
    return int(round(min(5, max(1, v))))


def sample_personality(subpop):
    base = SUBPOPULATIONS[subpop]
    return {t: clip_round(np.random.normal(base[t], SUBPOP_NOISE_SD)) for t in TRAITS}


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


def sample_academic(student_id, course_id, topic_pool):
    pool = topic_pool[:]
    random.shuffle(pool)
    strong = pool[:2]
    weak = pool[2:4]
    return {
        "student_id": student_id,
        "course_id": course_id,
        "strong_topics": strong,
        "weak_topics": weak,
        "can_help_with": strong,
        "needs_help_with": weak,
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
    personality_rows.append({"student_id": sid, "course_id": course["course_id"], **sample_personality(subpop)})
    availability_rows.append(sample_availability(sid, course["course_id"], random.randint(*n_blocks_range), course["popular_slots"]))
    academic_rows.append(sample_academic(sid, course["course_id"], course["topic_pool"]))
    return sid


cmpsc = courses[0]
math230 = courses[1]

cmpsc_students = [make_student(cmpsc, (3, 4)) for _ in range(28)]
math_students = [make_student(math230, (2, 4)) for _ in range(9)]

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
    (lambda c: c["preparation"] > 0.5 and c["structure"] > 0.5 and c["talkativeness"] < 0, "Focused Architect",
     "Highly prepared, structure-loving, and quiet — thrives on a clear plan executed early."),
    (lambda c: c["helpfulness"] > 0.5 and c["collaboration"] > 0.5 and c["social_preference"] > 0.3, "Collaborative Guide",
     "Energized by teaching others and solving problems together; keeps the group warm."),
    (lambda c: c["leadership"] > 0.5 and c["assertiveness"] > 0.5 and c["competitiveness"] > 0.3, "Study Captain",
     "Takes charge, sets the pace, and pushes the group toward results."),
    (lambda c: c["talkativeness"] < -0.3 and c["social_preference"] < -0.3 and c["collaboration"] < -0.3, "Independent Strategist",
     "Prefers working things out solo, even inside a group; contributes best async."),
    (lambda c: c["study_pace"] > 0.5 and c["preparation"] < -0.3 and c["structure"] < -0.3, "Deadline Sprinter",
     "Ramps up fast close to deadlines; spontaneous over scheduled."),
    (lambda c: c["social_preference"] > 0.3 and c["talkativeness"] > 0.3, "Social Solver",
     "Blends academic focus with social energy; makes study sessions feel easy."),
]
FALLBACK_NAMES = ["Steady Contributor", "Balanced Collaborator", "Quiet Achiever"]

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
# 4. Availability overlap + compatibility helpers — see matching_lib.py
# ---------------------------------------------------------------------------

personality_by_id = {r["student_id"]: r for r in personality_rows}
availability_by_id = {r["student_id"]: r for r in availability_rows}
academic_by_id = {r["student_id"]: r for r in academic_rows}

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
                academic_by_id[a], academic_by_id[b],
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
# 6. Group formation (greedy growth + 1 pass of local-search swaps)
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
    pool = [s for s in course_students if s in target_looking_ids]
    unassigned = set(pool)
    formed = []
    while len(unassigned) >= 4:
        # seed with the best compatible pair remaining
        best_pair, best_val = None, -1
        rem = sorted(unassigned)  # sorted, not list(set(...)) — set order depends on the interpreter's per-process hash seed
        for i in range(len(rem)):
            for j in range(i + 1, len(rem)):
                s = pair_score(rem[i], rem[j])
                if s > best_val:
                    best_val, best_pair = s, (rem[i], rem[j])
        if best_pair is None:
            break
        group = list(best_pair)
        unassigned -= set(group)
        while len(group) < 5 and unassigned:
            best_c, best_avg = None, -1
            for cand in sorted(unassigned):
                avg = mean(group_pair_scores(group + [cand]))
                if avg > best_avg:
                    best_avg, best_c = avg, cand
            if best_c is None:
                break
            group.append(best_c)
            unassigned.remove(best_c)
            if len(group) >= 4 and len(unassigned) < 4 and len(group) < 5:
                continue  # keep trying to reach 5 if possible
        if len(group) >= 4:
            formed.append(group)
        else:
            unassigned |= set(group)
            break
    return formed, unassigned


def local_search_swap(groups, rounds=25):
    improved = True
    r = 0
    while improved and r < rounds:
        improved = False
        r += 1
        for gi in range(len(groups)):
            for gj in range(gi + 1, len(groups)):
                for mi in range(len(groups[gi])):
                    for mj in range(len(groups[gj])):
                        a, b = groups[gi][mi], groups[gj][mj]
                        base_i = group_score(groups[gi])["group_score"]
                        base_j = group_score(groups[gj])["group_score"]
                        trial_i = groups[gi][:mi] + [b] + groups[gi][mi + 1:]
                        trial_j = groups[gj][:mj] + [a] + groups[gj][mj + 1:]
                        si, sj = group_score(trial_i), group_score(trial_j)
                        if si["group_score"] + sj["group_score"] > base_i + base_j + 0.5:
                            groups[gi], groups[gj] = trial_i, trial_j
                            improved = True
    return groups


cmpsc_looking = set(cmpsc_students[:24])  # leaves 4th/5th-seat vacancies for the recruiting demo
math_looking = set(math_students[:4])     # one under-capacity group of 4, open to recruiting

cmpsc_groups, cmpsc_unassigned = form_groups(cmpsc_students, cmpsc_looking)
math_groups, math_unassigned = form_groups(math_students, math_looking)
cmpsc_groups = local_search_swap(cmpsc_groups)
math_groups = local_search_swap(math_groups)

all_unassigned = cmpsc_unassigned | math_unassigned | (set(cmpsc_students) - cmpsc_looking) | (set(math_students) - math_looking)

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
    lead = personality_by_id[member_id]["leadership"]
    ranks = sorted(group_members, key=lambda m: (-personality_by_id[m]["leadership"], m))
    if member_id == ranks[0] and lead >= 4:
        return "Organizer"
    help_ = personality_by_id[member_id]["helpfulness"]
    if help_ >= 4:
        return "Explainer"
    if personality_by_id[member_id]["collaboration"] >= 4:
        return "Problem Solver"
    if personality_by_id[member_id]["talkativeness"] <= 2:
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
# into the existing groups they'd fit best (individual -> group matching, section 14)
for sid in sorted(all_unassigned):
    course = cmpsc if sid in cmpsc_students else math230
    candidate_groups = [g for g in groups_out if g["course_id"] == course["course_id"]]
    ranked = []
    for g in candidate_groups:
        members = [m["student_id"] for m in group_membership_out if m["group_id"] == g["group_id"]]
        if len(members) >= 5:
            continue
        avg = mean([pair_score(sid, o) for o in members])
        if avg > 0:
            ranked.append((g["group_id"], round(avg, 1)))
    ranked.sort(key=lambda x: -x[1])
    for gid, score in ranked[:3]:
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
