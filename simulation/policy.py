"""
Who is regrouped at the end of a week, and where they go.

Every week, like the live app's waiting pool:
  - anyone who quit, or is still without a group, is placed again
  - a group left with fewer than MIN_KEEP members dissolves; its members are placed too

Only on regroup weeks (every Policy.cadence weeks, up to last_move_week):
  - unhappy students are moved: those who answered "I wouldn't keep this
    group" Policy.strikes weeks in a row and have been in the group at least
    min_tenure weeks, so nobody is moved out of a group they've barely met.
    Students who don't answer aren't moved; there's no signal to act on.

Placement is per course with simulation/groups.py (the live ILP for small
pools, the swap search for big ones). Anyone it can't place joins the
existing group with room where their average score is highest, never the
group they just left. Otherwise they wait a week without a group.

Scores come from the Learner, so "learn" and "survey" share this exact
policy and differ only in what the scores know. frequency.py tests how
often regrouping should happen.
"""

from dataclasses import dataclass

import numpy as np

from algorithm.grouping import GROUP_MAX
from simulation.groups import form

MIN_KEEP = 3


@dataclass(frozen=True)
class Policy:
    """Defaults are what frequency.py found best in the rule world: acting on the first
    "I'd switch" beats waiting for a second, and every 2 weeks matches every week with
    a quarter fewer moves."""
    cadence: int | None = 2            # move unhappy students every `cadence` weeks; None = never
    strikes: int = 1                   # "I'd rather switch" answers in a row before a move
    min_tenure: int = 2                # weeks in a group before an unhappy student is moved out
    last_move_week: int = 11           # no moves after this week: groups need time together before finals

    def label(self):
        if self.cadence is None:
            return "never move unhappy students (only place those who quit)"
        every = "every week" if self.cadence == 1 else f"every {self.cadence} weeks"
        after = "1 unhappy answer" if self.strikes == 1 else f"{self.strikes} unhappy answers in a row"
        return f"move unhappy students {every}, after {after}"


def update_strikes(strikes, feedback):
    """Count each student's "I'd rather switch" answers in a row. Unanswered weeks change nothing."""
    for fb in feedback:
        if fb.responded:
            strikes[fb.sid] = 0 if fb.would_match_again else strikes.get(fb.sid, 0) + 1


def reassign(groups, feedback, learner, students, week, rng, policy, strikes):
    """-> (new groups, students whose group changed, counts of what happened)."""
    by_sid = {fb.sid: fb for fb in feedback}
    grouped = {s for m in groups.values() for s in m}
    released, previous, kept = {s for s in students if s not in grouped}, {}, {}
    moving = policy.cadence is not None and week % policy.cadence == 0 and week <= policy.last_move_week
    counts = {"quit": 0, "unhappy": 0, "dissolved": 0, "waiting": len(released)}
    for gid, members in groups.items():
        quit = {s for s in members if by_sid[s].left_group}
        unhappy = {s for s in members if moving and s not in quit and strikes.get(s, 0) >= policy.strikes
                   and by_sid[s].weeks_in_group >= policy.min_tenure}
        out = quit | unhappy
        stay = [s for s in members if s not in out]
        counts["quit"] += len(quit)
        counts["unhappy"] += len(unhappy)
        if out and len(stay) < MIN_KEEP:
            counts["dissolved"] += 1
            out, stay = set(members), []
        for s in out:
            previous[s] = gid
        released |= out
        if stay:
            kept[gid] = stay

    new_groups = dict(kept)
    formed = 0
    for course_id in sorted({students[s].course for s in released}):
        course = learner.courses[course_id]
        pool = sorted(s for s in released if students[s].course == course_id)
        S = learner.score_matrix(course_id)
        made, leftover = form(pool, S, course.index, rng)
        for i, members in enumerate(made):
            new_groups[f"w{week}_{course_id.split('-')[1]}_{i:03d}"] = members
        formed += len(made)
        for s in sorted(leftover):
            options = [(float(np.mean([S[course.index[s], course.index[m]] for m in members])), gid)
                       for gid, members in new_groups.items()
                       if len(members) < GROUP_MAX and gid != previous.get(s) and students[members[0]].course == course_id]
            if options:
                new_groups[max(options)[1]].append(s)

    before = {s: g for g, m in groups.items() for s in m}
    after = {s: g for g, m in new_groups.items() for s in m}
    moved = {s for s in students if before.get(s) != after.get(s) and s in after}
    for s in moved:
        strikes[s] = 0
    counts["new_groups"] = formed
    counts["still_waiting"] = sum(s not in after for s in students)
    return new_groups, moved, counts
