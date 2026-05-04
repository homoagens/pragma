from __future__ import annotations

import re
from pathlib import Path


def grep_search(pattern: str, path: str = ".", file_glob: str = "*",
                ignore_case: bool = False, max_results: int = 100) -> str:
    """
    Search a regex pattern in file contents.
    path      : directory or single file
    file_glob : filter files (e.g. "*.py", "*.md")
    Returns matches in the format "path:lineno: line_content".
    """
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        return f"ERROR: invalid regex '{pattern}': {e}"

    target = Path(path)
    if not target.exists():
        return f"ERROR: path not found: {path}"

    results: list[str] = []
    is_file = target.is_file()
    files   = [target] if is_file else sorted(target.rglob(file_glob))

    for f in files:
        if not f.is_file():
            continue
        display = str(f) if is_file else f.relative_to(target).as_posix()
        try:
            for lineno, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                if regex.search(line):
                    results.append(f"{display}:{lineno}: {line.rstrip()}")
                    if len(results) >= max_results:
                        results.append(f"... (truncated at {max_results} results)")
                        return "\n".join(results)
        except Exception:
            continue

    if not results:
        return f"(no matches for '{pattern}' in '{path}')"
    return "\n".join(results)
