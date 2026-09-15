# StudyMatch — Outcome Simulation Pipeline (planned, not built)

**Status: design only.** Nothing in this document is implemented. Intended to
be built at a late stage, after the core product (login, survey, matching,
placement, admin) is otherwise done — see the [repo root README](../README.md).

## Why this exists

StudyMatch's real feedback loop is slow by nature: you can't know if a
matching algorithm actually produced good study groups until a semester has
played out. Right now, `group_feedback` (satisfaction, retention,
`would_match_again`, ...) is filled with a placeholder formula —
`Normal(mean = 2 + 3 × group_score/100, sd = 0.7)` — which the project's own
docs already admit "carries no predictive signal beyond the correlation it
was built with" (see [`data/README.md`](../data/README.md)).

This pipeline replaces that placeholder with an actual simulation: run the
already-matched synthetic groups through a semester, week by week, and let
each simulated student's behavior (attendance, satisfaction, dropout) emerge
from their real personality traits and their group's real compatibility
data — instead of curve-fit noise. Modeled on
[IdeaLab](https://github.com/)'s NPC-population simulation pattern (deterministic
math doing ~90% of the work, an optional bounded LLM hint for texture), scoped
down to StudyMatch's much simpler shape: no population-wide social graph,
because a student's only social exposure is their fixed 4-5 person group.

**Scope decision (2026-09-14): deterministic only, no LLM, for the first
version.** Free, instant, fully reproducible (same seeded-RNG discipline as
[`generate_sample_data.py`](../data/generate_sample_data.py)) — validates the
mechanism itself before spending on API cost/latency/non-determinism. An LLM
hint layer (IdeaLab's bounded `llm_hint` term) is a plausible v2 addition
later, not part of this plan.

**Target scope when built**: the existing population as-is — both courses,
all 6+ existing groups (27 CMPSC 465 + 7 MATH 230 students), one simulated
semester (proposed: 14 weekly ticks, configurable).

## Concept mapping (IdeaLab → StudyMatch)

| IdeaLab | StudyMatch simulation |
|---|---|
| NPC (30, 8 archetypes) | Student (`personality_profile`, 5 discovered archetypes — already exists) |
| The product idea being tested | The assigned study group (`study_group`, `group_membership`) |
| WorldContext | Course context: semester length, which weeks are exam weeks, workload intensity |
| Tick | One week of the semester |
| Awareness → Reaction → Discussion → Peer Influence → Spread → Adoption | Meeting attendance → satisfaction update → within-group friction → retention decision |
| `interest_score` (0-1, per NPC per tick) | Running `satisfaction` (1-5 scale, per student per week) |
| `adopted` (bool) | `would_match_again` / `left_group` at semester end |
| Convergence tracking (stability/polarization) | Group classified: thriving / stable / eroding / collapsed |
| Population-wide social graph + spread | **Not needed** — a student's social exposure is their own fixed group, nothing spreads beyond it |

## Where it lives

A new top-level `simulation/` package, sibling to `algorithm/` — reuses
`algorithm/compatibility.py`'s scoring rather than duplicating it:

```
simulation/
├── __init__.py
├── world.py           semester config: n_weeks, exam_weeks, workload curve
├── student_state.py   per-student running state across the simulated semester
├── tick.py            the weekly tick loop (phases below)
├── dropout.py         the deterministic per-student retention decision
├── convergence.py     end-of-semester group classification
└── run.py             entry point: loads study_group/group_membership from
                        data/studymatch.db, runs the semester, writes results
                        into group_feedback (replacing the placeholder rows)
```

`run.py` reads from and writes to `data/studymatch.db` directly (same
pattern as `add_student.py`/`build_database.py`) — no new database needed.

## Inputs (all already exist — nothing new to collect)

- `personality_profile` — the 14 traits per student, per course
- `pairwise_compatibility` — every pair's `compatibility_score` (already computed)
- `study_group` / `group_membership` — the actual formed groups
- `availability` / `availability_block` — used to derive attendance probability

## World context (new, minimal)

Per course, a small config (not fed to an LLM in this deterministic version —
"world context" here just means the shared parameters every tick reads):

```
n_weeks: int                  # e.g. 14
exam_weeks: set[int]          # e.g. {6, 7, 14} - attendance dips, stress rises
workload_intensity: dict[int, float]  # per-week multiplier, 0.5-1.5
```

## The weekly tick loop

Each week, for every group independently (groups never interact with each
other — this is the key simplification vs. IdeaLab):

**1. Attendance** (deterministic)
Per member, a probability derived from: their `preferred_sessions_per_week`
vs. how often the group actually meets, modulated down during `exam_weeks`
by `workload_intensity`, and modulated by their `accountability` trait
(higher accountability = shows up even when it's inconvenient). Seeded RNG
(same discipline as `generate_sample_data.py`) decides the actual outcome
per member per week — reproducible, not hand-picked.

**2. Effective group compatibility this week** (deterministic)
Recompute `similarity_component()` (from `algorithm/compatibility.py`) over
only the members who actually showed up — a group where half the members
skip a session effectively "meets" as a smaller, possibly differently-compatible
subgroup that week.

**3. Satisfaction update** (deterministic)
```
satisfaction_delta =
    (this_week_effective_compatibility - running_baseline_compatibility)
  + attendance_delta        # did enough people show up to make it worth it
  - workload_penalty        # exam weeks reduce satisfaction regardless of the group
running_satisfaction = clamp(
    0.8 * running_satisfaction + 0.2 * (running_satisfaction + satisfaction_delta),
    1, 5
)
```
Exponential moving average (the `0.8`/`0.2` split) mirrors IdeaLab's exposure
decay — one bad week shouldn't tank an otherwise-good group's trajectory,
same asymmetric-stability principle as IdeaLab's discussion uplift/downdraft
caps.

**4. Within-group friction propagation** (deterministic, group-scoped)
A member whose `running_satisfaction` drops below a threshold measurably
drags down the group's *shared* baseline compatibility a small amount for
the following week (peers notice a disengaged groupmate) — the group-scoped
analog of IdeaLab's concern propagation, without needing a population graph
since the "peers" here are just the fixed 4-5 group members.

**5. Dropout check** (deterministic, per student, per week)
```
left_group = running_satisfaction < archetype_tolerance_threshold
             AND weeks_elapsed >= min_weeks_before_leaving (e.g. 3)
```
`archetype_tolerance_threshold` varies per discovered archetype (mirrors
IdeaLab's per-archetype adoption thresholds, 0.55-0.70 there) — e.g. an
"Independent Strategist" archetype might tolerate a mediocre group longer
than a "Study Captain" who came in expecting the group to actually perform.

## End of semester

- **`group_feedback` rows generated for real**, matching the exact existing
  schema (`satisfaction_score`, `meetings_attended`, `left_group`,
  `would_match_again`, `group_productivity`, etc.) — no schema change needed,
  just a real generator behind fields that already exist.
- **Convergence classification** per group: thriving / stable / eroding /
  collapsed, from the trajectory shape (steadily high, flat, declining, or
  a cascade of dropouts) — same spirit as IdeaLab's convergence tracking.

## Why this is worth building (beyond "better fake data")

Once this exists, it becomes a **backtesting harness for the matching
algorithm itself**: run the same population through the current
similarity-only matcher vs. an alternative strategy (e.g. reintroducing a
complementarity term, or comparing against pure random grouping — the
project already has all three compatibility bases available:
`compatibility_score`, `study_style_score`, and a random baseline would be
trivial to add), and compare *simulated* semester outcomes before ever
exposing a real student to a worse algorithm. That's the actual point of
building this — not just nicer-looking synthetic data.

## Explicitly deferred (not part of this plan)

- Any LLM involvement (bounded qualitative hints, IdeaLab's V2-style world
  building) — a plausible later addition, decided against for v1 here.
- Population-wide social spread between different groups/courses.
- Anything touching real students — this only ever runs against synthetic
  or already-collected data, offline, and only writes to `group_feedback`.
