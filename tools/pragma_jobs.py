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

def stop_key() -> bool:
    """Has someone asked to stop watching? Ctrl+D, Escape or q.

    Read without waiting, because the caller is in a display loop and must not
    block on a keypress that may never come. Ctrl+C arrives as an exception
    instead and is handled where the loop is.
    """
    if os.name != "nt":
        return False
    try:
        import msvcrt
        while msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch in (b"\x04", b"\x03", b"\x1b", b"q", b"Q"):
                return True
    except Exception:
        return False
    return False


def watch(path, job: dict) -> None:
    """Follow one running job the way the foreground used to read.

    The faculties are the same and they take the same minute; what changed is
    that you are no longer held there. So the log is FOLLOWED rather than
    dumped: each line appears as its faculty finishes, and the one in flight
    carries a second count, because forty seconds of nothing moving is
    indistinguishable from a worker that has died.
    """
    shown = 0
    started = time.time()
    last_len = 0
    # Repainting needs a terminal to repaint on. Piped to a file, a carriage
    # return is just a character, and the second counter would write four
    # hundred copies of the same sentence into the log.
    try:
        repaint = sys.stdout.isatty()
    except Exception:
        repaint = False
    if repaint:
        try:
            return _watch_live(path, job)
        except ImportError:
            pass
    while True:
        fresh = read(path)
        if not fresh and shown:
            # The worker finished and cleaned up after itself. A job file that
            # has gone is the success case, and the log already on screen is
            # the whole of what there was to see.
            print()
            print("  done.")
            return
        job = fresh or job
        log = job.get("log") or []
        for line in log[shown:-1] if len(log) > shown else []:
            print("\r" + " " * last_len + "\r  " + line[:100])
            last_len = 0
        shown = max(shown, len(log) - 1)
        done = job.get("status") not in ("pending", "running")
        tail = log[-1] if log else "starting"
        if done:
            if log:
                print("\r" + " " * last_len + "\r  " + log[-1][:100])
            break
        if repaint:
            row = f"  {tail[:88]}  {int(time.time() - started)}s"
            print("\r" + row.ljust(last_len), end="", flush=True)
            last_len = len(row)
        if stop_key():
            print("\r" + " " * last_len + "\r"
                  "  still working - it carries on without you.")
            return
        time.sleep(0.5)

    state = job.get("status")
    if state == "done":
        n = len(job.get("episodes") or [])
        print(f"  done - {n} episode(s) written.")
    else:
        print(f"  {state} - {str(job.get('error', ''))[:100]}")


def _watch_live(path, job: dict) -> None:
    """watch() on a terminal: the step in flight with its seconds, and under it
    the last lines of what the faculty is thinking - the same block the
    conversation draws for the agent."""
    from rich.console import Console, Group
    from rich.live import Live
    from rich.padding import Padding
    from rich.spinner import Spinner
    from rich.text import Text

    console = Console(highlight=False)
    spinner = Spinner("dots", text="")
    shown = 0
    started = time.time()

    def block(tail, thinking):
        spinner.update(text=Text(f"{tail[:88]}  {int(time.time() - started)}s", style="bright_black"))
        if not thinking:
            return spinner
        flat = Text(" ".join(thinking.split()), style="italic bright_black")
        lines = flat.wrap(console, max(20, console.width - 8))
        return Group(spinner, Padding(Group(*lines[-4:]), (0, 0, 0, 4)))

    with Live(block("starting", ""), console=console, refresh_per_second=4, transient=True) as live:
        while True:
            fresh = read(path)
            if not fresh and shown:
                live.stop()
                console.print("  done.")
                return
            job = fresh or job
            log = job.get("log") or []
            for line in log[shown:-1] if len(log) > shown else []:
                live.console.print("  " + line[:100], highlight=False)
            shown = max(shown, len(log) - 1)
            if job.get("status") not in ("pending", "running"):
                if log:
                    live.console.print("  " + log[-1][:100], highlight=False)
                break
            live.update(block(log[-1] if log else "starting", job.get("thinking") or ""))
            if stop_key():
                live.stop()
                console.print("  still working - it carries on without you.")
                return
            time.sleep(0.5)

    state = job.get("status")
    if state == "done":
        console.print(f"  done - {len(job.get('episodes') or [])} episode(s) written.")
    else:
        console.print(f"  {state} - {str(job.get('error', ''))[:100]}")


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
