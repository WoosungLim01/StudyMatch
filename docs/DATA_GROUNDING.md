# StudyMatch — Data Grounding

What real, existing research backs our synthetic data design, and what's
still just invented. Written to close the "data selection: create synthetic
data using existing data (research)" gap honestly — some of our design
choices turn out to have real support in the literature; others don't yet,
and this says so plainly rather than overclaiming.

## What's actually grounded in real research

**Similarity, not complementarity, is the right call for compatibility.**
A longitudinal study of a European fraternity found that similarity in
neuroticism and conscientiousness predicted *group formation*, and that
personality similarity predicted *group success* — even after controlling
for each member's own personality. That's real evidence behind the decision
already made in [`algorithm/compatibility.py`](../algorithm/compatibility.py):
compatibility is personality similarity only, with no "opposites attract"
complementarity term. See ["Homophily in Personality Enhances Group Success
Among Real-Life Friends"](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7212830/).

**Conscientiousness is the strongest personality predictor of academic
success in college students**, across multiple studies (e.g. [Frontiers in
Psychology, 2025](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2025.1490427/full),
[PMC12240771](https://pmc.ncbi.nlm.nih.gov/articles/PMC12240771/)). Several of
our 14 traits (`structure`, `accountability`, `preparation`) sit in
conscientiousness's territory — see the mapping table below — but nothing
in the current formula weights them any higher than the rest. That's a real,
specific gap, not just a vague "could be more realistic" — see "What's
missing" below.

**Algorithmic study-group formation at scale has real precedent.**
["Inclusive Study Group Formation At Scale"](https://arxiv.org/pdf/2202.07439)
ran a matching program across a 1000+ student engineering/CS course and found
that students placed in high-comfort, high-quality groups had measurably
improved learning outcomes. Different focus than StudyMatch (their axis was
demographic/equity, not personality), but it's a real, citable precedent for
"algorithmically formed study groups produce better outcomes than chance" —
exactly the hypothesis [`docs/SIMULATION_PLAN.md`](SIMULATION_PLAN.md) exists
to eventually test against our own matching algorithm.

## Where our design diverges from the literature (honestly, not glossed over)

- **Our 14-trait taxonomy isn't Big Five.** Big Five (OCEAN — openness,
  conscientiousness, extraversion, agreeableness, neuroticism) is the
  actual validated framework personality research uses. Our traits
  (`seriousness`, `structure`, `talkativeness`, etc.) were invented for this
  project, loosely inspired by what "matters for a study group" rather than
  derived from or validated against Big Five. See the rough mapping below —
  it's informal, not a validated psychometric crosswalk.
- **The archetype trait templates are hand-picked, not calibrated.** The
  `SUBPOPULATIONS` dict in
  [`generate_sample_data.py`](../data/generate_sample_data.py) (the "planner,"
  "connector," "captain," "loner," "sprinter" trait-value templates every
  synthetic student is sampled around) are numbers I chose because they
  seemed plausible — they aren't derived from any published personality
  distribution.
- **We don't use academic performance at all**, despite real matching-factor
  research suggesting grades/academic performance and study frequency are
  meaningful signals (see ["What kind of matching groups makes students
  benefit more?"](https://www.sciencedirect.com/science/article/pii/S0001691825001386)).
  `academic_profile` only carries `course_confidence`/`target_grade` — no
  actual grade data is collected or used anywhere in matching.
- **Openness has essentially no representative in our trait set.** Looking at
  the mapping below, conscientiousness, extraversion, and agreeableness all
  have multiple traits mapping onto them; openness (curiosity, creativity,
  intellectual engagement) has none. Not something a study-group-fit survey
  obviously needs, but worth naming as a real gap rather than a silent one.

## Rough Big Five mapping (informal — not a validated instrument)

| Our trait | Closest Big Five facet |
|---|---|
| `seriousness`, `preparation` | Conscientiousness — dutifulness / achievement-striving |
| `structure`, `accountability` | Conscientiousness — order / self-discipline |
| `study_pace` | Conscientiousness — deliberation (inverse: fast pace ≈ low deliberation) |
| `social_preference`, `talkativeness` | Extraversion — gregariousness |
| `assertiveness`, `leadership` | Extraversion — assertiveness |
| `communication_frequency` | Extraversion — warmth (partial) |
| `competitiveness` | Low Agreeableness / Extraversion — achievement-striving (contested; could map either way) |
| `helpfulness` | Agreeableness — altruism |
| `collaboration` | Agreeableness — cooperation |
| `patience` | Agreeableness — compliance / low Neuroticism |
| *(none)* | Openness — no current trait maps here |

## What would actually close this gap (not done here — scope call for later)

1. Either (a) relabel/consolidate the 14 traits into an explicit Big Five
   structure, or (b) keep the current 14 but add a documented, defensible
   weighting scheme that gives conscientiousness-adjacent traits more
   influence in `similarity_component()`, citing the academic-performance
   research above as the justification.
2. Calibrate `SUBPOPULATIONS`' trait-template numbers against a real
   published personality distribution instead of hand-picked values — even
   an approximate one (e.g., published Big Five college-population norms,
   translated onto our 1-5 scale) would be a real improvement over "seemed
   plausible."
3. Decide, with citation, whether academic performance/grades should
   actually factor into matching — currently a deliberate simplification,
   not an oversight, but the research above is a real reason to revisit it.

None of the three above are implemented — this document exists to make that
an explicit, citeable decision rather than a silent gap.
