"""
Run the semester experiment on the 1000-student cohort: every strategy, one
week at a time, for several seeds (semester.py has the strategies).

    python -m simulation.run                    # 10 seeds x 14 weeks, rule-based world
    python -m simulation.run --seeds 20 --weeks 12
    python -m simulation.run --cadence 4        # move unhappy students every 4 weeks
    python -m simulation.run --world llm-1.2 --sample 50 --seeds 2   # LLM world, 100 students

The cohort's hidden truth is fixed; a seed changes only the world's
randomness (who shows up, who answers the form...). Writes to simulation/output/
(LLM worlds: simulation/output/llm/, so the rule-based results stay):
  report.json          averages, every seed's numbers, the learner's path and
                       its tuning decisions (seed 0)
  feedback_seed0.csv   every answered form from seed 0 (group_feedback's
                       columns plus a few the app doesn't have yet)
  trace_seed0.json     seed 0 in full: groups, true satisfaction, feedback and
                       the learner's working profiles, week by week
  dashboard.html       all of the above as an interactive page (dashboard.py)

An LLM world needs the simulation's own Python environment; this command
switches to it by itself when simulation/.venv exists.
"""

import argparse
import csv
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from simulation import dashboard
from simulation.calibration import SCHEDULE_PRIOR, SENSITIVITY_PRIOR
from simulation.learner import FEATURES
from simulation.llm_world import SAMPLES, ensure_llm_python
from simulation.policy import Policy
from simulation.population import load_cohort
from simulation.semester import METRICS, STRATEGIES, Cohort, Semester
from simulation.world import SEMESTER_WEEKS, RuleWorld

OUTPUT = Path(__file__).resolve().parent / "output"
SEMESTER_START = date(2026, 8, 24)


WORLD_KINDS = {"llm": "the LLM judges each week", "meet": "the LLM plays the meetings, then judges"}


def make_world(name, cohort, samples=SAMPLES, budget=None):
    """'rule'; 'llm-<clamp>' (Claude judges each week); 'meet-<clamp>' (Claude also writes what
    happened at each meeting). Clamp: 1.2, 0.3 or none. Raises ValueError for anything else."""
    if name == "rule":
        return RuleWorld(cohort.students, cohort.truth, cohort.courses)
    kind, _, clamp = name.partition("-")
    if kind not in WORLD_KINDS or clamp not in ("1.2", "0.3", "none"):
        raise ValueError(f"unknown world {name!r}: use rule, llm-1.2, llm-0.3, llm-none, meet-1.2, meet-0.3 or meet-none")
    if kind == "meet":
        from simulation.meeting_world import MeetingWorld as cls
    else:
        from simulation.llm_world import LLMWorld as cls
    return cls(cohort.students, cohort.truth, cohort.courses, clamp=None if clamp == "none" else float(clamp),
               samples=samples, budget=budget)


def plain(x):
    """json.dumps fallback for numpy scalars."""
    if isinstance(x, np.generic):
        return x.item()
    raise TypeError(f"{type(x).__name__} is not JSON serializable")


def form_rows(strategy, trace):
    """Every answered form of one strategy, in group_feedback's columns."""
    rows = []
    for rec in trace:
        for fb in rec["feedback"]:
            if not fb["responded"]:
                continue
            stamp = (SEMESTER_START + timedelta(weeks=fb["week"])).isoformat()
            rows.append({
                "strategy": strategy, "week": fb["week"], "group_id": fb["group_id"], "student_id": fb["sid"],
                "satisfaction_score": fb["satisfaction"], "meetings_attended": fb["meetings_attended"],
                "meetings_per_week": fb["meetings_per_week"], "weeks_in_group": fb["weeks_in_group"],
                "left_group": int(fb["left_group"]), "would_match_again": int(fb["would_match_again"]),
                "perceived_personality_fit": fb["perceived_fit"], "group_productivity": fb["productivity"],
                "group_chat_activity": fb["chat_activity"],
                "peer_helpfulness_rating": None if fb["peer_helpfulness"] is None else round(fb["peer_helpfulness"]),
                "peer_reliability_rating": None if fb["peer_reliability"] is None else round(fb["peer_reliability"]),
                "timestamp": stamp, "tags": ";".join(fb["tags"]), "avoid": ";".join(fb["avoid"]),
            })
    return rows


def report_of(runs, policy, gate, world_name, weeks, samples=None):
    """Seed averages and every seed's numbers from finished Semesters (runs[0] is kept in full)."""
    names = list(runs[0].tracks)

    def mean_of(values):
        values = [v for v in values if v is not None]
        return float(np.mean(values)) if values else None

    summary = {s: [{k: mean_of([run.tracks[s].rows[w][k] for run in runs]) for k in METRICS} | {"week": w + 1}
                   for w in range(weeks)] for s in names}

    def mean_path(s, key):
        paths = [getattr(run.tracks[s], key) for run in runs]
        return [{x: float(np.mean([p[step][x] for p in paths])) for x in paths[0][step]} for step in range(weeks + 1)]

    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "world": world_name, "samples": samples if world_name != "rule" else None,
        "seeds": len(runs), "weeks": weeks, "max_weeks": SEMESTER_WEEKS,
        "students": len(runs[0].cohort.students),
        "policy": asdict(policy) | {"label": policy.label()}, "gate": gate,
        "summary": summary,
        "per_seed": {s: [[{k: row[k] for k in METRICS} for row in run.tracks[s].rows] for run in runs] for s in names},
        "learner_path": {s: {"weights": mean_path(s, "weights"), "accuracy": mean_path(s, "accuracy")} for s in names},
        "learned_weights": mean_path("learn", "weights")[-1] if "learn" in names else None,
        "learner_log": runs[0].tracks["learn"].log if "learn" in names else [],
    }


def main():
    parser = argparse.ArgumentParser(description="StudyMatch weekly semester simulation")
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--weeks", type=int, default=SEMESTER_WEEKS, help=f"1 to {SEMESTER_WEEKS}")
    parser.add_argument("--cadence", type=int, default=Policy().cadence, help="move unhappy students every N weeks; 0 = never")
    parser.add_argument("--strikes", type=int, default=Policy().strikes)
    parser.add_argument("--no-gate", action="store_true", help="adopt every weekly refit without the held-out check")
    parser.add_argument("--world", default="rule", help="rule (default); llm-1.2, llm-0.3, llm-none; meet-1.2, meet-0.3, meet-none")
    parser.add_argument("--sample", type=int, default=0, help="students per course (whole start groups); 0 = everyone")
    parser.add_argument("--samples", type=int, default=SAMPLES, help="LLM world: asks per group per week, averaged")
    parser.add_argument("--budget", type=float, default=5.0, help="LLM world: stop spending at this many dollars")
    parser.add_argument("--out", default=None, help="subfolder of simulation/output to write to (LLM worlds: llm)")
    args = parser.parse_args()
    policy = Policy(cadence=args.cadence or None, strikes=args.strikes)
    llm = args.world != "rule"
    if llm:
        ensure_llm_python("simulation.run", required=True)
    default_dir = "meetings" if args.world.startswith("meet-") else "llm"
    out_dir = OUTPUT / args.out if args.out else OUTPUT / default_dir if llm else OUTPUT

    cohort = Cohort(*load_cohort())
    if args.sample:
        cohort = cohort.sample(args.sample)
    try:
        world = make_world(args.world, cohort, samples=args.samples, budget=args.budget)
    except (ValueError, RuntimeError) as e:    # an unknown world, a missing key, an old SDK
        raise SystemExit(str(e))
    students, start_groups = cohort.students, cohort.start_groups
    print(f"{len(students)} students in {len(start_groups)} groups, {args.seeds} seeds x {args.weeks} weeks; "
          f"world: {args.world}{f', {args.samples} asks per group' if llm else ''}; policy: {policy.label()}\n")
    runs = []
    for seed in range(args.seeds):
        sem = Semester(cohort, world, policy=policy, gate=not args.no_gate, weeks=args.weeks, record=(seed == 0))
        sem.reset(seed)
        while not sem.done:
            sem.step()
            if llm:
                print(f"  seed {seed} week {sem.week:>2}: {world.calls} calls so far ({world.cached} from cache, "
                      f"{world.failed} failed), ${world.spent:.2f} spent", flush=True)
        runs.append(sem)
        if llm and world.budget_hit:
            print(f"budget of ${args.budget:.2f} reached: later groups were judged by the rule world", flush=True)
            break

    report = report_of(runs, policy, not args.no_gate, args.world, args.weeks, samples=args.samples)
    if llm:
        report["llm"] = {"calls": world.calls, "cached": world.cached, "failed": world.failed, "skipped": world.skipped,
                         "spent": round(world.spent, 4), "budget_hit": world.budget_hit, "halted": world.halted}

    # Write first, print after: a summary that can't be formatted must never lose the run.
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, default=plain))
    trace = {s: tr.trace for s, tr in runs[0].tracks.items()}
    rows = [r for s in STRATEGIES for r in form_rows(s, trace[s])]
    with open(out_dir / "feedback_seed0.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / "trace_seed0.json").write_text(json.dumps(trace, separators=(",", ":"), default=plain))

    cell = lambda v, spec: f"{'-':>{spec.split('.')[0].lstrip('>')}}" if v is None else format(v, spec)
    print(f"{'week':>4} {'strategy':<8} {'true sat':>8} {'unhappy':>8} {'reported':>8} {'answered':>8} "
          f"{'attend':>7} {'left':>5} {'no grp':>6} {'moved':>6} {'know all':>8} {'know rel':>8}")
    for w in range(args.weeks):
        for s in STRATEGIES:
            x = report["summary"][s][w]
            print(f"{w + 1:>4} {s:<8} {cell(x['true_satisfaction'], '>8.2f')} {cell(x['unhappy_share'], '>7.0%')} "
                  f"{cell(x['reported_satisfaction'], '>8.2f')} {cell(x['response_rate'], '>7.0%')} {cell(x['attendance'], '>7.0%')} "
                  f"{cell(x['left'], '>5.1f')} {cell(x['without_group'], '>6.1f')} {cell(x['moved_after'], '>6.1f')} "
                  f"{cell(x['profile_accuracy'], '>8.3f')} {cell(x['reliability_accuracy'], '>8.3f')}")
        if w % 2 == 1 or w == args.weeks - 1:
            print()
    for s in STRATEGIES:
        avg = np.mean([r["true_satisfaction"] for r in report["summary"][s] if r["true_satisfaction"] is not None])
        print(f"semester-average true satisfaction, {s:<6}: {avg:.3f}")
    hidden = {**SENSITIVITY_PRIOR, "schedule": SCHEDULE_PRIOR}
    print("\nlearned weights at the end, next to the hidden average sensitivity:")
    for x in FEATURES:
        print(f"  {x:<14} learned {report['learned_weights'][x]:5.2f}   hidden {hidden[x]:4.2f}")
    print("\nseed 0 tuning decisions:", ", ".join(f"w{e['week']} {e['action']}" for e in report["learner_log"]))
    if llm:
        print(f"\nLLM: {world.calls} calls, {world.cached} answers from cache, {world.failed} failed, "
              f"{world.skipped} skipped, ${world.spent:.2f} spent")
        if world.halted or world.skipped:
            print(f"WARNING: {world.halted or 'budget reached'}: {world.skipped} asks were never made and those groups "
                  f"got the rule verdict, so this is NOT a pure {args.world} result")
    rel = out_dir.relative_to(OUTPUT.parent.parent).as_posix()
    print(f"\nwrote {rel}/report.json, feedback_seed0.csv ({len(rows)} forms) and trace_seed0.json")
    print(f"dashboard: {dashboard.build(out_dir)}")


if __name__ == "__main__":
    main()
