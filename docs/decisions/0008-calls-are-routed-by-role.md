# 8. Calls are routed by role, from one catalogue, with no fallback

- **Date:** 2026-09-11
- **Status:** accepted
- **Where:** [`core/endpoints.py`](../../core/endpoints.py), [`tools/pragma_configure.py`](../../tools/pragma_configure.py)

## Context

Pragma talked to one model server, named in a file in the repository. But
the calls it makes are not alike: the agent's steps want the strongest model
available, the recall before every turn wants a fast one, and the memory is
written when nobody is waiting.

## Decision

Every call is made in a *role*, and the role comes from who is making the
call, not from the place in the code that makes it. No call names a server.

One file outside the repository, `~/.pragma/endpoints.json`, lists the servers
under names the person chose and says which role each one answers. What a
server is — whether its model reasons, how it should be sampled — is written
beside its address, because the server is the thing being described.

A catalogue that cannot be followed is an error. It is never a quiet return
to another server: that would put a call on a model nobody chose.

## Consequences

- A new kind of call is routed by the same rule without anyone remembering
  to ask.
- The file is the same for every project and is left out of every snapshot,
  so no address or key ends up in a zip.
- With one server, nothing about this is visible: it answers every role.
