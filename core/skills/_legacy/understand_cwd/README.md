# understand_cwd

Build an operational map of the current environment: cwd, Python version, platform, whitelisted env vars, and directory tree.

---

## Parameters

- `max_depth` (int, optional, default 2): Depth of the directory tree to display.

## Returns

A multi-line string with sections for cwd, Python runtime, directory structure, and environment variables.

## Notes

- Only env variables with operational meaning for an agent are shown (USERNAME, HOME, CONDA_DEFAULT_ENV, etc.).
- Noisy directories (venv, __pycache__, .git, node_modules, etc.) are hidden from the tree.
- At most 30 children per directory node are shown; remaining are counted.
