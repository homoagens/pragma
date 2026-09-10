# log_event

Append a structured JSON Lines log entry to a file.

---

## Parameters

- `message` (str): Log message text.
- `severity` (str, optional, default "INFO"): Severity level: `DEBUG`, `INFO`, `WARN`, or `ERROR`.
- `agent_id` (str, optional, default "baseline"): Identifier of the logging agent.
- `context` (str, optional, default ""): Optional JSON string with additional structured data.
- `log_path` (str, optional, default "agent.log"): Path of the log file (appended to).

## Returns

The JSON log entry as a string, or `"LOG WRITE ERROR: ..."` on failure.

## Notes

- Each entry is one JSON line with keys: `ts` (ISO 8601 UTC), `severity`, `agent`, `message`, and optionally `context`.
- If `context` is not valid JSON, it is stored as a plain string.
- The log file is opened in append mode; it is created if it does not exist.
