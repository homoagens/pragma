# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""What a live session looks like while Pragma works.

The conversation used to be drawn by the batch renderer with the thoughts
switched off: a ruled "Step n" heading per step, the whole of every tool
output in a grey gutter, a spinner from the LLM client for each call, a
per-step token line, and the answer delivered at the end inside a panel. It
was faithful and it was a wall - forty lines of a file you did not ask to see
between your question and the reply.

This is the same information at the altitude of a terminal harness:

- ONE STATUS BLOCK while anything is running - the curator, a model call, a
  tool - saying who and for how long. While the model thinks, the last few
  lines of its reasoning are under it, wrapped at words and redrawn in place:
  readable sentences, not a window sliding over characters. It is the same
  block for every phase, which is what makes waiting legible: something is
  always moving and it always says what. When the thinking ends, one dim
  line says how long it took.
- A TOOL IS ONE LINE, and its result a few: the first lines and how much was
  left out. Errors keep more. --show-thoughts keeps everything, for the times
  the tool output is the point.
- THE ANSWER IS WRITTEN IN FRONT OF YOU, paragraph by paragraph, each one
  rendered as Markdown the moment it is complete. Not the whole reply
  re-rendered on every token, which flickers and fights the scrollback, and
  not raw text either.
- ONE LINE CLOSES THE TURN: steps, seconds, tokens, how full the context is,
  and which files were touched. The receipt, once, where a receipt belongs.
- The memory keeps its own mark. What the curator recalled is the one thing
  here no other harness has, and it is shown as such.

The renderer honours the interface agent/batch.py defines (thought, action,
observation, final, error, notice, conclusion, faculty_running, faculty,
stats), so agent/chat.py hands it to the same on_step adapter, and adds the
streaming callbacks and the status hook that make the rest possible.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time

# How much of the reasoning is shown while it is being written: the last
# THINK_LINES lines of it, wrapped to the terminal. Enough to read a thought,
# not enough to become the screen.
THINK_LINES = 4
THINK_KEEP = 2000                  # characters of reasoning kept for the panel

GLYPHS = {"prompt": "❯", "tool": "●", "out": "⎿", "fac": "◆",
          "ok": "✓", "bad": "✗", "note": "!", "dot": "·"}
GLYPHS_LEGACY = {"prompt": ">", "tool": "*", "out": "|", "fac": "+",
                 "ok": "OK", "bad": "X", "note": "!", "dot": "-"}

# Faculty colours, the same ones the batch renderer uses, so a session and a
# batch log read alike: the sequence curator -> agent -> consolidator ->
# abstractor is a sequence of hues before it is a sequence of words.
FACULTY_COLOR = {
    "CURATOR": "magenta", "AGENT": "cyan", "CONSOLIDATOR": "green",
    "ABSTRACTOR": "blue", "RECONSOLIDATOR": "bright_magenta",
    "FORGETTING": "yellow", "SEGMENTER": "bright_cyan", "COMPACTOR": "bright_black",
}

# Notes the native channel writes when the model said nothing before a call.
_PLACEHOLDER_NOTE = re.compile(r"^\s*(Calling \S+\.|\(batched with step above\).*|\(no tool called\))\s*$")
_TOOLS_REQUESTED = re.compile(r"\[\d+ (read-only )?tools requested;[^\]]*\]")


def accent_hex() -> str:
    """PRAGMA_ACCENT ("R;G;B", set by the launcher) as a rich colour."""
    raw = (os.environ.get("PRAGMA_ACCENT") or "178;132;255").strip()
    parts = raw.split(";")
    if len(parts) != 3 or not all(p.isdigit() and int(p) < 256 for p in parts):
        parts = ["178", "132", "255"]
    return "#{:02x}{:02x}{:02x}".format(*(int(p) for p in parts))


def fold(content: str, width: int, verbose: bool = False) -> list[str]:
    """A tool's output as the lines worth a glance.

    The first few lines and a count of the rest. An error keeps more, because
    an error is the one output someone will actually read. Verbose keeps
    everything, within reason. Every line is clipped to the width, since a
    minified file on one line is still one line.
    """
    text = content if isinstance(content, str) else str(content)
    lines = text.splitlines() or [""]
    error = text.lstrip().upper().startswith("ERROR")
    limit = 400 if verbose else (12 if error else 4)
    if len(lines) <= max(limit, 6) and not verbose:
        limit = len(lines)
    room = max(20, width - 6)
    shown = [(ln if len(ln) <= room else ln[:room - 1] + "…") for ln in lines[:limit]]
    left = len(lines) - len(shown)
    if left > 0:
        shown.append(f"… +{left} line(s), {len(text):,} chars")
    return shown


def summary_line(steps: int, tools: int, seconds: float, out_tokens: int,
                 ctx_pct: int | None, touched: list[str], dot: str) -> str:
    parts = [f"{steps} step(s)" if steps != 1 else "1 step"]
    if tools:
        parts.append(f"{tools} tool(s)" if tools != 1 else "1 tool")
    parts.append(f"{seconds:.0f}s")
    if out_tokens:
        parts.append(f"{out_tokens / 1000:.1f}k tok" if out_tokens >= 1000 else f"{out_tokens} tok")
    if ctx_pct is not None:
        parts.append(f"ctx {ctx_pct}%" if ctx_pct else "ctx <1%")
    if touched:
        names = ", ".join(touched[:3]) + (f" +{len(touched) - 3}" if len(touched) > 3 else "")
        parts.append(f"touched {names}")
    return f" {dot} ".join(parts)


def toolbar(state: dict) -> list:
    """The line under the prompt, as prompt_toolkit formatted text.

    The things that change while you type nothing: which project, which
    model, how full the context is, whether the memory is on, how many turns
    so far, and whether a consolidation is being written right now.
    """
    dot = ("class:toolbar.dim", "  ·  ")
    out = [("class:toolbar", f" {state.get('project') or 'no project'}")]
    model = state.get("model")
    if model:
        out += [dot, ("class:toolbar.dim", str(model)[:40])]
    ctx = state.get("ctx")
    if ctx is not None:
        style = "class:toolbar.warn" if ctx >= 80 else "class:toolbar.dim"
        out += [dot, (style, f"ctx {ctx}%")]
    out += [dot, ("class:toolbar.dim", "memory on" if state.get("memory") else "memory off")]
    turns = state.get("turns") or 0
    out += [dot, ("class:toolbar.dim", f"{turns} turn(s)" if turns != 1 else "1 turn")]
    writing = state.get("writing")
    if writing:
        out += [dot, ("class:toolbar.warn", f"writing {writing}")]
    return out


def prompt_style():
    """The prompt_toolkit style: a quiet toolbar, the accent for what matters."""
    from prompt_toolkit.styles import Style
    return Style.from_dict({
        "bottom-toolbar": "noreverse",
        "toolbar": f"{accent_hex()} bold",
        "toolbar.dim": "#808080",
        "toolbar.warn": "#d7af00",
    })


class _AnswerStream:
    """The reply as the model writes it, one finished paragraph at a time.

    The paragraph in progress is shown as plain text in a live region; when a
    blank line closes it - outside a code fence - it is printed above the
    region as rendered Markdown and stays there. Re-rendering the whole reply
    on every token was the alternative, and past one screen of text it
    fights the terminal's scrollback.
    """

    def __init__(self, console, legacy: bool):
        from rich.live import Live
        from rich.text import Text
        self.console = console
        self.buf = ""
        self.chars = 0
        self._text = Text
        self.live = Live(Text(""), console=console, refresh_per_second=12,
                         transient=True, vertical_overflow="visible")
        self.live.start()

    def feed(self, chunk: str) -> None:
        self.chars += len(chunk)
        self.buf += chunk
        done, rest = self._split(self.buf)
        for paragraph in done:
            self._render(paragraph)
        self.buf = rest
        tail = rest.splitlines()[-12:]
        self.live.update(self._text("\n".join(tail)))

    def close(self) -> None:
        try:
            self.live.stop()
        except Exception:
            pass
        if self.buf.strip():
            self._render(self.buf)
        self.buf = ""

    def _render(self, paragraph: str) -> None:
        from rich.markdown import Markdown
        if not paragraph.strip():
            return
        self.console.print(Markdown(paragraph.strip("\n")))

    @staticmethod
    def _split(text: str) -> tuple[list[str], str]:
        """(finished paragraphs, the rest): blank lines outside fences split."""
        done: list[str] = []
        current: list[str] = []
        fence = False
        lines = text.split("\n")
        for i, line in enumerate(lines[:-1]):          # the last piece may be unfinished
            if line.strip().startswith("```"):
                fence = not fence
            if not line.strip() and not fence:
                if current:
                    done.append("\n".join(current))
                    current = []
                continue
            current.append(line)
        rest = "\n".join(current + [lines[-1]])
        return done, rest


class Harness:
    """The renderer for a live session. See the module docstring."""

    def __init__(self, console=None, verbose: bool = False, context_window: int = 0):
        from rich.console import Console
        self.console = console or Console(highlight=False)
        self.verbose = verbose
        self.window = int(context_window or 0)
        self.legacy = bool(getattr(self.console, "legacy_windows", False))
        self.g = GLYPHS_LEGACY if self.legacy else GLYPHS
        self.accent = accent_hex()
        self._lock = threading.RLock()
        self._status = None
        self._spinner = None
        self._label = ""
        self._since = 0.0
        self._tail = ""                 # the reasoning, as one flowing paragraph
        self._said = ""                 # a faculty's answer while it is written
        self._reasoning = ""            # the whole of it, kept only when verbose
        self._think_chars = 0
        self._think_since = 0.0
        self._last_draw = 0.0
        self._answer: _AnswerStream | None = None
        self._boundary = True
        self._call = {"streamed": 0}
        self._note = ""
        self._paused_label = ""
        self._turn: dict = {}
        self.turn_begin()
        self._ticking = True
        threading.Thread(target=self._tick, daemon=True).start()

    # ── the status line ────────────────────────────────────────────────────

    def _show(self, label: str) -> None:
        with self._lock:
            if self._answer is not None:
                return                      # the answer itself is the progress
            changed = label != self._label
            if changed:
                self._label = label
                self._since = time.monotonic()
            if self._status is None:
                try:
                    from rich.live import Live
                    self._status = Live(self._renderable(), console=self.console,
                                        refresh_per_second=8, transient=True)
                    self._status.start()
                    self._last_draw = time.monotonic()
                except Exception:
                    self._status = None
            elif changed:
                self._redraw()

    def _hide(self) -> None:
        with self._lock:
            if self._status is not None:
                try:
                    self._status.stop()
                except Exception:
                    pass
                self._status = None
            self._spinner = None
            self._label = ""
            self._tail = ""
            self._said = ""

    def _redraw(self) -> None:
        if self._status is not None:
            try:
                self._status.update(self._renderable())
            except Exception:
                pass
        self._last_draw = time.monotonic()

    def _renderable(self):
        """The block: a spinner line saying who and for how long, and under it
        the last lines of the reasoning while there is any."""
        from rich.console import Group
        from rich.padding import Padding
        from rich.spinner import Spinner
        from rich.text import Text
        secs = int(time.monotonic() - self._since) if self._since else 0
        head = Text(f"{self._label}  {secs}s", style="bright_black")
        if self._spinner is None:
            self._spinner = Spinner("line" if self.legacy else "dots", text=head,
                                    style=self.accent)
        else:
            self._spinner.update(text=head)
        # A faculty's answer, once it has started, replaces its reasoning in
        # the block: the thinking is over and what is being written is what
        # there is to watch. Upright, where the reasoning is in italics.
        if self._said:
            body = Text(self._said.strip("\n"), style="bright_black")
        elif self._tail:
            body = Text(self._tail, style="italic bright_black")
        else:
            return self._spinner
        lines = body.wrap(self.console, max(20, self.console.width - 6))
        return Group(self._spinner, Padding(Group(*lines[-THINK_LINES:]), (0, 0, 0, 4)))

    def _tick(self) -> None:
        while self._ticking:
            time.sleep(0.5)
            with self._lock:
                if self._status is not None:
                    self._redraw()

    def _end_thinking(self) -> None:
        """The thinking is over: the panel goes, one line says how long.

        Verbose keeps the whole reasoning on the screen instead, since the
        panel only ever showed the end of it.
        """
        with self._lock:
            chars, since, full = self._think_chars, self._think_since, self._reasoning
            self._think_chars, self._think_since, self._reasoning = 0, 0.0, ""
            self._tail = ""
        if not chars:
            return
        self._hide()
        from rich.padding import Padding
        from rich.text import Text
        if self.verbose and full.strip():
            self.console.print(Padding(Text(" ".join(full.split()), style="italic bright_black"),
                                       (0, 0, 0, 2)))
        secs = time.monotonic() - since
        self.console.print(Text(f"  {self.g['dot']} thought for {secs:.0f}s", style="bright_black"))

    # llm_client.STATUS_HOOK: what the spinner would have said, said here.
    def begin(self, who: str) -> None:
        tag = who[1:who.index("]")] if who.startswith("[") and "]" in who else "model"
        self._show(tag.lower() if tag != "model" else "thinking")

    def tick(self, who: str, seconds: float) -> None:
        pass                                # the ticker thread keeps the seconds moving

    def end(self) -> None:
        self._hide()

    def reasoning(self, chunk: str, who: str) -> None:
        """A faculty's reasoning, under its own status line.

        The same panel the agent's thinking gets, but it keeps the faculty's
        label and leaves no "thought for" line: the faculty's own summary
        follows, with its time.
        """
        with self._lock:
            piece = re.sub(r"\s+", " ", chunk)
            if piece.startswith(" ") and self._tail.endswith(" "):
                piece = piece[1:]
            self._tail = (self._tail + piece)[-THINK_KEEP:]
            if time.monotonic() - self._last_draw >= 0.1:
                self._redraw()

    def answering(self, chunk: str, who: str) -> None:
        """A faculty's answer as it is written, in the same block, gone with it."""
        with self._lock:
            self._said = (self._said + chunk)[-THINK_KEEP:]
            if time.monotonic() - self._last_draw >= 0.1:
                self._redraw()

    def looped(self, who: str, detail: str) -> None:
        from rich.text import Text
        self._hide()
        self.console.print(Text(f"  {self.g['note']} {who.lower()}: the reasoning went in circles "
                                f"- asked again without thinking", style="yellow"))

    def pause(self) -> None:
        """Give the screen back for a question; resume() takes it again."""
        with self._lock:
            self._paused_label = self._label
        self._hide()

    def resume(self) -> None:
        if self._paused_label:
            self._show(self._paused_label)
            self._paused_label = ""

    def idle(self) -> None:
        """Nothing running any more: no status, no live region."""
        with self._lock:
            if self._answer is not None:
                self._answer.close()
                self._answer = None
            self._think_chars, self._think_since, self._reasoning = 0, 0.0, ""
        self._hide()

    # ── streaming from the model ────────────────────────────────────────────

    def _new_call(self) -> None:
        if self._boundary:
            self._boundary = False
            self._call = {"streamed": 0}
            self._tail = ""

    def on_reasoning(self, chunk: str) -> None:
        self._new_call()
        with self._lock:
            if not self._think_chars:
                self._think_since = time.monotonic()
            self._think_chars += len(chunk)
            if self.verbose:
                self._reasoning = (self._reasoning + chunk)[-20000:]
            # One flowing paragraph. The panel shows the last lines of it,
            # wrapped at words, so what is read is sentences. Runs of
            # whitespace become one space, but a space at either edge of a
            # chunk is kept: chunks are cut mid-word, and dropping the edge
            # glued "sulla lezione" into "sullalezione".
            piece = re.sub(r"\s+", " ", chunk)
            if piece.startswith(" ") and self._tail.endswith(" "):
                piece = piece[1:]
            self._tail = (self._tail + piece)[-THINK_KEEP:]
        self._show("thinking")
        # Redrawn at most ten times a second: tokens arrive faster than that
        # and the ticker catches whatever a throttle skipped.
        if time.monotonic() - self._last_draw >= 0.1:
            with self._lock:
                self._redraw()

    def on_token(self, chunk: str) -> None:
        self._new_call()
        self._end_thinking()
        with self._lock:
            self._call["streamed"] += len(chunk)
            if self._answer is None:
                self._hide()
                self.console.print()
                self._answer = _AnswerStream(self.console, self.legacy)
            self._answer.feed(chunk)

    def _close_answer(self) -> None:
        with self._lock:
            if self._answer is not None:
                self._answer.close()
                self._answer = None

    # ── the renderer interface ─────────────────────────────────────────────

    def turn_begin(self) -> None:
        self._turn = {"t0": time.monotonic(), "steps": 0, "tools": 0,
                      "out_tokens": 0, "last_total": 0, "files": self._files()}
        self._boundary = True
        self._note = ""

    def note_stats(self, stats: dict) -> None:
        """The token counts of the call that just ended, kept for the summary."""
        if not stats or not stats.get("total"):
            return
        self._turn["out_tokens"] += int(stats.get("completion") or 0)
        self._turn["last_total"] = int(stats.get("total") or 0)

    def ctx_pct(self) -> int | None:
        total = self._turn.get("last_total") or 0
        if not self.window or not total:
            return None
        return min(999, total * 100 // self.window)

    def banner(self, cwd, model_line, endpoint, max_steps, task):
        pass                                # the session draws its own header

    def thought(self, step, text):
        self._close_answer()
        self._end_thinking()
        self._hide()
        self._turn["steps"] += 1
        self._boundary = True
        if self.verbose and text and self._call["streamed"] == 0:
            from rich.text import Text
            self.console.print(Text("  " + " ".join(text.split()), style="italic bright_black"))
            self._note = ""
        else:
            self._note = text or ""

    def action(self, step, name, args):
        from rich.text import Text
        self._close_answer()
        self._hide()
        self._turn["tools"] += 1
        note = self._note
        self._note = ""
        # What the model said before the call, when the server could not
        # stream it: the note is part of the conversation and this is its
        # one chance to be read. A placeholder is not a note.
        remark = _TOOLS_REQUESTED.search(note or "")
        plain = _TOOLS_REQUESTED.sub("", note or "").strip()
        if plain and self._call["streamed"] == 0 and not _PLACEHOLDER_NOTE.match(plain):
            self.console.print()
            self.console.print(Text("  " + " ".join(plain.split())[:600]))
        t = Text(f"  {self.g['tool']} ", style=self.accent)
        t.append(name, style="bold")
        shown = _kv(args)
        if shown:
            t.append("  " + shown, style="bright_black")
        self.console.print(t)
        if remark:
            self.console.print(Text("    " + remark.group(0).strip("[]"), style="italic bright_black"))
        if name != "ask_user":
            self._show(name)

    def observation(self, step, content, limit):
        from rich.text import Text
        self._hide()
        text = content if isinstance(content, str) else str(content)
        error = text.lstrip().upper().startswith("ERROR")
        style = "red" if error else "bright_black"
        lines = fold(text, self.console.width, self.verbose)
        for i, line in enumerate(lines):
            lead = f"    {self.g['out']} " if i == 0 else "      "
            self.console.print(Text(lead + line, style=style))

    def ask(self, question, context):
        from rich.text import Text
        self._hide()
        self.console.print(Text(f"  ? {question}", style="yellow"))
        if context:
            self.console.print(Text("    " + context, style="bright_black"))

    def ask_answer(self, text):
        from rich.text import Text
        self.console.print(Text("  -> " + text, style="yellow"))

    def final(self, step, content):
        from rich.markdown import Markdown
        self._close_answer()
        self._hide()
        self._note = ""
        # Streamed replies are already on the screen. A server that could not
        # stream delivers the whole reply here, rendered the same way.
        if self._call["streamed"] == 0 and content:
            self.console.print()
            self.console.print(Markdown(str(content)))

    def error(self, step, content):
        from rich.text import Text
        self._close_answer()
        self._end_thinking()
        self._hide()
        t = Text(f"  {self.g['bad']} ", style="bold red")
        t.append(str(content)[:600], style="red")
        self.console.print(t)

    def notice(self, step, content):
        from rich.text import Text
        self._hide()
        self.console.print(Text(f"  {self.g['note']} " + " ".join(str(content).split())[:300],
                                style="italic bright_black"))

    def conclusion(self, forced, elapsed, text):
        from rich.text import Text
        self._close_answer()
        self._hide()
        seconds = elapsed or (time.monotonic() - self._turn.get("t0", time.monotonic()))
        touched = sorted(set(self._files()) - set(self._turn.get("files") or []))
        line = summary_line(self._turn.get("steps", 0), self._turn.get("tools", 0), seconds,
                            self._turn.get("out_tokens", 0), self.ctx_pct(), touched, self.g["dot"])
        self.console.print()
        if forced:
            self.console.print(Text(f"  {self.g['note']} step budget exhausted - the answer was forced",
                                    style="yellow"))
        mark = Text(f"  {self.g['ok']} ", style="green")
        mark.append(line, style="bright_black")
        self.console.print(mark)
        self.console.print()

    def faculty_running(self, tag, note):
        self._show(f"{tag.lower()} {self.g['dot']} {note.rstrip('.… ')}")

    def faculty(self, tag, summary, details=None):
        from rich.text import Text
        self._hide()
        color = FACULTY_COLOR.get(tag, "magenta")
        t = Text(f"  {self.g['fac']} ", style=self.accent)
        t.append(f"{tag.lower()}  ", style=f"bold {color}")
        t.append(str(summary), style="bright_black")
        self.console.print(t)
        for d in details or []:
            self.console.print(Text(f"      {self.g['dot']} {d}", style="bright_black"))

    def stats(self, line):
        pass                                # gathered into the closing line

    def header(self, lines: list[str]) -> None:
        from rich.text import Text
        self.console.print()
        for i, line in enumerate(lines):
            self.console.print(Text(line, style=(self.accent if i == 0 else "bright_black")))
        self.console.print()

    def _files(self) -> list[str]:
        try:
            import checkpoint
            return [rel for rel, _existed in checkpoint.list_entries()]
        except Exception:
            return []


def _kv(args: dict, max_val: int = 80) -> str:
    """key="value" pairs, clipped: the arguments as a glance, not a dump."""
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        s = v if isinstance(v, str) else _json(v)
        s = s.replace("\n", "\\n")
        if len(s) > max_val:
            s = s[:max_val] + "…"
        parts.append(f'{k}="{s}"' if isinstance(v, str) else f"{k}={s}")
    return ", ".join(parts)


def _json(v) -> str:
    import json
    try:
        return json.dumps(v, ensure_ascii=False, default=str)
    except Exception:
        return str(v)


def can_draw() -> bool:
    """Is there a terminal to draw on? Piped output gets the plain lines."""
    try:
        return sys.stdout.isatty()
    except Exception:
        return False
