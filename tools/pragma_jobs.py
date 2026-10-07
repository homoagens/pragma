# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# pragma_jobs.py - the record of work the memory is doing on its own.
#
# Consolidation used to happen between `/exit` and the prompt coming back: the
# segmenter, the consolidator, the abstractor and the sweep, in the foreground,
# with the operator watching a spinner for a minute because the conversation
# they had just left was still being written down. Leaving a room should not
# take longer than being in it.
#
# So the work moves to its own process and leaves a JOB behind: one file per
# consolidation, holding what is being consolidated, what each faculty said,
# and how it ended. That file is what makes the background acceptable. Work you
# cannot see is work you cannot trust, and a memory that writes itself in
# silence is exactly the thing this project argues against.
#
#     <store>/jobs/job_<stamp>.json
#
# A JOB IS NOT A RECORD. It exists while the work does, and a consolidation
# that succeeded deletes its own file: the episode is the record, and a list of
# every consolidation ever run is a second, worse copy of the store. What
# survives is what still wants someone - work in flight, and work that failed.
#
# Failure is kept on purpose. The turns are copied into the job, so a worker
# that dies leaves everything needed to run it again, and the briefing says so
# rather than losing the session quietly.
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "core")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config                    # noqa: E402
import episodes as estore        # noqa: E402


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def jobs_dir(store: Path | None = None) -> Path:
    """Where jobs live: beside the episodes, inside the project's own store.

    Never in the workspace. A job holds the text of your turns, and a workspace
    is often a git repository.
    """
    root = Path(store) if store else Path(config.DATA_DIR)
    return root / "jobs"


# --- reading ------------------------------------------------------------------

def read(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def write(path: Path, job: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    estore.write_json(Path(path), job)


def alive(pid) -> bool:
    """Is that process still there? Unknown counts as alive.

    Guessing "dead" wrongly is the expensive mistake: it lets a second worker
    start on a store the first one is still writing.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return False
        # WAIT_TIMEOUT (258) means it is still running; WAIT_OBJECT_0 (0) that
        # it has exited and the handle is merely still open.
        rc = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
        ctypes.windll.kernel32.CloseHandle(h)
        return rc == 258
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _abandoned(job: dict) -> bool:
    if job.get("status") not in ("pending", "running"):
        return False
    if alive(job.get("pid")):
        return False
    if not job.get("pid"):
        # Written but never picked up: give the spawn a moment before judging.
        try:
            age = time.time() - Path(job["_path"]).stat().st_mtime
        except Exception:
            return False
        return age > 30
    return True


def listing(store: Path | None = None, limit: int = 20,
            include_done: bool = False) -> list[dict]:
    """Newest first. Each job carries `_path`, and a dead one reads as failed.

    A finished job is NOT history. Consolidation that worked has left its trace
    where traces belong - in the episodes - and a list of everything the memory
    has ever written down is a second, worse copy of the store. So `done` is
    excluded by default and the file is deleted; what survives is what still
    needs someone: work in flight, and work that failed.

    The status is corrected on the way out rather than in the file: a launcher
    that only ever reads must not have to write to tell the truth, and the
    worker owns that file for as long as it is alive.
    """
    d = jobs_dir(store)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("job_*.json"), reverse=True)[:limit]:
        job = read(p)
        if not job:
            continue
        job["_path"] = str(p)
        if _abandoned(job):
            job["status"] = "abandoned"
        if job["status"] == "done" and not include_done:
            continue
        out.append(job)
    return out


def running(store: Path | None = None) -> dict | None:
    """The job actually being worked on now, or None."""
    for job in listing(store, limit=8):
        if job.get("status") in ("pending", "running"):
            return job
    return None


# --- writing ------------------------------------------------------------------

def create(turns: list[dict], workspace: str, note: str,
           store: Path | None = None) -> Path:
    """File a job and return its path. The caller then starts a worker on it."""
    d = jobs_dir(store)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = d / f"job_{stamp}_{os.getpid()}.json"
    write(path, {
        "id": path.stem,
        "status": "pending",
        "pid": 0,
        "created": _utc(),
        "started": "",
        "finished": "",
        "workspace": workspace,
        "note": note,
        "turns": turns,
        "log": [],
        "episodes": [],
        "error": "",
    })
    return path


def prune(store: Path | None = None, keep_failed: int = 5) -> None:
    """Delete every finished job, and cap the failed ones.

    Success leaves nothing: the episode is the record, and the job file holds
    the text of your turns, which is not a thing to accumulate in a second
    place for ever.

    Failure is kept, because the turns in it are the only way to run it again -
    but not without limit either, or one broken endpoint fills the folder with
    copies of the same evening.
    """
    d = jobs_dir(store)
    if not d.is_dir():
        return
    failed = []
    for p in sorted(d.glob("job_*.json"), reverse=True):
        job = read(p)
        if not job:
            continue
        job["_path"] = str(p)
        status = "abandoned" if _abandoned(job) else job.get("status")
        if status == "done":
            try:
                p.unlink()
            except Exception:
                pass
        elif status in ("failed", "abandoned"):
            failed.append(p)
    for p in failed[keep_failed:]:
        try:
            p.unlink()
        except Exception:
            pass


# --- watching -----------------------------------------------------------------
# Following a job is the same act from the conversation and from the home
# screen, so it lives here, with the jobs, and both call it.

def _keyboard():
    """Keys one at a time and unechoed while a job is watched, where the
    terminal needs asking for that. Does nothing where it cannot."""
    try:
        from pragma_menu import keyboard
        return keyboard()
    except Exception:
        import contextlib
        return contextlib.nullcontext()


def stop_key() -> bool:
    """Has someone asked to stop watching? Ctrl+D, Escape or q.

    Read without waiting, because the caller is in a display loop and must not
    block on a keypress that may never come. Ctrl+C arrives as an exception
    instead and is handled where the loop is.

    On POSIX this used to answer False always: the line on the screen said
    "ctrl+D to leave it to itself" and only ctrl+C did anything.
    """
    try:
        if os.name == "nt":
            import msvcrt
            while msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b"\x04", b"\x03", b"\x1b", b"q", b"Q"):
                    return True
            return False
        import select
        if not sys.stdin.isatty():
            return False
        fd = sys.stdin.fileno()
        typed = b""
        while select.select([fd], [], [], 0)[0]:
            ch = os.read(fd, 1)
            if not ch:
                return True                 # end of input is a way of leaving
            typed += ch
            if len(typed) > 64:
                break
        # An arrow key is an escape followed by more, and is not a request to
        # leave; Escape on its own is.
        return (b"\x04" in typed or typed == b"\x1b"
                or typed.lower().strip() == b"q")
    except Exception:
        return False


def hold(text: str = "ctrl+D to go back") -> None:
    """What was watched stays on the screen until it is dismissed.

    A job followed from the home screen used to be wiped the moment it ended:
    the page noticed its own "memory is writing" line had gone stale and drew
    itself again, over the lines you were in the middle of reading.
    """
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return
    except Exception:
        return
    print(f"  \033[38;5;242m{text}\033[0m")
    try:
        from pragma_menu import read_key
    except Exception:
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            pass
        return
    try:
        with _keyboard():
            while read_key() not in ("back", "enter", "q"):
                pass
    except KeyboardInterrupt:
        pass


# --- what a job says, as it is read -------------------------------------------
# The log of a job is lines of text - "[ABSTRACTOR] 2 new beliefs" and, under
# it and indented, what it has to add - because a file a person may have to
# open should read as what happened. Drawn, it is the conversation's own
# ledger: a column of names in the accent, what each faculty did beside it,
# the one at work on a status line with its seconds, and a closing line.
#
#     giulia  a session of 2 turns · ctrl+D leaves it to itself
#
#     segmenter       2 turns, 1 worth keeping - the greeting carries nothing
#     consolidator    Agrilog delivered; never deploy on a Friday
#     reconsolidator  2 earlier memories re-read
#     abstractor      1 new belief · 1 confirmed
#                     · belief: A fixed price needs its risks named up front
#     ⠇ abstractor · distilling beliefs from the episodes  12s
#
#     ✓ 1 memory written · 96s
#
# It used to be the log itself, brackets and capitals, printed as it came:
# what a worker writes for a file is not what a person watching wants to read.

NAME = 16                        # the column a faculty's name stands in
_LINE = re.compile(r"^\[([A-Z][A-Z0-9 /]*)\]\s*(.*)$", re.DOTALL)


def entries(log) -> list[dict]:
    """A job's log as what each faculty said: {"tag", "text", "details",
    "running"}. `running` is a faculty saying what it is ABOUT to do - those
    lines end on an ellipsis - and is what the status line shows; the rest is
    what was done, and stays."""
    out: list[dict] = []
    for line in log or []:
        line = str(line)
        found = _LINE.match(line)
        if found:
            text = found.group(2).strip()
            if "\n" in text:            # a traceback: the line that names the error
                text = [part.strip() for part in text.splitlines() if part.strip()][-1]
            out.append({"tag": found.group(1).split()[0], "text": text, "details": [],
                        "running": text.endswith(("…", "..."))})
        elif out and line.strip():
            out[-1]["details"].append(line.strip())
    return out


def step_of(job: dict) -> str:
    """The faculty at work on a job and what it is doing, in one line."""
    said = entries(job.get("log"))
    if not said:
        return "starting"
    last = said[-1]
    return f"{last['tag'].lower()} · {last['text'].rstrip('.… ')}"


def _look():
    """The console, and the conversation's colours and marks for it."""
    from rich.console import Console
    from agent.harness import GLYPHS, GLYPHS_LEGACY, accent_hex
    console = Console(highlight=False)
    poor = bool(getattr(console, "legacy_windows", False))
    return console, {"accent": accent_hex(), "g": GLYPHS_LEGACY if poor else GLYPHS, "poor": poor,
                     "tones": ("", "bright_black", "bright_black") if poor else ("", "grey66", "grey42")}


def _row(look: dict, name: str, text: str, details=(), name_style: str = ""):
    """One entry: a name in its column, what it says, and under that - in the
    same column and a tone quieter - what it has to add."""
    from rich.console import Group
    from rich.table import Table
    from rich.text import Text

    def hanging(lead, body):
        # The body wraps under itself, never under what leads it in.
        grid = Table.grid(padding=0)
        grid.add_column(no_wrap=True)
        grid.add_column(overflow="fold")
        grid.add_row(lead, body)
        return grid

    rows = [hanging(Text("  " + name.ljust(NAME), style=name_style or look["accent"]),
                    Text(" ".join(str(text).split()), style=look["tones"][1]))]
    for d in details:
        rows.append(hanging(Text(" " * (2 + NAME) + look["g"]["dot"] + " ", style=look["tones"][2]),
                            Text(" ".join(str(d).split()), style=look["tones"][2])))
    return Group(*rows)


def _entry(look: dict, e: dict):
    return _row(look, e["tag"].lower(), e["text"], e["details"],
                name_style="red" if e["tag"] == "ERROR" else "")


def _seconds(job: dict, fallback: float) -> int:
    try:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        return max(0, int((datetime.strptime(job["finished"], fmt)
                           - datetime.strptime(job["started"], fmt)).total_seconds()))
    except Exception:
        return max(0, int(fallback))


def _closing(look: dict, job: dict, said: list[dict], elapsed: float, gone: bool = False):
    """How it ended, as a turn's closing line says how a turn did."""
    from rich.text import Text
    dot = look["g"]["dot"]
    state = "done" if gone else job.get("status")
    if state == "done":
        n = len(job.get("episodes") or []) if not gone else sum(
            1 for e in said if e["tag"] == "CONSOLIDATOR" and not e["running"])
        what = (f"{n} {'memory' if n == 1 else 'memories'} written" if n
                else "nothing in it was worth keeping")
        line = Text(f"  {look['g']['ok']} ", style="green")
        line.append(f"{what} {dot} {_seconds(job, elapsed)}s", style=look["tones"][2])
        return [line]
    line = Text(f"  {look['g']['bad']} ", style="red")
    line.append(f"{state} {dot} {str(job.get('error') or 'no reason recorded')[:160]}", style=look["tones"][1])
    return [line, Text(f"    the turns are still in it: {job.get('_path') or ''}", style=look["tones"][2])]


def header(project: str, note: str, also: str = "") -> None:
    """The line a job is watched under: whose memory, of what."""
    from rich.text import Text
    console, look = _look()
    line = Text("  ")
    if project:
        line.append(project + "  ", style=look["accent"])
    dot = look["g"]["dot"]
    line.append(f"{note or 'a session'} {dot} ctrl+D leaves it to itself"
                + (f" {dot} also writing: {also}" if also else ""), style=look["tones"][2])
    console.print(line)
    console.print()


def show_idle(everywhere: bool = False) -> None:
    from rich.text import Text
    console, look = _look()
    console.print(Text("  nothing in the background - "
                       + ("every memory is up to date" if everywhere else "the memory is up to date"),
                       style=look["tones"][2]))


def show_failed(found: list[tuple[str, dict]]) -> None:
    """The jobs that did not finish, and how to run one again.

    `found` is [(project or "", job)]. The command is spelled as THIS system
    spells it: the Windows one, printed on Linux, was a line nobody could
    paste.
    """
    from rich.text import Text
    console, look = _look()
    quiet = look["tones"][2]
    py = Path(sys.executable)
    try:
        py = py.relative_to(_ROOT)
    except ValueError:
        pass
    console.print(Text("  these did not finish. The turns are still in them, so they can be run again:",
                       style=look["tones"][1]))
    console.print(Text(f"    {py} {Path('tools') / 'pragma_consolidate.py'} <file>", style=quiet))
    console.print(Text(f"    from {_ROOT}", style=quiet))
    for project, job in found:
        console.print()
        when = str(job.get("finished") or job.get("started") or job.get("created") or "")
        when = when.replace("T", " ").rstrip("Z")[:16]
        dot = look["g"]["dot"]
        what = f" {dot} ".join(x for x in (project, str(job.get("note") or "a session"), when) if x)
        details = []
        if job.get("error"):
            details.append(str(job["error"])[:200])
        done = [e for e in entries(job.get("log")) if not e["running"] and e["tag"] != "ERROR"]
        if done:
            details.append(f"got as far as: {done[-1]['tag'].lower()} - {done[-1]['text'][:120]}")
        details.append(str(job.get("_path", "")))
        console.print(_row(look, str(job.get("status", "?")), what, details, name_style="red"))


def watch(path, job: dict) -> str:
    """Follow one running job the way the foreground used to read.

    The faculties are the same and they take the same minute; what changed is
    that you are no longer held there. So the log is FOLLOWED rather than
    dumped: each faculty's line appears as it finishes, and the one in flight
    is on the status line with its seconds, because forty seconds of nothing
    moving is indistinguishable from a worker that has died.

    Returns "left" when the watcher walked away, and otherwise how the job
    ended - so the caller knows whether there is an ending on the screen to
    leave standing.
    """
    # Repainting needs a terminal to repaint on. Piped to a file, a status
    # line is four hundred copies of the same sentence.
    try:
        live = sys.stdout.isatty()
    except Exception:
        live = False
    with (_keyboard() if live else _nothing()):
        return _watch(path, job, live)


def _nothing():
    import contextlib
    return contextlib.nullcontext()


def _watch(path, job: dict, live: bool) -> str:
    from rich.console import Group
    from rich.live import Live
    from rich.padding import Padding
    from rich.spinner import Spinner
    from rich.text import Text

    console, look = _look()
    dot = look["g"]["dot"]
    spinner = Spinner("line" if look["poor"] else "dots", text="", style=look["accent"])
    started = time.time()
    printed = 0                         # entries already on the screen for good
    step, since = None, time.time()     # the step in flight, and since when
    job = dict(job, _path=str(path))

    def block(label: str, embedding: str, thinking: str):
        """The status: who is at work and for how long; under it the embedding
        server when it is the one working, then the end of the reasoning."""
        spinner.update(text=Text(f"{label}  {int(time.time() - since)}s", style="bright_black"))
        under = []
        if embedding:
            under.append(Padding(Text(embedding[:max(20, console.width - 8)], style="bright_black"),
                                 (0, 0, 0, 2)))
        if thinking:
            body = Text(" ".join(thinking.split()), style=f"italic {look['tones'][2]}")
            lines = body.wrap(console, max(20, console.width - 10))
            under.append(Padding(Group(*lines[-4:]), (0, 0, 0, 4)))
        return Padding(Group(spinner, *under) if under else spinner, (0, 0, 0, 2))

    def settle(said: list[dict], out) -> None:
        nonlocal printed
        done = [e for e in said if not e["running"]]
        for e in done[printed:]:
            # What a job failed of is its closing line; said there, it is not
            # said twice.
            if e["tag"] == "ERROR" and e["text"] and e["text"] in str(job.get("error") or ""):
                continue
            out.print(_entry(look, e))
        printed = len(done)

    def follow(screen) -> tuple[str, dict, list[dict]]:
        nonlocal job, step, since
        missed = 0
        while True:
            fresh = read(path)
            if not fresh:
                # The worker finished and cleaned up after itself: a job file
                # that has gone is the success case. What it last said is
                # printed from the copy read before it went. (One empty read
                # can be the file between two writes; two are not.)
                missed += 1
                if missed >= 2:
                    said = entries(job.get("log"))
                    settle(said, screen.console if screen else console)
                    return "gone", job, said
                time.sleep(0.2)
                continue
            missed = 0
            job = dict(fresh, _path=str(path))
            said = entries(job.get("log"))
            settle(said, screen.console if screen else console)
            if job.get("status") not in ("pending", "running"):
                return str(job.get("status")), job, said
            if screen:
                at = said[-1] if said and said[-1]["running"] else None
                key = (len(said), bool(job.get("answer")))
                if key != step:
                    step, since = key, time.time()
                if at is None:
                    label = "starting" if not said else f"{said[-1]['tag'].lower()} {dot} working"
                elif job.get("answer"):
                    # What a faculty answers with is JSON for the program:
                    # that it is being written is said, the JSON is not shown.
                    label = f"{at['tag'].lower()} {dot} writing it down"
                else:
                    label = f"{at['tag'].lower()} {dot} {at['text'].rstrip('.… ')}"
                screen.update(block(label[:max(20, console.width - 12)],
                                    str(job.get("embedding") or "").replace("·", dot),
                                    "" if job.get("answer") else str(job.get("thinking") or "")))
            if stop_key():
                return "left", job, said
            time.sleep(0.25 if screen else 0.5)

    if live:
        with Live(Text(""), console=console, refresh_per_second=8, transient=True) as screen:
            how, job, said = follow(screen)
    else:
        how, job, said = follow(None)
    if how == "left":
        console.print(Text("  still working - it carries on without you.", style=look["tones"][2]))
        return "left"
    console.print()
    for line in _closing(look, job, said, time.time() - started, gone=(how == "gone")):
        console.print(line)
    return "done" if how == "gone" else how


# --- the lock -----------------------------------------------------------------

class Lock:
    """One consolidation per store at a time.

    Two of them would interleave writes to learnings.json and each would file
    the other's beliefs as its own evidence. This is not about a torn file -
    the writes are atomic now - but about two abstraction passes reading the
    same store and both deciding to add the rule they have just seen.
    """

    def __init__(self, store: Path | None = None):
        self.path = jobs_dir(store) / ".lock"
        self.held = False

    def acquire(self, wait_s: float = 900, poll_s: float = 2.0) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + wait_s
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.held = True
                return True
            except FileExistsError:
                # A lock whose owner is gone is not a lock. This is the crash
                # case, and without it one killed worker blocks the store for
                # ever.
                try:
                    owner = int(self.path.read_text(encoding="utf-8").strip() or 0)
                except Exception:
                    owner = 0
                if not alive(owner):
                    try:
                        self.path.unlink()
                    except Exception:
                        pass
                    continue
                if time.time() >= deadline:
                    return False
                time.sleep(poll_s)

    def release(self) -> None:
        if not self.held:
            return
        try:
            self.path.unlink()
        except Exception:
            pass
        self.held = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()
