# Turn on rule packs for a kind of work

*For the terminal on Linux; on Windows, inside WSL. [Where Pragma runs](../explanation/interfaces.md).*

A rule pack is a short set of rules for one kind of work: how to check Rust
or Python code after changing it, what a web page must have. The agent
follows the packs a project has turned on, and no others. Nothing turns one
on by itself: rules about code are tokens spent on every request, and a
project that is not about code should not pay for them.

## The packs Pragma comes with

| Pack | What it asks of the agent |
|---|---|
| `coding` | Read before changing, one change at a time and checked, say what was not run. Useful with any of the others. |
| `python` | The project's own environment, `py_compile` and the project's linter after each change, `pytest` before handing over. |
| `rust` | `cargo check` after every change, `fmt`, `clippy` and `test` before handing over, `Result` and `?` rather than `unwrap()`. |
| `html` | A valid, accessible page that works at phone width, served and fetched to check it. |

They are in [`core/rules/`](../../core/rules/), a page of Markdown each, a
few hundred tokens each.

## Turn one on

Inside the project, `/settings`, then `rule packs`. Enter turns the pack
under the arrow on or off; each line says what the pack costs. Where the
project's folder has the file a pack is for — `Cargo.toml` for `rust` — the
line says so, and that is all it does.

When the change takes effect:

- **Before anything has been said**, or from the next conversation
  (`/clear`, or opening the project again): the packs are part of the
  agent's instructions, after the project's own [`PRAGMA.md`](write-project-rules.md).
- **In a conversation already under way**, a pack turned on is put in front
  of your next message, and stays in the conversation from then on. A pack
  turned off stays until the next conversation: what the model has read
  cannot be taken back. The conversation says which of the two happened.

`/status` lists the packs on. A [served project](serve-a-project.md) follows
the same packs, read when each conversation starts. A
[single task](run-one-task.md) follows none.

Where a pack and the project's `PRAGMA.md` disagree, `PRAGMA.md` wins: the
agent is told so.

## Write your own

A pack is a Markdown file in `~/.pragma/rules/`. Its name is the pack's
name; its first line says what it is for, after the name and a colon; the
whole file is what the agent reads.

```markdown
# go: format, vet and test every change

- After every change, `gofmt -w` the files you touched and `go vet ./...`.
- Before handing over, `go test ./...`.
- Errors are returned and wrapped with `fmt.Errorf("...: %w", err)`, never ignored.
```

Saved as `~/.pragma/rules/go.md`, it is in the list the next time the page
opens. One with the name of a pack Pragma comes with — `rust.md` — takes its
place, for every project.

Keep a pack short and concrete: commands to run and things not to do. Every
line of it is sent with every request of every project that has it on.
