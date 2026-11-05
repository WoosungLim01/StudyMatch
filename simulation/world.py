"""
The simulated world: play one week for every group using each student's hidden
truth, and return only what the app would observe. A semester lasts at most
SEMESTER_WEEKS weeks; semester.py steps through it one week at a time.

Each group meets meetings_per_week times this week: the members' median
preference, one fewer if their schedules barely overlap. At each meeting a
member shows up with a probability set by their true reliability, how well
their schedule fits the group's, exam weeks, and how happy they currently
are (unhappy students skip more). Everyone who came has an experience:

    discomfort = style gap to whoever came, weighted by what this person cares about
               + groupmates who didn't come (minded more by reliable people)
               + schedule clash with the group
    utility    = 5 - 4 x discomfort

and their running satisfaction moves toward it. Satisfaction carries over
from week to week while a student stays in the same group (Member); a new
group starts fresh. Two week-ends in a row below LEAVE_BELOW and they leave.

judge() is the one place where a week's satisfaction is decided. Here it's
the rule above. llm_world.py overrides judge() so a language model decides
how each student felt, within a clamp around this rule.

What comes back (WeekResult) is what the app could know: who left, a short
weekly pulse form that only some students answer (fewer as the semester
wears on), and every CHECKIN_EVERY weeks a longer check-in with peer
ratings. No grades or course performance: a week says nothing about a grade.

  field                  produced from                                   used?
  left_group             leaving rule (the app sees this, form or not)   yes: placed in a new group
  responded              hidden response rate x PULSE_RESPONSE, less     -
                         each week (FATIGUE), halved if they left
  satisfaction 1-5       running satisfaction, rounded up a bit          yes: target for the weight refit
  would_match_again      satisfaction vs a status-quo threshold          yes: who's moved
  tags (new)             the 1-2 biggest causes of discomfort            yes: nudges the other 4 axes
  avoid (new)            the worst-fitting or flakiest groupmate         yes: pair never regrouped
  meetings attended      self-reported count this week                   no: peer ratings cover it
  check-in weeks only:
  peer reliability 1-5   each answering groupmate rates the attendance   yes: reliability estimate
                         they saw since the last check-in, plus their
                         own leniency and noise
  peer helpfulness 1-5   true collaboration and attendance, same biases  yes: collaboration estimate
  perceived fit 1-5      style gap felt at meetings                      no: overlaps satisfaction + tags
  productivity 1-5       attendance, motivation, organisation            no: describes the group, not fit
  chat activity          group talkativeness x attendance                no: mostly personality

"tags" and "avoid" aren't in the app's group_feedback table yet; they're the
two questions this simulation suggests adding to the real form.
"""

from dataclasses import dataclass, field

import numpy as np

from algorithm.scoring import AXES

SEMESTER_WEEKS = 14                    # hard maximum: no semester runs longer
EXAM_WEEKS = {7, 8, 13, 14}            # midterms and finals, counted from week 1
CHECKIN_EVERY = 4                      # peer ratings and the longer form in weeks 4, 8, 12
PULSE_RESPONSE = 0.8                   # a weekly pulse is answered less often than a monthly form
FATIGUE = 0.02                         # ... and a little less each week
STYLE_SCALE = 1.6
FLAKE_SCALE = 0.6
SCHEDULE_SCALE = 0.3
NOISE_SD = 0.10
EMA = 0.7                              # weight on the running satisfaction at each meeting
START_SATISFACTION = 3.7               # a new group starts here; a kept group carries on
LEAVE_BELOW = 2.4
STAY_IF_AT_LEAST = 2.9                 # "would you keep this group?" status quo wins unless clearly unhappy
REPORT_POSITIVITY = 0.3                # people round their own rating up a little
NO_GROUP_UTILITY = 2.0                 # a student with no group that week
COMPLAIN_AT_OR_BELOW = 3               # form asks "what would make it better?" at this rating or lower

# The form's "what would make the group better?" options. axis:more = the student
# wanted more of it than the group gave (they sit above the group on that axis).
TAGS = {
    "flaky_groupmates": "Groupmates didn't show up",
    "schedule_clash": "Schedules didn't line up",
    "planning:more": "Wanted more planning", "planning:less": "Wanted less planning",
    "session_mode:more": "Wanted to talk things through more", "session_mode:less": "Wanted quieter sessions",
    "reliability:more": "Wanted groupmates who follow through", "reliability:less": "Group expected more commitment",
    "structure:more": "Wanted more structure", "structure:less": "Wanted less structure",
    "intensity:more": "Wanted a more driven group", "intensity:less": "Group was too intense",
    "collaboration:more": "Wanted more explaining to each other",
    "collaboration:less": "Wanted to try problems alone first",
}


@dataclass
class Member:
    """What carries over for a student from one week to the next while they stay in one group."""
    group_id: str
    satisfaction: float = START_SATISFACTION
    low_weeks: int = 0                 # week-ends in a row below LEAVE_BELOW
    tenure: int = 0                    # weeks in this group so far
    attended: int = 0                  # meetings since the last check-in: what groupmates rate
    scheduled: int = 0


@dataclass
class Feedback:
    sid: str
    group_id: str
    week: int
    left_group: bool                   # known to the app regardless of the form
    weeks_in_group: int
    responded: bool
    checkin: bool = False              # the longer form with peer ratings
    meetings_per_week: int | None = None
    meetings_attended: int | None = None
    satisfaction: int | None = None    # 1-5
    would_match_again: bool | None = None
    perceived_fit: int | None = None   # 1-5, check-in weeks
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


@dataclass
class GroupWeek:
    """One group's week before anyone has judged it: who came to what, and the rule's verdict."""
    gid: str
    members: list
    week: int
    fit: dict                          # each member's mean schedule fit with the others, 0-1
    per_week: int
    meetings: list                     # one list of attendees per meeting
    before: dict                       # Member state at the start of the week
    satisfaction: dict                 # the rule's running satisfaction at the end of the week
    attended: dict
    contrib: dict                      # what caused each member's discomfort this week
    style_sum: dict


@dataclass
class Verdict:
    satisfaction: float
    tags: list | None = None           # None: the rule picks the complaint tags
    avoid: list | None = None
    detail: dict | None = None         # world-specific extras, kept in the trace


@dataclass
class WeekResult:
    feedback: list
    ratings: list
    utility: dict                      # true satisfaction at the end of the week, grouped students only
    state: dict                        # sid -> Member, to pass back in next week
    meetings: dict                     # gid -> meetings held
    detail: dict                       # sid -> Verdict.detail, when the world adds one
    stats: dict = field(default_factory=dict)   # what judging the week cost (LLM world): calls, cache hits...
    groups: dict = field(default_factory=dict)  # gid -> what the world adds per group (meeting accounts)


def _norm(x):
    return (x - 1) / 4


class RuleWorld:
    def __init__(self, students, truth, courses):
        self.students = students
        self.truth = truth
        self.courses = courses
        self.track = None                  # which strategy's semester is being played (simulate sets it)

    def _fit(self, a, b):
        course = self.courses[self.students[a].course]
        return course.fit[course.index[a], course.index[b]]

    def simulate(self, groups, week, rng, state=None, track=None):
        """groups: {group_id: [students]} meeting this week (1-based week number).
        state: what simulate() returned last week; students who stay in the same
        group pick up where they left off. track: which strategy's semester this
        is, for a world that keeps its own memory between weeks (the meeting
        world); None when there is only one. -> WeekResult."""
        state = state or {}
        self.track = track
        played = [self._play(gid, sorted(groups[gid]), week, rng, state) for gid in sorted(groups)]
        verdicts = self.judge(played)
        out = WeekResult([], [], {}, {}, {}, {})
        for gw in played:
            self._finish(gw, rng, verdicts, out)
        out.stats = self.week_stats()
        out.groups = self.week_groups()
        return out

    def judge(self, played):
        """How each student felt at the end of the week. -> {sid: Verdict}."""
        return {s: Verdict(gw.satisfaction[s]) for gw in played for s in gw.members}

    def week_stats(self):
        """What judging the week cost. Nothing, for rules."""
        return {}

    def week_groups(self):
        """What the world adds per group this week (meeting accounts). Nothing, for rules."""
        return {}

    def attend_factor(self, gid, sid):
        """Multiplier on a member's chance of coming to a meeting, from what the world knows
        beyond the rules (the meeting world's "likely to come next time"). 1 for rules."""
        return 1.0

    def reset(self):
        """Forget what the world kept between weeks (the meeting world's memory): a new
        semester starts. Nothing to forget, for rules."""

    def _play(self, gid, members, week, rng, state):
        t = self.truth
        before = {s: state[s] if s in state and state[s].group_id == gid else Member(gid) for s in members}
        fit = {s: float(np.mean([self._fit(s, m) for m in members if m != s])) if len(members) > 1 else 0.0
               for s in members}
        per_week = int(np.ceil(np.median([self.students[s].per_week for s in members])))
        if len(members) > 1 and np.mean(list(fit.values())) < 0.3:
            per_week = max(1, per_week - 1)
        exam = 0.9 if week in EXAM_WEEKS else 1.0

        sat = {s: before[s].satisfaction for s in members}
        attended = {s: 0 for s in members}
        contrib = {s: {} for s in members}
        style_sum = {s: 0.0 for s in members}
        meetings = []
        for _ in range(per_week):
            came = []
            for s in members:
                p = (np.clip(0.52 + 0.11 * (t[s].axes["reliability"] - 1), 0.45, 0.95)
                     * (0.72 + 0.28 * fit[s]) * exam
                     * (0.6 + 0.4 * np.clip((sat[s] - 1) / 3, 0, 1))
                     * self.attend_factor(gid, s))
                if rng.random() < min(p, 0.97):
                    came.append(s)
                    attended[s] += 1
            meetings.append(came)
            for s in came:
                others = [m for m in came if m != s]
                mates = [m for m in members if m != s]
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
        return GroupWeek(gid, members, week, fit, per_week, meetings, before, sat, attended, contrib, style_sum)

    def _finish(self, gw, rng, verdicts, out):
        """Leaving, the forms and peer ratings, from each member's judged satisfaction."""
        t = self.truth
        members, week = gw.members, gw.week
        sat = {s: float(verdicts[s].satisfaction) for s in members}
        after, left = {}, set()
        for s in members:
            b = gw.before[s]
            low = b.low_weeks + 1 if sat[s] < LEAVE_BELOW else 0
            if low >= 2:
                left.add(s)
            after[s] = Member(gw.gid, sat[s], low, b.tenure + 1, b.attended + gw.attended[s], b.scheduled + gw.per_week)
        rate = {s: after[s].attended / after[s].scheduled if after[s].scheduled else 0.0 for s in members}
        checkin = week % CHECKIN_EVERY == 0

        group_att = sum(gw.attended.values()) / max(1, gw.per_week * len(members))
        pool = [s for s in members if s not in left] or members
        productive = (0.45 * group_att + 0.25 * _norm(np.mean([t[s].axes["intensity"] for s in pool]))
                      + 0.20 * _norm(np.mean([(t[s].axes["planning"] + t[s].axes["structure"]) / 2 for s in pool]))
                      + 0.10 * (1 - np.mean([gw.style_sum[s] / max(1, gw.attended[s]) for s in pool])))
        talk = np.mean([_norm((t[s].axes["session_mode"] + t[s].axes["collaboration"]) / 2) for s in pool])
        activity = talk * group_att * min(1.0, (len(members) - len(left)) / 4)
        chat = "low" if activity < 0.33 else "medium" if activity < 0.47 else "high"

        feedback = []
        for s in members:
            gone = s in left
            out.utility[s] = sat[s]
            answer_rate = t[s].response_rate * PULSE_RESPONSE * max(0.3, 1 - FATIGUE * (week - 1))
            fb = Feedback(s, gw.gid, week, gone, after[s].tenure,
                          responded=rng.random() < answer_rate * (0.5 if gone else 1.0), checkin=checkin)
            if fb.responded:
                fb.meetings_per_week = gw.per_week
                fb.meetings_attended = gw.attended[s]
                fb.satisfaction = int(np.clip(round(sat[s] + REPORT_POSITIVITY + rng.normal(0, 0.4)), 1, 5))
                fb.would_match_again = bool(not gone and sat[s] + rng.normal(0, 0.3) >= STAY_IF_AT_LEAST)
                if checkin:
                    mean_style = gw.style_sum[s] / gw.attended[s] if gw.attended[s] else 0.3
                    fb.perceived_fit = int(np.clip(round(5.2 - 6 * mean_style + rng.normal(0, 0.5)), 1, 5))
                    fb.productivity = int(np.clip(round(1 + 4 * productive + 0.5 * t[s].leniency + rng.normal(0, 0.5)), 1, 5))
                    fb.chat_activity = chat
                if fb.satisfaction <= COMPLAIN_AT_OR_BELOW:
                    v = verdicts[s]
                    fb.tags = v.tags[:2] if v.tags is not None else (
                        self._reasons(s, members, gw.contrib[s]) if gw.contrib[s] else [])
                    if fb.satisfaction <= 2:
                        fb.avoid = v.avoid if v.avoid is not None else self._worst_mate(s, members, rate, fb.tags)
            feedback.append(fb)
            if verdicts[s].detail is not None:
                out.detail[s] = verdicts[s].detail

        if checkin:
            ratings = []
            for fb in feedback:
                if not fb.responded:
                    continue
                lenient = t[fb.sid].leniency
                for m in members:
                    if m == fb.sid:
                        continue
                    rel = int(np.clip(round(1 + 4 * rate[m] + lenient + rng.normal(0, 0.6)), 1, 5))
                    helpful = int(np.clip(round(1 + 4 * (0.6 * _norm(t[m].axes["collaboration"]) + 0.4 * rate[m])
                                                + lenient + rng.normal(0, 0.6)), 1, 5))
                    ratings.append(PeerRating(fb.sid, m, gw.gid, rel, helpful))
            received = {}
            for r in ratings:
                received.setdefault(r.ratee, []).append(r)
            for fb in feedback:
                if fb.responded and fb.sid in received:
                    fb.peer_reliability = float(np.mean([r.reliability for r in received[fb.sid]]))
                    fb.peer_helpfulness = float(np.mean([r.helpfulness for r in received[fb.sid]]))
            for s in members:
                after[s].attended = after[s].scheduled = 0
            out.ratings += ratings

        out.feedback += feedback
        out.state.update(after)
        out.meetings[gw.gid] = gw.per_week

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
