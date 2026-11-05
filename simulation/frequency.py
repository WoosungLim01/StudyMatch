"""
How often should matching change? Runs the "learn" strategy under every
combination of:

  cadence    move unhappy students every 1, 2 or 4 weeks, or never (people
             who quit are always placed again the same week)
  patience   move after 1 or 2 "I'd rather switch" answers in a row
  tuning     adopt every weekly refit, or only refits that pass the held-out
             check and stop once they stop helping (learner.retune)

    python -m simulation.frequency              # 6 seeds, rule-based world, about 6 minutes
    python -m simulation.frequency --seeds 10

The score is the semester-average true satisfaction: every student, every
week, students without a group counted as 2.0. It rewards fixing bad groups
early and penalises churn, because a new group starts over and a move costs
the weeks a group needed to settle. Settings within TIE of the best (or
within two standard errors, whichever is wider) are treated as tied, and the
tie goes to the one that moves the fewest students: no change without
evidence it helps.

Writes simulation/output/frequency.json, which the dashboard shows.
"""

import argparse
import itertools
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from simulation.policy import Policy
from simulation.population import load_cohort
from simulation.semester import Cohort, Semester
from simulation.world import SEMESTER_WEEKS, RuleWorld

OUTPUT = Path(__file__).resolve().parent / "output"
CADENCES = (1, 2, 4, None)
TIE = 0.02                             # satisfaction points: about a tenth of what regrouping gains at all
PATIENCE = (1, 2)
TUNING = (True, False)


def score(track, n):
    rows = track.rows
    return {
        "semester_satisfaction": float(np.mean([r["true_satisfaction"] for r in rows])),
        "final_unhappy": rows[-1]["unhappy_share"],
        "average_unhappy": float(np.mean([r["unhappy_share"] for r in rows])),
        "moves_per_student": sum(r["moved_after"] for r in rows) / n,
        "quits": sum(r["left"] for r in rows),
        "tuning_stopped": next((e["week"] for e in track.log if e["action"] == "froze"), None),
    }


def main():
    parser = argparse.ArgumentParser(description="How often to regroup and retune")
    parser.add_argument("--seeds", type=int, default=6)
    args = parser.parse_args()
    students, truth, start_groups, courses = load_cohort()
    cohort = Cohort(students, truth, start_groups, courses)
    world = RuleWorld(students, truth, courses)
    n = len(students)

    reference = {}
    for name in ("stay", "survey"):
        runs = []
        for seed in range(args.seeds):
            sem = Semester(cohort, world, strategies=(name,), policy=Policy(), record=False)
            sem.reset(seed)
            while not sem.done:
                sem.step()
            runs.append(score(sem.tracks[name], n))
        reference[name] = runs

    results = []
    for cadence, strikes, gate in itertools.product(CADENCES, PATIENCE, TUNING):
        if cadence is None and strikes == 2:
            continue                   # patience doesn't matter if nobody is ever moved for being unhappy
        policy = Policy(cadence=cadence, strikes=strikes)
        runs = []
        for seed in range(args.seeds):
            sem = Semester(cohort, world, strategies=("learn",), policy=policy, gate=gate, record=False)
            sem.reset(seed)
            while not sem.done:
                sem.step()
            runs.append(score(sem.tracks["learn"], n))
        results.append({"cadence": cadence, "strikes": strikes, "gate": gate, "label": policy.label(), "runs": runs})
        r = runs
        print(f"cadence {str(cadence):>4}  strikes {strikes}  {'checked' if gate else 'weekly '} tuning: "
              f"semester sat {np.mean([x['semester_satisfaction'] for x in r]):.3f}  "
              f"final unhappy {np.mean([x['final_unhappy'] for x in r]):.1%}  "
              f"moves/student {np.mean([x['moves_per_student'] for x in r]):.2f}", flush=True)

    # Paired across seeds (every setting sees the same chance events per seed), so differences are measured tightly.
    sat = np.array([[x["semester_satisfaction"] for x in res["runs"]] for res in results])
    best = int(np.argmax(sat.mean(axis=1)))
    for k, res in enumerate(results):
        diff = sat[k] - sat[best]
        se = float(diff.std(ddof=1) / np.sqrt(len(diff))) if k != best else 0.0
        res.update({key: float(np.mean([x[key] for x in res["runs"]])) for key in res["runs"][0] if key != "tuning_stopped"})
        stops = [x["tuning_stopped"] for x in res["runs"] if x["tuning_stopped"]]
        res["tuning_stopped"] = float(np.mean(stops)) if stops else None
        res["gap_to_best"], res["gap_se"] = float(diff.mean()), se
        res["tied_with_best"] = bool(k == best or abs(diff.mean()) <= max(2 * se, TIE))
    tied = [res for res in results if res["tied_with_best"]]
    pick = min(tied, key=lambda r: (r["moves_per_student"], -r["semester_satisfaction"]))
    for res in results:
        res["recommended"] = res is pick

    ref = {name: {key: float(np.mean([x[key] for x in runs])) for key in runs[0] if key != "tuning_stopped"}
           for name, runs in reference.items()}
    print(f"\nbest score: {results[best]['label']}, {'checked' if results[best]['gate'] else 'weekly'} tuning")
    print(f"recommended (tied with the best, fewest moves): {pick['label']}, "
          f"{'checked' if pick['gate'] else 'weekly'} tuning")
    print(f"for reference, semester sat: stay {ref['stay']['semester_satisfaction']:.3f}, "
          f"survey (default policy) {ref['survey']['semester_satisfaction']:.3f}")
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / "frequency.json").write_text(json.dumps({
        "generated": datetime.now().isoformat(timespec="seconds"), "seeds": args.seeds, "weeks": SEMESTER_WEEKS,
        "tie": TIE, "default": {"cadence": Policy().cadence, "strikes": Policy().strikes},
        "results": [{k: v for k, v in res.items() if k != "runs"} for res in results],
        "reference": ref,
    }, indent=2))


if __name__ == "__main__":
    main()
