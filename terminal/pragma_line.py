#!/usr/bin/env python3
# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

r"""A line typed by the person, with the keys a terminal has.

Python's input() edits a line only when readline happens to be loaded, and
nothing in Pragma loaded it: every field outside the conversation - a
project's name, an address, a port, the y/n of a command that waits - wrote
^[[D for the left arrow, and ctrl+arrows did the same. Every such field
reads through here instead: prompt_toolkit, as the conversation and the home
screen already do, so the arrows, ctrl+arrows, home/end and the rest are the
same keys everywhere; readline where prompt_toolkit cannot run.

    name = line("  name: ")            # raises EOFError / KeyboardInterrupt, as input()

The conversation's own prompt takes newline_keys(): ctrl+Enter starts a new
line instead of sending. It and the home prompt take redraw_key(): ctrl+L
draws the page again.
"""
from __future__ import annotations

import re
import sys

# ctrl+Enter, as the terminals that tell it from Enter spell it. Most send it
# as ctrl+J (a line feed, where Enter is a carriage return); some as CSI u
# (kitty, foot, WezTerm, Windows Terminal with the keyboard protocol); xterm
# with modifyOtherKeys in its own form. A terminal that sends plain Enter for
# it cannot be told apart: alt+Enter is the key that works there.
_CTRL_ENTER = ("\x1b[13;5u", "\x1b[27;5;13~", "\x1b[13;2u", "\x1b[27;2;13~")


def _registered() -> None:
    """Teach prompt_toolkit's parser the sequences above, as ctrl+J. It reads
    xterm's two as plain Enter of its own accord, which sent the message."""
    try:
        from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
        from prompt_toolkit.keys import Keys
        for seq in _CTRL_ENTER:
            ANSI_SEQUENCES[seq] = Keys.ControlJ
    except Exception:
        pass


def newline_keys(kb) -> None:
    """ctrl+Enter (and alt+Enter, shift+Enter where the terminal says so)
    puts a line break where the cursor is; Enter still sends."""
    _registered()

    @kb.add("c-j")
    @kb.add("escape", "enter")
    def _newline(event):
        event.current_buffer.insert_text("\n")


# What a prompt returns when ctrl+L asked for its page again: nothing a
# person can type, so it is never taken for a line.
REDRAW = "\x00redraw"


def redraw_key(kb, keep: list) -> None:
    """ctrl+L draws the page again, saying what is true now - an endpoint
    that came up, a memory that finished writing. prompt_toolkit's own ctrl+L
    cleared the screen and left the prompt alone on it, page and all gone.
    What was typed goes into keep[0], to be back on the line under the page."""

    @kb.add("c-l")
    def _redraw(event):
        keep[0] = event.current_buffer.text
        event.app.exit(result=REDRAW)


def line(prompt: str) -> str:
    """input(), editable. `prompt` may carry colours."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            from prompt_toolkit import prompt as _prompt
            from prompt_toolkit.formatted_text import ANSI
        except Exception:
            _prompt = None
        if _prompt is not None:
            try:
                return _prompt(ANSI(prompt))
            except (EOFError, KeyboardInterrupt):
                raise
            except Exception:
                pass                    # a console it cannot drive: the plain line below
    return input(_readline(prompt))


_COLOUR = re.compile(r"(\x1b\[[0-9;]*m)")


def _readline(prompt: str) -> str:
    """Load readline, if there is one, and mark the colours in the prompt as
    taking no room - or readline counts them and the cursor lands wrong."""
    try:
        import readline  # noqa: F401  loading it is what gives input() the keys
    except Exception:
        return prompt
    return _COLOUR.sub("\x01\\1\x02", prompt)
