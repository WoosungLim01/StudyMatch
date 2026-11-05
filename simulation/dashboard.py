"""
The results dashboard: one self-contained page that opens in any browser.

    python -m simulation.dashboard      # redraw output/dashboard.html from the latest run, no rerun

run.py rebuilds it after every run, and live.py serves the same page for a
semester you step through a week at a time. build_data() turns a run into
the page's data:
  report        seed averages, every seed's numbers, the learner's path and
                its tuning decisions (run.report_of)
  trace         one semester in full: groups, feedback, the learner's
                profiles, the LLM's notes
  checks.json, frequency.json, calibration.json   from checks.py,
                frequency.py and calibrate.py, when they've been run
It's baked into dashboard_template.html the way data/build_viewer.py builds
the data browser. Numbers describing the world's rules are read from the
modules' constants, so the page can't drift from the code.
"""

import json
import sqlite3
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

from algorithm.compatibility import AXIS_WEIGHTS
from algorithm.grouping import GROUP_MAX, GROUP_MIN
from algorithm.scoring import AXES
from simulation import calibration as cal
from simulation import learner as ln
from simulation import world as w
from simulation.cohort import COHORT_DB
from simulation.groups import ILP_MAX_POOL
from simulation.policy import MIN_KEEP, Policy
from simulation.population import FULL_FIT_HOURS

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "output"
TEMPLATE = HERE / "dashboard_template.html"
DASHBOARD = OUTPUT / "dashboard.html"
PLACEHOLDER = "__DASHBOARD_DATA__"

STRATEGIES = [  # phrase: how the strategy reads inside a sentence ("... with no regrouping")
    {"id": "stay", "label": "Never regroup", "short": "Stay", "phrase": "no regrouping",
     "desc": "Semester-start groups stay together. Anyone who quits stays without a group."},
    {"id": "survey", "label": "Survey only", "short": "Survey", "phrase": "survey answers alone",
     "desc": "Unhappy students are moved and quitters placed again, using only survey answers and the app's "
             "hand-set weights."},
    {"id": "learn", "label": "Learn from feedback", "short": "Learn", "phrase": "learning from feedback",
     "desc": "The same moves, scored with what feedback taught: peer-rated reliability, complaint tags, "
             "refit weights and pairs to keep apart."},
]

METRICS = [  # id, label, format, which way is better, what it means
    ("true_satisfaction", "True satisfaction", "sat", "up",
     "Average hidden satisfaction (1-5) at the end of the week. Students without a group count as "
     f"{w.NO_GROUP_UTILITY:.1f}."),
    ("unhappy_share", "Truly unhappy", "pct", "down",
     "Share of all students whose hidden satisfaction ended the week below 3."),
    ("reported_satisfaction", "Reported satisfaction", "sat", "up",
     "Average rating on the week's pulse forms. It runs above the truth because people round up."),
    ("response_rate", "Forms answered", "pct", "up",
     "Share of grouped students who answered the week's pulse. It falls as the semester wears on."),
    ("attendance", "Attendance", "pct", "up",
     "Meetings attended out of meetings held, as reported on the forms."),
    ("left", "Quit their group", "count", "down",
     "Students who quit their group this week (two bad weeks in a row)."),
    ("without_group", "Without a group", "count", "down",
     "Students who spent the week with no group."),
    ("moved_after", "Moved after the week", "count", "down",
     "Students placed in a different group at the end of the week. Fewer moves means less disruption."),
    ("profile_accuracy", "Knows the students", "r", "up",
     "How closely the matcher's picture of students matched the hidden truth when the week's groups "
     "were formed (correlation, averaged over the 6 traits)."),
    ("reliability_accuracy", "Knows reliability", "r", "up",
     "The same correlation for reliability alone."),
]

FEATURE_LABELS = {"planning": "Planning", "session_mode": "Session style", "reliability": "Reliability",
                  "structure": "Structure", "intensity": "Intensity", "collaboration": "Collaboration",
                  "schedule": "Schedule overlap"}
AXIS_HINTS = {
    "planning": "Sets goals and checks their own understanding",
    "session_mode": "Likes talking problems through (high) or working quietly (low)",
    "reliability": "Shows up prepared and follows through",
    "structure": "Wants organised sessions with a plan",
    "intensity": "Confidence and drive in this course",
    "collaboration": "Learns by explaining to others",
    "schedule": "Shared free hours in the week",
}

FORM_FIELDS = [  # field, question, when, how the world produces it, what the learner does with it, used?, new?
    ("left_group", "Left the group", "Any week", f"Two weeks in a row below {w.LEAVE_BELOW}. The app knows "
     "this without a form.", "Placed in a new group the same week", True, False),
    ("satisfaction", "How satisfied are you with your group? (1-5)", "Weekly pulse",
     f"Running satisfaction, rounded up by about {w.REPORT_POSITIVITY}", "Target for refitting the weights", True, False),
    ("would_match_again", "Would you keep this group?", "Weekly pulse", f"Yes unless clearly below {w.STAY_IF_AT_LEAST}",
     "Decides who is moved", True, False),
    ("tags", "What would make the group better?", "Weekly pulse", "The 1-2 biggest causes of discomfort, asked at "
     f"a rating of {w.COMPLAIN_AT_OR_BELOW} or lower", "Nudges the other four traits", True, True),
    ("avoid", "Anyone you'd rather not be grouped with again?", "Weekly pulse", "The worst-fitting or flakiest "
     "groupmate, asked at a rating of 2 or lower", "That pair is never grouped again", True, True),
    ("meetings_attended", "How many meetings did you attend?", "Weekly pulse", "Self-reported count",
     "Not used: peer ratings measure the same thing without self-report bias", False, False),
    ("peer_reliability", "Rate each groupmate: showed up and followed through (1-5)", "Check-in",
     "The attendance they saw since the last check-in, plus the rater's leniency and noise", "Reliability estimate",
     True, False),
    ("peer_helpfulness", "Rate each groupmate: helped others understand (1-5)", "Check-in",
     "True collaboration and attendance, same rater biases", "Collaboration estimate", True, False),
    ("perceived_fit", "How well did your styles fit? (1-5)", "Check-in", "Style gap felt at meetings",
     "Not used: overlaps satisfaction and the tags", False, False),
    ("productivity", "How productive were sessions? (1-5)", "Check-in", "Attendance, drive and organisation",
     "Not used: describes the group, not the fit", False, False),
    ("chat_activity", "How active was the group chat?", "Check-in", "Group talkativeness times attendance",
     "Not used: mostly personality, a weak fit signal", False, False),
]


def hidden_weights(truth):
    """What one unit of 0-1 gap costs in the world's discomfort formula, averaged
    over the cohort: STYLE_SCALE x sensitivity / 6 per trait, SCHEDULE_SCALE x
    schedule weight for schedules. That's the same footing as the learner's
    features, so their shares of the total compare directly. Flaky groupmates
    are left out: that's attendance, not a gap between two people."""
    out = {a: w.STYLE_SCALE * float(np.mean([t.sensitivity[a] for t in truth.values()])) / len(AXES) for a in AXES}
    out["schedule"] = w.SCHEDULE_SCALE * float(np.mean([t.schedule_weight for t in truth.values()]))
    return out


def shares(weights):
    total = sum(weights[x] for x in ln.FEATURES)
    return {x: weights[x] / total for x in ln.FEATURES}


def group_label(gid):
    """c465_g012 -> (Group 12, formed before week 1); w6_cmpsc465_004 -> (New group 5, formed after week 6)."""
    head = gid.split("_")[0]
    if head[0] in "wp" and head[1:].isdigit():
        return f"New group {int(gid.rsplit('_', 1)[1]) + 1}", int(head[1:])
    return f"Group {int(gid.rsplit('_g', 1)[1])}", 0


def _r(x, n=2):
    return None if x is None else round(float(x), n)


def compact_week(rec, ids, idx, tag_codes):
    """One strategy-week of the trace as per-student columns (index = position in ids)."""
    gids = sorted(rec["groups"])
    group_of = [-1] * len(ids)
    groups = []
    for g, gid in enumerate(gids):
        label, formed = group_label(gid)
        members = [idx[s] for s in rec["groups"][gid]]
        groups.append({"id": gid, "label": label, "formed": formed, "m": members})
        for i in members:
            group_of[i] = g
    fb = {f["sid"]: f for f in rec["feedback"]}

    def col(key, conv=lambda v: v):
        return [None if s not in fb or fb[s][key] is None else conv(fb[s][key]) for s in ids]

    chat = {"low": 0, "medium": 1, "high": 2}
    out = {
        "groups": groups,
        "g": group_of,
        "u": [_r(rec["utility"].get(s)) for s in ids],
        "left": col("left_group", int),
        "wk": col("weeks_in_group"),
        "resp": col("responded", int),
        "sat": col("satisfaction"),
        "wma": col("would_match_again", int),
        "fit": col("perceived_fit"),
        "prod": col("productivity"),
        "chat": col("chat_activity", chat.get),
        "prel": col("peer_reliability", lambda v: _r(v, 1)),
        "phelp": col("peer_helpfulness", lambda v: _r(v, 1)),
        "att": col("meetings_attended"),
        "mpw": col("meetings_per_week"),
        "tags": {idx[s]: [tag_codes[t] for t in f["tags"]] for s, f in fb.items() if f["tags"]},
        "avoid": {idx[s]: [idx[o] for o in f["avoid"]] for s, f in fb.items() if f["avoid"]},
        "moved": [idx[s] for s in rec["moved"]],
        # per student: rule world's value, the LLM's average, its note, every ask's answer, whether the clamp bound
        "llm": {idx[s]: [_r(d["rule"]), _r(d["raw"]), d["note"], d.get("asks"), d.get("clamped")]
                for s, d in (rec.get("detail") or {}).items() if d},
        "decision": rec.get("decision"),
        "counts": rec.get("counts") or {},
        "world": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in (rec.get("world") or {}).items()},
        # meeting world: per group, what happened at each meeting (index = position in groups)
        "stories": {g: [{"who": m["who"], "account": m["account"],
                         "exp": {idx[s]: e for s, e in (m.get("experience") or {}).items() if e}}
                        for m in extra["meetings"]]
                    for g, gid in enumerate(gids) if (extra := (rec.get("group_detail") or {}).get(gid))},
    }
    if rec.get("profile"):
        out["prof"] = [[_r(rec["profile"][s][a]) for a in AXES] for s in ids]
    return out


@lru_cache(maxsize=1)
def _people():
    con = sqlite3.connect(f"file:{COHORT_DB}?mode=ro", uri=True)
    people = {sid: (year, gender, major) for sid, year, gender, major in
              con.execute("SELECT student_id, year, gender, major FROM student")}
    titles = {cid: (code, title, semester) for cid, code, title, semester in
              con.execute("SELECT course_id, course_code, course_title, semester FROM course")}
    con.close()
    return people, titles


def assumptions(truth, policy, gate, samples=None):
    bias = ", ".join(f"{FEATURE_LABELS[a].lower()} +{v:.2f}" for a, v in cal.SELF_REPORT_BIAS.items() if v)
    response = float(np.mean([t.response_rate for t in truth.values()]))
    leniency = float(np.mean([t.leniency for t in truth.values()]))
    move_rule = (f"{policy.label().capitalize()}, once they've been in the group {policy.min_tenure} weeks, and never "
                 f"after week {policy.last_move_week}" if policy.cadence else
                 "Unhappy students are never moved; only students who quit are placed again")
    return [
        {"title": "How a week plays out", "source": "simulation/world.py", "items": [
            ("Semester", f"At most {w.SEMESTER_WEEKS} weeks, one step per week. Exam weeks "
             f"{', '.join(map(str, sorted(w.EXAM_WEEKS)))}: everyone is 10% less likely to show up"),
            ("Meetings", "The members' median preference per week, one fewer if their schedules barely overlap"),
            ("Showing up", "More likely for reliable students, good schedule fits and happy students; less in exam weeks"),
            ("A meeting's experience", "5 - 4 x discomfort. Discomfort adds style gaps to whoever came (weighted by "
             "what bothers this student), groupmates who didn't come, and schedule clashes"),
            ("Satisfaction", f"Moves {round((1 - w.EMA) * 100)}% of the way toward each meeting's experience and "
             f"carries over while the group stays together. A new group starts at {w.START_SATISFACTION}"),
            ("Quitting", f"Two week-ends in a row below {w.LEAVE_BELOW}"),
            ("No group", f"Counts as satisfaction {w.NO_GROUP_UTILITY}"),
        ]},
        {"title": "What students report", "source": "simulation/world.py, simulation/cohort.py", "items": [
            ("Weekly pulse", f"Rating, keep the group?, and what would help. Answered about "
             f"{response * w.PULSE_RESPONSE:.0%} of the time at the start, {w.FATIGUE:.0%} less each week, half as "
             "often after quitting"),
            ("Check-ins", f"Every {w.CHECKIN_EVERY} weeks the form also asks for peer ratings, fit, productivity "
             "and chat activity"),
            ("Rounding up", f"Ratings of their own group run about {w.REPORT_POSITIVITY} above the truth"),
            ("Rating groupmates", f"Lenient: raters add {leniency:+.2f} to every rating on average, each with their "
             "own habit"),
            ("Would keep the group", f"Yes unless satisfaction is clearly below {w.STAY_IF_AT_LEAST}"),
            ("No grades", "The form never asks about grades or course performance. A week says nothing about a "
             "final grade, and grades depend mostly on the student"),
        ]},
        {"title": "Who the students are", "source": "simulation/calibration.py", "items": [
            ("Personality", "Means, spreads and correlations from a published MSLQ validation study and the IPIP "
             "Big Five dataset (docs/SYNTHETIC_DATA.md)"),
            ("Flattering surveys", f"Survey answers overstate the truth: {bias}"),
            ("Careless answers", f"{cal.CARELESS_STRAIGHT_LINE:.0%} answer the same option throughout, "
             f"{cal.CARELESS_RANDOM:.0%} answer at random"),
            ("What bothers students", "Average weight of a gap: " + ", ".join(
                f"{FEATURE_LABELS[a].lower()} {v:.1f}" for a, v in cal.SENSITIVITY_PRIOR.items())
             + f", schedules {cal.SCHEDULE_PRIOR:.1f}. Each student's own weights scatter around these"),
            ("Courses", "CMPSC 465 is mostly juniors and CS majors; MATH 230 mostly freshmen and sophomores in "
             "engineering. These mixes are assumptions, not Penn State data"),
            ("Schedules", f"Drawn from each course's popular study windows; {FULL_FIT_HOURS} shared free hours a "
             "week count as a full fit"),
        ]},
        {"title": "How matching and learning work", "source": "simulation/policy.py, learner.py, groups.py", "items": [
            ("Group size", f"{GROUP_MIN}-{GROUP_MAX}, maximising how alike each group is"),
            ("Forming groups", f"The live ILP for pools of {ILP_MAX_POOL} or fewer; above that, a swap search on "
             "the same objective (99.6% of the ILP's score on 30-student samples)"),
            ("Placing", "Anyone who quits is placed again the same week, like the live app's waiting pool. "
             f"A group left with fewer than {MIN_KEEP} dissolves"),
            ("Moving", move_rule),
            ("Peer ratings", "Combined with the survey, each weighted by how noisy it is. The survey's noise comes "
             "from how consistently its four items agree (Cronbach's alpha)"),
            ("Complaint tags", f"Move the student's profile {ln.NUDGE:.0%} of the way to {ln.TAG_MARGIN} past the "
             "group's average on that trait"),
            ("Changing the weights", (f"Refit every week, adopted only when it predicts that week's forms better by "
             f"more than chance ({ln.SIGNIFICANCE:.0f} standard errors and at least {ln.MIN_GAIN:.1%}). Tuning stops "
             f"after {ln.FREEZE_AFTER} weeks in a row without a real gain and restarts if reported satisfaction "
             f"falls {ln.ALARM_DROP}") if gate else "Refit and adopted every week, without a check"),
        ]},
        {"title": "The LLM world", "source": "simulation/llm_world.py", "items": [
            ("What changes", "A language model decides how each student felt about their group's week. Meetings, "
             "attendance, who answers forms and peer ratings stay rule-based, so both worlds see the same events"),
            ("What it sees", "Each member's true traits, the sessions a week they want, shared free time, how they "
             "felt last week, and who came to each meeting"),
            ("What it doesn't see", "Names, gender, majors, the compatibility score, the rule world's answer, or "
             "what students are supposed to care about"),
            ("Several asks", f"Each group is asked {samples or '3'} time{'s' if (samples or 3) != 1 else ''} in "
             "independent calls and the answers are averaged, which cuts the model's sampling noise. A complaint "
             "counts when at least half the asks named it"),
            ("Clamp", "The average is held within a set distance of the rule world's value, as in IdeaLab V2. "
             "calibrate.py tests 0.3 and 1.2; 1.2 almost never binds"),
            ("Simulated meetings", "In the meetings world, Claude first writes an account of each meeting from who "
             "came and what the members are like, continuing the previous meeting's account, and the week is judged "
             "from those accounts. After each meeting, how likely each member is to come next time changes their "
             "attendance (likely ×1.1, unsure ×0.85, unlikely ×0.6)"),
            ("Cost", "One call per ask per group per week, cached by exact input, so replaying a semester is free. "
             "The rule world also judges a group whose calls failed or when the budget is spent"),
        ]},
    ]


def load_json(name, folder=OUTPUT):
    path = folder / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def build_data(report, trace, cohort, live=None):
    """Everything the page shows, as one JSON-ready dict."""
    students, truth, courses = cohort.students, cohort.truth, cohort.courses
    people, titles = _people()
    ids = sorted(students)
    idx = {s: i for i, s in enumerate(ids)}
    course_ids = sorted({students[s].course for s in ids})
    tag_codes = {t: i for i, t in enumerate(w.TAGS)}
    weeks = len(next(iter(report["summary"].values())))
    policy = Policy(**{k: v for k, v in report["policy"].items() if k != "label"})
    checks = load_json("checks.json")

    mix = {}
    for c in course_ids:
        rows = [people[s] for s in ids if students[s].course == c]
        mix[c] = {k: Counter(r[j] for r in rows).most_common() for j, k in enumerate(["year", "gender", "major"])}
    hand_set = {**AXIS_WEIGHTS, "schedule": 0.0}
    learn_path = report["learner_path"].get("learn", {}).get("weights") or [hand_set]

    return {
        "meta": {
            "generated": report.get("generated"), "world": report.get("world", "rule"),
            "samples": report.get("samples"), "llm": report.get("llm"),
            "seeds": report["seeds"], "weeks": weeks, "max_weeks": report.get("max_weeks", w.SEMESTER_WEEKS),
            "exam_weeks": sorted(w.EXAM_WEEKS), "checkin_every": w.CHECKIN_EVERY,
            "policy": report["policy"], "gate": report.get("gate", True),
            "checks_generated": checks and checks.get("generated"), "live": live,
        },
        "strategies": [s for s in STRATEGIES if s["id"] in report["summary"]],
        "metrics": [dict(zip(["id", "label", "format", "better", "desc"], m)) for m in METRICS],
        "summary": report["summary"],
        "per_seed": report["per_seed"],
        "learner_path": report["learner_path"],
        "learner_log": report.get("learner_log", []),
        "axes": AXES, "features": ln.FEATURES, "feature_labels": FEATURE_LABELS, "axis_hints": AXIS_HINTS,
        "weights": {
            "hand_set": shares(hand_set),
            "learned": shares(learn_path[-1]),
            "hidden": shares(hidden_weights(truth)),
            "learned_path": [shares(step) for step in learn_path],
        },
        "courses": [{"id": c, "code": titles[c][0], "title": titles[c][1], "semester": titles[c][2],
                     "n": sum(students[s].course == c for s in ids), "mix": mix[c]} for c in course_ids],
        "students": {
            "id": ids,
            "name": [students[s].name for s in ids],
            "course": [course_ids.index(students[s].course) for s in ids],
            "year": [people[s][0] for s in ids],
            "gender": [people[s][1] for s in ids],
            "major": [people[s][2] for s in ids],
            "survey": [[_r(students[s].survey[a]) for a in AXES] for s in ids],
            "truth": [[_r(truth[s].axes[a]) for a in AXES] for s in ids],
            "sens": [[_r(truth[s].sensitivity[a]) for a in AXES] for s in ids],
            "schedule_w": [_r(truth[s].schedule_weight) for s in ids],
            "flake_w": [_r(truth[s].flake_weight) for s in ids],
            "leniency": [_r(truth[s].leniency) for s in ids],
            "response_rate": [_r(truth[s].response_rate) for s in ids],
            "careless": [truth[s].careless for s in ids],
            "per_week": [students[s].per_week for s in ids],
            "blocks": [[[cal.DAYS.index(d), a, b] for d, a, b in students[s].blocks] for s in ids],
        },
        "averages": {
            "sens": [_r(np.mean([truth[s].sensitivity[a] for s in ids])) for a in AXES],
            "schedule_w": _r(np.mean([truth[s].schedule_weight for s in ids])),
            "flake_w": _r(np.mean([truth[s].flake_weight for s in ids])),
            "leniency": _r(np.mean([truth[s].leniency for s in ids])),
        },
        "tags": [{"code": t, "label": label} for t, label in w.TAGS.items()],
        "trace": {s: [compact_week(rec, ids, idx, tag_codes) for rec in recs] for s, recs in trace.items()},
        "form_fields": [dict(zip(["field", "question", "when", "produced", "use", "used", "new"], f)) for f in FORM_FIELDS],
        "checks": checks and checks["checks"],
        "frequency": load_json("frequency.json"),
        "calibration": load_json("calibration.json"),
        "assumptions": [{**sec, "items": [list(i) for i in sec["items"]]}
                        for sec in assumptions(truth, policy, report.get("gate", True), report.get("samples"))],
    }


def page(data):
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = TEMPLATE.read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        raise SystemExit(f"dashboard_template.html must contain {PLACEHOLDER} exactly once.")
    return template.replace(PLACEHOLDER, blob)


def build(folder=OUTPUT):
    """Redraw <folder>/dashboard.html from the files run.py wrote there. The cohort is
    shrunk to the students in the trace, so a sampled run shows only its own students."""
    from simulation.population import load_cohort
    from simulation.semester import Cohort

    report, trace = load_json("report.json", folder), load_json("trace_seed0.json", folder)
    if report is None or trace is None or "weeks" not in report:
        raise SystemExit(f"No weekly run found in {folder}: run python -m simulation.run first.")
    cohort = Cohort(*load_cohort())
    first_week = next(iter(trace.values()))[0]     # everyone starts the semester in a group
    in_run = {s for m in first_week["groups"].values() for s in m}
    if in_run and len(in_run) < len(cohort.students):
        keep = {g: m for g, m in cohort.start_groups.items() if set(m) <= in_run}
        cohort = Cohort({s: cohort.students[s] for s in sorted(in_run)}, {s: cohort.truth[s] for s in in_run},
                        keep, cohort.courses)
    target = folder / "dashboard.html"
    target.write_text(page(build_data(report, trace, cohort)), encoding="utf-8")
    return target


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Redraw a run's dashboard without rerunning it")
    parser.add_argument("--dir", default=None, help="subfolder of simulation/output (for example llm)")
    args = parser.parse_args()
    path = build(OUTPUT / args.dir if args.dir else OUTPUT)
    print(f"wrote {path} ({path.stat().st_size / 1024:.0f} KB). Open it in a browser.")
