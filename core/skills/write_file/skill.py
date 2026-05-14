from __future__ import annotations

from pathlib import Path


def write_file(path: str, content: str, encoding: str = "utf-8",
               create_parents: bool = True, overwrite: bool = False) -> str:
    """
    Create a file with the given content.

    By default REFUSES to overwrite existing files. Rewriting a whole file
    is expensive (the entire content travels through the JSON args of the
    LLM response) and a frequent cause of finish_reason=length truncation.
    Use the surgical skills for existing files:
        replace_in_file / insert_after / insert_before / append_file / edit_file

    Parameters
    ----------
    path           : target file path
    content        : text to write
    encoding       : file encoding (default utf-8)
    create_parents : if True, create intermediate directories
    overwrite      : if True, allow replacing an existing file. Use only
                     when the surgical skills genuinely don't fit (e.g.
                     wholesale regeneration of a small config file).

    Returns
    -------
    "OK: written N bytes to <path>"  on success (with size warning
    appended when content exceeds WRITE_FILE_SOFT_LIMIT bytes),
    "ERROR: file already exists ..." if the file is present and
    `overwrite=False`,
    "ERROR writing ..."              on I/O failure.
    """
    p = Path(path)

    # ── Refuse to clobber an existing file unless explicitly authorized ──
    if p.exists() and not overwrite:
        try:
            current_size = p.stat().st_size
        except Exception:
            current_size = -1
        return (
            f"ERROR: file already exists at {path} "
            f"({current_size} bytes). write_file is for NEW files only.\n"
            f"To modify it, use one of:\n"
            f"  - replace_in_file(path, old, new)   exact substring replace, no LLM\n"
            f"  - insert_after(path, anchor, content)   add a block after a known line\n"
            f"  - insert_before(path, anchor, content)  add a block before a known line\n"
            f"  - append_file(path, content)        add at the end\n"
            f"  - edit_file(path, instruction)      interpret-and-patch via LLM (last resort)\n"
            f"If you truly need to rewrite the whole file from scratch, "
            f"call write_file again with overwrite=True."
        )

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
