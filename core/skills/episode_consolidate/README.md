# episode_consolidate

Consolidate a finished session transcript into a structured episodic memory record; when similar past episodes exist, also distill semantic assertions (with sources and confidence).

---

## Parameters

- `transcript` (str): The session narrative — user request, thoughts, actions, observations, final conclusion. Required (returns ERROR if empty).
- `workspace` (str, optional): The working directory of the session. Stored on the episode (recall boosting) and used as the label of new assertions.
- `source` (str, optional): Provenance tag, e.g. `"batch"` or `"ui"`.
- `store_dir` (str, optional): Episode store override. Default `config.EPISODES_DIR` (`~/.pragma/episodes`).

## Returns

- `"OK: episode ep_... saved (N surprises); semantic pass skipped (no similar episodes yet)"` — first sessions on a theme.
- `"OK: episode ep_... saved (N surprises); semantics: +A assertions, C confirmed, X contradicted"` — when the abstraction step ran.
- `"ERROR: ..."` on empty transcript, LLM failure, or I/O failure.

## Notes

- Two LLM calls at most; the second (abstraction) only runs when at least one thematically similar past episode exists.
- The episode separates **facts** (`narrative`, written once, never rewritten) from **meaning** (`interpretation`, mutable). `surprises` — deviations from expectation — are the most important field and initialize the episode's salience.
- A new semantic assertion requires at least `SEMANTIC_MIN_SOURCES` (default 2) distinct source episodes: a pattern seen once is an anecdote. Enforcement is deterministic — assertions citing unknown or too few episodes are dropped regardless of what the model proposes.
- Confirmations raise an assertion's confidence (+0.1, cap 0.95); contradictions lower it (−0.2, floor 0.05) and, after `SEMANTIC_RETIRE_CONTRADICTIONS` (default 2), retire it from recall.
- Normally invoked by the runtime at the end of a task (batch `--memory`), not by the agent itself. For structured output use `episode_consolidate_detailed()`.

## Examples

```json
{ "action": "episode_consolidate", "args": { "transcript": "USER: ...\nTHOUGHT: ...\nACTION: ...\nOBS: ...\nFINAL: ...", "workspace": "C:\\proj", "source": "batch" } }
```
