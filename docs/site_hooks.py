# Copyright (C) 2026 Homo Agens
# SPDX-License-Identifier: AGPL-3.0-or-later
# This file is part of Pragma <https://github.com/homoagens/pragma>.

"""MkDocs hook: a link that leaves docs/ goes to the repository instead.

These pages are written to be read on GitHub first, and there a relative link
to ../../core/react.py opens the file. A site holds only what is under docs/,
so on the site the same link leads nowhere - and most links here are of that
kind, because a map of the code is made of them.

Rather than write every such link twice, or as an absolute URL that would stop
following a file when it moves, the pages keep the relative form and this hook
rewrites it while the site is built: anything that resolves outside docs/ and
inside the repository becomes a link to that file on GitHub. Links between
pages, and links that already name a site, are left alone.

Named in mkdocs.yml under `hooks`. It runs on the Markdown of each page,
before the links are checked, so a strict build still fails on a link that
points at nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

_LINK = re.compile(r"(\]\(\s*)([^)\s]+)")
_FENCE = re.compile(r"^\s*(```|~~~)")
_HAS_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*:", re.I)


def on_page_markdown(markdown, page, config, files):
    repo = (config.get("repo_url") or "").rstrip("/")
    if not repo:
        return markdown
    branch = (config.get("extra") or {}).get("repo_branch", "master")
    docs = Path(config["docs_dir"]).resolve()
    root = Path(config["config_file_path"]).resolve().parent
    here = (docs / page.file.src_uri).parent

    def outside(match: re.Match) -> str:
        target = match.group(2)
        if target.startswith("#") or _HAS_SCHEME.match(target):
            return match.group(0)
        path, sep, anchor = target.partition("#")
        dest = (here / path).resolve()
        if docs in dest.parents and dest.suffix.lower() == ".md":
            return match.group(0)                   # a page of the site
        if dest != root and root not in dest.parents:
            return match.group(0)                   # not ours to point at
        kind = "tree" if dest.is_dir() else "blob"
        where = dest.relative_to(root).as_posix()
        return f"{match.group(1)}{repo}/{kind}/{branch}/{where}{sep}{anchor}"

    out, fenced = [], False
    for line in markdown.split("\n"):
        if _FENCE.match(line):
            fenced = not fenced
        out.append(line if fenced else _LINK.sub(outside, line))
    return "\n".join(out)
