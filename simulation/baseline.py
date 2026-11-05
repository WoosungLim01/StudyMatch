"""
Random-grouping baseline: how much better StudyMatch's group formation is
than forming groups at random, over a whole simulated semester.

    python -m simulation.baseline                # 10 seeds x 14 weeks
    python -m simulation.baseline --seeds 20

Strategies, on the same cohort with the same weekly chance events per seed:
  random        random groups of the semester-start sizes, never changed
                (people who quit stay without a group)
  random_redo   random groups, and the pipeline's own regrouping rule (who
                quit, who said "I'd switch") still runs, but places people
                at random
  matched       StudyMatch's survey matching once, never changed
  studymatch    the full pipeline: matching plus the feedback loop
                (semester.py's "learn")

random_redo vs studymatch is the cleanest comparison: identical feedback
and regrouping rule, only how groups are formed differs. Writes
simulation/output/baseline.json.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from simulation.learner import Learner
from simulation.policy import Policy
from simulation.population import load_cohort
from simulation.semester import Cohort, Semester
from simulation.world import SEMESTER_WEEKS, RuleWorld

OUTPUT = Path(__file__).resolve().parent / "output"
NAMES = {"random": "Random groups, never changed",
         "random_redo": "Random groups, unhappy re-randomised",
         "matched": "StudyMatch matching, never changed",
         "studymatch": "StudyMatch pipeline (matching + feedback loop)"}


class RandomScores(Learner):
    """Never learns, and scores every pair at random, so whoever it places lands at random."""

    def __init__(self, students, courses, seed):
        super().__init__(students, courses, learn=False)
        self._rng = np.random.default_rng(seed)

    def score_matrix(self, course_id):
        n = len(self.courses[course_id].ids)
        R = self._rng.random((n, n)) * 100
        S = (R + R.T) / 2
        np.fill_diagonal(S, 0.0)
        return S


def random_start(cohort, seed):
    """The same number and sizes of groups per course as the matched start, filled at random."""
    rng = np.random.default_rng([seed, 4242])
    groups = {}
    for course in sorted(cohort.courses):
        sizes = [len(m) for g, m in sorted(cohort.start_groups.items()) if cohort.students[m[0]].course == course]
        pool = [str(s) for s in rng.permutation(sorted(s for s in cohort.students if cohort.students[s].course == course))]
        for i, n in enumerate(sizes):
            groups[f"rand_{course.split('-')[1]}_{i:03d}"], pool = pool[:n], pool[n:]
    return Cohort(cohort.students, cohort.truth, groups, cohort.courses)


def run_seed(cohort, world, seed, weeks, policy):
    """-> {strategy: weekly rows} for one seed."""
    rand = Semester(random_start(cohort, seed), world, strategies=("stay", "survey"), policy=policy,
                    weeks=weeks, record=False)
    rand.reset(seed)
    rand.tracks["survey"].learner = RandomScores(cohort.students, cohort.courses, [seed, 99])
    matched = Semester(cohort, world, strategies=("stay", "learn"), policy=policy, weeks=weeks, record=False)
    matched.reset(seed)
    for sem in (rand, matched):
        while not sem.done:
            sem.step()
    return {"random": rand.tracks["stay"].rows, "random_redo": rand.tracks["survey"].rows,
            "matched": matched.tracks["stay"].rows, "studymatch": matched.tracks["learn"].rows}


def per_seed_summary(rows):
    return {
        "week1_satisfaction": rows[0]["true_satisfaction"],
        "semester_satisfaction": float(np.mean([r["true_satisfaction"] for r in rows])),
        "final_satisfaction": rows[-1]["true_satisfaction"],
        "final_unhappy": rows[-1]["unhappy_share"],
        "average_unhappy": float(np.mean([r["unhappy_share"] for r in rows])),
        "quits": float(sum(r["left"] for r in rows)),
        "final_without_group": rows[-1]["without_group"],
        "moves": float(sum(r["moved_after"] for r in rows)),
    }


def paired(a, b):
    """Mean of a - b across seeds, its standard error, and how many seeds a beat b."""
    d = np.array(a) - np.array(b)
    se = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else 0.0
    return {"diff": float(d.mean()), "se": se, "t": float(d.mean() / se) if se else None,
            "wins": int((d > 0).sum()), "seeds": len(d)}


def main():
    parser = argparse.ArgumentParser(description="StudyMatch vs random grouping over a simulated semester")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--weeks", type=int, default=SEMESTER_WEEKS)
    args = parser.parse_args()
    policy = Policy()

    students, truth, start_groups, courses = load_cohort()
    cohort = Cohort(students, truth, start_groups, courses)
    world = RuleWorld(students, truth, courses)
    print(f"{len(students)} students, {args.seeds} seeds x {args.weeks} weeks; regrouping rule: {policy.label()}\n")

    runs = []
    for seed in range(args.seeds):
        runs.append(run_seed(cohort, world, seed, args.weeks, policy))
        print(f"  seed {seed} done")

    seeds = {s: [per_seed_summary(run[s]) for run in runs] for s in NAMES}
    summary = {s: {k: float(np.mean([x[k] for x in seeds[s]])) for k in seeds[s][0]} for s in NAMES}
    weekly = {s: [{k: float(np.mean([run[s][w][k] for run in runs])) for k in ("true_satisfaction", "unhappy_share")}
                  | {"week": w + 1} for w in range(args.weeks)] for s in NAMES}

    def compare(a, b, key):
        return paired([x[key] for x in seeds[a]], [x[key] for x in seeds[b]])

    comparisons = {
        f"studymatch vs {base}": {k: compare("studymatch", base, k)
                                  for k in ("week1_satisfaction", "semester_satisfaction", "final_satisfaction")}
        | {"final_unhappy": paired([x["final_unhappy"] for x in seeds[base]], [x["final_unhappy"] for x in seeds["studymatch"]])}
        for base in ("random", "random_redo")
    }
    comparisons["matched vs random"] = {k: compare("matched", "random", k)
                                        for k in ("week1_satisfaction", "semester_satisfaction", "final_satisfaction")}

    print(f"\n{'strategy':<48} {'week 1':>7} {'semester':>9} {'week ' + str(args.weeks):>8} {'unhappy':>8} "
          f"{'quits':>6} {'moves':>6}")
    for s, label in NAMES.items():
        x = summary[s]
        print(f"{label:<48} {x['week1_satisfaction']:>7.2f} {x['semester_satisfaction']:>9.2f} "
              f"{x['final_satisfaction']:>8.2f} {x['final_unhappy']:>7.0%} {x['quits']:>6.1f} {x['moves']:>6.0f}")
    print()
    for name, comp in comparisons.items():
        for k, c in comp.items():
            print(f"{name:<28} {k:<22} {c['diff']:+.3f} (SE {c['se']:.3f}, better in {c['wins']}/{c['seeds']} seeds)")

    OUTPUT.mkdir(exist_ok=True)
    out = OUTPUT / "baseline.json"
    out.write_text(json.dumps({"generated": datetime.now().isoformat(timespec="seconds"), "seeds": args.seeds,
                               "weeks": args.weeks, "policy": policy.label(), "names": NAMES, "summary": summary,
                               "weekly": weekly, "comparisons": comparisons}, indent=2))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
