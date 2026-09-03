# One command, many projects

*Design settled 2026-09-02, revised and built 2026-09-03. The launcher, the
registry and the menu exist; the migration and everything under "Later" do
not.*

Today a session is a folder holding `pragma.ps1`, `workspace/` and `.memoria/`,
entered by dot-sourcing an absolute path into a PowerShell window. The path is
typed by hand, the choice of which memory is live is made by the operator every
time, and the information needed to make that choice — every episode already
carries the workspace it was born in — is never used.

This replaces that with one command, a registry, and a briefing.

## The shape

`pragma` with no argument prints where you are, what changed while you were
away, and a menu it then stays in: an action runs and returns to the menu, and
quitting the menu leaves the program - the way a terminal harness behaves. The
window keeps the project's environment afterwards, so `pragma -Chat` and the
rest still work at the prompt.

*Revised 2026-09-03.* This shape replaces the first one, which set the window up
and got out of the way. The argument for that was that a loop would be unusable
to a developer and impossible in batch. Only the second half held, and it turned
out not to apply: batch never reaches the menu, because a project named by
`-Project` or `PRAGMA_PROJECT` skips it and a redirected stdin refuses it. What
the loop actually costs is mixing `git` and `pragma` on one command line, which
is a smaller price than it sounded.

```
$ pragma

  Pragma · Wednesday 2 September, 23:47

  project   pragma
  memory    47 episodes active, 12 dormant, 31 beliefs
  away for  6 days                                      tau 0.20

  Since you left
    2 episodes went dormant
    1 belief revised - "the user prefers fixed-price contracts"
    last time you were on: sorting out the git fork

  > chat            many turns, one conversation
    task            one task, then back here
    ask             a question, no file changes
    memory          map, beliefs, oblivion, last
    settings        what this project overrides
    switch project
    new project
    quit

  enter select . up/down move . esc quit
```

**The briefing is the point; the menu is packaging.** Entering a session is
currently a boundary event that means nothing to the memory, even though the
store knows exactly when it was last touched, what fell dormant since, and which
beliefs were revised. The moment of return is the one moment when a sense of
time is worth something, and it was the only moment not using it.

**The loop recomputes the briefing every pass.** After a chat you see what it
consolidated: the episode count moves under you, and anything that went dormant
while you worked is named. That is not decoration - it is the one moment the
store's sense of time is legible.

**Eight entries, not twenty.** chat, task, ask, memory, settings, switch, new,
quit. The diagnostics collapse into `memory`. The rare commands (`-Reset`,
`-Time`, `-Backup`) stay flags and never appear: whoever needs them already
knows they want them.

**Coming back continues the memory, not the conversation.** Chat holds its turns
in process memory only; on exit they become episodes and the literal transcript
is gone. Reopening a project lays the desk and shows the briefing, and the
conversation starts fresh. Persisting raw transcripts would compete with the
episodes — if the transcript is always there, the memory matters less — so it is
deliberately not done.

**Chat does not start by itself.** Landing straight in chat would mean leaving
something you did not ask to enter before you could look at anything else. It is
the first entry and one keystroke away.

## The registry

`~/.pragma/registry.json`, one entry per project:

```json
{
  "name": "notes",
  "workspace": "D:/notes",
  "memory":    "C:/Users/<user>/.pragma/projects/notes",
  "last_opened": "2026-09-02T23:47:00Z",
  "settings": { "Profile": "my-profile", "MaxSteps": 500, "Protocol": "native",
                "MemoryNoThink": "select", "CuratorEpisodes": 20,
                "CuratorRecent": 5, "Temperature": 0.6, "TopK": 20, "TopP": 0.95 }
}
```

**`settings` is what `pragma.ps1` used to be.** The session file was never only
an entry point: it carried the per-project model profile, step and token
budgets, action channel and sampling. Losing those in the move would leave a
memory that behaves differently the day after, in ways that surface late.

**`last_opened` is load-bearing**, not bookkeeping: it drives both "continue
where you were" and the read-only weighting of the previously open store.

### Two rules that keep it simple

**One folder, one project.** So `pragma` from inside a registered workspace never
has to ask which memory it means. If two memories over one folder are ever
wanted, register it twice under two names and accept being asked.

**The memory always lives under `~/.pragma/projects/<name>/`.** Never inside the
workspace. A workspace is a folder you already own and often a git repository;
a `.pragma/` directory inside it is one forgotten `.gitignore` away from
publishing personal episodes. One convention, no exceptions — including for the
existing personal store, which moves rather than earning a special case.

The workspace itself is a real directory you already work in. Nothing of the
agent's is written into it, and `PRAGMA.md` is created only on request.

## Refusing safely

> **memory on → registration required · memory off → works anywhere**

The hazard being prevented is writing into the wrong memory, and it does not
exist when there is no memory to write to. So `-NoMem` and batch — already
stateless by default — keep running in any directory, while a memory-backed run
in an unregistered folder refuses.

The refusal offers to register on the spot ("not registered — register it as
`notes`? [y/n]"). A wall is clumsy; a wall with a door is one keystroke, and the
guarantee is unchanged because creating the entry is still an explicit act.

Registering Pragma's own repository additionally needs
`PRAGMA_ALLOW_SELF_MODIFY=true` in that project's `settings` —
`self_modify_guard` refuses every write inside the source tree otherwise. That
switch belongs to one project and must never be global.

## Never prompt a machine

The menu must not appear when no human is present:

- a project named by `-Project` or `PRAGMA_PROJECT` skips the list
- when stdin is not a terminal, the menu is skipped and a missing project is a
  clear error, never a wait for a keypress

Fixing this later means discovering it as a batch script hanging on an invisible
prompt.

## Mechanism

Environment variables set inside a PowerShell function are process-wide and
survive its return — verified. The only reason today's file must be dot-sourced
is that it *defines* the `pragma` function, and a function defined in a normally
run script dies with the script's scope.

So the repository ships a module, and one line in `$PROFILE` imports it:

```powershell
Import-Module <repo>\tools\Pragma.psd1
```

From then on `pragma` exists in every window, with no paths. `-Chat`, `-Ask`,
`-Map` stay switch parameters: the surface does not change, only how a project
is chosen.

## Migrating an existing session

A folder created by `new-session.ps1`, in order:

1. Build and prove the launcher on a throwaway project.
2. Only once `pragma` opens the migrated project correctly: copy its `.memoria`
   to `~/.pragma/projects/<name>`, write the registry entry carrying every
   setting the old `pragma.ps1` held, delete that file.

Those settings are the migration. The files copy themselves; a profile or a
curator width left behind leaves a memory that behaves differently the day
after, in a way nothing announces.

The two ways coexist until step 2 — the dot-source keeps working because it
reads the same store — so the memory in daily use is never unavailable.

## Later, in this order

**Cross-store reading before merging.** The previously open project stays
readable with a lower weight rather than being closed; the Curator may still
draw from it. This is reversible and measurable — how often a chosen fragment
comes from the other store, and under which use label.

**Merging is reconsolidation, not concatenation.** `core/reconsolidate.py`
already carries the safety laws this needs: facts stay frozen, interpretations
may be rewritten in the light of new context, entailment and trust hierarchy
enforced. Two projects meeting *is* new context.

Its three layers differ sharply in difficulty. Facts are free — `narrative` is
frozen and timestamps are absolute, so even tau is already comparable across
stores. Beliefs are largely written: `_belief_key` and `_merge_duplicates`
already do this work for one store and need two inputs instead of one. Salience
is the problem, and a recent commit created it: importance is now judged against
each store's own anchors, so two memories hold two different scales. The merged
store draws its anchors from the union, so future judgements calibrate on the
common scale while old values stand as the historical record. Renormalising by
rank is rejected: it would rewrite recorded judgements, and nothing else in
Pragma corrects the past.

The cheap reversible step is also the prerequisite for the ambitious one. If the
memory is ever to notice by itself that two projects should merge — beliefs from
one confirmed by episodes of the other — it must already be able to read across.

## Already in place

`agent/chat.py` names each consolidated segment `chat:{cwd}:{timestamp}`, so the
project is already part of the identity of what gets written. What is missing is
the store swap and forcing consolidation of the open segment before switching,
without which a segment would straddle two memories.
