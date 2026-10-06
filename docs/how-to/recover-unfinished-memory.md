# Recover a memory that did not finish writing

*For the terminal. Tried on Linux; [what differs on Windows and in the browser](../explanation/interfaces.md).*

When you close a project, the conversation is turned into memory by a
separate process, after the terminal has come back. If that process dies —
the machine was shut down, the model server went away — the conversation is
not lost. It has simply not become memory yet.

## How you find out

The briefing of the project says so the next time you open it:

```text
  1 consolidation did not finish - /jobs
```

and `/jobs`, from the home screen or from inside a project, lists what is
waiting:

```text
  these did not finish. The turns are still in them, so they can be
  run again, from /home/you/pragma:
    venv/bin/python tools/pragma_consolidate.py <file>

  abandoned first           2026-10-01T14:24:51Z   this session
    /home/you/.pragma/projects/first/jobs/job_20261001T142451Z_480.json
```

`abandoned` means the process that was doing the work is gone. `failed` means
it stopped with an error, shown on the line below it.

## Run it again

Each piece of unfinished work is a file that still holds the turns it was
working on. Make sure the model server answers, go to the folder the page
names, and run the command it gives you with the file it lists:

```
cd /home/you/pragma
venv/bin/python tools/pragma_consolidate.py /home/you/.pragma/projects/first/jobs/job_20261001T142451Z_480.json
```

On Windows the page prints the same line the way PowerShell spells it.

It takes about as long as closing a project does, and ends by saying what it
did:

```text
done - 1 episode written to /home/you/.pragma/projects/first/episodes
```

The file is then gone — a job that finishes deletes itself — and `/jobs` goes
back to saying there is nothing.

Running the same file twice is safe: a conversation already written down is
recognised and not written again. If another process is still working on the
job, the command says so and does nothing.

## Or let it go

If the conversation was not worth keeping — a test, a false start — delete
the file. Nothing else refers to it. Its turns never become memory, and the
rest of the memory is untouched.

## Why it is kept at all

Because the alternative is a conversation that vanishes without a word. A
job that does not finish keeps everything needed to try again, and the next
briefing tells you — instead of leaving you to notice, months later, that
something you said was never remembered.

Pragma keeps the five most recent unfinished jobs of a project and removes
older ones.
