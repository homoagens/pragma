# Give the agent the tools of an MCP server

*For the terminal on Linux; on Windows, inside WSL. [Where Pragma runs](../explanation/interfaces.md).*

An [MCP](https://modelcontextprotocol.io) server publishes tools: a search
over a library, a company's documents, a calendar. Pragma can offer them to
the agent beside its own, and the agent calls them like any other.

Pragma speaks to such a server over HTTP, and uses its tools only — not its
prompts or resources — and only what they return as text.

## Add a server

1. `/configure`, `this machine`, and Enter on `mcp`. The page lists the servers already
   there, and `add`.
2. Enter on `add`, and type the whole address of the server, path included:
   `127.0.0.1:8000/mcp`. `/mcp` is only the usual path; the server's own
   documentation says which it is.
3. Pragma asks the server what it is and shows the answer. If it does not
   answer, you are asked whether to keep the address anyway.
4. Take the suggested name or type your own. The name starts the name of each
   of its tools as the agent sees them — `library__search` — so short is
   better.

A conversation reads the list when its project opens. A server added now is
there the next time you open a project, not in the one already open.

## Choose which of its tools are offered

Enter on the server's name opens its page. Its rows are `tools`, `offered`,
`name`, `address`, `API key` and `remove`.

Enter on `tools` lists what the server publishes, each with how much its
description weighs. Enter switches a tool on or off. **A tool that is on is
described to the model with every request, used or not**, so a server with
thirty tools of which you need two is worth trimming.

`offered` leaves the whole server out without removing it.

## Give it a key

`API key`, on the server's page. The key is sent as a bearer token. As for an
endpoint, it can be typed, or — better — left in an environment variable
whose *name* you give here, so that the key itself is never written to a
file.

## See that it works

The home screen has one row for each server: whether it answers, and how
many of its tools are on. When a project opens, the conversation prints the
same line, and a server that does not answer then has its tools left out for
that conversation, with a line saying so.

In a turn, a call to a server's tool is a line of the ledger like any other,
with what it was called with.

## By hand

The list is a file, `~/.pragma/mcp.json`, and can be written by hand:
[Files](../reference/files.md#mcpjson) has its fields. `PRAGMA_MCP` names
another file. Like the endpoints, it is never part of a snapshot, so no
address or key ends up in a zip.
