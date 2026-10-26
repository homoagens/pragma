# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""A conversation with a project, apart from whoever shows it.

The terminal (agent/chat.py) and a project served to another program
(agent/serve.py) hold the same kind of conversation: the memory recalled
before each turn, the turns recorded as they happen, the context compacted
when it fills up, and what was said handed to the memory when it ends. That
is here, once; how a turn is drawn, what the person types and how a program
talks to it stay with each of them.
"""
from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import advisor
import config as baseline_config
import llm_client
from react import _msg_chars, run_agent

from agent.batch import _make_on_step, _pool_line
from agent.harness import plural

# Said once in a conversation, not at every turn: see recall().
_SEARCH_WARNED: list = []


def project_settings() -> dict:
    """What the open project has decided for itself, as the registry has it."""
    name = os.environ.get("PRAGMA_PROJECT", "").strip()
    import pragma_registry
    return pragma_registry.settings_of(name) if name else {}


# How a compaction summary opens. It is how the loop tells a history that is
# already a summary from one that could still be made into one.
_COMPACTED = "[This conversation was compacted to make room in the context."


def compact_summary(history: list, renderer, instructions: str = "",
                     stop_event=None, said: str = "") -> list | None:
    """The conversation traded for one summary to go on working from.

    WHAT /compact DOES, and what happens unasked when the context fills up.
    Everything but the system prompt is handed to the summarizer, whole while
    it fits, and replaced by what comes back. Nothing is kept verbatim: a
    conversation worth keeping the last turns of is one that still fits.

    The turns themselves are untouched. They are what the memory is written
    from when the project closes, and a summary made to keep working is not
    what an episode is made of.

    Returns the new history, or None when there is nothing to compact - an
    empty conversation, or one that is already nothing but a summary. Raises
    what a stop raises; the caller keeps the history it had.
    """
    if not history:
        return None
    head = history[:1] if history[0].get("role") == "system" else []
    body = history[len(head):]
    if not body or (len(body) == 1
                    and str(body[0].get("content") or "").startswith(_COMPACTED)):
        return None
    import time as _time

    import memory
    chars = sum(_msg_chars(m) for m in body)
    weighed = renderer.last_prompt_tokens()
    # Characters per token on this conversation, as the server last counted
    # it; the summarizer's budget is worked out from it (memory._RATIO).
    ratio = (sum(_msg_chars(m) for m in history) / weighed) if weighed else None
    renderer.faculty_running("COMPACTOR", said or "summarising the conversation so far…")
    t0 = _time.monotonic()
    summary = memory.compact(body, instructions, ratio=ratio, stop_event=stop_event)
    carried = {"role": "user", "content": (
        f"{_COMPACTED} What follows is a summary of everything before this "
        f"point; the messages themselves are gone.]\n\n{summary}")}
    renderer.faculty("COMPACTOR",
                     f"{plural(len(body), 'message')}, {chars:,} characters → one summary "
                     f"of {len(summary):,} · {_time.monotonic() - t0:.0f}s")
    return head + [carried]


class Turn:
    """One user message and everything the agent did about it."""

    def __init__(self, text: str):
        self.text = text
        self.transcript: list[str] = [f"USER: {text}"]
        self.started = datetime.now(timezone.utc)


def append_raw_log(path: Path, turn: Turn) -> None:
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


def consolidate(turns: list[Turn], cwd: Path, renderer,
                 note: str = "this session") -> list[dict]:
    """Decide what was memorable, then write one episode per kept segment.

    The order matters: the segmenter runs FIRST, so a discarded turn is never
    written and can never be linked to. Consolidating everything and pruning
    afterwards would leave later episodes pointing at deleted ones.

    Returns the episodes actually written, read back from the store — the
    caller compacting a conversation needs their content, not just a count.
    """
    if not turns:
        return []
    try:
        from tools.episode_consolidate.tool import episode_consolidate_detailed
    except Exception as e:
        renderer.error(None, f"consolidation unavailable: {e}")
        return []

    import segmenter
    renderer.faculty_running("SEGMENTER", "deciding what was worth keeping…")
    segments, reason = segmenter.segment([t.text for t in turns])
    renderer.faculty("SEGMENTER",
                     segmenter.describe(segments, len(turns))
                     + (f" — {reason}" if reason else ""))

    kept = [(idx, why) for idx, keep, why in segments if keep]
    if not kept:
        return []

    renderer.faculty_running(
        "CONSOLIDATOR", f"writing {_so_many(len(kept), 'episode')} from {note}…")
    written: list[dict] = []
    for i, (idx, _why) in enumerate(kept, 1):
        # A merged segment is consolidated as ONE experience: the turns are
        # joined in order, so the episode holds the request and how it turned
        # out rather than splitting them across two thin memories.
        transcript = "\n".join(line for j in idx for line in turns[j].transcript)
        try:
            # Only this loop knows which of how many is in flight, so the
            # progress is set here while the faculty names itself further down.
            # Writing four episodes on a slow endpoint is minutes of spinner:
            # "2/4" is the difference between waiting and wondering.
            with llm_client.step(f"{i}/{len(kept)}"):
                # Name the segment so that consolidating it twice writes one
                # episode. The first turn's start is stable across a retry and
                # differs between segments, which a single per-session id would
                # not: chat files one episode per kept segment.
                sid = (f"chat:{cwd}:"
                       f"{turns[idx[0]].started.strftime('%Y%m%dT%H%M%S')}")
                res = episode_consolidate_detailed(
                    transcript=transcript, workspace=str(cwd), source="chat",
                    session_id=sid)
            ep = load_episode(res.get("episode_id", ""))
            _say_written(renderer, res, ep, i, len(kept))
            if ep:
                written.append(ep)
        except Exception as e:
            renderer.error(None, f"episode {i} failed: {e}")
    return written


def _so_many(n: int, one: str, many: str = "") -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _say_written(renderer, res: dict, ep: dict | None, i: int, n: int) -> None:
    """What writing one episode did to the memory, faculty by faculty.

    It used to be one line, the skill's own: "[1/1] OK: episode
    ep_20261007_101500_3fa2 saved (0 surprises); semantics: +2 assertions, 1
    confirmed, 0 contradicted; reconsolidated 1 episode(s)". Every word of it
    is true and none of it says what was written: an identifier, a count of
    surprises, and the names the code gives to things.

    So each faculty says its own part, as it does everywhere else: the
    consolidator WHAT it wrote - the episode's goal, which is the memory in
    one line - the reconsolidator what it re-read and why, the abstractor
    what is believed now that was not before. A faculty with nothing to say
    says nothing.
    """
    which = f"({i}/{n}) " if n > 1 else ""
    summary = str(res.get("summary", "") or "")
    if res.get("status") != "ok" or res.get("already_consolidated") or not ep:
        renderer.faculty("CONSOLIDATOR", which + (summary or "nothing was written"))
        return

    notes = []
    if res.get("surprises"):
        notes.append(_so_many(int(res["surprises"]), "surprise") + " in it")
    if "fallback" in summary:
        notes.append("the model did not write it: a plain record of the turns was kept")
    swept = res.get("sweep") or {}
    if swept.get("dormant"):
        notes.append(_so_many(len(swept["dormant"]), "older memory", "older memories") + " went dormant")
    if swept.get("deleted"):
        notes.append(_so_many(len(swept["deleted"]), "memory", "memories") + " forgotten for good")
    if res.get("embed_error"):
        notes.append("what it is related to was found by words - the embedding server did not answer "
                     f"({res['embed_error']})")
    renderer.faculty("CONSOLIDATOR", which + (str(ep.get("goal") or "").strip() or "an episode"), notes)

    reread = res.get("reconsolidated") or []
    if res.get("reconsolidate_error"):
        renderer.faculty("RECONSOLIDATOR", f"did not run - {res['reconsolidate_error']}")
    elif reread:
        renderer.faculty("RECONSOLIDATOR", _so_many(len(reread), "earlier memory", "earlier memories") + " re-read",
                         [str(r.get("reason", "")).strip() for r in reread if r.get("reason")][:3])

    if res.get("semantic_ran"):
        new = res.get("new_assertions") or []
        reworded = res.get("reformulated") or []
        counts = [(len(new), "new belief", "new beliefs"),
                  (len(res.get("confirmed") or []), "confirmed", "confirmed"),
                  (len(res.get("contradicted") or []), "contradicted", "contradicted"),
                  (len(reworded), "reworded", "reworded"),
                  (len(res.get("retired") or []), "retired", "retired"),
                  (int(res.get("merged_beliefs") or 0), "folded into another", "folded into others")]
        said = [_so_many(k, one, many) for k, one, many in counts if k]
        details = [f"belief: {str(a.get('text', '')).strip()}" for a in new[:3] if a.get("text")]
        details += [f"reworded: {str(r.get('to', '')).strip()}" for r in reworded[:2] if r.get("to")]
        renderer.faculty("ABSTRACTOR", " · ".join(said) or "nothing new to believe", details)


def _spool(turns: list[Turn]) -> list[dict]:
    """The turns as plain data, for a worker in another process."""
    return [{"text": t.text,
             "transcript": list(t.transcript),
             "started": t.started.strftime("%Y-%m-%dT%H:%M:%SZ")}
            for t in turns]


def consolidate_later(turns: list[Turn], cwd: Path,
                       note: str = "this session") -> bool:
    """Hand the turns to a detached worker. False means do it here instead.

    LEAVING SHOULD NOT TAKE LONGER THAN STAYING. Consolidation is four LLM
    calls and about a minute on a 27B, and it used to run between leaving and
    the prompt coming back - so the last thing a conversation did was hold you
    there while it wrote itself down. The work is the same; only who waits for
    it changes.

    A thread would not do: the launcher redraws its briefing when this process
    returns, so anything keeping the interpreter alive also keeps the menu
    away. Detached, the conversation ends now and the job outlives it.
    """
    if not turns:
        return True                       # nothing to do counts as handled
    if os.environ.get("PRAGMA_CONSOLIDATE_SYNC", "").strip().lower() in (
            "1", "true", "yes"):
        return False
    try:
        import pragma_jobs as jobs
        job_path = jobs.create(_spool(turns), str(cwd), note)
        jobs.start(job_path)
    except Exception as e:
        print(f"  could not start the consolidation worker: "
              f"{type(e).__name__}: {str(e)[:90]}")
        return False
    print()
    print(f"  {len(turns)} turn(s) handed to the memory - it writes them while")
    print("  you carry on.  /jobs to watch, or just look at the next briefing.")
    return True


def load_episode(episode_id: str) -> dict | None:
    if not episode_id:
        return None
    try:
        import episodes as estore
        p = Path(baseline_config.EPISODES_DIR) / f"{episode_id}.json"
        if not p.exists():                      # swept to dormant already
            p = Path(estore.dormant_dir()) / f"{episode_id}.json"
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def compact_by_episodes(history: list, turns: list[Turn], turn_msgs: list[int],
             done_upto: int, cwd: Path, renderer) -> tuple[list, int]:
    """Trade the older turns of a conversation for the memory of them.

    THE POINT OF THE WHOLE PHASE. A batch run that outgrows its window is
    summarised, and rightly: it is one task, and half a task is not an
    experience. A conversation is the opposite — its older turns are finished
    experiences, and it already owns the faculty that turns those into a
    compact durable form. Summarising them instead would be the memory system
    declining to apply itself to its own context.

    So the turns before the last CHAT_KEEP_TURNS are consolidated into
    episodes NOW, dropped from the message list, and replaced by what those
    episodes say. What stays is: the system prompt, the memory of what came
    before, and the recent turns verbatim.

    Returns (new history, new watermark). On any failure the history is
    returned untouched — a conversation must not lose its context because
    remembering it failed; it will simply be compacted again next turn, or
    fall back to the loop's own compression if it grows past the window.
    """
    keep_n = baseline_config.CHAT_KEEP_TURNS
    cut_at = len(turns) - keep_n
    if cut_at <= done_upto:
        return history, done_upto        # nothing old enough to trade away

    renderer.faculty("COMPACTOR",
                     f"conversation is full — remembering turns "
                     f"{done_upto + 1}-{cut_at} and keeping the last {keep_n}")
    episodes = consolidate(turns[done_upto:cut_at], cwd, renderer,
                            note=f"turns {done_upto + 1}-{cut_at}")
    if not episodes:
        # The segmenter judged none of it worth keeping. The turns still have
        # to go — nothing was memorable, so nothing is lost by dropping them.
        renderer.faculty("COMPACTOR", "nothing worth remembering in those turns")

    # Counted, never indexed: earlier compactions have already shifted every
    # absolute position in `history`, but they only ever touch its head, so
    # the turns to keep are reliably its last N messages.
    tail_n = sum(turn_msgs[cut_at:])
    head = history[:1] if history and history[0].get("role") == "system" else []
    tail = history[-tail_n:] if tail_n else []

    lines = ["[Earlier in this conversation — consolidated into memory when "
             "the context filled up. These are the episodes it produced; the "
             "turns themselves are gone.]"]
    for ep in episodes:
        lines.append(f"- {ep.get('goal', '')}")
        nar = (ep.get("narrative") or "").strip()
        if nar:
            lines.append(f"  {nar[:baseline_config.MEMORY_NARRATIVE_CHARS]}")
    carried = [{"role": "user", "content": "\n".join(lines)}] if episodes else []

    new_history = head + carried + tail
    renderer.faculty("COMPACTOR",
                     f"{len(history)} → {len(new_history)} messages")
    return new_history, cut_at


def recall(text: str, cwd, desk_ids: set[str], desk_rules: set[str],
            reinforced: set[str], renderer, first_turn: bool,
            state: dict | None = None, stop_event=None) -> str:
    """The curator's contribution to one turn, or "".

    WHY ONCE PER TURN AND NOT ONCE PER SESSION. A conversation changes subject.
    Curating only at the start would hand the agent whatever matched the
    opening pleasantry and nothing for the four topics that follow.

    WHY THE DESK ONLY GROWS. Every block stays in the history it was prepended
    to, so a memory fetched at turn three is still in front of the agent at
    turn eleven. Fetching it again would paste it twice and, worse, reinforce
    it twice: salience would then measure how long a conversation ran rather
    than what mattered in it. `desk_ids` is what makes recall idempotent.

    WHEN NO WORD MATCHES the curator is offered the most recent episodes
    instead, on every turn. It used to be on the first only, where the
    question is usually about the past itself and shares no words with it
    ("what do you know about me?") - but "what did we do yesterday?" is asked
    at turn five as well, and there it was offered nothing. See
    curator._episode_candidates.

    Failure is silent by design: a session must not die because recall did.
    """
    try:
        import curator
        # Say so BEFORE the call, as the other faculties do. Recall runs ahead
        # of the turn's first step, so without this the screen shows nothing
        # but the model's spinner - indistinguishable from the agent already
        # working on the answer. On a slow endpoint that is minutes of not
        # knowing which of the two you are waiting for.
        renderer.faculty_running(
            "CURATOR",
            "searching memory for what bears on this…" if not first_turn
            else "opening the conversation — offering the latest memories…")
        import time as _time
        _t0 = _time.monotonic()
        info = curator.curate_knowledge_detailed(
            text, workspace=str(cwd),
            exclude_ids=desk_ids, exclude_rules=desk_rules,
            no_reinforce=reinforced, stop_event=stop_event)
        took = f" · {_time.monotonic() - _t0:.0f}s"
        if state is not None and state.get("search"):
            # For the line under the prompt: whether the embedding server
            # answered this search.
            state["search"] = "words" if info.get("search_error") else "meaning"
        # Set to search by meaning and unable to: the recall went by words,
        # which is a different recall, and nothing on the screen would tell.
        if info.get("search_error") and not _SEARCH_WARNED:
            _SEARCH_WARNED.append(True)
            say = getattr(renderer, "warning", None)
            if say:
                say(f"the memory was searched by words: the embedding server did not answer "
                    f"({info['search_error']})")
        # The server kept its name and changed its vectors: the ones kept for
        # this memory were dropped (embed._ready). Said once, when it happens.
        import embed
        if embed.NOTICE:
            note, embed.NOTICE = embed.NOTICE, ""
            say = getattr(renderer, "warning", None)
            if say:
                say(note)
    except llm_client.LLMInterrupted:
        renderer.faculty("CURATOR", "stopped")
        return ""
    except Exception as e:
        renderer.faculty("CURATOR", f"recall unavailable — {e}")
        return ""

    if not info["block"]:
        # Now that the faculty announces itself, an empty recall cannot just
        # return: an opening line followed by nothing reads as a hang. Saying
        # "looked, found nothing" costs one line and is the difference between
        # a faculty that is idle and a faculty that is stuck.
        empty = not (info.get("pool_ep") or info.get("n_ep")
                     or info.get("pool_ln") or info.get("n_ln"))
        renderer.faculty("CURATOR",
                         ("the memory is still empty" if empty
                          else _pool_line(info) + " → none of them bears on this")
                         + (f" — {info['reason']}" if info.get("reason") and not empty else "")
                         + took)
        return ""
    desk_ids.update(info["episode_ids"])
    desk_rules.update(info["rule_texts"])
    reinforced.update(info["episode_ids"])

    pool = _pool_line(info)
    if info["fallback"]:
        renderer.faculty("CURATOR", f"{pool} → deterministic fallback "
                                    f"(curator unavailable)"
        + (f" — {info['reason']}" if info.get("reason") else ""))
    else:
        note = f"{pool} → recalled {len(info['selected'])}"
        if info["reason"]:
            note += f" — {info['reason']}"
        renderer.faculty("CURATOR", note + took, info["selected"])
    return info["block"]


# ── one conversation ──────────────────────────────────────────────────────────

class Conversation:
    """What has been said with a project since the conversation began, and
    how one more turn of it goes.

    The chat and /serve each hold one. They differ in how a turn is shown, in
    who can stop it and how, and in where the person's words come from; the
    turn itself is this. `guard(stop)` is the context a turn runs in - the
    chat's makes ctrl+C and ctrl+D stop it - and `say` writes a plain line;
    both default to nothing.

    The state was the chat loop's local variables and the attributes of
    /serve's own class, kept in step by hand:

    history          the messages the agent goes on from
    turns            what was said, turn by turn, for the memory
    turn_msgs        how many messages each turn added, for compacting by count
    desk_ids, desk_rules
                     what the curator has put in front of the agent: not
                     fetched again while it is still in the history
    reinforced       what this conversation has counted as recalled; never
                     emptied, so salience does not count overflows
    consolidated_upto
                     the turns already remembered by compacting into episodes
    weighed_at       (prompt tokens, characters) of the history as the server
                     last counted it, for the next turn to start from
    prompt_tokens    what the agent's last request weighed, 0 when unknown
    notes            words for the agent, not the person's, put in front of
                     the next request and kept in the conversation with it -
                     a rule pack turned on midway; emptied when a turn ends
    """

    def __init__(self, cwd, cfg, renderer, memory: bool, *, log_path=None,
                 state: dict | None = None, guard=None, say=None,
                 compact_mode: str | None = None):
        self.cwd = Path(cwd)
        self.cfg = cfg
        self.renderer = renderer
        self.memory = bool(memory)
        self.log_path = Path(log_path) if log_path else self.cwd / ".pragma_session.jsonl"
        self.state = state
        self.guard = guard or (lambda stop: contextlib.nullcontext())
        self.say = say or (lambda text: None)
        self.compact_mode = compact_mode or baseline_config.CHAT_COMPACT_MODE
        self.history: list | None = None
        self.turns: list[Turn] = []
        self.turn_msgs: list[int] = []
        self.desk_ids: set[str] = set()
        self.desk_rules: set[str] = set()
        self.reinforced: set[str] = set()
        self.consolidated_upto = 0
        self.weighed_at: tuple | None = None
        self.prompt_tokens = 0
        self.notes: list[str] = []
        # What the advisor said in the last turn - its plan, its advice - for
        # /plan to show whole: the screen gives each one line.
        self.advice: list[dict] = []
        # The undo net for this conversation: without it `revert` is offered
        # with nothing behind it.
        try:
            import checkpoint
            checkpoint.begin_session(str(self.cwd))
        except Exception:
            pass

    # ── a turn ────────────────────────────────────────────────────────────────

    def turn(self, text: str, context: str = "") -> dict:
        """One turn: the recall, the agent's work, the record of it.

        {"conclusion", "forced", "elapsed"} when it finished; {"stopped": True}
        when it was stopped - by the stop event or by ctrl+C, caught here so
        that what happened so far is still kept for the memory. The history
        does not get a stopped turn: the next message starts from the last one
        that finished.

        `context` is a program's: what the person is looking at, put in front
        of this turn's request and taken out of the history after it, so it is
        not sent again with every later turn.
        """
        cfg, renderer = self.cfg, self.renderer
        stop = cfg.stop_event
        # The Turn - and so the raw log, and so what the segmenter reads on
        # exit - keeps the person's words alone. Only the prompt carries the
        # recalled memory: a knowledge block replayed as if they had typed it
        # would corrupt segmentation and then the episodes.
        turn = Turn(text)
        before = len(self.history or [])
        # A wider budget for what the model said: in a conversation the thought
        # field is where it talks to the person, and the batch cap cut the
        # replies short before the consolidator ever saw them.
        inner = _make_on_step(renderer, 0, turn.transcript,
                              text_limit=baseline_config.CHAT_TRANSCRIPT_CHARS)

        # The advisor is the project's choice, read at every turn: turned on in
        # /settings, it plans the next one.
        settings = project_settings()
        cfg.advisor = advisor.mode_of(settings)
        cfg.advisor_consults = advisor.consults_of(settings)
        self.advice = []

        def on_step(ev: dict) -> None:
            if ev.get("advice"):
                self.advice.append(ev["advice"])
                note = getattr(renderer, "note_advisor", None)
                if note:
                    note(ev["advice"].get("tokens") or 0)
            # The token counts of the call that just ended, before the adapter
            # consumes them: the renderer adds them up for its closing line,
            # and the last prompt says whether the conversation is full.
            if ev.get("type") in ("thought", "final"):
                stats = dict(getattr(llm_client, "LAST_STATS", {}) or {})
                renderer.note_stats(stats)
                if stats.get("total"):
                    self.prompt_tokens = int(stats.get("prompt") or 0)
            inner(ev)

        # What was on the desk before this turn. If the conversation is
        # compacted while the turn runs, those blocks leave the context and may
        # be recalled again; the ones this turn fetched are still in its own
        # request, which is never summarised.
        desk_then = (set(self.desk_ids), set(self.desk_rules))

        def mid_turn(prefix: list):
            try:
                new = compact_summary(
                    prefix, renderer, "", stop,
                    "the context is full - summarising the conversation before this request…")
            except llm_client.LLMInterrupted:
                raise
            except Exception as e:
                # The turn goes on: its own steps are summarised instead.
                renderer.faculty("COMPACTOR", f"not compacted - {str(e)[:100]}")
                return None
            if new is not None:
                self.desk_ids.difference_update(desk_then[0])
                self.desk_rules.difference_update(desk_then[1])
                # The turn's largest request so far was of a list that is gone.
                renderer.context_reset()
                self.prompt_tokens = 0
            return new

        prompt = core = text
        result = None
        t0 = time.monotonic()
        try:
            # The recall is inside what can be stopped: a stop while the
            # curator was choosing used to end more than the reply.
            with self.guard(stop):
                if self.memory:
                    block = recall(text, self.cwd, self.desk_ids, self.desk_rules,
                                   self.reinforced, renderer, first_turn=not self.turns,
                                   state=self.state, stop_event=stop)
                    if block:
                        core = f"{block}\n\n{text}"
                if self.notes:
                    core = "\n\n".join(self.notes + [core])
                prompt = core
                if context:
                    prompt = f"[PROGRAM CONTEXT]\n{context}\n[/PROGRAM CONTEXT]\n\n{core}"
                renderer.turn_begin()
                self.prompt_tokens = 0
                t0 = time.monotonic()
                if stop is not None and stop.is_set():
                    raise KeyboardInterrupt     # asked to stop while recalling
                result = run_agent(
                    cfg, prompt, on_step=on_step, history=self.history,
                    # The critic holds the work to what was typed, not to the
                    # recalled memory standing in front of it.
                    request=text,
                    # When the window fills up while the turn runs, the
                    # conversation before it is what gives way first.
                    compact_prefix=mid_turn if self.compact_mode != "episodes" else None,
                    counted=self.weighed_at,
                )
        except KeyboardInterrupt:
            result = None               # the second press: abandoned at once
        finally:
            # Whatever ended the turn, nothing may be left spinning.
            renderer.idle()

        if result is None:
            append_raw_log(self.log_path, turn)
            self.turns.append(turn)
            return {"stopped": True}

        conclusion = result.get("conclusion", "") or ""
        turn.transcript.append(f"FINAL: {conclusion[:2000]}")
        # Kept BEFORE anything is shown: drawing the reply is the likelier
        # thing to fail, and the turn must not be lost with it.
        append_raw_log(self.log_path, turn)
        self.turns.append(turn)
        self.history = result.get("messages") or self.history
        self.notes = []                 # in the history now, with the request
        # Weighed on the list the server counted - with the program's context,
        # if there was one: taking the context out below is a change the next
        # count measures as growth, negative.
        last = self.prompt_tokens
        self.weighed_at = (last, sum(_msg_chars(m) for m in self.history or [])) if last else None
        if context and self.history:
            # The request is the first user message the turn added; on the
            # first turn the system prompt comes before it.
            # By how it begins: the advisor's plan may follow it in the same
            # message, and stays.
            for i in range(before, len(self.history)):
                m = self.history[i]
                content = m.get("content")
                if (m.get("role") == "user" and isinstance(content, str)
                        and content.startswith(prompt)):
                    self.history[i] = dict(m, content=core + content[len(prompt):])
                    break
        self.turn_msgs.append(max(len(self.history or []) - before, 1))
        return {"conclusion": conclusion, "forced": bool(result.get("forced")),
                "elapsed": time.monotonic() - t0}

    # ── when the context fills up ─────────────────────────────────────────────

    def compact(self, instructions: str = "", said: str = "") -> bool:
        """The conversation traded for one summary (/compact, or full).
        Whether it was: a stop, a failure or nothing to do leave it as it was."""
        stop = threading.Event()
        new = None
        try:
            with self.guard(stop):
                new = compact_summary(self.history, self.renderer, instructions, stop, said)
        except (KeyboardInterrupt, llm_client.LLMInterrupted):
            self.say("  not compacted: the conversation is as it was.")
        except Exception as e:
            self.say(f"  not compacted - {type(e).__name__}: {str(e)[:90]}")
        finally:
            self.renderer.idle()
        if new is None:
            return False
        self.desk_ids.clear()          # those blocks are gone from the context
        self.desk_rules.clear()
        self.renderer.context_reset()
        self.prompt_tokens = 0
        self.say("")
        self.history, self.weighed_at = new, None
        return True

    def compact_by_episodes_now(self) -> bool:
        """The older turns traded for the episodes made of them (the episodes
        mode). Whether anything was: the last CHAT_KEEP_TURNS always stay."""
        was = len(self.history or [])
        self.history, self.consolidated_upto = compact_by_episodes(
            self.history, self.turns, self.turn_msgs, self.consolidated_upto,
            self.cwd, self.renderer)
        if len(self.history or []) == was:
            return False
        self.desk_ids.clear()
        self.desk_rules.clear()
        self.weighed_at = None
        return True

    def compact_if_full(self) -> None:
        """Asked after every turn. By summary - the default - it is also asked
        inside one (see turn); by episodes only here, between turns: a turn
        still running has no finished experience to consolidate."""
        if not self.history or not (self.memory or self.compact_mode != "episodes"):
            return
        # In tokens the server counted, once one request has been answered; in
        # characters until then. The estimate is off by up to 3x on the
        # content a coding session is made of, which is why it is only the
        # fallback.
        if self.prompt_tokens:
            full = self.prompt_tokens > baseline_config.CHAT_COMPACT_TOKENS
        else:
            full = (sum(_msg_chars(m) for m in self.history)
                    > baseline_config.CHAT_COMPACT_CHARS)
        if full and self.compact_mode == "episodes":
            self.history, self.consolidated_upto = compact_by_episodes(
                self.history, self.turns, self.turn_msgs, self.consolidated_upto,
                self.cwd, self.renderer)
            self.desk_ids.clear()      # those blocks are gone from the context
            self.desk_rules.clear()
            self.weighed_at = None
        elif full:
            self.compact("", "the context is nearly full - summarising the conversation so far…")

    # ── when it ends ──────────────────────────────────────────────────────────

    def pending(self) -> list:
        """The turns not yet remembered."""
        return self.turns[self.consolidated_upto:]

    def clear(self, note: str = "before /clear") -> None:
        """A new conversation with the same project. What was said is not
        thrown away: it goes to the memory exactly as it does when the
        conversation closes, and the context starts empty."""
        pending = self.pending()
        if self.memory and pending:
            if not consolidate_later(pending, self.cwd, note=note):
                print("\n  writing what was said to memory - ctrl+C stops it")
                try:
                    consolidate(pending, self.cwd, self.renderer)
                except KeyboardInterrupt:
                    print("\n  stopped. What was written is kept; the "
                          "rest is still in the log.")
        elif pending:
            print(f"  {len(pending)} turn(s) stay in {self.log_path.name} "
                  f"(memory is off: nothing was consolidated)")
        self.turns, self.turn_msgs, self.consolidated_upto = [], [], 0
        self.history, self.weighed_at = None, None
        self.notes = []
        self.desk_ids.clear()
        self.desk_rules.clear()
        self.renderer.context_reset()
        self.prompt_tokens = 0

    def close(self, note: str = "this session") -> None:
        """What was not remembered yet, to the memory: by a worker in another
        process, so that closing takes no longer than closing; here, where
        there is none, with ctrl+C to stop it."""
        if self.memory:
            # Only what compaction has not already remembered. Without the
            # watermark a long conversation would write every early turn
            # twice: once when the context filled up, once again at the end.
            pending = self.pending()
            if not consolidate_later(pending, self.cwd, note=note):
                # CLOSING IS NOT LEAVING, until this is done. Nothing is left
                # half written - an episode is saved whole or not at all - so
                # what a stop loses is the segments not reached yet.
                print("\n  writing what was said to memory - ctrl+C stops it")
                try:
                    consolidate(pending, self.cwd, self.renderer)
                except KeyboardInterrupt:
                    llm_client.stop_everything()
                    print("\n  stopped. What was written is kept; the rest is "
                          "still in the log.")
        elif self.turns:
            print(f"\n  {len(self.turns)} turn(s) recorded in {self.log_path.name} "
                  f"(memory is off: nothing was consolidated)")
