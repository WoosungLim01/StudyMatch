# StudyMatch simulation

Lives only on the `simulation` branch and is never merged into `main`.
Everything simulation-related stays inside this folder: code, the generated
cohort (`data/`), run output (`output/`) and secrets (`.env`). The rest of
the repository is identical to `main`.

```
python -m simulation.cohort    # build the 1000-student cohort (automatic on first run)
python -m simulation.checks    # sanity and realism checks
python -m simulation.run       # multi-round experiment, about 40 s
```

Each round, groups meet for 4 weeks in a rule-based world. Students give
feedback, a learner updates its picture of each student, unhappy students
are reassigned, and the next round runs. Each module's docstring describes
its part. `docs/SIMULATION_PLAN.md` holds the original one-round design.

## Rules for keeping this branch mergeable

- The simulation may import the product (`algorithm/`, `data/`). The product
  never imports the simulation.
- If the simulation needs a product change, make it on the product branch
  (`dev_li` -> `main`) as a general improvement, such as a new parameter.
  Then merge `main` into this branch. Don't edit product files here.
- If product code ever has to call the simulation, the call must survive
  this folder being missing (an optional import inside `try/except
  ImportError`), so `main` runs without it.
