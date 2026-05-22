from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skills._utils import _now


def log_event(message: str, severity: str = "INFO",
              agent_id: str = "baseline", context: str = "",
              log_path: str = "") -> str:
    """
    Write a structured log entry (JSON Lines) to a file.
    severity : DEBUG | INFO | WARN | ERROR
    context  : optional JSON string with additional data
    log_path : optional override; defaults to config.LOG_PATH — the single
               cross-platform Pragma data folder (~/.pragma/pragma.log).
    Returns the entry as a string.
    """
    entry: dict[str, Any] = {
        "ts":       _now(),
        "severity": severity.upper(),
        "agent":    agent_id,
        "message":  message,
    }
    if context:
        try:
            entry["context"] = json.loads(context)
        except json.JSONDecodeError:
            entry["context"] = context

    line = json.dumps(entry, ensure_ascii=False)

    # Resolve the destination: explicit override, else the shared data folder.
    if log_path:
        target = Path(log_path)
    else:
        import config
        target = Path(config.LOG_PATH)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e:
        return f"LOG WRITE ERROR: {e} | entry: {line}"
    return line
