# 18. A turn is drawn as a ledger

- **Date:** 2026-10-06
- **Status:** accepted
- **Where:** [`agent/ledger.py`](../../agent/ledger.py), [`agent/harness.py`](../../agent/harness.py)

## Context

A conversation was drawn the way every agent in a terminal draws one: a mark
for each tool call, the name of the function and its arguments, then what it
returned, folded. That vocabulary describes the machinery. Reading a turn
meant translating `execute_command command="pytest -q"` back into *it ran the
tests*, and a turn of twenty steps was sixty lines in which the one that had
failed weighed the same as the nineteen that had not.

## Decision

A turn is drawn as a ledger: one line for each thing done, and three things
on a line — what was done, to what, and how it came out.

- A verb, not the name of a function: `ran`, `read`, `changed`, `wrote`.
- The outcome is a mark in the margin. Colour is never a background, and is
  used so rarely that a red mark is seen at once.
- What went fine fades as newer steps arrive. A failure does not, and keeps
  the one line that says why.
- What memory recalled is drawn in its own colour: whether it is a memory or
  a belief, and how strongly it is held.

A sentence the model writes before it acts is held until the next event
says what it was. Followed by a tool call it was a remark, and goes the way
its reasoning goes; otherwise it was the answer.

The look it replaced is kept, behind `PRAGMA_LOOK=classic`.

The first version, the same day, also put a clock in front of every step,
kept the model's remarks between the steps, and closed the turn on a bar of
where its seconds had gone. Used for an hour, it read as a mix of things.
They were taken out: a line carries three items, a step says how long it
took only when that was long enough to notice, and the turn closes on the
plain line it always had.

A real turn then showed what was still in the way. Every stretch of
reasoning left a line saying how long it had lasted, five in a turn of five
steps. A command's outcome was the last line it had printed, whatever that
was: a file's permissions, cut off at the column's edge. And two short
paragraphs written before a tool call were printed across the steps as
though they were the reply. So reasoning leaves nothing behind; a command
says how much it printed, or its verdict when it is a test runner's; text is
the answer only when it is long, or is a list, a heading, a table or a block
of code; and one blank line stands between the blocks of a turn — what was
recalled, the steps, the answer, the line that closes it — and none inside
one.

## Consequences

- The newest steps live in a region of the screen that is redrawn, and are
  printed for good only when they leave it: a line already printed cannot be
  recoloured.
- A skill nobody has given a verb is drawn by its own name. It shows up
  plainly rather than not at all, and a verb is one entry in a table.
- With `--show-thoughts`, everything a tool returned is wanted, and the
  classic drawing is used for the steps.
- A very long turn is one faint line per step. Folding those into a count is
  not done.
- It was tried in the terminal on Linux. On Windows it has not been looked
  at.
