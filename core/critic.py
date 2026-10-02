# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# critic.py — the work judged against the request, before it is delivered.
#
# The one who did the work is the wrong one to judge it: attention that was
# pointed forward, at finishing, does not turn round because it is asked to.
# So the judgement is a call of its own - the same model, with another mandate
# and other material - and it is made by the loop, never offered to the agent
# as a tool. That was tried: `critic_validate` sat in the palette for months
# and in 241 archived runs the agent never once called it.
#
# WHEN. At delivery, and only for a turn that changed something - a file
# written through a skill, or a command run. A turn that only read and
# answered is thought, and thought needs no inspector. Judging each step needs
# a success criterion for each step, which is a plan, and Pragma does not plan
# yet; until it does, the request is the only measure there is, and delivery is
# the one moment it can be held against the whole of the work.
#
# WHAT IT SEES. The request in the user's own words, the project's PRAGMA.md,
# a record of what was done built from the steps themselves - no model in
# between - the diffs of what the turn changed on disk, and the answer,
# labelled as a claim. NOT the agent's reasoning: a judge handed the producer's
# argument is a judge being argued with.
#
# WHAT IT SAYS. The requirements the request states, each met, missing or
# unverified with the evidence for it; a verdict; and when it sends the work
# back, the next action. A verdict of "revise" is only taken with something
# concrete to act on - a critic that only says no wastes what it knows.
#
# WHAT HAPPENS NEXT is not decided here: react.py holds that table, so that
# the critic judges and the loop disciplines, and neither does the other's job.

from __future__ import annotations

import difflib
import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import config
import llm_client
from json_parser import extract_json

# What counts as having touched the world. The file skills and the shell;
# reading, searching and fetching do not change anything anyone will find.
WORLD_SKILLS = frozenset({
    "write_file", "append_file", "replace_in_file", "replace_in_files",
    "insert_after", "insert_before", "apply_patch", "revert", "execute_command",
})

VERDICTS = ("accept", "revise", "ask_user")
STATUSES = ("met", "missing", "unverified")

# Directories never worth listing as "changed during the turn".
_SKIP_DIRS = {".git", ".pragma_checkpoints", "__pycache__", "node_modules",
              "venv", ".venv", "env", ".mypy_cache", ".pytest_cache", ".tox"}


_SYSTEM = """You are the critic. An agent has just finished a turn of work and is about
to deliver its answer. You did not do the work. Your job is to find out whether
what was done is what was asked, reading as someone who was not there and
looking for the reasons it might fall short.

You are given the REQUEST in the user's own words, the project's standing
INSTRUCTIONS, a RECORD of every step the agent took with what each returned,
the CHANGES on disk, and the agent's ANSWER. The answer is a claim. The record
and the changes are the evidence.

1. List the requirements the REQUEST states or plainly implies: each explicit
   instruction, constraint and deliverable, in the user's words where you can.
   Use the INSTRUCTIONS only where they bear on this request. Do not invent
   requirements nobody asked for; taste is not a requirement.
2. For each one decide:
   met         the record or the changes show it done - name the step or file
   missing     it was not done, or the evidence shows it done wrong
   unverified  it may be done, but nothing in the record shows it. A claim
               with no step behind it ("I verified it runs" with no run in the
               record) is unverified.
   Evidence must show the behaviour the requirement names, not merely that
   something ran. A command that exited cleanly, a file that parses, a test
   of the parts, show that much and no more. Ask what the user would see if
   the requirement did NOT hold, and whether the record rules that out: a
   program that must keep working over time, respond to input or produce a
   particular result is met only by a step that observed exactly that. If no
   step did, it is unverified, however sound the code looks.
3. Give a verdict:
   accept      every requirement is met; or what is left unverified cannot be
               checked from here, and the answer says so honestly
   revise      something is missing, or unverified and still checkable. Put
               the next action in "proposal": what to run, change or check -
               one or two actions, specific enough to carry out. When the
               gap is a missing observation, name the observation: what to
               run and what its output must show
   ask_user    the request can be read two ways and the work took one of them;
               only the user can settle it. Put the question in "proposal"
4. "aside" is optional: something the work produced outside the request that
   is worth pointing out in itself. Leave it empty otherwise.

Be strict about evidence and fair about scope. Do not send work back for style,
for extras nobody asked for, or for what cannot be checked here. Send it back
when the user would find something missing or broken.

Be brief: someone is waiting for the answer you are judging. "evidence" is a
pointer, not an argument - the step number or the file and a few words, a
dozen at most. Keep "aside" to one sentence, and empty unless it matters.

Reply with ONLY a JSON object:
{"requirements": [{"text": "...", "status": "met|missing|unverified", "evidence": "..."}],
 "verdict": "accept|revise|ask_user",
 "proposal": "...",
 "aside": "..."}"""


_SCHEMA = {
    "__name__": "review",
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text":     {"type": "string"},
                    "status":   {"type": "string", "enum": list(STATUSES)},
                    "evidence": {"type": "string"},
                },
                "required": ["text", "status"],
                "additionalProperties": False,
            },
        },
        "verdict":  {"type": "string", "enum": list(VERDICTS)},
        "proposal": {"type": "string"},
        "aside":    {"type": "string"},
    },
    "required": ["requirements", "verdict", "proposal"],
    "additionalProperties": False,
}


@dataclass
class Review:
    """One judgement of one delivery."""
    verdict: str = "unavailable"          # accept | revise | ask_user | unavailable
    requirements: list = field(default_factory=list)
    proposal: str = ""
    aside: str = ""
    why: str = ""                         # unavailable: what went wrong
    seconds: float = 0.0
    evidence_chars: int = 0
    round: int = 1

    def failing(self) -> list[dict]:
        return [r for r in self.requirements if r.get("status") != "met"]

    def met(self) -> int:
        return sum(1 for r in self.requirements if r.get("status") == "met")

    def as_dict(self) -> dict:
        return asdict(self)


def touched_world(ledger: list[dict]) -> bool:
    """Did this turn change anything - a file through a skill, or a command?"""
    return any(e.get("action") in WORLD_SKILLS for e in ledger)


# ── the evidence ─────────────────────────────────────────────────────────────

def _clip(text: str, head: int, tail: int = 0) -> str:
    """The start and, if asked, the end of a text, with how much was cut."""
    text = str(text or "")
    if len(text) <= head + tail + 40:
        return text
    cut = len(text) - head - tail
    out = text[:head] + f"\n[... {cut:,} characters not shown ...]"
    if tail:
        out += "\n" + text[-tail:]
    return out


def _args_line(action: str, args: dict) -> str:
    """What a step was asked to do, in one line: the target, not the payload.

    A write_file's content would be the whole file again - the diff below
    shows what it did - so only its size is said here.
    """
    args = dict(args or {})
    if action == "execute_command":
        return str(args.get("command", ""))[:400]
    bits = []
    for k, v in args.items():
        if k in ("content", "new", "old", "patch", "text"):
            bits.append(f"{k}=<{len(str(v)):,} chars>")
        else:
            s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
            bits.append(f"{k}={s[:160]}")
    return ", ".join(bits)


def _record(ledger: list[dict], budget: int) -> str:
    """Every step, in order, with what it returned - the recent ones fullest.

    The end of the work is where the evidence for the answer is: the last run
    of the tests, the last look at the output. So the budget for outputs is
    spent from the end backwards, and the early steps keep their one line.
    """
    if not ledger:
        return "(no steps)"
    heads = [f"[{e.get('step')}] {e.get('action')}  {_args_line(e.get('action', ''), e.get('args'))}"
             for e in ledger]
    left = max(0, budget - sum(len(h) + 1 for h in heads))
    outs = [""] * len(ledger)
    for i in range(len(ledger) - 1, -1, -1):
        obs = str(ledger[i].get("observation", ""))
        if left <= 200:
            outs[i] = "    -> " + _clip(obs, 120).replace("\n", "\n       ")
            left -= min(len(outs[i]), 160)
            continue
        share = min(left, 2400 if i >= len(ledger) - 6 else 600)
        body = _clip(obs, int(share * 0.6), int(share * 0.3))
        outs[i] = "    -> " + body.replace("\n", "\n       ")
        left -= len(outs[i])
    return "\n".join(h + "\n" + o for h, o in zip(heads, outs))


def _read(p: Path) -> str | None:
    try:
        raw = p.read_bytes()
    except Exception:
        return None
    if b"\0" in raw[:4096]:
        return None
    return raw.decode("utf-8", "replace")


def _diffs(before: dict, root: Path | None, budget: int) -> tuple[str, set[str]]:
    """What the turn changed through the file skills, as diffs. Returns the
    text and the paths it covered."""
    if not before or root is None:
        return "", set()
    import checkpoint
    parts, seen = [], set()
    per = max(800, budget // max(1, len(before)))
    for rel, old in sorted(before.items()):
        seen.add(rel)
        exists = (root / rel).is_file()
        now = _read(root / rel) if exists else None
        if old is None and not exists:
            continue                              # made and removed again
        if old is None:
            parts.append(f"NEW FILE {rel} (not text: not shown)" if now is None else
                         f"NEW FILE {rel} ({len(now.splitlines())} lines)\n"
                         + _clip(now, int(per * 0.7), int(per * 0.2)))
        elif not exists:
            parts.append(f"DELETED {rel}")
        elif old == checkpoint.UNREADABLE or now is None:
            parts.append(f"CHANGED {rel} (large or not text: not shown)")
        elif old == now:
            parts.append(f"UNCHANGED {rel} (edited and put back)")
        else:
            diff = "".join(difflib.unified_diff(
                old.splitlines(keepends=True), now.splitlines(keepends=True),
                fromfile=f"{rel} (before this turn)", tofile=f"{rel} (now)", n=2))
            parts.append(_clip(diff, int(per * 0.8), int(per * 0.15)))
    return "\n\n".join(parts), seen


def _written_by_commands(root: Path | None, since: float, known: set[str],
                         budget: int) -> str:
    """Files that changed during the turn without going through a file skill:
    a script's output, a file a command wrote. Their before is unknown, so the
    list says what they are now - and shows the small text ones."""
    if root is None:
        return ""
    found, looked = [], 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".pragma")]
        for name in filenames:
            looked += 1
            if looked > 5000 or len(found) >= 20:
                break
            p = Path(dirpath) / name
            try:
                st = p.stat()
            except OSError:
                continue
            rel = p.relative_to(root).as_posix()
            if st.st_mtime >= since and rel not in known and not name.startswith(".pragma_session"):
                found.append((rel, st.st_size, p))
    if not found:
        return ""
    lines, shown = [], 0
    for rel, size, p in found:
        lines.append(f"{rel} ({size:,} bytes)")
        if shown < 3 and size <= 4000:
            text = _read(p)
            if text is not None and text.strip():
                lines.append("    " + _clip(text, min(1200, budget // 4)).replace("\n", "\n    "))
                shown += 1
    return "\n".join(lines)


def _project_instructions(root: Path | None) -> str:
    """PRAGMA.md as the agent is given it, without the header that tells the
    agent how to treat it - the critic is told that by its own prompt."""
    try:
        from agent import prompts
    except Exception:
        return ""
    try:
        text = prompts.project_contract(str(root)) if root else ""
    except Exception:
        return ""
    return text[len(prompts._CONTRACT_HEADER):].strip() if text else ""


def evidence(request: str, claim: str, ledger: list[dict], before: dict,
             root: Path | None, since: float, previous: "Review | None" = None) -> str:
    """The material the critic reads, within config.CRITIC_EVIDENCE_CHARS."""
    total = int(getattr(config, "CRITIC_EVIDENCE_CHARS", 24000))
    request = _clip(request, 4000, 1000)
    claim = _clip(claim, 3000, 800)
    rules = _clip(_project_instructions(root), 2000)
    room = max(4000, total - len(request) - len(claim) - len(rules) - 1200)
    diffs, covered = _diffs(before, root, int(room * 0.4))
    others = _written_by_commands(root, since, covered, int(room * 0.1))
    record = _record(ledger, room - len(diffs) - len(others))

    parts = [f"REQUEST (the user's own words):\n{request}",
             f"INSTRUCTIONS (the project's PRAGMA.md):\n{rules or '(none)'}",
             f"RECORD (every step of this turn, in order; outputs clipped):\n{record}",
             "CHANGES ON DISK:\n" + (diffs or "(no file was changed through the file tools)")]
    if others:
        parts.append("ALSO CHANGED DURING THE TURN (by commands; before-state unknown):\n" + others)
    parts.append(f"ANSWER (the agent's claim, to be checked against the above):\n{claim}")
    if previous is not None and previous.verdict == "revise":
        gaps = "; ".join(f"{r.get('status')}: {r.get('text')}" for r in previous.failing())
        parts.append("YOUR PREVIOUS REVIEW sent the work back for: "
                     f"{gaps or '(no requirement named)'}. Proposed: {previous.proposal}\n"
                     "Judge whether that was dealt with - or, if the agent disagreed "
                     "in its answer, whether its reason holds.")
    return "\n\n".join(parts)


# ── the judgement ────────────────────────────────────────────────────────────

def _parse(raw) -> Review:
    try:
        data = extract_json(raw) if isinstance(raw, str) else raw
    except Exception:
        data = None
    if not isinstance(data, dict):
        return Review(why="the reply was not JSON")
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS:
        return Review(why=f"no verdict in the reply ({verdict or 'empty'})")
    reqs = []
    for r in data.get("requirements") or []:
        if not isinstance(r, dict) or not str(r.get("text", "")).strip():
            continue
        status = str(r.get("status", "")).strip().lower()
        reqs.append({"text": str(r["text"]).strip(),
                     "status": status if status in STATUSES else "unverified",
                     "evidence": str(r.get("evidence", "") or "").strip()})
    proposal = str(data.get("proposal", "") or "").strip()
    rv = Review(verdict=verdict, requirements=reqs, proposal=proposal,
                aside=str(data.get("aside", "") or "").strip())
    # Sent back with nothing to act on is not a review. With failing
    # requirements the list itself is the thing to act on; with neither, the
    # answer goes out as it stands and the record says why.
    if verdict == "revise" and not proposal:
        if rv.failing():
            rv.proposal = "Deal with: " + "; ".join(r["text"] for r in rv.failing())
        else:
            return Review(why="sent back with nothing to act on", requirements=reqs)
    if verdict == "ask_user" and not proposal:
        return Review(why="asked the user without a question", requirements=reqs)
    return rv


def review(request: str, claim: str, ledger: list[dict], before: dict,
           root: Path | None, since: float, round_no: int = 1,
           previous: Review | None = None, model=None, stop_event=None) -> Review:
    """Judge one delivery. Never raises, except to let a stop through."""
    t0 = time.monotonic()
    text = evidence(request, claim, ledger, before, root, since, previous)
    # The agent's loop reads the last call's token counts to decide when to
    # compress, and the harness adds them up for the turn. The critic's call is
    # neither, so what it leaves behind is put back.
    kept_stats = dict(getattr(llm_client, "LAST_STATS", {}) or {})
    kept_call = dict(getattr(llm_client, "LAST_CALL", {}) or {})
    try:
        with llm_client.faculty("CRITIC"):
            raw = llm_client.call_llm(
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": text}],
                model=model,
                max_tokens=config.MEMORY_MAX_TOKENS,
                stop_event=stop_event,
                **config.memory_call("select"),
                response_schema=_SCHEMA,
            )
        rv = _parse(raw)
    except llm_client.LLMInterrupted:
        raise
    except Exception as e:
        rv = Review(why=f"{type(e).__name__}: {str(e)[:160]}")
    finally:
        llm_client.LAST_STATS = kept_stats
        llm_client.LAST_CALL = kept_call
    rv.seconds = round(time.monotonic() - t0, 1)
    rv.evidence_chars = len(text)
    rv.round = round_no
    return rv


# ── what the loop does with it ───────────────────────────────────────────────

def sent_back(rv: Review, n: int, most: int) -> str:
    """The message that returns the work to the agent."""
    lines = [f"[CRITIC]: before this is delivered, a review of the work against the "
             f"request found it incomplete (send-back {n} of at most {most})."]
    for r in rv.failing():
        ev = f" ({r['evidence']})" if r.get("evidence") else ""
        lines.append(f"- {r['status']}: {r['text']}{ev}")
    lines.append(f"Next: {rv.proposal}")
    lines.append("Do that now, with a tool call. Then give your complete answer again. "
                 "If you think the review is wrong, say why in that answer: it will "
                 "be read.")
    return "\n".join(lines)


def closing_note(rv: Review, sends: int) -> str:
    """What goes under an answer delivered with something still open."""
    if rv.verdict == "ask_user":
        return f"\n\n> **Critic, a question for you:** {rv.proposal}"
    if rv.verdict == "revise":
        open_ = "\n".join(f"> - {r['status']}: {r['text']}" for r in rv.failing())
        return (f"\n\n> **Critic, still open after {sends} "
                f"send-back{'s' if sends != 1 else ''}:**\n" + (open_ or f"> - {rv.proposal}"))
    return ""


def summary(rv: Review, sends: int, most: int) -> tuple[str, list[str]]:
    """(one line, details) for the screen - said to a person, not a parser."""
    secs = f" · {rv.seconds:.0f}s" if rv.seconds >= 1 else ""
    if rv.verdict == "unavailable":
        return f"not available ({rv.why}) · delivered as it stands{secs}", []
    total = len(rv.requirements)
    count = f"{rv.met()} of {total} requirement{'s' if total != 1 else ''} met" if total else "no requirements named"
    details = [f"{r['status']}: {r['text']}" for r in rv.failing()]
    if rv.aside:
        details.append(f"aside: {rv.aside}")
    if rv.verdict == "accept":
        return f"{count} · delivered{secs}", details
    if rv.verdict == "ask_user":
        return f"{count} · a question for you: {rv.proposal}{secs}", details
    if sends < most:
        return f"{count} · sent back: {rv.proposal}{secs}", details
    return f"{count} · delivered with points still open ({sends} send-backs used){secs}", details


def snapshot_workspace(root: Path | None, dest: str) -> None:
    """The workspace as it was at the first delivery, for the bench. Once."""
    if not dest or root is None:
        return
    target = Path(dest)
    if target.exists():
        return
    try:
        shutil.copytree(root, target, ignore=shutil.ignore_patterns(
            ".pragma_checkpoints", "__pycache__", ".git", "venv", ".venv", "node_modules"))
    except Exception:
        pass
