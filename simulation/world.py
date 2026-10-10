"""
The simulated world: play one 4-week period for every group using each
student's hidden truth, and return only what the app would observe.

Each group meets meetings_per_week times a week: the members' median
preference, one fewer if their schedules barely overlap. At each meeting a
member shows up with a probability set by their true reliability, how well
their schedule fits the group's, exam weeks, and how happy they currently
are (unhappy students skip more). Everyone who came has an experience:

    discomfort = style gap to whoever came, weighted by what this person cares about
               + groupmates who didn't come (minded more by reliable people)
               + schedule clash with the group
    utility    = 5 - 4 x discomfort

and their running satisfaction moves toward it. Two week-ends in a row below
LEAVE_BELOW and they leave the group.

What comes back (Feedback, PeerRating) is what the app could know: who left
and when, plus an end-of-period form that only some students fill in. The
form has no grades or course performance. Four weeks say little about a
final grade, and grades depend mostly on the student, not the study group.

Every field, how it's produced, and whether the learner uses it:

  field                  produced from                                   used?
  left_group, weeks      leaving rule (the app sees this, form or not)   yes: who's released
  responded              hidden response rate, halved if they left       -
  satisfaction 1-5       running satisfaction, rounded up a bit          yes: target for the weight refit
  would_match_again      satisfaction vs a status-quo threshold          yes: who's released
  peer reliability 1-5   each answering groupmate rates attendance they  yes: reliability estimate
                         saw, plus their own leniency and noise
  peer helpfulness 1-5   true collaboration and attendance, same rater   yes: collaboration estimate
                         biases
  tags (new)             the 1-2 biggest causes of discomfort            yes: nudges the other 4 axes
  avoid (new)            the worst-fitting or flakiest groupmate         yes: pair never regrouped
  meetings attended      self-reported count                             no: peer ratings measure the
                                                                         same thing without self-report bias
  perceived fit 1-5      style gap felt at meetings                      no: overlaps satisfaction + tags
  productivity 1-5       group attendance, motivation, organisation      no: describes the group, not fit;
                         (how productive sessions felt, not grades)      kept for realism
  chat activity          group talkativeness x attendance (group-level)  no: mostly personality, weak fit signal

"tags" and "avoid" aren't in the app's group_feedback table yet; they're the
two questions this simulation suggests adding to the real form.
"""

from dataclasses import dataclass, field

import numpy as np

from algorithm.scoring import AXES

WEEKS_PER_PERIOD = 4
EXAM_WEEKS = {7, 8, 15, 16}            # midterms and finals, counted from week 1
STYLE_SCALE = 1.6
FLAKE_SCALE = 0.6
SCHEDULE_SCALE = 0.3
NOISE_SD = 0.10
EMA = 0.7                              # weight on the running satisfaction at each meeting
START_SATISFACTION = 3.7               # a new group starts here; a kept group carries on
LEAVE_BELOW = 2.4
STAY_IF_AT_LEAST = 2.9                 # "would you keep this group?" status quo wins unless clearly unhappy
REPORT_POSITIVITY = 0.3                # people round their own rating up a little
NO_GROUP_UTILITY = 2.0                 # a student with no group for the period
COMPLAIN_AT_OR_BELOW = 3               # form asks "what would make it better?" at this rating or lower


@dataclass
class Feedback:
    sid: str
    group_id: str
    left_group: bool                   # known to the app regardless of the form
    weeks_in_group: int
    responded: bool
    meetings_per_week: int | None = None
    meetings_attended: int | None = None
    satisfaction: int | None = None    # 1-5
    would_match_again: bool | None = None
    perceived_fit: int | None = None   # 1-5
    productivity: int | None = None    # 1-5, how productive sessions felt (not grades)
    chat_activity: str | None = None   # low / medium / high
    peer_reliability: float | None = None   # mean rating received from groupmates who answered
    peer_helpfulness: float | None = None
    tags: list = field(default_factory=list)    # e.g. "structure:more", "flaky_groupmates", "schedule_clash"
    avoid: list = field(default_factory=list)   # a groupmate they'd rather not be grouped with again


@dataclass
class PeerRating:
    rater: str
    ratee: str
    group_id: str
    reliability: int                   # 1-5: showed up and followed through
    helpfulness: int                   # 1-5: helped others understand


def _norm(x):
    return (x - 1) / 4


class RuleWorld:
    def __init__(self, students, truth, courses):
        self.students = students
        self.truth = truth
        self.courses = courses

    def _fit(self, a, b):
        course = self.courses[self.students[a].course]
        return course.fit[course.index[a], course.index[b]]

    def simulate(self, groups, period, rng, carry=None):
        """carry: {student: (group_id, satisfaction)} from the previous period, so
        students who stay in the same group pick up where they left off.
        -> (feedback for every grouped student, peer ratings, true utility by student)."""
        feedback, ratings, utility = [], [], {}
        carry = carry or {}
        for gid in sorted(groups):
            start = {s: carry[s][1] if s in carry and carry[s][0] == gid else START_SATISFACTION for s in groups[gid]}
            fb, pr, util = self._group(gid, sorted(groups[gid]), period, rng, start)
            feedback += fb
            ratings += pr
            utility.update(util)
        return feedback, ratings, utility

    def _group(self, gid, members, period, rng, start):
        t = self.truth
        fit = {s: float(np.mean([self._fit(s, m) for m in members if m != s])) if len(members) > 1 else 0.0
               for s in members}
        per_week = int(np.ceil(np.median([self.students[s].per_week for s in members])))
        if len(members) > 1 and np.mean(list(fit.values())) < 0.3:
            per_week = max(1, per_week - 1)

        sat = dict(start)
        attended = {s: 0 for s in members}
        scheduled = {s: 0 for s in members}
        low_weeks = {s: 0 for s in members}
        left_week = {}
        contrib = {s: {} for s in members}
        style_sum = {s: 0.0 for s in members}

        for w in range(WEEKS_PER_PERIOD):
            week = period * WEEKS_PER_PERIOD + w + 1
            exam = 0.9 if week in EXAM_WEEKS else 1.0
            for _ in range(per_week):
                active = [s for s in members if s not in left_week]
                came = []
                for s in active:
                    scheduled[s] += 1
                    p = (np.clip(0.52 + 0.11 * (t[s].axes["reliability"] - 1), 0.45, 0.95)
                         * (0.72 + 0.28 * fit[s]) * exam
                         * (0.6 + 0.4 * np.clip((sat[s] - 1) / 3, 0, 1)))
                    if rng.random() < p:
                        came.append(s)
                        attended[s] += 1
                for s in came:
                    others = [m for m in came if m != s]
                    mates = [m for m in active if m != s]
                    parts = {}
                    if others:
                        for a in AXES:
                            gap = abs(t[s].axes[a] - np.mean([t[m].axes[a] for m in others]))
                            parts[f"style:{a}"] = STYLE_SCALE * t[s].sensitivity[a] * gap / 4 / len(AXES)
                    absent = (len(mates) - len(others)) / len(mates) if mates else 1.0
                    parts["flaky_groupmates"] = FLAKE_SCALE * absent * t[s].flake_weight * (0.5 + 0.5 * _norm(t[s].axes["reliability"]))
                    parts["schedule_clash"] = SCHEDULE_SCALE * t[s].schedule_weight * (1 - fit[s])
                    discomfort = sum(parts.values()) + rng.normal(0, NOISE_SD)
                    sat[s] = EMA * sat[s] + (1 - EMA) * float(np.clip(5 - 4 * discomfort, 1, 5))
                    style_sum[s] += sum(v for k, v in parts.items() if k.startswith("style:"))
                    for k, v in parts.items():
                        contrib[s][k] = contrib[s].get(k, 0.0) + v
            for s in members:
                if s in left_week:
                    continue
                low_weeks[s] = low_weeks[s] + 1 if sat[s] < LEAVE_BELOW else 0
                if low_weeks[s] >= 2:
                    left_week[s] = w + 1

        active = [s for s in members if s not in left_week]
        att_rate = {s: attended[s] / scheduled[s] if scheduled[s] else 0.0 for s in members}
        group_att = sum(attended.values()) / max(1, sum(scheduled.values()))
        pool = active or members
        productive = (0.45 * group_att + 0.25 * _norm(np.mean([t[s].axes["intensity"] for s in pool]))
                      + 0.20 * _norm(np.mean([(t[s].axes["planning"] + t[s].axes["structure"]) / 2 for s in pool]))
                      + 0.10 * (1 - np.mean([style_sum[s] / max(1, attended[s]) for s in pool])))
        talk = np.mean([_norm((t[s].axes["session_mode"] + t[s].axes["collaboration"]) / 2) for s in pool])
        activity = talk * group_att * min(1.0, len(active) / 4)
        chat = "low" if activity < 0.33 else "medium" if activity < 0.47 else "high"

        feedback, util = [], {}
        for s in members:
            left = s in left_week
            util[s] = sat[s]
            fb = Feedback(s, gid, left, left_week.get(s, WEEKS_PER_PERIOD),
                          responded=rng.random() < t[s].response_rate * (0.5 if left else 1.0))
            if fb.responded:
                fb.meetings_per_week = per_week
                fb.meetings_attended = attended[s]
                fb.satisfaction = int(np.clip(round(sat[s] + REPORT_POSITIVITY + rng.normal(0, 0.4)), 1, 5))
                fb.would_match_again = not left and sat[s] + rng.normal(0, 0.3) >= STAY_IF_AT_LEAST
                mean_style = style_sum[s] / attended[s] if attended[s] else 0.3
                fb.perceived_fit = int(np.clip(round(5.2 - 6 * mean_style + rng.normal(0, 0.5)), 1, 5))
                fb.productivity = int(np.clip(round(1 + 4 * productive + 0.5 * t[s].leniency + rng.normal(0, 0.5)), 1, 5))
                fb.chat_activity = chat
                if fb.satisfaction <= COMPLAIN_AT_OR_BELOW and contrib[s]:
                    fb.tags = self._reasons(s, members, contrib[s])
                    if fb.satisfaction <= 2:
                        fb.avoid = self._worst_mate(s, members, att_rate, fb.tags)
            feedback.append(fb)

        ratings = []
        overlap = {s: left_week.get(s, WEEKS_PER_PERIOD) for s in members}
        for fb in feedback:
            if not fb.responded:
                continue
            for m in members:
                if m == fb.sid or overlap[m] < 1:
                    continue
                lenient = t[fb.sid].leniency
                rel = int(np.clip(round(1 + 4 * att_rate[m] + lenient + rng.normal(0, 0.6)), 1, 5))
                helpful = int(np.clip(round(1 + 4 * (0.6 * _norm(t[m].axes["collaboration"]) + 0.4 * att_rate[m])
                                            + lenient + rng.normal(0, 0.6)), 1, 5))
                ratings.append(PeerRating(fb.sid, m, gid, rel, helpful))
        received = {}
        for r in ratings:
            received.setdefault(r.ratee, []).append(r)
        for fb in feedback:
            if fb.responded and fb.sid in received:
                fb.peer_reliability = float(np.mean([r.reliability for r in received[fb.sid]]))
                fb.peer_helpfulness = float(np.mean([r.helpfulness for r in received[fb.sid]]))
        return feedback, ratings, util

    def _reasons(self, sid, members, contrib):
        """Up to two biggest complaints that each explain at least 15% of the discomfort."""
        total = sum(contrib.values()) or 1.0
        tags = []
        for key, value in sorted(contrib.items(), key=lambda kv: -kv[1])[:2]:
            if value / total < 0.15:
                continue
            if key.startswith("style:"):
                axis = key.split(":", 1)[1]
                mates = np.mean([self.truth[m].axes[axis] for m in members if m != sid])
                tags.append(f"{axis}:{'more' if self.truth[sid].axes[axis] > mates else 'less'}")
            else:
                tags.append(key)
        return tags

    def _worst_mate(self, sid, members, att_rate, tags):
        mates = [m for m in members if m != sid]
        if not mates:
            return []
        if tags and tags[0] == "flaky_groupmates":
            return [min(mates, key=lambda m: (att_rate[m], m))]
        t = self.truth[sid]
        return [max(mates, key=lambda m: (sum(t.sensitivity[a] * abs(t.axes[a] - self.truth[m].axes[a]) for a in AXES), m))]
