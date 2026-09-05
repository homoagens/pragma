# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# pragma_brief.py - what a memory looks like at the moment you come back to it.
#
# The launcher shows this before anything else. Entering a session used to be a
# boundary event that meant nothing to the memory, even though the store knows
# exactly when it was last touched and what faded since. The moment of return is
# the one moment a sense of time is worth something.
#
#     python tools/pragma_brief.py <store_dir> [--since <iso>]
#
# Prints one JSON object on stdout and nothing else, so the caller never has to
# parse prose. Every failure is reported inside that object rather than raised:
# a briefing is a courtesy, and no memory should be unopenable because the
# summary of it could not be built.
#
# WHY THIS IS PYTHON AND NOT POWERSHELL. Effective salience, dormancy and tau
# are the deterministic layer of the architecture. Reimplementing the decay in
# the launcher would give the system two implementations of its own physics,
# free to disagree. This asks core/episodes.py the same questions the agent
# asks it.
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT), str(_ROOT / "core")]

import clock                     # noqa: E402
import config                    # noqa: E402
import episodes as estore        # noqa: E402


def _parse(ts):
    return estore._parse_ts(str(ts or ""))


def _episodes(store: Path):
    """(active, dormant) as lists of (path, episode)."""
    return estore.load(store), estore.load(store / "dormant")


def _beliefs(store: Path) -> list[dict]:
    for candidate in (store.parent / "learnings.json", store / "learnings.json"):
        if candidate.is_file():
            try:
                return json.loads(candidate.read_text(encoding="utf-8")).get(
                    "entries", []) or []
            except Exception:
                return []
    return []


def brief(store: Path, since: str = "") -> dict:
    now = clock.now()
    half_life = float(getattr(config, "MEMORY_HALF_LIFE_DAYS", 30.0) or 30.0)
    out: dict = {"store": str(store), "ok": True}

    active, dormant = _episodes(store)
    beliefs = _beliefs(store)
    out["episodes_active"] = len(active)
    out["episodes_dormant"] = len(dormant)
    out["beliefs"] = sum(1 for b in beliefs
                         if str(b.get("status", "active")) != "retired")

    # How long you have been away: the most recent thing the store saw, whether
    # that was an episode being written or an old one being recalled.
    stamps = []
    for _p, ep in active + dormant:
        for key in ("last_recalled", "ts"):
            t = _parse(ep.get(key))
            if t is not None:
                stamps.append(t)
    if stamps:
        last = max(stamps)
        days = max(0.0, (now - last).total_seconds() / 86400.0)
        out["away_days"] = round(days, 2)
        out["tau"] = round(days / half_life, 2) if half_life > 0 else None
        out["last_touched"] = clock.stamp(last)
    else:
        out["away_days"] = None
        out["tau"] = None
        out["last_touched"] = None

    # The newest episode is what you were on. Its goal is the one line worth
    # showing; the narrative belongs to the agent, not to a launcher.
    newest = None
    for _p, ep in active:
        t = _parse(ep.get("ts"))
        if t is not None and (newest is None or t > newest[0]):
            newest = (t, ep)
    out["last_goal"] = (newest[1].get("goal") or "").strip()[:120] if newest else ""

    # What changed while you were gone. Without a `since` there is no "while
    # you were gone" to speak of, so these stay empty rather than guessing.
    cut = _parse(since) if since else None
    went_dormant, revised = [], []
    if cut is not None:
        for _p, ep in dormant:
            t = _parse(ep.get("dormant_since"))
            if t is not None and t > cut:
                went_dormant.append((ep.get("goal") or "").strip()[:90])
        for b in beliefs:
            hist = b.get("text_history") or []
            if any((_parse(h.get("ts")) or cut) > cut for h in hist):
                revised.append((b.get("text") or "").strip()[:90])
    out["went_dormant"] = went_dormant[:5]
    out["went_dormant_n"] = len(went_dormant)
    out["revised"] = revised[:3]
    out["revised_n"] = len(revised)

    # Episodes close enough to the threshold to fade before you next look.
    threshold = float(getattr(config, "EPISODE_DORMANT_THRESHOLD", 0.15))
    fading = []
    for _p, ep in active:
        try:
            s = estore.effective_salience(ep, now)
        except Exception:
            continue
        if s < threshold * 1.5:
            fading.append(round(s, 3))
    out["fading"] = len(fading)

    # What the memory is writing on its own right now, and what it wrote since
    # you were last here. Consolidation left the foreground, so without this
    # line the store simply changes under you between one briefing and the
    # next - which is the failure mode a background worker has to avoid.
    try:
        sys.path.insert(0, str(_ROOT / "tools"))
        import pragma_jobs as jobs
        # `store` here is the EPISODES directory - that is what the launcher
        # passes and what _beliefs already walks up from. Jobs live beside it,
        # in the project's store root.
        root = store.parent if store.name == "episodes" else store
        items = jobs.listing(root, limit=5)
        live = [j for j in items if j.get("status") in ("pending", "running")]
        out["working"] = len(live)
        out["working_note"] = (live[0].get("note") or "") if live else ""
        out["jobs_failed"] = sum(
            1 for j in items if j.get("status") in ("failed", "abandoned"))
    except Exception:
        out["working"] = 0
        out["working_note"] = ""
        out["jobs_failed"] = 0

    # The backend, asked here so the entry page can say whether it is up. It is
    # the thing worth knowing BEFORE choosing "chat", and the launcher clears
    # the screen, so the session banner that used to carry it is gone by the
    # time the page is drawn.
    try:
        import llm_client
        ok, detail = llm_client.ping_models(timeout=4)
        out["serving"] = (getattr(config, "SERVED_MODEL", "")
                          or config.DEFAULT_MODEL) if ok else ""
        # The window the server will actually accept, per slot - llama.cpp has
        # already divided by --parallel. The launcher hands this to the
        # conversation, so a server restarted with a different -c or -np is
        # picked up at the next briefing rather than discovered as a refused
        # request halfway through an evening.
        out["n_ctx"] = config._endpoint_context_window() if ok else 0
        out["context_window"] = config.CONTEXT_WINDOW
        out["context_source"] = getattr(config, "CONTEXT_WINDOW_SOURCE", "")
        # Trimmed to the first clause: the caller shows this under the
        # serving line, and a urllib traceback fragment is noise there.
        # The useful half is before the em dash; what follows it is the
        # urllib traceback, which is noise on a one-line notice.
        _why = ""
        if not ok:
            _why = str(detail).split("—")[0].split(" - ")[0].strip()[:76]
        out["backend"] = "up" if ok else f"down - {_why}"
    except Exception as e:
        out["serving"] = ""
        out["backend"] = f"unknown - {type(e).__name__}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("store", help="the episodes directory of a memory store")
    ap.add_argument("--since", default="",
                    help="ISO instant of the last time this project was opened")
    args = ap.parse_args()
    store = Path(args.store).expanduser()
    try:
        if not store.is_dir():
            data = {"store": str(store), "ok": False,
                    "error": "no such store"}
        else:
            data = brief(store, args.since)
    except Exception as e:                       # never block the launcher
        data = {"store": str(store), "ok": False,
                "error": f"{type(e).__name__}: {str(e)[:160]}"}
    sys.stdout.write(json.dumps(data, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
