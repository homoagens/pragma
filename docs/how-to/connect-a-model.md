# Connect a model

*For the terminal. Tried on Linux; [what differs on Windows and in the browser](../explanation/interfaces.md).*

Pragma needs one thing from outside: a model served on an OpenAI-compatible
endpoint — llama.cpp, LM Studio, Ollama, vLLM, or a hosted one. This is how
to point Pragma at it, and how to change that later.

Everything here is done in `/configure`, which opens from the home screen and
from inside a project. It is a page walked with the arrows; **ctrl+D** goes
back one step, everywhere.

## Add the first endpoint

1. Type `/configure`, and press Enter on `add`.
2. Type the address of the server. A host and a port are enough:
   `127.0.0.1:8080`. The `/v1` is added if you leave it out.
3. Pragma asks the server what it is serving and shows the answer. If the
   line says *not connected*, the address is wrong or the server is not
   running: **ctrl+D** stops here with nothing saved.
4. Take the suggested name or type your own. The name is yours: it is what
   the pages will call this server from now on.

The first endpoint you add serves everything. You can stop here.

## Say what the model is

Adding an endpoint leaves you on its own page. To come back to it later:
`/configure`, and Enter on its name. Every row of that page is one question,
with its answer beside it; these four say what the model is:

| Row | What to answer |
|---|---|
| `what it is` | `thinking` if the model reasons before it answers, `instruct` if it answers at once. |
| `what it is for` | `general`, or `coding` if this endpoint is used for writing and fixing code. |
| `who reasons` | Only for a `thinking` model: which roles are asked to reason. |
| `sampling` | `standard` sends nothing and the server keeps the numbers it was started with. `advanced` lets you type them. `ask it` has the model read its own card and fill them in. |

These answers belong to the endpoint, not to a project: every project that
talks to this server inherits them.

## Use a second server for part of the work

A model call is made in one of four roles, listed under
[`/configure`](../reference/commands.md#configure) in the commands reference.
One endpoint can serve them all, or each can have its own — a small fast model
for the recall that runs before every turn, a larger one for the agent.

1. `/configure`, then `add`, for the second server. You are left on its page.
2. Press Enter on `serves`. The page lists the four roles and who answers
   each one now.
3. Press Enter on a role to give it to this endpoint, or on `everything`.
   **ctrl+D** when you are done.

To take a role away from an endpoint, give it to another one from that
endpoint's page. A role that has no endpoint of its own follows the agent's.

## Change an address, a name or a key

`/configure`, and Enter on the endpoint. `name`, `address`, `model` and
`API key` are each a row: Enter on the one you came to change. `model` is
only for a server that hosts several.

A key can be typed, or — better — left in an environment variable whose
*name* you give here, so that the key itself is never written to a file.

## Remove an endpoint

The last row of its page. An endpoint that still serves a role is not
removed: give its roles to another one first.

## A second server, to search the memory by meaning

Optional. Before a turn, Pragma searches the project's memory for what fits
what you typed. It goes by the words the two share, so a memory written in
other words, or in another language, is easily missed. With an *embedding*
server it goes by meaning instead. The same holds when a conversation is
written into memory, and Pragma looks for the memories the new one is related
to.

That is a small model of its own, served on its own port — not the one you
talk to. With llama.cpp, for example:

```
llama-server -m bge-m3-Q8_0.gguf --embedding --port 7190
```

Then, in `/configure`, choose `meaning` and type its address. The page says
whether it answers. From then on the home screen says so too, on the line
under the endpoint, and inside a project the bar under the prompt says
`embedding on`. `/status` says how the memory is being searched.

The first search after that reads the whole memory, once, and takes as long as
that takes: while it does, a line under the status line says how far it is.
From then on only what is new is read.

Nothing has to be rebuilt: the first search after that takes a few seconds
longer, and the rest are as fast as before. If the server stops answering,
the search goes by words again and the screen says so. `meaning`, then `off`,
turns it back for good.

## Without `/configure`

A machine that never opens `/configure` can name its server in a `.env` file
in the repository instead: copy [`.env.example`](../../.env.example) to
`.env` and set `LLM_BASE_URL`.

It is one or the other. The first change made in `/configure` moves that
address into Pragma's own list, and from then on `.env` is no longer read for
it. The [configuration reference](../reference/configuration.md) says which
variables this applies to.

## When it does not answer

The home screen and every briefing say what the server is doing. Three
answers, three causes:

| The screen says | What it means |
|---|---|
| *not connected* | Nothing is listening at that address. The server is not running, or the address is wrong. |
| *connected, but no answer* | Something accepted the connection and then said nothing. Usually a tunnel whose far end has gone: see [Use a model on another machine](use-a-model-on-another-machine.md). |
| the model's name | It works. |
