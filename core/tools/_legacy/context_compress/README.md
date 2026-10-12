# context_compress

Summarize and compress a message list when approaching the LLM context limit.

---

## Parameters

- `messages` (list[dict]): Message list in OpenAI style (`[{"role": ..., "content": ...}]`).
- `label` (str, optional, default "context"): Label used for compression logging.
- `model` (str, optional, default ""): Model for summarization; defaults to `config.DEFAULT_MODEL`.

## Returns

Compressed message list (same structure, fewer elements).

## Notes

- Delegates to `memory.compress()` with `threshold=0`, forcing compression regardless of list length.
- The compressed result retains the same role/content structure as the input.
- Use this when message history is too long to fit in the next LLM call.
