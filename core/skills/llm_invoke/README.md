# llm_invoke

Make a direct LLM text call with a system prompt and user message.

---

## Parameters

- `system_prompt` (str): System instructions for the LLM.
- `user_message` (str): User turn content.
- `model` (str, optional, default ""): Model name; defaults to `config.DEFAULT_MODEL` if empty.
- `temperature` (float, optional, default -1.0): Sampling temperature; `-1` uses the config default.
- `max_tokens` (int, optional, default 0): Max tokens; `0` uses the config default.

## Returns

LLM response text or `"ERROR: LLM call failed — ..."`.

## Notes

- Thin wrapper around `llm_client.call_llm` with a standard two-message structure.
- Use this when a skill needs raw LLM output without JSON extraction.
