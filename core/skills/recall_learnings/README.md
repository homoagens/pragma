# recall_learnings

[D] Retrieve the most relevant entries from the cross-thread learnings store. Pure keyword overlap, no LLM call.

---

## Parameters

- `query` (str, optional): Free text describing the upcoming task. Empty string returns the most recent entries.
- `top_k` (int, optional, default from `LEARNINGS_RECALL_TOP_K`): Number of entries to return.
- `store_path` (str, optional): Override the default store at `config.LEARNINGS_PATH`.
- `kinds` (str, optional): Comma-separated filter, e.g. `"user_prefs,patterns"`. Empty means all kinds.

## Returns

A bullet list, one entry per line: `- (kind) text  [label]` — or `"(no learnings)"`.

## Notes

- No LLM call: scores entries by simple keyword overlap against the query, then sorts by score and recency.
- When the query has no useful tokens (empty or all stopwords), falls back to most recent entries.
- Usually invoked automatically at the START of every task by the orchestrator — but can be called manually any time you want to remind yourself of what you've learned.
- Companion of `session_reflect`, which produces the entries this skill reads.

## Examples

```json
{ "action": "recall_learnings", "args": { "query": "add a comet launcher to a canvas simulation" } }
{ "action": "recall_learnings", "args": { "kinds": "user_prefs,mistakes", "top_k": 10 } }
```
