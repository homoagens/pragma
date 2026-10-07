# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""Texts as vectors, so that the memory can be searched by meaning.

OPTIONAL. With no embedding server named, nothing here is used and the search
goes by words, as it always has. A server is named in /configure (the
catalogue's "embedding" entry) or, for a script, in PRAGMA_EMBED_URL. It is any
OpenAI-compatible server that answers POST {url}/embeddings.

WHAT IT IS FOR. The words of a request find a memory only when the two were
written with the same words, in the same language. A model that turns a text
into a vector puts texts that mean similar things near each other whatever
their words: the request becomes a vector, and the memories nearest to it are
the ones offered to the curator. It ranks; it does not judge. What is recalled
is still the curator's choice.

WHAT IS EMBEDDED. Nothing is cut into pieces: what the memory holds is already
written as short units, and each unit is one vector. There are three kinds,
all from one model and so comparable with each other:

    events     what happened: an episode's goal, keywords and narrative.
               These are written once and never rewritten, so an episode's
               event vector is computed once. IT IS THE KEY AN EPISODE IS
               FOUND BY - before a turn, and when a new episode looks for the
               earlier ones it is related to.
    readings   what it means: an episode's interpretation. This is the one
               part of an episode that is rewritten, and each version has a
               vector of its own. A reading is never a search key: an episode
               must not move in the search because it was re-read. The
               vectors are there to say how far a re-reading went, and in
               which direction (see moved()).
    beliefs    a belief's sentence, each formulation it has had. The key a
               belief is found by.

An episode is found by its event and not by event and reading together
because the reading says little about what the episode is about that the
event does not already say, and it is the part that changes.

THE VECTORS ARE KEPT, under the model that made them and the hash of the text:

    <store>/vectors/<model>/<kind>/<hash of the text>.f32

A text has one vector for as long as it exists, so nothing is ever recomputed
or re-indexed: a reading that is rewritten is a new text with a new vector,
and the old one stays for as long as the store keeps the old reading in its
history. A different embedding model starts its own folder.

AND THEY GO WHEN THE TEXT GOES. tidy() removes every vector whose text the
store no longer holds. It needs no server - the name of a file is the hash of
its text alone - and it runs whenever an episode is deleted and at the end of
each consolidation: an episode that is forgotten takes its vectors with it.

IT SAYS WHAT IT IS DOING to whoever is showing the work to a person. Turning a
store into vectors for the first time takes as long as the model's own answer
can, and a screen that names only the curator for those seconds is naming the
wrong one. STATUS_HOOK is told when stored texts are being read and when they
are in hand; with nobody listening, nothing is said.

WHEN IT FAILS it says so and steps aside. An embedding server that does not
answer must not cost a turn its recall: of() and query() return None, LAST_ERROR
says why, and the caller searches by words. It is not asked again for a minute,
so a server that is down is paid for once and not at every turn.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from array import array
from pathlib import Path

import config

LAST_ERROR = ""

KINDS = ("events", "readings", "beliefs")

# Whoever shows the work to a person, when there is one: the terminal's
# renderer. It is told through its `embedding(kind, done, todo, held)` -
#   ("events", 16, 83, 83)   16 of the 83 episodes that had no vector have one
#   ("events", 83, 83, 83)   all of them: 83 are in hand, 83 were read just now
#   ("beliefs", 0, 0, 49)    49 beliefs in hand, none of which had to be read
#   ("request", 0, 1, 0)     the request itself is being read
#   ("", 0, 0, 0)            the server did not answer: there is nothing to show
STATUS_HOOK = None


def _tell(kind: str, done: int, todo: int, held: int) -> None:
    hook = getattr(STATUS_HOOK, "embedding", None) if STATUS_HOOK is not None else None
    if hook is None:
        return
    try:
        hook(kind, done, todo, held)
    except Exception:
        pass                    # showing the work must never be what stops it

_BATCH = 16
_CHARS = 6000                 # of a text sent to the server: a unit is far shorter
_RETRY_AFTER = 60.0
_IDENTITY_FOR = 300.0         # seconds a server's answer about what it serves is trusted
_REMEMBERED = 20000           # vectors held in the process, at 4 KB each
_down_until = 0.0
_identity: dict[str, tuple[str, float]] = {}
_last_query: tuple[str, str, array] | None = None
# A file's name is the hash of its text, so what it holds never changes: a
# vector read once is good for as long as the process lives.
_held: dict[Path, array] = {}


def server() -> dict | None:
    """{"url", "model", "key"} for the embedding server, or None when none is named."""
    try:
        import endpoints
        entry = endpoints.embedding()
    except Exception:
        entry = None
    if entry:
        return entry
    if config.EMBED_URL:
        return {"url": config.EMBED_URL.rstrip("/"), "model": config.EMBED_MODEL, "key": ""}
    return None


def _post(srv: dict, path: str, body: dict | None, timeout: float) -> dict:
    import requests
    headers = {"Authorization": f"Bearer {srv['key']}"} if srv.get("key") else {}
    if body is None:
        r = requests.get(srv["url"] + path, headers=headers, timeout=timeout)
    else:
        r = requests.post(srv["url"] + path, json=body, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def identity(srv: dict) -> str:
    """What the server says it serves, asked once: the name vectors are kept under.

    The name written in the catalogue is what someone typed; a different model
    started on the same port keeps that name and gives vectors from another
    space. What the server itself reports changes with the model.

    Asked again every few minutes, because a conversation can stay open for
    hours and the model behind a port can be changed under it: vectors from
    the new one must not be filed with the old one's. And an answer that could
    not be had is not remembered: the typed name serves for this call only.
    """
    url = srv["url"]
    known = _identity.get(url)
    if known and time.monotonic() - known[1] < _IDENTITY_FOR:
        return known[0]
    named = srv.get("model") or ""
    try:
        data = _post(srv, "/models", None, min(5.0, config.EMBED_TIMEOUT))
        first = (data.get("data") or data.get("models") or [{}])[0]
        named = str(first.get("id") or first.get("model") or first.get("name") or named) or "embedding"
        _identity[url] = (named, time.monotonic())
    except Exception:
        pass
    return named or "embedding"


def _unit(vector) -> array:
    # Some servers answer with one vector per token instead of one per text.
    if vector and isinstance(vector[0], list):
        vector = [sum(column) / len(vector) for column in zip(*vector)]
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return array("f", [x / norm for x in vector])


def _ask(srv: dict, texts: list[str], each=None) -> list[array]:
    """A vector for each text, asked for a few at a time. `each` is called with
    how many are done before every request, for whoever is watching."""
    out: list[array] = []
    for at in range(0, len(texts), _BATCH):
        if each is not None:
            each(at)
        batch = [t[:_CHARS] or " " for t in texts[at:at + _BATCH]]
        data = _post(srv, "/embeddings", {"model": srv.get("model") or identity(srv), "input": batch},
                     config.EMBED_TIMEOUT)
        rows = sorted(data["data"], key=lambda d: d.get("index", 0))
        if len(rows) != len(batch):
            raise RuntimeError(f"asked for {len(batch)} vectors, got {len(rows)}")
        out += [_unit(row["embedding"]) for row in rows]
    return out


def _folder() -> Path:
    return Path(config.DATA_DIR) / "vectors"


def _slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-.") or "embedding"


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()[:24]


def _path(model: str, kind: str, text: str) -> Path:
    return _folder() / _slug(model) / kind / f"{_key(text)}.f32"


def _load(path: Path) -> array | None:
    held = _held.get(path)
    if held is not None:
        return held
    try:
        size = path.stat().st_size
        if not size or size % 4:
            return None
        kept = array("f")
        with open(path, "rb") as fh:
            kept.fromfile(fh, size // 4)
    except Exception:
        return None
    _hold(path, kept)
    return kept


def _hold(path: Path, vector: array) -> None:
    if len(_held) >= _REMEMBERED:
        _held.clear()
    _held[path] = vector


def _save(path: Path, vector: array) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        with open(tmp, "wb") as fh:
            vector.tofile(fh)
        os.replace(tmp, path)
    except Exception:
        pass                    # a vector that could not be kept is computed again


def _failed(e: Exception) -> None:
    global LAST_ERROR, _down_until
    LAST_ERROR = f"{type(e).__name__}: {str(e)[:140]}"
    _down_until = time.monotonic() + _RETRY_AFTER
    _tell("", 0, 0, 0)


def of(texts: list[str], kind: str, tell: bool = True) -> list[array] | None:
    """A unit vector for each text, kept between calls under `kind` - one of
    KINDS. None when there is no server or it did not answer: LAST_ERROR then
    says which.

    `tell=False` for texts that are not being searched: the one episode
    everything else is compared WITH, the two events a re-reading is measured
    against. Said to whoever is watching, they read as "1 memory searched"."""
    global LAST_ERROR
    if kind not in KINDS:
        raise ValueError(f"not a kind of vector: {kind!r}")
    srv = server()
    if srv is None:
        return None
    if time.monotonic() < _down_until:
        return None
    try:
        model = identity(srv)
        paths = [_path(model, kind, t) for t in texts]
        out = [_load(p) for p in paths]
        missing = [i for i, v in enumerate(out) if v is None]
        if missing:
            fresh = _ask(srv, [texts[i] for i in missing],
                         each=(lambda done: _tell(kind, done, len(missing), len(texts))) if tell else None)
            for i, vector in zip(missing, fresh):
                out[i] = vector
                _save(paths[i], vector)
                _hold(paths[i], vector)
        LAST_ERROR = ""
        if tell:
            _tell(kind, len(missing), len(missing), len(texts))
        return out
    except Exception as e:
        _failed(e)
        return None


def query(text: str) -> array | None:
    """The vector of a request. Not kept on disk - no two requests are the same
    - but remembered for the turn, where it is asked for twice."""
    global LAST_ERROR, _last_query
    srv = server()
    if srv is None:
        return None
    if time.monotonic() < _down_until:
        return None
    try:
        model = identity(srv)
        if _last_query and _last_query[:2] == (model, text):
            return _last_query[2]
        _tell("request", 0, 1, 0)
        vector = _ask(srv, [text])[0]
        _last_query = (model, text, vector)
        LAST_ERROR = ""
        return vector
    except Exception as e:
        _failed(e)
        return None


# ── What is embedded ──────────────────────────────────────────────────────────
# One definition of each for everyone who embeds it. A vector is kept under the
# hash of its text, so two callers that built the text differently would each
# compute their own and share nothing.

def event_text(ep: dict) -> str:
    """What an episode is about and what happened in it: the part that is
    written once. The key an episode is found by."""
    return "\n".join([str(ep.get("goal", "") or "").strip(), ", ".join(ep.get("keywords", []) or []),
                      str(ep.get("narrative", "") or "").strip()])


def reading_text(ep: dict) -> str:
    """What an episode means, as it is read now: the part that is rewritten."""
    return str(ep.get("interpretation", "") or "").strip()


def readings(ep: dict) -> list[str]:
    """Every reading an episode has had, the earliest first, the current last."""
    past = sorted((h for h in (ep.get("interpretation_history") or []) if isinstance(h, dict)),
                  key=lambda h: str(h.get("ts", "")))
    return [t for t in [str(h.get("text", "") or "").strip() for h in past] + [reading_text(ep)] if t]


def belief_text(entry: dict) -> str:
    return str(entry.get("text", "") or "").strip()


def formulations(entry: dict) -> list[str]:
    """Every sentence a belief has been, the earliest first, the current last."""
    past = sorted((h for h in (entry.get("text_history") or []) if isinstance(h, dict)),
                  key=lambda h: str(h.get("ts", "")))
    return [t for t in [str(h.get("text", "") or "").strip() for h in past] + [belief_text(entry)] if t]


_sumprod = getattr(math, "sumprod", None)


def nearness(a, b) -> float:
    """How close two unit vectors are: 1 the same direction, 0 unrelated."""
    if len(a) != len(b):
        return 0.0              # kept under one model, asked under another
    if _sumprod is not None:
        return _sumprod(a, b)
    return sum(x * y for x, y in zip(a, b))


def moved(own: dict, before: str, after: str, other: dict) -> dict | None:
    """How far a re-reading took an episode's interpretation, and where to.

    `own` is the episode re-read, `before` and `after` its interpretation on
    either side of the re-reading, `other` the episode in whose light it was
    re-read. Four nearnesses to two fixed points - the episode's own event and
    the other's - and one between the two readings:

        previous    the new reading to the one it replaces
        own_event   the reading to the event it is a reading of: [before, after]
        new_event   the reading to the event that occasioned it:  [before, after]

    A reading that the re-reading leaves nearer to the other episode's event
    than to its own has stopped being about its own episode; drifted() says
    so. None when the vectors cannot be had: nothing is measured by words.
    """
    if not before.strip() or not after.strip():
        return None
    r = of([before.strip(), after.strip()], "readings", tell=False)
    e = of([event_text(own), event_text(other)], "events", tell=False) if r is not None else None
    if r is None or e is None:
        return None
    srv = server()
    return {"previous": round(nearness(r[0], r[1]), 3),
            "own_event": [round(nearness(r[0], e[0]), 3), round(nearness(r[1], e[0]), 3)],
            "new_event": [round(nearness(r[0], e[1]), 3), round(nearness(r[1], e[1]), 3)],
            "model": identity(srv) if srv else ""}


def reworded(before: str, after: str) -> dict | None:
    """How near a belief's new sentence is to the one it replaces: the same
    measure as moved()'s `previous`, for the other thing in the memory that is
    rewritten. None when the vectors cannot be had."""
    if not before.strip() or not after.strip():
        return None
    v = of([before.strip(), after.strip()], "beliefs")
    if v is None:
        return None
    srv = server()
    return {"previous": round(nearness(v[0], v[1]), 3), "model": identity(srv) if srv else ""}


def drifted(measure: dict | None) -> bool:
    """Whether a re-reading, as moved() measured it, took the interpretation
    away from its own episode: the new reading is nearer to the other episode's
    event than to its own, AND it was the re-reading that took it there or
    further. Two episodes of one story have events that resemble each other,
    and a reading can sit nearer to its neighbour's before anyone touches it:
    a re-reading that brings such a reading back towards its own event has not
    drifted.

    Only nearnesses of the same texts are compared with each other, so no
    threshold has to be chosen - how near two unrelated texts are differs from
    one embedding model to the next."""
    if not measure:
        return False
    own_before, own_after = measure["own_event"]
    new_before, new_after = measure["new_event"]
    return own_after < new_after and (own_after - new_after) < (own_before - new_before)


# ── Keeping the folder true to the store ──────────────────────────────────────

def tidy(episodes_dir=None, learnings_path=None) -> int:
    """Remove every vector whose text the store no longer holds; say how many.

    What the store holds is the event of every episode, active or dormant,
    every reading each has had, and every formulation of every belief. Anything
    else in the folder belongs to an episode that was deleted, to a text that
    was edited, or to a layout this file no longer writes.

    It asks no server. It removes nothing when what the store holds cannot be
    established - an episode or the beliefs that could not be read - because
    from here an unreadable store looks like an empty one. Never raises.

    The folder is the one beside the episodes: a caller that names another
    store's episodes tidies that store's vectors, not this one's.
    """
    try:
        import episodes as estore
        root = estore.active_dir(episodes_dir).parent / "vectors"
        if not root.is_dir():
            return 0
        keep: dict[str, set[str]] = {kind: set() for kind in KINDS}
        for d in (estore.active_dir(episodes_dir), estore.dormant_dir(episodes_dir)):
            loaded = estore.load(d)
            if d.is_dir() and len(loaded) != len(list(d.glob("ep_*.json"))):
                return 0
            for _p, ep in loaded:
                keep["events"].add(_key(event_text(ep)))
                keep["readings"].update(_key(t) for t in readings(ep))
        lp = Path(learnings_path) if learnings_path else Path(config.LEARNINGS_PATH)
        if lp.exists():
            entries = json.loads(lp.read_text(encoding="utf-8")).get("entries")
            if not isinstance(entries, list):
                return 0
            for entry in entries:
                keep["beliefs"].update(_key(t) for t in formulations(entry))
        removed = 0
        stale = time.time() - 600       # a write that never finished
        for child in root.iterdir():
            if child.is_file():
                # Vectors used to be kept here directly, under a hash that
                # mixed in the model's name: none of them can be told apart.
                if child.suffix == ".f32":
                    child.unlink(missing_ok=True)
                    removed += 1
                continue
            for kind in KINDS:
                for f in (child / kind).iterdir() if (child / kind).is_dir() else ():
                    if f.suffix == ".f32" and f.stem not in keep[kind]:
                        f.unlink(missing_ok=True)
                        _held.pop(f, None)
                        removed += 1
                    elif f.suffix == ".tmp" and f.stat().st_mtime < stale:
                        f.unlink(missing_ok=True)
        return removed
    except Exception:
        return 0
