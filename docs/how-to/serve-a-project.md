# Serve a project to another program

*For the terminal on Linux and macOS: the Windows launcher does not have it. [Where each interface stands](../explanation/interfaces.md).*

A program that talks to a model through an OpenAI-compatible endpoint — a
chat panel, a presentation tool, a script — can talk to one of your projects
instead. It sends what it would send to a model, and gets the whole of
Pragma back: the recall before each turn, the agent with its tools and its
folder, and a memory that is written when the conversation ends.

## Serve a project

1. On the home screen, `/serve`.
2. Enter on `add`, and choose the project.

It starts at once, and its page shows what the program needs:

```text
  For the program, in its settings or its .env:
    LLM_BASE_URL=http://127.0.0.1:8300/v1
    LLM_MODEL=pragma:lezioni
    LLM_API_KEY=pgk_…
```

Put those three into the program's settings, under whatever names it uses
for the address of its model, the model's name and the key. The model's name
is not needed to choose the project — the port does that — but some programs
refuse to run without one.

## It keeps running

**A served project keeps running when Pragma is closed**, so a program using
it does not stop working because a terminal did. The home screen says, every
time it is drawn, what is served:

```text
  serve       lezioni  127.0.0.1:8300 · a conversation, 3 turns
```

Green is running; yellow is on and not running — the line says how to look;
grey is off. After a reboot, the next `pragma` starts again every project
that is on.

## Change where it listens, or stop it

Enter on the project's name in `/serve` opens its page:

| Row | What it does |
|---|---|
| `state` | Turns it on or off. Off, the program gets no answer. |
| `memory` | On: recalled before each turn, written when a conversation ends. Off: the agent alone, as with `pragma --agent`; nothing is read from the memory or added to it. |
| `address` | `127.0.0.1` is this machine only. `0.0.0.0` opens it to the network. |
| `port` | The first free one from 8300 is chosen for you. |
| `key` | Makes a new one. The program needs it in place of the old. |
| `log` | The last lines of what the service has done. |
| `remove` | Stops it and takes it off the list. |

A change of memory, address, port or key starts the service again. The home
screen's line says `memory off` for a project served without it.

**The key.** A program on this machine may send none. Once the address is
opened to the network, every request must carry the key, and one without it
is refused.

## What happens to a conversation

- **What the person types is a turn.** The program's own system messages — the
  slide on screen, a document — are context for that turn: the agent reads
  them, and they are never written to memory.
- **A program that starts over starts a new conversation.** The one before is
  closed and handed to the memory, as **ctrl+D** does in the terminal. One
  that nobody writes to for 20 minutes is closed the same way
  (`PRAGMA_SERVE_IDLE_MINUTES`).
- **The answer comes back as `content`.** While the turn runs,
  `reasoning_content` says what Pragma is doing — what was recalled, the
  model's reasoning, each tool and how it came out — for a program that
  shows a "thinking" panel.
- **Nobody can answer in the middle of a turn.** The agent ends the turn with
  its question instead. A [command that cannot be
  undone](allow-commands.md) is not run unless the project allows it in
  `/settings`: the agent says in its reply what it would run.

The model behind it is the one in `/configure`: a served project uses the
same endpoints as when you open it in the terminal.

## Where it is kept

`~/.pragma/serve.json` lists the served projects, with their addresses and
keys. While one runs, `~/.pragma/serve/<name>.json` says what it is doing,
and `~/.pragma/serve/<name>.log` is its log. [Files](../reference/files.md)
has the details.
