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

THE SAME NAME IS NOT THE SAME SPACE. A server restarted with another build of
the model, another quantization or another way of pooling still answers to
the name it had, and what it gives is no longer comparable with what was kept:
the memories stand in one space and the request in another, and the search
gets worse without a word. So beside the vectors of each model is kept the
vector of one fixed sentence. The first time a process uses the model that
sentence is asked for again, and when the answer has moved away from the one
kept, the vectors of that model are dropped - to be computed again as they are
needed - and NOTICE says so. rebuild() does the same on request, at once.

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

# The sentence a model's space is recognised by, and how near its vector has
# to stay to the one kept for the two to count as one space. Two runs of the
# same model on the same build agree to four decimals; another quantization of
# it to two or three, which still ranks the same; another model, or the same
# one pooled differently, does not come close.
_CANARY = ("The memory is searched by meaning. La memoria si cerca per significato: "
           "questa frase serve solo a riconoscere lo spazio dei vettori.")
_SAME_SPACE = 0.99
_SPACE_FILE = "space.f32"
_checked: set[tuple[str, str]] = set()        # (folder, model) recognised in this process
# What a person should be told once: vectors found to be from another space
# and dropped. Whoever shows it empties it.
NOTICE = ""


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


def probe(timeout: float = 3.0) -> dict | None:
    """Whether the embedding server that is named is there, for a screen that
    says so beside the model endpoint: None when none is named, otherwise
    {"url", "up", "model", "error"}.

    It asks the server what it serves and nothing else - no text is sent, and
    nothing is kept. A server that answers with an error it is still a server
    that answers: some have no list of models to give, and embed all the same.
    """
    srv = server()
    if srv is None:
        return None
    found = {"url": srv["url"], "up": False, "model": srv.get("model") or "", "error": ""}
    try:
        data = _post(srv, "/models", None, timeout)
        first = (data.get("data") or data.get("models") or [{}])[0]
        found["model"] = str(first.get("id") or first.get("model") or first.get("name") or found["model"])
        found["up"] = True
    except Exception as e:
        found["up"] = getattr(e, "response", None) is not None
        if not found["up"]:
            found["error"] = f"{type(e).__name__}: {str(e)[:100]}"
    return found


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


def _kept(folder: Path) -> list[Path]:
    """Every vector kept under one model's folder, of every kind."""
    return [f for kind in KINDS for f in ((folder / kind).glob("*.f32") if (folder / kind).is_dir() else ())]


def _drop(folder: Path) -> int:
    """Remove every vector under one model's folder; how many went."""
    gone = 0
    for f in _kept(folder):
        try:
            f.unlink()
            gone += 1
        except OSError:
            pass
        _held.pop(f, None)
    return gone


def _ready(srv: dict) -> str:
    """The model's name, once its space has been recognised.

    Asked of the server the first time a process uses a model with this store:
    one sentence, compared with the vector kept for it. A store that has
    vectors and no such vector yet - it was written before this was kept - is
    taken at its word, and the sentence is filed for the next time.
    """
    global NOTICE
    model = identity(srv)
    folder = _folder() / _slug(model)
    mark = (str(folder), model)
    if mark in _checked:
        return model
    now = _ask(srv, [_CANARY])[0]
    was = _load(folder / _SPACE_FILE)
    _held.pop(folder / _SPACE_FILE, None)
    if was is not None and (len(was) != len(now) or nearness(was, now) < _SAME_SPACE):
        gone = _drop(folder)
        if gone:
            NOTICE = (f"the embedding server answers to {model} as before, but its vectors are "
                      f"no longer the same: {gone} kept for this memory were dropped and are "
                      f"being computed again")
        was = None
    if was is None:
        _save(folder / _SPACE_FILE, now)
    _checked.add(mark)
    return model


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
        model = _ready(srv)
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
        model = _ready(srv)
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


def hindsights(ep: dict) -> list[str]:
    """Every line of hindsight an episode has carried, the current one last.
    Kept with the readings: each was measured against the meaning beside it."""
    lines = list(ep.get("hindsight_history") or []) + [ep.get("hindsight")]
    return [t for t in [str(h.get("text", "") or "").strip() for h in lines if isinstance(h, dict)] if t]


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
    than to its own has stopped being about its own episode: the numbers are
    kept so that this can be seen. None when the vectors cannot be had: nothing
    is measured by words.
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


# ── Keeping the folder true to the store ──────────────────────────────────────

def stored_texts(episodes_dir=None, learnings_path=None) -> dict[str, list[str]] | None:
    """Every text of the store that has a vector, by kind: the event of every
    episode, active or dormant, every reading and line of hindsight each has
    had, and every formulation of every belief.

    None when what the store holds cannot be established - an episode or the
    beliefs that could not be read - because from here an unreadable store
    looks like an empty one.
    """
    import episodes as estore
    out: dict[str, list[str]] = {kind: [] for kind in KINDS}
    for d in (estore.active_dir(episodes_dir), estore.dormant_dir(episodes_dir)):
        loaded = estore.load(d)
        if d.is_dir() and len(loaded) != len(list(d.glob("ep_*.json"))):
            return None
        for _p, ep in loaded:
            out["events"].append(event_text(ep))
            out["readings"] += readings(ep) + hindsights(ep)
    lp = Path(learnings_path) if learnings_path else Path(config.LEARNINGS_PATH)
    if lp.exists():
        entries = json.loads(lp.read_text(encoding="utf-8")).get("entries")
        if not isinstance(entries, list):
            return None
        for entry in entries:
            out["beliefs"] += formulations(entry)
    return out


def inventory() -> list[dict]:
    """What is kept beside this store, one entry for each model that left
    vectors: {"model", "events", "readings", "beliefs", "bytes", "in_use",
    "recognised"}. Asks the server only what it serves. Never raises."""
    out = []
    try:
        srv = server()
        using = _slug(identity(srv)) if srv else ""
        root = _folder()
        for child in sorted(root.iterdir()) if root.is_dir() else ():
            if not child.is_dir():
                continue
            row = {"model": child.name, "bytes": 0, "in_use": child.name == using,
                   "recognised": (child / _SPACE_FILE).is_file()}
            for kind in KINDS:
                files = list((child / kind).glob("*.f32")) if (child / kind).is_dir() else []
                row[kind] = len(files)
                row["bytes"] += sum(f.stat().st_size for f in files)
            out.append(row)
    except Exception:
        pass
    return out


def rebuild(each=None) -> dict:
    """Compute every vector of this store again with the model in use, now.

    What is kept for that model is dropped first, the sentence its space is
    recognised by included, and so are the folders of models no longer in use:
    they are copies of nothing the store needs. `each(kind, done, todo)` is
    called as it goes, for whoever is watching.

    Returns {"model", "events", "readings", "beliefs", "dropped", "error"}:
    how many vectors of each kind there are now, how many were removed, and
    why it stopped, when it did. Never raises.
    """
    global _down_until
    said = {"model": "", "dropped": 0, "error": "", **{kind: 0 for kind in KINDS}}
    try:
        srv = server()
        if srv is None:
            said["error"] = "no embedding server is named"
            return said
        held = stored_texts()
        if held is None:
            said["error"] = "the store could not be read: nothing was touched"
            return said
        _down_until = 0.0                   # asked for by a person: try the server now
        model = said["model"] = identity(srv)
        _ask(srv, [_CANARY])                # before anything is removed: is it there at all?
        root, mine = _folder(), _slug(model)
        for child in list(root.iterdir()) if root.is_dir() else ():
            if not child.is_dir():
                continue
            said["dropped"] += _drop(child)
            (child / _SPACE_FILE).unlink(missing_ok=True)
            if child.name != mine:
                import shutil
                shutil.rmtree(child, ignore_errors=True)
        _checked.discard((str(root / mine), model))
        _held.clear()
        _ready(srv)
        for kind in KINDS:
            texts = list(dict.fromkeys(held[kind]))
            paths = [_path(model, kind, t) for t in texts]
            fresh = _ask(srv, texts, each=(lambda done, k=kind, n=len(texts): each(k, done, n)) if each else None)
            for path, vector in zip(paths, fresh):
                _save(path, vector)
            said[kind] = len(texts)
            if each:
                each(kind, len(texts), len(texts))
    except Exception as e:
        said["error"] = f"{type(e).__name__}: {str(e)[:140]}"
    return said


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
        held = stored_texts(episodes_dir, learnings_path)
        if held is None:
            return 0
        keep = {kind: {_key(t) for t in held[kind]} for kind in KINDS}
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
