# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# pragma_consolidate.py - the consolidation worker.
#
#     python tools/pragma_consolidate.py <job.json>
#
# Runs one job filed by pragma_jobs: the segmenter decides what was worth
# keeping, the consolidator writes an episode per kept segment, the sweep and
# the abstraction pass follow. Exactly what `/exit` used to do in front of you,
# in its own process, so leaving a conversation takes as long as leaving takes.
#
# WHY A PROCESS AND NOT A THREAD. The harness is a PowerShell launcher running
# a Python conversation: when the conversation returns, the launcher redraws the
# briefing. A thread would keep the interpreter alive, and the menu would not
# come back until consolidation had finished - which is the thing being fixed.
# Detached, the conversation exits at once and the work outlives it.
#
# The consolidation itself is NOT reimplemented here: it is agent.chat's own
# _consolidate, called with a renderer that writes into the job instead of onto
# a screen. Two implementations of what becomes an episode would disagree, and
# the one running unattended is the worse one to have drift.
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "core"), str(_ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pragma_jobs as jobs       # noqa: E402


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _JobRenderer:
    """The renderer _consolidate expects, writing to the job file.

    Flushed on every line rather than at the end: the whole point is that the
    launcher can show progress while this runs, and a log written once at the
    end would show nothing until there was nothing left to show.
    """

    def __init__(self, path: Path, job: dict):
        self.path = path
        self.job = job

    def _add(self, line: str) -> None:
        self.job.setdefault("log", []).append(line)
        jobs.write(self.path, self.job)

    def faculty_running(self, tag, note):
        self._add(f"[{tag}] {note}")

    def faculty(self, tag, summary, details=None):
        self._add(f"[{tag}] {summary}")
        for d in details or []:
            self._add(f"         {d}")

    def error(self, step, content):
        self._add(f"[ERROR] {content}")


class _JobHook:
    """llm_client.STATUS_HOOK for the worker: the faculties' reasoning, into the job.

    The tail of what is being thought, at most once a second - a write is the
    whole job file - so /jobs can show it the way the conversation does. A
    reasoning that went in circles becomes a line in the log.
    """

    def __init__(self, renderer):
        self.r = renderer
        self.tail = ""
        self.said = ""
        self.written = 0.0

    def begin(self, who):
        self.tail = ""
        self.said = ""

    def tick(self, who, seconds):
        pass

    def reasoning(self, chunk, who):
        self.tail = (self.tail + chunk)[-600:]
        if time.time() - self.written >= 1.0:
            self.written = time.time()
            self.r.job["thinking"] = self.tail
            jobs.write(self.r.path, self.r.job)

    def answering(self, chunk, who):
        self.said = (self.said + chunk)[-600:]
        if time.time() - self.written >= 1.0:
            self.written = time.time()
            self.r.job["answer"] = self.said
            jobs.write(self.r.path, self.r.job)

    def end(self):
        had = self.r.job.pop("thinking", None) is not None
        had = (self.r.job.pop("answer", None) is not None) or had
        if had:
            jobs.write(self.r.path, self.r.job)
        self.tail = ""
        self.said = ""

    def looped(self, who, detail):
        self.r._add(f"[{who or 'MEMORY'}] the reasoning went in circles - asked again without thinking")


def run(path: Path) -> int:
    job = jobs.read(path)
    if not job:
        return 2
    if job.get("status") not in ("pending", "abandoned", "failed"):
        # Running, or finished successfully. Re-running one of those would
        # consolidate the same turns twice; the store's own session_id guard
        # would catch most of it, but "most" is not a thing to rely on for
        # memory.
        #
        # A FAILED job is different, and is the case /jobs tells you to run by
        # hand: nothing of it reached the store, the turns are still in it, and
        # the whole reason the file was kept is that it can be tried again.
        return 0

    store = Path(path).parent.parent
    lock = jobs.Lock(store)
    if not lock.acquire():
        job["status"] = "failed"
        job["error"] = "another consolidation held the store for too long"
        job["finished"] = _utc()
        jobs.write(path, job)
        return 1

    try:
        job["status"] = "running"
        job["pid"] = os.getpid()
        job["started"] = _utc()
        # A retry starts clean. Keeping the failed attempt's log would show
        # two runs interleaved, and the older one is exactly the part that is
        # no longer true.
        job["log"] = []
        job["error"] = ""
        jobs.write(path, job)

        # Imported here, not at the top: it pulls in the whole agent, and a
        # job that cannot even be read should fail without paying for that.
        from agent.chat import Turn, _consolidate

        turns = []
        for t in job.get("turns") or []:
            turn = Turn(t.get("text", ""))
            turn.transcript = list(t.get("transcript") or turn.transcript)
            parsed = None
            try:
                parsed = datetime.strptime(t.get("started", ""),
                                           "%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                parsed = None
            if parsed:
                turn.started = parsed.replace(tzinfo=timezone.utc)
            turns.append(turn)

        renderer = _JobRenderer(path, job)
        import llm_client
        llm_client.STATUS_HOOK = _JobHook(renderer)
        written = _consolidate(turns, Path(job.get("workspace") or os.getcwd()),
                               renderer, note=job.get("note") or "a session")
        job["episodes"] = [e.get("id", "") for e in written if e]
        job["status"] = "done"
    except Exception as e:
        job["status"] = "failed"
        job["error"] = f"{type(e).__name__}: {e}"
        job.setdefault("log", []).append("[ERROR] " + traceback.format_exc()[-800:])
    finally:
        job["finished"] = _utc()
        job["pid"] = 0
        jobs.write(path, job)
        lock.release()

    try:
        # A beat before clearing up. /jobs follows a running job by polling the
        # file twice a second, and deleting it the instant the last line is
        # written would take the last line with it - the consolidator's own
        # result, which is the one worth reading. Two seconds is nothing to a
        # process nobody is waiting for, and it makes the good path certain
        # rather than likely.
        time.sleep(2.0)
        jobs.prune(store)
    except Exception:
        pass
    return 0 if job.get("status") == "done" else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one consolidation job.")
    ap.add_argument("job", help="path to the job file")
    args = ap.parse_args()
    return run(Path(args.job))


if __name__ == "__main__":
    raise SystemExit(main())
