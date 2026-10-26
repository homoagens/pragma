# Connect a model

*For the terminal on Linux; on Windows, inside WSL. [Where Pragma runs](../explanation/interfaces.md).*

Pragma needs one thing from outside: a model served on an OpenAI-compatible
endpoint — llama.cpp, LM Studio, Ollama, vLLM, or a hosted one. This is how
to point Pragma at it, and how to change that later.

Everything here is done in `/configure`, which opens from the home screen and
from inside a project. It is a page walked with the arrows: ↑↓ chooses a row,
←→ changes its value where it has one, Enter opens what is a list or has to
be typed, and **ctrl+D** goes back one step, everywhere.

## Add the first endpoint

1. Type `/configure`, then Enter on `servers`, then on `add a server`.
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
`/configure`, `servers`, and Enter on its name: those that are up come
first, those that are down last. Every row of that page is one question
about the machine, with its answer beside it; these three say what the model
is:

| Row | What to answer |
|---|---|
| `what it is` | `thinking` if the model reasons before it answers, `instruct` if it answers at once. |
| `what it is for` | `general`, or `coding` if this endpoint is used for writing and fixing code. |
| `sampling` | `standard` sends nothing and the server keeps the numbers it was started with. `advanced` lets you type them. `ask it` has the model read its own card and fill them in. |

These answers belong to the endpoint, not to a project: every project that
talks to this server inherits them.

**Claude, through Anthropic's API**, is asked differently, and its page says
so: the three rows above are not asked. A Claude model decides for itself when
to think; how much it may - its effort, `low` to `max` - is set for each role
that uses it, with ←→ in the table below, as Claude Code does. The address is
`https://api.anthropic.com/v1`, `model` the model's name (`claude-haiku-5-5`),
and the key is best left in an environment variable. The model's reasoning is
not shown while it runs: that API does not return it.

## Who does what

A model call is made in one of five roles, and `/configure` opens on a table
of them: each role, its model, and how it thinks there.

```
    role          model         thinks
  ❯ agent         exec          reasons        does the work
    recall        exec          at once        picks what to remember, before each turn
    memory        exec          reasons        writes what happened, afterwards
    critic        exec          at once        checks the work, where a project wants it
    advisor       haiku         effort high    plans the turn, where a project wants it
```

One server can answer them all, or each can have its own — a small fast
model for the recall that runs before every turn, a larger one for the agent,
or a more capable one as the [advisor](use-an-advisor.md) of a small agent.

- **Enter on a role** chooses its model, from the servers that are up, and
  comes back to the table. Any role but the agent's can be the same as the
  agent's, whichever that is.
- **←→ on a role** changes how it thinks: `reasons` or `at once` on a model
  that can reason — the recall and the critic answer at once unless you say
  otherwise — and on Claude the effort, from `low` to `max`, so that the same
  Claude can think little as the recall and hard as the advisor.

A role that has no server of its own follows the agent's. A server that is
down is not offered; the table says so on any role it still answers.

## Change an address, a name or a key

`/configure`, `servers`, and Enter on the endpoint. `name`, `address`, `model` and
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

Then, in `/configure`, `this machine`, choose `meaning` and type its address. The page says
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
