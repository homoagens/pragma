# 28. Rule packs are turned on by the person

- **Date:** 2026-10-21
- **Status:** accepted
- **Where:** [`core/rule_packs.py`](../../core/rule_packs.py), [`core/rules/`](../../core/rules/), [`terminal/pragma_launcher.py`](../../terminal/pragma_launcher.py), [`agent/chat.py`](../../agent/chat.py)

## Context

A model works better on code when it is told how this kind of code is
checked: `cargo check` after every change in Rust, the project's own
environment in Python. A project's `PRAGMA.md` can say it, but the same
rules would be written again in every project, and they cost tokens on
every request. Put in every conversation, they weigh on the ones that are
not about code at all.

Pragma could have decided when to use them: from the files in the folder,
or by asking the model. Either is a guess, and a wrong guess is either
rules missing where they were needed or tokens spent where they were not.

## Decision

Rules for a kind of work are packs, one Markdown file each, which the
person turns on per project from `/settings`. Nothing turns one on by
itself; the page only says when the folder has the file a pack is for.
Pragma comes with four - `coding`, `python`, `rust`, `html` - and a person
adds or replaces packs in `~/.pragma/rules/`.

The packs on go into the system prompt, after the project's own rules and
before the session block. A pack turned on in the middle of a conversation
is put in front of the next request instead, so that the conversation is
not read again from the start; one turned off stays until the next
conversation.

## Consequences

- A project with no packs on sends exactly what it sent before.
- What a pack costs is shown where it is turned on.
- A single task (`agent.batch`) follows no packs, so runs of it stay
  comparable whatever a project has on.
