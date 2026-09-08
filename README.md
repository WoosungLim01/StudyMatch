# StudyMatch — DS440 Capstone Demo

Penn State study-group matching demo. Synthetic data only — no real student PII.

## Stack

- **Backend**: Python 3.11 + FastAPI + OR-Tools (ILP) + scikit-learn (GMM)
- **Frontend**: Vanilla HTML/CSS/JS served by FastAPI as static files

## Quick Start

```bash
cd backend
pip install -r requirements.txt
python main.py
# → open http://localhost:8000
```

## Pipeline (brief §3)

```
Survey responses (Likert 6-pt)
  ↓ score_axis() + consistency check     [pipeline.py]
  ↓ GMM clustering — k discovered by BIC [clustering.py]
  ↓
  ├─ 4a: Archetype label + strength %  → DISPLAY ONLY (never fed to ILP)
  └─ 4b: Raw continuous vector         → ILP solver
              ↓
         OR-Tools CP-SAT               [matching.py]
         maximize intra-group compat
         group size ∈ {4, 5}
         NO inter-group fairness (§6/7 — intentional)
```

## Deploy (Railway / Render)

```bash
# Railway
railway init && railway up

# Render — set build command to:
pip install -r backend/requirements.txt
# start command:
cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Known Limitation (§7)

Homogeneous matching may create echo-chamber dynamics over time.
Tracked as an outcome metric, not constrained away.

## Out of Scope (v1)

- Real authentication / student PII
- Feedback loop / Beta-Binomial update (stub TODO in matching.py)
- Inter-group fairness constraints
