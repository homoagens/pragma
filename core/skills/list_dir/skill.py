from __future__ import annotations

from datetime import datetime
from pathlib import Path


# Size thresholds used to suggest the cheaper exploration skill in the hint
# column. The agent learns to gate read_file behind file_outline for files
# that are big enough to justify the extra call.
_HINT_OUTLINE_MIN  = 2_000      # bytes — below this, read_file directly is fine
_HINT_GREP_MIN     = 20_000     # bytes — above this, outline or grep_search


def _hint_for(item: Path, size: int) -> str:
    """Return a short suggestion shown in the rightmost column."""
    if item.is_dir():
        return ""
    suffix = item.suffix.lower()
    # Extensions for which file_outline has a structural parser
    outlineable = suffix in (
        ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
        ".md", ".markdown", ".json",
    )
    if size >= _HINT_GREP_MIN:
        if outlineable:
            return "  <- large: file_outline or grep_search"
        return "  <- large: grep_search recommended"
    if size >= _HINT_OUTLINE_MIN and outlineable:
        return "  <- use file_outline first"
    return ""


def list_dir(path: str = ".", show_hidden: bool = False,
             max_entries: int = 200) -> str:
    """
    List the contents of a directory with metadata (type, size, mtime).
    Returns a tabular string or an error message.
    Files large enough to be expensive to read get a hint suggesting
    file_outline or grep_search instead of a direct read_file.
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
            hint = _hint_for(item, size)
            entries.append(f"{kind}  {size:>10}  {mtime}  {item.name}{hint}")
        except Exception:
            entries.append(f"????  {'?':>10}  {'?':>16}  {item.name}")

    if not entries:
        return f"(empty directory: {path})"

    header = f"type       size  modified          name\n{'-'*60}"
    body   = "\n".join(entries[:max_entries])
    suffix = f"\n... ({len(entries) - max_entries} more)" if len(entries) > max_entries else ""
    return f"{header}\n{body}{suffix}"
