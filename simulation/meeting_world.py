"""
The meeting world: the LLM world, except Claude first writes what happened at
each meeting, and then judges each student's week from those accounts.

For every meeting a group held (with at least MIN_PRESENT members there), one
call writes a short account: who led, who was lost, whether they got through
the work, what went wrong. It gets the members as letters with their true
traits, the sessions they want, their shared free time, how they felt coming
into the week, who came to this meeting, and the previous meeting's account,
so a group's story carries on from week to week. A student keeps the same
letter for as long as they stay in the group; when someone leaves or joins,
the next account is told so.

With the account, for each member, what the meeting was like for them and
what it added to their willingness to come next time. That likelihood
changes their attendance from then on (NEXT), so what happens at a meeting
feeds back into who shows up, which the rule world's formulas can't do. It
is framed as what the meeting added, because the attendance formula already
counts reliability, shared free time, exam weeks and mood.

The week's judgement is the LLM world's (several asks averaged, clamped
around the rule world's value), but the judge reads the accounts instead
of a bare list of who came. Accounts take one call each, no averaging; a
meeting that nobody or only one person came to gets a fixed line and no call.

Everything else stays rule-based and shared with the other worlds. The
accounts are kept in the trace, and the dashboard shows them in each
group's panel. The engine plays the stay, survey and learn strategies
through one world with the same group ids, so the memory (letters, last
account, willingness to come) is kept per strategy, and reset() clears it
for a new seed. The account prompt was drafted three ways and merged by a
judge panel (2026-10-27); its trait key is the judge's, word for word.
"""

from concurrent.futures import ThreadPoolExecutor

from algorithm.scoring import AXES
from simulation.calibration import COURSES
from simulation.llm_world import LETTERS, SYSTEM, TRAIT_NAMES, LLMWorld, share_words
from simulation.world import EXAM_WEEKS, SEMESTER_WEEKS

EXPERIENCES = ["led", "contributed", "quiet", "lost", "frustrated", "absent"]
NEXT = {"likely": 1.1, "unsure": 0.85, "unlikely": 0.6}     # attendance multipliers until the next account
MIN_PRESENT = 2
NO_REAL_MEETING = "The group has had no real meeting yet: nobody, or only one member, came to the earlier ones."

# The judge's instructions, with the one line that changes: it now gets accounts.
SYSTEM_JUDGE = SYSTEM.replace(
    "how they felt about the group last week, and who came to each of this week's meetings.",
    "how they felt about the group last week, who came to each of this week's meetings, and an account of "
    "what happened at each.")
assert SYSTEM_JUDGE != SYSTEM, "the judge's instructions no longer contain the line the meeting world changes"

TRAIT_KEY = SYSTEM[SYSTEM.index("Trait key"):SYSTEM.index("\n\nUse your own judgement")]

SYSTEM_MEETING = f"""You write what happened at one meeting of a university study group, for a research simulation of a study-group matching app; a second reader judges each member's feelings from it.

{TRAIT_KEY}

Drivers. Middling values drive nothing; extremes (below 2.5, above 4.5) and gaps of two or more among those present do. An unreliable member came late or unprepared about every other meeting; a member far ahead on explaining or drive led, sometimes talking over the rest; the quietest in a loud group, or least driven in a fast one, fell behind; a wide gap on structure or talk-it-through means a clash over how to work; without a planner present, the session drifted. Little shared free time means lateness, early exits, running out of time; absentees did nothing, the rest waited or covered less.

Usually. Most meetings are fine (unremarkable, not great) or dull; a quarter go wrong in a specific way, a few badly. In doubt, it was dull, not good. Discontent is silence, side talk or leaving early, not rows.

Continuity. The previous account is your only memory: build on it in a clause, in fresh words, noting repeats. Problems return, irritation builds quietly; don't resolve one the meeting it appears or end on unearned hope.

Account. Three to five plain past-tense sentences naming everyone who came and, once, who was missing. Feelings and traits as behaviour, never adjectives or labels. Letters, never names; "they", never he or she; no sentence starts with the article "A"; work stays generic. No digits, scores or ratings; never mention the app, simulation, traits, rules or instructions.

One entry per member. experience: absent exactly for those marked absent; led for at most two, often none; the account must show why anyone was lost or frustrated. next: what this meeting added to their willingness to come again; reliability, free time, exams and mood are counted elsewhere. likely by default, absentees included; unsure needs a visible reason (lost, frustrated, time wasted); unlikely is rare: a second bad meeting running, or one for someone who came in low. Don't mark everyone likely after a bad meeting."""


def account_schema(letters):
    member = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "enum": list(letters)},
            "experience": {"type": "string", "enum": EXPERIENCES},
            "next": {"type": "string", "enum": list(NEXT)},
        },
        "required": ["id", "experience", "next"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"account": {"type": "string"}, "members": {"type": "array", "items": member}},
            "required": ["account", "members"], "additionalProperties": False}


class MeetingWorld(LLMWorld):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.system = SYSTEM_JUDGE
        self.memory = {}               # per strategy (self.track): what carries over between weeks, see _mem
        self.stories = {}              # gid -> this week's meetings, for the judge and the trace

    def _mem(self):
        """The current strategy's memory. Each strategy the engine plays through this world keeps
        its own, because they share group ids: letters (gid -> {sid: letter}, stable while a
        student stays in the group), last (gid -> (week, k, n, account, letters used, meetings since
        that fell through) of the group's latest real account) and intent (sid -> (gid, attendance
        multiplier) from the latest account)."""
        return self.memory.setdefault(self.track, {"letters": {}, "last": {}, "intent": {}})

    @property
    def letters(self):
        return self._mem()["letters"]

    @property
    def last(self):
        return self._mem()["last"]

    @property
    def intent(self):
        return self._mem()["intent"]

    def reset(self):
        self.memory, self.stories = {}, {}

    def attend_factor(self, gid, sid):
        g, factor = self.intent.get(sid, (None, 1.0))
        return factor if g == gid else 1.0

    def week_groups(self):
        return {gid: {"meetings": [dict(m) for m in story]} for gid, story in self.stories.items()}

    def _mapping(self, gw):
        """letter -> student, kept from week to week: a newcomer takes a letter nobody in the group has
        used lately, a leaver's letter is freed. Used for the accounts and the judge alike."""
        if self.order == "reversed":
            return super()._mapping(gw)
        held = {s: L for s, L in self.letters.get(gw.gid, {}).items() if s in gw.members}
        recent = set(held.values()) | set((self.last.get(gw.gid) or (None, None, None, None, set()))[4])
        for s in sorted(gw.members):
            if s not in held:
                held[s] = next((L for L in LETTERS if L not in recent and L not in held.values()),
                               next(L for L in LETTERS if L not in held.values()))
        self.letters[gw.gid] = held
        return {L: s for s, L in sorted(held.items(), key=lambda kv: kv[1])}

    def judge(self, played):
        to_write = sum(1 for gw in played for k in range(gw.per_week) if len(gw.meetings[k]) >= MIN_PRESENT)
        self._begin_week(len(played), to_write + len(played) * self.samples)
        self._narrate(played)
        prompts = [self._prompt(gw) for gw in played]
        return self._judge(played, prompts)

    def _narrate(self, played):
        """One account per meeting: meeting 1 for every group in parallel, then meeting 2 (which reads meeting 1's)..."""
        self.stories = {gw.gid: [] for gw in played}
        mappings = {gw.gid: self._mapping(gw) for gw in played}

        def one(gw, k):
            mapping, came = mappings[gw.gid], gw.meetings[k]
            who = self.who_came(mapping, came)
            if len(came) < MIN_PRESENT:
                text = ("Nobody came, so there was no meeting." if not came
                        else f"Only {next(L for L, s in mapping.items() if s == came[0])} came, so there was no real meeting.")
                return {"who": who, "account": text, "experience": {}, "next": {}, "called": False}
            answer = self._call(SYSTEM_MEETING, self._account_prompt(gw, k, mapping, came), account_schema(mapping), self.nonce)
            with self.lock:
                self.week["accounts"] += 1
            if not answer or not isinstance(answer.get("account"), str):
                return {"who": who, "account": None, "experience": {}, "next": {}, "called": True}
            experience, nxt = {}, {}
            for m in answer.get("members", []):
                s = mapping.get(m.get("id")) if isinstance(m, dict) else None
                if s is None:
                    continue
                e = m.get("experience")
                if s not in came:
                    e = "absent"                       # the facts win over the model's label
                elif e == "absent" or e not in EXPERIENCES:
                    e = "quiet" if e == "absent" else None
                experience[s] = e
                if m.get("next") in NEXT:
                    nxt[s] = m["next"]
            return {"who": who, "account": answer["account"].strip()[:900], "experience": experience, "next": nxt, "called": True}

        for k in range(max((gw.per_week for gw in played), default=0)):
            todo = [gw for gw in played if k < gw.per_week]
            with ThreadPoolExecutor(self.workers) as pool:
                results = list(pool.map(lambda gw: one(gw, k), todo))
            for gw, result in zip(todo, results):
                self.stories[gw.gid].append(result)
        for gw in played:
            story = self.stories[gw.gid]
            for k, m in enumerate(story):
                if m["account"] is None:           # a failed call: nothing to remember
                    continue
                if m["called"]:
                    self.last[gw.gid] = (gw.week, k + 1, gw.per_week, m["account"], set(mappings[gw.gid]), 0)
                else:                              # fell through: the last real account stays the memory
                    pw, pk, pn, account, letters, since = (self.last.get(gw.gid)
                                                           or (gw.week, k + 1, gw.per_week, None, set(mappings[gw.gid]), 0))
                    self.last[gw.gid] = (pw, pk, pn, account, letters, since + 1)
            # A meeting only changes the willingness of those who were there; the latest such meeting wins.
            # Someone who came to nothing this week keeps half of last week's signal and drifts back to neutral.
            latest = {}
            for m, came in zip(story, gw.meetings):
                latest.update({s: n for s, n in m["next"].items() if s in came})
            for s in gw.members:
                if s in latest:
                    self.intent[s] = (gw.gid, NEXT[latest[s]])
                else:
                    g, factor = self.intent.get(s, (None, 1.0))
                    self.intent[s] = (gw.gid, 1.0 + (factor - 1.0) / 2 if g == gw.gid else 1.0)

    def _previous(self, gw, k, mapping):
        """What the account call is told about the meeting before this one: the last meeting that
        really happened, how many since fell through, and who left or joined since."""
        story = self.stories[gw.gid]
        fell = 0
        for j in range(k - 1, -1, -1):                    # earlier this week, latest first
            if story[j]["account"] is None:
                continue
            if story[j]["called"]:
                return self._memory(gw.week, j + 1, gw.per_week, story[j]["account"], fell, None, mapping)
            fell += 1
        last = self.last.get(gw.gid)
        if not last:
            return NO_REAL_MEETING if fell else "This is the group's first meeting."
        pw, pk, pn, account, old_letters, since = last
        return self._memory(pw, pk, pn, account, fell + since, old_letters, mapping)

    @staticmethod
    def _memory(week, k, n, account, fell, old_letters, mapping):
        text = f"Week {week}, meeting {k} of {n}: {account}" if account else NO_REAL_MEETING
        since = []
        if fell and account:
            since.append("the meeting after it fell through" if fell == 1 else f"the {fell} meetings after it fell through")
        if old_letters is not None:
            gone = sorted(old_letters - set(mapping))
            new = sorted(set(mapping) - old_letters)
            if gone:
                since.append(f"{', '.join(gone)} left the group")
            if new:
                since.append(f"{', '.join(new)} {'is' if len(new) == 1 else 'are'} new to the group")
        return text + (f" Since then: {'; '.join(since)}." if since else "")

    def _account_prompt(self, gw, k, mapping, came):
        code = COURSES.get(self.students[gw.members[0]].course, {}).get("code", "the course")
        lines = [f"Course: {code}. Week {gw.week} of {SEMESTER_WEEKS}"
                 + (" (an exam week: everyone is busier)" if gw.week in EXAM_WEEKS else "")
                 + f". Meeting {k + 1} of {gw.per_week} this week.", "", "Members:"]
        for letter, s in mapping.items():
            axes = self.truth[s].axes
            traits = ", ".join(f"{TRAIT_NAMES[a]} {axes[a]:.1f}" for a in AXES)
            before = gw.before[s]
            feeling = f"felt {before.satisfaction:.1f} about the group" if before.tenure else "new to the group"
            per_week = self.students[s].per_week
            lines.append(f"{letter}: {traits}. Wants {per_week} session{'s' if per_week > 1 else ''} a week. "
                         f"Free time shared with the group: {share_words(gw.fit[s])}. Going into this week: {feeling}. "
                         f"This meeting: {'came' if s in came else 'absent'}.")
        lines += ["", f"Previous meeting: {self._previous(gw, k, mapping)}", "",
                  f"Write the account of meeting {k + 1} and one entry per member."]
        return "\n".join(lines)

    def _meeting_lines(self, gw, mapping):
        story = self.stories.get(gw.gid) or []
        lines = []
        for k, came in enumerate(gw.meetings, 1):
            m = story[k - 1] if k - 1 < len(story) else None
            account = m["account"] if m and m["account"] else "no account of this meeting is available"
            lines.append(f"Meeting {k} ({self.who_came(mapping, came)}): {account}")
        return lines
