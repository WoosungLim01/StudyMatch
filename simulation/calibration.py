"""
Everything the 1000-student cohort is drawn from, in one place.

Personality: the same real-data calibration as data/generate_sample_data.py
(means, spreads and correlations from the MSLQ-CL validation study and the
IPIP Big Five dataset; derivation in docs/SYNTHETIC_DATA.md). Copied rather
than imported because that script runs its whole generation on import.

Everything else below is a stated ASSUMPTION, chosen to be plausible for a
large US public university, not measured Penn State data:
  - year: CMPSC 465 is upper-level (mostly juniors), MATH 230 (Calc III) is
    taken early (mostly freshmen and sophomores)
  - major: CS-heavy for CMPSC 465, engineering-heavy for MATH 230
  - gender: roughly a quarter women in CMPSC 465, a third in MATH 230,
    in line with national CS and engineering enrolment
  - survey self-report: people describe themselves a little more organised
    and reliable than they are (social desirability), and a few answer
    carelessly
"""

import numpy as np

# axis: (population mean, population SD, item-noise SD), 1-5 scale. Same values as
# REAL_AXIS_STATS in data/generate_sample_data.py.
REAL_AXIS_STATS = {
    "planning":      (3.533, 0.613, 0.683),
    "reliability":   (3.453, 0.700, 0.875),
    "structure":     (3.673, 0.653, 0.679),
    "intensity":     (3.764, 0.527, 0.500),
    "session_mode":  (3.011, 0.922, 0.982),
    "collaboration": (3.845, 0.715, 0.885),
}
MSLQ_AXES = ["planning", "reliability", "structure", "intensity"]
MSLQ_CORR = np.array([
    [1.000, 0.482, 0.679, 0.000],
    [0.482, 1.000, 0.421, 0.000],
    [0.679, 0.421, 1.000, 0.000],
    [0.000, 0.000, 0.000, 1.000],
])
BIG5_AXES = ["session_mode", "collaboration"]
BIG5_CORR = np.array([[1.000, 0.334], [0.334, 1.000]])

# What actually bothers students in a group (hidden from the matcher). Average
# weight of a gap on each axis; each person's own weights scatter around these.
# Reliability highest: a groupmate who doesn't show up prepared is the most
# common study-group complaint. The matcher starts from its own hand-set
# weights (algorithm/compatibility.py) and never sees these.
SENSITIVITY_PRIOR = {"planning": 0.8, "session_mode": 1.0, "reliability": 2.0,
                     "structure": 1.0, "intensity": 1.4, "collaboration": 0.8}
SCHEDULE_PRIOR = 1.0

# How much the survey overstates the truth, on average (social desirability).
SELF_REPORT_BIAS = {"planning": 0.15, "reliability": 0.25, "structure": 0.10,
                    "intensity": 0.10, "session_mode": 0.0, "collaboration": 0.05}
CARELESS_STRAIGHT_LINE = 0.03       # share answering (nearly) the same option everywhere
CARELESS_RANDOM = 0.02              # share answering at random

COURSES = {
    "psu-cmpsc465-001-fa26": {
        "code": "CMPSC 465",
        "slug": "c465",
        "years": {"Freshman": 0.02, "Sophomore": 0.15, "Junior": 0.55, "Senior": 0.28},
        "majors": {"Computer Science": 0.60, "Computer Engineering": 0.15, "Data Science": 0.10,
                   "Math": 0.06, "Electrical Engineering": 0.04,
                   "Information Sciences & Technology": 0.03, "Statistics": 0.02},
        "genders": {"Man": 0.72, "Woman": 0.24, "Non-binary": 0.02, "Prefer not to say": 0.02},
        # (day, start hour, end hour): common windows students draw from, same as the 36-student data
        "popular_slots": [("Mon", 18, 21), ("Wed", 18, 21), ("Tue", 14, 17), ("Thu", 14, 17),
                          ("Sun", 16, 20), ("Mon", 19, 22), ("Wed", 19, 22)],
    },
    "psu-math230-002-fa26": {
        "code": "MATH 230",
        "slug": "m230",
        "years": {"Freshman": 0.30, "Sophomore": 0.50, "Junior": 0.15, "Senior": 0.05},
        "majors": {"Mechanical Engineering": 0.18, "Computer Science": 0.10, "Electrical Engineering": 0.10,
                   "Aerospace Engineering": 0.08, "Civil Engineering": 0.08, "Math": 0.08,
                   "Chemical Engineering": 0.07, "Computer Engineering": 0.07, "Physics": 0.06,
                   "Industrial Engineering": 0.05, "Meteorology": 0.04, "Data Science": 0.04,
                   "Biomedical Engineering": 0.03, "Statistics": 0.02},
        "genders": {"Man": 0.62, "Woman": 0.34, "Non-binary": 0.02, "Prefer not to say": 0.02},
        "popular_slots": [("Mon", 19, 22), ("Wed", 19, 22), ("Sat", 10, 14), ("Tue", 18, 21),
                          ("Thu", 18, 21), ("Sun", 14, 18)],
    },
}

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SESSIONS_PER_WEEK = {1: 0.35, 2: 0.45, 3: 0.20}
BLOCK_COUNTS = {1: 0.10, 2: 0.30, 3: 0.35, 4: 0.25}
DURATIONS = {60: 0.30, 90: 0.45, 120: 0.25}
LOCATIONS = {"Library": 0.35, "Study Lounge": 0.20, "Dorm/Apartment": 0.15, "Coffee Shop": 0.10, "Online": 0.20}
ONLINE_PREF = {"in_person": 0.45, "hybrid": 0.40, "online": 0.15}
# target grade and confidence follow the student's true motivation (intensity), plus noise
GRADE_CUTS = [("A", 0.45), ("A-", 0.25), ("B+", 0.15), ("B", 0.10), ("C", 0.05)]
CONFIDENCE_CUTS = [(5, 0.15), (4, 0.30), (3, 0.35), (2, 0.15), (1, 0.05)]

FIRST_NAMES = [
    "James", "Michael", "David", "Ryan", "Matthew", "Andrew", "Tyler", "Kevin", "Brian", "Jason",
    "Emily", "Sarah", "Jessica", "Ashley", "Rachel", "Megan", "Lauren", "Hannah", "Olivia", "Emma",
    "Ethan", "Noah", "Liam", "Mason", "Logan", "Owen", "Nathan", "Connor", "Dylan", "Caleb",
    "Grace", "Chloe", "Abigail", "Madison", "Natalie", "Sophia", "Ava", "Mia", "Ella", "Claire",
    "Wei", "Jun", "Hao", "Yu", "Xin", "Min", "Jia", "Lei", "Yan", "Tian",
    "Ji-ho", "Min-jun", "Seo-yeon", "Ji-woo", "Hyun", "Soo-min", "Taeyang", "Eun-ji",
    "Arjun", "Rohan", "Priya", "Ananya", "Vikram", "Aditi", "Rahul", "Sneha", "Karthik", "Divya",
    "Carlos", "Diego", "Luis", "Sofia", "Valentina", "Mateo", "Camila", "Javier", "Isabel", "Andres",
    "Malik", "Jamal", "Aaliyah", "Imani", "Darius", "Kiara", "Andre", "Jasmine",
    "Omar", "Yusuf", "Layla", "Fatima", "Hassan", "Amira", "Zain", "Noor",
    "Kwame", "Amara", "Chidi", "Ngozi", "Tunde", "Adaeze", "Dmitri", "Anya", "Lukas", "Elena",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis", "Wilson", "Anderson", "Taylor",
    "Thomas", "Moore", "Martin", "Jackson", "Thompson", "White", "Harris", "Clark", "Lewis", "Walker",
    "Hall", "Allen", "Young", "King", "Wright", "Scott", "Green", "Baker", "Adams", "Nelson",
    "Hill", "Campbell", "Mitchell", "Roberts", "Carter", "Phillips", "Evans", "Turner", "Parker", "Collins",
    "Murphy", "Sullivan", "Kelly", "O'Brien", "Kowalski", "Novak", "Schmidt", "Muller", "Rossi", "Russo",
    "Wang", "Li", "Zhang", "Liu", "Chen", "Yang", "Huang", "Zhao", "Wu", "Zhou",
    "Kim", "Lee", "Park", "Choi", "Jung", "Kang", "Cho", "Yoon",
    "Patel", "Shah", "Singh", "Kumar", "Gupta", "Reddy", "Iyer", "Rao", "Mehta", "Desai",
    "Garcia", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Perez", "Sanchez", "Ramirez", "Torres",
    "Nguyen", "Tran", "Pham", "Khan", "Ali", "Ahmed", "Hassan", "Okafor", "Adeyemi", "Mensah",
    "Ivanov", "Petrov", "Haddad", "Nasser", "Cohen", "Levi", "Silva", "Santos", "Tanaka", "Sato",
]


def pick(rng, dist):
    keys = list(dist)
    p = np.array([dist[k] for k in keys], dtype=float)
    return keys[rng.choice(len(keys), p=p / p.sum())]


def from_cuts(cuts, quantile):
    """Map a 0-1 quantile onto categories listed best-first with their shares."""
    total = 0.0
    for label, share in cuts:
        total += share
        if quantile < total:
            return label
    return cuts[-1][0]


def _cov(axes, corr):
    sds = np.array([REAL_AXIS_STATS[a][1] for a in axes])
    return corr * np.outer(sds, sds)


def sample_true_axes(rng):
    """One person's true 6-axis profile from the real-data population model."""
    m = np.clip(rng.multivariate_normal([REAL_AXIS_STATS[a][0] for a in MSLQ_AXES], _cov(MSLQ_AXES, MSLQ_CORR)), 1, 5)
    b = np.clip(rng.multivariate_normal([REAL_AXIS_STATS[a][0] for a in BIG5_AXES], _cov(BIG5_AXES, BIG5_CORR)), 1, 5)
    return {**dict(zip(MSLQ_AXES, map(float, m))), **dict(zip(BIG5_AXES, map(float, b)))}
