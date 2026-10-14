# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations


def show_image(path: str) -> str:
    """
    Show the person an image file, drawn in their terminal.

    Only a conversation has a person watching a terminal, and only there is
    this offered: agent/chat.py puts in its own version, which draws the
    picture (see agent/picture.py). This one answers anywhere else it might
    be called.
    """
    return ("ERROR: not shown - nobody is watching a terminal in this run\n"
            f"Give the file's path in your answer instead: {path}")
