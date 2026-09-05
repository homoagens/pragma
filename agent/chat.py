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
import subprocess
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
from react import AgentConfig, run_agent, _msg_chars   # noqa: E402
from skills import palette as skills_palette   # noqa: E402
from skills import skills_summary_for      # noqa: E402

from agent.batch import (                  # noqa: E402
    _PrettyRenderer,
    _pool_line,
    _make_on_step,
    batch_ask_user,
)
from agent.prompts import build_system_prompt, project_contract  # noqa: E402

_EXIT_WORDS = {"/exit", "/quit", "/bye", "exit", "quit"}

# What a slash reaches without leaving the conversation. The alternative was
# quitting the chat, walking a menu and coming back, which is the cost that
# stopped anyone looking at their own memory mid-thought.
#
# Each entry is (what it runs, one line of help). "memory" values name a
# mem_map flag; "call" values name a python callable resolved at use.
_SLASH = {
    "/chat":     ("chat",    "talk to it - many turns, one conversation"),
    "/help":     ("help",    "this list"),
    "/info":     ("help",    "this list"),
    "/map":      ("map",     "what is in memory now"),
    "/beliefs":  ("beliefs", "what it has concluded"),
    "/diff":     ("diff",    "meanings it has revised"),
    "/oblio":    ("oblio",   "what has faded"),
    "/last":     ("last",    "the newest episode, in full"),
    "/sizes":    ("sizes",   "how wordy the store is"),
    "/configure": ("configure", "point Pragma at an LLM endpoint"),
    "/clear":    ("clear",   "clear the screen, keep the conversation"),
    "/exit":     ("exit",    "close the session and consolidate"),
    # Handed back to the launcher: these are about the window, not the talk.
    "/settings": ("ask:settings", "model, budgets, sampling for this project"),
    "/backups":  ("ask:backups",  "snapshot or restore"),
    "/switch":   ("ask:switch",   "another project"),
    "/new":      ("ask:new",      "start a project"),
    "/delete":   ("ask:delete",   "remove a project"),
}


def _ask_launcher(action: str) -> bool:
    """Leave a note for the launcher. False when there is nobody to read it."""
    path = os.environ.get("PRAGMA_REQUEST")
    if not path:
        return False
    try:
        Path(path).write_text(json.dumps({"action": action}), encoding="utf-8")
        return True
    except Exception:
        return False


class _SlashCompleter:
    """Offers the commands, narrowed by what has been typed after the slash.

    Only on a line that STARTS with a slash: a message that happens to contain
    one is prose, and a menu popping up mid-sentence would be worse than no
    menu at all.
    """

    at_home = False

    def get_completions(self, document, complete_event):
        from prompt_toolkit.completion import Completion
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return
        allowed = _allowed()
        for name, (_action, blurb) in _SLASH.items():
            if name == "/info":                  # a synonym, not a second entry
                continue
            if name not in allowed:
                continue
            if name.startswith(text):
                yield Completion(name, start_position=-len(text),
                                 display=name, display_meta=blurb)


def _set_level(session, at_home: bool) -> None:
    """Tell the completer which set of commands is on offer."""
    global _AT_HOME_NOW
    _AT_HOME_NOW = at_home
    try:
        session.completer.at_home = at_home
    except Exception:
        pass


def _make_session():
    """A prompt with completion, or None to fall back to input().

    Missing library, a console that cannot host it, output being captured: all
    of them mean the same thing here - use the plain prompt and lose nothing
    but the suggestions.
    """
    if not sys.stdout.isatty():
        return None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer
        from prompt_toolkit.history import InMemoryHistory

        # The mixin first: with Completer leading, its abstract
        # get_completions wins the lookup and the class cannot be built.
        class _C(_SlashCompleter, Completer):
            pass
        return PromptSession(completer=_C(), history=InMemoryHistory(),
                             complete_while_typing=True, reserve_space_for_menu=6)
    except Exception:
        return None


def _accent() -> str:
    """The launcher's accent as an ANSI foreground, or nothing.

    PRAGMA_ACCENT is set by whoever started this; matching it here keeps the
    prompt the same colour as the page it appeared under, which is the whole
    point of having chosen a colour.
    """
    raw = (os.environ.get("PRAGMA_ACCENT") or "178;132;255").strip()
    parts = raw.split(";")
    if len(parts) != 3 or not all(p.isdigit() and int(p) < 256 for p in parts):
        raw = "178;132;255"
    if not sys.stdout.isatty():
        return ""
    return "\033[38;2;" + raw + "m"


def _hint() -> str:
    """What Ctrl+D does from here, which is not the same thing at both levels.

    At the briefing it leaves the program; in a conversation it goes back to
    the briefing. Writing "exit" in both places would be wrong in one of them,
    and a hint that lies is worse than no hint.
    """
    return "ctrl+D to exit" if _AT_HOME_NOW else "ctrl+D to go back"


def _ask(session):
    """One line from the operator, with the hint while the line is empty."""
    if session is None:
        return input(_prompt()).strip()
    from prompt_toolkit.formatted_text import ANSI
    try:
        return session.prompt(ANSI(_prompt()),
                              placeholder=ANSI("\033[38;5;242m" + _hint()
                                               + "\033[0m")).strip()
    except TypeError:
        # Older prompt_toolkit has no placeholder. The prompt is the point;
        # the hint is not worth failing over.
        return session.prompt(ANSI(_prompt())).strip()


def _prompt() -> str:
    a = _accent()
    if not a:
        return "you > "
    return a + "you" + "\033[0m" + " " + a + ">" + "\033[0m" + " "


# At the briefing there is no conversation to clear or leave halfway, and
# /chat is the one thing that only makes sense there.
_AT_HOME = {"/chat", "/help", "/info", "/map", "/beliefs", "/diff", "/oblio",
            "/last", "/sizes", "/clear", "/configure", "/settings", "/backups",
            "/switch", "/new", "/delete", "/exit"}
_IN_CHAT = {n for n in _SLASH if n != "/chat"}

# Which level is being typed at. One place, read by the banner, the help
# and the completer, so a command cannot be offered by one and refused by
# another.
_AT_HOME_NOW = True


def _allowed() -> set:
    return _AT_HOME if _AT_HOME_NOW else _IN_CHAT


# What the conversation's page says at the top, kept so that clearing can put
# it back. A cleared screen with nothing on it is not the same page any more.
_CHAT_HEADER: list = []


def _new_page() -> None:
    try:
        os.system("cls" if os.name == "nt" else "clear")
    except Exception:
        pass


def _show_chat_header() -> None:
    print()
    for line in _CHAT_HEADER:
        print(line)
    print()


def _slash_banner(at_home: bool = False) -> None:
    """At home a pointer, inside the list.

    Fifteen commands under a briefing is a wall to read before doing the one
    thing anyone came for. Inside a conversation the list earns its place: it
    is the only thing saying that a slash means something there at all.
    """
    a, r = _accent(), ("\033[0m" if _accent() else "")
    print()
    if at_home:
        print(f"  {a}/chat{r} to talk"
              f"   ·   {a}/help{r} for everything else")
    else:
        names = " ".join(n for n in _SLASH if n != "/info" and n in _allowed())
        print(f"  {a}{names}{r}")
        print("  anything else is a message.")
    print()


def _slash_help() -> None:
    print()
    print("  commands")
    seen = set()
    for name, (action, blurb) in _SLASH.items():
        if name not in _allowed():
            continue
        if action in seen and action == "help":
            continue
        seen.add(action)
        print(f"    {name:<11}{blurb}")
    print()
    print("  anything else is a message to the agent.")
    print()


def _run_slash(cmd: str) -> bool:
    """True when the input was a command and has been dealt with.

    Never raises: a broken command must not end a conversation that has
    unconsolidated turns in it.
    """
    action = (_SLASH.get(cmd) or (None, None))[0]
    if action is None:
        print(f"  no such command: {cmd}   (/help for the list)")
        return True
    if action == "help":
        _slash_help()
        return True
    if action == "clear":
        # Clearing redraws the page rather than emptying the screen. At the
        # briefing the page belongs to the launcher - the logo, the counts,
        # what faded - so the only honest way to redraw it is to ask.
        if _AT_HOME_NOW:
            if _ask_launcher("refresh"):
                return False
            _new_page()
            _slash_banner(at_home=True)
            return True
        _new_page()
        _show_chat_header()
        return True
    if action == "configure":
        # The endpoint question, asked where you are rather than at a shell
        # you have to leave the program to reach. It edits .env, and .env is
        # read once at import - so the change is announced as taking effect
        # next time, which is the truth, instead of appearing to do nothing.
        tool = Path(__file__).resolve().parent.parent / "tools" / "pragma_configure.py"
        if not tool.is_file():
            print(f"  this needs {tool}, which is missing from this copy of Pragma.")
            return True
        print()
        try:
            subprocess.run([sys.executable, str(tool)], check=False)
        except Exception as e:
            print(f"  {type(e).__name__}: {str(e)[:120]}")
            return True
        print()
        print("  this window keeps the endpoint it started with -")
        print("  leave Pragma and come back for the new one.")
        print()
        return True
    if action in ("exit", "chat"):
        return False                      # handled by the caller
    if action.startswith("ask:"):
        want = action.split(":", 1)[1]
        if not _ask_launcher(want):
            print("  that one needs the launcher: start with `pragma`.")
            return True
        # False ends the loop the same way /exit does, so the turns consolidate
        # before the launcher takes over. Leaving without that would drop the
        # conversation on the floor to look at a settings page.
        return False

    # The inspection commands are mem_map's, which is the tool that already
    # knows how to render a store. Called rather than reimplemented: two
    # renderings of the same memory would disagree the first time one changed.
    tool = Path(__file__).resolve().parent.parent / "tools" / "mem_map.py"
    if not tool.is_file():
        print(f"  this needs {tool}, which is missing from this copy of Pragma.")
        return True
    # No store path: mem_map resolves it from PRAGMA_DATA_DIR itself, which is
    # the same source of truth the rest of the process uses. Passing one here
    # meant passing EPISODES_DIR - one level too deep - and it dutifully looked
    # for episodes/episodes and found an empty store.
    args = [sys.executable, str(tool)]
    if action != "map":
        args.append("--" + action)
    try:
        subprocess.run(args, check=False)
    except Exception as e:
        print(f"  {type(e).__name__}: {str(e)[:120]}")
    return True


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


def _consolidate(turns: list[Turn], cwd: Path, renderer,
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
        from skills.episode_consolidate.skill import episode_consolidate_detailed
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
        "CONSOLIDATOR", f"writing {len(kept)} episode(s) from {note}…")
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
            renderer.faculty("CONSOLIDATOR",
                             f"[{i}/{len(kept)}] {res.get('summary', '')}")
            ep = _load_episode(res.get("episode_id", ""))
            if ep:
                written.append(ep)
        except Exception as e:
            renderer.error(None, f"episode {i} failed: {e}")
    return written


def _load_episode(episode_id: str) -> dict | None:
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


def _compact(history: list, turns: list[Turn], turn_msgs: list[int],
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
    keep_n = getattr(baseline_config, "CHAT_KEEP_TURNS", 3)
    cut_at = len(turns) - keep_n
    if cut_at <= done_upto:
        return history, done_upto        # nothing old enough to trade away

    renderer.faculty("COMPACTOR",
                     f"conversation is full — remembering turns "
                     f"{done_upto + 1}-{cut_at} and keeping the last {keep_n}")
    episodes = _consolidate(turns[done_upto:cut_at], cwd, renderer,
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


class _ChatRenderer(_PrettyRenderer):
    """The pretty renderer, minus the thinking out loud.

    This is the half of the fix the prompt cannot do alone. Telling a model
    that a channel is internal is easy to ignore while its output is visibly
    delivered to the reader - and it WAS delivered: the model answered in the
    thought, called a tool, then answered again in the conclusion, so the
    person read the same thing twice, the second time as a receipt.

    With the text no longer printed, the instruction is simply true. The step
    rule and the action line stay, so the conversation still shows what is
    being done to the files - only the model's private note goes quiet.

    `--show-thoughts` brings it back for debugging, where the whole point is
    to see what the model told itself.
    """

    def thought(self, step, text):
        self._rule(step)


def _recall(text: str, cwd, desk_ids: set[str], desk_rules: set[str],
            reinforced: set[str], renderer, first_turn: bool) -> str:
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
        # Say so BEFORE the call, as the other faculties do. Recall runs ahead
        # of the turn's first step, so without this the screen shows nothing
        # but the model's spinner - indistinguishable from the agent already
        # working on the answer. On a slow endpoint that is minutes of not
        # knowing which of the two you are waiting for.
        renderer.faculty_running(
            "CURATOR",
            "searching memory for what bears on this…" if not first_turn
            else "opening the conversation — offering the latest memories…")
        info = curator.curate_knowledge_detailed(
            text, workspace=str(cwd),
            exclude_ids=desk_ids, exclude_rules=desk_rules,
            require_match=not first_turn, no_reinforce=reinforced)
    except Exception as e:
        renderer.faculty("CURATOR", f"recall unavailable — {e}")
        return ""

    if not info["block"]:
        # Now that the faculty announces itself, an empty recall cannot just
        # return: an opening line followed by nothing reads as a hang. Saying
        # "looked, found nothing" costs one line and is the difference between
        # a faculty that is idle and a faculty that is stuck.
        renderer.faculty("CURATOR",
                         _pool_line(info) + " → "
                         "nothing bore on this"
                         + (f" — {info['reason']}" if info.get("reason") else ""))
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
    # None, not 0.0: see agent/batch.py. A literal default here shadowed
    # DEFAULT_TEMPERATURE and made the environment variable inert.
    ap.add_argument("--temperature", type=float, default=None,
                    help="sampling temperature (default: DEFAULT_TEMPERATURE)")
    ap.add_argument("--show-thoughts", action="store_true",
                    help="print the model's private note at each step "
                         "(debugging: it is not part of the conversation)")
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

    # An unreachable endpoint used to end the program here. It should not:
    # most of what a memory is for still works with the model gone - the map,
    # the beliefs, what faded, a backup - and a tunnel that drops for a minute
    # should not throw you out of the room. So it opens offline and says so,
    # and every turn re-checks, so it heals the moment the server answers.
    online, detail = llm_client.ping_models()

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
    # Chat-only addendum. The base prompt was written for one headless task,
    # and two of its rules invert in a conversation - which is not the model
    # misbehaving but the model obeying: told that `conclusion` is where recaps
    # belong, it closes a warm exchange with "done, I updated journal.md".
    # An instruction that is not followed is usually a contradiction nobody
    # declared, so this declares which side wins.
    #
    # Overriding the 200-character thought rule is safe HERE and only here: the
    # live session runs on the native channel, where the text is `content` and
    # the arguments live in `tool_calls`, so a long reply cannot truncate the
    # JSON of an action. On the text protocol it could, which is why the rule
    # exists in the first place.
    chat_policy = """

## Live session - this is a conversation

Where the rules above disagree with this section, this section wins.

**`thought` IS NOT SHOWN TO THE PERSON.** It is your own note about the
immediate next step - one short sentence - and anything else you put there
is simply lost. Everything you want to say goes in `conclusion`, whole.

    Prefer   thought:    "Checking the end of the journal before appending."
             conclusion: <your whole reply to them>

    Over     thought:    <your whole reply to them>
             conclusion: "Done. I updated journal.md."

The second shape is the one to avoid: it delivers the answer where nobody
reads it, and the receipt where the answer belonged. Do not answer in the
thought and then summarise at the end - answer once, at the end.

**The conclusion closes the exchange**, it does not report on it. When what
you were asked for IS the work, say what came of it, not which files it went
through. Nobody wants the receipt for an operation they asked for and just
watched happen.

If the turn needed no tools at all, the conclusion is simply your reply.
"""

    system_prompt = build_system_prompt(
        str(cwd),
        default_model=baseline_config.DEFAULT_MODEL,
        coding_model=coding_model,
        skills_summary=skills_summary_for(skills.keys()),
        protocol=getattr(baseline_config, "LLM_TOOL_PROTOCOL", "text"),
    ) + chat_policy + project_contract(cwd)

    renderer = _PrettyRenderer() if args.show_thoughts else _ChatRenderer()
    served = getattr(baseline_config, "SERVED_MODEL", "") or baseline_config.DEFAULT_MODEL
    max_steps = args.max_steps or baseline_config.MAX_STEPS

    log_path = cwd / ".pragma_session.jsonl"
    print()
    # With the endpoint down there is no served model to name, and an empty
    # slot between two separators reads as a bug rather than a state.
    # Only what the briefing cannot say for itself. The launcher has already
    # drawn the logo, the project, the memory and the date above this; saying
    # "Pragma live session" under it announced a conversation that had not
    # started and made the briefing look like the chat.
    if not online:
        print(f"  backend down - {str(detail).split(chr(8212))[0].strip()[:70]}")
        print("  the memory still answers: /map /beliefs /oblio /last")
        print("  /configure points Pragma at another endpoint")

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
    session = _make_session()
    turns: list[Turn] = []
    # What the curator has already put in front of the agent, for the whole
    # conversation. It is not a cache: the desk IS the history, because the
    # block is prepended to the turn it was fetched for and stays there. The
    # sets are what stops it being fetched a second time.
    desk_ids: set[str] = set()
    desk_rules: set[str] = set()
    # Two sets, deliberately. `desk_ids` is what is IN FRONT of the agent and
    # empties when compaction drops the turns those blocks were attached to.
    # `reinforced` is what this conversation has already counted as recalled
    # and never empties: a memory may legitimately be fetched twice, but
    # reinforcing it twice would make salience record how often the context
    # overflowed instead of what mattered in the conversation.
    reinforced: set[str] = set()
    # Messages each turn added to the history, so compaction can take the tail
    # by count rather than by an index earlier compactions have invalidated.
    turn_msgs: list[int] = []
    consolidated_upto = 0

    # THE BRIEFING IS A PLACE, NOT A SPLASH. Landing straight in the
    # conversation meant every look at the memory, every settings change, was
    # something you did on the way out of a talk you had just started. Here
    # nothing is running: /chat begins one, and leaving one comes back here.
    #
    # /exit means the same at both levels - out of where you are - so it takes
    # two to leave the program, and Ctrl+D is the same key by another name.
    _set_level(session, True)
    _slash_banner(at_home=True)
    while True:
        try:
            text = _ask(session)
        except (EOFError, KeyboardInterrupt):
            print()
            return 0                              # nothing to consolidate yet
        if not text:
            continue
        if text.lower() in _EXIT_WORDS:
            return 0
        if text.startswith("/"):
            cmd = text.split()[0].lower()
            if cmd not in _AT_HOME:
                print(f"  {cmd} needs a conversation - /chat first")
                continue
            if (_SLASH.get(cmd) or ("", ""))[0] == "chat":
                break                             # into the conversation
            if not _run_slash(cmd):
                return 0                          # a page the launcher owns
            continue
        # Prose here would vanish: there is no turn to put it in yet, and
        # swallowing it silently is how a first message gets lost.
        print("  /chat first, then say it.")

    # A conversation gets a page. Printed under the briefing it read as more
    # of the same screen; cleared, it is somewhere you went. The commands are
    # not repeated here - /help still lists them, and the slash still offers
    # them as you type.
    _set_level(session, False)
    _CHAT_HEADER[:] = [
        f"  talking to {served or 'nothing - the backend is down'}"
        f" · memory {'on' if args.memory else 'off'}"
        f" · max {max_steps} steps per turn",
        "  /exit or ctrl+D goes back"
        "   ·   ctrl+C goes back and consolidates",
    ]
    _new_page()
    _show_chat_header()

    try:
        while True:
            try:
                text = _ask(session)
            except EOFError:
                # The same as /exit: out of the conversation, back to the
                # briefing. Two of them leave the program, because the second
                # is given to a briefing that has nothing left to step back to.
                print()
                _ask_launcher("refresh")
                break
            except KeyboardInterrupt:
                print()
                break
            if not text:
                continue
            if text.lower() in _EXIT_WORDS:
                # Back to the briefing, redrawn with whatever this
                # conversation just added to the memory.
                _ask_launcher("refresh")
                break
            # A slash is a command, not a message. Checked before anything
            # else so it never reaches the model, never becomes a Turn, and
            # never lands in an episode as though it had been said.
            if text.startswith("/"):
                if not _run_slash(text.split()[0].lower()):
                    break        # /exit, or a page the launcher owns
                continue

            # Only a real turn needs the model. Asked again rather than
            # remembered: the point of opening offline is that it stops being
            # true without anyone restarting anything - and the slash commands
            # above must keep working while it is.
            if not online:
                online, detail = llm_client.ping_models(timeout=4)
                if not online:
                    print("  backend still down - "
                          + str(detail).split(chr(8212))[0].strip()[:70])
                    print("  the memory commands still work; /help lists them.")
                    continue
                print("  backend is back.")

            # The Turn — and so the raw log, and so what the segmenter reads
            # on exit — keeps the user's words alone. Only the prompt carries
            # the recalled memory: a knowledge block replayed as if the user
            # had typed it would corrupt segmentation and then the episodes.
            turn = Turn(text)
            prompt = text
            if args.memory:
                block = _recall(text, cwd, desk_ids, desk_rules, reinforced,
                                renderer, first_turn=not turns)
                if block:
                    prompt = f"{block}\n\n{text}"

            before = len(history or [])
            result = run_agent(
                cfg, prompt,
                # A wider budget for what the model said: in a conversation the
                # thought field is where it talks to you, and the batch cap cut
                # the replies short before the consolidator ever saw them.
                on_step=_make_on_step(
                    renderer, 0, turn.transcript,
                    text_limit=getattr(baseline_config,
                                       "CHAT_TRANSCRIPT_CHARS", 2000)),
                history=history,
                # Everything already in the history is a finished turn. The
                # loop may compress its own step traffic; the conversation is
                # not its to blur.
                protect_prefix=before,
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
            turn_msgs.append(max(len(history or []) - before, 1))

            renderer.conclusion(result.get("forced", False), 0.0, conclusion)

            # Compaction happens BETWEEN turns, never inside one: a turn that
            # is still running has no finished experience to consolidate, and
            # a ~40s pause mid-answer is the worst possible moment for it.
            if args.memory and history:
                size = sum(_msg_chars(m) for m in history)
                if size > getattr(baseline_config, "CHAT_COMPACT_CHARS", 0):
                    history, consolidated_upto = _compact(
                        history, turns, turn_msgs, consolidated_upto,
                        cwd, renderer)
                    desk_ids.clear()      # those blocks are gone from context
                    desk_rules.clear()
    except KeyboardInterrupt:
        print()

    if args.memory:
        # Only what compaction has not already remembered. Without the
        # watermark a long session would write every early turn twice: once
        # when the context filled up, once again on the way out.
        _consolidate(turns[consolidated_upto:], cwd, renderer)
    elif turns:
        print(f"\n  {len(turns)} turn(s) recorded in {log_path.name} "
              f"(no --memory: nothing was consolidated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
