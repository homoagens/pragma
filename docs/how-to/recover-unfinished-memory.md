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

and `/jobs`, from the home screen or from inside a project, opens the work
that is waiting:

```text
  Jobs  first › this session

  segmenter       2 turns -> 1 episode (1 dropped)

  ✗ abandoned · whatever was writing it is gone
    the turns are still in it: /home/you/.pragma/projects/first/jobs/job_20261001T142451Z_480.json

  ❯ run again   start writing it again
    discard     delete it - what was said in it never becomes memory
```

The page is the job: what it had done when it stopped, how it ended, and
under that what can be done with it. `abandoned` means the process that was
doing the work is gone. `failed` means it stopped with an error, which the
line names. `stopped by hand` means you stopped it yourself.

When more than one is waiting — from the home screen, that is every
project's — `/jobs` lists them first, each line saying where its job stands.
Enter opens one, and **ctrl+D** comes back to the list.

## Run it again

Each piece of unfinished work still holds the turns it was working on. Make
sure the model server answers, and press Enter on `run again`.

The page stays where it is and follows the work: a line for each step as it
finishes, the one in flight with its seconds. It takes about as long as
closing a project does, and ends by saying what it wrote. The job is then
gone — one that finishes deletes itself — and `/jobs` goes back to saying
there is nothing.

The same can be done by hand, with the file the page names:

```
cd /home/you/pragma
venv/bin/python tools/pragma_consolidate.py /home/you/.pragma/projects/first/jobs/job_20261001T142451Z_480.json
```

Running the same file twice is safe: a conversation already written down is
recognised and not written again. If another process is still working on the
job, the command says so and does nothing.

## Or let it go

If the conversation was not worth keeping — a test, a false start — choose
`discard`. It asks first. Nothing else refers to the job: its turns never
become memory, and the rest of the memory is untouched.

## Stop one that is being written

The page of a memory that is being written has two rows, `back` and `stop`.
`stop` ends the work there: what it had already written stays written, and
what was said stays in the job. The page then offers what it offers for any
job that did not finish — `run again`, or `discard`.

`back`, like **ctrl+D**, only leaves the page. The work goes on.

## Why it is kept at all

Because the alternative is a conversation that vanishes without a word. A
job that does not finish keeps everything needed to try again, and the next
briefing tells you — instead of leaving you to notice, months later, that
something you said was never remembered.

Pragma keeps the five most recent unfinished jobs of a project and removes
older ones.
