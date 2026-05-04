from __future__ import annotations

from pathlib import Path


def write_file(path: str, content: str, encoding: str = "utf-8",
               create_parents: bool = True) -> str:
    """
    Create or overwrite a file.
    If create_parents=True, creates intermediate directories.
    Returns "OK: written N bytes to <path>" or an error message.
    """
    p = Path(path)
    try:
        if create_parents:
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return f"OK: written {len(content.encode(encoding))} bytes to {path}"
    except Exception as e:
        return f"ERROR writing {path}: {e}"
