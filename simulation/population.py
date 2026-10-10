"""
Load the simulation cohort (simulation/data/cohort.db, built by cohort.py
on first use). The 36 students in data/studymatch.db are never part of it.

Students carry what the matcher may see (survey profile, schedule). Truth
carries what only the simulated world may see (sim_hidden_truth).
"""

import sqlite3
from dataclasses import dataclass, field

import numpy as np

from algorithm.scoring import AXES
from simulation.calibration import DAYS
from simulation.cohort import COHORT_DB, build

FULL_FIT_HOURS = 3          # 3 shared free hours a week = schedules fully compatible


@dataclass
class Student:
    sid: str
    name: str
    course: str
    survey: dict
    per_week: int                       # preferred study sessions per week
    blocks: list = field(default_factory=list)
    items: dict = field(default_factory=dict)   # raw survey answers, item id -> 1-5


@dataclass
class Truth:
    axes: dict
    sensitivity: dict
    schedule_weight: float
    flake_weight: float
    leniency: float
    response_rate: float
    careless: str | None


@dataclass
class Course:
    ids: list                           # student ids, row order of fit (and of score matrices)
    index: dict                         # id -> row
    fit: np.ndarray                     # 0-1 schedule compatibility for every pair


def load_cohort(path=COHORT_DB):
    """-> (students, truth, starting groups {group_id: [ids]}, courses {course_id: Course})."""
    if not path.exists():
        build(path)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    students = {}
    for sid, name, course, per_week, *axes in con.execute(f"""
            SELECT s.student_id, s.name, pp.course_id, av.preferred_sessions_per_week,
                   {', '.join('pp.' + a for a in AXES)}
            FROM student s
            JOIN personality_profile pp ON pp.student_id = s.student_id
            JOIN availability av ON av.student_id = s.student_id AND av.course_id = pp.course_id
            ORDER BY s.student_id"""):
        students[sid] = Student(sid, name, course, dict(zip(AXES, axes)), per_week)
    for sid, day, start, end in con.execute(
            "SELECT student_id, day, start_time, end_time FROM availability_block ORDER BY block_id"):
        students[sid].blocks.append((day, int(start[:2]), int(end[:2])))
    for sid, item, value in con.execute("SELECT student_id, item_number, response FROM survey_response"):
        students[sid].items[item] = value

    truth = {}
    cols = [f"true_{a}" for a in AXES] + [f"sens_{a}" for a in AXES]
    for row in con.execute(f"""SELECT student_id, {', '.join(cols)}, schedule_weight, flake_weight,
                                      rating_leniency, response_rate, careless FROM sim_hidden_truth"""):
        sid, vals = row[0], row[1:]
        truth[sid] = Truth(dict(zip(AXES, vals[:6])), dict(zip(AXES, vals[6:12])), *vals[12:])

    groups = {}
    for gid, sid in con.execute("SELECT group_id, student_id FROM group_membership ORDER BY group_id, student_id"):
        groups.setdefault(gid, []).append(sid)
    con.close()

    courses = {}
    for course in sorted({s.course for s in students.values()}):
        ids = sorted(s for s in students if students[s].course == course)
        grid = np.zeros((len(ids), len(DAYS) * 24))
        for row, sid in enumerate(ids):
            for day, start, end in students[sid].blocks:
                d = DAYS.index(day)
                grid[row, d * 24 + start:d * 24 + end] = 1
        fit = np.minimum(grid @ grid.T / FULL_FIT_HOURS, 1.0)
        np.fill_diagonal(fit, 0.0)
        courses[course] = Course(ids, {s: i for i, s in enumerate(ids)}, fit)
    return students, truth, groups, courses
