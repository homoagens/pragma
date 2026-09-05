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
# The job is also the recovery path. The turns are copied into it, so a worker
# that dies leaves everything needed to run it again - and the next launch says
# so rather than losing the session quietly.
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


def listing(store: Path | None = None, limit: int = 20) -> list[dict]:
    """Newest first. Each job carries `_path`, and a dead one reads as failed.

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


def prune(store: Path | None = None, keep: int = 20) -> None:
    """Keep the last few finished jobs and drop the rest.

    They are small, but they hold the text of your turns, so they are not the
    kind of file to accumulate for ever without anyone deciding to.
    """
    d = jobs_dir(store)
    if not d.is_dir():
        return
    done = [p for p in sorted(d.glob("job_*.json"), reverse=True)
            if read(p).get("status") in ("done", "failed")]
    for p in done[keep:]:
        try:
            p.unlink()
        except Exception:
            pass


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
