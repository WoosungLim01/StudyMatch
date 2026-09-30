"""
StudyMatch — live group placement for incoming survey respondents.

Called synchronously right after a survey submission is inserted (see
../app.py), so the respondent gets an immediate group-or-pending answer.
Groups already formed are never reshuffled - only the course's currently
unassigned pool is placed:

  - The pool (looking_for_group students with no group_membership row in
    that course - synthetic leftovers AND any previously-pending real
    students together) is re-evaluated fresh every time someone new joins.
  - Pool >= 4: algorithm/grouping.py's ILP partitions it into new groups of
    4-5 that maximize within-group compatibility.
  - Whoever the ILP can't place (pool of 1-3, 6, 7 or 11 - sizes that don't
    split into 4s and 5s) joins the EXISTING under-capacity group in the
    course (current_members < max_members) where their average compatibility
    with the current members is highest. If no group has room, they stay
    pending until enough people arrive to form a new group.

NOT_IDEAL_THRESHOLD reuses the same 65 used elsewhere in this project
(generate_sample_data.py's group_feedback "left_group" cutoff) as the bar for
"this is a compatibility score worth warning about" - see ../app.py's popup.
Scores are the real 0-100 weighted similarity from algorithm/compatibility.py.
"""

import re
from statistics import mean

from algorithm.grouping import form_groups

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


def _best_open_group(cur, course_id, sid, pair_score):
    """Existing group with room where sid's mean compatibility with the members is highest."""
    best = None
    for (gid,) in cur.execute(
        "SELECT group_id FROM study_group WHERE course_id=? AND current_members < max_members ORDER BY group_id",
        (course_id,),
    ).fetchall():
        members = [r[0] for r in cur.execute(
            "SELECT student_id FROM group_membership WHERE group_id=?", (gid,)
        ).fetchall()]
        if not members:
            continue
        avg = mean(pair_score(sid, m) for m in members)
        if best is None or avg > best[1]:
            best = (gid, avg)
    return best


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


def _next_group_id(cur):
    row = cur.execute("SELECT group_id FROM study_group ORDER BY group_id DESC LIMIT 1").fetchone()
    n = int(row[0].split("_")[1]) + 1 if row else 1
    return f"grp_{n:03d}"


def _next_match_id(cur):
    row = cur.execute("SELECT match_id FROM match_data ORDER BY match_id DESC LIMIT 1").fetchone()
    n = int(row[0].split("_")[1]) + 1 if row else 1
    return f"match_{n:04d}"


def group_name_for(cur, course_id):
    """Next "<course code> Group <n>" for this course, n = 1 + highest number in use."""
    code = cur.execute("SELECT course_code FROM course WHERE course_id=?", (course_id,)).fetchone()[0]
    pattern = re.compile(rf"{re.escape(code)} Group (\d+)")
    used = [
        int(m.group(1))
        for (name,) in cur.execute("SELECT group_name FROM study_group WHERE course_id=?", (course_id,))
        if name and (m := pattern.fullmatch(name))
    ]
    return f"{code} Group {max(used, default=0) + 1}"


def _insert_group(cur, course_id, members, pair_score, now_iso, name=None):
    scores = _group_avg(members, pair_score)
    avg, worst = mean(scores), min(scores)
    gid = _next_group_id(cur)
    cur.execute(
        "INSERT INTO study_group VALUES (?,?,?,?,?,?,?,?,?)",
        (gid, course_id, name or group_name_for(cur, course_id), 5, len(members), now_iso,
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
    Places the course's whole unassigned pool (see module docstring).
    Returns {student_id: outcome} for every student this call placed - into
    a new ILP-formed group or an existing one. Students left pending are
    NOT in the returned dict.
    """
    cur = con.cursor()
    pair_score = _pair_score_fn(cur, course_id)
    pool = _unassigned_pool(cur, course_id)

    outcomes = {}

    new_groups, leftover, _ = form_groups(pool, pair_score)
    for group in new_groups:
        gid = _insert_group(cur, course_id, group, pair_score, now_iso)
        for m in group:
            outcomes[m] = {"status": "grouped", "group_id": gid, "is_new_group": True,
                           "member_avg_score": round(mean(pair_score(m, o) for o in group if o != m), 1)}

    for sid in sorted(leftover):
        best = _best_open_group(cur, course_id, sid, pair_score)
        if best is None:
            continue  # pending - nothing has room
        gid, avg = best
        cur.execute(
            "INSERT INTO group_membership VALUES (?,?,?,?)",
            (gid, sid, now_iso, "Flexible/No Preference"),
        )
        cur.execute(
            "INSERT INTO match_data VALUES (?,?,?,?,?,?,?)",
            (_next_match_id(cur), sid, gid, round(avg, 1), 1, 0, now_iso),
        )
        _recompute_group_stats(cur, gid, pair_score)
        outcomes[sid] = {"status": "grouped", "group_id": gid, "is_new_group": False,
                         "member_avg_score": round(avg, 1)}

    return outcomes
