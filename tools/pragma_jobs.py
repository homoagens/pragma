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
import subprocess
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
        elif status in ("failed", "abandoned", "stopped"):
            failed.append(p)
    for p in failed[keep_failed:]:
        try:
            p.unlink()
        except Exception:
            pass


# --- what a job says, as it is read -------------------------------------------
# The log of a job is lines of text - "[ABSTRACTOR] 2 new beliefs" and, under
# it and indented, what it has to add - because a file a person may have to
# open should read as what happened. Drawn, it is the conversation's own
# ledger: a column of names in the accent, what each faculty did beside it,
# the one at work on a status line with its seconds, and a closing line.
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
#
# The same lines are drawn for a job being written and for one that has ended:
# the page of a job is the job, and what can be done with it is under it.

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
    colours = console.color_system if console.is_terminal else None
    return console, {"accent": accent_hex(), "g": GLYPHS_LEGACY if poor else GLYPHS, "poor": poor,
                     "colours": "standard" if colours == "windows" else colours,
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
    # A job nobody is writing any more has no error to quote: it did not fail,
    # it was left. "no reason recorded" made that sound like a fault of the log.
    nobody = "whatever was writing it is gone" if state == "abandoned" else "no reason recorded"
    why = str(job.get("error") or nobody)[:160]
    # "stopped - stopped by hand" says it twice.
    line.append(why if state == "stopped" else f"{state} {dot} {why}", style=look["tones"][1])
    return [line, Text(f"    the turns are still in it: {job.get('_path') or ''}", style=look["tones"][2])]


def show_idle(everywhere: bool = False) -> None:
    from rich.text import Text
    console, look = _look()
    console.print(Text("  nothing in the background - "
                       + ("every memory is up to date" if everywhere else "the memory is up to date"),
                       style=look["tones"][2]))


_SPIN = ("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", "|/-\\")


def _drawn(look: dict, parts: list, width: int) -> list[str]:
    """What rich would print, as lines: the page redraws itself, and has to
    know how many lines it is made of."""
    import io
    from rich.console import Console
    out = io.StringIO()
    console = Console(file=out, force_terminal=bool(look["colours"]), color_system=look["colours"],
                      width=width, highlight=False, legacy_windows=False)
    for part in parts:
        console.print(part)
    return out.getvalue().splitlines()


class _Following:
    """One job, read again each time the page is drawn.

    The faculties are the same ones the foreground used to run, and they take
    the same minute: what each has finished stays as a line, and the one in
    flight is a status line with its seconds - forty seconds of nothing moving
    is indistinguishable from a worker that has died.
    """

    def __init__(self, path, job: dict):
        self.path = Path(path)
        self.job = dict(job, _path=str(path))
        self.gone = False               # it finished, and cleared up after itself
        self.missed = 0
        self.opened = time.time()
        self.step, self.since = None, time.time()
        self.console, self.look = _look()

    def read(self) -> dict:
        fresh = read(self.path)
        if fresh:
            self.missed, self.gone = 0, False
            self.job = dict(fresh, _path=str(self.path))
            if _abandoned(self.job):
                self.job["status"] = "abandoned"
        else:
            # A job file that has gone is the success case: the worker deletes
            # it when the memory is written. (One empty read can be the file
            # between two writes; two are not.)
            self.missed += 1
            if self.missed >= 2 and not self.gone:
                self.gone = True
                self.job.setdefault("started", "")
                self.job["finished"] = _utc()      # for the closing line's seconds
        return self.job

    def state(self) -> str:
        if self.gone:
            return "done"
        return str(self.job.get("status") or "")

    def lines(self) -> list[str]:
        from rich.text import Text
        look, job = self.look, self.job
        dot = look["g"]["dot"]
        width = max(30, self.console.width - 2)
        said = entries(job.get("log"))
        state = self.state()
        parts = []
        for e in said:
            if e["running"]:
                continue
            # What a job failed of is its closing line; said there, it is not
            # said twice.
            if e["tag"] == "ERROR" and e["text"] and e["text"] in str(job.get("error") or ""):
                continue
            parts.append(_entry(look, e))
        if state in ("pending", "running"):
            at = said[-1] if said and said[-1]["running"] else None
            key = (len(said), bool(job.get("answer")))
            if key != self.step:
                self.step, self.since = key, time.time()
            if at is None:
                label = "starting" if not said else f"{said[-1]['tag'].lower()} {dot} working"
            elif job.get("answer"):
                # What a faculty answers with is JSON for the program: that it
                # is being written is said, the JSON is not shown.
                label = f"{at['tag'].lower()} {dot} writing it down"
            else:
                label = f"{at['tag'].lower()} {dot} {at['text'].rstrip('.… ')}"
            frames = _SPIN[1] if look["poor"] else _SPIN[0]
            line = Text(f"  {frames[int(time.time() * 10) % len(frames)]} ", style=look["accent"])
            line.append(f"{label[:max(20, width - 12)]}  {int(time.time() - self.since)}s",
                        style="bright_black")
            parts.append(line)
            # Under it: the embedding server when it is the one working, then
            # the end of what the model is reasoning.
            embedding = str(job.get("embedding") or "").replace("·", dot)
            if embedding:
                parts.append(Text("    " + embedding[:max(20, width - 8)], style="bright_black"))
            thinking = "" if job.get("answer") else str(job.get("thinking") or "")
            if thinking:
                body = Text(" ".join(thinking.split()), style=f"italic {look['tones'][2]}")
                for part in body.wrap(self.console, max(20, width - 10))[-4:]:
                    parts.append(Text("      ") + part)
        else:
            if not parts and state != "done":
                parts.append(Text("  it had not got as far as saying anything", style=look["tones"][2]))
            parts.append(Text(""))
            parts += _closing(look, job, said, time.time() - self.opened, gone=self.gone)
        return _drawn(look, parts, width)


# --- starting, stopping, letting go --------------------------------------------
# A job could be watched and nothing else. One that was writing went on writing
# whatever was done to the screen it was started from - which is the point of
# running it elsewhere - and there was no way to tell it to stop short of
# finding its process by hand. One that had failed could be run again only by
# copying a command off the page.

def start(path) -> bool:
    """Start a worker on a job, detached: it outlives whoever called this.

    A job that had ended - failed, abandoned, stopped - is first marked as
    about to start. The worker takes a second or two to come up, and until it
    does the file would go on saying how the LAST attempt ended: whoever
    started it and turned to watch it was shown, at once, that it had stopped.
    """
    job = read(path)
    if job and job.get("status") not in ("pending", "running"):
        job.update(status="pending", pid=0, error="", finished="", log=[])
        write(path, job)
    worker = _ROOT / "tools" / "pragma_consolidate.py"
    exe = sys.executable
    kwargs: dict = {}
    if os.name == "nt":
        # NO WINDOW. DETACHED_PROCESS detaches the console but lets Windows
        # give a console application one of its own - a black window for the
        # length of the consolidation. pythonw.exe never allocates a console;
        # CREATE_NO_WINDOW says the same to Windows where it is missing. Its
        # own process group keeps a Ctrl+C aimed at the shell from reaching it
        # halfway through writing an episode.
        pyw = Path(exe).with_name("pythonw.exe")
        if pyw.is_file():
            exe = str(pyw)
        kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([exe, str(worker), str(path)], cwd=str(_ROOT), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True, **kwargs)
    return True


def _gone(pid: int) -> bool:
    """Whether a process has ended - counting one that has ended and is only
    waiting for its parent to notice, which os.kill still finds."""
    if not alive(pid):
        return True
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        return state == "Z"
    except Exception:
        return False


def stop(job: dict) -> bool:
    """End a job that is being written, and say so in its file.

    The worker is ended, not asked: it is in the middle of a call to the model
    that may have a minute to run, and nothing it writes is left half written
    - an episode is saved whole or not at all, and so is the job file. What
    it had not reached is still in the job, which stays: it can be written
    again later, or let go.
    """
    path = Path(job.get("_path") or "")
    try:
        pid = int(job.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid > 0 and not _gone(pid):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
            else:
                import signal
                os.kill(pid, signal.SIGTERM)
                for _ in range(30):
                    if _gone(pid):
                        break
                    time.sleep(0.1)
                else:
                    os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception:
            return False
        for _ in range(30):
            if _gone(pid):
                break
            time.sleep(0.1)
        else:
            return False
    fresh = read(path)
    if not fresh:
        return True                         # it finished and cleared up while this was being asked
    if fresh.get("status") in ("pending", "running"):
        fresh.update(status="stopped", error="stopped by hand", finished=_utc(), pid=0)
        fresh.pop("thinking", None)
        fresh.pop("answer", None)
        fresh.pop("embedding", None)
        write(path, fresh)
    # The lock it held is nobody's now. The next consolidation would find
    # that out by itself; this spares it the wait.
    lock = path.parent / ".lock"
    try:
        if pid and int(lock.read_text(encoding="utf-8").strip() or 0) == pid:
            lock.unlink()
    except Exception:
        pass
    return True


def discard(job: dict) -> bool:
    """Delete a job that is not being written: what was said in it never
    becomes memory. Nothing else refers to it."""
    if job.get("status") in ("pending", "running") and not _abandoned(job):
        return False
    try:
        Path(job["_path"]).unlink()
        return True
    except Exception:
        return False


def _sep() -> str:
    try:
        from pragma_menu import SEP
        return SEP
    except Exception:
        return " - "


def state_of(job: dict) -> str:
    """Where a job stands, in a few words, for the list."""
    state = job.get("status")
    if state == "running":
        return f"writing{_sep()}{step_of(job)}"
    if state == "pending":
        return "about to start"
    if state == "failed":
        return f"failed{_sep()}{str(job.get('error') or 'no reason recorded')[:70]}"
    if state == "abandoned":
        return f"abandoned{_sep()}whatever was writing it is gone"
    if state == "stopped":
        return "stopped by hand"
    return str(state or "?")


def _job_page(project: str, job: dict) -> str:
    """One job, as a page: what it has done so far, still being drawn while it
    is written, and under that what can be done with it.

    THE JOB IS THE PAGE. It was a list that opened onto two words - watch,
    stop - of which one opened a third screen, where the job finally was; and
    going back from there took you past both again. What it is doing is what
    someone who opens a job came to see, so that is what opening it shows.
    Stopping it, running it again and letting it go happen here, and the page
    stays: the lines above say what came of it.

    Returns what is left to say to the list it goes back to.
    """
    from pragma_menu import SEP, confirm, pick, title
    path = Path(job["_path"])
    note = str(job.get("note") or "a session")
    where = f"{project} > {note}" if project else note
    shown: dict = {}
    while True:
        following = _Following(path, job)

        def frame() -> dict:
            following.read()
            state = following.state()
            if state in ("pending", "running"):
                # `back` first, and under the cursor: Enter on a page you have
                # only just opened must not be what ends the work.
                rows = [("back", "it goes on writing without you", "back"),
                        ("stop", "end it now - what was said stays in the job, to write later or let go",
                         "stop")]
            elif state == "done":
                rows = []
            else:
                rows = [("run again", "start writing it again", "again"),
                        ("discard", "delete it - what was said in it never becomes memory", "discard")]
            shown["rows"] = rows
            return {"body": following.lines(),
                    "options": [r[0] for r in rows], "notes": [r[1] for r in rows],
                    "hint": "" if rows else "ctrl+D back"}

        title("Jobs", where)
        i = pick("", [], live=frame, every=0.1)
        job = following.job
        if i is None:
            return ""
        what = shown["rows"][i][2]
        if what == "back":
            return ""
        if what == "stop":
            fresh = read(path)
            if fresh and fresh.get("status") in ("pending", "running"):
                if not stop(dict(fresh, _path=str(path))):
                    return f"it could not be stopped{SEP}its process did not end"
        elif what == "again":
            try:
                start(path)
            except Exception as e:
                return f"could not start it{SEP}{type(e).__name__}: {str(e)[:90]}"
        elif what == "discard":
            title("Jobs", f"{where} > discard")
            if confirm("Delete it? What was said in it is lost to the memory.", "yes, delete it"):
                return "deleted." if discard(job) else "it could not be deleted"
        job = dict(read(path) or job, _path=str(path))


def manage(lister, everywhere: bool = False) -> str | None:
    """/jobs: the memory's work in the background.

    `lister()` gives [(project or "", job)]. With one job there is nothing to
    choose, and the page that opens is that job. With several it is the list
    of them, each saying where it stands and saying it again as that changes;
    Enter opens one.

    A PAGE, LIKE THE OTHERS: drawn in one place, under a head that says where
    you are. It was drawn down the screen once, each menu under the one
    before - three keys in, the list being chosen from was the fourth thing
    from the bottom and the first three were debris.

    Returns None when there was nothing to show and nothing was drawn but one
    line; otherwise the last thing it has to say - possibly nothing, "" - to
    whoever draws its own screen again in its place.
    """
    from pragma_menu import pick, say, title
    found = lister()
    if not found:
        print()
        show_idle(everywhere)
        return None
    if len(found) == 1:
        said = _job_page(*found[0])
        found = lister()
        if len(found) < 2:
            return said
    else:
        said = ""
    at = 0
    shown: dict = {"at": 0.0, "found": found}
    while True:
        if not found:
            return said or "nothing left in the background"
        title("Jobs", "what the memory is writing in the background")
        if said:
            print()
            say(f"  {said}", "dim")
            said = ""

        def frame() -> dict:
            # The files are read again once a second, not at every draw: there
            # is one per job, and from the home screen one folder per project.
            if time.time() - shown["at"] > 1.0:
                shown["found"], shown["at"] = lister(), time.time()
            now = shown["found"]
            return {"options": [project or str(job.get("note") or "a session") for project, job in now],
                    "notes": [state_of(job) for _p, job in now],
                    "hint": "" if now else "ctrl+D back"}

        shown["at"] = 0.0
        chosen = pick("", [], start=at, live=frame, every=0.5)
        found = shown["found"]
        if chosen is None:
            return ""
        at = chosen
        said = _job_page(*found[chosen])
        found = lister()


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
