# Back up and restore a project's memory

*For the terminal. The Linux part was tried; the Windows part is described from the code of its launcher. [Where each interface stands](../explanation/interfaces.md).*

A snapshot is a zip of everything a project remembers, taken at a moment you
choose. Take one before anything you might regret: deleting a project,
restoring an older state, editing the files by hand.

Both are done from the **home screen**, not from inside a project: close the
project with **ctrl+D** first.

The page is not the same on every system. The two launchers grew apart here:
they keep snapshots in different folders and lay them out differently inside
the zip, so do not count on carrying one from one system to the other.

## Linux and macOS

**Take a snapshot.** Type `/projects backups`, pick the project if there is
more than one, and press Enter on `take a snapshot now`. The page prints
where it went:

```text
  snapshot taken  (2 KB)
  /home/you/.pragma/projects/backups/first/memory_2026-10-06_104424.zip
```

**Restore one.** The same page lists the snapshots under that first row,
newest first. Select one and type the project's name to confirm.

Before anything is replaced, the memory as it is *now* is zipped beside the
others as `memory_before_restore_…`, so a restore can itself be undone.

A snapshot holds the memory only. The folder you work in is yours to back up.

## Windows

**Take a snapshot.** Type `/projects backups` and choose what to keep:

| Choice | What it holds |
|---|---|
| `snapshot both` | the memory and the folder you work in |
| `snapshot memory` | episodes and beliefs only |
| `snapshot workspace` | your files only |

**Restore one.** `restore a snapshot`, on the same page, lists them with
their date, their size and what each holds. Select one and type the project's
name to confirm. The memory is replaced by what the snapshot holds; the
workspace is overwritten file by file, so anything added since the snapshot
stays where it is. As on the other systems, the current state is saved first,
so a restore can be undone.

Snapshots are kept in `%USERPROFILE%\.pragma\backups\<project>\`.

## What a snapshot is for, and what it is not

It is the way back from a mistake on the same machine. Deleting a project
removes its memory and leaves its snapshots, on purpose.

It is not a way of carrying a project to another machine: see [Move a
project](move-a-project.md).
