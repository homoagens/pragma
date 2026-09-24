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

import os
import sys

ESC = "\033"
GREY, RESET = ESC + "[38;5;242m", ESC + "[0m"


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
    print()
    print(f"  {a}{name}{r}" + (f"  {GREY}{crumbs}{r}" if crumbs and a else
                               (f"  {crumbs}" if crumbs else "")))


def ask(question: str, default: str = "", hint: str = "") -> str | None:
    """One answer, or None for ctrl+D - which goes back, everywhere."""
    shown = f" [{default}]" if default else (f"  {hint}" if hint else "")
    try:
        answer = input(f"  {question}{shown}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return answer or default


def read_key() -> str:
    """One keypress, as a word: up, down, enter, back - or the character.

    Raw mode for one key and straight back out: the alternative is a line
    editor, and a menu that wants Enter after every arrow is not a menu.
    Windows has msvcrt for the same thing, so a page behaves the same there.
    """
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):          # an arrow arrives as two
            return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "")
        return {"\r": "enter", "\n": "enter",
                "\x04": "back", "\x1b": "back", "\x03": "back"}.get(ch, ch.lower())
    import select as _select
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1)
        if ch == ESC.encode():
            # An escape sequence, or the Esc key alone: what tells them apart
            # is whether anything follows it straight away.
            more = b""
            if _select.select([fd], [], [], 0.05)[0]:
                more = os.read(fd, 2)
            return {b"[A": "up", b"[B": "down"}.get(more, "back")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    if ch in (b"\r", b"\n"):
        return "enter"
    if ch == b"\x04":                       # ctrl+D, as everywhere else in Pragma
        return "back"
    if ch == b"\x03":
        raise KeyboardInterrupt
    return ch.decode("utf-8", "replace").lower()


def menu(options: list[str], notes: list[str] | None = None, start: int = 0,
         hint: str = "enter select . ctrl+D back") -> int | None:
    """The list, walked with the arrows.

    Drawn once and then redrawn over itself from where the drawing ended -
    the same trick Show-Menu uses in the PowerShell launcher, for the same
    reason: a menu that scrolls the page is not a menu.

    A number still picks a row, and so does a row's first letter: in a
    terminal that swallows the arrows, the page still works.
    """
    sel = max(0, min(start, len(options) - 1))
    a, r = accent(), (RESET if accent() else "")
    drawn = 0
    while True:
        if drawn:
            print(f"{ESC}[{drawn}A", end="")
        for i, option in enumerate(options):
            note = f"   {GREY}{notes[i]}{RESET}" if notes and notes[i] and a else ""
            body = f"  {'>' if i == sel else ' '} {option}"
            print(f"{ESC}[2K" + (f"{a}{body}{r}" if i == sel else body) + note)
        print(f"{ESC}[2K")
        print(f"{ESC}[2K  {GREY if a else ''}{hint}{r}")
        drawn = len(options) + 2
        try:
            key = read_key()
        except Exception:                   # a terminal that cannot go raw has
            return None                     # no menu to offer
        if key == "up":
            sel = (sel - 1) % len(options)
        elif key == "down":
            sel = (sel + 1) % len(options)
        elif key == "enter":
            return sel
        elif key == "back":
            return None
        elif key.isdigit() and 1 <= int(key) <= len(options):
            return int(key) - 1
        else:
            for i, option in enumerate(options):
                if option[:1].lower() == key:
                    return i


def pick(title: str, options: list[str], notes: list[str] | None = None,
         start: int = 0, hint: str = "enter select . ctrl+D back") -> int | None:
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
