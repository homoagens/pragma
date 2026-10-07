# Files

Every file Pragma writes, where it is, and what is in it. `~` is your home
folder: `/home/you`, `/Users/you`, or `C:\Users\you`.

Three places: its own folder under your home, the folder you work in, and the
folder Pragma is installed in.

## In `~/.pragma`

| Path | What it is | Written by |
|---|---|---|
| `registry.json` | The projects. | the launcher |
| `endpoints.json` | The model servers, which role uses which, the optional faculties. | `/configure` |
| `projects/<name>/` | One project's memory. In it, `vectors/` is kept only when an embedding server is in use, and can be deleted: it is rebuilt. | the memory worker |
| `projects/backups/<name>/` | Snapshots, on Linux and macOS. | `/projects backups` |
| `backups/<name>/` | Snapshots, on Windows. | `/projects backups` |
| `plugins/<name>/plugin.json` | Commands added to the home screen. | you |
| `threads/` | Conversations of the browser interface. | the server |
| `request-<pid>.json` | A note from an open conversation to the launcher. Gone when the conversation ends. | the conversation |

`PRAGMA_DATA_DIR` moves the memory in use, and `PRAGMA_ENDPOINTS` names
another file for the servers: see [Configuration](configuration.md).

### `registry.json`

A list, one entry per project.

```json
[
  {
    "name": "first",
    "workspace": "/home/you/first",
    "memory": "/home/you/.pragma/projects/first",
    "last_opened": "2026-10-06T10:43:16Z",
    "settings": {}
  }
]
```

| Field | What it is |
|---|---|
| `name` | What the screens call the project. |
| `workspace` | The folder the agent works in. |
| `memory` | The folder holding this project's memory. |
| `last_opened` | When it was last opened, in UTC. Orders the list on the home screen. |
| `settings` | What this project decides for itself: `MaxSteps`, and any of the settings marked *project setting* in [Configuration](configuration.md). Empty until something is set. |

The same file is read by the launcher on every system.

### `endpoints.json`

```json
{
  "endpoints": {
    "main": {
      "url": "http://127.0.0.1:8080/v1",
      "kind": "thinking",
      "work": "general",
      "reasons": {"agent": true, "recall": false, "memory": true},
      "sampling": {
        "thinking": {"general": {"temperature": 1.0, "top_p": 0.95}, "coding": {}},
        "instruct": {"general": {"temperature": 0.7, "top_p": 0.8}, "coding": {}}
      }
    }
  },
  "roles": {"agent": "main", "recall": "main", "memory": "main", "critic": "main"},
  "options": {"prediction": false, "critic": false},
  "embedding": {"url": "http://127.0.0.1:7190/v1"}
}
```

| Field | What it is |
|---|---|
| `endpoints` | The servers, under names you chose. |
| `url` | The address, ending in `/v1`. The only field an endpoint must have. |
| `model` | The model name to ask for, on a server that hosts several. |
| `key`, `key_env` | An API key, or the name of the environment variable that holds one. |
| `kind` | `thinking` or `instruct`: whether the model reasons before it answers. |
| `work` | `general` or `coding`: what the endpoint is used for. |
| `reasons` | For a `thinking` endpoint, which roles are asked to reason. Absent means the defaults. |
| `sampling` | The numbers sent with a request, one row per `kind` and `work`. Absent means the server keeps its own. The knobs are `temperature`, `top_p`, `top_k`, `min_p`, `presence_penalty`, `repeat_penalty`. |
| `roles` | Which endpoint answers each role. A role left out follows `agent`. |
| `options` | The optional faculties, on or off for the whole machine. |
| `embedding` | An embedding server, optional: `url`, and `model`, `key` or `key_env` as for an endpoint. With one, the memory is searched by meaning: before a recall, and when a new memory looks for the ones it is related to. Without one, or while it does not answer, by words. |

A file that cannot be followed — broken JSON, a role naming an endpoint that
is not listed — is an error, and Pragma says so. It does not fall back to
another server.

It is never part of a snapshot, so no address or key ends up in a zip.

### `projects/<name>/`

| Path | What it is |
|---|---|
| `episodes/ep_<date>_<time>_<id>.json` | One episode each. |
| `episodes/dormant/` | Episodes that have faded out of use. They come back when needed. |
| `learnings.json` | The beliefs drawn from the episodes. |
| `jobs/job_<stamp>_<n>.json` | Memory being written, or that did not finish. |
| `jobs/.lock` | Held by whoever is writing to this memory. |

What is inside an episode or a belief is Pragma's own and may change between
versions. Read them with [`/memory`](commands.md#memory), which shows the
same content in a form meant for reading.

A run started with `agent.batch --memory` and no project uses the same
layout directly under `~/.pragma`.

### A job file

Exists only while there is work to do: a job that finishes deletes itself.

| Field | What it is |
|---|---|
| `id` | The file's own name. |
| `status` | `pending`, `running`, `done` or `failed`. `/jobs` shows `abandoned` for one that says `running` and whose process is gone. |
| `pid` | The process doing the work. |
| `created`, `started`, `finished` | When, in UTC. |
| `workspace` | The folder the conversation was in. |
| `note` | What it is, in a few words. |
| `turns` | The conversation being written down: what you said and what was done. |
| `log` | What each stage reported, line by line. `/jobs` shows this. |
| `episodes` | The episodes written, once done. |
| `error` | Why it failed. |

To run one again: [Recover a memory that did not finish
writing](../how-to/recover-unfinished-memory.md).

### `plugins/<name>/plugin.json`

A plugin adds commands to the home screen.

```json
{
  "name": "example",
  "commands": {
    "/hello": {
      "blurb": "say hello - /hello <project>",
      "run": ["{python}", "-m", "example.cli", "hello"],
      "cwd": "/path/to/example",
      "complete": "projects"
    }
  }
}
```

| Field | What it is |
|---|---|
| `blurb` | The line shown beside the command. |
| `run` | The program and its arguments. What was typed after the command is appended. |
| `cwd` | The folder it runs in. |
| `complete` | `projects` completes project names after the command. |

In `run`, `{python}` is Pragma's own interpreter, `{plugin}` the plugin's
folder and `{pragma}` the folder Pragma is installed in. A plugin cannot
replace a built-in command, and one that cannot be read is skipped with a
line saying why.

## In the folder you work in

| Path | What it is | Written by |
|---|---|---|
| `PRAGMA.md` | Your [rules for the project](../how-to/write-project-rules.md). | you, and only you |
| `.pragma_session.jsonl` | The conversations held here, one line per turn. | the conversation |
| `.pragma_checkpoints/` | Copies of files as they were before the agent edited them. | the agent's tools |

**`.pragma_session.jsonl`** holds what you typed and what was done, in full,
and is added to on every turn. It is what lets a conversation survive a
crash. Each line is one JSON object:

| Field | What it is |
|---|---|
| `ts` | When the turn started, in UTC. |
| `user` | What you typed. |
| `transcript` | What happened in the turn, step by step. |

**`.pragma_checkpoints/<session>/`** has one folder per conversation. The
first time a file is edited, the version that was there is copied in, and
`manifest.json` records it:

| Field | What it is |
|---|---|
| `existed` | Whether the file was there before. `false` means undoing removes it. |
| `copy` | The name of the saved copy, when it existed. |
| `size`, `ts` | Its size, and when it was saved. |

If the folder you work in is a git repository, keep both out of it:

```
.pragma_session.jsonl
.pragma_checkpoints/
```

## In the folder Pragma is installed in

| Path | What it is |
|---|---|
| `.env` | Settings for the whole machine. Never committed. Start from [`.env.example`](../../.env.example). |
| `venv/` | The Python environment the installer builds. |
