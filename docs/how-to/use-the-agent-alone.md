# Use the agent without memory

*For the terminal on Linux and macOS: the Windows launcher does not have it. [Where each interface stands](../explanation/interfaces.md).*

```bash
pragma --agent
```

starts Pragma with the agent alone. Nothing is recalled before a turn, and
nothing is written to memory when a conversation ends. It holds for every
project opened in that run; the next `pragma` without the flag is as before.

It is worth it when the calls around a turn cost more than the turn — a slow
model, a quick question — or when a conversation should leave no trace in a
project's memory.

## What stays as it was

The memory of every project is left untouched: nothing is read from it and
nothing is added. A memory still being written by an earlier run carries on
in the background, so `/jobs` and `/memory` still answer when typed.

Everything else is the same agent: the workspace, `PRAGMA.md`, the tools,
the [commands that wait for you](allow-commands.md), the MCP servers.

## What the screens say

The pages leave out what there is nothing to do with, and say why:

- The home screen does not offer `/jobs`, and says the memory is off where it
  would say what the memory is searched by.
- The briefing says so in place of the counts and of what changed while you
  were away.
- In a conversation `/help` does not list `/memory` and `/jobs`, and
  `/clear` and **ctrl+D** no longer promise to remember.
- `/status` and `/configure` show only the roles that are still asked
  something, and `/settings` does not ask how much the memory brings to a
  turn.

The flag is kept in the environment as `PRAGMA_AGENT` for that run, because
the home screen, the briefing and the conversation are separate programs and
each has to know. Setting `PRAGMA_AGENT=1` yourself does the same.
