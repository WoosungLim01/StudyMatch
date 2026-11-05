# StudyMatch Simulation: Results

DS 440 capstone, Penn State. Simulation work through 2026-10-29.

## Summary

- We tested the StudyMatch pipeline (survey matching plus weekly feedback and regrouping) on a synthetic cohort of 1,000 students over a 14-week semester, in three simulated worlds that decide how students feel in different ways: our own formulas, a language model judging each week, and a language model that first writes out what happened at every meeting.
- In every world, regrouping on feedback reduced unhappiness and quitting compared with leaving groups alone. In the full-scale formula world the share of unhappy students at week 14 fell from 25% to 12%; in the two LLM worlds, on a 100-student sample, from 70% to 42% and from 95% to 53%.
- Learning weights from feedback added a further gain only at full scale (1,000 students). With 100 students the learner never saw enough forms to pass its own evidence test, so survey-only and the full pipeline tied in all three worlds.
- The language model, given the facts but not our formulas, agrees with them on what matters most: groupmates who don't show up and schedules that don't line up. It reacts far less to personality fit, and the meeting-writing version runs much harsher than the formulas because its base rates follow the wording of its instructions.
- None of this is evidence about real students. The simulation shows that the pipeline does what it was designed to do under two independent sets of assumptions; only feedback from the deployed app can show whether students behave this way.

## What was simulated

**Cohort.** 1,000 synthetic students, 500 in CMPSC 465 and 500 in MATH 230, with survey answers calibrated on the real survey's item statistics, weekly schedules, and a hidden truth per student: their true position on the six study-style axes (planning, session mode, reliability, structure, intensity, collaboration), how sensitive they are to each, how much they mind no-shows and schedule clashes, how leniently they rate others, and how often they answer forms. The 36 real users of the app are excluded entirely.

**One week.** Each group holds its planned meetings; who comes is drawn from each member's reliability, schedule fit, exam weeks and current mood. The world then decides how each student feels about the week, on a 1 to 5 scale. From that come leaving (below 2.4 at two week-ends in a row), the weekly form (answered by about 60% and falling, rated a little generously, with "would you keep this group?", up to two complaints and a groupmate to avoid when the rating is low), and every fourth week a check-in with peer ratings of reliability and helpfulness.

**Three strategies, played side by side on the same chance events.** *Stay*: never regroup; quitters stay without a group. *Survey*: regroup using the survey answers and hand-set weights. *Learn* (the full pipeline): the same regrouping, but the matcher updates its profiles from peer ratings and complaints and refits its weights when the feedback supports it. The regrouping policy, chosen by a separate sweep, moves unhappy students every two weeks after one "I'd rather switch" answer, with at least two weeks in a group first and no moves after week 11; quitters are placed every week.

**Metrics.** True satisfaction is the hidden 1 to 5 value, averaged over all students, counting a student without a group at 2.0. "Unhappy" means below 3.

## The three worlds

The worlds differ in one function: who decides how a student felt about the week. Everything else, attendance draws, forms, learner and regrouping, is identical.

**V0, rule-based.** Our formula: discomfort from style gaps to the groupmates who came, from groupmates who didn't, and from schedule clashes, each weighted by the student's hidden sensitivities, with the running satisfaction moving 30% of the way toward each meeting's result. Free, deterministic given the seed, and an encoding of our own assumptions.

**V1, LLM judge.** Claude Haiku 5.5 receives, per group and week, each member as a letter with their true traits, the sessions they want, how much free time they share with the group, how they felt last week, and who came to each meeting. It never sees names, the compatibility score, our formula's number, or any hint of what students should care about. It returns for each student a satisfaction from 1.0 to 5.0, up to two complaint codes from the form's own list, a groupmate to avoid, and a one-sentence note in the student's voice. Each group is asked three times in independent calls and the scores are averaged, which halves the model's sampling noise. The average is held within 1.2 of the formula's value as a safety net; the net touched 0% of verdicts.

**V2, LLM with simulated meetings.** Before judging, the model writes a three-to-five-sentence account of every meeting with at least two people present, given the same facts plus the previous meeting's account, under instructions that say which traits drive what (unreliable members arrive unprepared, strong explainers lead and talk over others, the quietest fall behind, a wide gap on structure means a clash, no planner means drift) and how often meetings go well or badly. With the account it labels each member's experience and whether the meeting made them more or less willing to come back; that label multiplies their attendance chance the following week. The judge then reads the accounts instead of a bare attendance list. Each strategy keeps its own meeting memory, and a meeting nobody attended does not erase it.

## Validating the LLM worlds

A language model's judgement has no formula to inspect, so it was tested from outside, the way a survey instrument is: hold everything fixed, change one thing, see what moves. The main probe holds the same 100 students in fixed groups for four weeks and compares conditions. A t value of 2 or more means the gap is unlikely to be chance.

| Check | V0 rule-based | V1 LLM judge | V2 LLM with meetings |
|---|---|---|---|
| Reliable students prefer reliable groupmates | 3.66 vs 2.45, t 11.0 | 3.35 vs 2.57, t 7.2, passes | 3.02 vs 2.49, t 2.3, not valid* |
| Overlapping schedules beat none | 3.59 vs 2.96, t 10.1 | 3.30 vs 3.07, t 5.9, passes | 2.86 vs 2.86, t 0.0, fails |
| Matched groups beat random ones | 3.59 vs 3.35, t 2.2 | 3.30 vs 3.27, t 0.6, fails | 2.86 vs 2.77, t 0.9, fails |
| Plausible week 4 (5 to 35% unhappy) | 14% | 16%, passes | 59%, fails |
| Correlation with the formula's value, mean offset | | 0.55, −0.12 | 0.65, −0.29 |
| Safety net changed the value | | 0.0% of verdicts | 1.5% |
| Wobble between repeated asks, one ask / average of three | | 0.12 / 0.07 | 0.13 / 0.07 |
| Matched groups, week 1 to week 4 | 3.64 to 3.59 | 3.59 to 3.30 | 3.44 to 2.93 |
| Top complaints | no-shows 53%, schedules 23% | no-shows 50%, schedules 26% | no-shows 27%, more explaining 18%, more structure 16% |

\* The run's budget ran out during this probe, so the flaky groups' week-4 verdicts came from the formula; the comparison mixes two worlds and is not reported as a pass.

What this says: V1 reproduces the two effects every student would recognize, no-shows and schedules, and its complaint mix matches the formula's, but it barely distinguishes a well-matched group from a random one. V2 was built to make personality visible, and its complaints do shift from attendance to planning, structure and explaining; but it runs far harsher than the formula, loses the schedule effect, and still does not separate matched from random groups. Letter order does not affect the model's answers, and averaging three asks makes the scores stable enough to compare weeks.

## Results

### Full scale: the formula world, 1,000 students, 10 seeds

| | Stay | Survey | Learn (pipeline) |
|---|---|---|---|
| Unhappy at week 14 | 25% | 19% | 12% |
| Semester-average satisfaction | 3.46 | 3.57 | 3.61 |
| Students who quit a group (per semester) | 95 | 74 | 40 |
| Students moved | 0 | 638 | 514 |

Regrouping on the survey alone removes a quarter of the unhappiness; learning from feedback removes half, with fewer moves. The learner's weights ended with reliability largest and the schedule weight, which the live matcher sets to zero, second largest: feedback taught the matcher that schedules matter. Tuning changed the weights in week 2 and stopped by week 5, because later refits no longer predicted the next week's forms better than chance.

**How often to regroup.** Moving unhappy students every two weeks matched moving them every week (3.62 vs 3.62) with a quarter fewer moves; every four weeks scored 3.58 and never regrouping 3.50. Acting on the first "I'd rather switch" answer beat waiting for a second by 0.07.

### Three worlds, the same 100 students, 2 seeds

| | V0 rule-based | V1 LLM judge | V2 LLM with meetings |
|---|---|---|---|
| Unhappy at week 14: stay / survey / pipeline | 18% / 17% / 19% | 70% / 44% / 42% | 95% / 59% / 53% |
| Semester-average satisfaction | 3.56 / 3.62 / 3.61 | 3.05 / 3.27 / 3.27 | 2.60 / 3.12 / 3.12 |
| Quit a group, of 100 | 6 / 4 / 5.5 | 31.5 / 8 / 9 | 81 / 53 / 50.5 |
| Students moved | 0 / 66 / 64 | 0 / 126 / 123 | 0 / 237 / 250 |
| API cost | none | $3.41 | $2.97 |

Three readings. First, regrouping helps in every world, and most where the world is harshest: in V2, leaving groups alone ends with four students in five gone or unhappy, and the pipeline halves that. Second, the learning step adds nothing at this size in any world, including the formula world where it clearly helps at 1,000 students: with 100 students the learner never accumulates the 35 past forms and 20 current forms its evidence test requires, so it keeps the hand-set weights. That is a sample-size limit, not a property of the LLM worlds. Third, levels are not comparable across worlds, only orderings: the LLM worlds rate harsher than the formula and drift down over the weeks, and V2's level is set largely by the base rates written into its meeting instructions.

## What the simulation says about real students

Both LLM worlds are what the research literature calls silicon samples: a model is given a persona, here six trait numbers and a few facts, and answers as that person would, and the collection of answers is treated like a survey sample. Argyle and colleagues (2023) showed that persona-prompted models can reproduce real survey patterns; Aher, Arriaga and Kalai (2023) proposed judging such simulations by whether they replicate effects already known in humans; Park and colleagues built interacting generative agents (2023) and, in 2024, agents from interviews that matched people's own survey answers about as well as the people matched themselves two weeks later; Törnberg and colleagues (2023) simulated a social network with model-driven users to compare ranking algorithms before deployment, the closest precedent for using simulated users to test a matching system. Later work also documented the limits: too little variance (Bisbee and colleagues, 2024), sensitivity to prompt wording, and a drift toward caricature (Cheng, Durmus and Jurafsky, 2023).

Our results sit inside those findings. The model responds strongly to concrete events and weakly to subtle dispositions; its mood follows our wording; its answers wobble and need averaging. The validation method we used is the one that literature recommends, with one honest difference: our known effects come from our own formula world, not from real students. The silicon-sample papers used GPT-3; we used Claude Haiku 5.5, a far stronger and cheaper model, about a tenth of a cent per call, but the limits we observed are limits of the method, not of model size, and we did not test larger models.

## Limitations

- The cohort is synthetic. Its personalities are calibrated on real survey statistics, but how those traits turn into satisfaction is assumed, either by our formula or by a language model.
- The LLM runs use 100 students and 2 seeds, enough to see orderings, not enough for the learning step or for small differences between strategies.
- V2 is uncalibrated: its instructions make most meetings dull or worse, which drives its harshness. Its one passed validation check is invalid because the run's budget cut in, and the reason its schedule effect vanished is not yet understood.
- The simulation has no grades or course performance by design; a week says nothing about learning outcomes.
- Satisfaction levels differ by world; comparisons across worlds should use orderings and effects, not percentages.

## Next steps

1. Calibrate the meeting instructions (base rates, schedule friction) and rerun the four-week probe, about $2, then the V2 semester again.
2. Run the LLM judge on a larger sample, 300 to 500 students, to see whether the learning gain appears there as it does in the formula world (roughly $10 to $20).
3. For the product: add peer ratings and the two complaint questions (what would make the group better, and whom to avoid) to the real feedback form; they are what the learner uses. Consider giving schedule fit a non-zero weight in the live matcher.
4. Collect the deployed app's real feedback; it is the only validation that bears on real students, and the simulation gives it something to be compared against.

## Appendix: costs and reproduction

A judge call averages about 2,000 input and 1,300 output tokens, about $0.0009; an account call about the same. A 100-student semester costs about $3 to $5 fresh, less with cached answers; the whole LLM effort so far cost about $13. Every call is cached by its exact input, so reruns are free and reproducible. Commands: `python -m simulation.run` (formula world, 10 seeds), `python -m simulation.run --world llm-1.2 --sample 50 --seeds 2` (V1), `--world meet-1.2` (V2), `python -m simulation.calibrate` and `--world meeting` (validation), `python -m simulation.live` (the interactive page with the world switch). Outputs: `simulation/output/` with a dashboard per run.
