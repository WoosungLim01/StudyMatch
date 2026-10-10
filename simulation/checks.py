"""
Sanity checks to pass before trusting anything run.py says.

    python -m simulation.checks

Behaviour (averaged over seeds):
  - matched groups beat random groups of the same sizes
  - reliable students are happier with reliable groupmates than flaky ones
  - the same groups do worse if nobody's schedules overlap
Realism of one period with the semester-start groups (ranges are judgement
calls for voluntary study groups, not measured data):
  - form response rate, attendance, reported satisfaction, share truly
    unhappy, leaving, would-match-again, lenient peer ratings, chat activity
Cohort:
  - survey vs truth correlation per axis, unique names, none of the 36 app students
"""

from collections import Counter

import numpy as np

from algorithm.scoring import AXES
from simulation.population import load_cohort
from simulation.world import RuleWorld

SEEDS = 10
results = []


def check(label, ok, detail):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} {label}: {detail}")


def random_groups(groups, students, rng):
    out = {}
    for course in sorted({students[m[0]].course for m in groups.values()}):
        sizes = [len(m) for g, m in sorted(groups.items()) if students[m[0]].course == course]
        pool = list(rng.permutation(sorted(s for s in students if students[s].course == course)))
        for i, n in enumerate(sizes):
            out[f"rand_{course}_{i}"] = [str(x) for x in pool[:n]]
            pool = pool[n:]
    return out


def main():
    students, truth, groups, courses = load_cohort()
    world = RuleWorld(students, truth, courses)

    matched, rand, mixed, solid, real_fit, no_fit = [], [], [], [], [], []
    rounds = []
    flat = {c: type(courses[c])(courses[c].ids, courses[c].index, np.zeros_like(courses[c].fit)) for c in courses}
    course = sorted(courses)[0]
    by_rel = sorted(courses[course].ids, key=lambda s: truth[s].axes["reliability"])
    reliable, flaky = by_rel[-4:], by_rel[:2]
    for seed in range(SEEDS):
        fb, pr, u = world.simulate(groups, 0, np.random.default_rng([seed, 0]))
        rounds.append((fb, pr, u))
        matched.append(np.mean(list(u.values())))
        _, _, ur = world.simulate(random_groups(groups, students, np.random.default_rng(seed)), 0, np.random.default_rng([seed, 0]))
        rand.append(np.mean(list(ur.values())))
        _, _, um = world.simulate({"mixed": reliable[:2] + flaky}, 0, np.random.default_rng([seed, 1]))
        _, _, us = world.simulate({"solid": reliable}, 0, np.random.default_rng([seed, 1]))
        mixed.append(np.mean([um[s] for s in reliable[:2]]))
        solid.append(np.mean([us[s] for s in reliable[:2]]))
        _, _, uf = RuleWorld(students, truth, flat).simulate(groups, 0, np.random.default_rng([seed, 0]))
        real_fit.append(np.mean(list(u.values())))
        no_fit.append(np.mean(list(uf.values())))

    def better(label, a, b):
        diff = np.array(a) - np.array(b)
        check(label, diff.mean() > 0 and (diff > 0).mean() >= 0.8,
              f"{np.mean(a):.2f} vs {np.mean(b):.2f}, better in {(diff > 0).mean():.0%} of seeds")

    better("matched groups beat random groups", matched, rand)
    better("reliable students prefer reliable groupmates", solid, mixed)
    better("overlapping schedules beat no overlap", real_fit, no_fit)

    answered = [f for fb, _, _ in rounds for f in fb if f.responded]
    every = [f for fb, _, _ in rounds for f in fb]
    utils = [x for _, _, u in rounds for x in u.values()]

    def within(label, value, low, high, fmt="{:.0%}"):
        check(label, low <= value <= high, f"{fmt.format(value)} (expected {fmt.format(low)}-{fmt.format(high)})")

    within("form response rate", len(answered) / len(every), 0.65, 0.85)
    within("attendance", sum(f.meetings_attended for f in answered) / sum(f.meetings_per_week * f.weeks_in_group for f in answered), 0.62, 0.80)
    within("mean reported satisfaction", np.mean([f.satisfaction for f in answered]), 3.5, 4.1, "{:.2f}")
    within("truly unhappy share", np.mean([x < 3 for x in utils]), 0.08, 0.30)
    within("left within 4 weeks", np.mean([f.left_group for f in every]), 0.0, 0.05)
    within("would match again", np.mean([f.would_match_again for f in answered]), 0.75, 0.95)
    within("mean peer reliability rating (lenient)", np.mean([r.reliability for _, pr, _ in rounds for r in pr]), 3.6, 4.5, "{:.2f}")
    chat = Counter(f.chat_activity for f in answered)
    top = max(chat.values()) / sum(chat.values())
    check("chat activity not dominated by one level", top <= 0.6,
          ", ".join(f"{k} {v / sum(chat.values()):.0%}" for k, v in sorted(chat.items())))

    ids = sorted(students)
    corr = [np.corrcoef([students[s].survey[a] for s in ids], [truth[s].axes[a] for s in ids])[0, 1] for a in AXES]
    check("survey tracks truth but imperfectly (r 0.65-0.90 per axis)", all(0.65 <= r <= 0.9 for r in corr),
          ", ".join(f"{a} {r:.2f}" for a, r in zip(AXES, corr)))
    names = [students[s].name for s in ids]
    check("1000 students with unique names", len(ids) == 1000 and len(set(names)) == 1000, f"{len(ids)} students, {len(set(names))} names")
    check("none of the 36 app students are in the cohort", not any(s.startswith("stu_") for s in ids), "ids start with c465_ / m230_")

    print(f"\n{results.count(False)} failure(s) of {len(results)}")


if __name__ == "__main__":
    main()
