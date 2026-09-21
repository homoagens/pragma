#!/usr/bin/env python3
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

r"""The launcher, in Python: the same two screens, on Linux and macOS too.

    python -m tools.pragma_launcher            (or the `pragma` script)

WHY IT EXISTS. The launcher was PowerShell - a Windows program for a Windows
desktop - while everything it launches is Python that already runs anywhere:
the skills, the memory, the harness, the endpoint catalogue. Running Pragma on
the machine that holds the model meant either a Windows box or no launcher at
all, which is to say no projects, no briefing, no pages.

WHAT IT IS. The same two screens the PowerShell launcher draws, built out of
the pieces both share, so there is one implementation of each thing and not
two to keep in step:

    the home prompt      tools/pragma_home.py  (commands, endpoints, plugins)
    the endpoint pages   tools/pragma_configure.py
    the briefing         tools/pragma_brief.py, drawn here
    the background work  tools/pragma_jobs.py
    the conversation     python -m agent.chat, with the project's environment

What is only here is what PowerShell used to own: the registry of projects,
opening one (its settings become the environment), the pages for choices and
backups, and the loop between the two screens.

THE REGISTRY IS THE SAME FILE. ~/.pragma/registry.json, with the same keys, so
a store written by the Windows launcher opens here and the other way round.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "core"), str(ROOT / "tools")]

import pragma_home as home                     # noqa: E402  the home prompt, shared

REGISTRY = Path.home() / ".pragma" / "registry.json"
PROJECTS = Path.home() / ".pragma" / "projects"
ESC = "\033"
GREY, RESET = ESC + "[38;5;242m", ESC + "[0m"

# A project's settings, and the environment variable each one becomes. The
# same table pragma-session.ps1 applies on Windows: one list, two launchers,
# and a setting that means one thing on one system and another elsewhere is
# not a thing that can happen quietly.
ENV_OF = {
    "Endpoint": "LLM_BASE_URL", "Protocol": "LLM_TOOL_PROTOCOL",
    "ContextWindow": "CONTEXT_WINDOW", "MaxTokens": "MAX_TOKENS",
    "SkillMaxTokens": "SKILL_MAX_TOKENS", "MemoryMaxTokens": "MEMORY_MAX_TOKENS",
    "MemoryNoThink": "MEMORY_NO_THINK", "AgentThink": "AGENT_THINK",
    "MemorySampling": "MEMORY_SAMPLING", "Timeout": "LLM_TIMEOUT",
    "CuratorEpisodes": "CURATOR_CANDIDATES_EPISODES",
    "CuratorRecent": "CURATOR_CANDIDATES_RECENT",
    "CuratorLearnings": "CURATOR_CANDIDATES_LEARNINGS",
    "CuratorFragments": "CURATOR_MAX_FRAGMENTS",
    "Temperature": "DEFAULT_TEMPERATURE", "TopK": "TOP_K", "TopP": "TOP_P", "MinP": "MIN_P",
}
NEW_PROJECT_SETTINGS = {"Temperature": "server", "MemoryNoThink": "select",
                        "AgentThink": "off", "MemorySampling": "preset"}

# The step budget a project runs at when it has never said. It is not a setting
# of the machine but an argument of the conversation, so config's own default
# (15, for a single batch task) never applies here: a conversation gets the
# room a conversation needs. The same number pragma-session.ps1 falls back to,
# because a project opened on one system and on the other must behave the same.
DEFAULT_STEPS = "50"


# ── the registry ──────────────────────────────────────────────────────────────

def read_registry() -> list[dict]:
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    return [e for e in data if isinstance(e, dict) and e.get("name")]


def write_registry(entries: list[dict]) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, REGISTRY)


def by_name(name: str) -> dict | None:
    return next((e for e in read_registry() if e["name"].lower() == (name or "").lower()), None)


def save_setting(name: str, key: str, value: str) -> None:
    """One setting of one project. An empty value REMOVES it: absent means the
    repository default, which is what someone clearing a field asked for."""
    entries = read_registry()
    for e in entries:
        if e["name"] != name:
            continue
        settings = dict(e.get("settings") or {})
        if value == "":
            settings.pop(key, None)
        else:
            settings[key] = value
        e["settings"] = settings
    write_registry(entries)


# ── the screen ────────────────────────────────────────────────────────────────

def accent() -> str:
    return home.accent()


def clear() -> None:
    """Home, wipe, and the scrollback with it - with the escape the terminal
    itself understands, not by running `clear`, which needs a TERM the shell
    may not have (over ssh without a pty it prints a complaint instead)."""
    if sys.stdout.isatty():
        print("\033[H\033[2J\033[3J", end="", flush=True)


def say(text: str = "", style: str = "") -> None:
    a = accent()
    if not a or not style:
        print(text)
        return
    colour = {"accent": a, "dim": GREY, "good": "\033[32m", "warn": "\033[33m",
              "bad": "\033[31m"}.get(style, "")
    print(f"{colour}{text}{RESET}" if colour else text)


# The mark from interface-web/logo.png beside the word, exactly as
# Show-Logo draws it in tools/Pragma.psm1 - one picture, two launchers.
# F is a full cell, T an upper half, B a lower half: letters, so this file
# stays readable, and so a terminal that cannot draw blocks needs one map
# rather than a second copy of the art.
LOGO = (
    " BFFFFFFFFFBB",
    " TTTTTTTTTTFFF",
    "       BB   FFF",
    "    B  TT   FFF",
    "  BFFBBBBBBFFF   _ _ __ _ __ _ _ __  __ _",
    r" FFFFFFFFFFTT   | '_/ _` / _` | '  \/ _` |",
    r" FFFT           |_| \__,_\__, |_|_|_\__,_|",
    " FT                       |___/",
)
BLOCKS = {"F": "█", "T": "▀", "B": "▄"}


# What the page needs under the mark before the prompt has somewhere to sit:
# the project count, the commands, the endpoint, whatever the memory is
# writing, and the six lines prompt_toolkit keeps free for its completion
# menu. Below this the terminal scrolls, and what goes off the top is the
# mark - which is how it comes to be half drawn.
ROOM_FOR_THE_MARK = 28


def logo(compact: bool | None = None) -> None:
    """The mark, or the word alone on a terminal too short to hold it.

    The PowerShell launcher has had the compact form since the beginning, for
    exactly this: eight rows of block characters are worth the space on a
    window that has it, and are the first thing to lose on one that does not.
    """
    if compact is None:
        try:
            compact = shutil.get_terminal_size(fallback=(80, 40)).lines < ROOM_FOR_THE_MARK
        except Exception:
            compact = False
    a = accent()
    if compact:
        print()
        print(f"  {a}Pragma{RESET if a else ''}")
        return
    r = RESET if a else ""
    glyph = BLOCKS
    try:                                   # a console that cannot encode them
        "".join(BLOCKS.values()).encode(sys.stdout.encoding or "ascii")
    except Exception:
        glyph = {"F": "#", "T": "#", "B": "#"}
    print()
    for row in LOGO:
        print(f"  {a}" + "".join(glyph.get(c, c) for c in row) + r)



def ask(question: str, default: str = "", hint: str = "") -> str | None:
    """One answer, or None for ctrl+D - which goes back, everywhere."""
    shown = f" [{default}]" if default else (f"  {hint}" if hint else "")
    try:
        answer = input(f"  {question}{shown}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return answer or default


def read_key() -> str:
    """One keypress, as a word: up, down, enter, back - or the character.

    Raw mode for one key and straight back out: the alternative is a line
    editor, and a menu that wants Enter after every arrow is not a menu.
    Windows has msvcrt for the same thing, so this launcher behaves the same
    there if it is ever the one running.
    """
    if os.name == "nt":                     # the PowerShell launcher usually runs there
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):          # an arrow arrives as two
            return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "")
        return {"\r": "enter", "\n": "enter",
                "\x04": "back", "\x1b": "back"}.get(ch, ch.lower())
    import select as _select
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1)
        if ch == ESC.encode():
            # An escape sequence, or the Esc key alone: what tells them apart
            # is whether anything follows it straight away.
            more = b""
            if _select.select([fd], [], [], 0.05)[0]:
                more = os.read(fd, 2)
            return {b"[A": "up", b"[B": "down"}.get(more, "back")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch == b"\x04":                       # ctrl+D, as everywhere else in Pragma
        return "back"
    if ch == b"\x03":
        raise KeyboardInterrupt
    return ch.decode("utf-8", "replace").lower()


def menu(options: list[str], notes: list[str] | None = None, start: int = 0,
         hint: str = "enter select . ctrl+D back") -> int | None:
    """The list, walked with the arrows, as the Windows launcher walks it.

    Drawn once and then redrawn over itself from where the drawing ended -
    the same trick Show-Menu uses, for the same reason.

    A number still picks a row, and so does a row's first letter: in a
    terminal that swallows the arrows, the page still works.
    """
    sel = max(0, min(start, len(options) - 1))
    a, r = accent(), (RESET if accent() else "")
    drawn = 0
    while True:
        if drawn:
            print(f"{ESC}[{drawn}A", end="")
        for i, option in enumerate(options):
            note = f"   {GREY}{notes[i]}{RESET}" if notes and notes[i] and a else ""
            body = f"  {'>' if i == sel else ' '} {option}"
            print(f"{ESC}[2K" + (f"{a}{body}{r}" if i == sel else body) + note)
        print(f"{ESC}[2K")
        print(f"{ESC}[2K  {GREY if a else ''}{hint}{r}")
        drawn = len(options) + 2
        try:
            key = read_key()
        except Exception:                   # a terminal that cannot go raw has
            return None                     # no menu to offer
        if key == "up":
            sel = (sel - 1) % len(options)
        elif key == "down":
            sel = (sel + 1) % len(options)
        elif key == "enter":
            return sel
        elif key in ("back", "q"):
            return None
        elif key.isdigit() and 1 <= int(key) <= len(options):
            return int(key) - 1
        else:
            for i, option in enumerate(options):
                if option[:1].lower() == key:
                    return i


def pick(title: str, options: list[str], notes: list[str] | None = None,
         start: int = 0) -> int | None:
    """A list to choose from: walked with the arrows where the terminal allows
    it, numbered where it does not - a pipe, a log, a test."""
    if not options:
        return None
    print()
    if title:
        say(f"  {title}", "accent")
        print()
    if sys.stdin.isatty() and sys.stdout.isatty():
        return menu(options, notes, start)
    for i, option in enumerate(options, 1):
        note = f"   {GREY}{notes[i - 1]}{RESET}" if notes and notes[i - 1] and accent() else ""
        print(f"    {i}. {option}{note}")
    while True:
        answer = ask("choice", hint="a number, or ctrl+D to go back")
        if answer is None:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        say("    not one of them", "warn")


# ── opening a project ─────────────────────────────────────────────────────────

def environment(entry: dict) -> dict:
    """The environment a project runs in: its own settings, nothing inherited.

    Cleared, not left over: a value from the project opened before this one in
    the same window would be invisible and wrong.
    """
    env = dict(os.environ)
    for key in ENV_OF.values():
        env.pop(key, None)
    # The home prompt switches the endpoint probe off for its own speed, and
    # here it runs in THIS process, so the switch was still on when the
    # conversation inherited the environment: config then skipped asking the
    # server what it serves and fell back to the repository's 65536, halving
    # the window of a machine serving 131072. It is a flag for drawing a page,
    # never for running a project.
    env.pop("PRAGMA_NO_ENDPOINT_PROBE", None)
    settings = entry.get("settings") or {}
    for key, name in ENV_OF.items():
        value = str(settings.get(key, "")).strip()
        if value:
            env[name] = value
    env["PRAGMA_PROJECT"] = entry["name"]
    env["PRAGMA_WORKSPACE"] = str(entry.get("workspace") or "")
    env["PRAGMA_DATA_DIR"] = str(entry.get("memory") or "")
    env.setdefault("PYTHONPATH", str(ROOT))
    return env


def touch_opened(name: str) -> None:
    entries = read_registry()
    for e in entries:
        if e["name"] == name:
            e["last_opened"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_registry(entries)


def brief(entry: dict, env: dict) -> dict:
    store = Path(entry.get("memory") or "") / "episodes"
    try:
        done = subprocess.run([sys.executable, str(ROOT / "tools" / "pragma_brief.py"), str(store)],
                              capture_output=True, text=True, env=env, timeout=120)
        return json.loads(done.stdout or "{}")
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}


def show_brief(entry: dict, data: dict) -> None:
    """Two questions: can I start, and what changed while I was away. Plus one
    line for each thing that wants you. The same page the Windows launcher
    draws - see Show-Brief in tools/Pragma.psm1."""
    a = accent()
    r = RESET if a else ""
    g = GREY if a else ""
    logo()
    print()
    print(f"   {g}{datetime.now().strftime('%A %d %B, %H:%M')}{r}")
    print()
    print(f"  {g}{'project':<10}{r}{entry['name']}")
    if not data.get("ok"):
        print(f"  {g}{'memory':<10}{r}\033[33m{data.get('error', 'unreadable')}{r}" if a
              else f"  memory    {data.get('error', 'unreadable')}")
        print()
        return
    memory = (f"{data['episodes_active']} episodes active, {data['episodes_dormant']} dormant, "
              f"{data['beliefs']} beliefs")
    away = data.get("away_days")
    if away is not None:
        memory += "   last here " + ("today" if away < 1 else "1 day" if away < 2 else f"{away:.0f} days")
    print(f"  {g}{'memory':<10}{r}{memory}")

    up = data.get("backend") == "up"
    serving = data.get("serving") or ("up (model not reported)" if up else "")
    if up:
        print(f"  {g}{'serving':<10}{r}\033[32m{serving}{r}" if a else f"  serving   {serving}")
    else:
        print(f"  {g}{'serving':<10}{r}\033[31mbackend down{r}" if a else "  serving   backend down")
        why = str(data.get("backend", "")).replace("down - ", "")
        if why and why != "up":
            print(f"            {g}{why}{r}")
        print(f"            {g}/configure to point it elsewhere{r}")

    attention = []
    if int(data.get("working") or 0) > 0:
        attention.append(f"the memory is writing {data.get('working_note') or 'a session'}"
                         " - the counts above will move")
    if int(data.get("jobs_failed") or 0) > 0:
        attention.append(f"{data['jobs_failed']} consolidation(s) did not finish - /jobs")
    window, served = int(data.get("context_window") or 0), int(data.get("n_ctx") or 0)
    if window and data.get("context_source") != "endpoint" and served and served < window:
        attention.append(f"context {window} tokens, but the server has {served} - requests will be refused")
    for role in data.get("roles") or []:
        if not role.get("up"):
            attention.append(f"{role['role']} endpoint {role['name']} - {role['status']} - /configure")
    for line in attention:
        print(f"            \033[33m{line}{r}" if a else f"            {line}")

    news = []
    if int(data.get("went_dormant_n") or 0) > 0:
        news.append(f"{data['went_dormant_n']} episode(s) went dormant")
    for revised in data.get("revised") or []:
        news.append(f'belief revised - "{revised}"')
    if int(data.get("fading") or 0) > 0:
        news.append(f"{data['fading']} episode(s) close to fading")
    if data.get("last_goal"):
        news.append("last time you were on: " + data["last_goal"])
    if news:
        print()
        print(f"  {g}Since you left{r}")
        for line in news:
            print(f"    {line}")
    print()


def talk(entry: dict, env: dict) -> str:
    """The conversation, with the project's environment. Returns what it asks
    the launcher for next: settings, backups, switch, new, delete, close."""
    request = Path.home() / ".pragma" / f"request-{os.getpid()}.json"
    request.parent.mkdir(parents=True, exist_ok=True)
    request.unlink(missing_ok=True)
    env = dict(env, PRAGMA_REQUEST=str(request))
    steps = str((entry.get("settings") or {}).get("MaxSteps", "")).strip() or DEFAULT_STEPS
    argv = [sys.executable, "-m", "agent.chat", "--cwd", str(entry.get("workspace") or Path.cwd()), "--memory"]
    if steps:
        argv += ["--max-steps", steps]
    subprocess.run(argv, cwd=str(ROOT), env=env)
    want = ""
    if request.exists():
        try:
            want = str(json.loads(request.read_text(encoding="utf-8")).get("action") or "")
        except Exception:
            want = ""
        request.unlink(missing_ok=True)
    return want


# ── the pages ─────────────────────────────────────────────────────────────────

def choices_page(entry: dict) -> None:
    """The decisions that change how a project feels, asked one at a time.
    Enter keeps what is in brackets, ctrl+D stops. The same five questions as
    Invoke-ProjectChoices on Windows."""
    name = entry["name"]
    print()
    say(f"  choices for '{name}'", "accent")
    say("  enter keeps the value in brackets . ctrl+D stops", "dim")

    def current(key, default=""):
        return str((by_name(name).get("settings") or {}).get(key, default) or default)

    print()
    print("  agent thinking - does the agent reason before each step?")
    say("    off  it answers and acts at once: fast, every turn (recommended for a conversation)", "dim")
    say("    on   it reasons first: better on problems in several steps, many times slower", "dim")
    shown = "on" if current("AgentThink") in ("on", "1", "true", "yes") else "off"
    while True:
        value = ask("agent thinking", shown)
        if value is None:
            return
        if value == shown:
            break
        if value.lower() in ("on", "off"):
            save_setting(name, "AgentThink", value.lower())
            break
        say("    on or off", "warn")

    print()
    print("  memory thinking - do the memory calls reason before answering?")
    say("    select  recall and segmenting answer at once, writing memory reasons (recommended)", "dim")
    say("    all     no memory call reasons: fastest, plainer episodes and beliefs", "dim")
    say("    on      every memory call reasons: slowest, the writing runs in the background", "dim")
    shown = current("MemoryNoThink") if current("MemoryNoThink") in ("select", "all", "write") else "on"
    while True:
        value = ask("memory thinking", shown)
        if value is None:
            return
        if value == shown:
            break
        if value.lower() in ("select", "all", "on"):
            save_setting(name, "MemoryNoThink", "" if value.lower() == "on" else value.lower())
            break
        say("    select, all or on", "warn")

    print()
    print("  memory sampling - when a memory call reasons, how does it pick its words?")
    say("    preset  the model's thinking preset with a fixed seed: no loops, same answer twice (recommended)", "dim")
    say("    greedy  temperature 0 always, as the paper's runs were: a thinking model may loop", "dim")
    shown = "greedy" if current("MemorySampling") == "greedy" else "preset"
    while True:
        value = ask("memory sampling", shown)
        if value is None:
            return
        if value == shown:
            break
        if value.lower() in ("preset", "greedy"):
            save_setting(name, "MemorySampling", value.lower())
            break
        say("    preset or greedy", "warn")

    print()
    print("  sampling - who picks temperature, top_k, top_p and min_p?")
    say("    server  the endpoint decides all four (recommended)", "dim")
    say("    greedy  temperature 0: the most likely word, every time", "dim")
    say("    manual  enter the four yourself", "dim")
    temperature = current("Temperature")
    shown = ("server" if temperature == "server"
             else "greedy" if temperature in ("0", "0.0", "") and not current("TopK") else "manual")
    while True:
        value = ask("sampling", shown)
        if value is None:
            return
        if value == shown and value != "manual":
            break
        if value.lower() in ("server", "greedy", "manual"):
            set_sampling(name, value.lower())
            break
        say("    server, greedy or manual", "warn")

    print()
    print("  steps per turn - how many actions the agent may take before it must answer")
    say(f"    {DEFAULT_STEPS} suits a conversation; long tasks on files may need more", "dim")
    shown = current("MaxSteps", DEFAULT_STEPS)
    while True:
        value = ask("steps per turn", shown)
        if value is None:
            return
        if value == shown:
            break
        if value.isdigit() and 1 <= int(value) <= 1000:
            save_setting(name, "MaxSteps", value)
            break
        say("    a number from 1 to 1000", "warn")
    print()


def set_sampling(name: str, how: str) -> None:
    """server: send none of the four. greedy: temperature 0 and the rest cleared.
    manual: all four, asked."""
    if how == "server":
        for key, value in (("Temperature", "server"), ("TopK", ""), ("TopP", ""), ("MinP", "")):
            save_setting(name, key, value)
        say("  sampling: the server's - it decides all four", "dim")
        return
    if how == "greedy":
        for key, value in (("Temperature", "0.0"), ("TopK", ""), ("TopP", ""), ("MinP", "")):
            save_setting(name, key, value)
        say("  sampling: greedy - the most likely word, every time", "dim")
        return
    for key, question in (("Temperature", "temperature"), ("TopK", "top_k"),
                          ("TopP", "top_p"), ("MinP", "min_p")):
        value = ask(question, hint="a number, or empty to leave it to the server")
        if value is None:
            return
        save_setting(name, key, value.strip())


def backups_page(entry: dict) -> None:
    store = Path(entry.get("memory") or "")
    folder = store.parent / "backups" / entry["name"]
    folder.mkdir(parents=True, exist_ok=True)
    zips = sorted(folder.glob("memory_*.zip"), reverse=True)
    what = pick(f"backups of '{entry['name']}'",
                ["take a snapshot now"] + [z.name for z in zips],
                ["the whole store, zipped beside it"] + [f"{z.stat().st_size / 1024:.0f} KB" for z in zips])
    if what is None:
        return
    if what == 0:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        dest = folder / f"memory_{stamp}.zip"
        i = 2
        while dest.exists():                       # never overwrite a snapshot
            dest = folder / f"memory_{stamp}_{i}.zip"
            i += 1
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in store.rglob("*"):
                if item.is_file() and "backups" not in item.parts:
                    zf.write(item, item.relative_to(store).as_posix())
        say(f"  backup: {dest}  ({dest.stat().st_size / 1024:.0f} KB)", "good")
        return
    chosen = zips[what - 1]
    say(f"  restoring {chosen.name} over the store at {store}", "warn")
    say("  what is there now is replaced. A snapshot of it is taken first.", "dim")
    if (ask("type the project name to confirm") or "") != entry["name"]:
        say("  nothing touched", "good")
        return
    safety = folder / f"memory_before_restore_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.zip"
    with zipfile.ZipFile(safety, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in store.rglob("*"):
            if item.is_file() and "backups" not in item.parts:
                zf.write(item, item.relative_to(store).as_posix())
    for item in list(store.iterdir()):
        if item.name == "backups":
            continue
        shutil.rmtree(item) if item.is_dir() else item.unlink()
    with zipfile.ZipFile(chosen) as zf:
        zf.extractall(store)
    say(f"  restored. The store as it was is in {safety.name}", "good")


def new_project() -> dict | None:
    name = ask("name of the project", hint="letters, digits, - and _")
    if name is None:
        return None
    name = name.strip()
    if not name or not all(c.isalnum() or c in "-._" for c in name):
        say("  that is not a usable name", "warn")
        return None
    if by_name(name):
        say(f"  there is already a project called '{name}'", "warn")
        return None
    workspace = ask("workspace - the folder the agent works in", str(Path.cwd()))
    if workspace is None:
        return None
    ws = Path(workspace).expanduser().resolve()
    if not ws.is_dir():
        say(f"  no such folder: {ws}", "warn")
        return None
    if ROOT == ws or ROOT in ws.parents:
        say("  not inside Pragma's own source: the agent must never edit itself", "warn")
        return None
    store = PROJECTS / name
    (store / "episodes").mkdir(parents=True, exist_ok=True)
    entry = {"name": name, "workspace": str(ws), "memory": str(store),
             "last_opened": "", "settings": dict(NEW_PROJECT_SETTINGS)}
    write_registry(read_registry() + [entry])
    say(f"  project '{name}'", "good")
    say(f"        workspace  {ws}", "dim")
    say(f"        memory     {store}", "dim")
    choices_page(entry)
    return by_name(name)


def open_project(suggested: dict | None = None) -> dict | None:
    entries = read_registry()
    if not entries:
        say("  no projects yet - /new starts one", "dim")
        return None
    entries.sort(key=lambda e: str(e.get("last_opened") or ""), reverse=True)
    names = [e["name"] for e in entries]
    notes = [f"{e.get('workspace', '')}" for e in entries]
    chosen = pick("open which project", names, notes)
    return entries[chosen] if chosen is not None else None


def delete_project(entry: dict | None = None) -> dict | None:
    """Remove a project: the registry entry and the memory it keeps.

    The same page, and the same meaning, as Invoke-DeleteProject on Windows -
    a destructive action that means two different things on two systems is
    worse than not having it. What Pragma made, Pragma removes; the workspace
    is the operator's own folder, often a git repository and often the only
    copy of something, so it is never touched. Snapshots stay too: they are
    the way back from exactly this.

    Returns the project still open afterwards, or None when it was the one
    deleted (or when there was none to begin with).
    """
    entries = read_registry()
    if not entries:
        say("  no projects to delete", "dim")
        return entry
    chosen = pick("delete which project", [e["name"] for e in entries],
                  [str(e.get("workspace") or "") for e in entries])
    if chosen is None:
        return entry
    doomed = entries[chosen]
    store = Path(doomed.get("memory") or "")
    there = bool(str(store)) and store.is_dir()
    episodes = len(list((store / "episodes").glob("ep_*.json"))) if there else 0
    backups = store.parent / "backups" / doomed["name"]

    clear()
    print()
    say(f"  Delete '{doomed['name']}'", "bad")
    print()
    say("  This removes, for good:", "dim")
    if there:
        print(f"    the memory        {store}")
        print(f"                      {episodes} episode(s), and every belief drawn from them")
    else:
        # A page that says "this removes the memory" about a folder that is
        # not there is how someone comes away sure a store was deleted when
        # nothing was. It says what it found instead.
        print("    the registry entry - and nothing else: there is no store at")
        print(f"                      {store or '(the entry names none)'}")
    if there:
        print("    the registry entry")
    print()
    say("  This does NOT touch:", "dim")
    print(f"    the workspace     {doomed.get('workspace')}")
    if backups.is_dir():
        print(f"    the snapshots     {backups}")
    print()
    say("  There is no undo.", "bad")
    print()
    if (ask("type the project name to confirm", hint="ctrl+D goes back") or "") != doomed["name"]:
        say("  not deleted", "good")
        ask("", hint="enter to go back")
        return entry
    write_registry([e for e in read_registry() if e["name"] != doomed["name"]])
    gone = True
    if there:
        try:
            shutil.rmtree(store)
        except Exception as e:
            gone = False
            say(f"  the entry is gone, but the store is not: {type(e).__name__}: {str(e)[:90]}", "warn")
            say(f"  remove it by hand: {store}", "dim")
    if not there:
        say(f"  '{doomed['name']}' removed from the registry. There was no store to delete.", "good")
    else:
        say(f"  '{doomed['name']}' deleted" + ("" if gone else " from the registry"), "good")
    ask("", hint="enter to go back")
    return None if (entry and entry["name"] == doomed["name"]) else entry


# ── the loop ──────────────────────────────────────────────────────────────────

def home_prompt() -> tuple[str, str]:
    """The shared home prompt, as a (action, argument). It draws the endpoints,
    the memory being written, the plugins, and reads the line."""
    out = Path.home() / ".pragma" / f"home-{os.getpid()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    argv = sys.argv
    probe = os.environ.get("PRAGMA_NO_ENDPOINT_PROBE")
    try:
        sys.argv = ["pragma_home", "--out", str(out)]
        home.main()
    finally:
        sys.argv = argv
        # And put the environment back as it was found, so nothing downstream
        # inherits a flag that belonged to one page.
        if probe is None:
            os.environ.pop("PRAGMA_NO_ENDPOINT_PROBE", None)
        else:
            os.environ["PRAGMA_NO_ENDPOINT_PROBE"] = probe
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except Exception:
        data = {"action": "exit", "arg": ""}
    out.unlink(missing_ok=True)
    return str(data.get("action") or ""), str(data.get("arg") or "")


def home_page() -> None:
    clear()
    logo()
    print()
    n = len(read_registry())
    say(f"  {'No projects yet.' if not n else '1 project' if n == 1 else f'{n} projects'}", "dim")
    print()
    a, r = accent(), (RESET if accent() else "")
    # From the prompt's own rows, so a command added there appears here
    # without a second list to remember - and so an empty registry offers
    # only what makes sense on it.
    for command, blurb in home.rows():
        print(f"  {a}{command:<12}{r}{GREY if a else ''}{blurb}{r}")


def projects_page() -> dict | None:
    """Everything that is done TO a project: four words, and the list of
    projects under the first of them.

    The page listed the projects itself at first, which put two questions on
    one screen - which project, and what to do with it - and meant the list
    had to be read before the word you wanted was visible.

    Returns the project to open, or None to stay at home.
    """
    while True:
        clear()
        print()
        say("  projects", "accent")
        # Up to the semicolon: what the word does. What comes after it is how
        # to type the same thing at the prompt, which is not news on a page
        # that is already offering it.
        chosen = pick("", list(home.PROJECT_ACTIONS),
                      [blurb.split(";")[0] for blurb in home.PROJECT_ACTIONS.values()])
        if chosen is None:
            return None
        action = list(home.PROJECT_ACTIONS)[chosen]
        if action == "open":
            entry = open_project()
            if entry:
                return entry
        elif action == "new":
            made = new_project()
            if made:
                return made
        elif action == "delete":
            delete_project()
        elif action == "backups":
            entry = open_project()
            if entry:
                backups_page(entry)
                ask("", hint="enter to go back")


def configure_page() -> None:
    subprocess.run([sys.executable, str(ROOT / "tools" / "pragma_configure.py")], cwd=str(ROOT))


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    entry: dict | None = None
    notice = ""
    while True:
        if entry is None:
            home_page()
            if notice:
                say(f"  {notice}", "warn")
                notice = ""
            action, arg = home_prompt()
            if action in ("exit", ""):
                clear()
                return 0
            if action == "open":
                entry = by_name(arg) if arg else open_project()
                if arg and entry is None:
                    notice = f"No project named '{arg}'."
            elif action == "new":
                entry = new_project()
            elif action == "projects":
                entry = projects_page()
            elif action == "delete":
                delete_project()
            elif action == "backups":
                chosen = by_name(arg) if arg else open_project()
                if chosen:
                    backups_page(chosen)
                    ask("", hint="enter to go back")
            elif action == "configure":
                configure_page()
            elif action == "clear":
                pass
            continue

        # A project is open: its briefing, then its conversation.
        env = environment(entry)
        touch_opened(entry["name"])
        clear()
        show_brief(entry, brief(entry, env))
        want = talk(entry, env)
        if want == "refresh":
            continue
        if want == "settings":
            clear()
            choices_page(entry)
            entry = by_name(entry["name"]) or entry
            ask("", hint="enter to go back")
        elif want == "backups":
            clear()
            backups_page(entry)
            ask("", hint="enter to go back")
        elif want == "switch":
            chosen = open_project(entry)
            entry = chosen or entry
        elif want == "new":
            entry = new_project() or entry
        elif want == "delete":
            entry = delete_project(entry)
        else:                                   # close, or the conversation ended
            entry = None


if __name__ == "__main__":
    raise SystemExit(main())
