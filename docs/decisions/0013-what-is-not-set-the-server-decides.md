# 13. What is not set, the server decides

- **Date:** 2026-09-25
- **Status:** accepted
- **Where:** [`core/config.py`](../../core/config.py), [`core/endpoints.py`](../../core/endpoints.py)

## Context

Sampling had several owners. Some numbers came from a file in the
repository, some from a table kept per model, and one — the temperature — was
always sent, with zero as its default. Zero means greedy decoding: it makes
every other sampling number inert, and it is what a reasoning model is least
suited to. A setup with nothing configured was running that way without
anyone having chosen it.

## Decision

A value that has not been set is not sent, and the server applies the one
it was started with. That holds for the temperature too.

Where the numbers should differ from the server's own, they are written in
the endpoint's entry: one row for a model that reasons and one for a model
that answers at once, because the people who publish a model publish two.
A call follows the row of what it is doing — a role told not to reason reads
the second row.

## Consequences

- There is no hidden default. What a request carries is either written
  down or left to the server.
- Decoding greedily is still possible, and has to be asked for by name.
