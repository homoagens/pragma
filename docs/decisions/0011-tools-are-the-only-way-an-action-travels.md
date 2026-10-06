# 11. Tools are the only way an action travels

- **Date:** 2026-09-24
- **Status:** accepted
- **Where:** [`core/tool_schema.py`](../../core/tool_schema.py), [`core/react.py`](../../core/react.py), [`core/config.py`](../../core/config.py)

## Context

The agent used to write its action as JSON inside its reply, and Pragma
parsed it out afterwards. Nothing constrained the generation, so every quote
and newline of a file being written was the model's own escaping work, and a
mistake could not be recovered by the time it showed. The alternative —
describing the skills to the server as tools — had been available as a
second protocol for two months.

## Decision

Actions travel as tool calls, always. The skills are described to the
server as tools, and a server such as llama.cpp constrains the arguments as
they are generated: a malformed call becomes unrepresentable instead of
merely detectable.

The text protocol was removed, not kept as an option. Keeping it cost a
second prompt, a second set of skills that existed only to work around the
escaping, and a second set of failures to reason about.

## Consequences

- A server that does not implement tool calls cannot run the agent, and
  Pragma says so on the first step.
- The faculties that write memory are not affected: they ask for a JSON
  object, not for a choice of tool.
