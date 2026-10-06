# 16. The reference is generated from the code

- **Date:** 2026-10-06
- **Status:** accepted
- **Where:** [`docs/build.py`](../../docs/build.py), [`docs/notes.py`](../../docs/notes.py)

## Context

The code read ninety-seven settings and no page listed them. The commands
had been reorganised twice since anyone wrote them down. A list kept by hand
is right on the day it is written.

## Decision

What the code already knows is read from the code: which settings exist and
their defaults, the commands, the skills, where each prompt is. What it
cannot know — what a setting is *for* — is one line each, written by hand in
a single file.

The two are checked against each other on every push. A page that has fallen
behind the code, a setting with no description, a link that points nowhere
or a page missing from the menu fails the build.

## Consequences

- A change that adds a setting is not finished until the page says so,
  and CI is what says it is not finished.
- The pages written by hand — these records among them — are not covered by
  that check. Only their links are.
