"""
Who gets reassigned after a period, and where they go.

  - Released: everyone who left their group, and everyone who answered the
    form and said they wouldn't want to stay. Students who didn't answer
    stay where they are; there's no signal to act on.
  - A group left with fewer than MIN_KEEP members is dissolved and all of
    its members are released too.
  - Released students (and anyone still without a group) are grouped per
    course with simulation/groups.py: the live ILP for small pools, the swap
    search for big ones. Anyone it can't place joins the existing group with
    room where their average score is highest, never the group they just
    left. Otherwise they wait a period without a group.

Scores come from the Learner, so the "learn" and "survey" runs share this
exact policy and differ only in what the scores know.
"""

import numpy as np

from algorithm.grouping import GROUP_MAX
from simulation.groups import form

MIN_KEEP = 3


def reassign(groups, feedback, learner, students, period, rng):
    """-> (new groups, set of students whose group changed)."""
    by_sid = {fb.sid: fb for fb in feedback}
    grouped = {s for m in groups.values() for s in m}
    released, previous, kept = {s for s in students if s not in grouped}, {}, {}
    for gid, members in groups.items():
        out = {s for s in members if by_sid[s].left_group
               or (by_sid[s].responded and not by_sid[s].would_match_again)}
        stay = [s for s in members if s not in out]
        if out and len(stay) < MIN_KEEP:
            out, stay = set(members), []
        for s in out:
            previous[s] = gid
        released |= out
        if stay:
            kept[gid] = stay

    new_groups = dict(kept)
    for course_id in sorted({students[s].course for s in released}):
        course = learner.courses[course_id]
        pool = sorted(s for s in released if students[s].course == course_id)
        S = learner.score_matrix(course_id)
        formed, leftover = form(pool, S, course.index, rng)
        for i, members in enumerate(formed):
            new_groups[f"p{period}_{course_id.split('-')[1]}_{i:03d}"] = members
        for s in sorted(leftover):
            options = [(float(np.mean([S[course.index[s], course.index[m]] for m in members])), gid)
                       for gid, members in new_groups.items()
                       if len(members) < GROUP_MAX and gid != previous.get(s) and students[members[0]].course == course_id]
            if options:
                new_groups[max(options)[1]].append(s)

    before = {s: g for g, m in groups.items() for s in m}
    after = {s: g for g, m in new_groups.items() for s in m}
    return new_groups, {s for s in students if before.get(s) != after.get(s)}
