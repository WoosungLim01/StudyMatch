"""
StudyMatch — FastAPI backend.

Also serves the /frontend directory as static files so the whole app
deploys as a single Python process.
"""

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from synthetic import generate_cohort, SURVEY_ITEMS, AXES, DEFAULT_AXIS_WEIGHTS
from pipeline import run_pipeline
from clustering import run_clustering
from matching import (
    run_matching,
    build_compat_matrix,
    random_groups,
    ilp_groups,
    DEFAULT_AXIS_WEIGHTS as WEIGHTS_DEFAULT,
)

_executor = ThreadPoolExecutor(max_workers=4)

app = FastAPI(title="StudyMatch API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
#  Request / Response models
# ─────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    n_students: int = Field(60, ge=12, le=200)
    noise_level: float = Field(0.4, ge=0.0, le=1.0)
    archetype_separation: float = Field(0.8, ge=0.1, le=1.0)
    low_effort_pct: float = Field(0.08, ge=0.0, le=0.20)
    n_archetypes: int = Field(4, ge=2, le=5)
    seed: int = Field(42)


class PipelineRequest(BaseModel):
    students: List[Dict]


class ClusterRequest(BaseModel):
    scored_students: List[Dict]
    k_min: int = Field(2, ge=2, le=4)
    k_max: int = Field(8, ge=4, le=10)


class MatchRequest(BaseModel):
    scored_students: List[Dict]
    axis_weights: Optional[Dict[str, float]] = None
    group_size_min: int = Field(4, ge=3, le=5)
    group_size_max: int = Field(5, ge=4, le=6)
    time_limit_s: float = Field(30.0, ge=5.0, le=120.0)


# ─────────────────────────────────────────────────────────────
#  Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/api/schema")
def get_schema():
    """Return the survey item list so the frontend can render the form."""
    return {"items": SURVEY_ITEMS, "axes": AXES, "default_weights": DEFAULT_AXIS_WEIGHTS}


@app.post("/api/generate")
def api_generate(req: GenerateRequest):
    """Generate a synthetic student cohort."""
    students = generate_cohort(
        n_students=req.n_students,
        noise_level=req.noise_level,
        archetype_separation=req.archetype_separation,
        low_effort_pct=req.low_effort_pct,
        n_archetypes=req.n_archetypes,
        seed=req.seed,
    )
    return {"students": students, "n": len(students)}


@app.post("/api/pipeline")
def api_pipeline(req: PipelineRequest):
    """
    Score raw survey responses and run consistency checks.

    Input:  students with raw_responses + true_axis_scores
    Output: same students enriched with axis_scores + consistency
    """
    if not req.students:
        raise HTTPException(400, "No students provided")
    scored = run_pipeline(req.students)
    n_flagged = sum(1 for s in scored if s["consistency"]["flag_low_effort"])
    return {"scored_students": scored, "n_flagged": n_flagged}


@app.post("/api/cluster")
def api_cluster(req: ClusterRequest):
    """
    Discover archetypes via GMM (BIC + silhouette selection).

    Returns soft membership per student (display layer only —
    raw axis_scores continue to matching, not archetype labels).
    """
    if len(req.scored_students) < 6:
        raise HTTPException(400, "Need at least 6 students for clustering")
    result = run_clustering(req.scored_students, req.k_min, req.k_max)
    return result


@app.post("/api/match")
async def api_match(req: MatchRequest):
    """
    Run ILP group formation + random baseline + Oracle upper bound.

    ILP uses axis_scores (step 4b); Oracle uses true_axis_scores.
    Archetype labels from clustering are NOT accepted here.
    ILP and Oracle solves run in parallel to halve wall-clock time.
    """
    students = req.scored_students
    if len(students) < req.group_size_min * 2:
        raise HTTPException(400, f"Need at least {req.group_size_min * 2} students")

    weights  = req.axis_weights or DEFAULT_AXIS_WEIGHTS
    gmin     = req.group_size_min
    gmax     = req.group_size_max
    tlimit   = req.time_limit_s

    # Build compat matrices synchronously (fast numpy ops)
    compat_scored = build_compat_matrix(students, "axis_scores",      weights)
    compat_oracle = build_compat_matrix(students, "true_axis_scores", weights)
    random_res    = random_groups(students, compat_scored, gmax)

    # Run ILP + Oracle in parallel threads (each solver is single-process safe)
    loop = asyncio.get_event_loop()
    ilp_future = loop.run_in_executor(
        _executor,
        lambda: ilp_groups(students, compat_scored, gmin, gmax, tlimit, weights),
    )
    oracle_future = loop.run_in_executor(
        _executor,
        lambda: ilp_groups(students, compat_oracle, gmin, gmax, tlimit, weights),
    )
    ilp_res, oracle_res = await asyncio.gather(ilp_future, oracle_future)

    return {
        "student_ids":   [s["id"] for s in students],
        "ilp_result":    ilp_res,
        "random_result": random_res,
        "oracle_result": oracle_res,
        "compat_matrix": compat_scored.tolist(),
    }


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ─────────────────────────────────────────────────────────────
#  Serve frontend (single deployable unit)
# ─────────────────────────────────────────────────────────────

_FRONTEND = Path(__file__).parent.parent / "frontend"
if _FRONTEND.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
