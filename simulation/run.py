"""
Run the multi-round experiment on the 1000-student cohort.

    python -m simulation.run                 # 10 seeds x 4 rounds (a 16-week semester)
    python -m simulation.run --seeds 20

Strategies, all starting from the cohort's semester-start groups:
  stay     never reassign (people who leave stay without a group)
  survey   reassign the unhappy, scoring with survey answers and hand-set
           weights only: feedback decides who moves, not where
  learn    same reassignment, but scores use what feedback taught the
           Learner (peer-rated reliability, complaint tags, refit weights,
           pairs to avoid)

The cohort's hidden truth is fixed; a seed changes only the world's
randomness (who shows up, who answers the form...). Within a seed every
strategy sees the same randomness each round, so differences come from the
strategy. Writes simulation/output/report.json, and every feedback form from
seed 0 to simulation/output/feedback_seed0.csv (group_feedback's columns
plus a few the app doesn't have yet: tags, avoid).
"""

import argparse
import csv
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from simulation.calibration import SCHEDULE_PRIOR, SENSITIVITY_PRIOR
from simulation.learner import FEATURES, Learner
from simulation.policy import reassign
from simulation.population import load_cohort
from simulation.world import NO_GROUP_UTILITY, WEEKS_PER_PERIOD, RuleWorld

STRATEGIES = ("stay", "survey", "learn")
OUTPUT = Path(__file__).resolve().parent / "output"
SEMESTER_START = date(2026, 8, 24)
METRICS = ["true_satisfaction", "unhappy_share", "reported_satisfaction", "response_rate", "attendance",
           "left", "without_group", "moved_after", "profile_accuracy", "reliability_accuracy"]


def run_strategy(strategy, students, truth, start_groups, courses, seed, rounds, csv_rows=None):
    world = RuleWorld(students, truth, courses)
    learner = Learner(students, courses, learn=(strategy == "learn"))
    groups = {g: list(m) for g, m in start_groups.items()}
    history, carry = [], {}
    for period in range(rounds):
        feedback, ratings, utility = world.simulate(groups, period, np.random.default_rng([seed, period]), carry)
        carry = {fb.sid: (fb.group_id, utility[fb.sid]) for fb in feedback}
        grouped = {s for m in groups.values() for s in m}
        true_all = [utility[s] if s in grouped else NO_GROUP_UTILITY for s in students]
        answered = [fb for fb in feedback if fb.responded]
        row = {
            "round": period + 1,
            "true_satisfaction": float(np.mean(true_all)),
            "unhappy_share": float(np.mean([u < 3 for u in true_all])),
            "reported_satisfaction": float(np.mean([fb.satisfaction for fb in answered])),
            "response_rate": len(answered) / len(feedback),
            "attendance": sum(fb.meetings_attended for fb in answered)
                          / max(1, sum(fb.meetings_per_week * fb.weeks_in_group for fb in answered)),
            "left": sum(fb.left_group for fb in feedback),
            "without_group": len(students) - len(grouped),
            "profile_accuracy": learner.accuracy(truth),
            "reliability_accuracy": learner.accuracy(truth, ["reliability"]),
        }
        if csv_rows is not None:
            stamp = (SEMESTER_START + timedelta(weeks=WEEKS_PER_PERIOD * (period + 1))).isoformat()
            for fb in answered:
                csv_rows.append({
                    "strategy": strategy, "round": period + 1, "group_id": fb.group_id, "student_id": fb.sid,
                    "satisfaction_score": fb.satisfaction, "meetings_attended": fb.meetings_attended,
                    "meetings_per_week": fb.meetings_per_week, "weeks_in_group": fb.weeks_in_group,
                    "left_group": int(fb.left_group), "would_match_again": int(fb.would_match_again),
                    "perceived_personality_fit": fb.perceived_fit, "group_productivity": fb.productivity,
                    "group_chat_activity": fb.chat_activity,
                    "peer_helpfulness_rating": None if fb.peer_helpfulness is None else round(fb.peer_helpfulness),
                    "peer_reliability_rating": None if fb.peer_reliability is None else round(fb.peer_reliability),
                    "timestamp": stamp, "tags": ";".join(fb.tags), "avoid": ";".join(fb.avoid),
                })
        if strategy == "stay":
            left = {fb.sid for fb in feedback if fb.left_group}
            new_groups = {g: [s for s in m if s not in left] for g, m in groups.items()}
            new_groups = {g: m for g, m in new_groups.items() if m}
            moved = left
        else:
            learner.update(groups, feedback, ratings)
            new_groups, moved = reassign(groups, feedback, learner, students, period + 1,
                                         np.random.default_rng([seed, period, 7]))
        row["moved_after"] = len(moved)
        history.append(row)
        groups = new_groups
    return history, dict(learner.weights)


def main():
    parser = argparse.ArgumentParser(description="StudyMatch multi-round simulation")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=4)
    args = parser.parse_args()

    students, truth, start_groups, courses = load_cohort()
    print(f"{len(students)} students in {len(start_groups)} groups, {args.seeds} seeds x {args.rounds} rounds\n")
    results = {s: [] for s in STRATEGIES}
    learned, csv_rows = [], []
    for seed in range(args.seeds):
        for strategy in STRATEGIES:
            history, weights = run_strategy(strategy, students, truth, start_groups, courses, seed, args.rounds,
                                            csv_rows if seed == 0 else None)
            results[strategy].append(history)
            if strategy == "learn":
                learned.append(weights)

    summary = {s: [{k: float(np.mean([run[r][k] for run in results[s]])) for k in METRICS} | {"round": r + 1}
                   for r in range(args.rounds)] for s in STRATEGIES}
    print(f"{'rnd':>3} {'strategy':<8} {'true sat':>8} {'unhappy':>8} {'reported':>8} {'answered':>8} "
          f"{'attend':>7} {'left':>5} {'no grp':>6} {'moved':>6} {'know all':>8} {'know rel':>8}")
    for r in range(args.rounds):
        for s in STRATEGIES:
            x = summary[s][r]
            print(f"{r + 1:>3} {s:<8} {x['true_satisfaction']:>8.2f} {x['unhappy_share']:>7.0%} "
                  f"{x['reported_satisfaction']:>8.2f} {x['response_rate']:>7.0%} {x['attendance']:>7.0%} "
                  f"{x['left']:>5.0f} {x['without_group']:>6.0f} {x['moved_after']:>6.0f} "
                  f"{x['profile_accuracy']:>8.3f} {x['reliability_accuracy']:>8.3f}")
        print()

    mean_weights = {x: float(np.mean([w[x] for w in learned])) for x in FEATURES}
    hidden = {**SENSITIVITY_PRIOR, "schedule": SCHEDULE_PRIOR}
    print("learned weights after the last round, next to the hidden average sensitivity:")
    for x in FEATURES:
        print(f"  {x:<14} learned {mean_weights[x]:5.2f}   hidden {hidden[x]:4.2f}")

    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / "report.json").write_text(json.dumps(
        {"seeds": args.seeds, "rounds": args.rounds, "summary": summary, "learned_weights": mean_weights}, indent=2))
    with open(OUTPUT / "feedback_seed0.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"\nwrote simulation/output/report.json and feedback_seed0.csv ({len(csv_rows)} forms)")


if __name__ == "__main__":
    main()
