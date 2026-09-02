# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""The clock the memory subsystem reads.

Every judgement about *when* something happened, how old it is and how far it
has decayed comes from here. Machine time does not: request latency, run
duration and log stamps measure the hardware, not the memory, and they keep
calling the system clock directly.

Why this exists. Two things went wrong when the clock was read from
``datetime.now()`` in a dozen places. The minutes a session spends generating
text aged the store as if narrative time had passed, so a scenario that
scripted 1.16 half-lives of decay could observe anywhere between 0.79 and 3.94
depending on how fast the model ran. And the current time reached the model
inside its own prompt, so two runs of the same scenario launched at different
times were not the same experiment.

With one clock behind an interface, both become controllable:

    PRAGMA_CLOCK=2026-07-01T09:00:00Z      freeze it at an instant
    PRAGMA_CLOCK_OFFSET=3600               shift it by seconds (may be negative)

and, from code:

    clock.freeze("2026-07-01T09:00:00Z")   pin it
    clock.advance(days=365)                move narrative time forward
    clock.release()                        back to the system clock

``advance`` is what time compression should use. Shifting stored timestamps
backwards, as the demos do now, moves the episodes but leaves everything else
in the present; moving the clock instead moves the whole world consistently,
so decay, episode ages and the date in the prompt all agree.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

STAMP = "%Y-%m-%dT%H:%M:%SZ"

# Set by freeze()/advance(); None means "follow the system clock".
_frozen: datetime | None = None
_offset: timedelta = timedelta(0)


def _from_env() -> tuple[datetime | None, timedelta]:
    """Read PRAGMA_CLOCK and PRAGMA_CLOCK_OFFSET. A malformed value is ignored
    rather than raised: a bad environment variable must not stop the agent
    from remembering."""
    fixed = None
    raw = os.environ.get("PRAGMA_CLOCK", "").strip()
    if raw:
        try:
            fixed = parse(raw)
        except Exception:
            fixed = None
    delta = timedelta(0)
    off = os.environ.get("PRAGMA_CLOCK_OFFSET", "").strip()
    if off:
        try:
            delta = timedelta(seconds=float(off))
        except Exception:
            delta = timedelta(0)
    return fixed, delta


def parse(s: str) -> datetime:
    """An ISO-8601 instant, with or without the trailing Z, as aware UTC."""
    t = s.strip().replace("Z", "+00:00")
    d = datetime.fromisoformat(t)
    return d.astimezone(timezone.utc) if d.tzinfo else d.replace(tzinfo=timezone.utc)


def now() -> datetime:
    """The current instant, aware and in UTC."""
    env_fixed, env_offset = _from_env()
    base = _frozen or env_fixed or datetime.now(timezone.utc)
    return base + _offset + env_offset


def local_now() -> datetime:
    """The same instant in the machine's timezone, for what the user is told."""
    return now().astimezone()


def stamp(when: datetime | None = None) -> str:
    """The timestamp format every stored record uses."""
    return (when or now()).astimezone(timezone.utc).strftime(STAMP)


def today() -> str:
    """Today's date in UTC, as the Curator states it to the model."""
    return now().strftime("%Y-%m-%d")


# ── control, for demos and tests ─────────────────────────────────────────────

def freeze(when: str | datetime | None = None) -> datetime:
    """Pin the clock. With no argument, pin it at the present instant."""
    global _frozen, _offset
    _frozen = parse(when) if isinstance(when, str) else (when or datetime.now(timezone.utc))
    _offset = timedelta(0)
    return _frozen


def advance(seconds: float = 0, **kw) -> datetime:
    """Move narrative time forward. Accepts anything timedelta accepts:
    ``advance(days=365)``, ``advance(hours=6)``, ``advance(900)``.

    Freezes the clock on first use, so that advancing is not silently undone
    by real time continuing to pass underneath."""
    global _frozen, _offset
    if _frozen is None:
        freeze()
    _offset += timedelta(seconds=seconds, **kw)
    return now()


def release() -> None:
    """Back to the system clock."""
    global _frozen, _offset
    _frozen, _offset = None, timedelta(0)


def is_frozen() -> bool:
    """True when the clock is pinned, by code or by the environment."""
    env_fixed, _ = _from_env()
    return _frozen is not None or env_fixed is not None


def describe() -> str:
    """One line for a trace or a log, so a run records the clock it ran under."""
    if not is_frozen() and _offset == timedelta(0):
        env_fixed, env_off = _from_env()
        if env_off == timedelta(0):
            return "system clock"
    return f"{stamp()} (frozen={is_frozen()}, offset={_offset + _from_env()[1]})"
