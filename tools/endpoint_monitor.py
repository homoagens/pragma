# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# endpoint_monitor.py - a dashboard for OpenAI-compatible LLM endpoints.
#
# Not a Pragma tool: it knows nothing about sessions, memories or campaigns. It
# asks a server what it is and what it is doing. Any llama.cpp / LM Studio /
# vLLM endpoint will do.
#
# WHY IT EXISTS. The facts you need while working live at four URLs and none of
# them is memorable at the moment you need it: which model is really loaded, what
# sampling the server applies to a request that omits it, what the last request
# actually used, whether the thing is busy. Over an SSH tunnel it is worse -
# every remote server arrives on the same local port, so the address stops
# identifying the machine and the model name becomes the only clue.
#
# WHAT IT DELIBERATELY DOES NOT DO: judge. The first version printed every fact
# it could find at equal weight, thirteen lines per endpoint, and the result was
# unreadable - a log pretending to be a dashboard. The fix was not to add
# cleverness but hierarchy: one headline row per endpoint, then the ONE
# comparison worth making, and everything else behind a button.
#
# THE COMPARISON IS THE DESIGN. Server defaults and last-served parameters sit on
# two adjacent rows in aligned columns, so a disagreement is visible without any
# rule deciding what counts as one. No colour, no warning, no threshold: the
# reader compares. That is on purpose - a monitor that decides for you is a
# monitor you have to argue with.
#
# The panels are read-only: four GETs on a timer. The test call at the bottom is
# the exception, and it is deliberate in both directions - you type the prompt
# and press the button. Leave its temperature box empty and the field is NOT SENT
# so the server's own default applies; type a number and it is. That asymmetry
# decides whether a client inherits a preset or overrides it, is invisible
# everywhere else, and here you can watch it happen. It costs GPU: with one slot
# it queues behind whatever is running, so the panel says when a slot is busy.

from __future__ import annotations

import json
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import ttk

import requests

# Endpoints you have typed, so they are not retyped every morning. Local and
# gitignored: a port list is a fact about one machine - and over a tunnel it is
# the tunnel's port, not the server's - never about the project.
STATE_FILE = Path(__file__).with_name("endpoint_monitor.local.json")

# Short. A dead endpoint must not hold up the refresh of the live ones, and over
# a tunnel "slow" and "gone" look the same for the first second.
TIMEOUT = 2.5

SAMPLERS = ("temperature", "top_k", "top_p", "min_p")
MONO = ("Consolas", 9)

GREEN, AMBER, RED, GREY = "#2e7d32", "#ef6c00", "#c62828", "#9e9e9e"


# ── talking to the server ────────────────────────────────────────────────────

def normalise(text: str) -> str:
    """Whatever was typed, as a server root - or "" if unusable.

    Accepts a bare port, host:port, or a full URL with or without the /v1 that
    OpenAI clients want. The root is what /props and /slots hang off; /v1 is
    added back only for the models call.
    """
    t = (text or "").strip().rstrip("/")
    if not t:
        return ""
    if t.isdigit():
        t = f"127.0.0.1:{t}"
    if not t.startswith(("http://", "https://")):
        t = "http://" + t
    if t.endswith("/v1"):
        t = t[:-3]
    return t.rstrip("/")


def _round(v):
    return round(v, 4) if isinstance(v, float) else v


def probe(base: str) -> dict:
    """One snapshot of a server. Never raises: failures become fields."""
    out = {"base": base, "up": False, "ms": None, "error": "",
           "model_id": "", "model_path": "", "model_alias": "", "build": "",
           "n_ctx": None, "sampling": {}, "slots": [], "metrics": None}
    s = requests.Session()

    t0 = time.time()
    try:
        r = s.get(f"{base}/props", timeout=TIMEOUT)
        r.raise_for_status()
        p = r.json()
        out["up"] = True
        out["ms"] = int((time.time() - t0) * 1000)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:140]}"
        return out

    # llama.cpp keeps the samplers two levels down, in
    # default_generation_settings.params, and n_ctx one level up. Reading only
    # the outer object finds nothing and reports blanks - which looks exactly
    # like a server that has no defaults.
    dgs = p.get("default_generation_settings") or {}
    params = dgs.get("params") or {}
    for k in SAMPLERS:
        for d in (params, dgs, p):
            if isinstance(d, dict) and d.get(k) is not None:
                out["sampling"][k] = _round(d[k])
                break
    for d in (dgs, p):
        if isinstance(d, dict) and d.get("n_ctx") is not None:
            out["n_ctx"] = d["n_ctx"]
            break
    out["model_path"] = str(p.get("model_path") or "")
    out["model_alias"] = str(p.get("model_alias") or "")
    out["build"] = str(p.get("build_info") or "")

    try:
        d = s.get(f"{base}/v1/models", timeout=TIMEOUT).json()
        rows = d.get("data") if isinstance(d, dict) else None
        if rows:
            out["model_id"] = str(rows[0].get("id", ""))
    except Exception:
        pass

    try:
        d = s.get(f"{base}/slots", timeout=TIMEOUT).json()
        for slot in (d if isinstance(d, list) else [d]):
            sp = slot.get("params") or slot
            out["slots"].append({
                "id": slot.get("id"),
                "busy": bool(slot.get("is_processing")),
                "prompt": slot.get("n_prompt_tokens"),
                "cached": slot.get("n_prompt_tokens_cache"),
                "params": {k: _round(sp.get(k)) for k in SAMPLERS
                           if sp.get(k) is not None},
            })
    except Exception:
        pass

    # 501 means the server was started without --metrics. Saying so beats an
    # empty panel, which could equally mean "idle".
    try:
        r = s.get(f"{base}/metrics", timeout=TIMEOUT)
        out["metrics"] = r.status_code == 200
    except Exception:
        out["metrics"] = None
    return out


def send_test(base: str, model: str, prompt: str, max_tokens: int,
              temperature: str) -> dict:
    """One chat completion. Never raises: failures become fields.

    `temperature` is a STRING on purpose. Empty means the key is left out of the
    body, which is the only way to let the server's own default apply - and the
    difference between omitting a field and sending 0.0 is visible nowhere else.
    """
    payload = {"model": model or "unknown",
               "messages": [{"role": "user", "content": prompt}],
               "max_tokens": max_tokens}
    t = (temperature or "").strip()
    if t:
        try:
            payload["temperature"] = float(t)
        except ValueError:
            return {"error": f"temperature '{t}' is not a number"}

    sent = {k: v for k, v in payload.items() if k != "messages"}
    t0 = time.time()
    try:
        r = requests.post(f"{base}/v1/chat/completions", json=payload, timeout=600)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:200]}", "sent": sent,
                "secs": time.time() - t0}
    secs = time.time() - t0
    choice = (d.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    usage = d.get("usage") or {}
    return {"sent": sent, "secs": secs,
            "text": msg.get("content") or "",
            "reasoning": msg.get("reasoning_content") or "",
            "finish": choice.get("finish_reason", ""),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens")}


def render_test(res: dict) -> str:
    if res.get("error"):
        head = f"failed after {res.get('secs', 0):.1f}s   {res['error']}"
        if res.get("sent"):
            head += "\nsent: " + json.dumps(res["sent"])
        return head
    secs = res["secs"] or 0.0
    ct = res.get("completion_tokens")
    tps = f"{ct / secs:.1f} tok/s" if ct and secs > 0 else "-"
    lines = [
        f"sent  {json.dumps(res['sent'])}",
        f"      a field absent above was decided by the server",
        f"got   {secs:.1f}s   prompt {res.get('prompt_tokens', '?')} tok   "
        f"completion {ct if ct is not None else '?'} tok   {tps}   "
        f"finish_reason={res.get('finish') or '?'}",
        "",
    ]
    if res.get("reasoning"):
        lines += ["reasoning", res["reasoning"].strip(), ""]
    lines += [res.get("text", "").strip() or "(empty reply)"]
    return "\n".join(lines)


def signature(snap: dict) -> str:
    """What must change for the log to gain a line.

    Only the model and the parameters actually served - not latency, not whether
    a slot happens to be busy this second, or the log would be a stopwatch
    instead of a record.
    """
    if not snap["up"]:
        return "down"
    parts = [snap["model_id"] or Path(snap["model_path"]).name]
    for s in snap["slots"]:
        parts.append(",".join(f"{k}={v}" for k, v in s["params"].items()))
    return " | ".join(parts)


def _row(label: str, values: dict) -> str:
    """One line of the comparison, in fixed columns so the eye can do the work."""
    cells = "".join(f"{('-' if values.get(k) is None else values[k]):>8}"
                    for k in SAMPLERS)
    return f"  {label:<11}{cells}"


# ── the window ───────────────────────────────────────────────────────────────

class Panel:
    """One endpoint: a headline, the comparison, and everything else hidden."""

    def __init__(self, parent, base: str, on_remove):
        self.base = base
        self.frame = ttk.Frame(parent, relief="groove", borderwidth=1, padding=8)
        self.frame.pack(fill="x", pady=4)

        head = ttk.Frame(self.frame)
        head.pack(fill="x")
        self.dot = tk.Canvas(head, width=12, height=12, highlightthickness=0)
        self.blob = self.dot.create_oval(2, 2, 11, 11, fill=GREY, outline="")
        self.dot.pack(side="left", padx=(0, 8))
        self.addr = ttk.Label(head, text=base, font=("Segoe UI", 10, "bold"))
        self.addr.pack(side="left")
        self.model = ttk.Label(head, text="", font=("Segoe UI", 10))
        self.model.pack(side="left", padx=12)
        self.right = ttk.Label(head, text="", foreground=GREY)
        self.right.pack(side="right")

        sub = ttk.Frame(self.frame)
        sub.pack(fill="x", pady=(2, 0))
        self.ctx = ttk.Label(sub, text="", foreground=GREY)
        self.ctx.pack(side="left")
        ttk.Button(sub, text="remove", width=8,
                   command=lambda: on_remove(base)).pack(side="right")
        self.detail_btn = ttk.Button(sub, text="details", width=8,
                                     command=self.toggle)
        self.detail_btn.pack(side="right", padx=4)

        self.table = ttk.Frame(self.frame)
        self.table.pack(fill="x", pady=(6, 0))
        self.head_l = ttk.Label(self.table, font=MONO, foreground=GREY,
                                text=_row("", {k: k.replace("temperature", "temp")
                                               for k in SAMPLERS}))
        self.head_l.pack(anchor="w")
        self.srv_l = ttk.Label(self.table, font=MONO, text="")
        self.srv_l.pack(anchor="w")
        self.last_l = ttk.Label(self.table, font=MONO, text="")
        self.last_l.pack(anchor="w")

        self.details = ttk.Frame(self.frame)
        self.details_l = ttk.Label(self.details, font=MONO, justify="left",
                                   foreground=GREY, text="")
        self.details_l.pack(anchor="w")
        self.open = False

    def toggle(self) -> None:
        self.open = not self.open
        if self.open:
            self.details.pack(fill="x", pady=(6, 0))
        else:
            self.details.pack_forget()

    def update(self, snap: dict) -> None:
        if not snap["up"]:
            self.dot.itemconfig(self.blob, fill=RED)
            self.model.configure(text="unreachable")
            self.right.configure(text="")
            self.ctx.configure(text=snap["error"])
            self.srv_l.configure(text="")
            self.last_l.configure(text="")
            self.details_l.configure(text=snap["error"])
            return

        busy = any(s["busy"] for s in snap["slots"])
        self.dot.itemconfig(self.blob, fill=AMBER if busy else GREEN)
        name = snap["model_id"] or Path(snap["model_path"]).name or "?"
        self.model.configure(text=name)
        self.right.configure(text=f"{'processing' if busy else 'idle'}"
                                  f"     {snap['ms']} ms")
        self.ctx.configure(text=f"ctx {snap['n_ctx'] if snap['n_ctx'] else '?'}")

        self.srv_l.configure(text=_row("server", snap["sampling"]))
        # The slot's own params, plus how much prompt the cache spared - the only
        # efficiency figure available without --metrics.
        if snap["slots"]:
            s = snap["slots"][0]
            note = ""
            if s["prompt"]:
                note = f"     prompt {s['prompt']}"
                if s["cached"] is not None and s["prompt"]:
                    note += f" ({100 * s['cached'] // s['prompt']}% cached)"
            self.last_l.configure(text=_row("last call", s["params"]) + note)
        else:
            self.last_l.configure(text=_row("last call", {}))

        lines = [f"model id     {snap['model_id'] or '-'}",
                 f"model file   {Path(snap['model_path']).name if snap['model_path'] else '-'}",
                 f"model alias  {snap['model_alias'] or '-'}",
                 f"build        {snap['build'] or '-'}",
                 f"slots        {len(snap['slots'])}"]
        if snap["metrics"] is False:
            lines.append("metrics      off - restart with --metrics for tokens/s")
        elif snap["metrics"]:
            lines.append("metrics      available at /metrics")
        self.details_l.configure(text="\n".join(lines))

    def destroy(self) -> None:
        self.frame.destroy()


class Dashboard:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("LLM endpoints")
        root.geometry("720x640")

        self.results: "queue.Queue[tuple[str, dict]]" = queue.Queue()
        self.answers: "queue.Queue[dict]" = queue.Queue()
        self.panels: dict[str, Panel] = {}
        self.snaps: dict[str, dict] = {}
        self.last_sig: dict[str, str] = {}
        self.endpoints: list[str] = []

        # Two tabs, because the two things are not equals. Watching is what you
        # open this for and it should be all you see; the test call is
        # occasional, writes to the server, and had no business taking a third
        # of the window while idle.
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        watch = ttk.Frame(nb)
        trial = ttk.Frame(nb, padding=8)
        nb.add(watch, text="  endpoints  ")
        nb.add(trial, text="  test call  ")

        bar = ttk.Frame(watch, padding=(0, 8))
        bar.pack(fill="x")
        self.entry = ttk.Entry(bar, width=22)
        self.entry.pack(side="left")
        self.entry.insert(0, "127.0.0.1:8100")
        self.entry.bind("<Return>", lambda _e: self.add())
        ttk.Button(bar, text="add", width=6, command=self.add).pack(side="left", padx=4)
        ttk.Button(bar, text="refresh", width=8,
                   command=self.refresh).pack(side="left")
        self.auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="auto", variable=self.auto).pack(side="left", padx=(10, 2))
        self.every = ttk.Spinbox(bar, from_=1, to=120, width=4)
        self.every.set("3")
        self.every.pack(side="left")
        ttk.Label(bar, text="s").pack(side="left", padx=(2, 0))

        self.body = ttk.Frame(watch)
        self.body.pack(fill="both", expand=True)

        log = ttk.LabelFrame(watch, text="log", padding=6)
        log.pack(fill="both", expand=False, pady=(8, 0))
        self.log_box = tk.Text(log, height=6, wrap="none", font=MONO,
                               state="disabled", borderwidth=0)
        self.log_box.pack(fill="both", expand=True)

        row = ttk.Frame(trial)
        row.pack(fill="x")
        self.target = ttk.Combobox(row, width=24, state="readonly")
        self.target.pack(side="left")
        ttk.Label(row, text="max").pack(side="left", padx=(10, 2))
        self.maxtok = ttk.Spinbox(row, from_=1, to=8192, width=6)
        self.maxtok.set("512")
        self.maxtok.pack(side="left")
        ttk.Label(row, text="temp").pack(side="left", padx=(10, 2))
        self.temp = ttk.Entry(row, width=6)
        self.temp.pack(side="left")
        self.sendbtn = ttk.Button(row, text="send", width=7, command=self.send)
        self.sendbtn.pack(side="left", padx=8)
        ttk.Button(row, text="clear", width=7,
                   command=lambda: self.write(self.answer, "")).pack(side="left")

        ttk.Label(trial, foreground=GREY,
                  text="temp empty = the field is not sent, so the server's own "
                       "default applies").pack(anchor="w", pady=(6, 0))

        self.prompt = ttk.Entry(trial, font=MONO)
        self.prompt.pack(fill="x", pady=(6, 4))
        self.prompt.insert(0, "In one sentence: what model are you?")
        self.prompt.bind("<Return>", lambda _e: self.send())
        self.answer = tk.Text(trial, wrap="word", font=MONO,
                              state="disabled", borderwidth=0)
        self.answer.pack(fill="both", expand=True)

        for e in self.load():
            self.add(e)
        if not self.endpoints:
            self.add()
        self.tick()
        self.root.after(200, self.drain)

    # --- endpoints ---------------------------------------------------------
    def load(self) -> list[str]:
        try:
            return list(json.loads(STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            return []

    def save(self) -> None:
        try:
            STATE_FILE.write_text(json.dumps(self.endpoints, indent=2),
                                  encoding="utf-8")
        except Exception:
            pass          # a monitor must not fail over its own convenience

    def add(self, text: str | None = None) -> None:
        base = normalise(text if text is not None else self.entry.get())
        if not base or base in self.endpoints:
            return
        self.endpoints.append(base)
        self.panels[base] = Panel(self.body, base, self.remove)
        self.target["values"] = self.endpoints
        if not self.target.get():
            self.target.set(base)
        self.save()
        self.refresh()

    def remove(self, base: str) -> None:
        if base in self.panels:
            self.panels.pop(base).destroy()
        if base in self.endpoints:
            self.endpoints.remove(base)
        self.snaps.pop(base, None)
        self.target["values"] = self.endpoints
        if self.target.get() == base:
            self.target.set(self.endpoints[0] if self.endpoints else "")
        self.save()

    # --- polling -----------------------------------------------------------
    def refresh(self) -> None:
        """One probe per endpoint, each on its own thread.

        Threads because a GET that waits two seconds on a tunnel would freeze
        the window; and tkinter is not thread-safe, so they draw nothing - they
        only put snapshots on the queue.
        """
        for base in list(self.endpoints):
            threading.Thread(target=lambda b=base: self.results.put((b, probe(b))),
                             daemon=True).start()

    def drain(self) -> None:
        try:
            while True:
                base, snap = self.results.get_nowait()
                self.snaps[base] = snap
                if base in self.panels:
                    self.panels[base].update(snap)
                sig = signature(snap)
                if self.last_sig.get(base) != sig:
                    self.last_sig[base] = sig
                    self.log(base, snap)
        except queue.Empty:
            pass
        try:
            while True:
                res = self.answers.get_nowait()
                self.write(self.answer, render_test(res))
                self.sendbtn.configure(state="normal", text="send")
        except queue.Empty:
            pass
        self.root.after(200, self.drain)

    def tick(self) -> None:
        if self.auto.get():
            self.refresh()
        try:
            secs = max(1, int(self.every.get()))
        except Exception:
            secs = 3
        self.root.after(secs * 1000, self.tick)

    # --- the one write ------------------------------------------------------
    def send(self) -> None:
        base = self.target.get()
        prompt = self.prompt.get().strip()
        if not base or not prompt:
            return
        try:
            mt = max(1, int(self.maxtok.get()))
        except Exception:
            mt = 512
        # The model the endpoint says it has, so the request names the truth
        # rather than a label. llama.cpp accepts anything; others do not.
        snap = self.snaps.get(base) or {}
        model = snap.get("model_id") or snap.get("model_alias") or ""
        busy = any(s.get("busy") for s in snap.get("slots") or [])
        note = "the slot is busy: this will wait for it\n\n" if busy else ""
        self.write(self.answer, note + "waiting...")
        self.sendbtn.configure(state="disabled", text="...")
        args = (base, model, prompt, mt, self.temp.get())
        threading.Thread(target=lambda: self.answers.put(send_test(*args)),
                         daemon=True).start()

    # --- output ------------------------------------------------------------
    @staticmethod
    def write(box: tk.Text, text: str) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    def log(self, base: str, snap: dict) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        if not snap["up"]:
            line = f"{stamp}  {base}  unreachable"
        else:
            served = "  ".join(
                " ".join(f"{k} {v}" for k, v in s["params"].items())
                for s in snap["slots"] if s["params"]) or "nothing served yet"
            name = snap["model_id"] or Path(snap["model_path"]).name or "?"
            line = f"{stamp}  {base}  {name}  ->  {served}"
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")


def main() -> int:
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
