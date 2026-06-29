# code

Delegate a coding task to the specialized coding model (or default model if not configured).

---

## Parameters

- `task` (str): Description of the work — e.g. "write a function that merges two sorted lists".
- `language` (str, optional, default `""`): Target language — e.g. `"python"`, `"typescript"`, `"rust"`. Leave empty if implied by context.
- `context` (str, optional, default `""`): Existing code, specs, or any text the model should read before generating.
- `mode` (str, optional, default `"generate"`): `"generate"` | `"review"` | `"explain"` | `"refactor"` | `"fix"`.

## Returns

The generated/modified code as a plain string (no markdown fences). On failure: `"ERROR: ..."`.

## Notes

- Uses `CODING_MODEL` / `CODING_BASE_URL` / `CODING_API_KEY` if set, otherwise inherits from the default model config (`DEFAULT_MODEL` / `LLM_BASE_URL` / `LLM_API_KEY`).
- All requests go to the same OpenAI-compatible endpoint (`POST {base}/chat/completions`); set `CODING_BASE_URL` only if the coding model lives on a different server.
- Always strips markdown fences if the model adds them anyway.

## Examples

```json
{ "action": "code", "args": { "task": "write a quicksort in Python" } }
{ "action": "code", "args": { "task": "add input validation", "language": "python", "context": "def add(a, b):\n    return a + b", "mode": "fix" } }
{ "action": "code", "args": { "task": "explain what this function does", "context": "<paste code here>", "mode": "explain" } }
```

## Do not

- Do not pass large file contents in `context` if `read_file` + a targeted excerpt would do — context has a token limit.
- Do not use for orchestration decisions or tool calls — `code` is for source code only.
