# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# checkpoint.py — undo for file edits.
#
# The agent edits real files, and until now a bad edit had no way back: git
# helps only if the workspace is a repository AND the work was committed, and
# many workspaces are neither. Without a way back the safe strategy is timid
# edits; with one, an ambitious change becomes affordable.
#
# The snapshot is automatic. A safety net that must be remembered is a safety
# net that is missing exactly when it is needed, so the first time a session
# touches a file, its original content is copied aside. Later edits to the
# same file do not overwrite that copy: reverting means going back to how the
# file was BEFORE the session, not before the last of many edits.
#
# Everything lives under <workspace>/.pragma_checkpoints/<session>/ and is
# addressed by the file's path relative to the workspace.

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

CHECKPOINT_DIRNAME = ".pragma_checkpoints"
_MANIFEST = "manifest.json"

# Set once per run by the runner; None disables snapshotting entirely.
_session_dir: Path | None = None
_root: Path | None = None

# THE TURN, beside the session. The session keeps each file as it was before
# the FIRST edit of the session, which is what `revert` needs. The critic needs
# something else: the file as it was before THIS turn, so that what it is shown
# is what this turn did and nothing older - in a conversation, the session is
# every turn since the project opened. Held in memory only (a turn touches a
# handful of files), reset by begin_turn(), never written anywhere.
_TURN_CAP = 200_000              # characters; a larger file is not diffed
UNREADABLE = "\0"                # before-text of a file too large or not text
_turn: dict[str, str | None] | None = None


def begin_session(workspace: str, session_id: str = "") -> Path | None:
    """Open a checkpoint session for `workspace`. Returns its directory."""
    global _session_dir, _root
    try:
        root = Path(workspace).resolve()
        if not root.is_dir():
            return None
        sid = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        d = root / CHECKPOINT_DIRNAME / sid
        d.mkdir(parents=True, exist_ok=True)
        _root, _session_dir = root, d
        return d
    except Exception:
        _root = _session_dir = None
        return None


def root() -> Path | None:
    """The workspace the open session belongs to, or None."""
    return _root


def begin_turn() -> None:
    """Start remembering files as they are before this turn's first edit."""
    global _turn
    _turn = {}


def turn_before() -> dict[str, str | None]:
    """{relative path: its text before this turn, None if it did not exist}.

    UNREADABLE stands for a file that existed but is too large or not text.
    """
    return dict(_turn or {})


def _remember_turn(p: Path, rel: str) -> None:
    if _turn is None or rel in _turn:
        return
    if not p.is_file():
        _turn[rel] = None
        return
    try:
        if p.stat().st_size > _TURN_CAP:
            _turn[rel] = UNREADABLE
            return
        raw = p.read_bytes()
        _turn[rel] = UNREADABLE if b"\0" in raw[:4096] else raw.decode("utf-8", "replace")
    except Exception:
        _turn[rel] = UNREADABLE


def _slug(rel: str) -> str:
    """Flat, collision-free name for a nested path."""
    safe = rel.replace("\\", "/").replace("/", "__")
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8]
    return f"{digest}_{safe}"[:150]


def _load_manifest() -> dict:
    if not _session_dir:
        return {}
    p = _session_dir / _MANIFEST
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_manifest(m: dict) -> None:
    if not _session_dir:
        return
    try:
        (_session_dir / _MANIFEST).write_text(
            json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def snapshot(path: str) -> None:
    """Preserve a file's pre-session state. Idempotent, and never raises —
    losing a snapshot must never break the edit the agent is making."""
    if not _session_dir or not _root:
        return
    try:
        p = Path(path)
        if not p.is_absolute():
            p = _root / p
        p = p.resolve()
        if CHECKPOINT_DIRNAME in p.parts:
            return
        try:
            rel = p.relative_to(_root).as_posix()
        except ValueError:
            return          # outside the workspace: not ours to restore
        _remember_turn(p, rel)
        m = _load_manifest()
        if rel in m:
            return          # already captured before the first edit
        if not p.is_file():
            # Recording a file that did not exist lets revert delete it again.
            m[rel] = {"existed": False, "ts": datetime.now(timezone.utc)
                      .strftime("%Y-%m-%dT%H:%M:%SZ")}
            _save_manifest(m)
            return
        dest = _session_dir / _slug(rel)
        shutil.copy2(p, dest)
        m[rel] = {"existed": True, "copy": dest.name,
                  "size": p.stat().st_size,
                  "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        _save_manifest(m)
    except Exception:
        return


def list_entries() -> list[tuple[str, bool]]:
    """(relative path, existed before the session) for everything captured."""
    return [(k, bool(v.get("existed"))) for k, v in sorted(_load_manifest().items())]


def restore(target: str = "") -> tuple[list[str], list[str]]:
    """Put files back as they were before this session.

    target: one path (relative or absolute); empty restores everything.
    Returns (restored, failed).
    """
    restored: list[str] = []
    failed: list[str] = []
    if not _session_dir or not _root:
        return restored, ["no checkpoint session is active"]

    m = _load_manifest()
    if not m:
        return restored, ["nothing was captured in this session"]

    wanted = None
    if target:
        t = Path(target)
        if not t.is_absolute():
            t = _root / t
        try:
            wanted = t.resolve().relative_to(_root).as_posix()
        except Exception:
            wanted = target.replace("\\", "/")

    for rel, info in m.items():
        if wanted and rel != wanted:
            continue
        dest = _root / rel
        try:
            if not info.get("existed"):
                # It did not exist before: undoing its creation means removing it.
                if dest.is_file():
                    dest.unlink()
                restored.append(f"{rel} (removed — it was created this session)")
                continue
            src = _session_dir / info.get("copy", "")
            if not src.is_file():
                failed.append(f"{rel} (snapshot missing)")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            restored.append(rel)
        except Exception as e:
            failed.append(f"{rel} ({e})")

    if wanted and not restored and not failed:
        failed.append(f"{wanted} was not modified in this session")
    return restored, failed
