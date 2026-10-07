# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""Texts as vectors, so that the memory can be searched by meaning.

OPTIONAL. With no embedding server named, nothing here is used and the search
goes by words, as it always has. A server is named in /configure (the
catalogue's "embedding" entry) or, for a script, in PRAGMA_EMBED_URL. It is any
OpenAI-compatible server that answers POST {url}/embeddings - llama.cpp started
with an embedding model is one.

WHAT IT IS FOR. The words of a request find a memory only when the two were
written with the same words, in the same language. A model that turns a text
into a vector puts texts that mean similar things near each other whatever
their words: the request becomes a vector, and the memories nearest to it are
the ones offered to the curator. It ranks; it does not judge. What is recalled
is still the curator's choice.

THE VECTORS ARE KEPT. A memory's vector does not change while its text does
not, so each is computed once and kept beside the store, in `vectors/`, under
the hash of the model's name and the text. A memory rewritten later has a new
hash and is computed again the next time it is searched; a different embedding
model has different hashes and starts its own set. Nothing has to be migrated
or rebuilt by hand: the first search after a server is named fills the folder.

WHEN IT FAILS it says so and steps aside. An embedding server that does not
answer must not cost a turn its recall: of() and query() return None, LAST_ERROR
says why, and the caller searches by words. It is not asked again for a minute,
so a server that is down is paid for once and not at every turn.
"""

from __future__ import annotations

import hashlib
import math
import os
import time
from array import array
from pathlib import Path

import config

LAST_ERROR = ""

_BATCH = 16
_CHARS = 6000                 # of a text sent to the server: a memory is far shorter
_RETRY_AFTER = 60.0
_down_until = 0.0
_identity: dict[str, str] = {}
_last_query: tuple[str, str, list[float]] | None = None


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
    """
    url = srv["url"]
    if url not in _identity:
        named = srv.get("model") or ""
        try:
            data = _post(srv, "/models", None, min(5.0, config.EMBED_TIMEOUT))
            first = (data.get("data") or data.get("models") or [{}])[0]
            named = str(first.get("id") or first.get("model") or first.get("name") or named)
        except Exception:
            pass
        _identity[url] = named or "embedding"
    return _identity[url]


def _unit(vector) -> list[float]:
    # Some servers answer with one vector per token instead of one per text.
    if vector and isinstance(vector[0], list):
        vector = [sum(column) / len(vector) for column in zip(*vector)]
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def _ask(srv: dict, texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for at in range(0, len(texts), _BATCH):
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


def _path(model: str, text: str) -> Path:
    key = hashlib.sha1((model + "\n" + text).encode("utf-8", "replace")).hexdigest()[:24]
    return _folder() / f"{key}.f32"


def _load(path: Path) -> list[float] | None:
    try:
        size = path.stat().st_size
        if not size or size % 4:
            return None
        kept = array("f")
        with open(path, "rb") as fh:
            kept.fromfile(fh, size // 4)
        return list(kept)
    except Exception:
        return None


def _save(path: Path, vector: list[float]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        with open(tmp, "wb") as fh:
            array("f", vector).tofile(fh)
        os.replace(tmp, path)
    except Exception:
        pass                    # a vector that could not be kept is computed again


def _failed(e: Exception) -> None:
    global LAST_ERROR, _down_until
    LAST_ERROR = f"{type(e).__name__}: {str(e)[:140]}"
    _down_until = time.monotonic() + _RETRY_AFTER


def of(texts: list[str]) -> list[list[float]] | None:
    """A unit vector for each text, kept between calls. None when there is no
    server or it did not answer - LAST_ERROR then says which."""
    global LAST_ERROR
    srv = server()
    if srv is None:
        return None
    if time.monotonic() < _down_until:
        return None
    try:
        model = identity(srv)
        paths = [_path(model, t) for t in texts]
        out = [_load(p) for p in paths]
        missing = [i for i, v in enumerate(out) if v is None]
        if missing:
            fresh = _ask(srv, [texts[i] for i in missing])
            for i, vector in zip(missing, fresh):
                out[i] = vector
                _save(paths[i], vector)
        LAST_ERROR = ""
        return out
    except Exception as e:
        _failed(e)
        return None


def query(text: str) -> list[float] | None:
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
        vector = _ask(srv, [text])[0]
        _last_query = (model, text, vector)
        LAST_ERROR = ""
        return vector
    except Exception as e:
        _failed(e)
        return None


def episode_text(ep: dict) -> str:
    """What an episode is about, as one text: what a search by meaning reads.

    One definition for everyone who embeds an episode - the search before a
    turn, and the write side when it looks for what a new memory is related
    to. The vector is kept under the hash of this text, so two callers that
    built it differently would each compute their own and share nothing.
    """
    return "\n".join([str(ep.get("goal", "") or ""), ", ".join(ep.get("keywords", []) or []),
                      str(ep.get("narrative", "") or ""), str(ep.get("interpretation", "") or "")])


def nearness(a: list[float], b: list[float]) -> float:
    """How close two unit vectors are: 1 the same direction, 0 unrelated."""
    if len(a) != len(b):
        return 0.0              # kept under one model, asked under another
    return sum(x * y for x, y in zip(a, b))
