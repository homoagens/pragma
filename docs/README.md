# Pragma documentation

The [README](../README.md) is where to start: what Pragma is, how to install
it, how to run it. These pages are for what comes after that — finding your
way around, looking something up, changing the code.

## Find your way

| I want to | Go to |
|---|---|
| see what the pieces are and how a turn runs | [Architecture](explanation/architecture.md) |
| find the file that does something | [Code map](explanation/architecture.md#code-map) |
| know where Pragma keeps its files | [Where state lives](explanation/architecture.md#where-state-lives) |
| look up a command or a key | [Commands](reference/commands.md) |
| look up a setting and its default | [Configuration](reference/configuration.md) |
| see which tools the agent has | [Skills](reference/skills.md) |
| add a tool | [CONTRIBUTING](../CONTRIBUTING.md), then the [template](../core/skills/_template/README.md) |
| read the agent's system prompt | [`agent/prompts.py`](../agent/prompts.py) |
| report a bug or send a change | [CONTRIBUTING](../CONTRIBUTING.md) |

## How these pages are organised

Four kinds of page, kept apart, because each answers a different need and a
page that tries to answer two answers neither.

| Folder | What is in it | State |
|---|---|---|
| `tutorial/` | One guided path, start to finish, for someone learning. | not written yet |
| `how-to/` | One page per task, for someone who knows what they want done. | not written yet |
| `reference/` | Facts to look up. | [commands](reference/commands.md), [configuration](reference/configuration.md), [skills](reference/skills.md) |
| `explanation/` | How Pragma is put together. | [architecture](explanation/architecture.md) |
| `decisions/` | One short, dated note per design decision. Never rewritten. | not written yet |

**Why** a thing is the way it is has a home already: the comment at the top
of the file that implements it. These pages say where to look. They do not
repeat it.

## Keeping them true

The pages under `reference/` are generated. Do not edit them:

```
python docs/build.py
```

reads the code for what the code knows — which variables are read and their
defaults, which commands exist, which skills are offered — and
[`notes.py`](notes.py) for the one thing it cannot know, what each setting is
for. CI runs

```
python docs/build.py --check
```

and fails when a page has fallen behind the code, when a setting has no
description, or when a link in any of these pages points at a file or a
heading that is not there.

So a change that adds, renames or removes a setting, a command or a skill is
finished when `python docs/build.py` has been run and its output committed
with it. A new setting also needs its line in `notes.py`; the build says
which one is missing.

Everything else here is written by hand, in English, and belongs in the same
commit as the change it describes.

## Reading them as a site

The pages read on GitHub as they are. For a menu and a search, the same files
build into a site with [MkDocs](https://www.mkdocs.org) and the
[Material](https://squidfunk.github.io/mkdocs-material/) theme, both open
source. In any Python environment other than Pragma's own:

```
pip install -r docs/requirements.txt
mkdocs serve
```

and open <http://127.0.0.1:8000>. It redraws a page when its file is saved.
`mkdocs build --strict` writes the site into `site/` and fails on a link that
points nowhere.

[`mkdocs.yml`](../mkdocs.yml) holds the menu, so a new page is listed there;
the check above fails on one that is not. On the site, a link to a file of the
code opens it on GitHub ([`site_hooks.py`](site_hooks.py) does that), since a
site holds only what is under `docs/`.
