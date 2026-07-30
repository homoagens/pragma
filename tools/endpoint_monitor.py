# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# endpoint_monitor.py - a dashboard for OpenAI-compatible LLM endpoints.
#
# Not a Pragma tool: it knows nothing about sessions, memories or campaigns. It
# asks a server what it is and what it is doing, and shows the answers side by
# side. Any llama.cpp / LM Studio / vLLM endpoint will do.
#
# WHY IT EXISTS. The facts you need while working are spread across four URLs
# and none of them is memorable at the moment you need it: which model is really
# loaded, what sampling the server applies to a request that omits it, what the
# last request actually used, whether the thing is busy at all. Working over an
# SSH tunnel makes it worse, because every remote server arrives on the same
# local port and the address stops telling you anything.
#
# WHY IT SHOWS THREE NAMES FOR ONE MODEL. `/v1/models` reports an id, `/props`
# reports a file path and an alias, and they can disagree - a label is written
# by a human and the path is what was loaded. Collapsing them into one field
# would hide exactly the mismatch worth seeing, so all three are printed and the
# comparison is left to the reader.
#
# WHY THERE IS A HISTORY. `/slots` knows only the request it served last. Look a
# moment too late and the parameters a run used are simply gone. So every time
# the observed set changes, a line is recorded - which turns "what is it using"
# into "what has been through here".
#
# The panels are read-only: four GETs, polled on a timer, nothing that starts or
# stops anything. The test call at the bottom is the one exception, and it is
# deliberate in both directions - you type the prompt and press the button. It
# exists because "answers /props" and "is usable" are different questions, and
# only the second one matters when a campaign is about to start.
#
# It also settles an asymmetry that is otherwise invisible: leave its temperature
# field empty and the field is NOT SENT, so the server's own default applies;
# type a number and it is sent, and the server's is ignored. That is exactly how
# every client behaves, and here you can watch it happen instead of reasoning
# about it. Note that a test call costs GPU: with one slot it queues behind
# whatever is running, which is why the panel tells you when a slot is busy.

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
# gitignored: a port list is a fact about one machine, not about the project.
STATE_FILE = Path(__file__).with_name("endpoint_monitor.local.json")

# Short. A dead endpoint must not hold the refresh of the live ones, and over a
# tunnel "slow" and "gone" look the same for the first second.
TIMEOUT = 2.5

SAMPLERS = ("temperature", "top_k", "top_p", "min_p", "repeat_penalty")


def normalise(text: str) -> str:
    """Turn whatever was typed into a server root, or "" if it is not usable.

    Accepts a bare port, host:port, or a full URL with or without the /v1 the
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
        out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return out

    dgs = p.get("default_generation_settings") or {}
    params = dgs.get("params") or {}
    # The samplers sit two levels down in llama.cpp; n_ctx one level up. Looking
    # at only the outer object finds nothing and reports blanks, which reads
    # exactly like a server with no defaults.
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
                "n_ctx": slot.get("n_ctx"),
                "prompt": slot.get("n_prompt_tokens"),
                "cached": slot.get("n_prompt_tokens_cache"),
                "params": {k: _round(sp.get(k)) for k in SAMPLERS
                           if sp.get(k) is not None},
            })
    except Exception:
        pass

    # 501 means the server was started without --metrics. Saying so beats an
    # empty panel that could equally mean "idle".
    try:
        r = s.get(f"{base}/metrics", timeout=TIMEOUT)
        if r.status_code == 200:
            vals = {}
            for line in r.text.splitlines():
                if line.startswith("#") or " " not in line:
                    continue
                name, _, val = line.partition(" ")
                vals[name.split("{")[0]] = val.strip()
            out["metrics"] = vals
        else:
            out["metrics"] = False        # reachable, not enabled
    except Exception:
        out["metrics"] = None             # unknown

    return out


def render(snap: dict) -> str:
    """The snapshot as the text of one panel."""
    if not snap["up"]:
        return f"DOWN   {snap['error']}"

    busy = any(s["busy"] for s in snap["slots"])
    lines = [
        f"UP  {snap['ms']} ms   {'PROCESSING' if busy else 'idle'}",
        "",
        f"  model id     {snap['model_id'] or '-'}",
        f"  model file   {Path(snap['model_path']).name if snap['model_path'] else '-'}",
        f"  model alias  {snap['model_alias'] or '-'}",
        f"  build        {snap['build'] or '-'}",
        f"  n_ctx        {snap['n_ctx'] if snap['n_ctx'] is not None else '-'}",
        "",
        "  server defaults (apply to any field a request omits)",
        "    " + ("  ".join(f"{k} {v}" for k, v in snap["sampling"].items())
                  or "(none reported)"),
    ]
    for s in snap["slots"]:
        used = ""
        if s["prompt"] is not None:
            used = f"prompt {s['prompt']}"
            if s["cached"] is not None:
                used += f" ({s['cached']} from cache)"
        lines += ["",
                  f"  slot {s['id']}  {'PROCESSING' if s['busy'] else 'idle'}"
                  + (f"   {used}" if used else ""),
                  "    last request: "
                  + ("  ".join(f"{k} {v}" for k, v in s["params"].items())
                     or "(nothing served yet)")]
    if snap["metrics"] is False:
        lines += ["", "  /metrics not enabled - restart the server with --metrics",
                  "  for tokens/s, request counts and queue depth"]
    elif isinstance(snap["metrics"], dict):
        keep = [(k, v) for k, v in snap["metrics"].items()
                if "token" in k or "request" in k]
        if keep:
            lines += ["", "  metrics"]
            lines += [f"    {k} {v}" for k, v in keep[:8]]
    return "\n".join(lines)


def send_test(base: str, model: str, prompt: str, max_tokens: int,
              temperature: str) -> dict:
    """One chat completion. Never raises: failures become fields.

    `temperature` is a STRING on purpose. Empty means the key is left out of the
    body, which is the only way to let the server's own default apply - and the
    difference between omitting a field and sending 0.0 is not visible anywhere
    else.
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

    sent = {k: v for k, v in payload.items() if k not in ("messages",)}
    t0 = time.time()
    try:
        r = requests.post(f"{base}/v1/chat/completions", json=payload,
                          timeout=600)
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
        head = f"FAILED after {res.get('secs', 0):.1f}s   {res['error']}"
        if res.get("sent"):
            head += "\nsent: " + json.dumps(res["sent"])
        return head
    secs = res["secs"] or 0.0
    ct = res.get("completion_tokens")
    tps = f"{ct / secs:.1f} tok/s" if ct and secs > 0 else "-"
    lines = [
        f"sent: {json.dumps(res['sent'])}",
        f"      (a field absent here is decided by the server)",
        f"{secs:.1f}s   prompt {res.get('prompt_tokens', '?')} tok   "
        f"completion {ct if ct is not None else '?'} tok   {tps}   "
        f"finish_reason={res.get('finish') or '?'}",
        "",
    ]
    if res.get("reasoning"):
        lines += ["--- reasoning ---", res["reasoning"].strip(), ""]
    lines += ["--- reply ---", res.get("text", "").strip() or "(empty)"]
    return "\n".join(lines)


def signature(snap: dict) -> str:
    """What must change for the history to gain a line.

    Only the parameters actually served, and the model - not latency, not
    whether a slot happens to be busy this second, or the log would be a
    stopwatch instead of a record.
    """
    if not snap["up"]:
        return "down"
    parts = [snap["model_id"] or Path(snap["model_path"]).name]
    for s in snap["slots"]:
        parts.append(",".join(f"{k}={v}" for k, v in s["params"].items()))
    return " | ".join(parts)


class Dashboard:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("LLM endpoint monitor")
        root.geometry("760x680")

        self.results: "queue.Queue[tuple[str, dict]]" = queue.Queue()
        self.answers: "queue.Queue[dict]" = queue.Queue()
        self.snaps: dict[str, dict] = {}
        self.panels: dict[str, tuple[ttk.LabelFrame, tk.Text]] = {}
        self.last_sig: dict[str, str] = {}
        self.endpoints: list[str] = []

        bar = ttk.Frame(root, padding=8)
        bar.pack(fill="x")
        ttk.Label(bar, text="host:port").pack(side="left")
        self.entry = ttk.Entry(bar, width=26)
        self.entry.pack(side="left", padx=6)
        self.entry.insert(0, "127.0.0.1:8100")
        self.entry.bind("<Return>", lambda _e: self.add())
        ttk.Button(bar, text="Add", command=self.add).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self.refresh).pack(side="left", padx=6)
        self.auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="auto every", variable=self.auto).pack(side="left")
        self.every = ttk.Spinbox(bar, from_=1, to=120, width=4)
        self.every.set("3")
        self.every.pack(side="left", padx=(2, 2))
        ttk.Label(bar, text="s").pack(side="left")

        self.body = ttk.Frame(root, padding=(8, 0))
        self.body.pack(fill="both", expand=True)

        # --- test call: the only thing here that writes to the server -------
        test = ttk.LabelFrame(root, text="test call  (uses the GPU: queues behind "
                                         "a busy slot)", padding=6)
        test.pack(fill="both", expand=False, padx=8, pady=(8, 0))

        row = ttk.Frame(test)
        row.pack(fill="x")
        ttk.Label(row, text="to").pack(side="left")
        self.target = ttk.Combobox(row, width=28, state="readonly")
        self.target.pack(side="left", padx=(4, 10))
        ttk.Label(row, text="max_tokens").pack(side="left")
        self.maxtok = ttk.Spinbox(row, from_=1, to=4096, width=6)
        self.maxtok.set("128")
        self.maxtok.pack(side="left", padx=(4, 10))
        # Empty on purpose: an empty box means the key is not sent at all, which
        # is the only way to see what the server would do on its own.
        ttk.Label(row, text="temperature (empty = let the server decide)").pack(side="left")
        self.temp = ttk.Entry(row, width=6)
        self.temp.pack(side="left", padx=4)
        self.sendbtn = ttk.Button(row, text="Send", command=self.send)
        self.sendbtn.pack(side="left", padx=6)

        self.prompt = tk.Text(test, height=2, wrap="word", font=("Consolas", 9))
        self.prompt.pack(fill="x", pady=(6, 4))
        self.prompt.insert("1.0", "In one sentence: what model are you?")
        self.answer = tk.Text(test, height=10, wrap="word", font=("Consolas", 9),
                              state="disabled")
        self.answer.pack(fill="both", expand=True)

        hist = ttk.LabelFrame(root, text="changes seen (model or served parameters)",
                              padding=6)
        hist.pack(fill="both", expand=False, padx=8, pady=8)
        self.hist = tk.Text(hist, height=7, wrap="none",
                            font=("Consolas", 9), state="disabled")
        self.hist.pack(fill="both", expand=True)

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
        frame = ttk.LabelFrame(self.body, text=base, padding=6)
        frame.pack(fill="x", pady=4)
        box = tk.Text(frame, height=13, wrap="none", font=("Consolas", 9),
                      state="disabled", borderwidth=0)
        box.pack(fill="x")
        ttk.Button(frame, text="remove",
                   command=lambda b=base: self.remove(b)).pack(anchor="e")
        self.panels[base] = (frame, box)
        self.target["values"] = self.endpoints
        if not self.target.get():
            self.target.set(base)
        self.write(box, "(not polled yet)")
        self.save()
        self.refresh()

    def remove(self, base: str) -> None:
        if base in self.panels:
            self.panels[base][0].destroy()
            del self.panels[base]
        if base in self.endpoints:
            self.endpoints.remove(base)
        self.snaps.pop(base, None)
        self.target["values"] = self.endpoints
        if self.target.get() == base:
            self.target.set(self.endpoints[0] if self.endpoints else "")
        self.save()

    # --- polling -----------------------------------------------------------
    def refresh(self) -> None:
        """One probe per endpoint, each in its own thread.

        Threads, because a GET that waits two seconds on a tunnel would freeze
        the window; and tkinter is not thread-safe, so nothing is drawn from
        them - they only put snapshots on the queue.
        """
        for base in list(self.endpoints):
            threading.Thread(target=self._worker, args=(base,), daemon=True).start()

    def _worker(self, base: str) -> None:
        self.results.put((base, probe(base)))

    def drain(self) -> None:
        try:
            while True:
                base, snap = self.results.get_nowait()
                self.snaps[base] = snap
                if base in self.panels:
                    self.write(self.panels[base][1], render(snap))
                sig = signature(snap)
                if self.last_sig.get(base) != sig:
                    self.last_sig[base] = sig
                    self.log(base, snap, sig)
        except queue.Empty:
            pass
        try:
            while True:
                res = self.answers.get_nowait()
                self.write(self.answer, render_test(res))
                self.sendbtn.configure(state="normal", text="Send")
        except queue.Empty:
            pass
        self.root.after(200, self.drain)

    # --- the one write ------------------------------------------------------
    def send(self) -> None:
        base = self.target.get()
        if not base:
            return
        prompt = self.prompt.get("1.0", "end").strip()
        if not prompt:
            return
        try:
            mt = max(1, int(self.maxtok.get()))
        except Exception:
            mt = 128
        # The model the endpoint says it has, so the request names the truth
        # rather than a label; llama.cpp would accept anything, other servers
        # will not.
        snap = self.snaps.get(base) or {}
        model = snap.get("model_id") or snap.get("model_alias") or ""
        busy = any(s.get("busy") for s in snap.get("slots") or [])
        note = "  the slot is BUSY: this will wait for it\n\n" if busy else ""
        self.write(self.answer, note + "waiting...")
        self.sendbtn.configure(state="disabled", text="...")
        args = (base, model, prompt, mt, self.temp.get())
        threading.Thread(target=lambda: self.answers.put(send_test(*args)),
                         daemon=True).start()

    def tick(self) -> None:
        if self.auto.get():
            self.refresh()
        try:
            secs = max(1, int(self.every.get()))
        except Exception:
            secs = 3
        self.root.after(secs * 1000, self.tick)

    # --- output ------------------------------------------------------------
    @staticmethod
    def write(box: tk.Text, text: str) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    def log(self, base: str, snap: dict, sig: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        if not snap["up"]:
            line = f"{stamp}  {base}  unreachable"
        else:
            served = "  ".join(
                "  ".join(f"{k} {v}" for k, v in s["params"].items())
                for s in snap["slots"] if s["params"]) or "(nothing served yet)"
            name = snap["model_id"] or Path(snap["model_path"]).name or "?"
            line = f"{stamp}  {base}  {name}  ->  {served}"
        self.hist.configure(state="normal")
        self.hist.insert("end", line + "\n")
        self.hist.see("end")
        self.hist.configure(state="disabled")


def main() -> int:
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
