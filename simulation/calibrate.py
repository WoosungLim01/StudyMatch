"""
Validate the LLM world before trusting it.

    python -m simulation.calibrate              # switches to simulation/.venv by itself

Two rounds of probes:

Week 1, every group, one ask (cached from the first validation, so free):
the model's raw answers scored as four versions of the world:
  rule        the rule world alone, the reference
  clamp 0.3   the model's answer, held within 0.3 of the rule world's
  clamp 1.2   held within 1.2 (IdeaLab's 0.30 on its 0-1 scale)
  no clamp    the model's own answer
  matched     all semester-start groups
  random      random groups of the same sizes                        should be worse
  no overlap  half the matched groups, nobody's free hours overlap   should be worse
  flaky       reliable students with reliable vs flaky groupmates    reliable mates better
  repeat      half the matched groups asked again                    how much one ask wobbles
  relabel     the same groups with the letters reversed              shouldn't wobble more than a repeat

Four weeks, the world as the live page runs it (clamp 1.2, several asks per
group averaged), on a 100-student sample with groups held fixed: feelings
have time to build up, which one week can't show. The same three behaviour
probes, next to the rule world on the same weeks, plus: how far the model
drifts from the rules by week, how often the clamp bound, and how much the
averaged answers wobble (from the spread between asks).

Pass marks are judgement calls, written next to each test. Writes
simulation/output/calibration.json, which the dashboard shows. About 900
calls the first time (under $1); cached afterwards.
"""

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

from simulation.checks import end_satisfaction, play, random_groups
from simulation.llm_world import CLAMP, EFFORT, MODEL, SAMPLES, Ledger, LLMWorld, ensure_llm_python
from simulation.population import load_cohort
from simulation.semester import Cohort
from simulation.world import TAGS, RuleWorld

OUTPUT = Path(__file__).resolve().parent / "output"
VERSIONS = {"rule": 0.0, "clamp 0.3": 0.3, "clamp 1.2": 1.2, "no clamp": None}
WEEK, SEED = 1, 0
LONG_WEEKS = 4
SAMPLE = 50                            # students per course for the four-week probes


def scored(res):
    """Each student's satisfaction under every version, from one LLM-world week with no clamp."""
    out = {v: {} for v in VERSIONS}
    for s, d in res.detail.items():
        rule, raw = d["rule"], d["raw"] if d["raw"] is not None else d["rule"]
        for v, width in VERSIONS.items():
            out[v][s] = raw if width is None else float(np.clip(raw, rule - width, rule + width))
    return out


def welch(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float((a.mean() - b.mean()) / se) if se > 0 else 0.0


def paired(a, b):
    d = np.asarray(a, float) - np.asarray(b, float)
    se = d.std(ddof=1) / np.sqrt(len(d))
    return float(d.mean() / se) if se > 0 else 0.0


def group_means(sat, groups):
    """One number per group: the mean over its members that have a value. Groups are the unit of
    every test, because one call judges a whole group and its members' answers move together."""
    return [np.mean([sat[s] for s in m if s in sat]) for m in groups.values() if any(s in sat for s in m)]


def finite(x):
    """A float, or None when it isn't a number (an empty correlation), so the JSON stays valid."""
    return float(x) if x is not None and np.isfinite(x) else None


def complaints(feedback):
    tags = Counter(t for fb in feedback for t in fb.tags)
    total = sum(tags.values()) or 1
    return [{"code": t, "label": TAGS[t], "share": n / total} for t, n in tags.most_common()]


def flat_courses(courses):
    return {c: type(courses[c])(courses[c].ids, courses[c].index, np.zeros_like(courses[c].fit)) for c in courses}


def reliable_probe_groups(courses, truth):
    """Pairs of very reliable students, each put once with reliable groupmates and once with flaky ones."""
    solid, mixed, anchors = {}, {}, []
    for c in sorted(courses):
        by_rel = sorted(courses[c].ids, key=lambda s: truth[s].axes["reliability"])
        top, bottom = by_rel[::-1][:28], by_rel[:14]
        for k in range(7):
            pair = top[2 * k:2 * k + 2]
            anchors += pair
            solid[f"solid_{c}_{k}"] = pair + top[14 + 2 * k:16 + 2 * k]
            mixed[f"mixed_{c}_{k}"] = pair + bottom[2 * k:2 * k + 2]
    return solid, mixed, anchors


def week_one(students, truth, courses, groups, ledger):
    """The first validation: one ask per group in week 1, scored four ways."""
    make = lambda **kw: LLMWorld(students, truth, kw.pop("courses", courses), clamp=None, samples=1, ledger=ledger, **kw)
    llm = make()
    rng = lambda: np.random.default_rng([SEED, WEEK])
    half = {g: groups[g] for g in sorted(groups)[::2]}
    print("week 1: matched groups...", flush=True)
    matched = llm.simulate(groups, WEEK, rng())
    print("week 1: random groups...", flush=True)
    shuffled = random_groups(groups, students, np.random.default_rng(SEED))
    rand = llm.simulate(shuffled, WEEK, rng())
    print("week 1: no schedule overlap...", flush=True)
    no_overlap_world = make(courses=flat_courses(courses))
    no_overlap = no_overlap_world.simulate(half, WEEK, rng())
    print("week 1: reliable vs flaky groupmates...", flush=True)
    solid_groups, mixed_groups, anchors = reliable_probe_groups(courses, truth)
    solid = llm.simulate(solid_groups, WEEK, rng())
    mixed = llm.simulate(mixed_groups, WEEK, rng())
    print("week 1: asking again, and with the letters reversed...", flush=True)
    repeat_world, relabel_world = make(nonce="repeat"), make(order="reversed")
    repeat = repeat_world.simulate(half, WEEK, rng())
    relabel = relabel_world.simulate(half, WEEK, rng())
    worlds = [llm, no_overlap_world, repeat_world, relabel_world]

    S = {name: scored(res) for name, res in [("matched", matched), ("random", rand), ("no_overlap", no_overlap),
                                             ("solid", solid), ("mixed", mixed)]}
    half_ids = sorted(s for m in half.values() for s in m)
    tests = []
    for v in VERSIONS:
        m, r = S["matched"][v], S["random"][v]
        solid_anchor = {s: S["solid"][v][s] for s in anchors}
        mixed_anchor = {s: S["mixed"][v][s] for s in anchors}
        row = {
            "matched_mean": float(np.mean(list(m.values()))),
            "random_mean": float(np.mean(list(r.values()))),
            "matched_vs_random_t": welch(group_means(m, groups), group_means(r, shuffled)),
            "solid_mean": float(np.mean(list(solid_anchor.values()))),
            "mixed_mean": float(np.mean(list(mixed_anchor.values()))),
            "solid_vs_mixed_t": paired(group_means(solid_anchor, solid_groups), group_means(mixed_anchor, mixed_groups)),
            "overlap_mean": float(np.mean([m[s] for s in half_ids])),
            "no_overlap_mean": float(np.mean([S["no_overlap"][v][s] for s in half_ids])),
            "overlap_t": paired(group_means(m, half), group_means(S["no_overlap"][v], half)),
            "unhappy_share": float(np.mean([x < 3 for x in m.values()])),
        }
        row["passes"] = {
            "matched groups beat random ones": row["matched_vs_random_t"] >= 2,
            "reliable students prefer reliable groupmates": row["solid_vs_mixed_t"] >= 2,
            "overlapping schedules beat none": row["overlap_t"] >= 2,
            "plausible first week (2-25% unhappy)": 0.02 <= row["unhappy_share"] <= 0.25,
        }
        tests.append({"version": v} | row)

    raw = {s: d["raw"] for s, d in matched.detail.items() if d["raw"] is not None}
    rule = {s: matched.detail[s]["rule"] for s in raw}
    ids = sorted(raw)
    wobble = lambda res: float(np.mean([abs(res.detail[s]["raw"] - matched.detail[s]["raw"]) for s in half_ids
                                         if res.detail.get(s, {}).get("raw") is not None and matched.detail[s]["raw"] is not None]))
    repeat_wobble, relabel_wobble = wobble(repeat), wobble(relabel)
    gap = np.array([raw[s] - rule[s] for s in ids])
    rule_week = RuleWorld(students, truth, courses).simulate(groups, WEEK, rng())
    model = {
        "correlation_with_rule": finite(np.corrcoef([raw[s] for s in ids], [rule[s] for s in ids])[0, 1]) if len(ids) > 1 else None,
        "mean_offset": float(gap.mean()),
        "mean_abs_gap": float(np.abs(gap).mean()),
        "binds_at": {str(w): float(np.mean(np.abs(gap) > w)) for w in (0.3, 0.6, 1.2)},
        "repeat_wobble": repeat_wobble,
        "relabel_wobble": relabel_wobble,
        "passes": {
            "stable when asked again (average change under 0.25)": repeat_wobble <= 0.25,
            "letters don't matter (no more wobble than a repeat)": relabel_wobble <= 1.5 * repeat_wobble + 0.05,
        },
        "complaints_llm": complaints(matched.feedback),
        "complaints_rule": complaints(rule_week.feedback),
        "notes": [{"sid": s, "rule": matched.detail[s]["rule"], "raw": matched.detail[s]["raw"], "note": matched.detail[s]["note"]}
                  for s in sorted(ids, key=lambda s: raw[s] - rule[s])[::max(1, len(ids) // 8)][:8]],
    }
    return tests, model, worlds


def four_weeks(cohort, courses, truth, samples, ledger, world_cls=LLMWorld):
    """Fixed groups for LONG_WEEKS weeks on the sample, an LLM world as the live page runs it, next to the rule world."""
    small = cohort.sample(SAMPLE)
    students = small.students
    make = lambda **kw: world_cls(students, truth, kw.pop("courses", courses), clamp=CLAMP, samples=samples, ledger=ledger, **kw)
    rule_of = lambda cs=courses: RuleWorld(students, truth, cs)
    llm = make()
    worlds = [llm]
    groups = small.start_groups
    runs = {}
    print(f"{LONG_WEEKS} weeks: matched groups ({len(groups)} groups, {samples} asks each)...", flush=True)
    runs["matched"] = (play(llm, groups, SEED, LONG_WEEKS), play(rule_of(), groups, SEED, LONG_WEEKS))
    print(f"{LONG_WEEKS} weeks: random groups...", flush=True)
    shuffled = random_groups(groups, students, np.random.default_rng(SEED))
    runs["random"] = (play(llm, shuffled, SEED, LONG_WEEKS), play(rule_of(), shuffled, SEED, LONG_WEEKS))
    print(f"{LONG_WEEKS} weeks: no schedule overlap...", flush=True)
    flat = flat_courses(courses)
    no_overlap_world = make(courses=flat)
    worlds.append(no_overlap_world)
    runs["no_overlap"] = (play(no_overlap_world, groups, SEED, LONG_WEEKS), play(rule_of(flat), groups, SEED, LONG_WEEKS))
    print(f"{LONG_WEEKS} weeks: reliable vs flaky groupmates...", flush=True)
    solid_groups, mixed_groups, anchors = reliable_probe_groups(courses, truth)
    full_llm = world_cls(cohort.students, truth, courses, clamp=CLAMP, samples=samples, ledger=ledger)
    full_rule = RuleWorld(cohort.students, truth, courses)
    worlds.append(full_llm)
    runs["solid"] = (play(full_llm, solid_groups, SEED + 100, LONG_WEEKS), play(full_rule, solid_groups, SEED + 100, LONG_WEEKS))
    runs["mixed"] = (play(full_llm, mixed_groups, SEED + 100, LONG_WEEKS), play(full_rule, mixed_groups, SEED + 100, LONG_WEEKS))

    def ends(weeks, members=None):
        """Satisfaction at the end for everyone who was grouped (quitters keep their last value)."""
        last = {}
        for res in weeks:
            last.update(res.utility)
        return {s: last[s] for s in (members or last)}

    tests = []
    for k, version in enumerate(["rule", "llm"]):
        pick = lambda name: ends(runs[name][1 - k])
        m, r, n = pick("matched"), pick("random"), pick("no_overlap")
        so, mi = ends(runs["solid"][1 - k], anchors), ends(runs["mixed"][1 - k], anchors)
        ids = sorted(set(m) & set(n))
        row = {
            "matched_mean": float(np.mean(list(m.values()))), "random_mean": float(np.mean(list(r.values()))),
            "matched_vs_random_t": welch(group_means(m, groups), group_means(r, shuffled)),
            "overlap_mean": float(np.mean([m[s] for s in ids])), "no_overlap_mean": float(np.mean([n[s] for s in ids])),
            "overlap_t": paired(group_means(m, groups), group_means(n, groups)),
            "solid_mean": float(np.mean(list(so.values()))), "mixed_mean": float(np.mean(list(mi.values()))),
            "solid_vs_mixed_t": paired(group_means(so, solid_groups), group_means(mi, mixed_groups)),
            "unhappy_share": float(np.mean([x < 3 for x in m.values()])),
        }
        row["passes"] = {
            "matched groups beat random ones": row["matched_vs_random_t"] >= 2,
            "reliable students prefer reliable groupmates": row["solid_vs_mixed_t"] >= 2,
            "overlapping schedules beat none": row["overlap_t"] >= 2,
            f"plausible week {LONG_WEEKS} (5-35% unhappy)": 0.05 <= row["unhappy_share"] <= 0.35,
        }
        tests.append({"version": version} | row)

    # Drift, clamp binding and wobble from the matched run, every student-week with LLM answers. "rule_world" is
    # the independent rule-world run; "rule_same_state" is the rule formula applied to the LLM-driven state.
    llm_weeks, rule_weeks = runs["matched"]
    by_week, gaps, bound, spreads, pair_diffs = [], [], 0, [], []
    skipped = fallback = 0
    for res, rres in zip(llm_weeks, rule_weeks):
        judged = [(s, d) for s, d in res.detail.items() if d.get("raw") is not None]
        by_week.append({"llm": float(np.mean([res.utility[s] for s, _ in judged])) if judged else None,
                        "llm_raw": float(np.mean([d["raw"] for _, d in judged])) if judged else None,
                        "rule_same_state": float(np.mean([d["rule"] for _, d in judged])) if judged else None,
                        "rule_world": float(np.mean(list(rres.utility.values()))) if rres.utility else None})
        for s, d in judged:
            gaps.append(d["raw"] - d["rule"])
    for probe_weeks, _ in runs.values():       # every probe: a skipped ask anywhere mixes the two worlds
        for res in probe_weeks:
            skipped += res.stats.get("skipped", 0)
            fallback += res.stats.get("fallback", 0)
            bound += bool(d.get("clamped"))
            asks = d.get("asks") or []
            if len(asks) >= 2:
                spreads.append(max(asks) - min(asks))
                pair_diffs += [abs(a - b) for i, a in enumerate(asks) for b in asks[i + 1:]]
    gaps = np.array(gaps)
    single = float(np.mean(pair_diffs)) if pair_diffs else None
    averaged = single / np.sqrt(samples) if single is not None else None
    correlation = finite(np.corrcoef([d["raw"] for res in llm_weeks for d in res.detail.values() if d.get("raw") is not None],
                                     [d["rule"] for res in llm_weeks for d in res.detail.values() if d.get("raw") is not None])[0, 1]) if len(gaps) > 1 else None
    return {
        "world": "meeting" if world_cls is not LLMWorld else "llm",
        "weeks": LONG_WEEKS, "clamp": CLAMP, "samples": samples, "students": len(students), "groups": len(groups),
        "tests": tests, "by_week": by_week,
        "correlation_with_rule": correlation,
        "mean_offset": float(gaps.mean()) if len(gaps) else None,
        "mean_abs_gap": float(np.abs(gaps).mean()) if len(gaps) else None,
        "clamp_bound_share": bound / max(1, len(gaps)),
        "ask_spread": float(np.mean(spreads)) if spreads else None,
        "wobble_single": single,
        "wobble_averaged": averaged,
        "judged": int(len(gaps)), "asks_skipped": int(skipped), "groups_judged_by_rules": int(fallback),
        "reliable": bool(len(gaps) and not skipped and not fallback),
        "passes": {
            f"averaged answers stable (expected change under 0.2 with {samples} asks)": bool(averaged is not None and averaged <= 0.2),
            "clamp rarely binds (under 10% of verdicts)": bool(len(gaps) and bound / len(gaps) < 0.10),
        },
        "complaints_llm": complaints([fb for res in llm_weeks for fb in res.feedback]),
        "complaints_rule": complaints([fb for res in rule_weeks for fb in res.feedback]),
    }, worlds


def print_rows(rows):
    print(f"{'version':<10} {'matched':>8} {'random':>7} {'t':>6} {'solid':>6} {'mixed':>6} {'t':>6} "
          f"{'overlap':>8} {'none':>6} {'t':>6} {'unhappy':>8}  passes")
    for row in rows:
        print(f"{row['version']:<10} {row['matched_mean']:>8.2f} {row['random_mean']:>7.2f} {row['matched_vs_random_t']:>6.1f} "
              f"{row['solid_mean']:>6.2f} {row['mixed_mean']:>6.2f} {row['solid_vs_mixed_t']:>6.1f} "
              f"{row['overlap_mean']:>8.2f} {row['no_overlap_mean']:>6.2f} {row['overlap_t']:>6.1f} "
              f"{row['unhappy_share']:>7.0%}  {sum(row['passes'].values())}/{len(row['passes'])}")


def print_long(long):
    fmt = lambda v, f="{:.2f}": "n/a" if v is None else f.format(v)
    print(f"\nafter {long['weeks']} weeks, {long['world']} world, clamp {long['clamp']}, {long['samples']} asks per group, "
          f"{long['students']} students")
    print_rows(long["tests"])
    print(f"model vs rule: r = {fmt(long['correlation_with_rule'])}, offset {fmt(long['mean_offset'], '{:+.2f}')}; clamp bound for "
          f"{long['clamp_bound_share']:.1%} of verdicts; asks spread {fmt(long['ask_spread'])} on average; "
          f"wobble one ask {fmt(long['wobble_single'])}, averaged {fmt(long['wobble_averaged'])}")
    print("by week, matched groups (LLM / rule world):", ", ".join(
        f"w{k + 1} {fmt(b['llm'])}/{fmt(b['rule_world'])}" for k, b in enumerate(long["by_week"])))
    print("model's top complaints:", ", ".join(f"{c['label']} {c['share']:.0%}" for c in long["complaints_llm"][:4]))
    print("rule's top complaints: ", ", ".join(f"{c['label']} {c['share']:.0%}" for c in long["complaints_rule"][:4]))


def main():
    parser = argparse.ArgumentParser(description="Validate the LLM worlds")
    parser.add_argument("--budget", type=float, default=3.0, help="stop spending at this many dollars")
    parser.add_argument("--samples", type=int, default=SAMPLES, help="asks per group in the four-week probes")
    parser.add_argument("--world", default="llm", choices=["llm", "meeting"],
                        help="llm: the week-1 probes and the four-week probes of the LLM judge (default); "
                             "meeting: the four-week probes of the world with simulated meetings")
    args = parser.parse_args()
    ensure_llm_python("simulation.calibrate", required=True)

    students, truth, groups, courses = load_cohort()
    cohort = Cohort(students, truth, groups, courses)
    OUTPUT.mkdir(exist_ok=True)
    path = OUTPUT / "calibration.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    stamp = datetime.now().isoformat(timespec="seconds")
    ledger = Ledger(args.budget)           # one cap for every world this run builds
    fmt = lambda v, spec=".2f": "n/a" if v is None else format(v, spec)
    model = None
    if args.world == "llm":
        tests, model, worlds = week_one(students, truth, courses, groups, ledger)
        long, more = four_weeks(cohort, courses, truth, args.samples, ledger, LLMWorld)
        worlds += more
        report.update({"generated": stamp, "model": MODEL, "effort": EFFORT, "week": WEEK,
                       "tests": tests, "model_vs_rule": model, "multiweek": long})
    else:
        from simulation.meeting_world import MeetingWorld

        long, worlds = four_weeks(cohort, courses, truth, args.samples, ledger, MeetingWorld)
        report["multiweek_meetings"] = long
    calls, spent, failed = sum(w.calls for w in worlds), sum(w.spent for w in worlds), sum(w.failed for w in worlds)
    long.update({"generated": stamp, "calls": calls, "spent": spent, "failed": failed, "budget_hit": ledger.hit})
    if args.world == "llm":
        report.update({"calls": calls, "failed": failed, "spent": spent})
    path.write_text(json.dumps(report, indent=2))     # written before the summary, so a print can't lose the run

    if model is not None:
        print("\nweek 1, one ask per group")
        print_rows(report["tests"])
        print(f"model vs rule world: r = {fmt(model['correlation_with_rule'])}, offset {fmt(model['mean_offset'], '+.2f')}, "
              f"average gap {fmt(model['mean_abs_gap'])}; one ask wobbles {fmt(model['repeat_wobble'])} when repeated, "
              f"{fmt(model['relabel_wobble'])} with the letters reversed")
    print_long(long)
    if ledger.hit and (long["asks_skipped"] or long["groups_judged_by_rules"]):
        print(f"budget of ${args.budget:.2f} reached: {long['asks_skipped']} asks skipped and {long['groups_judged_by_rules']} "
              "group-weeks judged by the rules across the probes, so the tests mix the two worlds")
    elif ledger.hit:
        print(f"budget of ${args.budget:.2f} reached, but only after the last ask: nothing was skipped")
    print(f"\n{calls} calls this run, {failed} failed, ${spent:.2f} spent ({MODEL}, effort {EFFORT}); wrote {path}")


if __name__ == "__main__":
    main()
