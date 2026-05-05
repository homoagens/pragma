# Contributing to Pragma

Thanks for your interest. Contributions are welcome — bug reports, new skills, fixes, and ideas.

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
- The first line of `README.md` (before `---`) becomes the skill summary in the agent's system prompt

A fully documented template is in `core/skills/_template/`.

---

## Reporting bugs

Open a GitHub issue with:
- What you did
- What you expected
- What happened instead (paste the error or a screenshot)
- Your setup: OS, Python version, Ollama version, model name

---

## Submitting a pull request

1. Fork the repo and create a branch from `master`
2. Make your changes
3. Make sure the CI checks pass (see below)
4. Open a PR with a short description of what and why

**CI checks that run automatically:**
- Python syntax on all `.py` files
- Server imports without errors
- Skill loader finds and loads all skills

No LLM calls are made in CI — tests that require a running model are out of scope.

---

## Code style

- Python 3.10+
- No external formatter enforced, but keep it readable
- Imports at the top of files, except inside skill functions (late imports are intentional)
- English for code, comments, docstrings, and prompts
- No emoji in code or comments

---

## Questions

Open an issue or reach out at [homoagens1@gmail.com](mailto:homoagens1@gmail.com).
