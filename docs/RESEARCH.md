# Research: does StudyMatch help?

A summary of how StudyMatch has been evaluated so far, taken from the team's DS 440 Report 5 (November 2026). No real StudyMatch groups have run a full semester yet, so most of the evidence is from simulation. Everything below says which kind of evidence it is.

## 1. Semester simulation (synthetic students)

A 14-week simulation of 1,000 synthetic students, whose survey answers are calibrated on public survey data (see [`SYNTHETIC_DATA.md`](SYNTHETIC_DATA.md)). Each week, every student's satisfaction is judged either by fixed formulas (the rule-based world) or by a language model.

**Regrouping on weekly feedback, rule-based world, 1,000 students, 10 seeds:**

| | Keep the first groups | Regroup on the survey | Regroup and learn weights |
|---|---|---|---|
| Unhappy at week 14 | 25% | 19% | 12% |
| Semester-average satisfaction (1–5) | 3.46 | 3.57 | 3.61 |
| Students who quit a group | 95 | 74 | 40 |
| Students moved | 0 | 638 | 514 |

**Matched vs. random groups:**

- Rule-based world: matched groups were more satisfied than random groups of the same sizes in all ten seeds of a four-week check (3.51 vs. 3.22). Over one 14-week semester (one seed), 24% of students in matched groups ended unhappy, against 45% in random groups.
- Language-model judge (100 students, 2 seeds): 3.30 vs. 3.27 (t = 0.6). With simulated meetings: 2.86 vs. 2.77 (t = 0.9). **Neither separated matched groups from random ones.**
- Regrouping helped in both language-model worlds: unhappy students at week 14 fell from 70% to 44%, and from 95% to 59%.

**What this does and doesn't show.** The rule-based world contains a study-style term by construction, so its matched-vs-random advantage is partly built in. The robust finding is that regrouping on feedback helps. Whether matching itself helps is the main open question for the pilot. The learning step only activates at about 1,000 students, so a 100-student pilot would test survey-based regrouping.

The language-model runs used Claude Haiku 5.5, cost $6.38 in total, and never saw any real student's data. The simulation code lives on the [`simulation`](https://github.com/WoosungLim01/StudyMatch/tree/simulation) branch.

## 2. Real survey responses

15 usable responses (of 16) from classmates in one data science class.

- The four axes adapted from the MSLQ (Motivated Strategies for Learning Questionnaire) look like the data the simulation was calibrated on.
- The two axes calibrated on Big Five personality proxies (`session_mode`, `collaboration`) don't.
- Survey items 7 and 8 measure session structure rather than session mode, and will be rewritten before the pilot.

A sample this small has wide error bars. It tests the survey, not matching.

## 3. What the pilot will check

The spring 2027 pilot (about 100 opted-in students, see the README's Roadmap) will report satisfaction and retention by group compatibility, weekly-form response rate, and how many students stay in a group to week 14.
