# Pragma documentation

The [README](../README.md) is where to start: what Pragma is, how to install
it, how to run it. These pages are for what comes after that — learning your
way around, getting something done, looking something up, changing the code.

New here? [Your first project](tutorial/first-project.md) takes ten minutes.

**These pages describe the terminal on Linux**, which is where Pragma is
developed and where everything is tested. The terminal on Windows follows it
and can be a step behind; the browser interface is the old one and is not
covered. [Three interfaces, and where each stands](explanation/interfaces.md)
says what differs.

## Find your way

| I want to | Go to |
|---|---|
| learn Pragma by using it | [Your first project](tutorial/first-project.md) |
| point Pragma at my model | [Connect a model](how-to/connect-a-model.md) |
| use a model that runs on another machine | [Use a model on another machine](how-to/use-a-model-on-another-machine.md) |
| give the agent rules it must always follow | [Write rules for a project](how-to/write-project-rules.md) |
| keep a copy of what a project remembers | [Back up and restore memory](how-to/back-up-and-restore-memory.md) |
| take a project to another computer | [Move a project](how-to/move-a-project.md) |
| deal with "a consolidation did not finish" | [Recover a memory that did not finish writing](how-to/recover-unfinished-memory.md) |
| run a task from a script | [Run one task](how-to/run-one-task.md) |
| look up a command or a key | [Commands](reference/commands.md) |
| look up a setting and its default | [Configuration](reference/configuration.md) |
| know which files Pragma writes, and where | [Files](reference/files.md) |
| see which tools the agent has | [Skills](reference/skills.md) |
| read what the model is told | [Prompts](reference/prompts.md) |
| know what differs on Windows, or in the browser | [Three interfaces](explanation/interfaces.md) |
| see what the pieces are and how a turn runs | [Architecture](explanation/architecture.md) |
| find the file that does something | [Code map](explanation/architecture.md#code-map) |
| know why something is the way it is | [Decisions](decisions/README.md) |
| add a tool, report a bug or send a change | [CONTRIBUTING](../CONTRIBUTING.md) |

## How these pages are organised

Four kinds of page, kept apart, because each answers a different need and a
page that tries to answer two answers neither.

| Folder | What is in it |
|---|---|
| [`tutorial/`](tutorial/first-project.md) | One guided path, start to finish, for someone learning. |
| `how-to/` | One page per task, for someone who knows what they want done. |
| `reference/` | Facts to look up: commands, settings, files, skills, prompts. |
| [`explanation/`](explanation/architecture.md) | How Pragma is put together, and where each of its interfaces stands. |
| [`decisions/`](decisions/README.md) | One short, dated record per design decision. Never rewritten. |

The reason for a smaller choice has a home already: the comment at the top of
the file that implements it. These pages say where to look. They do not
repeat it.

## Keeping them true

Five pages are generated, and are not edited by hand: four under
`reference/` and the list of decisions. They say so in their first line.

```
python docs/build.py
```

reads the code for what the code knows — which variables are read and their
defaults, which commands exist, which skills are offered, where each prompt
is — and [`notes.py`](notes.py) for the one thing it cannot know, what each
of them is for. CI runs

```
python docs/build.py --check
```

and fails when a page has fallen behind the code, when a setting or a prompt
has no description, when a link in any of these pages points at a file or a
heading that is not there, or when a page is missing from the site's menu.

So a change that adds, renames or removes a setting, a command, a skill or a
prompt is finished when `python docs/build.py` has been run and its output
committed with it. The build names what is missing.

Everything else here is written by hand, in English, and belongs in the same
commit as the change it describes.

## Reading them as a site

The pages read on GitHub as they are. For a menu and a search, the same files
are published as a site at <https://homoagens.github.io/pragma/>, rebuilt on
every push to `master` that touches them
([`docs.yml`](../.github/workflows/docs.yml)).

The site is built with [MkDocs](https://www.mkdocs.org) and the
[Material](https://squidfunk.github.io/mkdocs-material/) theme, both open
source. To have it on your own machine, in any Python environment other than
Pragma's own:

```
pip install -r docs/requirements.txt
mkdocs serve
```

and open <http://127.0.0.1:8000/pragma/>. It redraws a page when its file is
saved. `mkdocs build --strict` writes the site into `site/` and fails on a
link that points nowhere.

A page of the site asks nothing of any other server: the fonts are the
reader's own, and the library that draws the diagrams is downloaded when the
site is built and served with it.

[`mkdocs.yml`](../mkdocs.yml) holds the menu, so a new page is listed there;
the check above fails on one that is not. On the site, a link to a file of the
code opens it on GitHub ([`site_hooks.py`](site_hooks.py) does that), since a
site holds only what is under `docs/`.
