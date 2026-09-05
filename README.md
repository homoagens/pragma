<p align="center">
  <img src="interface-web/logo.png" width="140" alt="Pragma">
</p>

<h2 align="center">Pragma</h2>

<p align="center">
  <em>A local agent with a memory that forgets.</em>
</p>

<p align="center">
  Your machine  ·  Open models  ·  No API key  ·  A terminal you can live in
</p>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-5c6bc0?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/platform-Windows-0078d4?style=flat-square" alt="Windows">
  <img src="https://img.shields.io/badge/runs%20on-llama.cpp-f97316?style=flat-square" alt="llama.cpp">
  <a href="https://doi.org/10.5281/zenodo.21474333"><img src="https://img.shields.io/badge/DOI-10.5281%2Fzenodo.21474333-blue?style=flat-square" alt="DOI"></a>
</p>

<p align="center">
  <img src="pragma.gif" alt="Pragma" width="800">
</p>

---

Pragma runs on your machine, against a model you serve yourself, and **remembers
between sessions** — not by keeping a transcript, but by writing down what
happened, distilling what recurs, and letting the rest fade. Come back after a
month and it tells you what it still holds and what has gone quiet.

*From the Greek pragma — something accomplished through action.*

---

## Quickstart

**1. Install it.**

```bat
git clone https://github.com/homoagens/pragma.git
cd pragma
.\install.ps1
```

Builds the Python environment and adds one line to your PowerShell profile.
`tools\install.bat` does the same from a double-click.

Windows only for now. The launcher is a PowerShell module and nothing else has
been tested, so the rest is not offered rather than offered and broken.

**2. Serve a model.** Any OpenAI-compatible endpoint. The short path is
[llama.cpp](https://github.com/ggml-org/llama.cpp/releases): grab a prebuilt
binary, serve a GGUF with `llama-server`, leave that terminal open. Two flags
matter — `-np 2` so a background consolidation does not block your turn, and
`--jinja` for chat templates on Qwen-family models.

*Never launched llama.cpp?* [There is a prompt below](#dont-know-llamacpp) that
writes the command for your hardware.

**3. Open a new terminal and go.**

```bat
cd D:\notes
pragma
```

A **new** terminal, or the profile line is not read yet and `pragma` is not a
command. That is the only reason the old window will not do.

Everything else happens inside. The first run has no projects and offers to
make one, proposing the folder you are standing in — two presses of Enter.
Then `/configure` to point it at the server from step 2; leave the model name
**empty**, so Pragma asks the endpoint what it is serving and cannot go stale
the day you load another one.

From then on, `pragma` on its own is the whole thing.

---

## What you get

<!-- TODO: a short recording of the harness goes here -->

```
 ████████████
 █████████████
       ██   ███
    █  ██   ███
  ████████████   _ _ __ _ __ _ _ __  __ _
 ████████████   | '_/ _` / _` | '  \/ _` |
 ████           |_| \__,_\__, |_|_|_\__,_|
 ██                       |___/

   Saturday 5 September, 09:35

  project   notes
  memory    65 episodes active, 4 dormant, 36 beliefs
  away for  19 days                       tau 0.63
  serving   Qwen3.6-27B

  Since you left
    4 episodes went dormant
    1 belief revised - "fixed-price contracts, this client"
    last time you were on: the deployment that went wrong on a Friday

  /chat to talk   ·   /help for everything else

  you >
```

**That screen is the point.** Opening a session used to tell you nothing;
here the store says how long you have been away in half-lives of its own
forgetting, what slipped below the surface while you were gone, and what it
last saw you doing.

`/chat` opens a conversation. `/exit` or `Ctrl+D` comes back here; again, and
you are out.

---

## The commands

Type `/` and they appear, narrowed by what you type next.

| | |
| --- | --- |
| `/chat` | talk to it — many turns, one conversation |
| `/map` | everything in memory, with what has faded |
| `/beliefs` | what it has concluded from what recurred |
| `/diff` | meanings it has revised, before and after |
| `/oblio` | the dormant zone |
| `/last` | the newest episode, in full |
| `/configure` | point Pragma at an LLM endpoint |
| `/settings` | model, budgets, sampling for this project |
| `/backups` | snapshot or restore |
| `/switch` `/new` `/delete` | projects |
| `/help` | all of it |

Anything that is not a command is a message.

---

## Projects

A project is **one folder you work in** plus **a memory of its own**. `/new`
makes one, or `pragma` does when there are none yet.

The folder is the workspace: the agent reads and writes there. The memory
lives apart, under `~/.pragma/projects/notes` — never inside your folder,
because a workspace is often a git repository and personal episodes have no
business in one.

Without the menu, for a script or a habit:

```bat
cd D:\notes
pragma -Register -Name notes
```

One folder, one project, nesting included. So `pragma` from anywhere inside a
registered folder never has to ask which memory you mean.

**`PRAGMA.md`** in the workspace is the other half. Memory is what the agent
*learns*; that file is what you *decide*, and a rule in it always applies:

```markdown
## Conventions
- journal.md holds dated reflections; notebook.md holds course notes.
```

---

## The memory

Every session that was worth keeping becomes an **episode** — what you were
doing, what happened, what it seems to mean. What recurs across episodes is
distilled into **beliefs**, each carrying the episodes it rests on.

**It forgets on purpose.** An episode's salience decays with the time since it
was last recalled; below a threshold it goes dormant — out of the way, not
deleted — and comes back when a question matches it again. Nothing is
destroyed by default.

**And it changes its mind.** Later experience can rewrite what an old episode
*means* while the record of what happened stays frozen. A belief that
accumulates contradictions is reformulated rather than merely dropped.

That is the subject of the paper below, and the numbers there come from 229
recorded executions rather than from this paragraph.

---

## Backups

`/backups` takes a snapshot of the memory, the workspace, or both, and
restores one. Restoring names what it will replace, asks you to type the
project's name, and **takes a snapshot of the current state first** — so a
restore is itself undoable.

The workspace is never deleted by a restore, only overwritten file by file:
that folder is yours, and Pragma removes only what Pragma made.

---

## Configuration

`/configure` writes `.env`, which holds the endpoint. **The endpoint decides
the model** — llama.cpp
serves whatever is loaded and ignores the name in the request — so leaving
`DEFAULT_MODEL` empty is the right answer for a single-model server. Set it
only when the endpoint hosts several and the field actually selects one.

Sampling has three states, in `/settings`:

- **the server's** — nothing is sent, the endpoint decides all four
- **by hand** — you set temperature, top_k, top_p, min_p
- **greedy** — temperature 0, deterministic

The memory faculties run at temperature 0 regardless, so the store stays
reproducible whatever the conversation is doing.

---

## Other ways in

**The browser interface** — the older way, with threads and panes:

```bat
.\pragma-gui.bat
```

Opens at `http://localhost:8006`.

**One task, no conversation** — for scripts and long jobs:

```bat
venv\Scripts\python.exe -m agent.batch "read my notes and list what I left unfinished" --cwd D:\notes --memory
```

Stateless without `--memory`. Each faculty tags its own output (`[CURATOR]`,
`[CONSOLIDATOR]`, `[ABSTRACTOR]`, `[FORGETTING]`, `[RECONSOLIDATOR]`) so you
can watch what memory did.

---

## Don't know llama.cpp?

Paste this into any LLM and it produces install commands, a tuned
`llama-server` invocation, and the matching `.env` for your hardware.

<details>
<summary>Show the prompt</summary>

```
I need to run llama.cpp locally as the inference backend for an OpenAI-compatible
HTTP API (it will be consumed by an agent framework called Pragma).

Tell me, step by step:

1. How to download and install the right prebuilt llama.cpp binary for my OS
   and GPU vendor from https://github.com/ggml-org/llama.cpp/releases (CUDA for
   NVIDIA, Vulkan for AMD/Intel, AVX2/AVX512 for CPU only). Give me the exact
   filename to download.

2. Which GGUF model to download for my hardware. Recommend a sensible
   default from bartowski's collection on Hugging Face for my VRAM/RAM budget,
   and give me the direct download link. Prefer Qwen3 MoE for >=16 GB VRAM,
   smaller dense models otherwise.

3. The full `llama-server` command to launch it, with appropriate flags for:
     - context window appropriate for the model
     - GPU offloading (-ngl)
     - MoE expert offloading (-ncmoe) if the model is MoE and VRAM is tight
     - KV cache quantization (-ctk / -ctv) if memory is tight
     - flash attention (--flash-attn on)
     - **MANDATORY: -np 2** so the foreground task and the background
       consolidation worker run in parallel. Without this Pragma blocks
       waiting for the worker to finish serially.
     - threads (-t) = my CPU physical core count
     - --jinja for chat template handling on Qwen-family models
   The server must listen on port 11434.

4. A curl command to verify the server is responding on /v1/models.

5. The .env values I should put in Pragma:
     LLM_BASE_URL=http://127.0.0.1:11434/v1
     DEFAULT_MODEL=            (leave empty: Pragma asks the endpoint)
     CONTEXT_WINDOW=<same value used with -c in the server>
     MAX_TOKENS=<sensible output cap, typically context/4>

My hardware:
- OS: <Windows 11 / Ubuntu 24.04 / macOS 14 / ...>
- GPU: <NVIDIA RTX 4070 12GB / AMD RX 7900 24GB / no discrete GPU / ...>
- RAM: <32 GB / 64 GB / ...>
- CPU: <model + physical core count>

Be concrete: filenames, full commands, expected output. No prose, no theory.
```

</details>

Which model? Everything here is developed against **Qwen3.6 27B · Q5** (24 GB
VRAM class). **Qwen3.6 35B-A3B · Q5** is a mixture-of-experts with ~3B active
parameters — fast even with experts on the CPU, so it tolerates less VRAM than
its size suggests.

---

## Architecture

```
pragma/
  agent/          chat harness · batch runner · FastAPI server · ReAct orchestration
  core/           LLM client · ReAct loop · the memory · skill palette
  tools/          the launcher: PowerShell module, briefing, endpoint report,
                  configuration, mem_map.py behind /map and /beliefs, and the
                  wrappers - install, build, batch sessions
  interface-web/  the browser UI - vanilla JS, no build step
```

**`core/`** — provider-agnostic:

| File | Role |
| --- | --- |
| `llm_client.py` | Calls the OpenAI-compatible `/chat/completions` endpoint |
| `react.py` | Generic ReAct loop with a streaming `on_step` callback |
| `clock.py` | The one place time comes from — injectable, so a run can be aged |
| `episodes.py` | The episodic store: salience, decay, dormancy, revival |
| `curator.py` | Chooses which episodes and beliefs enter the next context |
| `reconsolidate.py` | Rewrites what an episode or belief *means*; facts stay frozen |
| `memory.py` | Compression *within* one conversation — a different thing |
| `skills/` | One folder per skill: filesystem, shell, web, code |

Two different things are called memory: `memory.py` compresses a single
growing conversation, while `episodes.py`, `curator.py` and `reconsolidate.py`
are the store that persists *between* sessions.

Design notes live in [`docs/`](./docs).

---

## Research artifacts

Pragma's memory subsystem is the subject of *"Giving Stateless Agents a Sense
of Time: A Reconsolidating Episodic–Semantic Memory Architecture"*, under
review.

The evaluation corpus, the stimuli and the derived datasets are deposited
separately:

**DOI:** [10.5281/zenodo.21474333](https://doi.org/10.5281/zenodo.21474333)
*(concept DOI — always resolves to the most recent version)*

The deposit holds the raw traces of every archived run: transcripts, episodic
and semantic stores with their revision histories, and metadata pinning the
served model, code revision and memory parameters — so the reported results
can be checked without trusting this codebase.

---

## Part of Homo Agens

Pragma is the first public project under
**[Homo Agens](https://github.com/homoagens)**, an open-source effort on
autonomous agents, local inference, and a simple thesis:

> The model matters less than the architecture around it.
> Memory, tools, transparency and execution control are what turn an LLM into
> something that gets things done.

---

## Contact

If you work on agents, local AI, or developer experience — let's talk.

[Email](mailto:homoagens1@gmail.com) &nbsp;·&nbsp; [X](https://x.com/homoagens1)

---

## License

[AGPL-3.0-or-later](./LICENSE) — free to use, study, modify and share. If you
distribute a modified Pragma, or offer it to others as a service, you must
release your changes under the same license. Take freely, give back freely.

Versions up to commit `12e94d8` (2026-07-12) were published under the MIT
license.
