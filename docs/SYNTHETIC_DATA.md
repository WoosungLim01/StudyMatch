# StudyMatch — Synthetic Data: Real Datasets and How It's Made

`data/generate_sample_data.py`'s synthetic students are no longer sampled
around hand-picked "archetype template" numbers. Each synthetic student's
6-axis personality profile is one draw from a population distribution whose
means, spreads, and cross-axis correlations come from real, cited data —
not invented ones. This document says exactly which data, and exactly how
the numbers in `REAL_AXIS_STATS` / `MSLQ_CORR` / `BIG5_CORR` (in
`generate_sample_data.py`) were derived, so they can be checked or
re-derived rather than taken on faith.

## The two real datasets

**1. MSLQ-CL validation study** — Fatima, S., Pallath, V., & Hong, W-H.
(2025). *Validation of the Motivated Strategies for Learning Questionnaire
among clinical clerkship students in Malaysia.* PLOS ONE, 20(4), e0319763.
https://doi.org/10.1371/journal.pone.0319763

349 real medical clerkship students completed the 75-item re-specified
MSLQ-CL (7-point Likert, 1=not at all true of me .. 7=very true of me). The
paper's own published Tables 3 and 4 report each subscale's real mean, SD,
and the full inter-subscale correlation matrix for N=349. Files in
`questionary_data/`: `journal.pone.0319763.pdf` (the paper), `.s004.pdf`
(the 75-item bank with subscale assignments and reverse-item markings),
`.s005.xlsx` (raw anonymized per-student responses).

**2. IPIP Big Five Factor Markers** — Open-Source Psychometrics Project,
http://openpsychometrics.org/_rawdata/ (`BIG5.zip`), built from the
International Personality Item Pool's 50-item Big Five markers. 19,719 real
respondents, already on a native 5-point scale (1=Disagree .. 5=Agree — the
same scale StudyMatch's survey uses, no rescaling needed). Published openly
for research/educational reuse. Copied into
`questionary_data/IPIP_BIG5/` (`codebook.txt` + `data.csv`) for
reproducibility.

## Which axis maps to which real construct

| StudyMatch axis | Real source | Construct | Match quality |
|---|---|---|---|
| `planning` | MSLQ-CL | Metacognitive Self-Regulation | Direct — same construct the item bank was built from |
| `reliability` | MSLQ-CL | Effort Regulation | Direct |
| `structure` | MSLQ-CL | Organisation | Direct |
| `intensity` | MSLQ-CL | Self-Efficacy + Task Value (combined) | Direct — matches `algorithm/scoring.py`'s own stated derivation of this axis |
| `session_mode` | IPIP Big Five | Extraversion | **Proxy** — no real dataset measures "talks problems out loud / wants a clear agenda" directly; Extraversion is the closest available real-data stand-in for the verbal/social half |
| `collaboration` | IPIP Big Five | Agreeableness | **Proxy** — closest available real measure of group-helping orientation; not a direct construct match |

## How the numbers were actually derived

**MSLQ-CL axes (`planning`, `reliability`, `structure`, `intensity`):** the
paper's raw per-student item columns (`s005.xlsx`) use a different item
numbering than the subscale item bank (`s004.pdf`) — `s005.xlsx`'s `Qn`
columns go up to `Q81` and include inconsistent `r`-suffixed columns that
don't line up with the "(REVERSED)" markings `s004.pdf` documents for the
same item numbers. Recomputing subscale statistics from the raw file risked
silently mis-mapping items. Rather than guess, the already-published,
peer-reviewed numbers in the paper's own **Table 3** (Motivation scale) and
**Table 4** (Learning Strategies scale) were used directly instead — these
are the paper's own computed means, SDs, Cronbach's alphas, and
inter-subscale Pearson correlations for N=349, not a re-derivation:

| Subscale | Mean (1-7) | SD (1-7) | Median inter-item r |
|---|---|---|---|
| Organisation (`structure`) | 5.01 | 0.98 | 0.403 |
| Metacognitive Self-Regulation (`planning`) | 4.80* | 0.92 | 0.414 |
| Effort Regulation (`reliability`) | 4.68 | 1.05 | 0.280 |
| Self-Efficacy | 4.76 | 0.93 | 0.534 |
| Task Value | 5.66 | 0.81 | 0.477 |

\* Table 4 prints this mean as "0.48," which is out of the stated 1.00-7.00
range and inconsistent with every other subscale in the table (all 4.6-5.7)
— almost certainly a missing leading digit in the published table. Read as
4.80 (consistent with the range and the pattern of the other Learning
Strategies subscales); flagged here rather than silently assumed.

`intensity` combines Self-Efficacy (8 items) and Task Value (6 items) per
`algorithm/scoring.py`'s own design. Its mean/SD were derived by weighting
the two subscales by item count and combining their variances using the
paper's reported Self-Efficacy/Task-Value correlation (0.598):
`mean = (8×4.76 + 6×5.66)/14 = 5.15`, `SD = 0.79` (standard variance-of-sum
formula with the real correlation, not assumed independence).

All four means/SDs were then rescaled from the paper's 1-7 scale to
StudyMatch's 1-5 scale with `new = 1 + (old − 1) × 4/6` (a linear scale
transform — assumes the two scales' endpoints correspond proportionally,
which is the standard approach but still an assumption, not a measured
equivalence).

**Real correlations used** (Pearson, from Table 4, scale-invariant so no
rescaling needed): `planning`-`reliability` = 0.482, `planning`-`structure`
= 0.679, `reliability`-`structure` = 0.421. `intensity`'s correlation with
the other three is **not available** — Table 3 (Motivation) and Table 4
(Learning Strategies) each report correlations only *within* their own
scale, never across the two. `intensity` is therefore sampled independently
of the other three MSLQ-derived axes — a real, stated limitation, not an
oversight.

**Item-level noise** (how much an individual item answer should wander from
its axis's target) was derived from each subscale's median inter-item
correlation `r̄` and SD, using the standard compound-symmetry relationship
for `k` equally-correlated items: `item_sd = sqrt(SD² × k / (1 + (k−1)r̄))`,
then the noise around a *respondent's own* subscale mean specifically is
`item_sd × sqrt(1 − r̄)`, rescaled the same 1-7→1-5 way. This is why each
axis has its own item-noise value in `REAL_AXIS_STATS` instead of one flat
guessed constant.

**BIG5 axes (`session_mode`, `collaboration`):** no numbering ambiguity —
`data.csv`'s `E1`-`E10` (Extraversion) and `A1`-`A10` (Agreeableness)
columns are unambiguous and match the published codebook exactly. Reverse
items (`E2,E4,E6,E8,E10` and `A1,A3,A5,A7`, per the codebook) were flipped
with `6 − raw`, each respondent's two subscale means and the real
item-noise SD were computed directly from the 19,718 usable rows — no
re-publishing of someone else's summary table needed here, the raw data
was trustworthy enough to compute from directly:

| | Mean | SD | Item-noise SD | Real correlation |
|---|---|---|---|---|
| Extraversion (`session_mode`) | 3.011 | 0.922 | 0.982 | 0.334 (with Agreeableness) |
| Agreeableness (`collaboration`) | 3.845 | 0.715 | 0.885 | |

## The sampling model

Per synthetic student, `generate_sample_data.py`'s `sample_axis_targets()`
draws two **independent** multivariate-normal samples (not five discrete
archetype templates anymore):

- `(planning, reliability, structure, intensity)` from a 4-D normal with the
  real means/SDs above and the real 4×4 correlation matrix (`intensity`
  uncorrelated with the other three, per the limitation above), clipped to
  [1, 5].
- `(session_mode, collaboration)` from a 2-D normal with the real BIG5
  means/SDs and their real 0.334 correlation, clipped to [1, 5].

Then `sample_survey_responses()` draws each of the 24 raw item answers
around its axis's sampled target using that axis's own real item-noise SD,
reverse-encoding exactly as a real respondent's stored answer would be
(raw-as-answered, not pre-flipped) — same mechanism as before, just fed by
real statistics instead of a hand-picked table. Everything downstream
(`score_axes()`, archetype classification, pairwise compatibility, ILP
grouping) is unchanged — this redesign only touches how the *input* to that
pipeline is generated.

## Known limitations (stated, not hidden)

- **No real joint data links the two blocks.** Nobody has published a study
  where the same people answered both MSLQ and a Big Five instrument *and*
  reported the correlations — so `session_mode`/`collaboration` are sampled
  completely independently of `planning`/`reliability`/`structure`/
  `intensity`. A real synthetic person's "talks it out loud" score has no
  real-data-backed relationship to their "plans ahead" score, even though
  one might plausibly exist.
- **`session_mode` and `collaboration` are proxies, not construct matches.**
  Extraversion and Agreeableness are the closest *available* real data, not
  a validated measure of "prefers talking through problems out loud" or
  "learns by explaining to others." Treat these two axes as less rigorously
  grounded than the other four.
- **Population mismatch.** The MSLQ data is from Malaysian medical
  clerkship students; the BIG5 data is from self-selected online
  personality-test takers. Neither is Penn State CMPSC/MATH undergrads.
  Using them makes the synthetic population's *shape* (spread, skew, how
  traits co-vary) realistic, not its *content* representative of
  StudyMatch's actual target population — same caveat as
  [`docs/DATA_GROUNDING.md`](DATA_GROUNDING.md) already states for the
  survey items themselves.
- **The 7-point → 5-point rescale is a linear assumption**, not a measured
  equivalence between the two scales.
- **The Table 4 "0.48" mean was corrected to 4.80** based on range and
  pattern, not confirmed with the authors — see above.

## Reproducing or updating these numbers

The source files are in `questionary_data/` (`journal.pone.0319763.*` for
MSLQ, `IPIP_BIG5/` for Big Five) — both committed to the repo so the
derivation above can be checked or redone. The MSLQ figures come from
reading Tables 3-4 directly out of the paper PDF (no script, since the raw
per-item file's numbering couldn't be trusted — see above); the BIG5
figures are reproducible by running the same reverse-code-and-average logic
described above over `IPIP_BIG5/data.csv`. If `s005.xlsx`'s true item
numbering is ever confirmed (e.g. by finding an explicit original→
re-specified item crosswalk), the MSLQ axes could be recomputed directly
from raw per-item data the same way the BIG5 axes already are, including
real item-to-item correlations within each subscale instead of the
compound-symmetry approximation used now.
