# agent/server.py — FastAPI server for Pragma
#
# Architecture:
#   - Threads persisted on disk (configurable directory, default C:\tmp\Pragma)
#   - Each thread has its own cwd, conversation_history, and message list
#   - REST API for creating/listing/loading/deleting/updating threads
#   - WebSocket /ws?thread_id=XXX: activates a thread and works on it
#   - Skills that use cwd (execute_command, understand_cwd) are wrapped
#     to point to the thread's cwd, without ever doing a global os.chdir.

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── path setup ────────────────────────────────────────────────────────────────
_HERE    = Path(__file__).resolve().parent   # Pragma/agent/
_ROOT    = _HERE.parent                       # Pragma/
_CORE    = _ROOT / "core"                     # Pragma/core/  (ex agent-baseline)

for _p in [str(_CORE), str(_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# core/react.py — the generic ReAct loop (core/ is on sys.path above).
from react import AgentConfig, run_agent

import config as baseline_config
import memory as baseline_memory
from skills import ALL_SKILLS, SKILLS_SUMMARY
from agent.prompts import build_system_prompt

GEMMA_SKILLS: dict = dict(ALL_SKILLS)


# ── Storage ───────────────────────────────────────────────────────────────────
# All persistent paths come from config — one cross-platform location
# (~/.pragma by default, override with PRAGMA_DATA_DIR).

DATA_DIR    = baseline_config.DATA_DIR
THREADS_DIR = baseline_config.THREADS_DIR
THREADS_DIR.mkdir(parents=True, exist_ok=True)

# Lock for cwd operations (chdir-based skills) — serializes across agent threads
_chdir_lock = threading.Lock()
# Lock for thread file writes on disk. RLock so nested acquisitions from the
# same thread don't deadlock — needed because _persist_event_to_thread holds
# the lock while loading the thread, then calls _save_thread which also
# acquires it. Without RLock we'd deadlock; without ANY lock we'd race with
# concurrent persist_message calls and `os.replace` would fail on Windows.
_file_locks: dict[str, threading.RLock] = {}
_file_locks_master = threading.Lock()

def _lock_for(thread_id: str) -> threading.RLock:
    with _file_locks_master:
        if thread_id not in _file_locks:
            _file_locks[thread_id] = threading.RLock()
        return _file_locks[thread_id]

def _thread_path(thread_id: str) -> Path:
    return THREADS_DIR / f"{thread_id}.json"

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")

def _new_thread_data(cwd: Optional[str] = None) -> dict:
    now = _now_iso()
    return {
        "id":                   str(int(time.time() * 1000)),
        "title":                "New conversation",
        "cwd":                  cwd or os.getcwd(),
        "created_at":           now,
        "updated_at":           now,
        "messages":             [],   # events visible in the UI
        "conversation_history": [],   # coppie user/conclusion per contesto
    }

def _save_thread(data: dict) -> None:
    data["updated_at"] = _now_iso()
    tid = data["id"]
    p   = _thread_path(tid)
    tmp = p.with_suffix(".tmp")
    with _lock_for(tid):
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

def _load_thread(thread_id: str) -> Optional[dict]:
    p = _thread_path(thread_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def _list_threads() -> list[dict]:
    out = []
    files = sorted(THREADS_DIR.glob("*.json"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for p in files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "id":            data.get("id", p.stem),
                "title":         data.get("title", "Untitled"),
                "cwd":           data.get("cwd", ""),
                "created_at":    data.get("created_at", ""),
                "updated_at":    data.get("updated_at", ""),
                "message_count": len(data.get("messages", [])),
            })
        except Exception:
            continue
    return out

def _delete_thread(thread_id: str) -> bool:
    p = _thread_path(thread_id)
    if not p.exists():
        return False
    with _lock_for(thread_id):
        p.unlink()
    return True


# ── Background reflection worker ──────────────────────────────────────────────
#
# session_reflect is moved off the foreground task path: as soon as a task ends
# with a conclusion, the transcript is pushed to a global queue and the WS
# worker is freed. A single dedicated thread drains the queue one item at a
# time (FIFO), runs session_reflect, persists the events to the thread's
# message log, and — if the same thread still has an active WebSocket — pushes
# `reflection_start` / `reflection` events live so the UI can react.
#
# Why one worker, not a pool: session_reflect is a single LLM call. With
# `llama-server -np 2` the backend can serve user-facing requests concurrently
# with the reflection call, which is the speed-up the user gets. Running more
# than one reflection in parallel would compete with foreground requests for
# llama.cpp's parallel slots, defeating the point.

import queue

# {thread_id -> (asyncio loop, async_queue)} for live WS deliveries.
# Populated when a WS connects, cleared when it disconnects.
_thread_ws_registry: "dict[str, tuple[object, object]]" = {}
_thread_ws_lock = threading.Lock()

_reflection_queue: "queue.Queue[dict | None]" = queue.Queue()


def _emit_to_thread(thread_id: str, event: dict) -> None:
    """Deliver an event to the live WS of `thread_id`, if one is connected.
    Silently dropped if the thread is not currently being viewed — the event
    is persisted to disk by the caller anyway, so the user will see it on
    next thread open."""
    with _thread_ws_lock:
        target = _thread_ws_registry.get(thread_id)
    if not target:
        return
    loop, async_queue = target
    try:
        loop.call_soon_threadsafe(async_queue.put_nowait, event)
    except Exception:
        pass  # WS might have just closed


def _reflection_worker_loop() -> None:
    while True:
        item = _reflection_queue.get()
        try:
            if item is None:
                return  # shutdown sentinel
            thread_id = item["thread_id"]
            transcript = item["transcript"]
            label      = item.get("label", "")
            thread_path = item["thread_path"]

            # Notify UI that this reflection has started running (not just queued).
            start_ev = {"type": "reflection_start"}
            _persist_event_to_thread(thread_path, start_ev)
            _emit_to_thread(thread_id, start_ev)

            # Run the actual reflection (single LLM call). Use the detailed
            # variant so we can ship the persisted entries to the UI for
            # inspection (the user expands the indicator to see what was
            # actually saved).
            try:
                from skills.session_reflect.skill import session_reflect_detailed as _reflect
                res = _reflect(transcript=transcript, label=label)
                done_ev = {
                    "type":    "reflection",
                    "content": res.get("summary", ""),
                    "added":   res.get("added", []),
                }
            except Exception as e:
                done_ev = {
                    "type":    "reflection",
                    "content": f"ERROR: {e}",
                    "added":   [],
                }

            _persist_event_to_thread(thread_path, done_ev)
            _emit_to_thread(thread_id, done_ev)
        except Exception as outer:
            try:
                if baseline_config.DEBUG:
                    print(f"[reflection-worker] failure: {outer}")
            except Exception:
                pass
        finally:
            _reflection_queue.task_done()


def _persist_event_to_thread(thread_path, event: dict) -> None:
    """Append an event to the thread's JSON message log on disk.
    Hold the per-thread lock for the entire load → modify → save cycle to
    serialize with concurrent persist_message calls from the foreground
    task. Lock is an RLock so the nested acquisition inside _save_thread
    is safe."""
    try:
        from pathlib import Path as _Path
        p = _Path(thread_path)
        if not p.exists():
            return
        thread_id = p.stem
        with _lock_for(thread_id):
            data = _load_thread(thread_id)
            if data is None:
                return
            data.setdefault("messages", []).append(event)
            _save_thread(data)
    except Exception:
        pass  # never let persistence failure crash the worker


_reflection_worker_thread = threading.Thread(
    target=_reflection_worker_loop, name="reflection-worker", daemon=True,
)
_reflection_worker_thread.start()


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Pragma")

_STATIC  = _ROOT / "interface-web"

app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


def _asset_v(name: str) -> str:
    """Cache-bust version derived from the file's mtime — updates whenever
    the asset is edited, even without a server restart."""
    try:
        return str(int((_STATIC / name).stat().st_mtime))
    except Exception:
        return str(int(time.time()))


@app.get("/")
async def index():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace("/static/style.css", f"/static/style.css?v={_asset_v('style.css')}")
    html = html.replace("/static/app.js",    f"/static/app.js?v={_asset_v('app.js')}")
    return HTMLResponse(html, headers={
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma":        "no-cache",
        "Expires":       "0",
    })


# ── REST API ──────────────────────────────────────────────────────────────────

@app.post("/api/quit")
async def quit_app():
    import asyncio
    import os as _os
    asyncio.get_event_loop().call_later(0.3, lambda: _os._exit(0))
    return {"ok": True}


@app.post("/api/browse")
async def browse_folder():
    """Opens a native OS folder picker and returns the chosen path.
    Runs the tkinter dialog in a thread-pool executor so it doesn't block the event loop.
    Returns {"path": ""} if the user cancels."""
    import asyncio
    import tkinter as tk
    from tkinter import filedialog

    def _pick():
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        path = filedialog.askdirectory(title="Select working directory for this conversation")
        root.destroy()
        return path or ""

    loop = asyncio.get_event_loop()
    path = await loop.run_in_executor(None, _pick)
    return {"path": path}


@app.get("/api/config")
async def get_config():
    coding_model    = baseline_config.CODING_MODEL    or baseline_config.DEFAULT_MODEL
    coding_base_url = baseline_config.CODING_BASE_URL or baseline_config.LLM_BASE_URL
    return {
        "default_cwd": os.getcwd(),
        "data_dir":    str(DATA_DIR),
        "max_steps":   baseline_config.MAX_STEPS,
        "llm": {
            "provider":        "openai",
            "base_url":        baseline_config.LLM_BASE_URL,
            "default_model":   baseline_config.DEFAULT_MODEL,
            "coding_model":    coding_model,
            "coding_provider": "openai",
            "coding_base_url": coding_base_url,
            "coding_distinct": bool(baseline_config.CODING_MODEL),
        },
    }


# ── Settings — manage .env from the UI ───────────────────────────────────────

# Active .env path. In a source checkout it is the repo .env (dev behavior
# unchanged). In a frozen build (PyInstaller exe) _ROOT points into the temp
# extraction dir, which is wiped each run — so the persistent DATA_DIR is used
# instead, letting an uploaded .env survive across launches.
if getattr(sys, "frozen", False):
    _ENV_PATH = DATA_DIR / ".env"
else:
    _ENV_PATH = _ROOT / ".env"

def _upsert_env(env_path: Path, updates: dict) -> None:
    """Update or insert env vars in .env, preserving comments and order.
    `updates` is {key: value}. To clear a var pass an empty string.
    """
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    seen  = set()
    out   = []
    pat   = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$")
    for line in lines:
        m = pat.match(line.lstrip())
        if m and m.group(1) in updates:
            key = m.group(1)
            seen.add(key)
            out.append(f"{key}={updates[key]}")
        else:
            out.append(line)
    for key, val in updates.items():
        if key in seen:
            continue
        out.append(f"{key}={val}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _reload_config() -> None:
    """Reload .env into os.environ, then reload the config module in-place."""
    try:
        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH, override=True)
    except ImportError:
        pass
    importlib.reload(baseline_config)


# On a frozen build the bundled config.py cannot see a .env (it would look in
# the temp extraction dir). If the user has previously uploaded one to the
# persistent location, load it now so the exe starts already configured.
if getattr(sys, "frozen", False) and _ENV_PATH.exists():
    _reload_config()


def _mask(value: str) -> str:
    """Return a masked preview: empty string if no value, else last 4 chars."""
    if not value:
        return ""
    if len(value) <= 4:
        return "•" * len(value)
    return "•" * (len(value) - 4) + value[-4:]


_SENSITIVE_KEYS = {"KEY", "SECRET", "TOKEN", "PASSWORD"}

def _env_lines() -> list[str]:
    """Read .env and return active (non-comment, non-empty) lines.
    Values whose key contains a sensitive word are masked."""
    if not _ENV_PATH.exists():
        return []
    pat = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$")
    out = []
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = pat.match(stripped)
        if m:
            key, val = m.group(1), m.group(2)
            if any(s in key for s in _SENSITIVE_KEYS) and val:
                val = _mask(val)
            out.append(f"{key}={val}")
        else:
            out.append(stripped)
    return out


@app.get("/api/settings")
async def get_settings():
    return {
        "env_path":   str(_ENV_PATH),
        "env_exists": _ENV_PATH.exists(),
        "env_lines":  _env_lines(),
        "data_dir":   str(DATA_DIR),
        # kept for /api/config consumers
        "max_steps":  baseline_config.MAX_STEPS,
    }


class SettingsBody(BaseModel):
    max_steps: Optional[int] = None


@app.post("/api/settings")
async def save_settings(body: SettingsBody):
    """Only max_steps is runtime-writable. All other config lives in .env."""
    if body.max_steps is not None:
        _upsert_env(_ENV_PATH, {"MAX_STEPS": str(body.max_steps)})
        _reload_config()
    return {"ok": True}


@app.post("/api/settings/reload")
async def reload_settings():
    """Reload .env from disk into the running process."""
    _reload_config()
    return {
        "ok":       True,
        "env_path": str(_ENV_PATH),
        "env_lines": _env_lines(),
    }


class EnvUploadBody(BaseModel):
    content: str


@app.post("/api/settings/env")
async def upload_env(body: EnvUploadBody):
    """Receive the text content of a .env file the user picked via the
    browser's native file dialog, persist it to the active env path, and
    reload the config so it applies immediately."""
    try:
        _ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        _ENV_PATH.write_text(body.content, encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": str(e)}
    _reload_config()
    return {
        "ok":        True,
        "env_path":  str(_ENV_PATH),
        "env_lines": _env_lines(),
    }

@app.get("/api/learnings")
async def api_learnings():
    """
    Return the global cross-thread learnings store. Used by the UI's
    "Knowledge" tab in the settings panel. Entries are grouped by kind on
    the client side.
    """
    try:
        from pathlib import Path as _P
        import json as _json
        p = _P(baseline_config.LEARNINGS_PATH)
        if not p.exists():
            return {"path": str(p), "entries": []}
        data = _json.loads(p.read_text(encoding="utf-8"))
        return {
            "path":       str(p),
            "created_at": data.get("created_at", ""),
            "entries":    data.get("entries", []),
        }
    except Exception as e:
        raise HTTPException(500, f"Could not read learnings store: {e}")


class DeleteLearningBody(BaseModel):
    text: str


@app.post("/api/learnings/delete")
async def api_learnings_delete(body: DeleteLearningBody):
    """
    Remove a single learning entry from the store by its exact text.
    Lets the user prune obviously-bad learnings from the UI without
    editing the JSON by hand.
    """
    try:
        from pathlib import Path as _P
        import json as _json
        p = _P(baseline_config.LEARNINGS_PATH)
        if not p.exists():
            return {"removed": 0}
        data = _json.loads(p.read_text(encoding="utf-8"))
        before = len(data.get("entries", []))
        data["entries"] = [e for e in data.get("entries", [])
                           if e.get("text") != body.text]
        removed = before - len(data["entries"])
        p.write_text(_json.dumps(data, indent=2, ensure_ascii=False),
                     encoding="utf-8")
        return {"removed": removed}
    except Exception as e:
        raise HTTPException(500, f"Could not update learnings store: {e}")


_SUMMARIZE_SYSTEM = """You are summarizing what an AI coding agent has \
learned across past tasks. You receive a list of entries grouped into:
  - lessons    (facts the agent learned)
  - patterns   (preferred ways of doing things)
  - user_prefs (preferences expressed or inferred from the user)
  - mistakes   (things that went wrong and why)

Produce a concise human-readable summary in Markdown. Rules:
- One short section per category that has entries (skip empty ones).
- Use bullet points, ONE line per insight, MERGE near-duplicates.
- 3-6 bullets per category MAX. Be ruthless: skip trivia, skip anything
  already obvious to any developer.
- Italian or English, follow the entries' dominant language.
- Open with a one-sentence overall takeaway, then the sections.
- Output ONLY the Markdown — no preamble, no closing remarks."""


@app.post("/api/learnings/summarize")
async def api_learnings_summarize():
    """
    Run a single LLM call over the whole learnings store and return a
    short Markdown summary grouped by kind. Used by the "Summarize"
    button in the Knowledge tab. The detailed entries returned by
    /api/learnings remain the source of truth for what gets injected
    into prompts — this endpoint is purely for human consumption.
    """
    try:
        from pathlib import Path as _P
        import json as _json
        p = _P(baseline_config.LEARNINGS_PATH)
        if not p.exists():
            return {"summary": "_(no learnings yet)_", "count": 0}
        data = _json.loads(p.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        if not entries:
            return {"summary": "_(no learnings yet)_", "count": 0}

        # Build a compact, kind-grouped text payload.
        groups: dict[str, list[str]] = {
            "lessons": [], "patterns": [], "user_prefs": [], "mistakes": [],
        }
        for e in entries:
            kind = e.get("kind", "")
            text = (e.get("text", "") or "").strip()
            if kind in groups and text:
                groups[kind].append(text)

        lines = []
        for kind in ("lessons", "patterns", "user_prefs", "mistakes"):
            if not groups[kind]:
                continue
            lines.append(f"## {kind}")
            for t in groups[kind]:
                lines.append(f"- {t}")
            lines.append("")
        payload = "\n".join(lines).strip()

        try:
            import llm_client as _llm
            # call_llm is a BLOCKING synchronous HTTP call. If we awaited
            # nothing the asyncio event loop would freeze for the whole
            # 10-60s of the LLM round-trip, blocking every other request
            # (notably /api/settings when the user wants to reopen the
            # modal). Push it to the default thread pool instead.
            summary = await asyncio.to_thread(
                _llm.call_llm,
                messages=[
                    {"role": "system", "content": _SUMMARIZE_SYSTEM},
                    {"role": "user",   "content": payload},
                ],
                temperature=0.2,
                max_tokens=baseline_config.SKILL_MAX_TOKENS,
            )
        except Exception as e:
            raise HTTPException(500, f"Summarization LLM call failed: {e}")

        return {"summary": summary, "count": len(entries)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Could not summarize learnings: {e}")


@app.post("/api/learnings/clear")
async def api_learnings_clear():
    """
    Wipe ALL cross-thread learnings and drop a `knowledge_cleared` marker
    into every thread's message log so the user has a clear visual trace
    in each conversation that the store was emptied. Active WebSocket
    sessions also receive the marker live so the indicator appears
    immediately in the open tabs.
    """
    from pathlib import Path as _P
    import json as _json

    # 1. Clear the global learnings file.
    removed = 0
    p = _P(baseline_config.LEARNINGS_PATH)
    try:
        if p.exists():
            data = _json.loads(p.read_text(encoding="utf-8"))
            removed = len(data.get("entries", []))
            data["entries"] = []
            p.write_text(_json.dumps(data, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"Could not clear learnings store: {e}")

    # 2. Drop a `knowledge_cleared` marker into every thread on disk and
    #    push it live to any open WS.
    marker = {
        "type":    "knowledge_cleared",
        "removed": removed,
        "ts":      _now_iso(),
    }
    touched = 0
    for tp in THREADS_DIR.glob("*.json"):
        try:
            thread_id = tp.stem
            with _lock_for(thread_id):
                tdata = _load_thread(thread_id)
                if tdata is None:
                    continue
                tdata.setdefault("messages", []).append(marker)
                _save_thread(tdata)
            _emit_to_thread(thread_id, marker)
            touched += 1
        except Exception:
            continue

    return {"removed": removed, "threads_marked": touched}


@app.get("/api/threads")
async def api_list_threads():
    return {"threads": _list_threads()}

class NewThreadBody(BaseModel):
    cwd: Optional[str] = None
    title: Optional[str] = None

@app.post("/api/threads")
async def api_new_thread(body: NewThreadBody = NewThreadBody()):
    cwd = (body.cwd or "").strip()
    if cwd and not Path(cwd).is_dir():
        raise HTTPException(400, f"Not a directory: {cwd}")
    data = _new_thread_data(cwd=cwd or None)
    if body.title:
        data["title"] = body.title
    _save_thread(data)
    return data

@app.get("/api/threads/{thread_id}")
async def api_get_thread(thread_id: str):
    data = _load_thread(thread_id)
    if data is None:
        raise HTTPException(404, "Thread not found")
    return data

class PatchThreadBody(BaseModel):
    title: Optional[str] = None
    cwd:   Optional[str] = None

@app.patch("/api/threads/{thread_id}")
async def api_patch_thread(thread_id: str, body: PatchThreadBody):
    data = _load_thread(thread_id)
    if data is None:
        raise HTTPException(404, "Thread not found")
    if body.cwd is not None:
        cwd = body.cwd.strip()
        if cwd and not Path(cwd).is_dir():
            raise HTTPException(400, f"Not a directory: {cwd}")
        data["cwd"] = cwd or data.get("cwd", os.getcwd())
    if body.title is not None:
        data["title"] = body.title.strip() or data.get("title", "New conversation")
    _save_thread(data)
    return data

@app.delete("/api/threads/{thread_id}")
async def api_delete_thread(thread_id: str):
    if not _delete_thread(thread_id):
        raise HTTPException(404, "Thread not found")
    return {"ok": True}


# ── Per-thread skill wrapping ─────────────────────────────────────────────────
# Some skills (execute_command, understand_cwd) depend on cwd.
# We wrap them to use the thread's cwd, without doing a global os.chdir
# (which would break concurrency across different WebSocket connections).

def _abs_path(path: str, base: str) -> str:
    """Return an absolute path: relative paths are anchored to base."""
    p = Path(path)
    return str(p) if p.is_absolute() else str(Path(base) / path)


def _build_thread_skills(thread_cwd: str,
                         ws_ask_user,
                         stop_event=None) -> dict:
    skills = dict(GEMMA_SKILLS)
    skills["ask_user"] = ws_ask_user

    # ── execute_command: default cwd = thread_cwd + stop_event ───────────────
    original_exec = GEMMA_SKILLS.get("execute_command")
    if original_exec:
        def exec_wrapped(command: str, cwd: str = "", timeout: int = 60,
                         capture_stderr: bool = True, max_output_chars: int = 10_000):
            actual_cwd = _abs_path(cwd.strip(), thread_cwd) if cwd.strip() else thread_cwd
            return original_exec(command=command, cwd=actual_cwd, timeout=timeout,
                                 capture_stderr=capture_stderr,
                                 max_output_chars=max_output_chars,
                                 stop_event=stop_event)
        skills["execute_command"] = exec_wrapped

    # ── understand_cwd: temporary chdir so Path.cwd() returns thread_cwd ──────
    original_uc = GEMMA_SKILLS.get("understand_cwd")
    if original_uc:
        def uc_wrapped(max_depth: int = 3):
            with _chdir_lock:
                saved = os.getcwd()
                try:
                    if Path(thread_cwd).is_dir():
                        os.chdir(thread_cwd)
                    return original_uc(max_depth=max_depth)
                finally:
                    os.chdir(saved)
        skills["understand_cwd"] = uc_wrapped

    # ── Filesystem skills: resolve relative / empty paths against thread_cwd ──
    #
    # list_dir, glob_match, grep_search default to "." which would resolve
    # against os.getcwd() (the Pragma process root), NOT the user's project.
    # read_file / write_file / edit_file require explicit paths, but the model
    # sometimes passes relative names — anchor them too.

    orig_ld = GEMMA_SKILLS.get("list_dir")
    if orig_ld:
        def list_dir_wrapped(path: str = "", show_hidden: bool = False,
                             max_entries: int = 200):
            return orig_ld(path=_abs_path(path, thread_cwd) if path else thread_cwd,
                           show_hidden=show_hidden, max_entries=max_entries)
        skills["list_dir"] = list_dir_wrapped

    orig_gm = GEMMA_SKILLS.get("glob_match")
    if orig_gm:
        def glob_match_wrapped(pattern: str, base_path: str = ""):
            return orig_gm(pattern=pattern,
                           base_path=_abs_path(base_path, thread_cwd) if base_path else thread_cwd)
        skills["glob_match"] = glob_match_wrapped

    orig_gs = GEMMA_SKILLS.get("grep_search")
    if orig_gs:
        def grep_search_wrapped(pattern: str, path: str = "",
                                file_glob: str = "*", ignore_case: bool = False,
                                max_results: int = 100):
            return orig_gs(pattern=pattern,
                           path=_abs_path(path, thread_cwd) if path else thread_cwd,
                           file_glob=file_glob, ignore_case=ignore_case,
                           max_results=max_results)
        skills["grep_search"] = grep_search_wrapped

    for _name in ("read_file", "write_file", "write_file_b64",
                  "edit_file", "insert_after", "insert_before",
                  "append_file", "replace_in_file", "replace_in_file_b64",
                  "file_outline"):
        _orig = GEMMA_SKILLS.get(_name)
        if _orig:
            def _make_wrapped(fn):
                def wrapped(path: str, **kwargs):
                    return fn(path=_abs_path(path, thread_cwd), **kwargs)
                wrapped.__name__ = fn.__name__
                return wrapped
            skills[_name] = _make_wrapped(_orig)

    # ── slide_plan: anchor output_path to thread_cwd ─────────────────────────
    orig_sp = GEMMA_SKILLS.get("slide_plan")
    if orig_sp:
        def slide_plan_wrapped(topic: str, output_path: str = "slide_plan.json"):
            return orig_sp(topic=topic,
                           output_path=_abs_path(output_path, thread_cwd))
        slide_plan_wrapped.__name__ = "slide_plan"
        skills["slide_plan"] = slide_plan_wrapped

    # ── slide_plan_revise: anchor plan_path to thread_cwd ────────────────────
    orig_spr = GEMMA_SKILLS.get("slide_plan_revise")
    if orig_spr:
        def slide_plan_revise_wrapped(plan_path: str, feedback: str):
            return orig_spr(plan_path=_abs_path(plan_path, thread_cwd),
                            feedback=feedback)
        slide_plan_revise_wrapped.__name__ = "slide_plan_revise"
        skills["slide_plan_revise"] = slide_plan_revise_wrapped

    # ── slide_gen: anchor plan_path and output_dir to thread_cwd ─────────────
    orig_sg = GEMMA_SKILLS.get("slide_gen")
    if orig_sg:
        def slide_gen_wrapped(plan_path: str, output_dir: str = ".",
                              filename: str = ""):
            return orig_sg(plan_path=_abs_path(plan_path, thread_cwd),
                           output_dir=_abs_path(output_dir, thread_cwd),
                           filename=filename)
        slide_gen_wrapped.__name__ = "slide_gen"
        skills["slide_gen"] = slide_gen_wrapped

    return skills


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()

    # Thread from query string ?thread_id=XXX
    thread_id = ws.query_params.get("thread_id", "").strip()
    thread_data: Optional[dict] = _load_thread(thread_id) if thread_id else None

    if thread_data is None:
        # Implicitly create a new thread (fallback case)
        thread_data = _new_thread_data()
        _save_thread(thread_data)
        thread_id = thread_data["id"]
        # Notify the client of the new thread_id
        await ws.send_json({"type": "thread_created", "thread": thread_data})

    loop = asyncio.get_running_loop()
    async_queue: asyncio.Queue = asyncio.Queue()

    # Register this WS in the global registry so the background reflection
    # worker can deliver `reflection_start` / `reflection` events live while
    # this thread is being viewed. Cleared in the `finally` of websocket_endpoint.
    with _thread_ws_lock:
        _thread_ws_registry[thread_id] = (loop, async_queue)

    # ask_user state
    answer_event = threading.Event()
    answer_store: dict[str, str] = {"value": ""}
    pending_ask_user: Optional[dict] = None

    # Lock to prevent two concurrent tasks on the same thread
    task_running = threading.Event()
    task_stop    = threading.Event()   # set() to interrupt the running task

    def persist_message(msg: dict):
        """Append a message to the thread and save to disk."""
        thread_data["messages"].append(msg)
        _save_thread(thread_data)

    def ws_ask_user(topic: str = "", context: str = "", mode: str = "input",
                    prompt: str = "", question: str = "") -> str:
        nonlocal pending_ask_user
        # Accept common aliases for topic
        if not topic:
            topic = prompt or question
        display_question = context if context else topic
        hint             = topic   if context else ""
        ev = {
            "type":     "ask_user",
            "question": display_question,
            "hint":     hint,
            "mode":     mode,
        }
        pending_ask_user = dict(ev)
        persist_message(ev)
        loop.call_soon_threadsafe(async_queue.put_nowait, ev)

        # Poll so a stop signal (which sets answer_event without filling
        # answer_store) unblocks the wait promptly.
        answered = False
        elapsed  = 0.0
        while elapsed < 600:
            if answer_event.wait(timeout=0.5):
                answered = True
                break
            if task_stop.is_set():
                break
            elapsed += 0.5
        answer_event.clear()

        if task_stop.is_set():
            pending_ask_user = None
            return "(stopped)"
        if not answered:
            pending_ask_user = None
            return "(no response)"
        val = answer_store["value"]
        # Persisti anche la risposta (associandola all'ultimo ask_user)
        if thread_data["messages"] and thread_data["messages"][-1].get("type") == "ask_user":
            thread_data["messages"][-1]["answer"] = val
            _save_thread(thread_data)
        pending_ask_user = None
        if mode == "confirm":
            return "yes" if val.strip().lower() in ("y", "yes", "1") else "no"
        return val

    def _history_chars() -> int:
        return sum(len(h.get("user", "")) + len(h.get("conclusion", ""))
                   for h in thread_data["conversation_history"])

    def compress_history_if_needed():
        if _history_chars() <= baseline_config.HISTORY_MAX_CHARS:
            return
        ch = thread_data["conversation_history"]
        if len(ch) <= 2:
            return
        keep = 2
        old   = ch[:-keep]
        recent = ch[-keep:]
        text = "\n".join(f"User: {h['user']}\nPragma: {h['conclusion']}" for h in old)
        try:
            summary = baseline_memory.summarize(text, "conversation history")
            thread_data["conversation_history"] = [
                {"user": "[summary of previous conversation]",
                 "conclusion": summary},
                *recent,
            ]
            _save_thread(thread_data)
        except Exception:
            pass

    def _recall_learnings_block(task_text: str) -> str:
        """Pull a few relevant entries from the cross-thread learnings store
        and format them as an injection block. Pure keyword overlap; no LLM
        call. Empty string if the store is empty / unavailable."""
        try:
            from skills.recall_learnings.skill import recall_learnings as _recall
        except Exception:
            return ""
        try:
            out = _recall(query=task_text)
        except Exception:
            return ""
        if not out or out.startswith("(no learnings") or out.startswith("ERROR"):
            return ""
        return (
            "[Relevant prior learnings — short heuristics from past tasks, "
            "use only if they fit the current request]\n" + out + "\n\n"
        )

    def build_task_with_history(task_text: str) -> str:
        compress_history_if_needed()
        ch = thread_data["conversation_history"]
        learnings = _recall_learnings_block(task_text)
        if not ch:
            return learnings + task_text if learnings else task_text
        lines = []
        for h in ch:
            lines.append(f"User: {h['user']}")
            lines.append(f"Pragma: {h['conclusion']}")
        return (
            learnings +
            "[Previous conversation — use as context]\n" +
            "\n".join(lines) +
            f"\n\n[Current request]\n{task_text}"
        )

    async def relay_events():
        """Single long-lived pump for the lifetime of this WebSocket.
        Reads every event from the per-WS async queue and forwards it to
        the client. A `None` item is a sentinel meaning 'foreground task
        finished' — we emit a `done` event so the UI re-enables input,
        but we DON'T exit the loop, because background events (e.g.
        reflection_start, reflection from the consolidation worker)
        may still arrive while no foreground task is active."""
        while True:
            event = await async_queue.get()
            if event is None:
                try:
                    await ws.send_json({"type": "done"})
                except Exception:
                    return
                continue
            try:
                await ws.send_json(event)
            except Exception:
                return

    # Start the per-WS event pump once, before any task. It lives for the
    # full lifetime of the WS so background-emitted events (reflection_start,
    # reflection from the consolidation worker) reach the client even when
    # no foreground task is running.
    relay_task: Optional[asyncio.Task] = asyncio.create_task(relay_events())

    try:
        # Send initial thread state (including cwd)
        await ws.send_json({
            "type":   "thread_state",
            "thread": {
                "id":    thread_data["id"],
                "title": thread_data.get("title", ""),
                "cwd":   thread_data.get("cwd", os.getcwd()),
            },
        })

        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            mtype = msg.get("type")

            # ── Stop current task ──────────────────────────────────────────
            if mtype == "stop":
                if task_running.is_set():
                    task_stop.set()
                    # Unblock any pending ask_user so the agent thread can return
                    answer_event.set()
                continue

            # ── New task ───────────────────────────────────────────────────
            if mtype == "task":
                task_text = msg.get("content", "").strip()
                if not task_text:
                    continue
                if task_running.is_set():
                    await ws.send_json({
                        "type": "error",
                        "content": "A task is already running on this thread.",
                    })
                    continue

                # NB: the relay_task is created ONCE (below, on WS open) and
                # kept alive for the whole connection. Do NOT cancel or drain
                # it here — otherwise background events (reflection_start,
                # reflection) emitted by the consolidation worker between
                # tasks would be lost.

                answer_event.clear()
                answer_store["value"] = ""

                # Salva user message
                persist_message({"type": "user", "content": task_text})

                # Auto-title dal primo messaggio
                if thread_data.get("title", "New conversation") == "New conversation":
                    t = task_text.strip().splitlines()[0]
                    thread_data["title"] = t[:48] + ("…" if len(t) > 48 else "")
                    _save_thread(thread_data)

                task_running.set()
                task_stop.clear()   # reset any previous stop signal
                task_max_steps = int(msg.get("max_steps") or baseline_config.MAX_STEPS)

                def run_in_thread(raw_text: str = task_text,
                                  _max_steps: int = task_max_steps,
                                  _stop: threading.Event = task_stop):
                    try:
                        # Reload cwd from disk: it may have been updated
                        # via REST PATCH while this WS was already connected.
                        fresh = _load_thread(thread_id)
                        if fresh and fresh.get("cwd"):
                            thread_data["cwd"] = fresh["cwd"]

                        full_text = build_task_with_history(raw_text)
                        thread_cwd = thread_data.get("cwd") or os.getcwd()
                        coding_model = baseline_config.CODING_MODEL or baseline_config.DEFAULT_MODEL
                        system_prompt = build_system_prompt(
                            thread_cwd,
                            default_model  = baseline_config.DEFAULT_MODEL,
                            coding_model   = coding_model,
                            skills_summary = SKILLS_SUMMARY,
                        )
                        def on_token(chunk: str):
                            loop.call_soon_threadsafe(
                                async_queue.put_nowait,
                                {"type": "token", "content": chunk},
                            )

                        def on_reasoning(chunk: str):
                            # Event type is "thinking" in the UI protocol:
                            # disambiguates from the agent-level "reasoning"
                            # role (model that does reasoning vs coding).
                            # The callback keeps its name `on_reasoning`
                            # because the source channel is OpenAI/llama.cpp's
                            # `reasoning_content` SSE field.
                            loop.call_soon_threadsafe(
                                async_queue.put_nowait,
                                {"type": "thinking", "content": chunk},
                            )

                        cfg = AgentConfig(
                            name          = "Pragma",
                            system_prompt = system_prompt,
                            skills        = _build_thread_skills(thread_cwd, ws_ask_user, _stop),
                            final_keys    = ("conclusion",),
                            model         = baseline_config.DEFAULT_MODEL,
                            temperature   = 0.2,
                            max_steps     = _max_steps,
                            stop_event    = _stop,
                            on_token      = on_token,
                            on_reasoning  = on_reasoning,
                        )

                        _steps       = [0]
                        _total_chars = [0]
                        _start       = time.time()

                        def on_step(ev: dict):
                            t = ev.get("type", "")
                            if t in ("thought", "action", "observation", "final"):
                                _steps[0] = ev.get("step", _steps[0]) or _steps[0]
                                _total_chars[0] += len(ev.get("content", ""))
                                _total_chars[0] += len(str(ev.get("args", "")))
                            # Persisti tutti gli eventi tranne "start" (rumore)
                            if t != "start":
                                persist_message(ev)
                            loop.call_soon_threadsafe(async_queue.put_nowait, ev)

                        try:
                            result = run_agent(cfg, full_text, on_step=on_step)
                            if result and "conclusion" in result:
                                thread_data["conversation_history"].append({
                                    "user":       raw_text,
                                    "conclusion": result["conclusion"],
                                })
                                _save_thread(thread_data)

                                # ── Auto session_reflect (asynchronous) ──
                                # Build a compact transcript from the persisted
                                # messages of this task and PUSH it to the
                                # global reflection queue. A single dedicated
                                # background worker thread will run the actual
                                # LLM call. The user-facing task is NOT held
                                # back: as soon as we push, this worker frees
                                # the task lock and the UI can start a new task
                                # immediately. With `llama-server -np 2` the
                                # reflection runs in parallel with the user's
                                # next request. If multiple reflections are
                                # pending, they execute FIFO one at a time.
                                if getattr(baseline_config, "AUTO_REFLECT", False):
                                    try:
                                        # Take only the events of THIS task:
                                        # everything after the last "user" message.
                                        msgs = thread_data.get("messages", [])
                                        last_user_idx = max(
                                            (i for i, m in enumerate(msgs)
                                             if m.get("type") == "user"),
                                            default=-1,
                                        )
                                        task_events = msgs[last_user_idx:] if last_user_idx >= 0 else msgs
                                        # Compact representation — kind: short text
                                        transcript_parts = []
                                        for ev in task_events:
                                            t = ev.get("type", "")
                                            if t == "user":
                                                transcript_parts.append(f"USER: {ev.get('content','')}")
                                            elif t == "thought":
                                                transcript_parts.append(f"THOUGHT: {ev.get('content','')[:300]}")
                                            elif t == "action":
                                                transcript_parts.append(
                                                    f"ACTION: {ev.get('name','')}({ev.get('args','')})"[:300])
                                            elif t == "observation":
                                                transcript_parts.append(f"OBS: {ev.get('content','')[:300]}")
                                            elif t == "final":
                                                transcript_parts.append(f"FINAL: {ev.get('content','')[:300]}")
                                            elif t == "error":
                                                transcript_parts.append(f"ERROR: {ev.get('content','')[:300]}")
                                        transcript = "\n".join(transcript_parts)
                                        if transcript.strip():
                                            # Emit a "queued" event immediately so
                                            # the UI shows the indicator without
                                            # waiting for the worker to wake up.
                                            queued_ev = {"type": "reflection_queued"}
                                            persist_message(queued_ev)
                                            loop.call_soon_threadsafe(
                                                async_queue.put_nowait, queued_ev)

                                            _reflection_queue.put({
                                                "thread_id":   thread_id,
                                                "thread_path": str(_thread_path(thread_id)),
                                                "transcript":  transcript,
                                                "label":       f"thread:{thread_id}",
                                            })
                                    except Exception as _re:
                                        if baseline_config.DEBUG:
                                            print(f"[auto-reflect enqueue] failed: {_re}")

                            stats_ev = {
                                "type":    "stats",
                                "steps":   _steps[0],
                                "tokens":  _total_chars[0] // 4,
                                "elapsed": int((time.time() - _start) * 1000),
                            }
                            persist_message(stats_ev)
                            loop.call_soon_threadsafe(async_queue.put_nowait, stats_ev)
                        except Exception as e:
                            err_ev = {"type": "error", "content": str(e)}
                            persist_message(err_ev)
                            loop.call_soon_threadsafe(async_queue.put_nowait, err_ev)
                    finally:
                        loop.call_soon_threadsafe(async_queue.put_nowait, None)
                        task_running.clear()

                threading.Thread(target=run_in_thread, daemon=True).start()
                # relay_task is created once per WS (see WS open block);
                # do NOT re-create here or we'd spawn a new pump per task.

            # ── ask_user answer ─────────────────────────────────────────────
            elif mtype == "user_answer":
                answer_store["value"] = msg.get("content", "")
                answer_event.set()

            # ── Update cwd via WS (optional, convenient) ────────────────────
            elif mtype == "set_cwd":
                new_cwd = msg.get("cwd", "").strip()
                if new_cwd and Path(new_cwd).is_dir():
                    thread_data["cwd"] = new_cwd
                    _save_thread(thread_data)
                    await ws.send_json({"type": "cwd_updated", "cwd": new_cwd})
                else:
                    await ws.send_json({
                        "type": "error",
                        "content": f"Not a directory: {new_cwd}",
                    })

    except WebSocketDisconnect:
        if relay_task:
            relay_task.cancel()
    finally:
        # Stop receiving live reflection events for this thread when the
        # WS closes. The background worker will still persist them to disk.
        with _thread_ws_lock:
            current = _thread_ws_registry.get(thread_id)
            # Only remove if it's still pointing at *this* WS (another tab
            # may have reconnected on the same thread in the meantime).
            if current and current[1] is async_queue:
                _thread_ws_registry.pop(thread_id, None)
