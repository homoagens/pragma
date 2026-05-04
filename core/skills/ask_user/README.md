# ask_user

Pause execution, formulate a clear question via LLM, and collect a response from the user via stdin.

---

## Parameters

- `topic` (str): Subject to ask about.
- `context` (str, optional, default ""): Additional context to help the LLM formulate the question.
- `mode` (str, optional, default "input"): `"input"` (free text), `"confirm"` (y/n), or `"choice"` (option list).

## Returns

User's answer as a string; `"yes"` or `"no"` in `confirm` mode.

## Notes

- If the LLM call fails, the topic is used directly as the question (fallback).
- In `confirm` mode, answers `y`, `yes`, or `1` map to `"yes"`; anything else maps to `"no"`.
- This skill blocks until the user provides input; do not call it in non-interactive pipelines.

## Examples

```json
{ "action": "ask_user", "args": { "topic": "output file path", "context": "The script needs to save results somewhere", "mode": "input" } }
{ "action": "ask_user", "args": { "topic": "overwrite existing file", "context": "C:\\project\\output.csv already exists", "mode": "confirm" } }
{ "action": "ask_user", "args": { "topic": "output format", "context": "Available: json, csv, plain text", "mode": "choice" } }
```

## Do not

- Ask for information you can infer or discover with a skill (`list_dir`, `read_file`, `understand_cwd`)
- Ask multiple questions in one call — one topic per call
- Use `ask_user` for destructive operations without `mode: "confirm"` — always ask for confirmation before deleting or overwriting
- Ask trivial questions the user should not need to answer (e.g. "should I read the file?" — just read it)
