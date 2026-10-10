"""
Build the simulation cohort: 1000 synthetic students, 500 per course, in a
database of their own, simulation/data/cohort.db. It uses the app's schema
plus one extra table of hidden truths. data/studymatch.db and its 36
students are never read or changed.

    python -m simulation.cohort            # build if missing
    python -m simulation.cohort --force    # rebuild

The same seed always builds the same cohort. Per student:
  1. a true 6-axis profile from the real-data population model
  2. 24 survey answers drawn around the truth with each axis's real item
     noise and a small self-flattering bias; 5% answer carelessly. Scored
     with the live score_axes(), so the stored profile is what the app shows
  3. hidden extras only the simulated world reads: what bothers them in a
     group, how leniently they rate peers, how likely they are to answer a
     feedback form
  4. year, major, gender, availability and academic profile (calibration.py)
Each course is then grouped for the start of the semester with the live
matching score (survey answers, hand-set weights, schedules ignored).
"""

import argparse
import math
import sqlite3
from pathlib import Path

import numpy as np

from algorithm.compatibility import AXIS_RANGE, AXIS_WEIGHTS, preferred_role_for
from algorithm.quality import response_flag
from algorithm.scoring import AXES, SURVEY_ITEMS, reverse_code, score_axes
from simulation import calibration as cal
from simulation.groups import form

ROOT = Path(__file__).resolve().parent.parent
COHORT_DB = Path(__file__).resolve().parent / "data" / "cohort.db"
PER_COURSE = 500
SEED = 2026
SEMESTER_START = "2026-08-24T00:00:00Z"

HIDDEN_TABLE = f"""
CREATE TABLE sim_hidden_truth (
    student_id       TEXT PRIMARY KEY REFERENCES student(student_id),
    {', '.join(f'true_{a} REAL NOT NULL' for a in AXES)},
    {', '.join(f'sens_{a} REAL NOT NULL' for a in AXES)},
    schedule_weight  REAL NOT NULL,
    flake_weight     REAL NOT NULL,
    rating_leniency  REAL NOT NULL,   -- added to every peer rating this person gives
    response_rate    REAL NOT NULL,   -- chance of answering a feedback form
    careless         TEXT             -- NULL, 'straight_line' or 'random' survey answers
)"""


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def survey_answers(true, rng, careless):
    if careless == "straight_line":
        v = cal.pick(rng, {3: 0.30, 4: 0.45, 5: 0.25})
        return {it["id"]: int(np.clip(v + (rng.choice([-1, 1]) if rng.random() < 0.15 else 0), 1, 5))
                for it in SURVEY_ITEMS}
    if careless == "random":
        return {it["id"]: int(rng.integers(1, 6)) for it in SURVEY_ITEMS}
    answers = {}
    for it in SURVEY_ITEMS:
        a = it["axis"]
        intended = int(np.clip(round(rng.normal(true[a] + cal.SELF_REPORT_BIAS[a], cal.REAL_AXIS_STATS[a][2])), 1, 5))
        answers[it["id"]] = reverse_code(intended) if it["reverse"] else intended
    return answers


def availability(course, rng):
    slots = cal.COURSES[course]["popular_slots"]
    k = min(cal.pick(rng, cal.BLOCK_COUNTS), len(slots))
    blocks = []
    for idx in rng.choice(len(slots), size=k, replace=False):
        day, start, end = slots[idx]
        start = max(7, start + int(rng.choice([-1, 0, 0, 0, 1])))
        end = min(23, max(start + 1, end + int(rng.choice([-1, 0, 0, 0, 1]))))
        blocks.append((day, start, end))
    if rng.random() < 0.25:
        start = int(rng.integers(8, 21))
        blocks.append((cal.DAYS[int(rng.integers(0, 7))], start, min(23, start + 2)))
    return {
        "blocks": [(d, f"{s:02d}:00", f"{e:02d}:00") for d, s, e in blocks],
        "period": "Evening" if any(s >= 17 for _, s, _ in blocks) else "Afternoon",
        "duration": cal.pick(rng, cal.DURATIONS),
        "per_week": cal.pick(rng, cal.SESSIONS_PER_WEEK),
        "location": cal.pick(rng, cal.LOCATIONS),
        "online": cal.pick(rng, cal.ONLINE_PREF),
    }


def academic(true, rng):
    z_int = (true["intensity"] - cal.REAL_AXIS_STATS["intensity"][0]) / cal.REAL_AXIS_STATS["intensity"][1]
    z_rel = (true["reliability"] - cal.REAL_AXIS_STATS["reliability"][0]) / cal.REAL_AXIS_STATS["reliability"][1]
    conf = 0.7 * z_int + rng.normal(0, 0.7)
    grade = 0.6 * z_int + 0.2 * z_rel + rng.normal(0, 0.75)
    return (cal.from_cuts(cal.CONFIDENCE_CUTS, 1 - _phi(conf / 0.99)),
            cal.from_cuts(cal.GRADE_CUTS, 1 - _phi(grade / 0.98)))


def hidden_extras(true, rng):
    raw = {a: rng.gamma(4.0, cal.SENSITIVITY_PRIOR[a] / 4.0) for a in AXES}
    total = sum(raw.values())
    rel = (true["reliability"] - 1) / 4
    return {
        "sens": {a: raw[a] * len(AXES) / total for a in AXES},
        "schedule_weight": float(rng.gamma(4.0, cal.SCHEDULE_PRIOR / 4.0)),
        "flake_weight": float(rng.gamma(4.0, 0.25)),
        "rating_leniency": float(rng.normal(0.4, 0.3)),
        "response_rate": float(np.clip(rng.beta(8, 2) * (0.85 + 0.15 * rel), 0.2, 0.98)),
    }


def score_matrix(profiles, weights=AXIS_WEIGHTS):
    """Live compatibility score (0-100) for every pair, from a list of axis dicts."""
    P = np.array([[p[a] for a in AXES] for p in profiles])
    w = np.array([weights[a] for a in AXES])
    closeness = 1 - np.abs(P[:, None, :] - P[None, :, :]) / AXIS_RANGE
    return 100 * (closeness * w).sum(axis=2) / w.sum()


def build(path=COHORT_DB, seed=SEED):
    rng = np.random.default_rng(seed)
    path.parent.mkdir(exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript((ROOT / "data" / "schema.sql").read_text(encoding="utf-8"))
    con.execute(HIDDEN_TABLE)
    con.execute("INSERT INTO university VALUES ('psu', 'Penn State University', 'University Park, PA')")
    titles = {"CMPSC 465": "Data Structures and Algorithms", "MATH 230": "Calculus and Vector Analysis"}
    used_names = set()

    for course, info in cal.COURSES.items():
        code = info["code"]
        con.execute("INSERT INTO course VALUES (?,?,?,?,?,?)",
                    (course, "psu", code, titles[code], course.split("-")[2], "Fall 2026"))
        ids, surveys = [], []
        for n in range(1, PER_COURSE + 1):
            sid = f"{info['slug']}_{n:03d}"
            while True:
                name = f"{cal.FIRST_NAMES[rng.integers(len(cal.FIRST_NAMES))]} {cal.LAST_NAMES[rng.integers(len(cal.LAST_NAMES))]}"
                if name not in used_names:
                    used_names.add(name)
                    break
            true = cal.sample_true_axes(rng)
            r = rng.random()
            careless = ("straight_line" if r < cal.CARELESS_STRAIGHT_LINE
                        else "random" if r < cal.CARELESS_STRAIGHT_LINE + cal.CARELESS_RANDOM else None)
            answers = survey_answers(true, rng, careless)
            survey = score_axes(answers)
            extra = hidden_extras(true, rng)
            av = availability(course, rng)
            confidence, grade = academic(true, rng)

            con.execute("INSERT INTO student VALUES (?,?,?,?,?,'synthetic')",
                        (sid, name, cal.pick(rng, info["years"]), cal.pick(rng, info["genders"]), cal.pick(rng, info["majors"])))
            con.execute("INSERT INTO course_membership VALUES (?,?,?,?,1)", (sid, course, course.split("-")[2], "Fall 2026"))
            con.execute(f"INSERT INTO personality_profile VALUES (?,?,{','.join('?' * len(AXES))},NULL,?,NULL,?)",
                        (sid, course, *[survey[a] for a in AXES], preferred_role_for(survey), response_flag(answers)))
            con.executemany("INSERT INTO survey_response VALUES (?,?,?,?)",
                            [(sid, course, item, v) for item, v in answers.items()])
            con.execute("INSERT INTO availability VALUES (?,?,?,?,?,?,?)",
                        (sid, course, av["period"], av["duration"], av["per_week"], av["location"], av["online"]))
            con.executemany("INSERT INTO availability_block (student_id, course_id, day, start_time, end_time) VALUES (?,?,?,?,?)",
                            [(sid, course, d, s, e) for d, s, e in av["blocks"]])
            con.execute("INSERT INTO academic_profile VALUES (?,?,?,?)", (sid, course, confidence, grade))
            con.execute(f"INSERT INTO sim_hidden_truth VALUES (?,{','.join('?' * (2 * len(AXES) + 5))})",
                        (sid, *[true[a] for a in AXES], *[extra["sens"][a] for a in AXES], extra["schedule_weight"],
                         extra["flake_weight"], extra["rating_leniency"], extra["response_rate"], careless))
            ids.append(sid)
            surveys.append(survey)

        S = score_matrix(surveys)
        index = {s: i for i, s in enumerate(ids)}
        groups, leftover = form(ids, S, index, rng)
        assert not leftover
        for g, members in enumerate(groups, start=1):
            gid = f"{info['slug']}_g{g:03d}"
            pairs = [S[index[a], index[b]] for i, a in enumerate(members) for b in members[i + 1:]]
            avg = round(float(np.mean(pairs)), 1)
            con.execute("INSERT INTO study_group VALUES (?,?,?,?,?,?,?,?,?)",
                        (gid, course, f"{code} Group {g}", 5, len(members), SEMESTER_START, avg, avg, round(float(min(pairs)), 1)))
            con.executemany("INSERT INTO group_membership VALUES (?,?,?,?)",
                            [(gid, s, SEMESTER_START, "Flexible/No Preference") for s in members])
    con.commit()
    con.close()
    return path


def main():
    parser = argparse.ArgumentParser(description="Build the 1000-student simulation cohort.")
    parser.add_argument("--force", action="store_true", help="rebuild even if it exists")
    args = parser.parse_args()
    if COHORT_DB.exists() and not args.force:
        print(f"{COHORT_DB} already exists (use --force to rebuild)")
        return
    print(f"built {build()}")


if __name__ == "__main__":
    main()
