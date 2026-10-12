# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

from __future__ import annotations


def web_search(query: str, num_results: int = 10) -> str:
    """
    [G] Query DuckDuckGo. Returns ranked snippets and URLs.

    DuckDuckGo is the only engine: it needs no API key, and the library is in
    requirements.txt. A Serper branch used to sit here, reading a key that
    config never defined, so choosing it could only ever return an error.

    Note: the quality of the query decides the quality of the results;
    phrasing it well is the calling agent's job.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return "ERROR: DDGS library not installed. Run: pip install ddgs"
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
    except Exception as e:
        return f"ERROR: DuckDuckGo search failed — {e}"

    if not results:
        return "NO RESULTS"

    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. [{r.get('title', '')}] {r.get('href', '')}")
        body = r.get("body", "")
        if body:
            lines.append(f"   {body[:200]}")
        lines.append("")

    return "\n".join(lines).strip()
