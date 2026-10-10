"""
What the matching side knows and learns. It never sees the hidden truth:
only survey answers, schedules, and the Feedback / PeerRating the world returns.

  profile    working 6-axis profile per student, starting at the survey.
             - reliability (from reliability ratings) and collaboration (from
               helpfulness ratings): survey and peer ratings are two noisy
               readings of the same trait, combined by how noisy each is.
               The survey's noise comes from how consistently its 4 items on
               that axis agree (Cronbach's alpha over the whole cohort); the
               ratings' noise and scale come from how they relate to the
               survey each round. Ratings are lenient and partly about
               attendance, so they're never taken at face value.
             - the other 4 axes: complaint tags ("structure:more" = wanted
               the group more structured) nudge the profile past the group's
               average on that axis
  weights    the live axis weights plus a schedule weight that starts at 0
             (live matching ignores schedules); refit each round from every
             answered form so far: which gaps went with low satisfaction
  avoid      pairs someone asked not to be grouped with again

learn=False keeps the survey answers and hand-set weights (the control).
"""

import numpy as np
from scipy.optimize import nnls

from algorithm.compatibility import AXIS_RANGE, AXIS_WEIGHTS
from algorithm.scoring import AXES, ITEMS_BY_AXIS, reverse_code

FEATURES = list(AXES) + ["schedule"]
PEER_AXES = {"reliability": "reliability", "collaboration": "helpfulness"}
NUDGE = 0.5
TAG_MARGIN = 0.3
BLEND = 0.5
WEIGHT_TOTAL = sum(AXIS_WEIGHTS.values())


def cronbach_alpha(students, axis):
    """Internal consistency of the survey's items on one axis, over everyone."""
    items = ITEMS_BY_AXIS[axis]
    X = np.array([[reverse_code(st.items[it["id"]]) if it["reverse"] else st.items[it["id"]] for it in items]
                  for st in students.values()], dtype=float)
    k = X.shape[1]
    return float(k / (k - 1) * (1 - X.var(axis=0, ddof=1).sum() / X.sum(axis=1).var(ddof=1)))


class Learner:
    def __init__(self, students, courses, learn=True):
        self.students = students
        self.courses = courses
        self.learn = learn
        self.profile = {s: dict(st.survey) for s, st in students.items()}
        self.weights = {**AXIS_WEIGHTS, "schedule": 0.0}
        self.avoid = set()
        self._rows = []
        # Per peer-rated axis: survey mean, true-score variance, survey noise variance.
        self._prior = {}
        for a in PEER_AXES:
            x = np.array([st.survey[a] for st in students.values()])
            alpha = cronbach_alpha(students, a)
            self._prior[a] = (x.mean(), alpha * x.var(), (1 - alpha) * x.var())
        self._peer_prec = {s: {a: 0.0 for a in PEER_AXES} for s in students}
        self._peer_sum = {s: {a: 0.0 for a in PEER_AXES} for s in students}

    def score_matrix(self, course_id):
        """0-100 pair scores for every student pair in the course, in Course.ids order."""
        course = self.courses[course_id]
        P = np.array([[self.profile[s][a] for a in AXES] for s in course.ids])
        w = np.array([self.weights[a] for a in AXES])
        closeness = 1 - np.abs(P[:, None, :] - P[None, :, :]) / AXIS_RANGE
        S = 100 * ((closeness * w).sum(axis=2) + self.weights["schedule"] * course.fit) / sum(self.weights.values())
        for pair in self.avoid:
            a, b = tuple(pair)
            if a in course.index and b in course.index:
                S[course.index[a], course.index[b]] = S[course.index[b], course.index[a]] = 0.0
        np.fill_diagonal(S, 0.0)
        return S

    def _fit(self, a, b):
        course = self.courses[self.students[a].course]
        return course.fit[course.index[a], course.index[b]]

    def update(self, groups, feedback, ratings):
        if not self.learn:
            return
        for fb in feedback:
            mates = [m for m in groups[fb.group_id] if m != fb.sid]
            if fb.responded and mates:
                p = self.profile[fb.sid]
                row = [np.mean([abs(p[a] - self.profile[m][a]) / AXIS_RANGE for m in mates]) for a in AXES]
                row.append(1 - np.mean([self._fit(fb.sid, m) for m in mates]))
                self._rows.append((row, 5 - fb.satisfaction))

        self._learn_from_peers(ratings)

        for fb in feedback:
            mates = [m for m in groups[fb.group_id] if m != fb.sid]
            for tag in fb.tags:
                axis, _, direction = tag.partition(":")
                if axis not in AXES or axis in PEER_AXES or not mates:
                    continue
                group_mean = np.mean([self.profile[m][axis] for m in mates])
                p = self.profile[fb.sid]
                if direction == "more" and p[axis] < group_mean + TAG_MARGIN:
                    p[axis] += NUDGE * (min(group_mean + TAG_MARGIN, 5.0) - p[axis])
                elif direction == "less" and p[axis] > group_mean - TAG_MARGIN:
                    p[axis] += NUDGE * (max(group_mean - TAG_MARGIN, 1.0) - p[axis])
            for other in fb.avoid:
                self.avoid.add(frozenset((fb.sid, other)))

        self._refit_weights()

    def _learn_from_peers(self, ratings):
        """Treat this round's mean received rating y as y = c + b * trait + noise.
        b and the noise come from how y co-varies with the survey: the survey's
        own noise is known from alpha, so cov(survey, y) = b * true variance."""
        received = {}
        for r in ratings:
            received.setdefault(r.ratee, []).append(r)
        if len(received) < 30:
            return
        for axis, field in PEER_AXES.items():
            mu, var_t, var_survey = self._prior[axis]
            ids = sorted(received)
            x = np.array([self.students[s].survey[axis] for s in ids])
            y = np.array([np.mean([getattr(r, field) for r in received[s]]) for s in ids])
            b = np.cov(x, y)[0, 1] / var_t
            if b <= 0:
                continue
            var_noise = max(y.var(ddof=1) - b * b * var_t, 0.05 * y.var(ddof=1))
            c = y.mean() - b * x.mean()
            for s, ys in zip(ids, y):
                self._peer_prec[s][axis] += b * b / var_noise
                self._peer_sum[s][axis] += (ys - c) / b * (b * b / var_noise)
        for s in self.students:
            for axis in PEER_AXES:
                mu, var_t, var_survey = self._prior[axis]
                prec = 1 / var_t + 1 / var_survey + self._peer_prec[s][axis]
                self.profile[s][axis] = float(np.clip(
                    (mu / var_t + self.students[s].survey[axis] / var_survey + self._peer_sum[s][axis]) / prec, 1, 5))

    def _refit_weights(self):
        if len(self._rows) < 5 * len(FEATURES):
            return
        X = np.array([r for r, _ in self._rows])
        y = np.array([d for _, d in self._rows])
        beta, _ = nnls(np.hstack([X, np.ones((len(X), 1))]), y)
        beta = beta[:-1]
        if beta.sum() <= 0:
            return
        fitted = beta * WEIGHT_TOTAL / beta.sum()
        for x, f in zip(FEATURES, fitted):
            self.weights[x] = BLEND * f + (1 - BLEND) * self.weights[x]
        scale = WEIGHT_TOTAL / sum(self.weights.values())
        self.weights = {x: w * scale for x, w in self.weights.items()}

    def accuracy(self, truth, axes=AXES):
        """Mean correlation between working and true profiles across the given axes.
        Correlation, not error: matching uses differences between people, so a
        uniform offset (the survey's flattering bias) doesn't matter."""
        ids = sorted(self.profile)
        return float(np.mean([np.corrcoef([self.profile[s][a] for s in ids], [truth[s].axes[a] for s in ids])[0, 1]
                              for a in axes]))
