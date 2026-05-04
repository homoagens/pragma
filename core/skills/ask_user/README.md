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
