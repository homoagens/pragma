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
# TWO SCREENS. The launcher's home prompt is where a project is chosen; opening
# one draws its briefing and lands here, in the conversation. There used to be
# a third place between them - a prompt under the briefing where /chat began
# the talk - and it decided nothing: everything it offered works from inside
# the conversation. Leaving goes back to the home prompt, one step, and what
# was said is consolidated on the way.
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
_TOOLS = _ROOT / "tools"
for p in (str(_ROOT), str(_CORE), str(_TOOLS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import config as baseline_config          # noqa: E402
import llm_client                          # noqa: E402
from react import AgentConfig, run_agent, _msg_chars   # noqa: E402
from skills import palette as skills_palette   # noqa: E402
from skills import skills_summary_for      # noqa: E402

from agent.batch import (                  # noqa: E402
    _pool_line,
    _make_on_step,
)
from agent.prompts import build_system_prompt, project_contract  # noqa: E402
from agent import harness as _harness       # noqa: E402

# The renderer of the conversation in progress, for the one caller that is
# not handed it: ask_user, which needs the screen for a question.
_RENDERER = None
# What the toolbar under the prompt shows. Read on every redraw, so it holds
# values, never work: the loop refreshes it between turns.
_STATE: dict = {}

# Not commands: the words people type when they mean ctrl+D. Answered rather
# than obeyed, because obeying them would put a second door next to the one
# every other screen already uses - and rejected as unknown they would look
# like a mistake, when the only thing wrong is the habit.
_LEAVING_WORDS = {"/exit", "/quit", "/bye", "/q"}

# What a slash reaches without leaving the conversation. The alternative was
# quitting the chat, walking a menu and coming back, which is the cost that
# stopped anyone looking at their own memory mid-thought.
#
# TWO FAMILIES, NOT TWENTY COMMANDS. Flat, the list was twenty lines in which
# the thing done daily and the thing done twice a year weighed the same, and
# the help was a wall. Everything about the store is now /memory <view> and
# everything about the project and the window is /project <action>, which makes
# the list someone reads seven lines long and the views discoverable from the
# family that owns them. Every old name still works - see _ALIASES - because
# fingers that learned /map should not have to relearn anything.
#
# Each entry is (what it runs, one line of help).
_COMMANDS = {
    "/memory":    ("memory",    ""),      # the views fill the blurb in
    "/settings":  ("ask:settings", "what this project decides for itself"),
    "/status":    ("status",    "how this project is set up right now"),
    "/jobs":      ("jobs",      "what the memory is writing in the background"),
    "/configure": ("configure", "point Pragma at an LLM endpoint"),
    "/clear":     ("clear",     "clear the screen, keep the conversation"),
    "/help":      ("help",      "this list"),
}

# The views of the store. The name is the flag mem_map already takes, so the
# two never disagree about what "beliefs" means.
_MEMORY_VIEWS = {
    "map":     "what is in memory now",
    "beliefs": "what it has concluded",
    "diff":    "meanings it has revised",
    "oblio":   "what has faded",
    "last":    "the newest episode, in full",
    "sizes":   "how wordy the store is",
}

# Done TO a project rather than inside one, so they live on the screen where
# no project is open. Typed here they say where they went: a habit is worth
# one line of directions, and silently not existing is worth none.
_AT_HOME = {
    "/backups": "snapshot or restore",
    "/switch":  "another project",
    "/new":     "start a project",
    "/delete":  "remove a project",
    "/open":    "open a project",
    "/projects": "the projects screen itself",
}

# Old names, and the odd synonym. They work exactly as they did and are offered
# by nothing: the list stays short, the habits keep working. /chat is one of
# them now: there is no second place to be, so it answers where you already
# are instead of failing.
_ALIASES = {"/info": "/help"}
_ALIASES.update({f"/{view}": f"/memory {view}" for view in _MEMORY_VIEWS})
# /project settings was where these lived; the head is what is matched, so
# the one entry covers both "/project" and "/project settings".
_ALIASES.update({"/project": "/settings", "/config": "/configure"})
# The names for leaving all point at the same answer: ctrl+D.
_ALIASES.update({"/close": "/exit"})


def _blurb(name: str) -> str:
    """The help line for a command; a family lists what it takes."""
    if name == "/memory":
        return " . ".join(_MEMORY_VIEWS)
    return _COMMANDS[name][1]


def _normalise(line: str) -> tuple[str, str]:
    """A typed line as (command, argument), old names expanded to the new ones."""
    head, _, arg = line.strip().partition(" ")
    head = head.lower()
    arg = arg.strip().lower()
    if head in _ALIASES:
        parts = _ALIASES[head].split()
        head = parts[0]
        if len(parts) > 1:
            arg = parts[1]
    return head, arg


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

    def get_completions(self, document, complete_event):
        from prompt_toolkit.completion import Completion
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        allowed = _allowed()
        if " " in text:
            # Inside a family: the views and actions it takes, which is where
            # they are discovered now that they are not top-level commands.
            head, _, typed = text.partition(" ")
            head = head.lower()
            if head in _ALIASES:
                return
            options = dict(_MEMORY_VIEWS) if head == "/memory" else {}
            if head not in allowed or " " in typed.strip():
                return
            for name, blurb in options.items():
                if name.startswith(typed.strip().lower()):
                    yield Completion(name, start_position=-len(typed),
                                     display=name, display_meta=blurb)
            return
        for name in _COMMANDS:
            if name not in allowed:
                continue
            if name.startswith(text):
                yield Completion(name, start_position=-len(text),
                                 display=name, display_meta=_blurb(name))


def _chat_ask_user(topic: str = "", context: str = "", mode: str = "input",
                   prompt: str = "", question: str = "", **_ignored) -> str:
    """ask_user for a live conversation, where the person is right here.

    The batch version was wired in, so a person sitting at the terminal was
    reported as absent: every question got \"no user is available\" and the
    step limit always answered no.

    A confirmation is now asked for real: the loop needs a yes or no before
    it can go on (another round of steps, an overwrite), and the person can
    give one. Anything else ends the turn instead. A free answer typed in the
    middle of the steps would sit buried among them; asked in the reply, the
    question is the last thing on the screen and the answer comes back as the
    next message, with the conversation still in view.
    """
    q = (topic or prompt or question or "").strip()
    if mode == "confirm":
        # The status line is on the screen: it steps aside for the question
        # and comes back with the answer.
        if _RENDERER is not None:
            _RENDERER.pause()
        print()
        print(f"  ? {q}")
        if context:
            print(f"    {context}")
        try:
            answer = input("  y/n > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if _RENDERER is not None:
            _RENDERER.resume()
        return "yes" if answer in ("y", "yes", "s", "si") else "no"
    return ("The person is in this conversation but cannot answer in the "
            "middle of your turn. Stop here: end the turn now with your "
            "question as the reply, saying what you need and why in one or "
            "two sentences. Their answer will arrive as their next message.")


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
        # The toolbar is the part of a harness that does not scroll away:
        # project, model, how full the context is, whether a consolidation
        # is being written. Drawn by prompt_toolkit under the prompt, from
        # _STATE, which the loop keeps current.
        return PromptSession(completer=_C(), history=InMemoryHistory(),
                             complete_while_typing=True, reserve_space_for_menu=6,
                             bottom_toolbar=lambda: _harness.toolbar(_STATE),
                             style=_harness.prompt_style())
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
    """What the empty line offers: say something, or step back out."""
    return "say something, or /help  ·  ctrl+D closes the project"


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
    """The prompt mark, in the accent. The project's name is on the toolbar."""
    glyph = _RENDERER.g["prompt"] if _RENDERER is not None else ">"
    a = _accent()
    if not a:
        return f"{glyph} "
    return a + glyph + "\033[0m" + " "


# ONE LEVEL. There used to be two - a briefing you typed at, and the
# conversation /chat opened - and the first decided nothing: every command it
# offered works from inside the talk, and the only one that did not, /chat,
# existed to leave it. Now the briefing is the page you land on and the prompt
# under it is already the conversation's.
def _allowed() -> set:
    return set(_COMMANDS)


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


def _slash_banner() -> None:
    """One line under the briefing: what to type, and what a slash is for.

    The briefing is right above it and was read on the way in, so this says
    the little the briefing cannot: that talking is the default and that the
    slash commands exist.
    """
    a, r = _accent(), ("\033[0m" if _accent() else "")
    print()
    print(f"  say something to begin"
          f"   ·   {a}/memory{r} to look at the store"
          f"   ·   {a}/help{r} for the commands")
    print()


def _slash_help() -> None:
    """One format, the same one the home prompt and /configure use."""
    a, r = _accent(), ("\033[0m" if _accent() else "")
    print()
    print("  commands")
    for name in _COMMANDS:
        if name in _allowed():
            print(f"    {a}{name:<12}{r}{_blurb(name)}")
    print()
    print("  /memory takes one of the words above; alone it shows the map.")
    print("  Starting, backing up or removing a project is done where none is")
    print("  open: ctrl+D, then /projects.")
    print("  Anything without a slash is a message to the agent.")
    print(f"  {a}ctrl+D{r} closes the project, consolidating what was said.")
    print()


def _show_memory(view: str) -> bool:
    """One view of the store, rendered by mem_map.

    Called rather than reimplemented: two renderings of the same memory would
    disagree the first time one of them changed.
    """
    tool = Path(__file__).resolve().parent.parent / "tools" / "mem_map.py"
    if not tool.is_file():
        print(f"  this needs {tool}, which is missing from this copy of Pragma.")
        return True
    # No store path: mem_map resolves it from PRAGMA_DATA_DIR itself, which is
    # the same source of truth the rest of the process uses. Passing one here
    # meant passing EPISODES_DIR - one level too deep - and it dutifully looked
    # for episodes/episodes and found an empty store.
    args = [sys.executable, str(tool)]
    if view != "map":
        args.append("--" + view)
    try:
        subprocess.run(args, check=False)
    except Exception as e:
        print(f"  {type(e).__name__}: {str(e)[:120]}")
    return True


def _status_lines() -> list[tuple[str, str]]:
    """(label, value) for /status: what is set, where, and what answers.

    The briefing answers "can I start and what changed"; this answers "how is
    this thing configured", which used to be spread over the briefing, the
    settings panel and /configure, with nobody holding all of it.
    """
    out: list[tuple[str, str]] = []
    cfg = baseline_config
    out.append(("project", os.environ.get("PRAGMA_PROJECT", "") or "(none named)"))
    out.append(("workspace", os.environ.get("PRAGMA_WORKSPACE", "") or str(Path.cwd())))
    out.append(("store", str(getattr(cfg, "DATA_DIR", ""))))
    out.append(("", ""))
    try:
        import endpoints
        roles = endpoints.assignments()
        found = endpoints.probe_all(list(roles.values()))
        agent = roles["agent"]
        for role, ep in roles.items():
            p = found.get(ep.base_url, {})
            same = role != "agent" and ep.base_url == agent.base_url
            out.append((role, f"{ep.name} . {ep.base_url} . {endpoints.status_text(p)}"
                        if not same else f"{ep.name} . the same endpoint as the agent"))
    except Exception as e:
        out.append(("endpoint", f"{type(e).__name__}: {str(e)[:90]} . /configure"))
    window = int(getattr(cfg, "CONTEXT_WINDOW", 0) or 0)
    source = getattr(cfg, "CONTEXT_WINDOW_SOURCE", "") or "this project"
    context = f"{window} tokens, from {source}" if window else "unknown"
    # What the server says it has, when that is not where the number came
    # from. Every compaction threshold is derived from the window in force, so
    # the two disagreeing is worth seeing before a request is refused.
    try:
        served = int(cfg._endpoint_context_window() or 0)
    except Exception:
        served = 0
    if served and window and served != window:
        context += f"   (the agent endpoint reports {served})"
    out.append(("context", context))
    # What the window is spent on. Pragma never lets a request approach the
    # window: the history is traded for episodes above one line, the prompt is
    # capped at another, and the answer has to fit in what is left. Without
    # these three numbers "ctx 31%" reads as "a third of the way to a wall",
    # and the wall is somewhere else entirely.
    if window:
        prompt_cap = int(getattr(cfg, "MAX_CHARS", 0) / 4)
        compact_at = int(getattr(cfg, "CHAT_COMPACT_CHARS", 0) / 4)
        answer = int(getattr(cfg, "MAX_TOKENS", 0))
        compact_tokens = int(getattr(cfg, "CHAT_COMPACT_TOKENS", 0))
        if compact_tokens:
            out.append(("", f"the conversation is consolidated into memory above "
                            f"{compact_tokens} tokens ({compact_tokens * 100 // window}%), "
                            f"counted by the server"))
        elif compact_at:
            out.append(("", f"the conversation is consolidated into memory above "
                            f"{compact_at} tokens ({compact_at * 100 // window}%), estimated"))
        if prompt_cap:
            out.append(("", f"one step of a turn is capped at {prompt_cap} "
                            f"({prompt_cap * 100 // window}%), estimated, "
                            f"plus {answer} for the answer"))

    # How the agent's actions are carried. It is not a thing a screen offers
    # to change, but it is the first thing to look at when a file comes back
    # mangled, so it is a thing a screen has to show.
    protocol = getattr(cfg, "LLM_TOOL_PROTOCOL", "native")
    if protocol == "native":
        line = "native . the skills go as tools and the server constrains the arguments"
        try:
            import endpoints
            import llm_client
            if endpoints.state(llm_client.current_endpoint().base_url).tools_unsupported:
                line = ("native, but this endpoint refused tools . running on text, "
                        "where the model escapes its own arguments")
        except Exception:
            pass
    else:
        line = f"{protocol} . the model writes its own JSON and escapes it itself"
    out.append(("actions", line))
    out.append(("", ""))
    out.append(("steps", f"{_STATE.get('max_steps') or getattr(cfg, 'MAX_STEPS', 0)} per turn"))
    think = getattr(cfg, "MEMORY_NO_THINK", "")
    # The value as well as its meaning: the sentence is what it does, the word
    # in brackets is what to type to change it. Both are asked for on every
    # call, so they hold whatever the server's own default is.
    try:
        reasons = cfg.agent_thinking()
    except Exception:
        reasons = getattr(cfg, "AGENT_THINK", False)
    out.append(("agent", "reasons before each step  (a thinking endpoint)"
                if reasons else "acts without reasoning  (an instruct endpoint)"))
    out.append(("memory", {
        "": "every memory call reasons before it answers  (MemoryNoThink on)",
        "select": "recall and segmenting answer at once, writing memory reasons  (select)",
        "write": "writing memory answers at once, the rest reasons  (write)",
        "all": "no memory call reasons  (all)",
    }.get(think, think)))
    out.append(("", "when it reasons: " + ("temperature 0  (MemorySampling greedy)"
                                         if getattr(cfg, "MEMORY_SAMPLING", "preset") == "greedy"
                                         else f"thinking preset, seed {getattr(cfg, 'MEMORY_SEED', 42)}"
                                              "  (MemorySampling preset)")))
    # What this project's own calls carry. A profile answers for all of them at
    # once and says which row of the table it is, because "temperature 0.6" on
    # its own is a number and "thinking-coding" is a reason.
    profile, knobs = ("", {})
    try:
        profile, knobs = cfg.agent_profile()
    except Exception:
        pass
    try:
        temp = cfg.agent_temperature()
    except Exception:
        temp = getattr(cfg, "DEFAULT_TEMPERATURE", None)
    if profile:
        sent = " . ".join(f"{k} {v:g}" for k, v in sorted(knobs.items()) if k != "temperature")
        out.append(("sampling", f"{profile}"))
        out.append(("", (f"temperature {temp:g}" if temp is not None else "temperature: the endpoint")
                    + (f" . {sent}" if sent else "")))
    else:
        extra = [f"{name} {value}" for name, value in
                 (("top_k", getattr(cfg, "TOP_K", None)), ("top_p", getattr(cfg, "TOP_P", None)),
                  ("min_p", getattr(cfg, "MIN_P", None))) if value is not None]
        out.append(("sampling", "the endpoint decides" if temp is None and not extra
                    else " . ".join([f"temperature {temp}" if temp is not None
                                     else "temperature: the endpoint"] + extra)))

    # The store as it stands, from the same summary the briefing is built from.
    # It reads the endpoint too, so a server that is down or a tunnel that is
    # flapping makes it slow or makes it fail - and a page that then printed
    # nothing about the memory looked like a Pragma with no memory at all.
    # Whatever happens, these two lines say something.
    out.append(("", ""))
    tool = Path(__file__).resolve().parent.parent / "tools" / "pragma_brief.py"
    why, brief = "", {}
    try:
        done = subprocess.run([sys.executable, str(tool), str(cfg.EPISODES_DIR)],
                              capture_output=True, text=True, timeout=60)
        brief = json.loads(done.stdout or "{}")
        if not brief.get("ok"):
            why = str(brief.get("error") or (done.stderr or "").strip()[-120:] or "unreadable")
    except subprocess.TimeoutExpired:
        why = "took longer than a minute - the endpoint it also reads may be down"
    except Exception as e:
        why = f"{type(e).__name__}: {str(e)[:100]}"
    if why:
        out.append(("episodes", f"not read - {why}"))
        out.append(("", f"the store itself is at {cfg.EPISODES_DIR}"))
        return out
    out.append(("episodes", f"{brief['episodes_active']} active, "
                            f"{brief['episodes_dormant']} dormant, "
                            f"{brief['beliefs']} beliefs"))
    away, tau = brief.get("away_days"), brief.get("tau")
    half = getattr(cfg, "EPISODE_DECAY_HALF_LIFE_DAYS", 0)
    if away is not None:
        out.append(("away", f"{away} day(s)" + (f", tau {tau}" if tau is not None else "")
                    + f", half-life {half:g} days"))
    return out


def _show_status() -> bool:
    a, r = _accent(), ("\033[0m" if _accent() else "")
    grey = "\033[38;5;242m" if a else ""
    print()
    print(f"  {a}status{r}")
    print()
    for label, value in _status_lines():
        if not label and not value:
            print()
            continue
        print(f"    {grey}{label:<11}{r}{value}")
    print()
    print(f"  {grey}/configure changes the endpoints . /settings the rest{r}")
    print()
    return True


def _run_slash(line: str) -> bool:
    """True when the input was a command and has been dealt with.

    Never raises: a broken command must not end a conversation that has
    unconsolidated turns in it.
    """
    cmd, arg = _normalise(line)
    if cmd == "/chat":
        # It used to open the conversation from the briefing. There is one
        # level now, so it answers where you already are.
        print("  you are already in the conversation - just say it.")
        return True
    if cmd in _LEAVING_WORDS:
        print("  ctrl+D closes the project, and what was said is consolidated")
        print("  on the way out. Another ctrl+D at the projects leaves Pragma.")
        return True
    if cmd in _AT_HOME:
        print(f"  {cmd} - {_AT_HOME[cmd]} - lives on the projects screen now:")
        print("  ctrl+D closes this one, and /projects is there.")
        return True
    if cmd not in _COMMANDS:
        print(f"  no such command: {cmd}   (/help for the list)")
        return True
    action = _COMMANDS[cmd][0]
    if action == "memory":
        # Bare /memory is the map: the view anyone means when they do not say.
        view = arg or "map"
        if view not in _MEMORY_VIEWS:
            print(f"  /memory takes one of: {', '.join(_MEMORY_VIEWS)}")
            return True
        return _show_memory(view)
    if action == "status":
        return _show_status()
    if action == "help":
        _slash_help()
        return True
    if action == "clear":
        # The screen, not the conversation: the briefing above scrolls away
        # with everything else and the header takes its place, because asking
        # the launcher to draw it again would mean starting a second process
        # and losing the turns this one is holding.
        _new_page()
        _show_chat_header()
        return True
    if action == "jobs":
        _show_jobs()
        return True
    if action == "configure":
        # The endpoint question, asked where you are rather than at a shell
        # you have to leave the program to reach. What it changed decides what
        # is true afterwards: the catalogue is re-read on every call, so new
        # roles apply here from the next turn; .env is read once at import, so
        # that change is announced as taking effect next time.
        tool = Path(__file__).resolve().parent.parent / "tools" / "pragma_configure.py"
        if not tool.is_file():
            print(f"  this needs {tool}, which is missing from this copy of Pragma.")
            return True
        print()
        try:
            done = subprocess.run([sys.executable, str(tool)], check=False)
        except Exception as e:
            print(f"  {type(e).__name__}: {str(e)[:120]}")
            return True
        print()
        if done.returncode == 3:              # nothing changed
            return True
        if done.returncode == 0:              # the catalogue: live
            print("  endpoints and roles apply from the next turn.")
            print()
            return True
        print("  this window keeps the .env endpoint it started with -")
        print("  leave Pragma and come back for the new one.")
        print()
        return True
    if action.startswith("ask:"):
        want = action.split(":", 1)[1]
        if not _ask_launcher(want):
            print("  that one needs the launcher: start with `pragma`.")
            return True
        # False ends the loop the same way ctrl+D does, so the turns
        # consolidate before the launcher takes over. Leaving without that
        # would drop the conversation on the floor to look at a settings page.
        return False

    print(f"  {cmd} is not wired up in this copy of Pragma.")
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


def _spool(turns: list[Turn]) -> list[dict]:
    """The turns as plain data, for a worker in another process."""
    return [{"text": t.text,
             "transcript": list(t.transcript),
             "started": t.started.strftime("%Y-%m-%dT%H:%M:%SZ")}
            for t in turns]


def _consolidate_later(turns: list[Turn], cwd: Path,
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
        worker = _ROOT / "tools" / "pragma_consolidate.py"
        exe = sys.executable
        kwargs: dict = {}
        if os.name == "nt":
            # NO WINDOW. The first version used DETACHED_PROCESS, which detaches
            # the console but lets Windows give a console application one of its
            # own - so a black window appeared for the length of the
            # consolidation, which is a strange thing for "it happens quietly in
            # the background" to look like.
            #
            # Two belts. pythonw.exe is the GUI-subsystem interpreter and never
            # allocates a console at all; CREATE_NO_WINDOW says the same thing
            # to Windows for the case where it is missing. The child outlives
            # this process either way - that was never what DETACHED_PROCESS
            # was for - and its own process group keeps a Ctrl+C aimed at the
            # shell from reaching it halfway through writing an episode.
            pyw = Path(exe).with_name("pythonw.exe")
            if pyw.is_file():
                exe = str(pyw)
            kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                       | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(
            [exe, str(worker), str(job_path)],
            cwd=str(_ROOT), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, **kwargs)
    except Exception as e:
        print(f"  could not start the consolidation worker: "
              f"{type(e).__name__}: {str(e)[:90]}")
        return False
    print()
    print(f"  {len(turns)} turn(s) handed to the memory - it writes them while")
    print("  you carry on.  /jobs to watch, or just look at the next briefing.")
    return True


def _writing_now() -> str:
    """The note of the consolidation in flight for this store, or ""."""
    try:
        import pragma_jobs as jobs
        live = jobs.running()
    except Exception:
        return ""
    return (live.get("note") or "a session") if live else ""


def _show_jobs() -> None:
    """What the memory has been doing on its own, newest first.

    A job still running is FOLLOWED rather than listed: the reason to type
    /jobs while something is working is to watch it work.
    """
    try:
        import pragma_jobs as jobs
        items = jobs.listing(limit=6)
    except Exception as e:
        print(f"  {type(e).__name__}: {str(e)[:120]}")
        return
    print()
    if not items:
        print("  nothing in the background - the memory is up to date.")
        print()
        return

    live = next((j for j in items if j.get("status") in ("pending", "running")),
                None)
    # Everything else in the list is a failure: `listing` drops finished jobs,
    # because a record of consolidations that worked is a worse copy of the
    # episodes they produced. What is left is what still wants attention.
    if live:
        print(f"  {live.get('note', 'a session')}   "
              "ctrl+D to leave it to itself")
        print()
        try:
            jobs.watch(Path(live["_path"]), live)
        except KeyboardInterrupt:
            print()
            print("  still working - it carries on without you.")
        print()
        return

    print("  these did not finish. The turns are still in them, so they can be")
    print("  run again:  venv\\Scripts\\python.exe tools\\pragma_consolidate.py <file>")
    print()
    for job in items:
        state = job.get("status", "?")
        when = (job.get("finished") or job.get("started")
                or job.get("created") or "")
        print(f"  {state:<10}{when}   {job.get('note', '')}")
        if job.get("error"):
            print(f"    {job['error'][:100]}")
        for line in (job.get("log") or [])[-4:]:
            print(f"    {line[:100]}")
        print(f"    {job.get('_path', '')}")
        print()


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


# The conversation is drawn by agent/harness.py: one status line for every
# phase, tools on one line with their output folded, the answer streamed
# paragraph by paragraph, one closing line per turn. The batch renderer with
# the thoughts switched off, which used to be here, was the same information
# as a wall.


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
        import time as _time
        _t0 = _time.monotonic()
        info = curator.curate_knowledge_detailed(
            text, workspace=str(cwd),
            exclude_ids=desk_ids, exclude_rules=desk_rules,
            require_match=not first_turn, no_reinforce=reinforced)
        took = f" · {_time.monotonic() - _t0:.0f}s"
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
                         + (f" — {info['reason']}" if info.get("reason") else "")
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
    skills["ask_user"] = _chat_ask_user
    # One channel, always curated — the same rule as `agent.batch`. The raw
    # recall skills would be a second, uncurated way in: they reinforce and
    # revive on keyword overlap alone, with no judgment between the prefilter
    # and the write, so an agent free to call them turns salience into a count
    # of how often a word recurred. The curator reinforces only what it chose.
    # palette() withholds them: see _NOT_AGENT_TOOLS.
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

**To ask the person something, end the turn.** Put the question in your
reply and stop; the answer arrives as their next message. Calling
`ask_user` tells you the same, except for a yes-or-no confirmation, which
it asks them directly.

If the turn needed no tools at all, the conclusion is simply your reply.
"""

    system_prompt = build_system_prompt(
        str(cwd),
        default_model=baseline_config.DEFAULT_MODEL,
        skills_summary=skills_summary_for(skills.keys()),
        protocol=getattr(baseline_config, "LLM_TOOL_PROTOCOL", "native"),
    ) + chat_policy + project_contract(cwd)

    global _RENDERER
    renderer = _harness.Harness(
        verbose=args.show_thoughts,
        context_window=getattr(baseline_config, "CONTEXT_WINDOW", 0),
        envelope=getattr(baseline_config, "LLM_TOOL_PROTOCOL", "native") != "native")
    _RENDERER = renderer
    # Every model call - the curator's, the segmenter's, the agent's - reports
    # its wait to the same status line instead of drawing a spinner of its own.
    llm_client.STATUS_HOOK = renderer
    served = getattr(baseline_config, "SERVED_MODEL", "") or baseline_config.DEFAULT_MODEL
    max_steps = args.max_steps or baseline_config.MAX_STEPS
    _STATE.update(project=os.environ.get("PRAGMA_PROJECT") or cwd.name,
                  model=served if online else "backend down",
                  # The budget in force, which is not config's: a project's
                  # MaxSteps arrives as --max-steps, because it is an argument
                  # of this process and not a setting of the machine. /status
                  # read config and so reported the default however the
                  # project was set.
                  max_steps=max_steps,
                  memory=bool(args.memory), turns=0, ctx=None, writing="")

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
        print("  the memory still answers: /memory, /status, /jobs")
        print("  /configure points Pragma at another endpoint")

    cfg = AgentConfig(
        name="Pragma",
        system_prompt=system_prompt,
        skills=skills,
        final_keys=("conclusion",),
        temperature=args.temperature,
        max_steps=max_steps,
        # The reply as it is written, and the reasoning as it happens: the
        # harness shows the first and scrolls the second through its status.
        on_token=renderer.on_token,
        on_reasoning=renderer.on_reasoning,
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

    # TWO SCREENS, NOT THREE. The launcher has just drawn the briefing - the
    # logo, the project, what the memory holds, what changed while you were
    # away - and the prompt under it is the conversation's. The screen is NOT
    # cleared here: clearing it threw away the page that had just been drawn
    # and replaced it with two lines saying less.
    #
    # The undo net for this conversation. Batch opens one per run; the
    # conversation never did, so `revert` was offered with nothing behind it
    # and answered that no file had changed, whatever had.
    try:
        import checkpoint
        checkpoint.begin_session(str(cwd))
    except Exception:
        pass
    # What /clear puts back, since the briefing above cannot be redrawn from
    # here without starting a second process.
    _CHAT_HEADER[:] = [
        f"  {_STATE['project']} · talking to {served or 'nothing - the backend is down'}"
        f" · memory {'on' if args.memory else 'off'}"
        f" · max {max_steps} steps per turn",
        "  ctrl+D closes the project and consolidates what was said"
        "   ·   ctrl+C the same",
    ]
    _slash_banner()

    try:
        while True:
            _STATE["turns"] = len(turns)
            _STATE["ctx"] = renderer.ctx_pct()
            _STATE["writing"] = _writing_now()
            try:
                text = _ask(session)
            except EOFError:
                # One level up, which is now the home prompt: the project
                # closes and another can be opened. What was said is
                # consolidated on the way out, below.
                print()
                _ask_launcher("close")
                break
            except KeyboardInterrupt:
                print()
                _ask_launcher("close")
                break
            if not text:
                continue
            # A slash is a command, not a message. Checked before anything
            # else so it never reaches the model, never becomes a Turn, and
            # never lands in an episode as though it had been said.
            if text.startswith("/"):
                if not _run_slash(text):
                    break        # a page the launcher owns
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
            # A wider budget for what the model said: in a conversation the
            # thought field is where it talks to you, and the batch cap cut
            # the replies short before the consolidator ever saw them.
            inner = _make_on_step(
                renderer, 0, turn.transcript,
                text_limit=getattr(baseline_config, "CHAT_TRANSCRIPT_CHARS", 2000))

            def on_step(ev: dict, _inner=inner) -> None:
                # The token counts of the call that just ended, before the
                # adapter consumes them: the harness adds them up for the
                # closing line instead of printing one per step.
                if ev.get("type") in ("thought", "final"):
                    renderer.note_stats(dict(getattr(llm_client, "LAST_STATS", {}) or {}))
                _inner(ev)

            renderer.turn_begin()
            import time as _time
            _t_turn = _time.monotonic()
            try:
                result = run_agent(
                    cfg, prompt, on_step=on_step, history=history,
                    # Everything already in the history is a finished turn.
                    # The loop may compress its own step traffic; the
                    # conversation is not its to blur.
                    protect_prefix=before,
                )
            finally:
                # Whatever ended the turn, nothing may be left spinning.
                renderer.idle()
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

            renderer.conclusion(result.get("forced", False),
                                _time.monotonic() - _t_turn, conclusion)

            # Compaction happens BETWEEN turns, never inside one: a turn that
            # is still running has no finished experience to consolidate, and
            # a ~40s pause mid-answer is the worst possible moment for it.
            if args.memory and history:
                # Is the conversation full? In tokens the server counted, once
                # one request has been answered; in characters until then. The
                # estimate is off by up to 3x on the content a coding session
                # is made of, which is why it is only the fallback.
                weighed = renderer.last_prompt_tokens()
                if weighed:
                    full = weighed > getattr(baseline_config, "CHAT_COMPACT_TOKENS", 0)
                else:
                    full = (sum(_msg_chars(m) for m in history)
                            > getattr(baseline_config, "CHAT_COMPACT_CHARS", 0))
                if full:
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
        pending = turns[consolidated_upto:]
        if not _consolidate_later(pending, cwd):
            _consolidate(pending, cwd, renderer)
    elif turns:
        print(f"\n  {len(turns)} turn(s) recorded in {log_path.name} "
              f"(no --memory: nothing was consolidated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
