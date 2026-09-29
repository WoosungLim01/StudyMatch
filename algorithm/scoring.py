"""
StudyMatch — entry survey item bank + Likert scoring.

The entry survey (ui/survey.html) is a fixed 24-item, 5-point Likert
instrument — "Version 3" (the recommended blend) from
references/StudyMatch_Survey_Redesign_3_Versions...: 6 axes x 4 items each.
Items are pulled from validated MSLQ subscales where one exists
(metacognitive self-regulation -> planning, effort regulation + a couple of
original items -> reliability, organization -> structure, self-efficacy +
task value -> intensity) and kept as original StudyMatch items where MSLQ has
no equivalent (session_mode, collaboration - MSLQ has no group-study-behavior
subscale). Reverse-worded items are marked reverse=True and are stored RAW
(as answered) in survey_response; only score_axes() flips them.

score_axes() turns 24 raw 1-5 answers into the 6 axis values
personality_profile stores. Used by BOTH the live /api/survey endpoint
(app.py) and generate_sample_data.py, so real and synthetic students are
scored identically — see algorithm/compatibility.py's docstring for how the
resulting axis values feed into matching.
"""

AXES = ["planning", "session_mode", "reliability", "structure", "intensity", "collaboration"]

LIKERT_MIN = 1
LIKERT_MAX = 5
REVERSE_CONSTANT = LIKERT_MIN + LIKERT_MAX  # 6: reverse_code(1)=5, reverse_code(5)=1

# id, axis, reverse-coded?, item text (verbatim from Version 3 of the reference doc).
SURVEY_ITEMS = [
    {"id": 1, "axis": "planning", "reverse": False,
     "text": "I set clear goals for what I want to accomplish before I start studying."},
    {"id": 2, "axis": "planning", "reverse": False,
     "text": "I notice when a study strategy isn't working and switch to something else."},
    {"id": 3, "axis": "planning", "reverse": False,
     "text": "I check my own understanding as I go, instead of waiting for a quiz to find out."},
    {"id": 4, "axis": "planning", "reverse": True,
     "text": "I rarely stop to think about whether my approach to studying is actually working."},

    {"id": 5, "axis": "session_mode", "reverse": False,
     "text": "I prefer sessions where we talk through problems out loud together."},
    {"id": 6, "axis": "session_mode", "reverse": True,
     "text": "I'd rather work through material quietly on my own, even in a group setting."},
    {"id": 7, "axis": "session_mode", "reverse": False,
     "text": "I like sessions that follow a clear agenda rather than open-ended discussion."},
    {"id": 8, "axis": "session_mode", "reverse": True,
     "text": "I do better in loosely structured sessions where the conversation can wander."},

    {"id": 9, "axis": "reliability", "reverse": False,
     "text": "Even when material is dry, I make myself keep working through it."},
    {"id": 10, "axis": "reliability", "reverse": False,
     "text": "I keep working on something difficult instead of giving up on it."},
    {"id": 11, "axis": "reliability", "reverse": False,
     "text": "I show up to group sessions having done what I said I would beforehand."},
    {"id": 12, "axis": "reliability", "reverse": True,
     "text": "I've flaked on a study commitment to my group before."},

    {"id": 13, "axis": "structure", "reverse": False,
     "text": "I outline or organize material before diving into the details."},
    {"id": 14, "axis": "structure", "reverse": False,
     "text": "I keep my study materials organized so I can find what I need quickly."},
    {"id": 15, "axis": "structure", "reverse": False,
     "text": "I like group sessions to follow a set structure or checklist."},
    {"id": 16, "axis": "structure", "reverse": True,
     "text": "I'm fine with sessions that don't have a clear plan going in."},

    {"id": 17, "axis": "intensity", "reverse": False,
     "text": "I'm confident I can understand the most complex material in this course."},
    {"id": 18, "axis": "intensity", "reverse": False,
     "text": "I believe I can do well in this course if I apply myself."},
    {"id": 19, "axis": "intensity", "reverse": False,
     "text": "I care about understanding the material, not just getting a good grade."},
    {"id": 20, "axis": "intensity", "reverse": True,
     "text": "Compared to others in this course, I don't think I'm very capable."},

    {"id": 21, "axis": "collaboration", "reverse": False,
     "text": "I learn material best by explaining it to someone else."},
    {"id": 22, "axis": "collaboration", "reverse": True,
     "text": "I'd rather listen to someone explain it than explain it myself."},
    {"id": 23, "axis": "collaboration", "reverse": False,
     "text": "I'm comfortable being the person who answers the group's questions."},
    {"id": 24, "axis": "collaboration", "reverse": True,
     "text": "I'd rather attempt problems alone first and bring questions to the group."},
]

ITEMS_BY_AXIS = {axis: [it for it in SURVEY_ITEMS if it["axis"] == axis] for axis in AXES}


def reverse_code(raw):
    return REVERSE_CONSTANT - raw


def score_axes(responses):
    """
    responses: dict {item id (1-24): raw 1-5 answer}.
    Returns dict {axis: mean of that axis's 4 items (reverse-coded where
    marked), rounded to 2 decimals, still on the 1-5 scale}.
    """
    missing = [it["id"] for it in SURVEY_ITEMS if it["id"] not in responses]
    if missing:
        raise ValueError(f"Missing survey responses for item(s): {missing}")

    scores = {}
    for axis in AXES:
        vals = [
            reverse_code(responses[it["id"]]) if it["reverse"] else responses[it["id"]]
            for it in ITEMS_BY_AXIS[axis]
        ]
        scores[axis] = round(sum(vals) / len(vals), 2)
    return scores
