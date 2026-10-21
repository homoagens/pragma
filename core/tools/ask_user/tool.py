# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations


def ask_user(topic: str = "", context: str = "", mode: str = "input",
             prompt: str = "", question: str = "") -> str:
    """Ask the person something: a free answer, or yes or no.

    Every runner puts in its own, because only the runner knows whether
    anyone is there to answer: the conversation asks at the terminal, /serve
    and a batch run say that nobody can. This one is what is left for a
    runner that forgot - it says the same as theirs, and never waits on a
    keyboard nobody is at. The folder stays for its README, which is how the
    model learns what the tool is for.
    """
    if mode == "confirm":
        return "no - nobody can confirm here. Do not take it as permission."
    return ("Nobody can answer here. Carry on with your best judgment, or end with "
            "what you need and why.")
