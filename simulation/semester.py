"""
One simulated semester, one week at a time, for several strategies side by side.

    sem = Semester(cohort, RuleWorld(...))
    sem.reset(seed=0)          # back to the semester-start groups, learners back to the survey
    while not sem.done:
        sem.step()             # one week: meet, give feedback, learn, regroup

run.py drives it across seeds; live.py drives it from the dashboard's Reset and
Step buttons. A semester never runs past SEMESTER_WEEKS weeks.

Strategies, all starting from the same semester-start groups:
  stay     never regroup (people who quit stay without a group)
  survey   regroup per the Policy, scoring with survey answers and hand-set weights
  learn    the same Policy, scored with what the Learner took from feedback

The world's randomness depends only on (seed, week): within a seed every
strategy sees the same chance events each week, so differences come from
the strategy, not luck.
"""

from dataclasses import asdict, dataclass, field

import numpy as np

from algorithm.scoring import AXES
from simulation.learner import Learner
from simulation.policy import Policy, reassign, update_strikes
from simulation.world import NO_GROUP_UTILITY, SEMESTER_WEEKS

STRATEGIES = ("stay", "survey", "learn")
METRICS = ["true_satisfaction", "unhappy_share", "reported_satisfaction", "response_rate", "attendance",
           "left", "without_group", "moved_after", "profile_accuracy", "reliability_accuracy"]


@dataclass
class Cohort:
    students: dict
    truth: dict
    start_groups: dict
    courses: dict

    def sample(self, per_course):
        """A smaller cohort made of whole semester-start groups, about per_course students per course.
        Keeps the real starting groups, so nobody has to be regrouped to shrink the run."""
        keep = {}
        for course in sorted(self.courses):
            n = 0
            for gid in sorted(g for g, m in self.start_groups.items() if self.students[m[0]].course == course):
                if n >= per_course:
                    break
                keep[gid] = self.start_groups[gid]
                n += len(keep[gid])
        ids = {s for m in keep.values() for s in m}
        return Cohort({s: self.students[s] for s in sorted(ids)}, {s: self.truth[s] for s in ids}, keep, self.courses)


@dataclass
class Track:
    """Everything one strategy carries through the semester."""
    name: str
    learner: Learner
    groups: dict
    state: dict = field(default_factory=dict)
    strikes: dict = field(default_factory=dict)
    rows: list = field(default_factory=list)
    trace: list = field(default_factory=list)
    weights: list = field(default_factory=list)
    accuracy: list = field(default_factory=list)
    log: list = field(default_factory=list)


class Semester:
    def __init__(self, cohort, world, strategies=STRATEGIES, policy=Policy(), gate=True, weeks=SEMESTER_WEEKS,
                 record=True):
        if not 1 <= weeks <= SEMESTER_WEEKS:
            raise ValueError(f"a semester is 1 to {SEMESTER_WEEKS} weeks, not {weeks}")
        self.cohort, self.world = cohort, world
        self.strategies, self.policy, self.gate = tuple(strategies), policy, gate
        self.weeks, self.record = weeks, record
        self.reset(0)

    @property
    def done(self):
        return self.week >= self.weeks

    def reset(self, seed=None):
        """Back to week 0: the semester-start groups, nobody has met yet."""
        if seed is not None:
            self.seed = seed
        self.week = 0
        self.current = None
        self.world.reset()
        c = self.cohort
        self.tracks = {}
        for name in self.strategies:
            learner = Learner(c.students, c.courses, learn=(name == "learn"), gate=self.gate)
            tr = Track(name, learner, {g: list(m) for g, m in c.start_groups.items()})
            tr.weights.append(dict(learner.weights))
            tr.accuracy.append(self._axis_accuracy(learner))
            self.tracks[name] = tr

    def _axis_accuracy(self, learner):
        return {a: learner.accuracy(self.cohort.truth, [a]) for a in AXES}

    def step(self):
        """Play one week for every strategy. -> {strategy: what happened this week}."""
        if self.done:
            raise RuntimeError(f"the semester is over: it ends after week {self.weeks}")
        self.week += 1
        week, c = self.week, self.cohort
        news = {}
        for tr in self.tracks.values():
            self.current = tr.name             # for progress messages while a slow (LLM) week runs
            res = self.world.simulate(tr.groups, week, np.random.default_rng([self.seed, week]), tr.state, track=tr.name)
            grouped = {s for m in tr.groups.values() for s in m}
            true_all = [res.utility[s] if s in grouped else NO_GROUP_UTILITY for s in c.students]
            answered = [fb for fb in res.feedback if fb.responded]
            row = {
                "week": week,
                "true_satisfaction": float(np.mean(true_all)),
                "unhappy_share": float(np.mean([u < 3 for u in true_all])),
                "reported_satisfaction": float(np.mean([fb.satisfaction for fb in answered])) if answered else None,
                "response_rate": len(answered) / len(res.feedback) if res.feedback else None,
                "attendance": sum(fb.meetings_attended for fb in answered)
                              / max(1, sum(fb.meetings_per_week for fb in answered)) if answered else None,
                "left": sum(fb.left_group for fb in res.feedback),
                "without_group": len(c.students) - len(grouped),
                "profile_accuracy": tr.learner.accuracy(c.truth),
                "reliability_accuracy": tr.learner.accuracy(c.truth, ["reliability"]),
            }
            decision, counts = None, {}
            if tr.name == "stay":
                left = {fb.sid for fb in res.feedback if fb.left_group}
                new_groups = {g: [s for s in m if s not in left] for g, m in tr.groups.items()}
                new_groups = {g: m for g, m in new_groups.items() if m}
                moved = set()
                counts = {"quit": len(left)}
            else:
                tr.learner.observe(tr.groups, res.feedback, res.ratings, week)
                decision = tr.learner.retune(week)
                update_strikes(tr.strikes, res.feedback)
                if self.done:          # the last week: nothing left to regroup for
                    new_groups, moved = tr.groups, set()
                    counts = {"quit": row["left"]}
                else:
                    new_groups, moved, counts = reassign(tr.groups, res.feedback, tr.learner, c.students, week,
                                                         np.random.default_rng([self.seed, week, 7]), self.policy,
                                                         tr.strikes)
            row["moved_after"] = len(moved)
            tr.rows.append(row)
            tr.weights.append(dict(tr.learner.weights))
            tr.accuracy.append(self._axis_accuracy(tr.learner))
            if decision:
                tr.log.append(decision)
            if self.record:
                tr.trace.append({
                    "groups": tr.groups,
                    "utility": {s: res.utility[s] for s in grouped},
                    "feedback": [asdict(fb) for fb in res.feedback],
                    "moved": sorted(moved),
                    "profile": {s: dict(p) for s, p in tr.learner.profile.items()} if tr.name == "learn" else None,
                    "detail": res.detail,
                    "decision": decision,
                    "counts": counts,
                    "world": res.stats,
                    "group_detail": res.groups,
                })
            news[tr.name] = {"row": row, "decision": decision, "counts": counts, "world": res.stats}
            tr.state = res.state
            tr.groups = new_groups
        self.current = None
        return news
