"""
The LLM world: the rule world, except a language model decides how each
student felt about their group's week.

Everything else stays rule-based and identical, so both worlds see the same
chance events: who comes to each meeting, who answers the form, how
leniently they rate. One call per group per week gets:
  - each member's true study traits (the hidden truth), the sessions a week
    they want, how much free time they share with the group, and how they
    felt about the group last week
  - what happened: the meetings held and who came to each
It does not get names, gender, majors, the compatibility score or the rule
world's verdict, and it isn't told what students care about. The point is a
second opinion that doesn't know our formula.

It answers, per member: satisfaction 1-5 at the end of the week, up to two
problems from the form's list (world.TAGS), a groupmate to avoid, and a
one-line note. Each group is asked `samples` times in independent calls and
the answers are averaged: the model's sampling noise shrinks by about the
square root of the number of asks (calibrate.py measures it). A problem
counts when at least half the asks named it, a groupmate to avoid needs more
than half, and the note comes from the ask closest to the average.
Satisfaction is then clamped to within `clamp` of the rule world's value
(None: no clamp), as in IdeaLab V2. The rule world's value and every raw
answer are kept in the trace.

Calls are cached on disk by their exact input (simulation/data/llm_cache.sqlite),
so rerunning or resetting the same semester costs nothing. Spending is
counted from the API's token usage. At `budget` dollars it stops: from then
on groups are judged by the rule world, and week_stats() says how many.

Needs anthropic>=1.13 (structured outputs). ensure_llm_python() re-runs a
command under simulation/.venv, which has it, when this Python doesn't.
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from algorithm.scoring import AXES
from simulation.calibration import COURSES
from simulation.world import EXAM_WEEKS, SEMESTER_WEEKS, START_SATISFACTION, TAGS, RuleWorld, Verdict

HERE = Path(__file__).resolve().parent
CACHE = HERE / "data" / "llm_cache.sqlite"
VENV_PYTHON = HERE / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
MODEL = "claude-haiku-5-5"
EFFORT = "medium"
CLAMP = 1.2
SAMPLES = 3                            # independent asks per group per week, averaged
WORKERS = 12
PROMPT_VERSION = 1                     # bump when the prompt changes, so old cached answers aren't reused
PRICES = {                             # $ per million tokens: input, output (thinking counts as output)
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
LETTERS = "ABCDEFGH"
TRAIT_NAMES = {"planning": "planning", "session_mode": "talk-it-through", "reliability": "reliability",
               "structure": "structure", "intensity": "drive", "collaboration": "explaining"}

SYSTEM = f"""You simulate how university students experience the study group they were assigned to, one week at a time, for a research simulation of a study-group matching app.

For each student you get their study traits (their true values, 1-5), how much free time they share with the group, how they felt about the group last week, and who came to each of this week's meetings. Decide how satisfied each student is with this group at the end of the week.

Trait key (1 = low, 5 = high):
- planning: sets goals and checks their own understanding (1 rarely plans, 5 plans carefully)
- talk-it-through: prefers talking problems through out loud with an agenda (1 prefers working quietly)
- reliability: shows up prepared and follows through (1 often flakes, 5 always does)
- structure: wants sessions to follow a set plan (1 is happy with unplanned sessions)
- drive: confidence and motivation in this course (1 low, 5 very driven)
- explaining: learns by explaining to others (1 prefers to listen, or to try problems alone first)

Use your own judgement about what makes a study group work or fail for different people. People differ: what bothers one student may not bother another.

Satisfaction, 1.0 to 5.0 with one decimal:
5 = the group works really well for them
4 = good, small gripes
3 = mixed, unsure about the group
2 = unhappy, would rather be in another group
1 = miserable
Feelings usually change gradually from week to week; a big change needs a clear reason in what happened. A student who missed every meeting mostly keeps last week's feeling.

For each student also give:
- problems: up to 2 codes from the list below for what bothered them this week, or [] if nothing did
- avoid: the letter of a groupmate they'd rather never be grouped with again, only if they're unhappy mainly because of that person; otherwise "none"
- note: one short sentence in their own voice about the week

Problem codes ("more" means the student wanted more of it than the group gave):
{chr(10).join(f"- {code}: {text.lower()}" for code, text in TAGS.items())}"""


def llm_sdk_ok():
    """True when this Python has an anthropic SDK new enough for structured outputs."""
    try:
        import anthropic
    except ImportError:
        return False
    return int(anthropic.__version__.split(".")[0]) >= 1


def ensure_llm_python(module, required):
    """Run `python -m module` again under simulation/.venv when this Python's SDK is too
    old, and exit with its status. Returns when this Python is fine. If the venv is
    missing: exit with instructions when the LLM world is required, else carry on
    and leave LLM worlds unavailable."""
    if llm_sdk_ok():
        return True
    if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
        print(f"switching to {VENV_PYTHON} for the LLM world", flush=True)
        try:
            code = subprocess.call([str(VENV_PYTHON), "-m", module, *sys.argv[1:]])
        except KeyboardInterrupt:
            code = 0
        sys.exit(code)
    message = ("The LLM world needs anthropic>=1.13. Create the simulation's own environment once:\n"
               "  python -m venv --system-site-packages simulation\\.venv\n"
               "  simulation\\.venv\\Scripts\\python -m pip install -r simulation\\requirements.txt")
    if required:
        raise SystemExit(message)
    print(message + "\nContinuing with the rule-based world only.", flush=True)
    return False


def api_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    env = HERE / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ANTHROPIC_API_KEY" and value.strip():
                key = value.strip().strip('"').strip("'")
    if not key:
        raise RuntimeError("No ANTHROPIC_API_KEY: put it in simulation/.env")
    return key


class Ledger:
    """Dollars spent by every world that shares it, against one budget. A run that builds
    several worlds (calibrate.py) gives them one ledger, so the cap is on the run."""

    def __init__(self, budget=None):
        self.budget, self.spent, self.hit = budget, 0.0, False
        self.lock = threading.Lock()

    def charge(self, cost):
        with self.lock:
            self.spent += cost

    def over(self):
        with self.lock:
            if self.budget is not None and self.spent >= self.budget:
                self.hit = True
            return self.hit


class Cache:
    """Answers keyed by a hash of everything that went into the call."""

    def __init__(self, path=CACHE):
        path.parent.mkdir(exist_ok=True)
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.execute("""CREATE TABLE IF NOT EXISTS calls (key TEXT PRIMARY KEY, model TEXT, answer TEXT,
                            input_tokens INTEGER, output_tokens INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP)""")
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            row = self.con.execute("SELECT answer FROM calls WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, model, answer, usage):
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO calls (key, model, answer, input_tokens, output_tokens) VALUES (?,?,?,?,?)",
                             (key, model, json.dumps(answer), usage.input_tokens, usage.output_tokens))
            self.con.commit()


def answer_schema(letters):
    student = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "enum": list(letters)},
            "satisfaction": {"type": "number"},
            "problems": {"type": "array", "items": {"type": "string", "enum": list(TAGS)}},
            "avoid": {"type": "string", "enum": list(letters) + ["none"]},
            "note": {"type": "string"},
        },
        "required": ["id", "satisfaction", "problems", "avoid", "note"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"students": {"type": "array", "items": student}},
            "required": ["students"], "additionalProperties": False}


def share_words(fit):
    """A member's mean schedule fit with the group (0-1, 1 = 3+ shared free hours) in words."""
    return ("plenty (3+ hours a week)" if fit >= 0.8 else "some (1-2 hours a week)" if fit >= 0.4
            else "little (under an hour a week)" if fit >= 0.1 else "almost none")


class LLMWorld(RuleWorld):
    def __init__(self, students, truth, courses, clamp=CLAMP, samples=SAMPLES, model=MODEL, effort=EFFORT,
                 budget=None, ledger=None, workers=WORKERS, order="sorted", nonce="", client=None):
        super().__init__(students, truth, courses)
        if not llm_sdk_ok():
            raise RuntimeError("The LLM world needs anthropic>=1.13. "
                               r"Run this with simulation\.venv\Scripts\python (see simulation/README.md).")
        import anthropic
        self.anthropic = anthropic
        self.client = client or anthropic.Anthropic(api_key=api_key(), max_retries=6)
        self.clamp, self.samples, self.model, self.effort = clamp, max(1, int(samples)), model, effort
        self.workers, self.order, self.nonce = workers, order, nonce
        self.ledger = ledger or Ledger(budget)  # the budget is checked here, shared with any other world given the same ledger
        self.stop = threading.Event()          # set to abandon the week's remaining calls (the live server, on shutdown)
        self.system = SYSTEM                   # the judge's standing instructions (a subclass may vary them)
        self.cache = Cache()
        self.lock = threading.Lock()
        self.spent = 0.0                       # this world's own spending; the ledger has the run's
        self.calls = self.cached = self.failed = self.skipped = 0
        self.halted = None                     # why the world stopped calling, if it did (out of API credits)
        self.week = self._fresh_week(0)
        self.progress = [0, 0]                 # asks done / asks this week, for the live page

    @property
    def budget_hit(self):
        return self.ledger.hit

    @staticmethod
    def _fresh_week(groups):
        return {"groups": groups, "calls": 0, "cached": 0, "failed": 0, "skipped": 0, "fallback": 0,
                "accounts": 0, "spent": 0.0}

    def week_stats(self):
        with self.lock:
            return {**self.week, "budget_hit": self.budget_hit}

    def _count(self, what, cost=0.0):
        with self.lock:
            self.week[what] += 1
            self.progress[0] += 1
            if what in ("calls", "cached", "failed", "skipped"):
                setattr(self, what, getattr(self, what) + 1)
            self.week["spent"] += cost
            self.spent += cost
        if cost:
            self.ledger.charge(cost)

    def _ask_nonce(self, i):
        """Ask 0 keeps the caller's nonce, so earlier single-ask runs stay cached."""
        return self.nonce if i == 0 else f"{self.nonce}|ask{i}"

    def judge(self, played):
        prompts = [self._prompt(gw) for gw in played]
        self._begin_week(len(played), len(prompts) * self.samples)
        return self._judge(played, prompts)

    def _begin_week(self, groups, asks):
        with self.lock:
            self.progress = [0, asks]
            self.week = self._fresh_week(groups)

    def _judge(self, played, prompts):
        """Ask about every group (samples times each, in parallel) and combine the answers."""
        jobs = [(k, i) for k in range(len(prompts)) for i in range(self.samples)]
        with ThreadPoolExecutor(self.workers) as pool:
            answers = list(pool.map(lambda job: self._ask(prompts[job[0]], self._ask_nonce(job[1])), jobs))
        asks_by_group = [[] for _ in prompts]
        for (k, _), answer in zip(jobs, answers):
            if answer is not None:
                asks_by_group[k].append(answer)
        verdicts = {}
        for gw, (mapping, _), asks in zip(played, prompts, asks_by_group):
            if not asks:
                with self.lock:
                    self.week["fallback"] += 1
            picks = {}
            for answer in asks:
                for st in answer.get("students", []):
                    if isinstance(st, dict) and isinstance(st.get("satisfaction"), (int, float)):
                        picks.setdefault(st.get("id"), []).append(st)
            for letter, s in mapping.items():
                verdicts[s] = self._combine(s, float(gw.satisfaction[s]), picks.get(letter, []), mapping)
        with self.lock:
            self.progress = [0, 0]             # nothing in flight until the next judge
        return verdicts

    def _combine(self, sid, rule, picks, mapping):
        """One student's verdict from every ask that answered for them (none: the rule world's)."""
        if not picks:
            return Verdict(rule, detail={"rule": round(rule, 3), "raw": None, "note": None})
        sats = [float(np.clip(p["satisfaction"], 1, 5)) for p in picks]
        raw = float(np.mean(sats))
        final = raw if self.clamp is None else float(np.clip(raw, rule - self.clamp, rule + self.clamp))
        n = len(picks)
        named = Counter(t for p in picks for t in dict.fromkeys(x for x in p.get("problems", []) if x in TAGS))
        tags = [t for t, c in named.most_common() if 2 * c >= n][:2]
        blamed = Counter(mapping.get(p.get("avoid")) for p in picks)
        for drop in (None, sid):
            blamed.pop(drop, None)
        other, votes = blamed.most_common(1)[0] if blamed else (None, 0)
        avoid = [other] if other and 2 * votes > n else []
        note = min(picks, key=lambda p: abs(float(p["satisfaction"]) - raw)).get("note", "")
        return Verdict(final, tags, avoid, {"rule": round(rule, 3), "raw": round(raw, 3), "note": str(note)[:240],
                                             "asks": [round(x, 1) for x in sats], "clamped": bool(final != raw)})

    def _mapping(self, gw):
        """letter -> student for this group this week. Sorted ids here; the meeting world keeps letters stable."""
        return dict(zip(LETTERS, sorted(gw.members, reverse=(self.order == "reversed"))))

    def _prompt(self, gw):
        mapping = self._mapping(gw)
        week = gw.week
        code = COURSES.get(self.students[gw.members[0]].course, {}).get("code", "the course")
        lines = [f"Course: {code}. Week {week} of {SEMESTER_WEEKS}"
                 + (" (an exam week: everyone is busier)." if week in EXAM_WEEKS else "."),
                 f"The group planned {gw.per_week} meeting{'s' if gw.per_week > 1 else ''} this week.", "",
                 "Students:"]
        for letter, s in mapping.items():
            axes = self.truth[s].axes
            traits = ", ".join(f"{TRAIT_NAMES[a]} {axes[a]:.1f}" for a in AXES)
            before = gw.before[s]
            mood = (f"Last week they felt {before.satisfaction:.1f} about this group, after {before.tenure} "
                    f"week{'s' if before.tenure > 1 else ''} in it." if before.tenure
                    else f"New to this group this week (a new group starts around {START_SATISFACTION}: hopeful, unproven).")
            per_week = self.students[s].per_week
            lines.append(f"{letter}: {traits}. Wants {per_week} session{'s' if per_week > 1 else ''} a week. "
                         f"Free time shared with the group: {share_words(gw.fit[s])}. {mood}")
        lines += ["", "What happened this week:"] + self._meeting_lines(gw, mapping)
        return mapping, "\n".join(lines)

    @staticmethod
    def who_came(mapping, came):
        here = [L for L, s in mapping.items() if s in came]
        missed = [L for L, s in mapping.items() if s not in came]
        if not here:
            return "nobody came"
        if not missed:
            return "everyone came"
        return f"{', '.join(here)} came; {', '.join(missed)} missed it"

    def _meeting_lines(self, gw, mapping):
        """What the judge is told about each meeting: here, who came. The meeting world adds an account."""
        return [f"Meeting {k}: {self.who_came(mapping, came)}." for k, came in enumerate(gw.meetings, 1)]

    def _ask(self, prompt, nonce):
        """One ask of the judge (or its cached answer). None when it failed or the budget is spent."""
        mapping, text = prompt
        return self._call(self.system, text, answer_schema(mapping), nonce)

    def _call(self, system, text, schema, nonce):
        """One structured call to the model, cached by its exact input. None when it failed or the budget is spent."""
        key = hashlib.sha256(json.dumps([PROMPT_VERSION, self.model, self.effort, system, text, nonce]).encode()).hexdigest()
        answer = self.cache.get(key)
        if answer is not None:
            self._count("cached")
            return answer
        if self.stop.is_set() or self.ledger.over():
            self._count("skipped")
            return None
        try:
            resp = self.client.messages.create(
                model=self.model, max_tokens=4000, system=system,
                messages=[{"role": "user", "content": text}],
                output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
            )
        except (self.anthropic.AuthenticationError, self.anthropic.PermissionDeniedError, self.anthropic.NotFoundError):
            raise
        except (self.anthropic.APIStatusError, self.anthropic.APIConnectionError) as e:
            self._count("failed")
            if isinstance(e, self.anthropic.BadRequestError) and "credit balance" in str(e):
                if not self.stop.is_set():          # out of API credits: stop asking, say so once
                    print("API credits are exhausted: no more calls this run; the remaining groups are judged "
                          "by the rules (top up at console.anthropic.com, then rerun: cached answers are free)", flush=True)
                    self.halted = "API credits exhausted"
                    self.stop.set()
                return None
            print(f"LLM call failed, skipping it: {e}", flush=True)
            return None
        price_in, price_out = PRICES.get(self.model, PRICES[MODEL])
        self._count("calls", (resp.usage.input_tokens * price_in + resp.usage.output_tokens * price_out) / 1e6)
        if resp.stop_reason != "end_turn":
            with self.lock:
                self.failed += 1
                self.week["failed"] += 1
            print(f"LLM answer unusable ({resp.stop_reason}), skipping this call", flush=True)
            return None
        answer = json.loads(next(b.text for b in resp.content if b.type == "text"))
        self.cache.put(key, self.model, answer, resp.usage)
        return answer
