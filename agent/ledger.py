# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""A turn drawn as a ledger: what was done to the world, and how it went.

This is how a conversation looks. `PRAGMA_LOOK=classic` gives back the look
it replaced, which agent/harness.py still draws; everything here is built on
that module's status line and answer stream, and changes only how the steps
of a turn are shown.

    python -m agent.ledger          a turn replayed with no model, to look at

WHY "LEDGER". A ledger is a book of entries, one line each, in columns that
never move. That is what a turn is drawn as here - a record of what happened
to the world, to be read down a column - and not as a talk with a tool.

WHAT IS DIFFERENT. The classic look draws a tool call the way a debugger
would: the name of the function, its arguments, then what it returned. That
is the vocabulary every agent in a terminal uses, and it describes the
machinery. This draws what happened instead, and three things only:

      | ran      pytest -q                              exit 1
                 FAILED test_report.py::test_json - KeyError: 'total'
      | changed  report.py                               +1 -1
      | ran      pytest -q                             8 passed

- A VERB, NOT A FUNCTION. `ran`, `read`, `changed`, `wrote`: what was done,
  then what it was done to, then how it went. Nothing else is on the line.
- THE OUTCOME IS A MARK IN THE MARGIN. Grey when nothing is worth saying, red
  when it failed, green when a command succeeded. Colour is spent so rarely
  that a red mark is seen from across the room.
- WHAT WENT FINE FADES. The last few steps are bright; as newer ones arrive
  the older ones dim, and the scrollback keeps them as one quiet line each.
  A failure does not fade, and keeps the one line that says why.
- WHAT WAS RECALLED HAS ITS OWN VOICE: the accent colour, whether it is a
  `memory:` or a `belief:`, and the bar of strength that /memory draws. It
  is the one thing here no other harness has.

WHAT WAS TAKEN OUT, and why it stays out. A first version also put a clock
in front of every step and closed the turn on a bar of where its seconds
went. Read by the person it was made for, it was "a mix of things": six
items on a line, and a bar that was one colour whenever the model took all
the time, which is nearly always. A step says how long it took only when it
was long enough to notice, and the turn closes on the plain line it always
had.

HOW THE FADING WORKS. Lines already printed cannot be recoloured, so the
newest steps are not printed: they are held in the live region the status
line already uses, drawn brighter or dimmer by age, and a step is printed for
good only when it leaves that window - already in the tone it will keep.

WHAT THE MODEL SAYS ON THE WAY. A model often writes a sentence before it
acts ("now I'll run the tests"), and until the next event nobody can tell
that sentence from the beginning of the answer. So text is held as it
arrives, and shown while it is written the way reasoning is. If a tool call
follows, it was a remark: the step says what was done, and the remark goes
as the reasoning goes. If it grows past a couple of lines, or the turn ends
on it, it was the answer, and it is handed to the answer stream.
"""

from __future__ import annotations

import os
import re
import sys
import time

try:
    from agent.harness import Harness, _plain_reasoning, plural, tame
except ImportError:                      # run from inside agent/
    from harness import Harness, _plain_reasoning, plural, tame  # type: ignore

# How many finished steps stay in the live window, brightest last.
WINDOW = 4

# A step's line stops here however wide the terminal is: what was done and
# how it went are read together, not from opposite edges of the screen.
LINE = 80

# Seconds a step must have taken before the line says how long it took.
SLOW = 2.0

# The mark in the margin: one per step, and SEEN as one per step. It was a
# half block, and block characters are made to tile - one on each line and
# they fuse into a single bar down the screen, so five steps read as one
# stripe. A tall rectangle has air above and below it. It was chosen by eye,
# out of the ones `python -m agent.ledger --marks` draws, in the terminal
# where Pragma is used: which one looks right depends on the font.
MARK = "▮"
# The bar of strength is the same rectangle, eight times: filled for what is
# held, hollow for what is not. Hollow rather than dimmed, so that the bar
# still reads where there is no colour to tell the two apart.
HELD, FADED = "▮", "▯"
MARKS = (("■", "square"), ("▪", "small square"), ("▮", "tall rectangle"),
         ("▖", "low quarter block"), ("●", "dot"), ("▸", "arrow"),
         ("▌", "half block - the first one, which fuses"))

# Text the model writes is taken for a remark until it is longer than this,
# or shows any of the marks of an answer: a second paragraph, a list, a
# heading, a code fence.
REMARK_CHARS = 280
_ANSWER_MARKS = re.compile(r"\n\s*\n\S|```|^\s*(#{1,6} |[-*] |\d+[.)] |\|)", re.MULTILINE)

# The verb a skill is drawn with. Anything not here is drawn by its own name:
# a skill added tomorrow shows up, plainly, rather than not at all.
VERBS = {
    "execute_command": "ran",
    "read_file": "read", "file_outline": "read",
    "write_file": "wrote",
    "replace_in_file": "changed", "replace_in_files": "changed",
    "insert_after": "changed", "insert_before": "changed",
    "append_file": "changed", "apply_patch": "changed",
    "list_dir": "looked", "glob_match": "looked", "grep_search": "looked",
    "git_status": "looked", "git_diff": "looked",
    "web_fetch": "fetched", "web_search": "searched",
    "vision_interpret": "saw", "revert": "undid",
}

# Lines of a failed command worth showing: the ones that name the error.
_TELLING = re.compile(r"^\s*(FAILED|ERROR|E\s{2,}|fatal:|error:|Traceback)|"
                      r"\b\w*(Error|Exception)\b\s*:", re.IGNORECASE)
_RETURNCODE = re.compile(r"^returncode:\s*(-?\d+)", re.MULTILINE)


def _lines(text: str) -> int:
    text = text or ""
    return text.count("\n") + (1 if text and not text.endswith("\n") else 0)


def _delta(old: str, new: str) -> tuple[int, int]:
    """(lines added, lines removed) going from `old` to `new`."""
    import difflib
    added = removed = 0
    for line in difflib.ndiff((old or "").splitlines(), (new or "").splitlines()):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return added, removed


def _sections(text: str) -> tuple[str, str]:
    """(stdout, stderr) out of what execute_command returns.

    It writes `stdout:` and then `stderr:`, each on a line of its own and only
    when there is something under it. Split on those two lines and nothing
    else: a program is free to print a line that looks like a heading.
    """
    out = err = ""
    rest = "\n" + (text or "")
    if "\nstderr:\n" in rest:
        rest, err = rest.split("\nstderr:\n", 1)
    if "\nstdout:\n" in rest:
        out = rest.split("\nstdout:\n", 1)[1]
    return out.strip(), err.strip()


def _last(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        if line.strip():
            return " ".join(line.split())
    return ""


class Ledger(Harness):
    """The harness, with a turn's steps drawn as a ledger. See the module."""

    def __init__(self, *args, **kwargs):
        self._steps: list[dict] = []
        self._pending: dict | None = None
        self._holding = False
        self._remark = ""
        self._strength: dict[str, float] = {}
        super().__init__(*args, **kwargs)
        marks = MARK + HELD + FADED + "−"
        try:
            marks.encode(getattr(self.console, "encoding", None) or sys.stdout.encoding or "utf-8")
            poor = self.legacy
        except Exception:
            poor = True
        self.m = ({"stripe": "|", "full": "#", "empty": "-", "minus": "-"} if poor
                  else {"stripe": MARK, "full": HELD, "empty": FADED, "minus": "−"})
        # Three tones for three ages. A console with sixteen colours has one
        # grey, so there the fade is two steps instead of three.
        self.tones = (("", "bright_black", "bright_black") if poor
                      else ("", "grey66", "grey42"))

    # ── what a step is ──────────────────────────────────────────────────────

    def _root(self) -> str:
        try:
            import checkpoint
            root = checkpoint.root()
            if root:
                return str(root)
        except Exception:
            pass
        return os.getcwd()

    def _near(self, path: str) -> str:
        """A path as it reads from the workspace: `report.py`, not the drive."""
        path = str(path or "")
        if not path:
            return ""
        root = self._root()
        try:
            rel = os.path.relpath(path, root)
            if not rel.startswith(".."):
                return rel.replace(os.sep, "/")
        except Exception:
            pass
        home = os.path.expanduser("~")
        return ("~" + path[len(home):]) if path.startswith(home) else path

    def _describe(self, name: str, args: dict) -> tuple[str, str]:
        """(verb, what it was done to) for a call."""
        args = args or {}
        verb = VERBS.get(name, name)
        if name == "execute_command":
            command = " ".join(str(args.get("command", "")).split())
            root = self._root()
            # `cd <the workspace> && ...` is where the command runs anyway:
            # said in front of every line it is noise, so it is not said.
            command = re.sub(r"^cd\s+[\"']?" + re.escape(root) + r"[/\\]?[\"']?\s*(&&|;)\s*",
                             "", command)
            for prefix in (root + os.sep, root + "/", root):
                command = command.replace(prefix, "")
            return verb, command
        if name == "web_search":
            return verb, f'"{args.get("query", "")}"'
        if name == "web_fetch":
            return verb, re.sub(r"^https?://", "", str(args.get("url", "")))
        if name in ("glob_match", "grep_search"):
            where = self._near(args.get("base_path") or args.get("path") or "")
            what = str(args.get("pattern", ""))
            return verb, f"{what}  in {where}" if where and where != "." else what
        if name in ("git_status", "git_diff"):
            return verb, name.replace("_", " ")
        if name == "apply_patch":
            files = re.findall(r"^\+\+\+ (?:b/)?(\S+)", str(args.get("diff", "")), re.MULTILINE)
            return verb, ", ".join(self._near(f) for f in files[:3]) or "a patch"
        target = (args.get("path") or args.get("image_path") or args.get("file") or "")
        return verb, self._near(target) or name

    def _outcome(self, name: str, args: dict, text: str, took: float) -> dict:
        """How a call went: a word or two, whether it failed, and why."""
        args = args or {}
        text = tame(text if isinstance(text, str) else str(text))
        head = text.lstrip()
        if name == "execute_command":
            return self._ran(text, took)
        if head.upper().startswith("ERROR"):
            why = " ".join(head.split("\n", 1)[0].split())
            why = re.sub(r"^ERROR:?\s*", "", why, flags=re.IGNORECASE)
            return {"word": "refused" if "refused" in why[:40] else "failed",
                    "ok": False, "why": [why], "mark": "bad"}
        word = ""
        if name in ("read_file", "file_outline"):
            # The file's own length, not the length of what came back: a read
            # is returned with a heading and line numbers around it.
            count = _lines(text)
            try:
                if name == "read_file" and not (args.get("start_line") or args.get("end_line")):
                    with open(str(args.get("path", "")), encoding="utf-8", errors="replace") as fh:
                        count = sum(1 for _ in fh)
            except Exception:
                pass
            word = plural(count, "line")
        elif name == "write_file":
            word = f"+{_lines(str(args.get('content', '')))}"
        elif name == "replace_in_file":
            added, removed = _delta(str(args.get("old", "")), str(args.get("new", "")))
            word = f"+{added} {self.m['minus']}{removed}"
        elif name in ("insert_after", "insert_before", "append_file"):
            word = f"+{_lines(str(args.get('content', '')))}"
        elif name == "apply_patch":
            diff = str(args.get("diff", ""))
            added = len(re.findall(r"^\+(?!\+\+)", diff, re.MULTILINE))
            removed = len(re.findall(r"^-(?!--)", diff, re.MULTILINE))
            word = f"+{added} {self.m['minus']}{removed}"
        elif name in ("list_dir", "glob_match", "grep_search", "git_status", "git_diff"):
            word = plural(_lines(text), "line")
        elif name == "web_fetch":
            word = f"{len(text):,} chars"
        else:
            word = _last(text.split("\n", 1)[0])[:28]
        return {"word": word, "ok": True, "why": [], "mark": "plain"}

    def _ran(self, text: str, took: float) -> dict:
        head = text.lstrip()
        if head.startswith("STARTED in background"):
            pid = re.search(r"pid\s*:\s*(\d+)", text)
            return {"word": f"in background{' · pid ' + pid.group(1) if pid else ''}",
                    "ok": True, "why": [], "mark": "plain", "took": took}
        if head.startswith("INTERRUPTED"):
            return {"word": "stopped", "ok": False, "why": [], "mark": "bad", "took": took}
        if head.upper().startswith("ERROR"):
            first = " ".join(head.split("\n", 1)[0].split())
            word = "timed out" if "timed out" in first else "failed"
            why = [] if word == "timed out" else [re.sub(r"^ERROR:?\s*", "", first)]
            return {"word": word, "ok": False, "why": why, "mark": "bad", "took": took}
        m = _RETURNCODE.search(text)
        code = int(m.group(1)) if m else 0
        out, err = _sections(text)
        if code == 0:
            # The program's own last line, which is usually its verdict
            # ("8 passed"). Its own timing is dropped: ours is beside it.
            # A rule drawn around it ("==== 2 passed ====") is decoration.
            said = re.sub(r"\s+in\s+[\d.]+\s*s(ec(onds)?)?\s*$", "",
                          _last(out).strip("=-*#~ "))
            # A last line with no words in it is data, not a verdict: a
            # program that prints ten numbers has not said "100".
            if not re.search(r"[^\W\d_]{2,}", said):
                said = plural(_lines(out), "line") if out else ""
            return {"word": said[:30] or "ok", "ok": True, "why": [],
                    "mark": "good", "took": took}
        # Why it failed, in the fewest lines that say it. A test runner's own
        # summary lines ("FAILED test_x - assert 4 == 5") say it best; without
        # them, the last line that names an error; without that, the last line.
        body = [" ".join(ln.split()) for ln in (out + "\n" + err).splitlines() if ln.strip()]
        summary = [ln for ln in body if re.match(r"(FAILED|ERROR)\b", ln)]
        named = [ln for ln in body if _TELLING.search(ln) and not ln.startswith("Traceback")]
        why = summary[-2:] or named[-1:] or body[-1:]
        return {"word": f"exit {code}", "ok": False, "why": why,
                "mark": "bad", "took": took}

    # ── drawing a step ──────────────────────────────────────────────────────

    def _rows(self, step: dict, age: int) -> list:
        """A step as rich lines. `age` 0 is the newest; older is dimmer.

        Three things on a line and no more: what was done, what to, how it
        went. The line stops at LINE columns however wide the terminal is, so
        the outcome sits where the eye already is and not at the far edge.
        """
        from rich.text import Text
        width = min(max(40, self.console.width), LINE)
        lead = 2 + 2 + 9                               # margin, mark, verb
        failed = step["ok"] is False
        tone = "" if failed else self.tones[min(age, len(self.tones) - 1)]
        quiet = self.tones[-1]
        mark = {"bad": "red", "good": "green"}.get(step["mark"], quiet)
        word = step["word"]
        # How long it took is said only when it was long enough to notice.
        took = step.get("took")
        long = f"{took:.0f}s" if took is not None and took >= SLOW else ""
        right = len(word) + (2 + len(long) if long else 0)
        room = width - lead - right - 2
        what = step["what"]
        if room < 10:
            word, long, room = "", "", width - lead
        if len(what) > room:
            what = what[:max(1, room - 1)] + "…"
        line = Text("  ")
        line.append(self.m["stripe"] + " ", style=mark)
        line.append(f"{step['verb']:<8} ", style=tone)
        line.append(what.ljust(room) if word else what, style=tone)
        if word:
            line.append("  ")
            line.append(word, style=("red" if failed else tone))
            if long:
                line.append("  " + long, style=quiet)
        rows = [line]
        for why in step["why"]:
            rows.append(Text(" " * lead + why[:max(10, self.console.width - lead - 1)],
                             style="red"))
        return rows

    def _commit(self, steps: list[dict], aged: bool) -> None:
        """Print steps for good. `aged`: they left the window, so in the tone
        they keep; otherwise as they stood, newest brightest."""
        n = len(steps)
        for i, step in enumerate(steps):
            age = len(self.tones) - 1 if aged else (n - 1 - i)
            for row in self._rows(step, age):
                self.console.print(row)

    # ── the live window ─────────────────────────────────────────────────────

    def _renderable(self):
        from rich.console import Group
        from rich.padding import Padding
        from rich.text import Text
        steps = list(self._steps)
        rows = []
        for i, step in enumerate(steps):
            rows += self._rows(step, len(steps) - 1 - i)
        if self._remark.strip():
            # Text that may be the answer and may be a remark: shown while it
            # is written, the way reasoning is, and kept only if it is the
            # answer.
            said = Text(" ".join(_plain_reasoning(self._remark).split()),
                        style=f"italic {self.tones[-1]}")
            lines = said.wrap(self.console, max(20, self.console.width - 6))
            rows.append(Padding(Group(*lines[-3:]), (0, 0, 0, 4)))
        if self._label:
            base = super()._renderable()
            return Group(*rows, base) if rows else base
        return Group(*rows) if rows else Text("")

    def _hold(self) -> None:
        """Keep the live region up, with the window and without a status."""
        with self._lock:
            self._spinner = None
            self._label = ""
            self._tail = ""
            self._said = ""
            if self._status is None:
                try:
                    from rich.live import Live
                    self._status = Live(self._renderable(), console=self.console,
                                        refresh_per_second=8, transient=True)
                    self._status.start()
                except Exception:
                    self._status = None
            else:
                self._redraw()

    def _hide(self) -> None:
        # While something is held, hiding the status must not take the window
        # with it: the live region stays and only the status line goes.
        with self._lock:
            held = self._holding and self._answer is None and (
                self._steps or self._remark.strip())
        if held:
            self._hold()
            return
        super()._hide()

    def _flush(self) -> None:
        """Give the window up: the live region goes, what it held is printed.

        Text still being held at this point was not followed by a tool call,
        so it was not a remark: it is what the model had to say, and is
        printed as that.
        """
        with self._lock:
            steps, self._steps = self._steps, []
            said, self._remark = self._remark, ""
            self._holding = False
        super()._hide()
        self._commit(steps, aged=False)
        if said.strip():
            from rich.markdown import Markdown
            self.console.print()
            self.console.print(Markdown(said.strip()))

    def _promote(self) -> None:
        """The held text has turned out to be the answer: stream it as one."""
        with self._lock:
            text, self._remark = self._remark, ""
            self._call["streamed"] -= len(text)
        self._flush()
        super().on_token(text)

    # ── the events that end a window ────────────────────────────────────────

    def on_token(self, chunk: str) -> None:
        if self.envelope or self._answer is not None:
            return super().on_token(chunk)
        if self.verbose:
            self._flush()
            return super().on_token(chunk)
        self._new_call()
        self._end_thinking()
        with self._lock:
            self._call["streamed"] += len(chunk)
            self._remark += chunk
            text = self._remark
            self._holding = True
        if len(text) > REMARK_CHARS or _ANSWER_MARKS.search(text):
            self._promote()
        else:
            self._hold()

    def pause(self) -> None:
        self._flush()
        super().pause()

    def idle(self) -> None:
        self._flush()
        super().idle()

    def final(self, step, content):
        self._flush()
        super().final(step, content)

    def error(self, step, content):
        self._flush()
        super().error(step, content)

    def conclusion(self, forced, elapsed, text):
        self._flush()
        super().conclusion(forced, elapsed, text)

    def turn_begin(self) -> None:
        super().turn_begin()
        self._steps = []
        self._pending = None
        self._holding = False
        self._remark = ""

    # ── the renderer interface ──────────────────────────────────────────────

    def action(self, step, name, args):
        if self.verbose or name == "ask_user":
            self._flush()
            return super().action(step, name, args)
        self._close_answer()
        self._turn["tools"] += 1
        self._note = ""
        verb, what = self._describe(name, args or {})
        with self._lock:
            # A tool call follows, so what was held was a remark on the way
            # to it. The step says what was done; the remark is let go.
            self._remark = ""
            self._holding = True
            self._pending = {"name": name, "args": args or {}, "verb": verb, "what": what,
                             "t0": time.monotonic()}
        self._show(f"{verb} {what}"[:max(20, self.console.width - 12)])

    def observation(self, step, content, limit):
        pending, self._pending = self._pending, None
        if pending is None:
            return super().observation(step, content, limit)
        took = time.monotonic() - pending["t0"]
        how = self._outcome(pending["name"], pending["args"], content, took)
        done = {"verb": pending["verb"], "what": pending["what"], **how}
        with self._lock:
            self._steps.append(done)
            leaving, self._steps = self._steps[:-WINDOW], self._steps[-WINDOW:]
        self._commit(leaving, aged=True)
        self._hide()

    def faculty(self, tag, summary, details=None):
        if self.verbose:
            return super().faculty(tag, summary, details)
        if tag == "CURATOR":
            self.recalled([(str(d), self._strength_of(str(d))) for d in details or []],
                          str(summary))
            return
        # Any other faculty, in the same voice as the recall: its name in the
        # accent, what it says beside it, and nothing drawn in front.
        from rich.text import Text
        self._close_answer()
        self._hide()
        self._boundary = True
        lead = Text("  ")
        lead.append(f"{tag.lower()}  ", style=self.accent)
        self._hanging(lead, Text(str(summary), style=self.tones[1]))
        pad = " " * (2 + len(tag) + 2)
        for d in details or []:
            self._hanging(Text(f"{pad}{self.g['dot']} ", style=self.tones[-1]),
                          Text(str(d), style=self.tones[-1]))

    def recalled(self, items: list, summary: str = "") -> None:
        """What memory brought to this turn, in its own colour.

        `items` is [(label, strength or None)]. Each line says which of the
        two things it is - `memory:` for an episode, something that happened,
        `belief:` for what was concluded from several - then how strongly it
        is held. With nothing recalled, one quiet line says so: a faculty
        that looked and found nothing is not a faculty that did not look.
        """
        from rich.text import Text
        self._close_answer()
        self._hide()
        self._boundary = True
        quiet = self.tones[-1]
        if not items:
            # "1 memory + 0 beliefs → none of them bears on this — why · 2s"
            # is the curator's whole account. Here it is the verdict alone.
            said = re.sub(r"\s*·\s*\d+s\s*$", "", summary).strip()
            said = re.sub(r"^.*?→\s*", "", said).split(" — ")[0].strip()
            self.console.print(Text(f"  recalled  {said or 'nothing'}", style=quiet))
            return
        self.console.print()
        width = max(40, self.console.width)
        for i, (label, strength) in enumerate(items):
            if not label.startswith("belief: "):
                label = "memory: " + label
            line = Text("  ")
            line.append("recalled  " if i == 0 else " " * 10, style=self.accent)
            if strength is None:
                line.append(" " * 10)
            else:
                cells = max(0, min(8, round(float(strength) * 8)))
                line.append(self.m["full"] * cells, style=self.accent)
                line.append(self.m["empty"] * (8 - cells), style=quiet)
                line.append("  ")
            room = width - 2 - 10 - 10 - 1
            line.append(label if len(label) <= room else label[:room - 1] + "…",
                        style=self.accent)
            self.console.print(line)
        self.console.print()

    def _strength_of(self, label: str) -> float | None:
        """How strongly a recalled item is held now, looked up by its label.

        The curator hands the renderer the words, not the numbers, and this
        prototype does not change what it hands over: the episode is found
        again by its goal, the belief by its text. None when it cannot be.
        """
        if label in self._strength:
            return self._strength[label]
        found = None
        try:
            stem = re.sub(r"\s*\(dormant.revived\)\s*$", "", label).rstrip("…").strip()
            if label.startswith("belief: "):
                import json
                import config
                stem = stem[len("belief: "):]
                with open(config.LEARNINGS_PATH, encoding="utf-8") as fh:
                    for entry in json.load(fh).get("entries", []):
                        if " ".join(str(entry.get("text", "")).split()).startswith(stem):
                            found = float(entry.get("confidence", 0) or 0)
                            break
            else:
                import episodes
                for folder in (episodes.active_dir(), episodes.dormant_dir()):
                    for _path, ep in episodes.load(folder):
                        if " ".join(str(ep.get("goal", "")).split()).startswith(stem):
                            found = float(episodes.effective_salience(ep))
                            break
                    if found is not None:
                        break
        except Exception:
            found = None
        self._strength[label] = found
        return found


# ── a turn to look at, with no model behind it ───────────────────────────────

def demo(fast: bool = False) -> None:
    """Replay one turn, at something like its own pace."""
    from rich.console import Console
    from rich.text import Text

    def wait(seconds: float) -> None:
        time.sleep(seconds * (0.15 if fast else 1.0))

    console = Console(highlight=False)
    r = Ledger(console=console, context_window=131072)
    console.print()
    console.print(Text("❯ ", style=r.accent).append(
        "Add a --json flag to report.py and make the tests pass", style=""))
    r.turn_begin()
    r.faculty_running("CURATOR", "searching memory for what bears on this…")
    wait(2.2)
    r.end()
    r.recalled([("Every script starts with a one-line docstring", 0.62),
                ("belief: Tests live in tests/ and run with pytest -q", 0.41)])

    def step(name, args, result, think=1.4, work=0.6, say=""):
        r.begin("")
        r.on_progress(900, 900, 0)
        wait(think)
        r.end()
        for word in say.split(" ") if say else []:
            r.on_token(word + " ")
            wait(0.05)
        r.thought(0, "")
        r.action(0, name, args)
        wait(work)
        r.observation(0, result, 600)

    root = r._root()
    report = os.path.join(root, "report.py")
    step("read_file", {"path": report}, "\n".join(f"line {i}" for i in range(141)))
    step("replace_in_file", {"path": report, "old": "def main(argv):\n    rows = load()",
                             "new": "def main(argv):\n    as_json = '--json' in argv\n"
                                    "    rows = load()\n    if as_json:\n        return dump(rows)"},
         f"OK: replaced 1 occurrence(s) in {report}")
    step("execute_command", {"command": "pytest -q"},
         "returncode: 1\nstdout:\n.......F\n=== FAILURES ===\n"
         "FAILED tests/test_report.py::test_json_flag - KeyError: 'total'\n"
         "1 failed, 7 passed in 0.31s", work=2.4)
    step("replace_in_file", {"path": report, "old": "row['sum']", "new": "row['total']"},
         f"OK: replaced 1 occurrence(s) in {report}", think=1.8,
         say="The row has no key called sum: the column is total. Fixing the name.")
    step("execute_command", {"command": "pytest -q"},
         "returncode: 0\nstdout:\n........\n8 passed in 0.29s", work=2.2)

    r.begin("")
    wait(1.0)
    r.thought(0, "")
    answer = ("The `--json` flag is in: `report.py --json` prints the rows as JSON instead of "
              "the table. The first run of the tests failed on a key I had misnamed, "
              "`sum` for `total`; it is fixed and the eight tests pass.")
    for word in answer.split(" "):
        r.on_token(word + " ")
        wait(0.03)
    r.final(0, answer)
    r._turn["peak_total"] = 7800
    r.conclusion(False, 0, answer)
    r._ticking = False


def marks() -> None:
    """The same four steps under each candidate mark, to choose by eye."""
    from rich.console import Console
    from rich.text import Text
    console = Console(highlight=False)
    r = Ledger(console=console)
    r._ticking = False
    steps = [
        {"verb": "read", "what": "report.py", "word": "141 lines", "ok": True,
         "why": [], "mark": "plain"},
        {"verb": "ran", "what": "pytest -q", "word": "exit 1", "ok": False,
         "why": [], "mark": "bad"},
        {"verb": "changed", "what": "report.py", "word": "+1 −1", "ok": True,
         "why": [], "mark": "plain"},
        {"verb": "ran", "what": "pytest -q", "word": "8 passed", "ok": True,
         "why": [], "mark": "good"},
    ]
    for n, (glyph, name) in enumerate(MARKS, 1):
        console.print()
        console.print(Text(f"  {n}. {name}", style="bold"))
        r.m["stripe"] = glyph
        for i, step in enumerate(steps):
            for row in r._rows(step, len(steps) - 1 - i):
                console.print(row)
    console.print()


if __name__ == "__main__":
    if "--marks" in sys.argv:
        marks()
    else:
        demo(fast="--fast" in sys.argv)
