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
  what the memory is writing

  ❯ first   abandoned · whatever was writing it is gone
```

`abandoned` means the process that was doing the work is gone. `failed` means
it stopped with an error, which the line names. `stopped by hand` means you
stopped it yourself, from this same list.

## Run it again

Each piece of unfinished work still holds the turns it was working on. Make
sure the model server answers, press Enter on the line, and choose:

```text
  first · this session

  ❯ log         what it did, and how it ended
    run again   start writing it again
    discard     delete it - what was said in it never becomes memory
```

`run again` starts it and follows it. It takes about as long as closing a
project does, and ends by saying what it wrote. The job is then gone — one
that finishes deletes itself — and `/jobs` goes back to saying there is
nothing.

The same can be done by hand, with the file that `log` names:

```
cd /home/you/pragma
venv/bin/python tools/pragma_consolidate.py /home/you/.pragma/projects/first/jobs/job_20261001T142451Z_480.json
```

Running the same file twice is safe: a conversation already written down is
recognised and not written again. If another process is still working on the
job, the command says so and does nothing.

## Or let it go

If the conversation was not worth keeping — a test, a false start — choose
`discard`. Nothing else refers to it. Its turns never become memory, and the
rest of the memory is untouched.

## Stop one that is being written

A memory being written is on the same list, as `writing`. Enter on it offers
`watch` and `stop`. `stop` ends it there: what it had already written stays
written, and what was said stays in the job, to run again later or discard.

## Why it is kept at all

Because the alternative is a conversation that vanishes without a word. A
job that does not finish keeps everything needed to try again, and the next
briefing tells you — instead of leaving you to notice, months later, that
something you said was never remembered.

Pragma keeps the five most recent unfinished jobs of a project and removes
older ones.
