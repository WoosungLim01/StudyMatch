# StudyMatch — Data Layer Handoff

This describes the data StudyMatch collects and stores — what a matching
algorithm should be built against. The matching/grouping step itself is
currently a random placeholder (see the last section). Building the real one
is your part.

## The survey

Every student fills out one screen, once, before they ever see their group:
name, course, year/gender/major, then **24 statements** rated on a 5-point
Likert scale — Strongly Disagree, Disagree, Neutral, Agree, Strongly Agree —
with no option pre-selected. Optional availability and academic-goal sections
follow (off by default; nothing recorded unless the student switches them on).

The 24 statements are grouped into **6 axes, 4 statements each**. A few items
are worded in the opposite direction of their axis (marked reverse below) —
these are stored exactly as answered, then flipped during scoring, not
flipped at collection time.

**planning** — plans ahead / self-monitors study strategy
1. I set clear goals for what I want to accomplish before I start studying.
2. I notice when a study strategy isn't working and switch to something else.
3. I check my own understanding as I go, instead of waiting for a quiz to find out.
4. I rarely stop to think about whether my approach to studying is actually working. *(reverse)*

**session_mode** — talks through problems out loud / wants a clear agenda, vs. quiet and open-ended
5. I prefer sessions where we talk through problems out loud together.
6. I'd rather work through material quietly on my own, even in a group setting. *(reverse)*
7. I like sessions that follow a clear agenda rather than open-ended discussion.
8. I do better in loosely structured sessions where the conversation can wander. *(reverse)*

**reliability** — follows through, shows up prepared
9. Even when material is dry, I make myself keep working through it.
10. I keep working on something difficult instead of giving up on it.
11. I show up to group sessions having done what I said I would beforehand.
12. I've flaked on a study commitment to my group before. *(reverse)*

**structure** — organizes material and likes sessions to follow a plan
13. I outline or organize material before diving into the details.
14. I keep my study materials organized so I can find what I need quickly.
15. I like group sessions to follow a set structure or checklist.
16. I'm fine with sessions that don't have a clear plan going in. *(reverse)*

**intensity** — confidence and how much the course itself matters to them
17. I'm confident I can understand the most complex material in this course.
18. I believe I can do well in this course if I apply myself.
19. I care about understanding the material, not just getting a good grade.
20. Compared to others in this course, I don't think I'm very capable. *(reverse)*

**collaboration** — learns by teaching vs. prefers to work things out alone first
21. I learn material best by explaining it to someone else.
22. I'd rather listen to someone explain it than explain it myself. *(reverse)*
23. I'm comfortable being the person who answers the group's questions.
24. I'd rather attempt problems alone first and bring questions to the group. *(reverse)*

The item bank and reverse flags live in code (not just this doc) at
[`algorithm/scoring.py`](../algorithm/scoring.py), so it can't drift out of
sync with what's actually being asked.

## From raw answers to axis scores

Each of the 5 on-screen options maps to a fixed raw value — this is exactly
what gets stored in `survey_response.response`, regardless of whether the
item is a normal or reverse-worded one:

| Option (shown to the student) | Raw value stored |
|---|---|
| Strongly Disagree | 1 |
| Disagree | 2 |
| Neutral | 3 |
| Agree | 4 |
| Strongly Agree | 5 |

[`algorithm/scoring.py`](../algorithm/scoring.py)'s `score_axes()` then turns
those 24 raw answers into 6 axis scores: for items marked `reverse: True`, it
flips the raw value with `6 - raw` *before* averaging — because agreeing with
a negatively-worded statement should count against the trait, not for it. For
normal items the raw value is used as-is. Either way, the 4 items belonging
to an axis are then averaged into a single 1.0-5.0 float.

| Option | Raw | Contribution — normal item | Contribution — reverse item (`6 - raw`) |
|---|---|---|---|
| Strongly Disagree | 1 | 1 (lowest) | 5 (highest) |
| Disagree | 2 | 2 | 4 |
| Neutral | 3 | 3 | 3 (unchanged — the fixed point) |
| Agree | 4 | 4 | 2 |
| Strongly Agree | 5 | 5 (highest) | 1 (lowest) |

Concretely, for `planning` (items 1-4, item 4 is reverse): raw answers
`[4, 4, 4, 1]` score as `[4, 4, 4, 6-1=5]`, averaging to `4.25`. The raw
answer is always what's stored in `survey_response` — the direction-corrected
("scored") value only exists at scoring time and never overwrites it, so the
UI never hints at reverse-coding and the stored raw data stays an honest
record of what was actually clicked.

This scoring runs identically whether the student is real (submitted through
`ui/survey.html` -> `app.py`) or synthetic (`data/generate_sample_data.py`),
so every row in `personality_profile` means the same thing regardless of
where it came from.

## Schema reference (SQLite, `data/studymatch.db`)

- **`student`**, **`course_membership`** — identity and course enrollment.
- **`personality_profile`** *(student_id, course_id, planning, session_mode,
  reliability, structure, intensity, collaboration, archetype_id,
  preferred_role)* — the 6 axis scores. This is almost certainly what you'll
  score matching on.
- **`survey_response`** *(student_id, course_id, item_number 1-24, response
  1-5)* — the raw answers behind those scores, kept for auditing or if you
  ever want to weight individual items instead of axis averages.
- **`archetype`** — 5 descriptive clusters (e.g. "Study Captain", "Focused
  Architect") discovered by KMeans over the 6 axes, purely for display/
  labeling. Not used to decide who groups with whom — safe to ignore, or use
  as a feature if it's useful to you.
- **`availability`**, **`availability_block`**, **`academic_profile`** —
  schedule preferences and course-confidence/target-grade. Collected and
  populated for every student, but nothing currently reads them when forming
  groups. Real signal if you want to use it.
- **`pairwise_compatibility`**, **`study_group`**, **`group_membership`**,
  **`match_data`** — where a real algorithm's output needs to land: a score
  per pair, the groups themselves (capped at 5 members), who's in which
  group, and the recommendation records shown to students still waiting.

Full column-by-column schema: [`data/schema.sql`](../data/schema.sql).

## Where to actually browse the data

- **`data/studymatch-data-browser.html`** — double-click to open in any
  browser, no server needed. Has a "Personality Survey" table (the 6 axis
  scores per student) and a "Survey Responses (raw)" table (all 24 raw
  answers, with the item text, axis, and both the raw and reverse-corrected
  "Scored" value shown side by side — useful for seeing exactly how a score
  was derived). Rebuild it after any data change with `python
  data/build_viewer.py`.
  **This file is a static snapshot of the synthetic sample data only**
  (baked in at build time from `data/sample/*.json`). It does **not** include
  real students who sign up through the running app, and won't update itself
  when they do.
- **Real records** (anyone who actually went through `/login` -> `/survey`
  live) only exist in `data/studymatch.db` — open it directly in **DBeaver**
  (or DB Browser for SQLite) and query `personality_profile` /
  `survey_response` there. That's the only place real submissions show up.

## The algorithm is a placeholder right now — this is what's left

`algorithm/compatibility.py`'s `pair_compatibility()` currently returns a
**random number** instead of a real score. Group formation
(`data/generate_sample_data.py`'s `form_groups()` for the synthetic batch,
`algorithm/placement.py`'s `_form_full_groups()` and its remainder logic for
live signups) just **shuffles students and chunks them into groups of 5** —
it doesn't look at `personality_profile` at all. This exists only so the rest
of the app (schema, the post-signup message, the home/admin pages) has
something to run against while the real algorithm gets built.

What to replace:
- `pair_compatibility()` in `algorithm/compatibility.py` — should compute a
  real score from two students' 6 axis values (and optionally their
  availability/academic data) instead of `random.uniform(40, 95)`.
- `form_groups()` in `data/generate_sample_data.py` and the grouping logic in
  `algorithm/placement.py` — should use that real score to decide who groups
  with whom, instead of a random shuffle.

What to keep as-is: groups are capped at exactly 5 members; matching is
scoped per course (never cross-course); `similarity_component()` in
`algorithm/compatibility.py` already computes real personality-axis
closeness (it's just not wired into `pair_compatibility()` right now) —
worth a look before writing new math from scratch.
