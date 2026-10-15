# 19. The agent can be offered the tools of MCP servers

- **Date:** 2026-10-12
- **Status:** accepted
- **Where:** [`core/mcp_client.py`](../../core/mcp_client.py), [`terminal/pragma_configure.py`](../../terminal/pragma_configure.py)

## Context

Every tool the agent had was a folder of Pragma's own. Reaching a service — a
search over a collection of documents, a library, a calendar — meant writing
a tool for it, inside Pragma, for each one. MCP is the way such services now
publish tools for any agent to call.

## Decision

Pragma is an MCP client. The servers are listed in `~/.pragma/mcp.json`,
written from the `mcp` row of `/configure` or by hand. Their tools join the
ones a conversation or a single task is offered, named
`<server>__<tool>` and described by the schema the server publishes, and
what a server says about itself goes into the system prompt.

- HTTP only, tools only, text only: no prompts, no resources, no images.
- A server that does not answer when a conversation starts has its tools
  left out, and a line says so. A call that fails is an error the agent
  reads, like any other.
- Each tool of a server can be switched off. A tool that is offered is
  described to the model with every request, used or not, so connecting a
  server should not mean paying for all of it.
- What a server returns is kept whole. A file cut short can be read again
  in pieces; an answer from a server cannot. `MCP_OBSERVATION_LIMIT` puts a
  limit back.

## Consequences

- The list is read when a conversation starts: a server added in
  `/configure` reaches a project the next time it is opened, and the page
  says so.
- A server listed is trusted like a tool of Pragma's: what it says about
  itself reaches the system prompt, and what it returns reaches the model.
- A long answer from a server can fill much of the context in one step.
- Servers started as local programs (stdio) are not supported.
- It was tried on Linux. On Windows it is the same code, and has been read,
  not tried.
