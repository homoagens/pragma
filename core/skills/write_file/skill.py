from __future__ import annotations

from pathlib import Path


def write_file(path: str, content: str, encoding: str = "utf-8",
               create_parents: bool = True) -> str:
    """
    Create or overwrite a file.
    If create_parents=True, creates intermediate directories.
    Returns "OK: written N bytes to <path>" or an error message.
    For large writes (> WRITE_FILE_SOFT_LIMIT) the OK message includes a
    warning that suggests preferring incremental edits next time.
    """
    p = Path(path)
    try:
        if create_parents:
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        n_bytes = len(content.encode(encoding))

        # Soft size warning — informs the agent that a large write happened
        # so on subsequent edits it prefers edit_file / insert_* / replace_in_file.
        try:
            import config
            soft = getattr(config, "WRITE_FILE_SOFT_LIMIT", 0)
        except Exception:
            soft = 0

        if soft > 0 and n_bytes > soft:
            return (
                f"OK: written {n_bytes} bytes to {path}\n"
                f"NOTE: large write ({n_bytes} bytes > soft limit {soft}). "
                f"For future changes on this file prefer edit_file, "
                f"insert_after, insert_before, append_file or replace_in_file "
                f"so you don't risk hitting the token limit."
            )
        return f"OK: written {n_bytes} bytes to {path}"
    except Exception as e:
        return f"ERROR writing {path}: {e}"
