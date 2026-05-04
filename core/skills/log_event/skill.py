from __future__ import annotations

import json
from typing import Any

from skills._utils import _now


def log_event(message: str, severity: str = "INFO",
              agent_id: str = "baseline", context: str = "",
              log_path: str = "agent.log") -> str:
    """
    Write a structured log entry (JSON Lines) to a file.
    severity : DEBUG | INFO | WARN | ERROR
    context  : optional JSON string with additional data
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
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e:
        return f"LOG WRITE ERROR: {e} | entry: {line}"
    return line
