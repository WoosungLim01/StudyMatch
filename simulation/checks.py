"""
Sanity checks to pass before trusting anything run.py says.

    python -m simulation.checks

Each check plays the first CHECK_WEEKS weeks with groups held fixed (anyone who
quits just leaves), over SEEDS seeds.
Behaviour:
  - matched groups beat random groups of the same sizes
  - reliable students are happier with reliable groupmates than flaky ones
  - the same groups do worse if nobody's schedules overlap
Realism of those weeks with the semester-start groups (ranges are judgement
calls for voluntary study groups, not measured data):
  - weekly pulse response rate, attendance, reported satisfaction, share truly
    unhappy, leaving, would-match-again, lenient peer ratings, chat activity
Cohort:
  - survey vs truth correlation per axis, unique names, none of the 36 app students

Also writes simulation/output/checks.json for the dashboard.
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

from algorithm.scoring import AXES
from simulation.population import load_cohort
from simulation.world import CHECKIN_EVERY, RuleWorld

SEEDS = 10
CHECK_WEEKS = CHECKIN_EVERY            # through the first check-in, so peer ratings are included
OUTPUT = Path(__file__).resolve().parent / "output"
results = []


def check(section, label, ok, detail, sides=None, **numbers):
    """sides and numbers are what the dashboard needs to draw the check: the two
    things compared, or a value and its expected range."""
    results.append({"section": section, "label": label, "ok": bool(ok), "detail": detail, "sides": sides,
                    **{k: float(v) for k, v in numbers.items()}})
    print(f"{'PASS' if ok else 'FAIL'} {label}: {detail}")


def play(world, groups, seed, weeks=CHECK_WEEKS):
    """Run fixed groups for some weeks; people who quit drop out. -> one WeekResult per week."""
    groups = {g: list(m) for g, m in groups.items()}
    state, out = {}, []
    for week in range(1, weeks + 1):
        res = world.simulate(groups, week, np.random.default_rng([seed, week]), state)
        out.append(res)
        left = {fb.sid for fb in res.feedback if fb.left_group}
        groups = {g: [s for s in m if s not in left] for g, m in groups.items()}
        groups = {g: m for g, m in groups.items() if m}
        state = res.state
    return out


def random_groups(groups, students, rng):
    out = {}
    for course in sorted({students[m[0]].course for m in groups.values()}):
        sizes = [len(m) for g, m in sorted(groups.items()) if students[m[0]].course == course]
        pool = list(rng.permutation(sorted(s for s in students if students[s].course == course)))
        for i, n in enumerate(sizes):
            out[f"rand_{course}_{i}"] = [str(x) for x in pool[:n]]
            pool = pool[n:]
    return out


def end_satisfaction(weeks, members=None):
    """Mean satisfaction at the end, for everyone who was in a group (quitters keep their last value)."""
    last = {}
    for res in weeks:
        last.update(res.utility)
    return float(np.mean([last[s] for s in (members or last)]))


def main():
    students, truth, groups, courses = load_cohort()
    world = RuleWorld(students, truth, courses)
    flat = {c: type(courses[c])(courses[c].ids, courses[c].index, np.zeros_like(courses[c].fit)) for c in courses}
    course = sorted(courses)[0]
    by_rel = sorted(courses[course].ids, key=lambda s: truth[s].axes["reliability"])
    reliable, flaky = by_rel[-4:], by_rel[:2]

    matched, rand, mixed, solid, real_fit, no_fit, runs = [], [], [], [], [], [], []
    for seed in range(SEEDS):
        weeks = play(world, groups, seed)
        runs.append(weeks)
        matched.append(end_satisfaction(weeks))
        rand.append(end_satisfaction(play(world, random_groups(groups, students, np.random.default_rng(seed)), seed)))
        mixed.append(end_satisfaction(play(world, {"mixed": reliable[:2] + flaky}, seed + 100), reliable[:2]))
        solid.append(end_satisfaction(play(world, {"solid": reliable}, seed + 100), reliable[:2]))
        real_fit.append(matched[-1])
        no_fit.append(end_satisfaction(play(RuleWorld(students, truth, flat), groups, seed)))

    def better(label, a, b, sides):
        diff = np.array(a) - np.array(b)
        check("behaviour", label, diff.mean() > 0 and (diff > 0).mean() >= 0.8,
              f"{np.mean(a):.2f} vs {np.mean(b):.2f}, better in {(diff > 0).mean():.0%} of seeds", sides,
              value=np.mean(a), versus=np.mean(b), share=(diff > 0).mean())

    better("matched groups beat random groups", matched, rand,
           ["Matched groups", "Random groups of the same sizes"])
    better("reliable students prefer reliable groupmates", solid, mixed,
           ["Two reliable students with reliable groupmates", "The same two with flaky groupmates"])
    better("overlapping schedules beat no overlap", real_fit, no_fit,
           ["Real schedules", "Nobody's free hours overlap"])

    every = [f for weeks in runs for res in weeks for f in res.feedback]
    answered = [f for f in every if f.responded]
    checkins = [f for f in answered if f.checkin]
    at_end = [x for weeks in runs for x in weeks[-1].utility.values()]
    quit_share = np.mean([len({f.sid for res in weeks for f in res.feedback if f.left_group}) / len(students) for weeks in runs])

    def within(label, value, low, high, fmt="{:.0%}"):
        check("realism", label, low <= value <= high, f"{fmt.format(value)} (expected {fmt.format(low)}-{fmt.format(high)})",
              value=value, low=low, high=high, percent=float(fmt == "{:.0%}"))

    within("weekly pulse response rate", len(answered) / len(every), 0.45, 0.75)
    within("attendance", sum(f.meetings_attended for f in answered) / sum(f.meetings_per_week for f in answered), 0.62, 0.80)
    within("mean reported satisfaction", np.mean([f.satisfaction for f in answered]), 3.5, 4.2, "{:.2f}")
    within(f"truly unhappy share after week {CHECK_WEEKS}", np.mean([x < 3 for x in at_end]), 0.08, 0.30)
    within(f"quit within {CHECK_WEEKS} weeks", quit_share, 0.0, 0.05)
    within("would match again", np.mean([f.would_match_again for f in answered]), 0.75, 0.95)
    within("mean peer reliability rating (lenient)",
           np.mean([r.reliability for weeks in runs for res in weeks for r in res.ratings]), 3.6, 4.5, "{:.2f}")
    chat = Counter(f.chat_activity for f in checkins)
    top = max(chat.values()) / sum(chat.values())
    check("realism", "chat activity not dominated by one level", top <= 0.6,
          ", ".join(f"{k} {v / sum(chat.values()):.0%}" for k, v in sorted(chat.items())),
          value=top, low=0.0, high=0.6, percent=1.0)

    ids = sorted(students)
    corr = [np.corrcoef([students[s].survey[a] for s in ids], [truth[s].axes[a] for s in ids])[0, 1] for a in AXES]
    check("cohort", "survey tracks truth but imperfectly (r 0.65-0.90 per axis)", all(0.65 <= r <= 0.9 for r in corr),
          ", ".join(f"{a} {r:.2f}" for a, r in zip(AXES, corr)))
    names = [students[s].name for s in ids]
    check("cohort", "1000 students with unique names", len(ids) == 1000 and len(set(names)) == 1000,
          f"{len(ids)} students, {len(set(names))} names")
    check("cohort", "none of the 36 app students are in the cohort", not any(s.startswith("stu_") for s in ids),
          "ids start with c465_ / m230_")

    failures = sum(not r["ok"] for r in results)
    print(f"\n{failures} failure(s) of {len(results)}")
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / "checks.json").write_text(json.dumps(
        {"generated": datetime.now().isoformat(timespec="seconds"), "weeks": CHECK_WEEKS, "checks": results}, indent=2))


if __name__ == "__main__":
    main()
