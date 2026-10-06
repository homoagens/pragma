# Your first project

*For the terminal. Written and tried on Linux; on Windows the same screens are drawn from PowerShell. [Where each interface stands](../explanation/interfaces.md).*

Ten minutes, start to finish. You will point Pragma at a model, make a
project, ask for two small things, close it, and come back to find that it
remembered the one that mattered.

You need Pragma installed (the [README](../../README.md) has the two
commands) and a model being served on your machine or one you can reach.
The examples use llama.cpp on port 8290; yours will have its own address.

What the agent writes back is in its own words, so your screen will not match
these line for line. What each screen is *for* will.

## 1. Start it

Open a new terminal and type:

```
pragma
```

On a machine that has never run it, the home screen is short:

```text
  No projects yet.

  /new        start your first project
  /configure  the model server Pragma talks to
  /help       this list
  /exit       leave

  endpoint    127.0.0.1:8080 · not connected · /configure
```

The last line is the one to read. Pragma has guessed llama.cpp's usual port
and found nothing there.

## 2. Tell it where the model is

Type `/configure` and press Enter. The page that opens is walked with the
arrow keys. `add` is already selected: press Enter, then type the address of
your server.

```text
  Address of the server  e.g. 127.0.0.1:8100 - /v1 is added if missing: 127.0.0.1:8290
  http://127.0.0.1:8290/v1  Qwen3.6-35B-A3B-MTP (UD-Q5_K_M) · 128k context
  Name [qwen3.6-35b-a3b-mtp]:
```

The second line is the server answering: Pragma asked what it is serving and
suggests a name from the reply. Press Enter to take it.

One more question follows, and it is worth answering now. Select `what it is`
and say whether your model reasons before it answers (`thinking`) or answers
at once (`instruct`). If you are not sure, choose `instruct`: it is also what
Pragma assumes when nothing has been said.

Then **ctrl+D** twice: once to leave the endpoint, once to leave `/configure`.
The home screen now names your model where it said *not connected*.

## 3. Make a project

A project is a folder the agent works in, and a memory of its own. Type
`/new`:

```text
  name  letters, digits, - and _ · ctrl+D goes back: first
  folder [/home/you/first]:
  /home/you/first does not exist yet. Create it?
    no, go back
  ❯ yes, create it
```

Give it the name `first`, press Enter to accept the folder, and move down to
`yes, create it` before pressing Enter — the page starts on *no*.

The project opens straight away, on a briefing:

```text
  first   Tuesday 06 October, 10:41

  memory      0 episodes active · 0 dormant · 0 beliefs
  serving     Qwen3.6-35B-A3B-MTP (UD-Q5_K_M) · 128k context

❯ say something  ·  /help for the commands  ·  ctrl+D closes the project
```

An empty memory, a model that answers, and a prompt. Everything typed here
without a `/` in front is said to the agent.

## 4. Ask for something

```
Create a file squares.py that prints the first ten square numbers, then run it.
```

Watch the turn happen:

```text
  ◆ curator  the memory is still empty · 0s
  ● write_file  path="/home/you/first/squares.py", content="for i in range(1, 11):\n    print(i * i)\n"
    ⎿ OK: written 40 bytes to /home/you/first/squares.py
  ● execute_command  command="python3 /home/you/first/squares.py"
    ⎿ returncode: 0
      stdout:
      1
      4
      … 8 more lines, 49 characters in all
Done. Created squares.py and ran it — output is the first ten square numbers.
  ✓ 3 steps · 2 tools · 30s · 166 tok · ctx 4% · touched squares.py
```

Four things, top to bottom. The **curator** looked in the memory for anything
that bears on your request and found it empty. Each **●** is a tool the agent
called, with what came back folded to a few lines. Then the **answer**. The
last line is the receipt: how many steps, how long, how full the context is,
and which files were touched.

The file is really there, in the folder you chose.

## 5. Say something worth remembering

Now tell it how you want things done from here on:

```
From now on every script in this project starts with a one-line docstring saying what it does. Add one to squares.py.
```

It edits the file and says so. Nothing else looks different — but this turn
was not like the first one. The first was a chore. This one was a decision.

## 6. Close the project, and watch it remember

Press **ctrl+D**. The terminal comes back at once, on the home screen, with
one new line at the bottom:

```text
  memory      first - writing  starting
              /jobs to watch it
```

The conversation is being turned into memory in the background. Type `/jobs`
to follow it:

```text
  first - this session   ctrl+D to leave it to itself
  [SEGMENTER] deciding what was worth keeping…
  [SEGMENTER] 2 turns -> 1 episode (1 dropped)
  [CONSOLIDATOR] writing 1 episode(s) from this session…
  [CONSOLIDATOR] [1/1] OK: episode saved
  done - 1 episode written.
```

Two turns went in and one episode came out. Writing ten square numbers to a
file was not worth keeping; the rule about docstrings was. Which turns are
kept is the model's judgement, so your run may keep both — what matters is
that it is a judgement, and not a transcript.

Press **ctrl+D** to go back.

## 7. Come back

Type `/open first`. The briefing has changed:

```text
  memory      1 episode active · 0 dormant · 0 beliefs · last here today

  since you left
    last time you were on: Enforce one-line docstring convention for all project scripts
```

This is a new conversation. The agent has no transcript of the last one in
front of it. Ask for another script, and do not mention the rule:

```
Write fib.py that prints the first ten Fibonacci numbers.
```

```text
  ◆ curator  1 memory + 0 beliefs → recalled 1 · 5s
      · Enforce one-line docstring convention for all project scripts
  ● write_file  path="/home/you/first/fib.py", content=""""Print the first ten Fibonacci numbers."""\n\na, b = 0, 1…"
```

The curator found the episode, judged that it bears on this request, and put
it in front of the agent. The new file starts with a docstring nobody asked
for this time.

## 8. Look at what it holds

Type `/memory`:

```text
  what is remembered   1 episode active · 0 dormant
    █████░░░ 0.62  Enforce one-line docstring convention for all project scripts

  Strength is how readily a memory comes back. It halves every 30 days unless
  the memory is recalled, and below 0.15 the memory goes dormant.
```

One memory, and how strongly it is held. `/memory last` shows it in full, and
`/help` lists everything else this screen takes.

**ctrl+D** closes the project; a second one, at home, leaves Pragma.

## What you have seen

- A **project** is a folder plus a memory kept apart from it.
- A **turn** is recall, then tools, then an answer.
- **Closing** a project is what turns a conversation into memory, and not all
  of it is kept.
- The next conversation starts **without the transcript and with the
  memory**.

## Where to go next

- A rule you want followed every time, without leaving it to memory, goes in
  a file: [Write rules for a project](../how-to/write-project-rules.md).
- A model on another machine: [Use a model on another
  machine](../how-to/use-a-model-on-another-machine.md).
- Every command on these two screens: [Commands](../reference/commands.md).
- What happened underneath: [Architecture](../explanation/architecture.md).
