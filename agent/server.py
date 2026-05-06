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
import importlib.util as _ilu
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

# Load core's agent.py (same name as the package → importlib)
_spec = _ilu.spec_from_file_location("_baseline_agent", str(_CORE / "agent.py"))
_mod  = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
AgentConfig = _mod.AgentConfig
run_agent   = _mod.run_agent

import config as baseline_config
import memory as baseline_memory
from skills import ALL_SKILLS, SKILLS_SUMMARY
from agent.prompts import build_system_prompt

GEMMA_SKILLS: dict = dict(ALL_SKILLS)


# ── Storage ───────────────────────────────────────────────────────────────────

def _default_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(r"C:\tmp\pragma")
    return Path.home() / ".pragma"

DATA_DIR    = Path(os.environ.get("PRAGMA_DATA_DIR", str(_default_data_dir())))
THREADS_DIR = DATA_DIR / "threads"
THREADS_DIR.mkdir(parents=True, exist_ok=True)

# Lock for cwd operations (chdir-based skills) — serializes across agent threads
_chdir_lock = threading.Lock()
# Lock for thread file writes on disk
_file_locks: dict[str, threading.Lock] = {}
_file_locks_master = threading.Lock()

def _lock_for(thread_id: str) -> threading.Lock:
    with _file_locks_master:
        if thread_id not in _file_locks:
            _file_locks[thread_id] = threading.Lock()
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


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="Pragma")

_STATIC  = _ROOT / "interface-web"
_VERSION = str(int(time.time()))

app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/")
async def index():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace("/static/style.css", f"/static/style.css?v={_VERSION}")
    html = html.replace("/static/app.js",    f"/static/app.js?v={_VERSION}")
    return HTMLResponse(html)


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
    coding_provider = baseline_config.CODING_PROVIDER or baseline_config.LLM_PROVIDER
    coding_base_url = (baseline_config.CODING_BASE_URL
                       or baseline_config.LLM_BASE_URL
                       or baseline_config.BACKEND_URL)
    return {
        "default_cwd": os.getcwd(),
        "data_dir":    str(DATA_DIR),
        "max_steps":   baseline_config.MAX_STEPS,
        "llm": {
            "provider":        baseline_config.LLM_PROVIDER,
            "base_url":        baseline_config.LLM_BASE_URL or baseline_config.BACKEND_URL,
            "default_model":   baseline_config.DEFAULT_MODEL,
            "coding_model":    coding_model,
            "coding_provider": coding_provider,
            "coding_base_url": coding_base_url,
            "coding_distinct": bool(baseline_config.CODING_MODEL),
        },
    }


# ── Settings — manage .env from the UI ───────────────────────────────────────

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

    for _name in ("read_file", "write_file", "edit_file"):
        _orig = GEMMA_SKILLS.get(_name)
        if _orig:
            def _make_wrapped(fn):
                def wrapped(path: str, **kwargs):
                    return fn(path=_abs_path(path, thread_cwd), **kwargs)
                wrapped.__name__ = fn.__name__
                return wrapped
            skills[_name] = _make_wrapped(_orig)

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

    def ws_ask_user(topic: str, context: str = "", mode: str = "input") -> str:
        nonlocal pending_ask_user
        question = context if context else topic
        hint     = topic   if context else ""
        ev = {
            "type":     "ask_user",
            "question": question,
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

    def build_task_with_history(task_text: str) -> str:
        compress_history_if_needed()
        ch = thread_data["conversation_history"]
        if not ch:
            return task_text
        lines = []
        for h in ch:
            lines.append(f"User: {h['user']}")
            lines.append(f"Pragma: {h['conclusion']}")
        return (
            "[Previous conversation — use as context]\n" +
            "\n".join(lines) +
            f"\n\n[Current request]\n{task_text}"
        )

    async def relay_events():
        while True:
            event = await async_queue.get()
            if event is None:
                try:
                    await ws.send_json({"type": "done"})
                except Exception:
                    pass
                break
            try:
                await ws.send_json(event)
            except Exception:
                break

    relay_task: Optional[asyncio.Task] = None

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

                if relay_task and not relay_task.done():
                    relay_task.cancel()

                # Drain residual queue events
                while not async_queue.empty():
                    try: async_queue.get_nowait()
                    except asyncio.QueueEmpty: break

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
                            loop.call_soon_threadsafe(
                                async_queue.put_nowait,
                                {"type": "reasoning", "content": chunk},
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
                relay_task = asyncio.create_task(relay_events())

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
