# python: compile, lint and test what you change, in the project's own environment

- Use the project's environment: a `venv` or `.venv` in the folder means its `bin/python`, not the system's. Never `pip install` into the system Python; ask before adding a dependency, and add it to `requirements.txt` or `pyproject.toml` when you do.
- After each change, `python -m py_compile <file>`. If the project uses a linter or a type checker (ruff, flake8, mypy - look in `pyproject.toml`, `setup.cfg`), run it on the files you touched.
- Tests: with a `tests/` folder or a pytest configuration, run the closest test file with `python -m pytest -q <file>` after a change, and the whole suite before handing over.
- Write as the code around it does: type hints and f-strings where it uses them, `pathlib` for paths, `open(..., encoding="utf-8")`.
- No bare `except:`. Catch what you expect, and keep the error's message where someone will read it.
- A script has `if __name__ == "__main__":` and an exit code that says whether it worked.
