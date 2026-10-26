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

It is not the critic either. The critic judges the finished work against the
request before it is delivered; the advisor works at the start and in the
middle. Neither sees what the other said.

Off unless a project turns it on (/settings): `plan`, or `consult` for the
plan and the advice. A single task takes --advisor.
"""

from __future__ import annotations

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
Check: <how to show it works - what to run, with what input. For a program \
that waits for keys or takes over the terminal: the parts that can be called \
and checked on their own, not the whole program driven from outside>
Watch out: <the risk you see, two lines at most>
Stop and ask if: <the condition in which guessing is worse than asking>

Name files by the paths in the listing. Plan the request and nothing beyond \
it. Do not write code."""

_CONSULT_SYSTEM = _ROLE + """

The agent has stopped making progress, and Pragma has called you. Read what \
it has done and tell it what to do next, in this form and nothing else, ten \
lines at most:

Diagnosis: <what is going wrong, one or two lines>
Next: <exactly one of these three>
  - the next one to three actions, concrete
  - deliver what you have, and say what is missing
  - stop and ask the person: <the question>

A line or two of code at most."""

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


def _ask(system: str, payload: str, stop_event=None) -> tuple[str, float]:
    t0 = time.monotonic()
    with llm_client.faculty("ADVISOR"):
        raw = llm_client.call_llm(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": payload}],
            max_tokens=config.MAX_TOKENS,
            **config.memory_call("write"),
            stop_event=stop_event,
        )
    return _clean(raw), time.monotonic() - t0


def plan(task: str, history: list | None, root, stop_event=None) -> dict:
    """The plan for this turn.

    {"text": the plan, or "" for NO PLAN, "line": what the screen says,
     "seconds", "error": "" or why there is none}. Never raises but for a stop
    (llm_client.LLMInterrupted): a turn must not fail because its advisor did.
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
        text, took = _ask(_PLAN_SYSTEM, "\n".join(parts), stop_event)
    except llm_client.LLMInterrupted:
        raise
    except Exception as e:
        return {"text": "", "line": f"no plan - {type(e).__name__}: {str(e)[:80]}",
                "seconds": 0.0, "error": str(e)[:200]}
    if not text or text.upper().startswith("NO PLAN"):
        return {"text": "", "line": f"no plan needed · {took:.0f}s", "seconds": took, "error": ""}
    steps = len(re.findall(r"^\s*\d+[.)]\s", text, flags=re.MULTILINE))
    done = re.search(r"^\s*Done when:\s*(.+)$", text, flags=re.MULTILINE | re.IGNORECASE)
    line = "plan"
    if steps:
        line += f" · {steps} step{'s' if steps != 1 else ''}"
    if done:
        what = done.group(1).strip()
        line += f" · done when: {what[:70]}{'…' if len(what) > 70 else ''}"
    return {"text": text, "line": f"{line} · {took:.0f}s · /plan shows it",
            "seconds": took, "error": ""}


def consult(request: str, plan_text: str, ledger: list[dict], signal: str,
            stop_event=None) -> dict:
    """Advice for an agent that has stopped making progress. Same shape as
    plan(); never raises but for a stop."""
    parts = ["[What the person asked]", (request or "").strip()]
    if plan_text:
        parts += ["", "[Your plan for it]", plan_text]
    parts += ["", f"[Why you are called] {signal}",
              "", "[What the agent has done, step by step]", record(ledger)]
    try:
        text, took = _ask(_CONSULT_SYSTEM, "\n".join(parts), stop_event)
    except llm_client.LLMInterrupted:
        raise
    except Exception as e:
        return {"text": "", "line": f"no advice - {type(e).__name__}: {str(e)[:80]}",
                "seconds": 0.0, "error": str(e)[:200]}
    if not text:
        return {"text": "", "line": f"no advice given · {took:.0f}s", "seconds": took, "error": ""}
    nxt = re.search(r"^\s*Next:\s*(.*)$", text, flags=re.MULTILINE | re.IGNORECASE)
    said = (nxt.group(1).strip() if nxt else "") or "advice"
    return {"text": text,
            "line": f"{signal} → {said[:60]}{'…' if len(said) > 60 else ''} · {took:.0f}s",
            "seconds": took, "error": ""}


# ── when to ask ───────────────────────────────────────────────────────────────

class Watch:
    """The two signals of a run going nowhere that the loop does not already
    watch for: half the steps spent with nothing delivered, and nearly the
    same thing done three times over. (The other two - the same call failing
    over and over, most calls failing - are react.py's watchdogs, which tell
    this one when they fire.)

    The repetition is counted by what a step is ABOUT, not by its exact
    arguments: the snake run's six terminal scripts each differed by a line,
    and each began the same way."""

    REPEATS = 3

    def __init__(self, max_steps: int):
        self.half = max(2, int(max_steps or 0) // 2)
        self.counts: dict[str, int] = {}
        self.half_said = False

    @staticmethod
    def _about(action: str, args: dict) -> str:
        args = args or {}
        if action == "execute_command":
            return "run: " + " ".join(str(args.get("command", "")).split())[:60]
        if action == "write_file":
            return f"write: {args.get('path', '')}"
        return ""

    def after(self, step: int, action: str, args: dict) -> str:
        """The signal this step gives, or ""."""
        about = self._about(action, args)
        if about:
            self.counts[about] = self.counts.get(about, 0) + 1
            if self.counts[about] == self.REPEATS:
                what = about.split(": ", 1)[1]
                verb = "run" if about.startswith("run") else "written"
                return f"nearly the same thing {verb} {self.REPEATS} times ({what[:50]})"
        if step >= self.half and not self.half_said:
            self.half_said = True
            return "half the steps are spent and nothing is delivered"
        return ""
