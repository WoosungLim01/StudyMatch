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
               survey each check-in. Ratings are lenient and partly about
               attendance, so they're never taken at face value.
             - the other 4 axes: complaint tags ("structure:more" = wanted
               the group more structured) nudge the profile past the group's
               average on that axis
  weights    the live axis weights plus a schedule weight that starts at 0
             (live matching ignores schedules)
  avoid      pairs someone asked not to be grouped with again

observe() takes in a week's feedback: profiles and pairs to avoid update
every week, because that's evidence about people and doesn't oscillate.

retune() is the final call on whether the weights change. Feedback is noisy
and no group is perfect, so a refit is adopted only when it predicts this
week's forms (which it hasn't seen) better than the current weights by more
than chance: the per-form improvement must be at least SIGNIFICANCE standard
errors above zero, and at least MIN_GAIN in size. After FREEZE_AFTER checks
in a row that fail, the weights are frozen: tuning has reached the point
where changes are just noise. Freezing is lifted if the average reported
satisfaction falls ALARM_DROP below where it was when they froze.
gate=False refits and adopts every week, which frequency.py compares against.

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
MIN_ROWS = 5 * len(FEATURES)           # answered forms before the first refit
MIN_TEST = 20                          # forms this week needed to judge a refit
MIN_GAIN = 0.005                       # held-out error must drop at least 0.5% ...
SIGNIFICANCE = 2.0                     # ... and by at least 2 standard errors (paired, per form)
FREEZE_AFTER = 3
ALARM_DROP = 0.3


def cronbach_alpha(students, axis):
    """Internal consistency of the survey's items on one axis, over everyone."""
    items = ITEMS_BY_AXIS[axis]
    X = np.array([[reverse_code(st.items[it["id"]]) if it["reverse"] else st.items[it["id"]] for it in items]
                  for st in students.values()], dtype=float)
    k = X.shape[1]
    return float(k / (k - 1) * (1 - X.var(axis=0, ddof=1).sum() / X.sum(axis=1).var(ddof=1)))


class Learner:
    def __init__(self, students, courses, learn=True, gate=True):
        self.students = students
        self.courses = courses
        self.learn = learn
        self.gate = gate
        self.profile = {s: dict(st.survey) for s, st in students.items()}
        self.weights = {**AXIS_WEIGHTS, "schedule": 0.0}
        self.avoid = set()
        self.frozen = False
        self._misses = 0
        self._frozen_at = None
        self._rows = []                # (features, 5 - reported satisfaction, week)
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
        # Students outside this run (a sampled cohort) get a placeholder row; they're never in a pool.
        P = np.array([[self.profile[s][a] for a in AXES] if s in self.profile else [3.0] * len(AXES) for s in course.ids])
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

    def observe(self, groups, feedback, ratings, week):
        """Take in one week's forms and peer ratings."""
        if not self.learn:
            return
        for fb in feedback:
            mates = [m for m in groups[fb.group_id] if m != fb.sid]
            if fb.responded and mates:
                p = self.profile[fb.sid]
                row = [np.mean([abs(p[a] - self.profile[m][a]) / AXIS_RANGE for m in mates]) for a in AXES]
                row.append(1 - np.mean([self._fit(fb.sid, m) for m in mates]))
                self._rows.append((row, 5 - fb.satisfaction, week))

        if ratings:
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

    def retune(self, week):
        """Decide whether this week's feedback changes the weights. -> a log entry, or None for the control."""
        if not self.learn:
            return None
        train = [(x, y) for x, y, w in self._rows if w < week]
        test = [(x, y) for x, y, w in self._rows if w == week]
        level = 5 - float(np.mean([y for _, y in test])) if test else None

        def entry(action, text, gain=None):
            return {"week": week, "action": action, "text": text, "gain": gain,
                    "weights": dict(self.weights), "forms": len(train) + len(test)}

        if self.frozen:
            if level is not None and level <= self._frozen_at - ALARM_DROP:
                self.frozen, self._misses = False, 0
                note = (f"Reported satisfaction fell to {level:.2f}, {self._frozen_at - level:.2f} below where it was "
                        "when tuning stopped, so tuning resumes.")
                return entry("unfrozen", note)
            return entry("frozen", "Weights stay as they are: recent refits didn't predict feedback any better.")
        if len(train) < MIN_ROWS or len(test) < MIN_TEST:
            return entry("waiting", f"Not enough feedback yet ({len(train) + len(test)} forms).")

        proposal = self._refit(train)
        if proposal is None:
            return entry("kept", "The refit found no pattern in the feedback.")
        if not self.gate:
            self.weights = proposal
            return entry("adopted", "Refit adopted (every week, no check).")
        before = self._heldout_errors(self.weights, train, test)
        after = self._heldout_errors(proposal, train, test)
        gain = 1 - after.mean() / before.mean() if before.mean() > 0 else 0.0
        d = before - after
        z = d.mean() / (d.std(ddof=1) / np.sqrt(len(d))) if d.std(ddof=1) > 0 else 0.0
        if gain >= MIN_GAIN and z >= SIGNIFICANCE:
            self.weights, self._misses = proposal, 0
            return entry("adopted", f"The refit predicts this week's {len(test)} forms {gain:.1%} better, "
                                    f"well beyond chance ({z:.1f} standard errors), so it's adopted.", gain)
        self._misses += 1
        if self._misses >= FREEZE_AFTER:
            self.frozen, self._frozen_at = True, level
            return entry("froze", f"No real improvement {FREEZE_AFTER} weeks in a row ({gain:+.1%} this week): "
                                  "the weights are settled, so tuning stops.", gain)
        return entry("kept", f"The refit would predict this week's forms {gain:+.1%} better, which is within "
                             f"chance ({z:.1f} standard errors), so the weights stay.", gain)

    def _refit(self, rows):
        """Which gaps went with low satisfaction (NNLS), blended into the current weights."""
        X = np.array([r for r, _ in rows])
        y = np.array([d for _, d in rows])
        beta, _ = nnls(np.hstack([X, np.ones((len(X), 1))]), y)
        beta = beta[:-1]
        if beta.sum() <= 0:
            return None
        fitted = beta * WEIGHT_TOTAL / beta.sum()
        blended = {x: BLEND * f + (1 - BLEND) * self.weights[x] for x, f in zip(FEATURES, fitted)}
        scale = WEIGHT_TOTAL / sum(blended.values())
        return {x: v * scale for x, v in blended.items()}

    @staticmethod
    def _heldout_errors(weights, train, test):
        """Squared error per test row of discomfort ~ a + b * (gaps . weights), a and b fit on train."""
        w = np.array([weights[x] for x in FEATURES])
        Xtr, ytr = np.array([r for r, _ in train]), np.array([d for _, d in train])
        Xte, yte = np.array([r for r, _ in test]), np.array([d for _, d in test])
        A = np.column_stack([np.ones(len(Xtr)), Xtr @ w])
        coef, *_ = np.linalg.lstsq(A, ytr, rcond=None)
        pred = coef[0] + coef[1] * (Xte @ w)
        return (yte - pred) ** 2

    def _learn_from_peers(self, ratings):
        """Treat this check-in's mean received rating y as y = c + b * trait + noise.
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

    def accuracy(self, truth, axes=AXES):
        """Mean correlation between working and true profiles across the given axes.
        Correlation, not error: matching uses differences between people, so a
        uniform offset (the survey's flattering bias) doesn't matter."""
        ids = sorted(self.profile)
        return float(np.mean([np.corrcoef([self.profile[s][a] for s in ids], [truth[s].axes[a] for s in ids])[0, 1]
                              for a in axes]))
