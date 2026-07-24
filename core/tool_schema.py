# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

# tool_schema.py — describe the skill palette as OpenAI-style `tools`.
#
# WHY THIS EXISTS. Pragma asks the model to emit its action as JSON inside
# free text, then parses it. Nothing constrains the generation, so a model
# that drifts is only caught afterwards, with the step already lost. Measured
# over 27 write_file calls on a real benchmark: 11 failed, none of them by
# hitting the token limit — the model simply stopped mid-structure or answered
# in prose. A harness on the SAME model and server, using native tool calls,
# does not have this failure mode: llama.cpp compiles the tool definitions
# into a grammar and constrains the sampler token by token, so malformed
# arguments become unrepresentable rather than merely detectable.
#
# This module is the translation layer: skill signatures and their READMEs,
# which already drive the text protocol, become JSON Schema. Nothing here
# changes behaviour — it only produces a description. Wiring it up is a
# separate, flag-controlled step.
#
# The memory faculties (consolidator, abstractor, curator, reconsolidator) do
# NOT go through this. They ask for a domain JSON object, not for a tool
# choice, and they keep their existing protocol untouched: the evaluation
# corpus stays reproducible.

from __future__ import annotations

import inspect
import typing
from pathlib import Path

SKILLS_DIR = Path(__file__).parent / "skills"

# Injected by the runner, never chosen by the model.
_HIDDEN_PARAMS = {"context", "stop_event", "self", "cls"}

_PRIMITIVES = {
    str: "string", int: "integer", float: "number", bool: "boolean",
    list: "array", dict: "object",
}


def _json_type(annotation) -> dict:
    """Map a Python annotation to a JSON Schema fragment.

    Unknown or unrepresentable annotations deliberately produce {} — an
    unconstrained value — rather than a guess. A wrong type in the schema is
    worse than an absent one: the grammar would reject arguments the skill
    would have accepted.
    """
    if annotation is inspect.Parameter.empty:
        return {}
    if annotation in _PRIMITIVES:
        return {"type": _PRIMITIVES[annotation]}

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    if origin in (list, set, tuple):
        inner = _json_type(args[0]) if args else {}
        return {"type": "array", "items": inner or {}}
    if origin is dict:
        return {"type": "object"}
    if origin is typing.Union:
        # Optional[X] is Union[X, None]: describe X, nullability is carried by
        # the parameter being optional rather than by the type.
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _json_type(non_none[0])
        return {}

    # Strings survive `from __future__ import annotations`, which turns every
    # annotation into its source text.
    if isinstance(annotation, str):
        base = annotation.split("|")[0].strip().strip("'\"")
        for py, js in (("str", "string"), ("int", "integer"),
                       ("float", "number"), ("bool", "boolean"),
                       ("list", "array"), ("dict", "object")):
            if base == py or base.startswith(py + "["):
                return {"type": js}
    return {}


def _description(name: str, fn) -> str:
    """One-line purpose, from the same README that feeds the text protocol.

    Keeping a single source means the two protocols can never describe a skill
    differently.
    """
    readme = SKILLS_DIR / name / "README.md"
    if readme.is_file():
        try:
            head = readme.read_text(encoding="utf-8").split("---")[0]
            for ln in head.splitlines():
                s = ln.strip()
                if s and not s.startswith("#"):
                    return s
        except Exception:
            pass
    doc = inspect.getdoc(fn) or ""
    for ln in doc.splitlines():
        s = ln.strip()
        if s:
            return s
    return f"Run the {name} skill."


def schema_for(name: str, fn) -> dict | None:
    """OpenAI-style tool definition for one skill, or None if unusable."""
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        return None

    props: dict = {}
    required: list[str] = []
    for p in sig.parameters.values():
        if p.name in _HIDDEN_PARAMS:
            continue
        if p.kind in (inspect.Parameter.VAR_POSITIONAL,
                      inspect.Parameter.VAR_KEYWORD):
            continue          # *args / **kwargs cannot be described
        frag = _json_type(p.annotation)
        if p.default is not inspect.Parameter.empty and p.default is not None:
            # The default is documentation in itself: it tells the model what
            # happens when it says nothing.
            frag = dict(frag)
            frag["description"] = f"default: {p.default!r}"
        props[p.name] = frag
        if p.default is inspect.Parameter.empty:
            required.append(p.name)

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": _description(name, fn),
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
                # The whole point is to make invented arguments impossible.
                "additionalProperties": False,
            },
        },
    }


def build_tools(skills: dict, names=None) -> list[dict]:
    """The `tools` array for a palette, optionally restricted to `names`.

    Restricting matters: every schema is sent on every request, so the palette
    is a per-call token cost, unlike the text summary it replaces.
    """
    wanted = set(names) if names is not None else None
    out = []
    for name, fn in skills.items():
        if wanted is not None and name not in wanted:
            continue
        s = schema_for(name, fn)
        if s:
            out.append(s)
    return out
