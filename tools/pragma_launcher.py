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

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "core"), str(ROOT / "tools")]

import pragma_home as home                     # noqa: E402  the home prompt, shared
# The arrows, the digits, the first letter, ctrl+D: one menu, every page that
# offers a choice - this one and /configure.
from pragma_menu import (SEP, accent, ask, choose, clear, confirm, menu,   # noqa: E402,F401
                         pause, pick, read_key, row, say, title)

REGISTRY = Path.home() / ".pragma" / "registry.json"
PROJECTS = Path.home() / ".pragma" / "projects"
ESC = "\033"
GREY, RESET = ESC + "[38;5;242m", ESC + "[0m"

# A project's settings, and the environment variable each one becomes. The
# same table pragma-session.ps1 applies on Windows: one list, two launchers,
# and a setting that means one thing on one system and another elsewhere is
# not a thing that can happen quietly.
ENV_OF = {
    "Endpoint": "LLM_BASE_URL", "ContextWindow": "CONTEXT_WINDOW", "MaxTokens": "MAX_TOKENS",
    "SkillMaxTokens": "SKILL_MAX_TOKENS", "MemoryMaxTokens": "MEMORY_MAX_TOKENS",
    "Timeout": "LLM_TIMEOUT",
    "CuratorEpisodes": "CURATOR_CANDIDATES_EPISODES",
    "CuratorRecent": "CURATOR_CANDIDATES_RECENT",
    "CuratorLearnings": "CURATOR_CANDIDATES_LEARNINGS",
    "CuratorFragments": "CURATOR_MAX_FRAGMENTS",
    "RecallMemoriesOffered": "CURATOR_OFFERED_EPISODES",
    "RecallBeliefsOffered": "CURATOR_OFFERED_LEARNINGS",
    "RecallMemoriesTaken": "CURATOR_TAKEN_EPISODES",
    "RecallBeliefsTaken": "CURATOR_TAKEN_LEARNINGS",
    "Temperature": "DEFAULT_TEMPERATURE", "TopK": "TOP_K", "TopP": "TOP_P", "MinP": "MIN_P",
}
NEW_PROJECT_SETTINGS: dict[str, str] = {}

# What a recall is offered and what it may take, each few, medium or many. The
# numbers are config's (RECALL_OFFERED, RECALL_TAKEN), repeated here because
# this page is drawn without importing it; what is written under a level is
# what the page says, and the only place it is said.
RECALL = {
    "RecallMemoriesOffered": ("memories offered", "medium", [
        ("few", "the 5 that fit the request best, 2 of them simply the latest"),
        ("medium", "10, 3 of them the latest"),
        ("many", "20, 5 of them the latest - a slower recall")]),
    "RecallBeliefsOffered": ("beliefs offered", "medium", [
        ("few", "the 4 that fit the request best"),
        ("medium", "8"),
        ("many", "16 - a slower recall")]),
    "RecallMemoriesTaken": ("memories taken", "few", [
        ("few", "only what would change the next step"),
        ("medium", "everything that bears on the request, up to 5"),
        ("many", "anything on its subject, up to 8")]),
    "RecallBeliefsTaken": ("beliefs taken", "few", [
        ("few", "only what would change the next step"),
        ("medium", "everything that bears on the request, up to 5"),
        ("many", "anything on its subject, up to 8")]),
}

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


def terminal_lines(fallback: int = 40) -> int:
    """How tall the window IS, asked of the window.

    Not shutil.get_terminal_size, which believes $LINES and $COLUMNS before
    it asks anything: bash sets them, and over ssh or after a resize they are
    routinely stale. A launcher that believed a stale 50 on a 30-line window
    drew the eight-row mark, overflowed the page, and the terminal scrolled
    the mark half off the top - which is exactly the bug this was meant to
    prevent.
    """
    for stream in (sys.__stdout__, sys.__stderr__, sys.__stdin__):
        try:
            return os.get_terminal_size(stream.fileno()).lines
        except Exception:
            continue
    try:                                    # no terminal to ask: the env, then a guess
        return shutil.get_terminal_size(fallback=(80, fallback)).lines
    except Exception:
        return fallback


# What the page needs under the mark before the prompt has somewhere to sit:
# the commands, the endpoint, whatever the memory is writing, and the lines
# prompt_toolkit keeps free for its completion menu - plus one line for each
# project listed, which home_page() adds. Below this the terminal scrolls, and
# what goes off the top is the mark - which is how it comes to be half drawn.
ROOM_FOR_THE_MARK = 26


def logo(compact: bool | None = None) -> None:
    """The mark, or the word alone on a terminal too short to hold it.

    The PowerShell launcher has had the compact form since the beginning, for
    exactly this: eight rows of block characters are worth the space on a
    window that has it, and are the first thing to lose on one that does not.
    """
    if compact is None:
        compact = terminal_lines() < ROOM_FOR_THE_MARK
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
    for line in LOGO:
        print(f"  {a}" + "".join(glyph.get(c, c) for c in line) + r)



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


@contextlib.contextmanager
def child_owns_ctrl_c():
    """While a child runs in this window, ctrl+C is the child's.

    The terminal sends ctrl+C to every process in the foreground group, and
    that is this launcher as well as the conversation it started. The
    conversation stops a reply with it; the launcher, waiting in
    subprocess.run, took it as its own and died with a traceback - so ctrl+C
    during an answer threw the operator out of Pragma altogether, and left the
    conversation without its parent. MEASURED in tmux, 2026-09-30.

    A handler that does nothing, not SIG_IGN: an ignored signal stays ignored
    across exec, and the child would inherit a ctrl+C that no longer reaches
    it. A handler is reset to the default in the child, which then does with
    the key what it means to do.
    """
    try:
        old = signal.signal(signal.SIGINT, lambda *_: None)
    except (ValueError, OSError):       # not the main thread: nothing to guard
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, old)


def brief(entry: dict, env: dict) -> dict:
    store = Path(entry.get("memory") or "") / "episodes"
    try:
        with child_owns_ctrl_c():
            done = subprocess.run([sys.executable, str(ROOT / "tools" / "pragma_brief.py"), str(store)],
                                  capture_output=True, text=True, env=env, timeout=120)
        return json.loads(done.stdout or "{}")
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}


def _n(count, one: str, many: str = "") -> str:
    """"1 episode", "3 episodes": a count with its noun agreeing."""
    count = int(count or 0)
    return f"{count} {one if count == 1 else (many or one + 's')}"


def show_brief(entry: dict, data: dict) -> None:
    """Two questions: can I start, and what changed while I was away. Plus one
    line for each thing that wants you. The same page the Windows launcher
    draws - see Show-Brief in tools/Pragma.psm1."""
    a = accent()
    r = RESET if a else ""
    g = GREY if a else ""
    logo()
    print()
    print(f"  {a}{entry['name']}{r}   {g}{datetime.now().strftime('%A %d %B, %H:%M')}{r}")
    print()
    if not data.get("ok"):
        row("memory", str(data.get("error", "unreadable")), ESC + "[33m")
        print()
        return
    memory = SEP.join([_n(data.get("episodes_active"), "episode") + " active",
                       f"{int(data.get('episodes_dormant') or 0)} dormant",
                       _n(data.get("beliefs"), "belief")])
    away = data.get("away_days")
    if away is not None:
        memory += SEP + "last here " + ("today" if away < 1 else "yesterday" if away < 2
                                        else f"{away:.0f} days ago")
    row("memory", memory)

    up = data.get("backend") == "up"
    if up:
        row("serving", data.get("serving_display") or data.get("serving")
            or "up (the model is not reported)", ESC + "[32m")
    else:
        why = str(data.get("backend", "")).replace("down - ", "")
        row("serving", "the model server is down" + (f" - {why}" if why and why != "up" else ""),
            ESC + "[31m")
        row("", "/configure points Pragma at another one")

    attention = []
    if int(data.get("working") or 0) > 0:
        attention.append(f"the memory is writing {data.get('working_note') or 'a session'}"
                         " - the counts above will move")
    if int(data.get("jobs_failed") or 0) > 0:
        attention.append(_n(data["jobs_failed"], "consolidation") + " did not finish - /jobs")
    window, served = int(data.get("context_window") or 0), int(data.get("n_ctx") or 0)
    if window and data.get("context_source") != "endpoint" and served and served < window:
        attention.append(f"context {window} tokens, but the server has {served} - requests will be refused")
    for role in data.get("roles") or []:
        if not role.get("up"):
            attention.append(f"{role['role']} endpoint {role['name']} - {role['status']} - /configure")
    for line in attention:
        row("", line, ESC + "[33m")

    news = []
    if int(data.get("went_dormant_n") or 0) > 0:
        news.append(_n(data["went_dormant_n"], "episode") + " went dormant")
    for revised in data.get("revised") or []:
        news.append(f'a belief was revised - "{revised}"')
    if int(data.get("fading") or 0) > 0:
        news.append(_n(data["fading"], "episode") + " close to fading")
    if data.get("last_goal"):
        news.append("last time you were on: " + data["last_goal"])
    if news:
        print()
        say("  since you left", "dim")
        for line in news:
            row("", line, indent=2, width=2)
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
    with child_owns_ctrl_c():
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

def choices_page(entry: dict) -> bool:
    """What a project decides for itself: how many steps a turn may take, and
    how much its memory brings to one.

    Everything else a project used to decide - whether the agent reasons, how
    it samples, whether Pragma guesses your next question - belongs to the
    endpoint now, in /configure. The conversation opens this same page with
    /settings, without closing: see main().

    Returns whether anything was changed.
    """
    name = entry["name"]
    changed = False
    at = 0
    while True:
        settings = (by_name(name) or entry).get("settings") or {}
        steps = str(settings.get("MaxSteps", "") or DEFAULT_STEPS)
        keys = ["MaxSteps"] + list(RECALL)
        options, notes = ["steps per turn"], [steps]
        for key, (label, default, levels) in RECALL.items():
            level = str(settings.get(key, "") or default)
            options.append(label)
            notes.append(f"{level}{SEP}{dict(levels).get(level, '')}")
        title("Settings", name)
        chosen = pick("", options, notes, at)
        if chosen is None:
            return changed
        at = chosen
        key = keys[chosen]
        if key == "MaxSteps":
            changed = steps_question(name, steps) or changed
            continue
        label, default, levels = RECALL[key]
        now = str(settings.get(key, "") or default)
        title("Settings", f"{name} > {label}")
        print()
        for line in RECALL_SAYS["Offered" if key.endswith("Offered") else "Taken"]:
            say(f"  {line}", "dim")
        level = choose("", levels, now)
        if level is None or level == now:
            continue
        # The level a project has never chosen is not written down: absent
        # means "as Pragma comes", and stays that if what Pragma comes with
        # ever changes.
        save_setting(name, key, "" if level == default else level)
        changed = True


# What the two questions about a recall mean, said once above the three levels.
RECALL_SAYS = {
    "Offered": ("Before a turn, the memory is searched for what fits the request, and",
                "the best of it is offered to the model that decides what to recall.",
                "More offered is a wider search and a slower recall."),
    "Taken": ("Of what it is offered, the model takes what it judges worth putting",
              "in front of the agent. This is how readily it takes. What is taken",
              "stays there for the rest of the conversation, and a memory that is",
              "recalled fades more slowly."),
}


def steps_question(name: str, shown: str) -> bool:
    """Ask for the steps per turn. Whether the number was changed."""
    title("Settings", f"{name} > steps per turn")
    print()
    say("  How many actions the agent may take in one turn before it must", "dim")
    say(f"  answer. {DEFAULT_STEPS} suits a conversation; long work on files may need more.", "dim")
    print()
    while True:
        value = ask("steps per turn", shown, hint="enter keeps it · ctrl+D goes back")
        if value is None or value == shown:
            return False
        if value.isdigit() and 1 <= int(value) <= 1000:
            save_setting(name, "MaxSteps", value)
            return True
        say("    a number from 1 to 1000", "warn")


def backups_page(entry: dict) -> None:
    store = Path(entry.get("memory") or "")
    folder = store.parent / "backups" / entry["name"]
    folder.mkdir(parents=True, exist_ok=True)
    zips = sorted(folder.glob("memory_*.zip"), reverse=True)
    title("Backups", entry["name"])
    what = pick("", ["take a snapshot now"] + [z.name for z in zips],
                ["the whole memory, zipped beside it"]
                + [f"restore this one · {z.stat().st_size / 1024:.0f} KB" for z in zips])
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
        print()
        say(f"  snapshot taken  ({dest.stat().st_size / 1024:.0f} KB)", "good")
        say(f"  {dest}", "dim")
        print()
        pause()
        return
    chosen = zips[what - 1]
    print()
    say(f"  Restore {chosen.name}?", "warn")
    say(f"  The memory at {store} is replaced by it.", "dim")
    say("  A snapshot of what is there now is taken first.", "dim")
    print()
    if (ask("type the project name to confirm", hint="ctrl+D goes back") or "") != entry["name"]:
        say("  nothing touched", "good")
        print()
        pause()
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
    say(f"  restored. The memory as it was is in {safety.name}", "good")
    print()
    pause()


def suggested_workspace(name: str) -> Path:
    """Where a new project's folder is offered: here, unless here is a bad idea.

    It was always the folder the launcher was started in - which, started from
    a shortcut or a fresh terminal, is the home folder: the agent would have
    been handed the whole of it. Now the current folder is offered only when it
    looks like a project's own, and a folder named after the project, in the
    home folder, otherwise.
    """
    here, home = Path.cwd().resolve(), Path.home().resolve()
    taken = {str(Path(e.get("workspace") or "").resolve()) for e in read_registry()
             if e.get("workspace")}
    if (here == home or here == Path(here.anchor) or here == ROOT or ROOT in here.parents
            or str(here) in taken or here in home.parents):
        return home / name
    return here


def new_project() -> dict | None:
    title("New project")
    print()
    say("  A project is a folder the agent works in, and a memory of its own.", "dim")
    print()
    while True:
        name = ask("name", hint="letters, digits, - and _ · ctrl+D goes back")
        if name is None:
            return None
        name = name.strip()
        if not name or not all(c.isalnum() or c in "-._" for c in name):
            say("    letters, digits, - and _ only", "warn")
            continue
        if by_name(name):
            say(f"    there is already a project called '{name}'", "warn")
            continue
        break
    while True:
        workspace = ask("folder", str(suggested_workspace(name)))
        if workspace is None:
            return None
        ws = Path(workspace).expanduser().resolve()
        if ws.exists() and not ws.is_dir():
            say(f"    that is a file, not a folder: {ws}", "warn")
            continue
        if ROOT == ws or ROOT in ws.parents:
            say("    not inside Pragma's own source: the agent must never edit itself", "warn")
            continue
        break
    # A FOLDER THAT IS NOT THERE YET is the normal way to start a project, not
    # a mistake: you name where the work will go before there is any. So it is
    # offered, not refused - and still offered rather than made silently,
    # because a typed path with a typo in it would otherwise become a folder
    # nobody meant to create.
    if not ws.exists():
        if not confirm(f"{ws} does not exist yet. Create it?", "yes, create it"):
            return None
        try:
            ws.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            say(f"  cannot create it: {e.strerror or e}", "warn")
            pause()
            return None
    store = PROJECTS / name
    (store / "episodes").mkdir(parents=True, exist_ok=True)
    entry = {"name": name, "workspace": str(ws), "memory": str(store),
             "last_opened": "", "settings": dict(NEW_PROJECT_SETTINGS)}
    write_registry(read_registry() + [entry])
    return by_name(name)


def open_project(heading: str = "Open a project") -> dict | None:
    """A project chosen from the list, or None. With one project there is
    nothing to choose: it is the answer."""
    entries = read_registry()
    if not entries:
        say("  no projects yet - /new starts one", "dim")
        return None
    if len(entries) == 1:
        return entries[0]
    entries.sort(key=lambda e: str(e.get("last_opened") or ""), reverse=True)
    title(heading)
    chosen = pick("", [e["name"] for e in entries],
                  [home._home_short(str(e.get("workspace", ""))) for e in entries])
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
    title("Delete a project")
    chosen = pick("", [e["name"] for e in entries],
                  [home._home_short(str(e.get("workspace") or "")) for e in entries])
    if chosen is None:
        return entry
    doomed = entries[chosen]
    store = Path(doomed.get("memory") or "")
    there = bool(str(store)) and store.is_dir()
    episodes = len(list((store / "episodes").glob("ep_*.json"))) if there else 0
    backups = store.parent / "backups" / doomed["name"]

    title("Delete a project", doomed["name"])
    print()
    say("  This removes, for good:", "dim")
    if there:
        print(f"    the memory        {store}")
        print(f"                      {_n(episodes, 'episode')}, and every belief drawn from them")
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
        print()
        pause()
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
    print()
    pause()
    return None if (entry and entry["name"] == doomed["name"]) else entry


# ── the loop ──────────────────────────────────────────────────────────────────

def home_prompt(notice: str = "") -> tuple[str, str]:
    """The shared home prompt, as a (action, argument). It draws the body of
    the page - projects, commands, endpoints, the memory at work, the plugins -
    and reads the line. The mark above it is drawn by home_page()."""
    out = Path.home() / ".pragma" / f"home-{os.getpid()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    argv = sys.argv
    probe = os.environ.get("PRAGMA_NO_ENDPOINT_PROBE")
    try:
        sys.argv = ["pragma_home", "--out", str(out), "--page"] + (
            ["--notice", notice] if notice else [])
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
    listed = min(len(read_registry()), home.RECENT)
    logo(terminal_lines() < ROOM_FOR_THE_MARK + listed)


def projects_page() -> dict | None:
    """Everything that is done TO a project: four words, and the list of
    projects under the one that needs it.

    Returns the project to open, or None to stay at home.
    """
    at = 0
    while True:
        title("Projects")
        # Up to the semicolon: what the word does. What comes after it is how
        # to type the same thing at the prompt, which is not news on a page
        # that is already offering it.
        chosen = pick("", list(home.PROJECT_ACTIONS),
                      [blurb.split(";")[0] for blurb in home.PROJECT_ACTIONS.values()], at)
        if chosen is None:
            return None
        at = chosen
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
            entry = open_project("Back up which project?")
            if entry:
                backups_page(entry)


def configure_page() -> None:
    with child_owns_ctrl_c():
        subprocess.run([sys.executable, str(ROOT / "tools" / "pragma_configure.py")], cwd=str(ROOT))


def run() -> int:
    entry: dict | None = None
    notice = ""
    while True:
        if entry is None:
            home_page()
            action, arg = home_prompt(notice)
            notice = ""
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
                chosen = by_name(arg) if arg else open_project("Back up which project?")
                if chosen:
                    backups_page(chosen)
            elif action == "configure":
                configure_page()
            elif action == "clear":
                notice = arg
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
            choices_page(entry)
            entry = by_name(entry["name"]) or entry
        elif want == "backups":
            backups_page(entry)
        elif want == "switch":
            chosen = open_project()
            entry = chosen or entry
        elif want == "new":
            entry = new_project() or entry
        elif want == "delete":
            entry = delete_project(entry)
        else:                                   # close, or the conversation ended
            entry = None


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--settings":
            # One page and back: what an open conversation runs for /settings,
            # so that changing a setting does not mean closing it. 0 when
            # something was changed, 3 when nothing was - /configure's codes.
            entry = by_name(sys.argv[2])
            if entry is None:
                print(f"  No project named '{sys.argv[2]}'.")
                return 2
            return 0 if choices_page(entry) else 3
        return run()
    except KeyboardInterrupt:
        # The last line of defence, not the way out: every page takes ctrl+C
        # as "back". Whatever still reaches here leaves quietly - a traceback
        # is not a goodbye.
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
