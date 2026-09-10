# Retired skills

Nothing in this folder is offered to the agent. The skill loader skips every
folder whose name starts with an underscore, so a skill moved here disappears
from the palette and from the system prompt, and stays readable in the tree.

Retired on 2026-09-10. Usage was counted in 241 archived runs, the sandbox, and
real use of the terminal harness: each skill here had zero purposeful calls.

| skill | why it was retired | what does the job instead |
| --- | --- | --- |
| `code` | delegated code generation to a separate model; never called | the agent writes code directly with `write_file` |
| `edit_file` | patched a file through an extra LLM call; never called | `replace_in_file`, `insert_after`, `insert_before`, `apply_patch` |
| `context_compress` | manual context compression; its one call was the wrong tool | automatic compression inside the loop |
| `llm_invoke` | a raw model call from inside the loop; only one model family used it, to ask itself for a summary, at a temperature it chose | the agent's own reasoning |
| `understand_cwd` | built an environment map | the environment block in the system prompt, plus `list_dir` |
| `todo_create`, `todo_execute` | wrote and dispatched a JSON task list; never called | the loop, one step at a time. Planning is a future system in its own right |
| `call_agent` | delegated to another agent server over HTTP; never called | none yet |
| `parse_document` | LLM extraction from HTML or text; never called | none |
| `session_broadcast` | published events on a WebSocket; from the browser UI era | none |
| `log_event` | appended JSON Lines to an application log; never called | the run logs |

## Not retired, on purpose

`ask_user` looks like a candidate and is not. Chat, batch and the browser server
all replace its implementation with their own, so this `skill.py` never runs.
The name, though, is live: the loop calls it when the step budget runs out, the
prompt tells the agent to use it when stuck, and its README is the description
the agent reads. Moving it here would leave the agent told to call a tool it
has no documentation for.

## Bringing one back

Move the folder back to `core/skills/`, and restore any prompt or config lines
that referred to it (the commit that retired these lists them).
