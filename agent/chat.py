# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# agent/chat.py — a live session: many turns, one conversation.
#
# `agent.batch` runs ONE request and consolidates it into an episode. Between
# two batch runs the agent remembers nothing directly: the only bridge is the
# curator, which must find the past again from the words of the new request.
# That works, but it means every request starts by meeting the user afresh.
#
# A session keeps the conversation in front of the agent while it lasts, and
# turns it into memory when it ends. Inside the session you can say "that table
# we discussed"; between sessions the curator takes over again.
#
# WHAT BECOMES AN EPISODE. One user turn = one episode, exactly the granularity
# `agent.batch` produces today. The boundaries are the user's own messages, so
# no judgement is needed to find them and no faculty has to be invented for
# this phase. Consolidating a whole conversation into a single episode would be
# simpler still and much worse: importance would average across everything said
# in an evening, and the salience signal — a crisis outweighing routine — is
# precisely what averaging destroys.
#
# WHY CONSOLIDATION IS DEFERRED. It costs ~40s on a 27B. Running it after every
# message would leave the user waiting three quarters of the time. So the turns
# are recorded as they happen and consolidated together at the end.
#
# WHAT THAT COSTS. A crash between the first turn and the exit would lose the
# session's memory. The raw transcript is therefore appended to disk after
# every turn, before anything else can fail: consolidation can then be re-run
# from it. A memory may arrive late; it must not disappear.
#
# RECALL. The curator runs once per turn, on the user's words, and prepends
# what it chose to that turn. The desk only grows: a fragment already placed is
# excluded from later turns, so it is neither pasted nor reinforced twice.
#
# NOT IN THIS PHASE: consolidation on context overflow. See the plan.

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_CORE = _ROOT / "core"
for p in (str(_ROOT), str(_CORE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import config as baseline_config          # noqa: E402
import llm_client                          # noqa: E402
from react import AgentConfig, run_agent   # noqa: E402
from skills import palette as skills_palette   # noqa: E402
from skills import skills_summary_for      # noqa: E402

from agent.batch import (                  # noqa: E402
    _PrettyRenderer,
    _make_on_step,
    batch_ask_user,
)
from agent.prompts import build_system_prompt, project_contract  # noqa: E402

_EXIT_WORDS = {"/exit", "/quit", "/bye", "exit", "quit"}


class Turn:
    """One user message and everything the agent did about it."""

    def __init__(self, text: str):
        self.text = text
        self.transcript: list[str] = [f"USER: {text}"]
        self.started = datetime.now(timezone.utc)


def _append_raw_log(path: Path, turn: Turn) -> None:
    """Persist the turn before anything else can fail.

    Written as one JSON object per line: an interrupted write costs the last
    line, not the file. This is what makes deferred consolidation safe to
    interrupt — the conversation survives even when the session does not.
    """
    try:
        rec = {"ts": turn.started.strftime("%Y-%m-%dT%H:%M:%SZ"),
               "user": turn.text, "transcript": turn.transcript}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass          # a logging failure must never end the session


def _consolidate(turns: list[Turn], cwd: Path, renderer) -> None:
    """Decide what was memorable, then write one episode per kept turn.

    The order matters: the segmenter runs FIRST, so a discarded turn is never
    written and can never be linked to. Consolidating everything and pruning
    afterwards would leave later episodes pointing at deleted ones.
    """
    if not turns:
        return
    try:
        from skills.episode_consolidate.skill import episode_consolidate_detailed
    except Exception as e:
        renderer.error(None, f"consolidation unavailable: {e}")
        return

    import segmenter
    renderer.faculty_running("SEGMENTER", "deciding what was worth keeping…")
    segments, reason = segmenter.segment([t.text for t in turns])
    renderer.faculty("SEGMENTER",
                     segmenter.describe(segments, len(turns))
                     + (f" — {reason}" if reason else ""))

    kept = [(idx, why) for idx, keep, why in segments if keep]
    if not kept:
        return

    renderer.faculty_running(
        "CONSOLIDATOR", f"writing {len(kept)} episode(s) from this session…")
    for i, (idx, _why) in enumerate(kept, 1):
        # A merged segment is consolidated as ONE experience: the turns are
        # joined in order, so the episode holds the request and how it turned
        # out rather than splitting them across two thin memories.
        transcript = "\n".join(line for j in idx for line in turns[j].transcript)
        try:
            res = episode_consolidate_detailed(
                transcript=transcript, workspace=str(cwd), source="chat")
            renderer.faculty("CONSOLIDATOR",
                             f"[{i}/{len(kept)}] {res.get('summary', '')}")
        except Exception as e:
            renderer.error(None, f"episode {i} failed: {e}")


def _recall(text: str, cwd, desk_ids: set[str], desk_rules: set[str],
            renderer, first_turn: bool) -> str:
    """The curator's contribution to one turn, or "".

    WHY ONCE PER TURN AND NOT ONCE PER SESSION. A conversation changes subject.
    Curating only at the start would hand the agent whatever matched the
    opening pleasantry and nothing for the four topics that follow.

    WHY THE DESK ONLY GROWS. Every block stays in the history it was prepended
    to, so a memory fetched at turn three is still in front of the agent at
    turn eleven. Fetching it again would paste it twice and, worse, reinforce
    it twice: salience would then measure how long a conversation ran rather
    than what mattered in it. `desk_ids` is what makes recall idempotent.

    WHY THE FIRST TURN IS SPECIAL. With no keyword match the curator is offered
    the most recent episodes instead — worth one LLM call at the opening, where
    the question is usually about the past itself and shares no words with it
    ("what do you know about me?"), and not worth one on every later turn.

    Failure is silent by design: a session must not die because recall did.
    """
    try:
        import curator
        info = curator.curate_knowledge_detailed(
            text, workspace=str(cwd),
            exclude_ids=desk_ids, exclude_rules=desk_rules,
            require_match=not first_turn)
    except Exception as e:
        renderer.faculty("CURATOR", f"recall unavailable — {e}")
        return ""

    if not info["block"]:
        return ""
    desk_ids.update(info["episode_ids"])
    desk_rules.update(info["rule_texts"])

    pool = f"{info['n_ep']} memories + {info['n_ln']} rules"
    if info["fallback"]:
        renderer.faculty("CURATOR", f"{pool} → deterministic fallback "
                                    f"(curator unavailable)")
    else:
        note = f"{pool} → recalled {len(info['selected'])}"
        if info["reason"]:
            note += f" — {info['reason']}"
        renderer.faculty("CURATOR", note, info["selected"])
    return info["block"]


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="python -m agent.chat",
        description="Pragma live session: many turns, one conversation.")
    ap.add_argument("--cwd", default=None,
                    help="workspace (default: PRAGMA_WORKSPACE, else cwd)")
    ap.add_argument("--max-steps", type=int, default=None,
                    help="step budget per turn")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--memory", action="store_true",
                    help="consolidate the session into episodes on exit")
    args = ap.parse_args()

    # A model reply containing an emoji must not end the conversation: the
    # Windows console defaults to cp1252 and raises on the first one it cannot
    # encode. Same treatment batch gives its own output.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Same resolution order as batch: --cwd > PRAGMA_WORKSPACE > current dir.
    cwd = Path(args.cwd or os.environ.get("PRAGMA_WORKSPACE") or Path.cwd()).resolve()
    if not cwd.is_dir():
        print(f"ERROR: workspace not found: {cwd}", file=sys.stderr)
        return 1
    # Same guard as batch: Pragma must never edit the agent that is running.
    if _ROOT == cwd or _ROOT in cwd.parents:
        print(f"ERROR: refusing to work inside Pragma's own source tree ({cwd})",
              file=sys.stderr)
        return 1

    ok, detail = llm_client.ping_models()
    if not ok:
        print(f"ERROR: LLM endpoint unreachable — {detail}", file=sys.stderr)
        return 1

    skills = skills_palette()
    skills["ask_user"] = batch_ask_user
    # One channel, always curated — the same rule as `agent.batch`. The raw
    # recall skills would be a second, uncurated way in: they reinforce and
    # revive on keyword overlap alone, with no judgment between the prefilter
    # and the write, so an agent free to call them turns salience into a count
    # of how often a word recurred. The curator reinforces only what it chose.
    skills.pop("recall_episodes", None)
    skills.pop("recall_learnings", None)

    coding_model = baseline_config.CODING_MODEL or baseline_config.DEFAULT_MODEL
    system_prompt = build_system_prompt(
        str(cwd),
        default_model=baseline_config.DEFAULT_MODEL,
        coding_model=coding_model,
        skills_summary=skills_summary_for(skills.keys()),
        protocol=getattr(baseline_config, "LLM_TOOL_PROTOCOL", "text"),
    ) + project_contract(cwd)

    renderer = _PrettyRenderer()
    served = getattr(baseline_config, "SERVED_MODEL", "") or baseline_config.DEFAULT_MODEL
    max_steps = args.max_steps or baseline_config.MAX_STEPS

    log_path = cwd / ".pragma_session.jsonl"
    print()
    print(f"  Pragma live session · {served} · {cwd}")
    print(f"  memory: {'recall on + consolidation on exit' if args.memory else 'off'}"
          f" · max {max_steps} steps per turn")
    print("  /exit to close the session (Ctrl+C also consolidates)")
    print()

    cfg = AgentConfig(
        name="Pragma",
        system_prompt=system_prompt,
        skills=skills,
        final_keys=("conclusion",),
        model=baseline_config.DEFAULT_MODEL,
        temperature=args.temperature,
        max_steps=max_steps,
    )

    history: list | None = None
    turns: list[Turn] = []
    # What the curator has already put in front of the agent, for the whole
    # conversation. It is not a cache: the desk IS the history, because the
    # block is prepended to the turn it was fetched for and stays there. The
    # sets are what stops it being fetched a second time.
    desk_ids: set[str] = set()
    desk_rules: set[str] = set()

    try:
        while True:
            try:
                text = input("you > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            if text.lower() in _EXIT_WORDS:
                break

            # The Turn — and so the raw log, and so what the segmenter reads
            # on exit — keeps the user's words alone. Only the prompt carries
            # the recalled memory: a knowledge block replayed as if the user
            # had typed it would corrupt segmentation and then the episodes.
            turn = Turn(text)
            prompt = text
            if args.memory:
                block = _recall(text, cwd, desk_ids, desk_rules, renderer,
                                first_turn=not turns)
                if block:
                    prompt = f"{block}\n\n{text}"

            result = run_agent(
                cfg, prompt,
                on_step=_make_on_step(renderer, 0, turn.transcript),
                history=history,
            )
            if result is None:          # interrupted mid-turn
                _append_raw_log(log_path, turn)
                turns.append(turn)
                break

            conclusion = result.get("conclusion", "") or ""
            turn.transcript.append(f"FINAL: {conclusion[:2000]}")

            # Persist BEFORE displaying. Rendering is the least important thing
            # here and one of the likelier to fail — an emoji in the reply was
            # enough to kill the session on a cp1252 console, and with the write
            # after the render the turn was lost with it. The order is the
            # guarantee, so it has to be this way round.
            _append_raw_log(log_path, turn)
            turns.append(turn)
            history = result.get("messages") or history

            renderer.conclusion(result.get("forced", False), 0.0, conclusion)
    except KeyboardInterrupt:
        print()

    if args.memory:
        _consolidate(turns, cwd, renderer)
    elif turns:
        print(f"\n  {len(turns)} turn(s) recorded in {log_path.name} "
              f"(no --memory: nothing was consolidated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
