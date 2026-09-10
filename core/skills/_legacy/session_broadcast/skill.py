# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

from typing import Callable, Optional


# Optional handler for Pattern B (FastAPI + WebSocket).
# A FastAPI server registers it with register_broadcast_handler().
# Without a handler, the skill works as a logging stub.
_BROADCAST_HANDLER: Optional[Callable] = None


def register_broadcast_handler(fn: Callable) -> None:
    """
    Register a real broadcast function.
    Expected signature: fn(channel: str, event_type: str, payload: str) -> None
    Call from the FastAPI server at startup:
        from skills.session_broadcast.skill import register_broadcast_handler
        register_broadcast_handler(my_ws_broadcast)
    """
    global _BROADCAST_HANDLER
    _BROADCAST_HANDLER = fn


def session_broadcast(event_type: str, payload: str = "",
                      channel: str = "default") -> str:
    """
    Publish an event on the session channel (WebSocket or log).
    In Pattern B: the handler is registered by the FastAPI server.
    In standalone baseline: falls back to stdout (stub).
    Returns a confirmation string.
    """
    if _BROADCAST_HANDLER is not None:
        try:
            _BROADCAST_HANDLER(channel, event_type, payload)
            return f"broadcast OK: {channel}/{event_type}"
        except Exception as e:
            return f"broadcast ERROR: {e}"
    # Stub fallback
    msg = f"[session_broadcast] {channel}/{event_type}"
    if payload:
        msg += f": {payload[:120]}"
    print(msg)
    return f"broadcast stub: {channel}/{event_type}"
