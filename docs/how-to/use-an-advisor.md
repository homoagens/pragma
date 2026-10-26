# Let an advisor plan the agent's work

*For the terminal on Linux; on Windows, inside WSL. [Where Pragma runs](../explanation/interfaces.md).*

A small, fast model is good at doing what it is told and poor at three
things: knowing what "done" looks like, noticing that it is going round in
circles, and knowing when to stop and ask. An advisor is a second model —
usually a more capable one — that does those three things for it. It never
acts and never answers you: it writes for the agent.

- **Before each turn** it writes a plan in a fixed form, what "done" will look
  like first — or answers that the turn needs none, for a greeting or a
  question answered in words.
- **When the agent stops making progress** — the same call failing again and
  again, most calls failing, the same throwaway script written into a command
  a third time, the same command run a third time with nothing changed in
  between, the same file written whole a third time, half the steps spent
  with nothing delivered — it reads what the agent did and says what to do
  next. Pragma decides when, from what it measures: the agent is exactly the
  one that does not know it is stuck. A command run again after a change is
  the change being checked, and does not count.

The agent reads what the advisor says as a message on your side, not as yours:
it follows the plan unless what it finds contradicts it, and the advisor can
never allow for you what cannot be undone.

## Turn it on

Inside the project, `/settings`, then `advisor`:

| Choice | What happens |
|---|---|
| `off` | The agent works alone. The default. |
| `plan` | A plan before each turn that needs work. |
| `plan + consult` | A plan, and advice when the agent stops making progress. |

With `plan + consult` a second line appears, `advice per turn`: how many
times one turn may ask, 2 unless you say otherwise. Each plan and each piece
of advice is a call to a model, and a wait.

The conversation reads the setting at every turn, so a change counts from the
next one.

## Choose the model

`/configure`, the page of the endpoint that should advise, `serves`, and
Enter on `advisor`. An endpoint that reasons is asked to reason for it. With
no endpoint given the role, the agent's own model plans for itself — which
already gives it the plan's `Done when`, but not a second mind.

## Read what it said

A plan shows what "done" will be and its steps, under one line that says what
it cost; a piece of advice, why it was asked for, the diagnosis and what to do
next:

```
  advisor  plan · 4 steps · 4s · 2.1k tok
           · done when: python3 snake.py runs, and the tests of its logic pass
           · 1. snake.py: the rules apart from the curses screen
           · 2. tests for the rules
           · 3. run the tests
           · 4. start it once, quit with q
```

The tokens are what the advisor read and wrote, together: on a paid endpoint
both are paid for. The line that closes the turn adds them up apart from the
agent's (`advisor 3.4k tok`). `/plan` shows the last turn's plan and advice in
full, with how to check it and when to stop and ask. `/status` says whether
the advisor is on and who it is.

## A single task

`python -m agent.batch` takes `--advisor plan` or `--advisor consult`, and
`--advisor-consults N`. Off by default, so a run without the flag is the run
it always was. The `--log` file records every plan and piece of advice.
