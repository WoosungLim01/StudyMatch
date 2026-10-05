# StudyMatch — Data Grounding

What published research supports in our data design, and what is still a judgment call. This document says where the gaps are rather than hiding them.

The earlier version of this document analyzed a 14-trait instrument that has since been replaced. That version is in git history.

## The survey and its axes

The 24-item survey covers six axes, four items each. Four axes (`planning`, `reliability`, `structure`, `intensity`) use items drawn from validated MSLQ subscales. Two axes (`session_mode`, `collaboration`) are StudyMatch-specific, because MSLQ has no group-study subscale. The item bank and reverse-coding are in [`algorithm/scoring.py`](../algorithm/scoring.py). How the synthetic population was calibrated, and its limitations, are in [`SYNTHETIC_DATA.md`](SYNTHETIC_DATA.md).

## What research supports

- **Similarity over complementarity.** A longitudinal study of a European fraternity found that similarity in neuroticism and conscientiousness predicted group formation, and that personality similarity predicted group success even after controlling for each member's own personality. This supports the similarity-only compatibility score. See [Homophily in Personality Enhances Group Success Among Real-Life Friends](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7212830/).
- **Conscientiousness predicts academic success.** Several studies find it to be the strongest personality predictor of college academic performance ([Frontiers in Psychology, 2025](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2025.1490427/full), [PMC12240771](https://pmc.ncbi.nlm.nih.gov/articles/PMC12240771/)). The `reliability` and `structure` axes are conscientiousness-adjacent. The research supports the importance of these traits, but not the specific 1.5× weight on `reliability` and `intensity` in compatibility, which is a design judgment.
- **Algorithmic study-group formation has precedent.** ["Inclusive Study Group Formation At Scale"](https://arxiv.org/pdf/2202.07439) matched students in a 1000+ student engineering and CS course and found that students placed in high-comfort, high-quality groups had better learning outcomes. Its focus was demographic equity rather than personality, but it supports the hypothesis that algorithmic grouping beats chance.

## What is not grounded

- **`session_mode` and `collaboration`** are calibrated on Big Five Extraversion and Agreeableness as proxies. No available dataset measures "talks problems through out loud" or "learns by explaining" directly.
- **Population mismatch.** The MSLQ calibration data comes from Malaysian medical clerkship students, and the Big Five data from self-selected online test-takers. Neither is Penn State undergraduates. The population's shape (spread, skew, how traits co-vary) is realistic, but its content may not represent StudyMatch's users.
- **The 7-point to 5-point rescale** of the MSLQ means assumes the scales map linearly. That's a standard approach, not a measured equivalence.
- **Academic performance is not used.** Matching research suggests grades and study frequency matter ([What kind of matching groups makes students benefit more?](https://www.sciencedirect.com/science/article/pii/S0001691825001386)). StudyMatch doesn't collect grades. `academic_profile` holds only course confidence and target grade. This is a deliberate simplification.
- **No outcome data yet.** Nothing validates that similarity-based groups produce better outcomes for StudyMatch students. The planned simulation ([`SIMULATION_PLAN.md`](SIMULATION_PLAN.md)) and real feedback would close this gap.
- **Openness is not measured.** Curiosity, creativity, and intellectual engagement have no axis. That's probably fine for study-group fit, but it's a real gap.

## Open decision

Whether academic performance should factor into matching. The research above is the reason to revisit it. Record the decision and its citation before the report is final.
