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

A turn is drawn as a ledger: one line for each thing done, in columns that
do not move — when, what was done, to what, and how it came out.

- A verb, not the name of a function: `ran`, `read`, `changed`, `wrote`.
- The outcome is a mark in the margin. Colour is never a background, and is
  used so rarely that a red mark is seen at once.
- What went fine fades as newer steps arrive. A failure does not, and keeps
  the one line that says why.
- What memory recalled is drawn in its own colour, with how strongly it is
  held.
- Time is shown: when each step started, and at the end where the seconds
  of the turn went.

A sentence the model writes before it acts is held until the next event
says what it was. Followed by a tool call it was a remark, and takes its
place in the ledger; otherwise it was the answer.

The look it replaced is kept, behind `PRAGMA_LOOK=classic`.

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
