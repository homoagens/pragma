# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""One project, served to other programs as an OpenAI-compatible endpoint.

    python -m agent.serve --host 127.0.0.1 --port 8300

Started by `/serve` on the home screen, in the background, with the project's
environment (PRAGMA_PROJECT, PRAGMA_WORKSPACE, PRAGMA_DATA_DIR), and never by
hand in normal use. A program that talks to a model through the OpenAI chat
API - its base URL, a key, a model name - talks to this project instead and
gets the whole of Pragma: the recall before each turn, the agent and its
tools, and a memory written when the conversation ends.

ONE PROCESS, ONE PROJECT. Pragma reads its store and its workspace from the
environment, once: a process is a project, so the memory of one can never be
written into another's. A port is therefore a project too, and the model name
a program sends is not needed to choose it.

ONE CONVERSATION AT A TIME. A program sends the whole conversation with every
request. When the person's earlier messages are the ones the open
conversation has had, the request continues it; when they are not - the
program started over - the open one is closed and a new one begins. One left
idle is closed too. Closing hands the turns to the memory worker exactly as
ctrl+D does in the terminal, so the memory is written in the background.

WHAT THE PROGRAM SENDS. The last message from the person is what they said.
The program's own system messages - the slide on screen, a document - are
context for that turn only: the agent reads them, the history keeps the
person's words without them, and the memory never sees them.

WHAT GOES BACK. `content` is the answer. `reasoning_content`, while the turn
runs, says what Pragma is doing: what was recalled, the model's reasoning,
each tool and how it came out. A program that shows a "thinking" panel shows
that; one that does not, ignores it.

NOBODY TO ASK. A question in the middle of a turn has nobody to answer it, so
the agent is told to end the turn with the question; and a command that
cannot be undone (core/command_gate.py) is not run unless the project allows
it in /settings - the agent is told to ask in its reply instead.

While it runs, ~/.pragma/serve/<project>.json says so: the pid, the address,
the conversation. /serve and the home screen read it. It is removed on the
way out.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import queue
import signal
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (str(_ROOT), str(_ROOT / "core"), str(_ROOT / "terminal")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import config as baseline_config          # noqa: E402
import llm_client                          # noqa: E402
from react import AgentConfig   # noqa: E402
from tools import palette as skills_palette   # noqa: E402

from agent import conversation             # noqa: E402
from agent.prompts import build_system_prompt, project_contract, session_block   # noqa: E402

STATE_DIR = Path.home() / ".pragma" / "serve"

# A conversation nobody has written to for this long is closed and handed to
# the memory. The program may still send the next message: it opens a new one.
IDLE_MINUTES = float(os.environ.get("PRAGMA_SERVE_IDLE_MINUTES", "20") or 20)

# The program's context is capped per turn: a whole deck can be hundreds of
# kilobytes, and a window spent on it is a window the conversation does not
# have. A share of the agent's window, at about four characters a token.
CONTEXT_SHARE = 0.15
CONTEXT_CHARS = 24000

# Seconds of silence after which a comment line is sent down a stream: it is
# how a client that went away is noticed while Pragma is busy.
KEEPALIVE = 10

SERVE_POLICY = """

## Served to another program

The person is not in Pragma's terminal: another program relays their
messages and shows your reply in its own window.

- **The sentence that goes with a tool call is not shown to them.** Everything
  meant for them goes in your final reply, once.
- **A turn may begin with a block marked PROGRAM CONTEXT**: what the program
  supplies about what the person is looking at right now. Use it to answer. It
  is not something they said, and it can change from one turn to the next.
- **Nobody can answer in the middle of a turn.** To ask them something, end the
  turn with the question in your reply; the answer is their next message.
- **A command that cannot be undone is not run here** unless the project
  allows it: deleting files, pushing or discarding git history, installing
  software, anything run as administrator. If one is refused, do not do the
  same another way: say in your reply what you would run and why, and let
  them decide.
"""


def _say(line: str) -> None:
    """The log: stderr, which /serve sends to ~/.pragma/serve/<project>.log."""
    print(time.strftime("%Y-%m-%d %H:%M:%S ") + line, file=sys.stderr, flush=True)


# ── what Pragma reports while it works ───────────────────────────────────────

class Relay:
    """The renderer a served turn reports to: lines of reasoning for the program.

    File contents stay out - a tool's output is not something a person following
    along wants in a side panel - and so does the model's note before a tool
    call, which is its own business. Any call a terminal renderer would draw and
    this one has no use for is accepted and dropped.
    """

    def __init__(self):
        self.out = None                      # set for the length of a turn

    def say(self, text: str) -> None:
        if self.out is not None and text:
            self.out(text if text.endswith("\n") else text + "\n")

    def faculty_running(self, tag, note=""):
        self.say(f"[{tag}] {note}".rstrip())

    def faculty(self, tag, summary="", details=None):
        self.say(f"[{tag}] {summary}".rstrip())
        for d in details or []:
            self.say(f"    {d}")

    def action(self, step, name, args):
        parts = []
        for k, v in (args or {}).items():
            s = " ".join(str(v).split())
            parts.append(f"{k}={s[:60] + '...' if len(s) > 60 else s}")
        self.say(f"-> {name}({', '.join(parts)[:160]})")

    def observation(self, step, content, limit=0):
        s = str(content or "").strip()
        head = s.splitlines()[0] if s else ""
        if head.upper().startswith(("ERROR", "REFUSED", "FAILED")):
            self.say(f"   x {head[:160]}")
        else:
            self.say(f"   ok, {len(s)} characters")

    def error(self, step, content=""):
        self.say(f"[error] {str(content)[:300]}")

    def notice(self, step, content=""):
        self.say(f"[note] {str(content)[:300]}")

    def __getattr__(self, name):
        # thought, final, stats, conclusion, idle, status... - nothing to draw.
        return lambda *a, **k: None


def _ask_nobody(topic: str = "", context: str = "", mode: str = "input",
                prompt: str = "", question: str = "", **_ignored) -> str:
    """ask_user, where nobody can answer in the middle of a turn."""
    if mode == "confirm":
        return ("no - nobody can confirm in the middle of a turn here. Stop, and ask in "
                "your reply instead.")
    return ("The person cannot answer in the middle of your turn. End the turn now with "
            "your question as the reply, saying what you need and why in one or two "
            "sentences. Their answer will be their next message.")


def _held_unless_allowed(run, root: str):
    """execute_command, where a command that cannot be undone runs only if the
    project allows it: there is nobody to ask. The same rules as a
    conversation's (core/command_gate.py), the same patterns from /settings."""
    import functools

    import command_gate

    @functools.wraps(run)
    def gated(command: str = "", *args, **kwargs):
        allowed = conversation.project_settings().get("AllowedCommands") or []
        why = command_gate.held(command, allowed=allowed if isinstance(allowed, list) else [allowed],
                                where=str(kwargs.get("cwd") or root), root=root)
        if why:
            return ("REFUSED: this command " + why + " and cannot be undone, and nobody can "
                    "allow it from here. It was not run:\n"
                    f"  {command}\n"
                    "Do not run it, or anything that does the same, another way. Carry on "
                    "without it, and say in your reply what you would run and why.")
        return run(command, *args, **kwargs)
    return gated


# ── one conversation ──────────────────────────────────────────────────────────

class Session:
    """One conversation as a program holds it.

    The conversation itself - the recall, the turn, the context and when it
    is full, the memory at the end - is agent/conversation.py's, the same as
    the terminal's. What is here is what a program adds to it: the words it
    has sent so far, by which its next request is recognised as the same
    conversation; one turn at a time; when it was last used; and the
    program's context, cut to what the window can spare.
    """

    def __init__(self, cwd: Path, memory: bool, max_steps: int):
        self.cwd = cwd
        self.memory = memory
        self.id = uuid.uuid4().hex[:8]
        self.started = time.time()
        self.last_used = time.monotonic()
        self.lock = threading.Lock()
        self.said: list[str] = []            # the person's words, turn by turn
        self.closed = False
        self.relay = Relay()

        skills = skills_palette()
        skills["ask_user"] = _ask_nobody
        if "execute_command" in skills:
            skills["execute_command"] = _held_unless_allowed(skills["execute_command"], str(cwd))
        import mcp_client
        for note in mcp_client.offer(skills):
            _say(note)
        cfg = AgentConfig(
            name="Pragma",
            system_prompt=build_system_prompt(str(cwd), default_model=baseline_config.DEFAULT_MODEL,
                                              memory=memory)
            + SERVE_POLICY + mcp_client.prompt_block() + project_contract(cwd) + session_block(cwd),
            skills=skills,
            final_keys=("conclusion",),
            temperature=None,
            max_steps=max_steps,
        )
        self.conv = conversation.Conversation(cwd, cfg, self.relay, memory)

    @property
    def turns(self) -> list:
        return self.conv.turns

    def turn(self, text: str, context: str, out, stop: threading.Event) -> dict:
        """One turn. `out` receives the reasoning as it happens."""
        cfg = self.conv.cfg
        self.relay.out = out
        cfg.stop_event = stop
        cfg.on_reasoning = out
        try:
            # The program's context, cut to a share of the agent's window: a
            # whole deck can be hundreds of kilobytes, and a window spent on
            # it is a window the conversation does not have.
            shown = context
            if context:
                window = int(baseline_config.CONTEXT_WINDOW or 0)
                cap = max(1000, min(CONTEXT_CHARS, int(window * 4 * CONTEXT_SHARE))) if window else CONTEXT_CHARS
                shown = context[:cap]
                if len(context) > cap:
                    self.relay.say(f"[pragma] the program's context was cut from {len(context)} "
                                   f"to {cap} characters, to fit the model's window")
                    shown += "\n[... the rest was cut to fit the model's window]"
            # Counted before the turn runs: a turn that fails is still one the
            # program will send back as said, and the next request must match.
            self.said.append(text)
            done = self.conv.turn(text, context=shown)
            self.last_used = time.monotonic()
            if done.get("stopped"):
                return {"stopped": True}
            self.conv.compact_if_full()
            return {"conclusion": done["conclusion"], "forced": done["forced"]}
        finally:
            self.relay.out = None
            cfg.on_reasoning = None

    def close(self, why: str) -> None:
        """Hand what was said to the memory, as ctrl+D does in the terminal."""
        with self.lock:
            if self.closed:
                return
            self.closed = True
        _say(f"conversation {self.id} closed - {why} - {len(self.turns)} turn(s)")
        if not self.memory or not self.turns:
            return
        try:
            self.conv.close(note=f"served conversation {self.id}")
        except Exception:
            traceback.print_exc()


# ── the server ────────────────────────────────────────────────────────────────

def _text_of(content) -> str:
    """A message's text: a string, or the text parts of a content list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text", "")) for p in content
                         if isinstance(p, dict) and p.get("type") == "text")
    return ""


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, project: str, cwd: Path, key: str, memory: bool, max_steps: int):
        super().__init__(address, Handler)
        self.project = project
        self.cwd = cwd
        self.key = key
        self.memory = memory
        self.max_steps = max_steps
        self.local = address[0] in ("127.0.0.1", "localhost", "::1")
        self.conversation: Session | None = None
        self.guard = threading.Lock()
        self.online, self.detail = llm_client.ping_models()
        self.requests = 0
        self.last_request = 0.0

    @property
    def model(self) -> str:
        return f"pragma:{self.project}"

    def conversation_for(self, earlier: list[str]) -> Session:
        """The open conversation when this request continues it, or a new one."""
        with self.guard:
            c = self.conversation
            if c and not c.closed and c.said == earlier:
                return c
            if c and not c.closed:
                threading.Thread(target=c.close, args=("the program started a new one",),
                                 daemon=False).start()
            c = Session(self.cwd, self.memory, self.max_steps)
            self.conversation = c
            _say(f"conversation {c.id} opened")
            self.write_state()
            return c

    def reap(self) -> None:
        while True:
            time.sleep(30)
            with self.guard:
                c = self.conversation
                idle = time.monotonic() - c.last_used if c else 0
                if c and not c.closed and not c.lock.locked() and idle > IDLE_MINUTES * 60:
                    self.conversation = None
                    threading.Thread(target=c.close, args=(f"idle for {idle / 60:.0f} minutes",),
                                     daemon=False).start()
            self.write_state()

    def write_state(self) -> None:
        c = self.conversation
        state = {
            "pid": os.getpid(), "project": self.project,
            "host": self.server_address[0], "port": self.server_address[1],
            "started": STARTED, "requests": self.requests, "last_request": self.last_request,
            "conversation": None if not c or c.closed else {
                "id": c.id, "turns": len(c.turns), "since": c.started,
                "busy": c.lock.locked()},
        }
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = STATE_DIR / f"{self.project}.json.tmp"
            tmp.write_text(json.dumps(state), encoding="utf-8")
            tmp.replace(STATE_DIR / f"{self.project}.json")
        except OSError:
            pass


STARTED = time.time()


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "pragma"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code: int, message: str) -> None:
        self._json(code, {"error": {"message": message, "type": "pragma"}})

    def _allowed(self) -> bool:
        """The key, when one is sent, must be this project's. None sent is
        accepted on this machine only: some programs send no key to a local
        server, and none is how the address alone would be enough elsewhere."""
        auth = self.headers.get("Authorization", "")
        key = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else ""
        if key:
            return key == self.server.key
        return self.server.local or not self.server.key

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path in ("", "/health"):
            c = self.server.conversation
            return self._json(200, {"ok": True, "project": self.server.project, "pid": os.getpid(),
                                    "conversation": None if not c or c.closed else
                                    {"id": c.id, "turns": len(c.turns)}})
        if not self._allowed():
            return self._error(401, f"not the key of {self.server.model} - /serve in Pragma shows it")
        if path in ("/v1/models", "/models"):
            return self._json(200, {"object": "list", "data": [
                {"id": self.server.model, "object": "model", "owned_by": "pragma"}]})
        return self._error(404, f"no route {path}")

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        if not self._allowed():
            return self._error(401, f"not the key of {self.server.model} - /serve in Pragma shows it")
        if path not in ("/v1/chat/completions", "/chat/completions"):
            return self._error(404, f"no route {path}")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._error(400, "the request body is not JSON")
        messages = [m for m in body.get("messages") or [] if isinstance(m, dict)]
        context = "\n\n".join(_text_of(m.get("content")) for m in messages
                              if m.get("role") in ("system", "developer")).strip()
        talk = [m for m in messages if m.get("role") in ("user", "assistant")]
        if not talk or talk[-1].get("role") != "user":
            return self._error(400, "the last message must be the person's")
        text = _text_of(talk[-1].get("content")).strip()
        if not text:
            return self._error(400, "the person's message is empty")
        earlier = [_text_of(m.get("content")).strip() for m in talk[:-1] if m.get("role") == "user"]

        server = self.server
        server.requests += 1
        server.last_request = time.time()
        if not server.online:
            server.online, server.detail = llm_client.ping_models(timeout=4)
            if not server.online:
                return self._error(502, f"Pragma cannot reach its model: {str(server.detail)[:160]}")
        c = server.conversation_for(earlier)
        if not c.lock.acquire(timeout=5):
            return self._error(409, "this conversation is still answering the previous message")
        try:
            server.write_state()
            model = str(body.get("model") or server.model)
            if body.get("stream"):
                self._stream(c, model, text, context)
            else:
                self._whole(c, model, text, context)
        finally:
            c.lock.release()
            c.last_used = time.monotonic()
            server.write_state()

    def _run(self, c: Session, text: str, context: str, events: queue.Queue,
             stop: threading.Event) -> None:
        try:
            res = c.turn(text, context, lambda t: events.put(("reasoning", t)), stop)
        except Exception as e:
            traceback.print_exc()
            res = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
        events.put(("done", res))

    def _whole(self, c: Session, model: str, text: str, context: str) -> None:
        events: queue.Queue = queue.Queue()
        stop = threading.Event()
        self._run(c, text, context, events, stop)
        reasoning, res = [], {}
        while not events.empty():
            kind, data = events.get()
            if kind == "reasoning":
                reasoning.append(data)
            else:
                res = data
        if res.get("error"):
            return self._error(502, f"Pragma could not answer: {res['error']}")
        self._json(200, {
            "id": "chatcmpl-" + uuid.uuid4().hex[:24], "object": "chat.completion",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": res.get("conclusion") or "",
                                     "reasoning_content": "".join(reasoning)}}],
        })

    def _stream(self, c: Session, model: str, text: str, context: str) -> None:
        cid = "chatcmpl-" + uuid.uuid4().hex[:24]
        created = int(time.time())
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def chunk(delta: dict, finish=None) -> None:
            payload = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                       "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            self.wfile.write(("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8"))
            self.wfile.flush()

        events: queue.Queue = queue.Queue()
        stop = threading.Event()
        worker = threading.Thread(target=self._run, args=(c, text, context, events, stop), daemon=True)
        try:
            chunk({"role": "assistant"})
        except OSError:
            return
        worker.start()
        res: dict = {}
        gone = False
        while True:
            try:
                kind, data = events.get(timeout=KEEPALIVE)
            except queue.Empty:
                kind, data = "quiet", None
            try:
                if kind == "reasoning" and not gone:
                    chunk({"reasoning_content": data})
                elif kind == "quiet" and not gone:
                    # A comment line: clients ignore it, and writing it is how
                    # a closed connection is noticed while nothing else moves.
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                elif kind == "done":
                    res = data
                    break
            except OSError:
                if not gone:
                    gone = True
                    stop.set()
                    _say(f"conversation {c.id}: the program went away - the turn is stopped")
        if gone:
            return
        answer = res.get("conclusion") or ""
        if res.get("error"):
            _say(f"conversation {c.id}: the turn failed - {res['error']}")
            answer = answer or f"(Pragma could not answer: {res['error']})"
        elif res.get("stopped"):
            answer = answer or "(stopped)"
        try:
            for i in range(0, len(answer), 400):
                chunk({"content": answer[i:i + 400]})
            chunk({}, "stop")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m agent.serve",
                                 description="Serve one Pragma project as an OpenAI-compatible endpoint.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8300)
    ap.add_argument("--max-steps", type=int, default=None, help="step budget per turn")
    ap.add_argument("--no-memory", action="store_true",
                    help="the agent alone: nothing recalled, nothing written")
    args = ap.parse_args()

    project = os.environ.get("PRAGMA_PROJECT", "").strip()
    cwd = Path(os.environ.get("PRAGMA_WORKSPACE") or "").resolve()
    if not project or not cwd.is_dir():
        print("agent.serve: run it from /serve - it needs the project's environment "
              "(PRAGMA_PROJECT, PRAGMA_WORKSPACE, PRAGMA_DATA_DIR)", file=sys.stderr)
        return 2
    if _ROOT == cwd or _ROOT in cwd.parents:
        print(f"agent.serve: refusing to work inside Pragma's own source tree ({cwd})", file=sys.stderr)
        return 2
    # A command the agent runs without saying where runs here, in the
    # project's folder - as in a single task - and not in Pragma's own.
    os.chdir(cwd)
    memory = not args.no_memory
    max_steps = args.max_steps or baseline_config.MAX_STEPS
    try:
        server = Server((args.host, args.port), project, cwd,
                        os.environ.get("PRAGMA_SERVE_KEY", "").strip(), memory, max_steps)
    except OSError as e:
        print(f"agent.serve: cannot listen on {args.host}:{args.port} - {e}", file=sys.stderr)
        return 3

    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    server.write_state()
    threading.Thread(target=server.reap, daemon=True).start()
    _say(f"serving {server.model} on http://{args.host}:{args.port}/v1 - workspace {cwd} - "
         f"memory {'on' if memory else 'off'} - model "
         f"{'answers' if server.online else 'not answering: ' + str(server.detail)[:80]}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
        c = server.conversation
        if c:
            c.close("the service was stopped")
        try:
            (STATE_DIR / f"{project}.json").unlink(missing_ok=True)
        except OSError:
            pass
        llm_client.stop_everything()
        _say("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
