"""
StudyMatch — live group-placement policy for incoming survey respondents.

PLACEHOLDER NOTICE: group formation here is RANDOM, not a real matching
algorithm - see algorithm/compatibility.py's docstring and docs/Woosung.md.
_form_full_groups() just shuffles and chunks; the 1-2 remainder case joins a
RANDOMLY chosen eligible group rather than the best-scoring one. This is
deliberate so the whole pipeline (schema, live placement, the post-signup
message) works end to end while the real algorithm is built separately.

Batch generation (generate_sample_data.py) only ever forms exactly-5 groups
and deliberately leaves a remainder unassigned per course (population sizes
are chosen as a multiple of 5, plus 2 - see that file). This module is what
completes that remainder as real students take the survey, applying the
policy exactly as specified:

  - The course's currently-unassigned pool (looking_for_group students with
    no group_membership row - fake leftovers AND any previously-pending real
    students together) is re-evaluated fresh every time someone new joins.
  - While >=5 people are unassigned: peel off exactly-5 groups at random.
  - Whatever remains (0-4 people) is the "remainder":
      0            -> nothing to do.
      1 or 2       -> each person individually joins a RANDOMLY chosen
                       EXISTING under-capacity group (current_members <
                       max_members) in the course. If literally no group has
                       room, they stay unassigned/pending - a real edge case
                       this policy doesn't try to solve further.
      3 or 4       -> they become a brand-new (smaller) group together.

Called synchronously right after a survey submission is inserted (see
../app.py), so the respondent gets an immediate group-or-pending answer.

NOT_IDEAL_THRESHOLD reuses the same 65 used elsewhere in this project
(generate_sample_data.py's group_feedback "left_group" cutoff) as the bar for
"this is a compatibility score worth warning about" - see ../app.py's popup.
Since compatibility_score is currently random (see algorithm/compatibility.py),
this threshold is only meaningful again once the real scoring is in place.
"""

import random
from statistics import mean

NOT_IDEAL_THRESHOLD = 65.0


def _unassigned_pool(cur, course_id):
    return [
        r[0] for r in cur.execute(
            """SELECT cm.student_id FROM course_membership cm
               WHERE cm.course_id = ? AND cm.looking_for_group = 1
                 AND cm.student_id NOT IN (
                     SELECT gm.student_id FROM group_membership gm
                     JOIN study_group sg ON sg.group_id = gm.group_id
                     WHERE sg.course_id = ?
                 )""",
            (course_id, course_id),
        ).fetchall()
    ]


def _pair_score_fn(cur, course_id):
    scores = {}
    for a, b, score in cur.execute(
        "SELECT student_a, student_b, compatibility_score FROM pairwise_compatibility WHERE course_id = ?",
        (course_id,),
    ):
        scores[(a, b)] = scores[(b, a)] = score

    def pair_score(x, y):
        return scores[(x, y)]

    return pair_score


def _group_avg(members, pair_score):
    pairs = [pair_score(members[i], members[j]) for i in range(len(members)) for j in range(i + 1, len(members))]
    return pairs


def _form_full_groups(unassigned):
    """PLACEHOLDER: exactly-5 groups formed by pure random shuffle-and-chunk."""
    pool = sorted(unassigned)
    random.shuffle(pool)
    formed = []
    while len(pool) >= 5:
        formed.append(pool[:5])
        pool = pool[5:]
    return formed, set(pool)  # pool is now the remainder (<5)


def _next_group_id(cur):
    row = cur.execute("SELECT group_id FROM study_group ORDER BY group_id DESC LIMIT 1").fetchone()
    n = int(row[0].split("_")[1]) + 1 if row else 1
    return f"grp_{n:03d}"


def _next_match_id(cur):
    row = cur.execute("SELECT match_id FROM match_data ORDER BY match_id DESC LIMIT 1").fetchone()
    n = int(row[0].split("_")[1]) + 1 if row else 1
    return f"match_{n:04d}"


def _insert_group(cur, course_id, members, pair_score, now_iso, name=None):
    scores = _group_avg(members, pair_score)
    avg, worst = mean(scores), min(scores)
    gid = _next_group_id(cur)
    cur.execute(
        "INSERT INTO study_group VALUES (?,?,?,?,?,?,?,?,?)",
        (gid, course_id, name or f"New Group {gid.split('_')[1]}", 5, len(members), now_iso,
         round(avg, 1), round(avg, 1), round(worst, 1)),
    )
    for m in members:
        cur.execute(
            "INSERT INTO group_membership VALUES (?,?,?,?)",
            (gid, m, now_iso, "Flexible/No Preference"),
        )
    for m in members:
        others = [o for o in members if o != m]
        avg_m = mean(pair_score(m, o) for o in others) if others else avg
        cur.execute(
            "INSERT INTO match_data VALUES (?,?,?,?,?,?,?)",
            (_next_match_id(cur), m, gid, round(avg_m, 1), 1, 0, now_iso),
        )
    return gid


def _recompute_group_stats(cur, group_id, pair_score):
    members = [r[0] for r in cur.execute(
        "SELECT student_id FROM group_membership WHERE group_id=?", (group_id,)
    ).fetchall()]
    scores = _group_avg(members, pair_score)
    avg, worst = mean(scores), min(scores)
    cur.execute(
        "UPDATE study_group SET current_members=?, group_score=?, avg_pairwise=?, worst_pairwise=? WHERE group_id=?",
        (len(members), round(avg, 1), round(avg, 1), round(worst, 1), group_id),
    )


def recompute_or_delete_group(cur, group_id, course_id):
    """
    Used by ../app.py's admin delete: call after removing a member from
    group_membership. Recomputes group_score/avg_pairwise/worst_pairwise for
    whoever's left, or deletes the group outright if that was the last member.
    """
    remaining = [r[0] for r in cur.execute(
        "SELECT student_id FROM group_membership WHERE group_id=?", (group_id,)
    ).fetchall()]
    if not remaining:
        cur.execute("DELETE FROM study_group WHERE group_id=?", (group_id,))
        return
    if len(remaining) == 1:
        cur.execute(
            "UPDATE study_group SET current_members=1, group_score=NULL, avg_pairwise=NULL, worst_pairwise=NULL WHERE group_id=?",
            (group_id,),
        )
        return
    pair_score = _pair_score_fn(cur, course_id)
    _recompute_group_stats(cur, group_id, pair_score)


def run_placement(con, course_id, now_iso):
    """
    Re-evaluates the whole unassigned pool for one course and applies the
    remainder policy. Returns {student_id: outcome} for every student this
    call touched (formed into a full group, placed into an existing one, or
    grouped into a new small group) - callers look up their own student_id
    in the result to report back what happened. Students left pending are
    NOT in the returned dict.
    """
    cur = con.cursor()
    pair_score = _pair_score_fn(cur, course_id)
    pool = _unassigned_pool(cur, course_id)

    outcomes = {}

    full_groups, remainder = _form_full_groups(pool)
    for group in full_groups:
        gid = _insert_group(cur, course_id, group, pair_score, now_iso)
        avg = mean(_group_avg(group, pair_score))
        for m in group:
            outcomes[m] = {"status": "grouped", "group_id": gid, "is_new_group": True,
                            "member_avg_score": round(mean(pair_score(m, o) for o in group if o != m), 1)}

    remainder = sorted(remainder)
    if len(remainder) in (1, 2):
        for sid in remainder:
            candidates = [r[0] for r in cur.execute(
                "SELECT group_id FROM study_group WHERE course_id=? AND current_members < max_members",
                (course_id,),
            ).fetchall()]
            if not candidates:
                outcomes[sid] = {"status": "pending"}
                continue
            best_gid = random.choice(candidates)
            members = [r[0] for r in cur.execute(
                "SELECT student_id FROM group_membership WHERE group_id=?", (best_gid,)
            ).fetchall()]
            best_avg = mean(pair_score(sid, m) for m in members)
            cur.execute(
                "INSERT INTO group_membership VALUES (?,?,?,?)",
                (best_gid, sid, now_iso, "Flexible/No Preference"),
            )
            cur.execute(
                "INSERT INTO match_data VALUES (?,?,?,?,?,?,?)",
                (_next_match_id(cur), sid, best_gid, round(best_avg, 1), 1, 0, now_iso),
            )
            _recompute_group_stats(cur, best_gid, pair_score)
            outcomes[sid] = {"status": "grouped", "group_id": best_gid, "is_new_group": False,
                              "member_avg_score": round(best_avg, 1)}
    elif len(remainder) in (3, 4):
        gid = _insert_group(cur, course_id, remainder, pair_score, now_iso)
        for sid in remainder:
            others = [o for o in remainder if o != sid]
            outcomes[sid] = {"status": "grouped", "group_id": gid, "is_new_group": True,
                              "member_avg_score": round(mean(pair_score(sid, o) for o in others), 1)}
    # len(remainder) == 0: nothing left to do.

    return outcomes
