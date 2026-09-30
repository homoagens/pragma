#!/usr/bin/env python3
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

r"""A list walked with the arrows, for every page that offers a choice.

It was the launcher's own, written once for its home screen; /configure then
wanted the same thing and the choice was to copy it or to move it here. One
implementation, so a menu behaves the same wherever Pragma draws one - the
arrows, the digits, the first letter, and ctrl+D going back.

    i = pick("Which endpoint?", ["montecucco", "qwen36"], ["connected", "..."])

`pick` falls back to a numbered list where the terminal cannot go raw (a pipe,
a log, a test), so nothing here needs a terminal to be exercised.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import sys
import threading
import time

ESC = "\033"
GREY, RESET = ESC + "[38;5;242m", ESC + "[0m"

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def visible(text: str) -> int:
    """How many columns a string occupies once the colours are taken out."""
    return len(_ANSI.sub("", text))


def columns() -> int:
    """The terminal's width, with a floor a menu can still be drawn in."""
    try:
        return max(24, shutil.get_terminal_size((80, 24)).columns)
    except Exception:
        return 80


def lines() -> int:
    """The terminal's height, asked of the terminal itself.

    Not $LINES first: bash exports it, and over ssh or after a resize it is
    routinely stale - a menu sized for a stale 50 on a 24-line window scrolls
    its own top off the screen and then redraws in the wrong place.
    """
    for stream in (sys.__stdout__, sys.__stdin__, sys.__stderr__):
        try:
            return max(8, os.get_terminal_size(stream.fileno()).lines)
        except Exception:
            continue
    return 24


def _encodes(text: str) -> bool:
    try:
        text.encode(sys.stdout.encoding or "ascii")
        return True
    except Exception:
        return False


# The separator between the parts of a hint, and the mark beside the chosen
# row: the same two the conversation draws, where the console can show them.
SEP = " · " if _encodes("·") else " - "
MARK = "❯" if _encodes("❯") else ">"


def fit(body: str, note: str = "") -> str:
    """One menu line, trimmed so it NEVER wraps.

    A wrapped row is what breaks the redraw: menu() goes back up by one line
    per option, and a row that took two physical lines leaves the cursor in
    the wrong place, so the next draw lands beside the last one instead of
    over it - the row appearing again and again down the page. Seen on a
    narrow WSL window, where the sampling row and its note are long.

    The note is what gives way first: the row itself is the answer and the
    note only explains it. What is cut ends in a dot, so a trimmed note does
    not read as a short one.
    """
    room = columns() - 1
    cut = "…" if _encodes("…") else "."
    if visible(body) >= room:
        plain = _ANSI.sub("", body)
        return plain[:max(0, room - 1)] + cut
    if not note:
        return body
    left = room - visible(body)
    if visible(note) <= left:
        return body + note
    # The note carries its own colour codes; cut the text, keep the codes.
    plain = _ANSI.sub("", note).strip()
    if left < 7:
        return body
    return body + f"   {GREY}{plain[:left - 4]}{cut}{RESET}"


def accent() -> str:
    """The accent as an ANSI foreground, as every Pragma page uses it."""
    raw = (os.environ.get("PRAGMA_ACCENT") or "178;132;255").strip()
    parts = raw.split(";")
    if len(parts) != 3 or not all(p.isdigit() and int(p) < 256 for p in parts):
        raw = "178;132;255"
    return ESC + "[38;2;" + raw + "m" if sys.stdout.isatty() else ""


def say(text: str = "", style: str = "") -> None:
    a = accent()
    if not a or not style:
        print(text)
        return
    colour = {"accent": a, "dim": GREY, "good": ESC + "[32m", "warn": ESC + "[33m",
              "bad": ESC + "[31m"}.get(style, "")
    print(f"{colour}{text}{RESET}" if colour else text)


def row(label: str, value: str, colour: str = "", width: int = 12, indent: int = 2) -> None:
    """One `label   value` line, wrapped under its own value and never at column 0.

    A line longer than the window used to be handed to the terminal, which
    broke it at the last column and carried the rest to the left edge: an
    address split as ".../" and "v1", a sentence continuing under the labels
    as though it were one of them. Here the value wraps at words, and every
    line after the first starts where the value started.

    `colour` is an ANSI code for the value (the label is always grey); it is
    dropped where there is no terminal to colour.
    """
    import textwrap
    a = accent()
    grey, reset = (GREY, RESET) if a else ("", "")
    paint = colour if (colour and a) else ""
    lead = " " * indent + f"{label:<{width}}"
    room = max(20, columns() - 1 - len(lead))
    parts = textwrap.wrap(value, room, break_long_words=True,
                          break_on_hyphens=False) or [""]
    for i, part in enumerate(parts):
        head = f"{grey}{lead}{reset}" if i == 0 else " " * len(lead)
        print(head + (f"{paint}{part}{reset}" if paint else part))


_CLEAR_SEQ: bytes | None = None


def clear() -> None:
    """Home, wipe, and the scrollback with it.

    The sequence comes from TERMINFO - the terminal's own answer to "how do I
    clear you", which is the string /usr/bin/clear writes, obtained without
    spawning it. A hand-written ESC[H ESC[2J is right for xterm and is not
    what every emulator wants: some keep the viewport where it was and draw
    the new page below the old one, which looks like the screen sliding down
    with the page half off the top.

    The hand-written escape stays as the fallback: a terminal with no TERM,
    and Windows, where there is no terminfo to ask.
    """
    global _CLEAR_SEQ
    if not sys.stdout.isatty():
        return
    if _CLEAR_SEQ is None:
        _CLEAR_SEQ = b""
        if os.name != "nt" and os.environ.get("TERM"):
            try:
                import curses
                curses.setupterm()
                _CLEAR_SEQ = curses.tigetstr("clear") or b""
            except Exception:
                _CLEAR_SEQ = b""
    try:
        if _CLEAR_SEQ:
            sys.stdout.flush()
            sys.stdout.buffer.write(_CLEAR_SEQ + b"\033[3J")    # and the scrollback
            sys.stdout.flush()
            return
    except Exception:
        pass
    print(ESC + "[H" + ESC + "[2J" + ESC + "[3J", end="", flush=True)


def title(name: str, crumbs: str = "") -> None:
    """The head of a page: where you are, on a screen of its own.

    Every page clears before it draws. A terminal that keeps the last four
    questions above the current one is not showing history, it is showing
    debris: the answers are already recorded in what the page says about
    itself, and the eye has to find the live line among the dead ones.
    """
    clear()
    a, r = accent(), (RESET if accent() else "")
    if crumbs and _encodes("›"):
        crumbs = crumbs.replace(" > ", " › ")
    print()
    print(f"  {a}{name}{r}" + (f"  {GREY}{crumbs}{r}" if crumbs and a else
                               (f"  {crumbs}" if crumbs else "")))


_SPIN_FANCY = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPIN_PLAIN = "|/-\\"


@contextlib.contextmanager
def waiting(message: str):
    """A line that moves while something slow happens, and the seconds with it.

    A local model asked to read a page can sit for a minute, and a terminal
    that shows nothing in that minute is indistinguishable from one that has
    hung - which is the moment people press ctrl+C on work that was about to
    finish. The elapsed count is the part that actually answers the question:
    a spinner says "alive", a number says "forty seconds so far, this is
    normal" or "four minutes, something is wrong".

    The line is erased on the way out, so whatever the caller prints next
    lands where the spinner was.
    """
    if not sys.stdout.isatty():
        print(f"  {message}...")
        yield
        return
    frames = _SPIN_FANCY
    try:
        frames.encode(sys.stdout.encoding or "ascii")
    except Exception:
        frames = _SPIN_PLAIN          # a console that cannot draw braille
    stop = threading.Event()
    a, r = accent(), (RESET if accent() else "")

    def spin():
        started = time.time()
        i = 0
        while not stop.is_set():
            seconds = int(time.time() - started)
            clock = f"{seconds}s" if seconds < 60 else f"{seconds // 60}m {seconds % 60}s"
            print(f"\r{ESC}[2K  {a}{frames[i % len(frames)]}{r} {message}  "
                  f"{GREY}{clock}{r}", end="", flush=True)
            i += 1
            stop.wait(0.09)

    thread = threading.Thread(target=spin, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)
        print(f"\r{ESC}[2K", end="", flush=True)


def ask(question: str, default: str = "", hint: str = "") -> str | None:
    """One answer, or None for ctrl+D - which goes back, everywhere.

    The default in brackets is what Enter keeps; the hint, in grey after it,
    says what kind of answer fits. They used to share one slot, so a question
    with both lost its hint, and a hint read as part of the question:
    "type the project name to confirm  ctrl+D goes back:".

    With no question it is a pause - see pause().
    """
    if not question:
        pause(hint or "enter to go back")
        return default
    a = accent()
    grey, reset = (GREY, RESET) if a else ("", "")
    shown = f" [{default}]" if default else ""
    tip = f"  {grey}{hint}{reset}" if hint else ""
    try:
        answer = input(f"  {question}{shown}{tip}{grey}:{reset} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return answer or default


def pause(text: str = "enter to go back") -> None:
    """Wait for Enter, saying so - a line to read, not a question to answer."""
    a = accent()
    grey, reset = (GREY, RESET) if a else ("", "")
    try:
        input(f"  {grey}{text}{reset} ")
    except (EOFError, KeyboardInterrupt):
        print()


# THE KEYBOARD, for as long as a menu is up. Per key the terminal used to be
# switched raw and straight back, and the switch FLUSHED: tty.setraw defaults
# to TCSAFLUSH, which throws away whatever has been typed and not yet read. Two
# arrows pressed quickly moved the cursor one row, three moved it one - and a
# held arrow skipped rows at random - because every key after the first was
# discarded by the read of the first. MEASURED in tmux: Down Down Down from
# the top landed on the second row.
#
# Now the menu takes the keyboard once, in cbreak mode (keys one at a time, no
# echo, output unchanged), and gives it back when it returns. Nothing typed is
# lost, and nothing typed is echoed onto the page between two redraws.
_KEYS_HELD = [False]


@contextlib.contextmanager
def keyboard():
    """Keys one at a time, unechoed, for the length of the block. POSIX only;
    on Windows msvcrt already reads that way and this does nothing."""
    if os.name == "nt" or _KEYS_HELD[0] or not sys.stdin.isatty():
        yield
        return
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd, termios.TCSANOW)
        _KEYS_HELD[0] = True
        yield
    finally:
        _KEYS_HELD[0] = False
        termios.tcsetattr(fd, termios.TCSANOW, saved)


# The escape sequences worth a name. Both spellings of the arrows: a terminal
# in application-cursor mode sends ESC O A where the others send ESC [ A.
_SEQUENCES = {
    b"[A": "up", b"OA": "up", b"[B": "down", b"OB": "down",
    b"[H": "home", b"OH": "home", b"[1~": "home", b"[7~": "home",
    b"[F": "end", b"OF": "end", b"[4~": "end", b"[8~": "end",
    b"[5~": "pageup", b"[6~": "pagedown",
}


def read_key() -> str:
    """One keypress, as a word: up, down, home, end, pageup, pagedown, enter,
    back - or the character, lower-cased.

    ctrl+C is `back`, as ctrl+D and Esc are, on both systems. It used to raise
    on Linux, and nothing above a menu caught it: ctrl+C on the projects page
    or in /configure ended Pragma with a traceback, while on Windows the same
    key went back one page.
    """
    if os.name == "nt":
        import msvcrt
        try:
            ch = msvcrt.getwch()
        except KeyboardInterrupt:
            return "back"
        if ch in ("\x00", "\xe0"):          # a special key arrives as two
            return {"H": "up", "P": "down", "G": "home", "O": "end",
                    "I": "pageup", "Q": "pagedown"}.get(msvcrt.getwch(), "")
        return {"\r": "enter", "\n": "enter",
                "\x04": "back", "\x1b": "back", "\x03": "back"}.get(ch, ch.lower())
    import select as _select
    with keyboard():
        fd = sys.stdin.fileno()
        try:
            ch = os.read(fd, 1)
        except KeyboardInterrupt:
            return "back"
        if ch == ESC.encode():
            # An escape sequence, or the Esc key alone: what tells them apart
            # is whether anything follows it straight away. Read to the end of
            # the sequence, so a key is never left half-read for the next one.
            more = b""
            while _select.select([fd], [], [], 0.03)[0]:
                more += os.read(fd, 1)
                if len(more) >= 2 and (more[-1:].isalpha() or more[-1:] == b"~"):
                    break
                if len(more) > 6:
                    break
            if not more:
                return "back"
            return _SEQUENCES.get(more, "")
        if ch and ch[0] >= 0xC0:            # the rest of a UTF-8 character
            need = 1 if ch[0] < 0xE0 else 2 if ch[0] < 0xF0 else 3
            ch += os.read(fd, need)
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch in (b"\x04", b"\x03"):             # ctrl+D, ctrl+C: back, as everywhere
        return "back"
    return ch.decode("utf-8", "replace").lower()


def menu(options: list[str], notes: list[str] | None = None, start: int = 0,
         hint: str = "") -> int | None:
    """The list, walked with the arrows.

    Drawn once and then redrawn over itself from where the drawing ended -
    the same trick Show-Menu uses in the PowerShell launcher, for the same
    reason: a menu that scrolls the page is not a menu.

    THE NOTES ARE A COLUMN. Each used to start three spaces after its own
    option, so a list of words of different lengths had its explanations
    zig-zagging down the page; they now start where the longest option ends.

    A LIST LONGER THAN THE WINDOW scrolls inside itself, with a line saying
    how many rows are above and below. Drawn whole, it pushed its own top off
    the screen, and the redraw - which goes back up one line per row - landed
    in the wrong place.

    A digit picks a row, and so does a first letter when only one row starts
    with it. When several do, the letter moves to the next of them instead of
    choosing blindly: "q" on qwen3.8 and qwen36 used to open qwen3.8, always.
    """
    if not options:
        return None
    sel = max(0, min(start, len(options) - 1))
    a, r = accent(), (RESET if accent() else "")
    grey = GREY if a else ""
    hint = hint or f"↑↓ move{SEP}enter select{SEP}ctrl+D back"
    if not _encodes(hint):
        hint = "arrows move - enter select - ctrl+D back"
    col = min(max(len(o) for o in options), max(12, columns() // 3))
    drawn = 0
    top = 0
    with keyboard():
        while True:
            # How many rows fit: the window, less the hint, the blank line and
            # the two "more" markers - and never fewer than three.
            room = max(3, lines() - 6)
            window = len(options) if len(options) <= room else room
            if sel < top:
                top = sel
            elif sel >= top + window:
                top = sel - window + 1
            if drawn:
                print(f"{ESC}[{drawn}A", end="")
            count = 0
            if len(options) > window:
                above = f"  {grey}  ↑ {top} more{r}" if top else ""
                print(f"{ESC}[2K" + above)
                count += 1
            for i in range(top, top + window):
                option = options[i]
                note = notes[i] if notes and i < len(notes) and notes[i] else ""
                label = option.ljust(col) if note else option
                if i == sel:
                    body = f"  {a}{MARK} {label}{r}"
                else:
                    body = f"    {label}"
                line = fit(body, f"   {grey}{note}{r}" if note else "")
                print(f"{ESC}[2K" + line)
                count += 1
            if len(options) > window:
                left = len(options) - top - window
                print(f"{ESC}[2K" + (f"  {grey}  ↓ {left} more{r}" if left else ""))
                count += 1
            print(f"{ESC}[2K")
            print(f"{ESC}[2K  {grey}{hint}{r}", flush=True)
            drawn = count + 2
            try:
                key = read_key()
            except Exception:               # a terminal that cannot go raw has
                return None                 # no menu to offer
            if key == "up":
                sel = (sel - 1) % len(options)
            elif key == "down":
                sel = (sel + 1) % len(options)
            elif key == "home":
                sel = 0
            elif key == "end":
                sel = len(options) - 1
            elif key == "pageup":
                sel = max(0, sel - window)
            elif key == "pagedown":
                sel = min(len(options) - 1, sel + window)
            elif key == "enter":
                return sel
            elif key == "back":
                return None
            elif key.isdigit() and 1 <= int(key) <= min(9, len(options)):
                return int(key) - 1
            elif key:
                hits = [i for i, o in enumerate(options) if o[:1].lower() == key]
                if len(hits) == 1:
                    return hits[0]
                if hits:
                    after = [i for i in hits if i > sel]
                    sel = after[0] if after else hits[0]


def pick(title: str, options: list[str], notes: list[str] | None = None,
         start: int = 0, hint: str = "") -> int | None:
    """A list to choose from: walked with the arrows where the terminal allows
    it, numbered where it does not - a pipe, a log, a test."""
    if not options:
        return None
    print()
    if title:
        say(f"  {title}", "accent")
        print()
    if sys.stdin.isatty() and sys.stdout.isatty():
        return menu(options, notes, start, hint)
    for i, option in enumerate(options, 1):
        note = f"   {GREY}{notes[i - 1]}{RESET}" if notes and notes[i - 1] and accent() else ""
        print(f"    {i}. {option}{note}")
    while True:
        answer = ask("choice", hint="a number, or ctrl+D to go back")
        if answer is None:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        say("    not one of them", "warn")


def choose(title: str, pairs: list[tuple[str, str]], current: str = "") -> str | None:
    """pick() over (value, blurb) pairs, returning the value. The current one
    is where the cursor starts, so Enter alone keeps what is already set."""
    values = [v for v, _ in pairs]
    start = values.index(current) if current in values else 0
    i = pick(title, values, [b for _, b in pairs], start)
    return None if i is None else values[i]


def confirm(title: str, what: str = "yes, do it", instead: str = "no, go back") -> bool:
    """A yes that has to be walked to, with "no" already under the cursor."""
    return pick(title, [instead, what]) == 1
