"""
The live dashboard: step through one semester a week at a time.

    python -m simulation.live          # http://localhost:8020

Reset puts every strategy back to the semester-start groups: week 0, groups
formed, nobody has met. "Play week N" plays one week; "Play to the end"
plays the rest. A semester stops at its length (12 to 14 weeks), so a run
can't drift on indefinitely; reset to start again.

The page has a switch between the two worlds. The rule-based world is free.
The LLM world asks Claude to judge every group's week (llm_world.py); it
needs the simulation's own Python environment, and this command switches to
it by itself when simulation/.venv exists (see simulation/README.md). Any
change of world or settings restarts the semester at week 0, so a run is
always one world from start to finish. The page is the same dashboard as
output/dashboard.html, drawn from this one run.

LLM worlds spend real money (one call per ask per group per week, cached by
exact input, so replaying the same semester is free), up to --budget dollars
per session. It only listens on this computer (127.0.0.1).
"""

import argparse
import threading
import traceback
import webbrowser

from simulation.llm_world import CLAMP, MODEL, PRICES, SAMPLES, ensure_llm_python, llm_sdk_ok
from simulation.world import SEMESTER_WEEKS

PORT = 8020
BUDGET = 5.0                           # dollars of LLM calls per session
SAMPLE = 50                            # students per course in the small cohort, in whole start groups
MIN_WEEKS = 12
MAX_SAMPLES = 4


def make_app(live):
    """The FastAPI app. Imported lazily so ensure_llm_python() can relaunch before anything heavy loads."""
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel

    class Settings(BaseModel):
        world: str = "rule"            # rule | llm-1.2 | llm-0.3 | llm-none
        cohort: str = "full"           # full | sample
        weeks: int = SEMESTER_WEEKS
        cadence: int | None = 2
        strikes: int = 1
        gate: bool = True
        seed: int = 0
        samples: int = SAMPLES         # asks per group per week in the LLM world

    class StepRequest(BaseModel):
        all: bool = False

    live.Settings = Settings
    app = FastAPI(title="StudyMatch live simulation")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return live.page()

    @app.get("/api/status")
    def status():
        return live.status()

    @app.post("/api/step")
    def step(body: StepRequest):
        try:
            live.start(body.all)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return live.status()

    @app.post("/api/reset")
    def reset(body: Settings):
        with live.lock:
            if live.busy:
                raise HTTPException(409, "Wait for the current week to finish.")
            try:
                live.reset(body)
            except ValueError as e:
                raise HTTPException(400, str(e))
        return live.status()

    return app


class Live:
    def __init__(self, budget):
        from simulation.population import load_cohort
        from simulation.semester import Cohort

        self.full = Cohort(*load_cohort())
        self.small = self.full.sample(SAMPLE)
        self.budget = budget
        self.lock = threading.Lock()
        self.busy, self.broken = False, False
        self.error = None
        self.version = 0
        self.spent_before = 0.0            # what earlier worlds in this session spent
        self.world = None
        self.html = None
        self.Settings = None

    @property
    def spent(self):
        return self.spent_before + getattr(self.world, "spent", 0.0)

    def _make_world(self, settings, cohort):
        from simulation.run import make_world

        if settings.world != "rule" and not llm_sdk_ok():
            raise ValueError("The LLM worlds aren't available in this Python. Create simulation/.venv "
                             "(see simulation/README.md) and start the page again.")
        try:
            return make_world(settings.world, cohort, samples=settings.samples, budget=max(0.0, self.budget - self.spent))
        except (RuntimeError, SystemExit) as e:   # a missing key, an old SDK: tell the page, not the console
            raise ValueError(str(e))

    def reset(self, settings):
        from simulation.policy import Policy
        from simulation.semester import Semester

        if not MIN_WEEKS <= settings.weeks <= SEMESTER_WEEKS:
            raise ValueError(f"A semester is {MIN_WEEKS} to {SEMESTER_WEEKS} weeks.")
        if settings.strikes not in (1, 2) or settings.cadence not in (None, 1, 2, 3, 4):
            raise ValueError("Unsupported regrouping setting.")
        if not 1 <= settings.samples <= MAX_SAMPLES:
            raise ValueError(f"Asks per group must be 1 to {MAX_SAMPLES}.")
        if settings.cohort not in ("full", "sample"):
            raise ValueError("Unknown cohort.")
        cohort = self.full if settings.cohort == "full" else self.small
        world = self._make_world(settings, cohort)
        self.spent_before = self.spent
        self.settings, self.cohort, self.world = settings, cohort, world
        self.policy = Policy(cadence=settings.cadence, strikes=settings.strikes)
        self.sem = Semester(cohort, world, policy=self.policy, gate=settings.gate, weeks=settings.weeks)
        self.sem.reset(settings.seed)
        self.broken, self.error, self.html = False, None, None
        self.version += 1

    def start(self, all_weeks):
        with self.lock:
            if self.busy:
                raise ValueError("A week is already playing.")
            if self.broken:
                raise ValueError("This run stopped partway through a week. Reset to start again.")
            if self.sem.done:
                raise ValueError("The semester is over. Reset to run it again.")
            self.page()                    # keep the last finished week's page to serve while this one plays
            self.busy, self.error = True, None
        threading.Thread(target=self._play, args=(all_weeks,), daemon=True).start()

    def _play(self, all_weeks):
        try:
            while not self.sem.done:
                self.sem.step()
                self.version += 1
                self.html = None
                if not all_weeks:
                    break
                self.page()
        except Exception as e:             # noqa: BLE001 - report anything to the page rather than die silently
            traceback.print_exc()
            self.broken = True
            self.error = f"Stopped during week {self.sem.week}: {e}. Reset to start again."
        finally:
            self.busy = False

    def status(self):
        from simulation import dashboard

        sem, world = self.sem, self.world
        done, total = getattr(world, "progress", [0, 0])
        names = list(sem.tracks)
        k = names.index(sem.current) if sem.current in names else 0
        if self.busy and sem.current:
            label = dashboard.STRATEGIES[[s["id"] for s in dashboard.STRATEGIES].index(sem.current)]["label"]
            message = f"Playing week {sem.week}: {label}" + (f", calls {done}/{total}" if total else "")
        else:
            message = "Starting…" if self.busy else ""
        return {"week": sem.week, "weeks": sem.weeks, "busy": self.busy, "version": self.version,
                "message": message, "done": k * max(total, 1) + done, "total": len(names) * max(total, 1),
                "spent": round(self.spent, 4), "budget_hit": bool(getattr(world, "budget_hit", False)),
                "error": self.error}

    def page(self):
        from simulation import dashboard
        from simulation.run import report_of

        if self.html is None:
            sem = self.sem
            report = report_of([sem], self.policy, self.settings.gate, self.settings.world, sem.week,
                               samples=self.settings.samples)
            trace = {s: tr.trace for s, tr in sem.tracks.items()}
            calibration = dashboard.load_json("calibration.json") or {}
            # Dollars per call from every validation block that paid for calls (a cached replay writes 0 calls).
            paid = [b for b in [calibration, calibration.get("multiweek"), calibration.get("multiweek_meetings")]
                    if b and b.get("calls")]
            per_call = sum(b["spent"] for b in paid) / sum(b["calls"] for b in paid) if paid else 0.001
            live = {"version": self.version, "settings": self.settings.model_dump(), "weeks": sem.weeks,
                    "spent": round(self.spent, 4), "budget": self.budget, "budget_hit": bool(getattr(self.world, "budget_hit", False)),
                    "llm_ready": llm_sdk_ok(), "cost_per_call": per_call, "model": MODEL, "default_clamp": CLAMP,
                    "default_samples": SAMPLES, "max_samples": MAX_SAMPLES,
                    "calls": getattr(self.world, "calls", 0), "cached": getattr(self.world, "cached", 0),
                    "full_size": len(self.full.students), "sample_size": len(self.small.students)}
            self.html = dashboard.page(dashboard.build_data(report, trace, self.cohort, live=live))
        return self.html


def main():
    parser = argparse.ArgumentParser(description="Step through a simulated semester in the browser")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--budget", type=float, default=BUDGET, help="dollars of LLM calls per session")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    ensure_llm_python("simulation.live", required=False)
    import uvicorn

    print("loading the cohort...", flush=True)
    live = Live(args.budget)
    app = make_app(live)
    live.reset(live.Settings())
    url = f"http://127.0.0.1:{args.port}/"
    print(f"live simulation at {url}  (Ctrl+C to stop; LLM worlds {'ready' if llm_sdk_ok() else 'unavailable'}, "
          f"budget ${args.budget:.2f}; {MODEL} at about ${PRICES[MODEL][0]:.2f} in / ${PRICES[MODEL][1]:.2f} out per million tokens)",
          flush=True)
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        stop = getattr(live.world, "stop", None)   # abandon a week's queued LLM calls instead of paying for them
        if stop is not None:
            stop.set()


if __name__ == "__main__":
    main()
