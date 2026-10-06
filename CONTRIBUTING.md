# Contributing to Pragma

Thanks for your interest. Contributions are welcome — bug reports, new skills, fixes, and ideas.

## Licensing of contributions

By submitting a contribution (pull request, patch, or code snippet) you agree that:

- your contribution is licensed to the project under its license ([AGPL-3.0-or-later](./LICENSE)), and
- you grant Homo Agens the perpetual right to re-license the project, including your contribution, under different terms in the future.

This keeps the project free to evolve its licensing as it grows. If you are not comfortable with this, open an issue describing your idea instead of a PR.

---

## The fastest way to contribute: add a skill

Each skill lives in its own folder under `core/skills/`. The loader picks it up automatically — no registration needed.

```
core/skills/
  your_skill/
    skill.py     ← required: contains a function named exactly like the folder
    README.md    ← required: documents parameters, returns, examples
```

**Rules:**
- The function name must match the folder name exactly (e.g. folder `send_email` → function `send_email`)
- Use late imports inside the function body to avoid circular loading
- Return a string always — on error return `"ERROR: ..."` instead of raising
- The first line under the title of `README.md` is what the model is told the tool does. Keep it on **one line**: a sentence wrapped over two reaches the model cut in half

A fully documented template is in `core/skills/_template/`. The skills that
exist, and which of them the agent is offered, are listed in
[docs/reference/skills.md](docs/reference/skills.md); that page is generated,
so run `python docs/build.py` after adding one.

---

## Reporting bugs

Open a GitHub issue with:
- What you did
- What you expected
- What happened instead (paste the error or a screenshot)
- Your setup: OS, Python version, the model server and its version (llama.cpp, LM Studio, Ollama, vLLM), and the model

---

## Submitting a pull request

1. Fork the repo and create a branch from `master`
2. Make your changes
3. Try them in the terminal on **Linux**: that is where Pragma is developed
   and tested. The Windows terminal is aligned afterwards, and the browser
   interface is not being worked on for now — see [where each interface
   stands](docs/explanation/interfaces.md). If a change touches something
   both launchers draw, say in the PR whether the Windows side was done too
4. Make sure the CI checks pass (see below)
5. Open a PR with a short description of what and why

**CI checks that run automatically:**
- Python syntax on all `.py` files
- `ruff check .` passes
- The generated documentation is up to date, and no link in the docs is broken
- Server imports without errors
- Skill loader finds and loads all skills, and offers the agent the right ones
- No `.env` is tracked

No LLM calls are made in CI — tests that require a running model are out of scope.

---

## Documentation

The pages are in [`docs/`](docs/README.md), in English, and a change to what
Pragma does goes in the same commit as the page that describes it.

The reference pages are generated from the code and are not edited by hand.
After adding, renaming or removing a setting, a command or a skill:

```
python docs/build.py
```

and commit what it wrote. A new setting or a new prompt also needs one line
in [`docs/notes.py`](docs/notes.py) saying what it is for; the build names
the one that is missing.

A change that settles how Pragma is built — not a fix, a choice — gets a
short record in [`docs/decisions/`](docs/decisions/README.md): the situation,
what was decided, what follows.

[docs/README.md](docs/README.md) has the rest, including how to read the
pages as a site.

---

## Code style

- Python 3.10+
- `ruff check .` must pass; the rules are in [`ruff.toml`](ruff.toml). No formatter is enforced beyond that, but keep it readable
- Imports at the top of files, except inside skill functions (late imports are intentional)
- English for code, comments, docstrings, and prompts
- No emoji in code or comments

---

## Questions

Open an issue or reach out at [homoagens1@gmail.com](mailto:homoagens1@gmail.com).
