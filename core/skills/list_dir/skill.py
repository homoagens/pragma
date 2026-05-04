from __future__ import annotations

from datetime import datetime
from pathlib import Path


def list_dir(path: str = ".", show_hidden: bool = False,
             max_entries: int = 200) -> str:
    """
    List the contents of a directory with metadata (type, size, mtime).
    Returns a tabular string or an error message.
    """
    p = Path(path)
    if not p.exists():
        return f"ERROR: path not found: {path}"
    if not p.is_dir():
        return f"ERROR: not a directory: {path}"

    entries = []
    for item in sorted(p.iterdir()):
        if not show_hidden and item.name.startswith("."):
            continue
        try:
            stat = item.stat()
            kind = "dir " if item.is_dir() else "file"
            size = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            entries.append(f"{kind}  {size:>10}  {mtime}  {item.name}")
        except Exception:
            entries.append(f"????  {'?':>10}  {'?':>16}  {item.name}")

    if not entries:
        return f"(empty directory: {path})"

    header = f"type       size  modified          name\n{'-'*60}"
    body   = "\n".join(entries[:max_entries])
    suffix = f"\n... ({len(entries) - max_entries} more)" if len(entries) > max_entries else ""
    return f"{header}\n{body}{suffix}"
