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

You are now on the page of your endpoint: one row for each thing that can be
said about it. The first is worth answering now. Press Enter on `what it is`
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
  recalled  the memory is still empty

  ▮ wrote    squares.py                                                  +2
  ▮ ran      python3 squares.py                                    10 lines

Done. squares.py prints the first ten square numbers, and it ran successfully.

  ✓ 3 steps · 2 tools · 7s · 166 tok · ctx 4% · touched squares.py
```

Four things, top to bottom.

**`recalled`** is the memory being asked whether it holds anything that bears
on your request. It is empty, and says so.

Then **one line for each thing done**, and three things on each: what was
done, as a verb; what it was done to; and how it came out. `wrote squares.py
+2` is a file of two lines. `ran python3 squares.py` printed ten. The mark in
the margin is green for a command that succeeded and red for anything that
failed, and a failure keeps, under it, the line that says why. While the turn
runs, the newest lines are the brightest and the older ones fade.

Then **the answer**.

The last line is the receipt: how many steps, how long, how full the context
is, and which files were touched.

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
to see it:

```text
  Jobs  first › this session

  segmenter       2 turns -> 1 episode (1 dropped)
  ⠼ consolidator · writing the episode  12s

  ❯ back   it goes on writing without you
    stop   end it now - what was said stays in the job, to write later or let go
```

That page is the work itself, drawn as it happens: a line for each step that
has finished, and the one in flight with its seconds. Leave it open. When the
work ends, the page says how:

```text
  Jobs  first › this session

  segmenter       2 turns -> 1 episode (1 dropped)
  consolidator    Every script in this project starts with a one-line docstring

  ✓ 1 memory written · 58s
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
  recalled  ▮▮▮▮▮▯▯▯  memory: Enforce one-line docstring convention for all project scripts

  ▮ wrote    fib.py                                                     +13
  ▮ ran      python3 fib.py                                        10 lines

fib.py prints the first ten Fibonacci numbers. The script follows the
project's one-line docstring convention.
```

This time `recalled` has something. `memory:` says it is an episode, a thing
that happened; a `belief:` would be something concluded from several of them.
The bar is how strongly it is held. Pragma found it, judged that it bears on
this request, and put it in front of the agent.

Open `fib.py`: it starts with a docstring nobody asked for this time.

## 8. Look at what it holds

Type `/memory`:

```text
  what is remembered   1 episode active · 0 dormant
    ▮▮▮▮▮▯▯▯ 0.62  Enforce one-line docstring convention for all project scripts

  Strength is how readily a memory comes back. It halves every 30 days unless
  the memory is recalled, and below 0.15 the memory goes dormant.
```

One memory, and how strongly it is held. `/memory last` shows it in full, and
`/help` lists everything else this screen takes.

**ctrl+D** closes the project; a second one, at home, leaves Pragma.

## What you have seen

- A **project** is a folder plus a memory kept apart from it.
- A **turn** is recall, then what was done, line by line, then an answer.
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
