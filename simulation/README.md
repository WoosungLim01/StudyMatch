# StudyMatch simulation

Lives only on the `simulation` branch and is never merged into `main`.
Everything simulation-related stays inside this folder: code, the generated
cohort (`data/`), run output (`output/`), secrets (`.env`) and its own
Python environment (`.venv/`). The rest of the repository is identical to `main`.

A semester is simulated one week at a time, at most 14 weeks. Each week,
groups meet in a simulated world, students answer a short pulse form (and a
longer check-in with peer ratings every 4 weeks), a learner updates its
picture of each student, and unhappy students are regrouped. Three
strategies are compared: never regroup, regroup on survey answers alone,
and regroup with what feedback taught.

```
python -m simulation.cohort       # build the 1000-student cohort (automatic on first run)
python -m simulation.checks       # sanity and realism checks
python -m simulation.run          # 10 seeds x 14 weeks, about 3 minutes; rebuilds the dashboard
python -m simulation.frequency    # how often to regroup and retune, about 6 minutes
python -m simulation.dashboard    # redraw output/dashboard.html from the last run, no rerun
python -m simulation.live         # step through one semester in the browser (Reset / Play week)
```

Open `output/dashboard.html` for the multi-seed results. `live.py` serves the
same page for a single semester you play week by week. Its control bar has a
**World** switch with three worlds: rule-based (free), the LLM judge, and
the LLM with simulated meetings. Switching worlds, or changing any setting,
restarts the semester at week 0, so a run is always one world from start to
finish; Reset replays the same settings from week 0.

## The LLM worlds

`llm_world.py` lets a language model (Claude Haiku 5.5) decide how each
student felt about their group's week. Each group is asked several times
(3 by default) and the answers are averaged, which cuts the model's
sampling noise; the average is then held within a clamp (±1.2 by default)
of the rule-based world's value. Everything else, meetings, attendance,
forms and peer ratings, stays rule-based, so the worlds see the same events
and only the judgement differs.

`meeting_world.py` goes one step further: for every meeting, Claude first
writes a short account of what happened (who led, who got lost, what went
wrong), continuing the previous meeting's account, and the week is judged
from those accounts rather than from a bare list of who came. After each
meeting, how likely each member is to come next time adjusts their
attendance, so what happens in the room feeds back into who shows up. The
accounts are shown in each group's panel on the dashboard.

```
python -m simulation.calibrate                           # validate the LLM judge: ~900 calls the first time, under $1
python -m simulation.calibrate --world meeting           # validate the meetings world the same way
python -m simulation.run --world llm-1.2 --sample 50     # a 2-seed LLM semester on 100 students -> output/llm/
python -m simulation.run --world meet-1.2 --sample 50    # the same with simulated meetings -> output/meetings/
python -m simulation.dashboard --dir llm                 # redraw a run's dashboard
```

It needs a newer `anthropic` SDK than other projects on this computer use,
so it runs from the simulation's own environment, which reuses every
globally installed package and adds only that SDK. Every command above
switches to it by itself once it exists:

```
python -m venv --system-site-packages simulation\.venv
simulation\.venv\Scripts\python -m pip install -r simulation\requirements.txt
```

The API key goes in `simulation/.env` as `ANTHROPIC_API_KEY`. Calls are cached
in `data/llm_cache.sqlite`, so replaying a semester costs nothing. Runs stop
at a dollar budget (`--budget`; the live page's default is $5 a session) and
from then on groups are judged by the rules, which the page says. A 14-week
semester for 100 students costs about $2 with the LLM judge and about $3
with simulated meetings, at 3 asks per group.

## Rules for keeping this branch mergeable

- The simulation may import the product (`algorithm/`, `data/`). The product
  never imports the simulation.
- If the simulation needs a product change, make it on the product branch
  (`dev_li` -> `main`) as a general improvement, such as a new parameter.
  Then merge `main` into this branch. Don't edit product files here.
- If product code ever has to call the simulation, the call must survive
  this folder being missing (an optional import inside `try/except
  ImportError`), so `main` runs without it.
