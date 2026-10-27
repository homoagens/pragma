# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""advisor.py - a second model that plans the turn and unsticks it.

WHAT IT IS FOR. A small model run as the agent is good at doing what it is
told and poor at three things: knowing what "done" looks like, noticing that
it is going round in circles, and knowing when to stop and ask. One snake game
on Qwen3.8 Flash Next took 85 steps; the game worked, and some 65 of them went on
six variants of the same throwaway terminal script, never once asking whether
they were getting anywhere. The advisor is another model - usually a more
capable one, on its own endpoint (the `advisor` role) - that does those three
things for it, and nothing else:

- BEFORE THE FIRST STEP it writes a plan in a fixed form, `Done when` first,
  or answers NO PLAN for a turn that needs no work. Every turn, when on.
- WHEN THE AGENT STOPS MAKING PROGRESS it reads the record of the steps and
  says what to do next. When is decided by Pragma, from signals it already
  measures (react.py), never by the agent: the agent is exactly the one that
  does not know when it is stuck.

It does not act and does not answer the person. What it says reaches the
agent as a message beginning [ADVISOR], with the same standing as a [CRITIC]:
a second reader on the person's side, not the person.

It is not the critic either. The critic judges the finished work before it is
delivered; the advisor works at the start and in the middle. They are the two
ends of one loop: the plan fixes what "done" means and the critic holds the
work to it, reading the plan beside the request; and when the critic sends the
work back, with `consult` on and consults left, the advisor is called again to
say whether one step went wrong or the plan did - a revise is a reason to plan
again. Neither sees the other's reasoning, only what it wrote.

Off unless a project turns it on (/settings): `plan`, or `consult` for the
plan and the advice. A single task takes --advisor.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import config
import llm_client

# The project setting, and what it can say. Absent or anything else is off.
SETTING = "Advisor"
MODES = ("plan", "consult")
# How many times one turn may ask for advice; the plan is not counted.
CONSULTS_SETTING = "AdvisorConsults"
DEFAULT_CONSULTS = 2
MOST_CONSULTS = 10

# What the advisor reads of the folder: two levels, the clutter left out, and
# no more lines than this. Enough to name the files a plan is about.
_LISTING_LINES = 150
_SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pragma_checkpoints",
         ".mypy_cache", ".pytest_cache", ".ruff_cache", "target", "dist", "build"}

# What a plan or a piece of advice may be, at most. A model asked for fifteen
# lines has been seen to write its whole deliberation instead.
_MOST_CHARS = 3000


def mode_of(settings: dict) -> str:
    """The advisor mode a project's settings ask for: "plan", "consult" or ""."""
    got = str((settings or {}).get(SETTING) or "").strip().lower()
    return got if got in MODES else ""


def consults_of(settings: dict) -> int:
    """How many times a turn may ask for advice, from a project's settings."""
    try:
        n = int(str((settings or {}).get(CONSULTS_SETTING, "")).strip())
    except ValueError:
        return DEFAULT_CONSULTS
    return max(0, min(MOST_CONSULTS, n))


# ── what the advisor is told ──────────────────────────────────────────────────

_ROLE = """You are the advisor of a coding agent that works in a folder on the \
person's machine. The agent is a smaller model: good at doing what it is told, \
poor at knowing when the work is done, at noticing that it is going round in \
circles, and at knowing when to stop and ask. You do not act and you do not \
answer the person: you write for the agent."""

_PLAN_SYSTEM = _ROLE + """

Reply with exactly NO PLAN when the request needs no work on files or \
commands: a greeting, a question answered in words, an explanation.

Otherwise reply in this form and nothing else, fifteen lines at most:

Done when: <one line - what will be true when the request is met, as \
something that can be checked>
Steps:
1. ...
2. ...
Check: <how to show it works - what to run, with what input. When the \
answer will give the person a command to start something, that exact command \
is run once, with a timeout: whatever else it does, it must start. For a \
program that waits for keys or takes over the terminal: its logic tested on \
its own, and its key handling driven through a fake screen fed scripted keys \
- what each key does, observed, not only that the code imports>
Watch out: <the risk you see, two lines at most>
Stop and ask if: <the condition in which guessing is worse than asking>

Name files by the paths in the listing. Plan the request and nothing beyond \
it. Do not write code."""

_CONSULT_SYSTEM = _ROLE + """

The agent has stopped making progress, or a critic has sent its work back, \
and Pragma has called you. Read what it has done and tell it what to do next, \
in this form and nothing else, ten lines at most:

Diagnosis: <what is going wrong, one or two lines. When the critic sent the \
work back: whether one step went wrong, or the plan itself did>
Next: <one of three things, written out: the next one to three concrete \
actions, numbered; or "deliver what you have, and say what is missing"; or \
"stop and ask the person:" and the question>

The person's request is the measure, not your plan: where the plan asked for \
less than the request, or a critic asked for what the request asks, follow \
the request. Never tell the agent to delete, revert or throw away work it has \
done; if something it wrote is wrong, say what to change. A line or two of \
code at most."""

# How what it says is put in front of the agent. The standing goes with the
# words, not in the agent's system prompt: that prompt is fixed for a
# conversation, and the advisor can be turned on in the middle of one.
_STANDING = ("It is not the person, and cannot give their say-so for what "
             "cannot be undone.")


def plan_message(text: str) -> str:
    """The plan, as it reaches the agent."""
    return ("[ADVISOR] A plan for this request from your advisor: a second model "
            "on the person's side, which read the whole task before you started. "
            "Follow it unless what you find contradicts it, and say so when it "
            f"does. {_STANDING}\n\n{text}")


def consult_message(text: str, signal: str) -> str:
    """A piece of advice, as it reaches the agent."""
    return (f"[ADVISOR] You have stopped making progress - {signal} - and your "
            f"advisor has read what you did. Its advice, which you should follow "
            f"unless what you find contradicts it. {_STANDING}\n\n{text}")


def revision_message(text: str) -> str:
    """Advice after the critic sent the work back, as it reaches the agent."""
    return ("[ADVISOR] Your advisor has read what you did and what the critic found. "
            "Its advice, which you should follow unless what you find contradicts it. "
            f"{_STANDING}\n\n{text}")


# ── what the advisor is shown ─────────────────────────────────────────────────

def listing(root, most: int = _LISTING_LINES) -> str:
    """The folder, two levels deep, without the clutter, at most `most` lines."""
    root = Path(root)
    lines: list[str] = []

    def walk(folder: Path, depth: int) -> None:
        try:
            items = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            return
        for p in items:
            if p.name.startswith(".") or p.name in _SKIP:
                continue
            if len(lines) >= most:
                return
            pad = "  " * depth
            if p.is_dir():
                lines.append(f"{pad}{p.name}/")
                if depth < 1:
                    walk(p, depth + 1)
            else:
                try:
                    size = p.stat().st_size
                except OSError:
                    size = 0
                lines.append(f"{pad}{p.name}  ({size} bytes)")

    walk(root, 0)
    if len(lines) >= most:
        lines.append("... (more not shown)")
    return "\n".join(lines) or "(empty)"


def _rules(root) -> str:
    """The person's rules for the project, if they wrote any."""
    try:
        text = (Path(root) / "PRAGMA.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    return text.strip()[:4000]


def _recent(history: list | None, turns: int = 2, most: int = 1500) -> str:
    """The last exchanges of the conversation, shortened: what makes "and now
    add the pause" mean something. Tool traffic is left out."""
    said = [m for m in (history or [])
            if m.get("role") in ("user", "assistant") and not m.get("tool_calls")
            and isinstance(m.get("content"), str) and m["content"].strip()]
    out = []
    for m in said[-2 * turns:]:
        text = " ".join(m["content"].split())
        if len(text) > most:
            text = text[:most] + " ..."
        out.append(f"{'PERSON' if m['role'] == 'user' else 'AGENT'}: {text}")
    return "\n".join(out)


def _target(action: str, args: dict) -> str:
    """What a step was done to, in one short line."""
    args = args or {}
    if action == "execute_command":
        first = str(args.get("command", "")).strip().splitlines()
        return (first[0] if first else "")[:100]
    for key in ("path", "file", "url", "query"):
        if args.get(key):
            return str(args[key])[:100]
    return json.dumps(args, ensure_ascii=False, default=str)[:100]


def _outcome(observation) -> str:
    first = str(observation or "").strip().splitlines()
    return (first[0] if first else "(nothing)")[:120]


def record(ledger: list[dict], errors: int = 3, most: int = 1200) -> str:
    """The steps as the advisor reads them: one line each, and the last few
    errors whole. Not the agent's reasoning: what it did, and what came back."""
    lines = [f"{e.get('step')}. {e.get('action')} {_target(e.get('action', ''), e.get('args'))}"
             f"  ->  {_outcome(e.get('observation'))}"
             for e in ledger]
    failed = [e for e in ledger if str(e.get("observation", "")).lstrip().startswith("ERROR")
              or "Traceback" in str(e.get("observation", ""))
              or re.search(r"\bexit(?:ed)? (?:code )?[1-9]", str(e.get("observation", ""))[:200])]
    if failed:
        lines.append("")
        lines.append("The last errors, whole:")
        for e in failed[-errors:]:
            lines.append(f"- step {e.get('step')}: {str(e.get('observation', ''))[:most]}")
    return "\n".join(lines)


# ── the calls ─────────────────────────────────────────────────────────────────

def _clean(raw: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", str(raw or ""), flags=re.DOTALL).strip()
    if len(text) > _MOST_CHARS:
        text = text[:_MOST_CHARS].rstrip() + "\n..."
    return text


def _ask(system: str, payload: str, stop_event=None) -> tuple[str, float, int]:
    """(what it said, seconds, tokens read and written)."""
    t0 = time.monotonic()
    llm_client.LAST_STATS = {}
    with llm_client.faculty("ADVISOR"):
        raw = llm_client.call_llm(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": payload}],
            max_tokens=config.MAX_TOKENS,
            **config.memory_call("write"),
            stop_event=stop_event,
        )
    stats = llm_client.LAST_STATS or {}
    tokens = int(stats.get("total") or 0) or (int(stats.get("prompt") or 0)
                                              + int(stats.get("completion") or 0))
    return _clean(raw), time.monotonic() - t0, tokens


def tok(n: int) -> str:
    """Tokens as the screen says them. Read and written together: on a paid
    endpoint both are paid for."""
    return f"{n / 1000:.1f}k tok" if n >= 1000 else f"{n} tok"


def _cost(took: float, tokens: int) -> str:
    return f"{took:.0f}s" + (f" · {tok(tokens)}" if tokens else "")


# How much of a plan the turn shows: `Done when` whole, then the steps, one
# line each. Check, the risk and when to ask are for /plan.
_SHOWN_STEPS = 6
_STEP_CHARS = 100


def _plan_details(text: str) -> list[str]:
    out = []
    done = re.search(r"^\s*Done when:\s*(.+)$", text, flags=re.MULTILINE | re.IGNORECASE)
    if done:
        out.append(f"done when: {done.group(1).strip()}")
    steps = re.findall(r"^\s*(\d+)[.)]\s+(.+)$", text, flags=re.MULTILINE)
    for number, step in steps[:_SHOWN_STEPS]:
        step = step.strip()
        out.append(f"{number}. {step[:_STEP_CHARS]}{'…' if len(step) > _STEP_CHARS else ''}")
    if len(steps) > _SHOWN_STEPS:
        out.append(f"… {len(steps) - _SHOWN_STEPS} more · /plan shows them")
    return out


def _advice_details(text: str) -> list[str]:
    """The diagnosis, and what to do next with the lines that spell it out."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    at = next((i for i, ln in enumerate(lines) if ln.lower().startswith("diagnosis:")), None)
    nxt = next((i for i, ln in enumerate(lines) if ln.lower().startswith("next:")), None)
    if at is None and nxt is None:
        return lines[:3]
    out = [lines[at]] if at is not None else []
    if nxt is not None:
        out += lines[nxt:nxt + 3]
    return out[:4]


def plan(task: str, history: list | None, root, stop_event=None) -> dict:
    """The plan for this turn.

    {"text": the plan, or "" for NO PLAN, "line": what the screen says,
     "details": the lines under it, "seconds", "tokens", "error": "" or why
    there is none}. Never raises but for a stop (llm_client.LLMInterrupted):
    a turn must not fail because its advisor did.
    """
    parts = ["[The request, with what the agent remembers in front of it]", task.strip()]
    recent = _recent(history)
    if recent:
        parts += ["", "[The conversation just before, shortened]", recent]
    rules = _rules(root)
    if rules:
        parts += ["", "[PRAGMA.md - the person's rules for this project]", rules]
    parts += ["", f"[The folder: {root}]", listing(root)]
    try:
        text, took, tokens = _ask(_PLAN_SYSTEM, "\n".join(parts), stop_event)
    except llm_client.LLMInterrupted:
        raise
    except Exception as e:
        return {"text": "", "line": f"no plan - {type(e).__name__}: {str(e)[:80]}",
                "details": [], "seconds": 0.0, "tokens": 0, "error": str(e)[:200]}
    if not text or text.upper().startswith("NO PLAN"):
        return {"text": "", "line": f"no plan needed · {_cost(took, tokens)}", "details": [],
                "seconds": took, "tokens": tokens, "error": ""}
    steps = len(re.findall(r"^\s*\d+[.)]\s", text, flags=re.MULTILINE))
    line = "plan" + (f" · {steps} step{'s' if steps != 1 else ''}" if steps else "")
    return {"text": text, "line": f"{line} · {_cost(took, tokens)}",
            "details": _plan_details(text), "seconds": took, "tokens": tokens, "error": ""}


def consult(request: str, plan_text: str, ledger: list[dict], signal: str,
            stop_event=None, found: str = "") -> dict:
    """Advice for an agent that has stopped making progress, or whose work the
    critic sent back - `found` is then what the critic said. Same shape as
    plan(); never raises but for a stop."""
    parts = ["[What the person asked]", (request or "").strip()]
    if plan_text:
        parts += ["", "[Your plan for it]", plan_text]
    parts += ["", f"[Why you are called] {signal}"]
    if found:
        parts += ["", "[What the critic found]", found.strip()]
    parts += ["", "[What the agent has done, step by step]", record(ledger)]
    try:
        text, took, tokens = _ask(_CONSULT_SYSTEM, "\n".join(parts), stop_event)
    except llm_client.LLMInterrupted:
        raise
    except Exception as e:
        return {"text": "", "line": f"no advice - {type(e).__name__}: {str(e)[:80]}",
                "details": [], "seconds": 0.0, "tokens": 0, "error": str(e)[:200]}
    why = signal if len(signal) <= 70 else signal[:69] + "…"
    if not text:
        return {"text": "", "line": f"no advice given ({why}) · {_cost(took, tokens)}",
                "details": [], "seconds": took, "tokens": tokens, "error": ""}
    return {"text": text, "line": f"advice · {why} · {_cost(took, tokens)}",
            "details": _advice_details(text), "seconds": took, "tokens": tokens, "error": ""}


# ── when to ask ───────────────────────────────────────────────────────────────

_TIMEOUT_N = re.compile(r"(?:^|[\s;&|(])timeout\s+(?:-\S+\s+)*(\d+)")


def _timed_out(command: str, out: str) -> bool:
    """Did this command run into a time limit long enough to mean it hung?"""
    out = (out or "").lstrip()
    if out.startswith("ERROR: command timed out"):
        return True
    if not out.startswith("returncode: 124"):
        return False
    m = _TIMEOUT_N.search(command)
    return bool(m) and int(m.group(1)) >= 20


def _is_test(path: str) -> bool:
    """A test file, by the names test runners look for."""
    p = Path(path)
    name = p.name
    return (name.startswith("test_") or name.endswith(("_test.py", ".test.js", ".spec.js"))
            or "tests" in p.parts or "test" in p.parts)


# Skills that change files: a command run again after one of these is checking
# the change, not going round in circles.
_EDITS = {"write_file", "append_file", "replace_in_file", "replace_in_files",
          "insert_after", "insert_before", "apply_patch", "revert"}


def _inline(command: str) -> bool:
    """Does the command carry its own program - a script written into it, not
    a file it runs? `python3 - <<EOF`, `python3 -c "..."`, `cat > x <<EOF`."""
    return "<<" in command or bool(re.search(r"(^|\s)-c\s", command))


class Watch:
    """The signals of a run going nowhere that the loop does not already watch
    for. (The same call failing over and over and most calls failing are
    react.py's watchdogs, which tell this one when they fire.)

    - HALF THE STEPS spent with nothing delivered.
    - THE SAME THROWAWAY SCRIPT written into a command a third time. Counted
      by how it begins, not by its exact text: the snake run's six terminal
      scripts each differed by a line, and each began the same way - and
      between them the game was edited, so an edit does not excuse these.
    - THE SAME COMMAND run a third time with nothing changed in between. A
      command run again AFTER an edit is the edit being checked: three
      `py_compile snake.py` around two changes are the work done right, and
      counting them sent a careful run to the advisor for being careful.
    - THE SAME FILE written whole a third time.
    - A FILE BROUGHT BACK to what it was after an earlier edit of this turn:
      the edit undone, which is going round in circles with edits between. A
      tetris turn added seven lines and took them out again four times over,
      and every signal above saw a different command each time.
    - EDITS THAT CHANGED NOTHING, a second time.
    - COMMANDS THAT RAN INTO THEIR TIMEOUT, twice: Pragma's own, or a
      `timeout N` of twenty seconds or more that ended in 124. A test that
      waited on a terminal sat out two minutes twice before anything noticed.
      A short `timeout 3` is a program being shown to start, and its 124 is
      the expected answer.
    - THE TESTS EDITED OVER AND OVER and nothing else: six edits in a row to
      test files with no change to the code they test. On a turn where the
      tests failed, twenty-five edits went to the tests and two to the logic:
      tests bent until they pass, the oldest way to look finished.
    """

    REPEATS = 3

    def __init__(self, max_steps: int, root=None):
        self.half = max(2, int(max_steps or 0) // 2)
        self.root = Path(root) if root else None
        # A file -> the fingerprints it has had after each edit this turn.
        self.states: dict[str, list[str]] = {}
        self.back: set[str] = set()
        self.idle = 0
        self.timeouts = 0
        self.test_edits = 0
        self.tests_said = False
        self.edits = 0                    # file changes so far in the turn
        self.scripts: dict[str, int] = {}
        self.writes: dict[str, int] = {}
        # A command -> (times in a row with no edit between, edits when last run)
        self.runs: dict[str, tuple[int, int]] = {}
        self.half_said = False

    def after(self, step: int, action: str, args: dict, ok: bool = True,
              out: str = "") -> str:
        """The signal this step gives, or "". `ok` is False for a call that
        failed: a refused edit left the file as it was, and is not an edit
        that changed nothing. `out` is what the call returned."""
        args = args or {}
        said = ""
        if action == "execute_command":
            command = " ".join(str(args.get("command", "")).split())
            about = command[:60]
            if _timed_out(command, out):
                self.timeouts += 1
                if self.timeouts == 2:
                    said = f"commands ran into their timeout twice ({about[:45]})"
            if _inline(command):
                self.scripts[about] = self.scripts.get(about, 0) + 1
                if self.scripts[about] == self.REPEATS:
                    said = said or (f"the same throwaway script written {self.REPEATS} "
                                    f"times ({about[:45]})")
            else:
                times, at = self.runs.get(command, (0, -1))
                times = times + 1 if at == self.edits else 1
                self.runs[command] = (times, self.edits)
                if times == self.REPEATS:
                    said = said or (f"the same command run {self.REPEATS} times with nothing "
                                    f"changed between ({about[:40]})")
        elif action in _EDITS:
            self.edits += 1
            if ok:
                if _is_test(str(args.get("path", ""))):
                    self.test_edits += 1
                    if self.test_edits == 6 and not self.tests_said:
                        self.tests_said = True
                        said = ("the tests edited 6 times in a row and the code they "
                                "test not once")
                elif args.get("path"):
                    self.test_edits = 0
            # A refused write wrote nothing: "written whole three times" once
            # counted a write_file that failed because the file existed, and
            # spent a consult on two writes.
            if action == "write_file" and ok:
                path = str(args.get("path", ""))
                self.writes[path] = self.writes.get(path, 0) + 1
                if self.writes[path] == self.REPEATS:
                    said = f"the same file written whole {self.REPEATS} times ({path[-45:]})"
            # The tools refuse an edit that changes nothing (tools._utils.
            # unchanged): it fails, and is counted here as what it is.
            if (out or "").lstrip().startswith("ERROR: nothing changed"):
                self.idle += 1
                if self.idle == 2:
                    said = said or (f"two edits that changed nothing "
                                    f"({str(args.get('path', ''))[-45:]})")
            # Always taken, so the record of states has no gaps.
            state = self._state(str(args.get("path", ""))) if ok else ""
            said = said or state
        if said:
            return said
        if step >= self.half and not self.half_said:
            self.half_said = True
            return "half the steps are spent and nothing is delivered"
        return ""

    def _state(self, path: str) -> str:
        """What the file now holds says about the edit just made, or ""."""
        if not path or self.root is None:
            return ""
        p = Path(path)
        p = p if p.is_absolute() else self.root / p
        try:
            now = hashlib.md5(p.read_bytes()).hexdigest()
        except OSError:
            return ""
        seen = self.states.setdefault(str(p), [])
        said = ""
        if seen and seen[-1] == now:
            self.idle += 1
            if self.idle == 2:
                said = f"two edits that changed nothing ({path[-45:]})"
        elif now in seen and str(p) not in self.back:
            self.back.add(str(p))
            said = (f"an edit undone: {path[-45:]} is back to what it was "
                    f"{len(seen) - seen.index(now)} edits ago")
        seen.append(now)
        return said
