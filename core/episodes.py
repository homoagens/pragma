# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# episodes.py — storage layer for episodic memory: active zone, dormant
# zone, salience decay.
#
# The model: every episode carries a stored `salience` (set at consolidation
# from its surprises, reinforced on recall). What search and forgetting use
# is the EFFECTIVE salience, computed lazily at read time:
#
#     eff = salience * 0.5 ** (age_days / EPISODE_DECAY_HALF_LIFE_DAYS)
#
# where age is the time since the episode was last recalled (or created).
# No background process ever runs: decay is a property of *reading*, and
# the dormancy sweep happens at consolidation time — the session's natural
# "sleep" moment.
#
# Zones:
#   episodes/            active — searched by recall and by the abstraction pass
#   episodes/dormant/    faded  — out of active search, revivable on demand
#
# True deletion is opt-in (EPISODE_DELETE_AFTER_DAYS > 0) and never touches
# an episode that is still referenced: linked by an active episode or cited
# as a source by a semantic assertion. Forgetting means inaccessibility,
# not destruction of provenance.

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import config
try:                      # core/ is normally on sys.path directly
    import clock
except ImportError:       # imported as a package instead
    from core import clock

DORMANT_SUBDIR = "dormant"


def now_iso() -> str:
    return clock.stamp()


def _parse_ts(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except Exception:
        return None


def reinforced(salience: float, factor: float = 1.0) -> float:
    """The stored salience after one recall.

    Under the default rule each recall closes a fixed fraction of what is left
    between the value and 1.0, so the increment shrinks as an episode grows
    strong and is largest for one that had almost faded. Ordering by the
    formation judgement survives any number of recalls, and no clamp is needed
    because the ceiling is a limit rather than a wall.

    `factor` scales the increment by what the recall was worth. A fragment
    fetched to see how a file is laid out and one fetched because of what it
    means are both recalls, and crediting them equally is what let a routine
    episode draw level with a consequential one.

    EPISODE_RECALL_RULE=additive restores the flat +boost of the frozen
    revision, under which four recalls were worth the whole judgement.
    """
    s = float(salience)
    boost = getattr(config, "EPISODE_RECALL_BOOST", 0.10) * max(0.0, float(factor))
    if getattr(config, "EPISODE_RECALL_RULE", "asymptotic") == "additive":
        return min(1.0, s + boost)
    return s + boost * (1.0 - s)


def age_days(ep: dict, now: datetime | None = None) -> float:
    """Days since the episode was last recalled (or created, if never)."""
    ref = _parse_ts(ep.get("last_recalled") or "") or _parse_ts(ep.get("ts") or "")
    if ref is None:
        return 0.0
    now = now or clock.now()
    return max(0.0, (now - ref).total_seconds() / 86400.0)


def effective_salience(ep: dict, now: datetime | None = None) -> float:
    """Stored salience discounted by time since last recall. A recall
    resets the age, so remembering literally keeps the memory alive."""
    raw = float(ep.get("salience", 0.5))
    half = getattr(config, "EPISODE_DECAY_HALF_LIFE_DAYS", 30.0)
    if half <= 0:
        return raw  # decay disabled
    return raw * (0.5 ** (age_days(ep, now) / half))


def active_dir(store=None) -> Path:
    return Path(store) if store else Path(config.EPISODES_DIR)


def dormant_dir(store=None) -> Path:
    return active_dir(store) / DORMANT_SUBDIR


def load(directory: Path) -> list[tuple[Path, dict]]:
    """All well-formed episodes in `directory` (non-recursive)."""
    out: list[tuple[Path, dict]] = []
    if not directory.is_dir():
        return out
    for p in sorted(directory.glob("ep_*.json")):
        try:
            out.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return out


def write_json(path: Path, obj) -> None:
    """Write JSON so a reader never sees a half-written file.

    The store is no longer touched by one process at a time: consolidation
    runs in its own process while a conversation may be open against the same
    memory, and the curator reads learnings.json on every turn. A plain
    write_text truncates the file and then fills it, so a reader arriving in
    between gets a syntax error - which surfaces as a memory that briefly
    knows nothing, and is indistinguishable from a store that was never
    written.

    Write beside the target, then rename. os.replace is atomic on Windows and
    POSIX alike: the reader sees the old file or the new one, never neither.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, path)


def save(path: Path, ep: dict) -> None:
    write_json(path, ep)


def to_dormant(path: Path, ep: dict, store=None) -> Path:
    """Move an episode file to the dormant zone, stamping dormant_since."""
    d = dormant_dir(store)
    d.mkdir(parents=True, exist_ok=True)
    ep["dormant_since"] = now_iso()
    new_path = d / path.name
    save(new_path, ep)
    path.unlink(missing_ok=True)
    return new_path


def revive(path: Path, ep: dict, store=None) -> Path:
    """Bring a dormant episode back to the active zone. The recall that
    triggered the revival refreshes last_recalled, so the age (and thus
    the effective salience) resets — the memory is alive again."""
    ep.pop("dormant_since", None)
    ep["last_recalled"] = now_iso()
    a = active_dir(store)
    a.mkdir(parents=True, exist_ok=True)
    new_path = a / path.name
    save(new_path, ep)
    path.unlink(missing_ok=True)
    return new_path


def _protected_ids(store=None, learnings_path=None) -> set[str]:
    """Episode ids that must never be hard-deleted: linked by an active
    episode, or cited as a source by any semantic assertion (provenance)."""
    protected: set[str] = set()
    for _p, ep in load(active_dir(store)):
        protected.update(str(x) for x in ep.get("links", []) or [])
    lp = Path(learnings_path) if learnings_path else Path(config.LEARNINGS_PATH)
    try:
        data = json.loads(lp.read_text(encoding="utf-8"))
        for e in data.get("entries", []):
            protected.update(str(x) for x in e.get("sources", []) or [])
    except Exception:
        pass
    return protected


def sweep(store=None, learnings_path=None) -> dict:
    """Forgetting maintenance, run at consolidation time.

    1. Active episodes whose effective salience fell below
       EPISODE_DORMANT_THRESHOLD move to the dormant zone.
    2. If EPISODE_DELETE_AFTER_DAYS > 0, dormant episodes older than that
       (and referenced by nothing) are deleted for good.

    Returns {"dormant": [ids...], "deleted": [ids...]}. Never raises —
    forgetting must not break remembering.
    """
    result = {"dormant": [], "deleted": []}
    try:
        threshold = getattr(config, "EPISODE_DORMANT_THRESHOLD", 0.15)
        now = clock.now()
        for p, ep in load(active_dir(store)):
            if effective_salience(ep, now) < threshold:
                to_dormant(p, ep, store)
                result["dormant"].append(ep.get("id", p.stem))

        delete_after = getattr(config, "EPISODE_DELETE_AFTER_DAYS", 0)
        if delete_after > 0:
            protected = _protected_ids(store, learnings_path)
            for p, ep in load(dormant_dir(store)):
                if ep.get("id") in protected:
                    continue
                since = _parse_ts(ep.get("dormant_since") or "")
                if since is None:
                    continue
                if (now - since).total_seconds() / 86400.0 > delete_after:
                    p.unlink(missing_ok=True)
                    result["deleted"].append(ep.get("id", p.stem))
    except Exception:
        pass
    return result
