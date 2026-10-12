# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations

import re
from pathlib import Path


# Regex per riconoscere "top-level" symbols. Volutamente leggeri: niente AST,
# niente dipendenze esterne — funziona su file rotti, in qualsiasi linguaggio
# che segue convenzioni sintattiche simili.

_PY_PATTERNS = [
    (re.compile(r"^\s*class\s+([A-Za-z_]\w*)"),              "class"),
    (re.compile(r"^\s*def\s+([A-Za-z_]\w*)\s*\("),           "def"),
    (re.compile(r"^\s*async\s+def\s+([A-Za-z_]\w*)\s*\("),   "async def"),
    (re.compile(r"^([A-Z_][A-Z0-9_]*)\s*="),                 "const"),
]

# JS: function/class with any indentation; const/let/var ONLY at indent 0
# (otherwise the outline drowns in inner block-scoped variables).
_JS_PATTERNS = [
    (re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"), "function"),
    (re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"),                 "class"),
    (re.compile(r"^(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*="),                "const"),
    (re.compile(r"^(?:export\s+)?let\s+([A-Za-z_$][\w$]*)\s*="),                  "let"),
    (re.compile(r"^(?:export\s+)?var\s+([A-Za-z_$][\w$]*)\s*="),                  "var"),
]

_MD_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$")


def _outline_python(lines: list[str]) -> list[str]:
    out = []
    for i, ln in enumerate(lines, 1):
        for pat, kind in _PY_PATTERNS:
            m = pat.match(ln)
            if m:
                out.append(f"L{i:>5}  {kind:<10} {m.group(1)}")
                break
    return out


def _outline_js(lines: list[str]) -> list[str]:
    out = []
    for i, ln in enumerate(lines, 1):
        for pat, kind in _JS_PATTERNS:
            m = pat.match(ln)
            if m:
                out.append(f"L{i:>5}  {kind:<10} {m.group(1)}")
                break
    return out


def _outline_markdown(lines: list[str]) -> list[str]:
    out = []
    for i, ln in enumerate(lines, 1):
        m = _MD_PATTERN.match(ln)
        if m:
            level   = len(m.group(1))
            heading = m.group(2).strip()
            out.append(f"L{i:>5}  {'  ' * (level - 1)}{'#' * level} {heading}")
    return out


def _outline_json(text: str) -> list[str]:
    import json
    try:
        obj = json.loads(text)
    except Exception:
        return []
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            tp = type(v).__name__
            preview = ""
            if isinstance(v, (str, int, float, bool)):
                preview = f" = {v!r}"
                if len(preview) > 60:
                    preview = preview[:57] + "..."
            elif isinstance(v, list):
                preview = f" ({len(v)} items)"
            elif isinstance(v, dict):
                preview = f" ({len(v)} keys)"
            out.append(f"  {k:<28} {tp}{preview}")
        return out
    if isinstance(obj, list):
        return [f"  list of {len(obj)} items"]
    return [f"  {type(obj).__name__}"]


def file_outline(path: str, tail_lines: int = 5,
                 encoding: str = "utf-8") -> str:
    """
    [D] Cheap structural map of a file — no LLM call, no full content read into context.

    Returns:
      - file size, line count
      - top-level symbols (functions, classes, constants) with line numbers
      - section headings (for Markdown)
      - top-level keys (for JSON)
      - last `tail_lines` lines of the file (useful to know how it ends)

    Use BEFORE read_file on any file you don't already know.
    Lets you decide whether to read_file fully, read_file_section, or just
    use insert_after/replace_in_file with the anchor of interest.

    path       : file to summarize
    tail_lines : how many trailing lines to include verbatim (default 5)
    encoding   : file encoding (default utf-8)
    Returns    : multi-line summary or "ERROR: ..."
    """
    p = Path(path)
    if not p.exists():
        return f"ERROR: file not found: {path}"
    if not p.is_file():
        return f"ERROR: not a file: {path}"

    try:
        text = p.read_text(encoding=encoding)
    except Exception as e:
        return f"ERROR reading {path}: {e}"

    lines     = text.splitlines()
    n_lines   = len(lines)
    n_bytes   = len(text.encode(encoding))
    suffix    = p.suffix.lower()

    header = [
        f"file       : {path}",
        f"size       : {n_bytes} bytes",
        f"lines      : {n_lines}",
        f"extension  : {suffix or '(none)'}",
    ]

    symbols: list[str] = []
    if suffix == ".py":
        symbols = _outline_python(lines)
        kind = "python symbols"
    elif suffix in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"):
        symbols = _outline_js(lines)
        kind = "js/ts symbols"
    elif suffix in (".md", ".markdown"):
        symbols = _outline_markdown(lines)
        kind = "markdown headings"
    elif suffix == ".json":
        symbols = _outline_json(text)
        kind = "json structure"
    else:
        kind = "(no structural parser for this extension)"

    parts = ["\n".join(header), ""]
    parts.append(f"{kind}:")
    if symbols:
        parts.extend(symbols)
    else:
        parts.append("  (none found)")

    if tail_lines > 0 and n_lines > 0:
        tail = lines[-min(tail_lines, n_lines):]
        parts.append("")
        parts.append(f"last {len(tail)} lines:")
        for i, ln in enumerate(tail, n_lines - len(tail) + 1):
            parts.append(f"L{i:>5}  {ln}")

    return "\n".join(parts)
