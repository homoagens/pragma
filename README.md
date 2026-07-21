<p align="center">
  <img src="interface-web/logo.png" width="140" alt="Pragma">
</p>

<h2 align="center">Pragma</h2>

<p align="center">
  <em>A local-first autonomous agent you can actually understand.</em>
</p>

<p align="center">
  Open-source models  ·  Visible reasoning loop  ·  No black boxes  ·  No API key required
</p>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-5c6bc0?style=flat-square" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/frontend-vanilla%20JS%2C%20no%20build-43a047?style=flat-square" alt="No build step">
  <img src="https://img.shields.io/badge/runs%20on-llama.cpp-f97316?style=flat-square" alt="llama.cpp">
</p>

<p align="center">
  <img src="pragma.gif" alt="Pragma demo" width="800">
</p>

---

Most AI agents are cloud-dependent black boxes. **Pragma runs** entirely **on your machine**, uses **open-source models** served by **llama.cpp**, and streams every reasoning step live in the UI as it happens. You see the thinking, the tools, the observations — nothing hidden.

*From the Greek pragma — something accomplished through action.*

---

## ✦ What makes it different

**🏠 Everything runs locally.**
llama.cpp, your models, your files. No data leaves your machine. No account, no API key, no vendor.

**🔍 The reasoning loop is visible.**
Every thought, action, and observation streams live in the UI. Watch the agent plan, execute, and react — step by step, in real time.

**🧠 One model, different jobs.**
The same local model wears a different hat for each job — planning, choosing what to
remember, consolidating a session, distilling knowledge — each with its own system
prompt. Nothing is hardcoded to a vendor. (You *can* route the `code` skill to a
dedicated model with `CODING_MODEL`; by default it uses the same one.)

**⏳ A memory with a sense of time.**
Sessions become episodes, what recurs becomes knowledge, and what stops being recalled
fades — then resurfaces when it becomes relevant again. Later experience can change what
an old episode *means*, without rewriting what happened.

**📐 Plain, readable stack.**
FastAPI · Vanilla JS · WebSocket. No framework magic. Every file is understandable in isolation.

---

## ⚡ Quickstart

Two terminals: one serves the model, one runs Pragma.

### 1. Install

```bash
git clone https://github.com/homoagens/pragma
cd pragma
```

Three twin scripts, in order — `install` → `configure` → `start`:

```bat
install.bat          :: Windows — create venv + install deps
configure.bat        :: interactive: writes .env (backend URL, model, key)
start.bat            :: launch Pragma (opens the UI)
```

```bash
chmod +x install.sh configure.sh start.sh
./install.sh         # Linux / macOS — create venv + install deps
./configure.sh       # interactive: writes .env (backend URL, model, key)
./start.sh           # launch Pragma (opens the UI)
```

`configure` asks for your **OpenAI-compatible backend URL** (must end in `/v1`), the
model name, and an optional API key, then checks the endpoint answers. Re-run it any time
to change them — there is no config file to hand-edit.

### 2. Serve a model

Pragma talks to any OpenAI-compatible endpoint; you bring your own. The path of least
resistance is `llama.cpp` — grab a prebuilt binary from
[github.com/ggml-org/llama.cpp/releases](https://github.com/ggml-org/llama.cpp/releases)
(CUDA for NVIDIA, Vulkan for AMD/Intel, AVX2 for CPU-only) and serve a GGUF with
`llama-server`.

| | Model | Notes |
| --- | --- | --- |
| 🐉 **Reference** | **Qwen3.6 27B · Q5** | **The daily driver.** Everything here is developed and tested against it — if you want Pragma to behave as described, run this. 24 GB VRAM class. |
| 🐦 Starter | Qwen3.6 35B-A3B · Q5 | Mixture-of-experts, ~3B active parameters: fast even with experts offloaded to CPU, so it tolerates less VRAM than its size suggests. |
| ⚡ Ultra-light | Qwen3.6 9B · Q6 | For modest GPUs. It works; expect rougher reasoning on long tasks. |

Two flags matter regardless of model: **`-np 2`** (so a background consolidation can run
without blocking the foreground task) and **`--jinja`** (chat templates on Qwen-family
models). Leave the server terminal open.

Not sure how to launch it on your hardware? The next section has a prompt that writes the
command for you.

### 3. Start

```bat
start.bat       :: Windows
./start.sh      # Linux / macOS
```

Opens at **http://localhost:8006**. The settings panel shows the active `.env` entries and
the knowledge store, and reloads config without a restart.

---

## 🤖 Don't know llama.cpp?

You don't actually need to learn the flags from scratch. Paste this prompt into any LLM (Claude, ChatGPT, Gemini, even a local model) and it produces **OS- and hardware-specific install commands + a tuned `llama-server` invocation + the matching `.env`**.

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
   and give me the direct download link. Prefer Qwen3 MoE for ≥16 GB VRAM,
   smaller dense models otherwise.

3. The full `llama-server` command to launch it, with appropriate flags for:
     - context window appropriate for the model
     - GPU offloading (-ngl)
     - MoE expert offloading (-ncmoe) if the model is MoE and VRAM is tight
     - KV cache quantization (-ctk / -ctv) if memory is tight
     - flash attention (--flash-attn on)
     - **MANDATORY: -np 2** so the foreground task and the background
       consolidation worker (session_reflect) run in parallel. Without this
       Pragma's UI blocks waiting for the worker to finish serially.
     - threads (-t) = my CPU physical core count
     - --jinja for chat template handling on Qwen-family models
   The server must listen on port 11434.

4. A curl command to verify the server is responding on /v1/models.

5. The .env values I should put in Pragma:
     LLM_BASE_URL=http://127.0.0.1:11434/v1
     DEFAULT_MODEL=<the name llama-server reports for the loaded model>
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

Fill in the four hardware lines, run what comes back, you're done.

---

## 🖥 Batch mode — Pragma without the UI

`agent.batch` runs **one task start to finish** from the terminal: no browser, no
interaction, every reasoning step streamed to stdout. It is what you reach for in a
script, a scheduled job or a CI step — and it is where Pragma's memory work happens.

```bat
venv\Scripts\python.exe -m agent.batch --task "fix the failing test" --cwd C:\my\project
```

```bash
./venv/bin/python -m agent.batch --task "fix the failing test" --cwd /my/project
```

**The output adapts to where it lands:**

| Where it goes | Mode | What you get |
| --- | --- | --- |
| a terminal | pretty | live rendering: step rules, dim thoughts, cyan actions, the conclusion as real Markdown in a panel |
| a redirect (`> run.md`) | markdown | a clean Markdown document — view it rendered with `glow run.md` (or `python -m rich.markdown run.md`) |
| `--plain` | plain | flat `[HH:MM:SS] STEP n ...` lines, stable for grepping from scripts |

Useful flags:

- `--task-file task.txt` — or pipe the task on stdin
- `--log run.json` — full structured step log (every observation, untruncated)
- `--max-steps 25` · `--temperature 0.2` (default `0.0`, for reproducible runs)
- `--memory` — persistent memory, see below

**Where it works.** The workspace is `--cwd`, else `PRAGMA_WORKSPACE`, else the current
directory — and Pragma's own source tree is **always refused**, so a stray run can't
edit the agent that is running it. Point it at a dedicated folder.

Exit codes: `0` clean conclusion · `2` step budget exhausted (forced verdict) · `1` failure.

> [!NOTE]
> **No user, no blocking.** In batch `ask_user` never waits: confirmation
> requests for destructive actions fail safe to *no*, unless the operation is
> explicitly authorized in the task text or in `PRAGMA.md` (below).

### Memory (`--memory`) — experimental

> [!WARNING]
> **This is the newest and least settled part of Pragma.** It is under active
> development: the faculties, the parameters and the on-disk format can change between
> commits. Everything else in Pragma is stable; this is the moving edge. Point it at a
> throwaway store (`PRAGMA_DATA_DIR`) before you rely on it.

With `--memory` a run is no longer an isolated episode. Between sessions the memory has a
life cycle of its own:

- **at the start**, a curator picks only the *relevant* past episodes and learnings and puts them in context — not the whole history;
- **at the end**, the session is consolidated into an episode — what was done, what surprised, how important it was — under `~/.pragma/episodes/` (override with `PRAGMA_DATA_DIR`);
- what **recurs across episodes** is distilled into an assertion with sources and confidence — the store you see in **Settings → Knowledge** in the UI;
- what stops being recalled **fades**: episodes decay with time into a dormant zone, and come back when a later session makes them relevant again;
- new experience can **reinterpret** older episodes and reformulate a belief, keeping every previous version — the recorded facts are never rewritten.

Each faculty tags its own line in the output (`[CURATOR]`, `[CONSOLIDATOR]`,
`[ABSTRACTOR]`, `[FORGETTING]`, `[RECONSOLIDATOR]`), so you can watch what memory did.

No `--memory`, no traces: batch runs are stateless by default.

### PRAGMA.md — the project contract

Drop a `PRAGMA.md` in the workspace root and every batch run injects it as user-authored project instructions: conventions, constraints, standing authorizations (*"deletions in this folder are pre-authorized"*). The file is **read-only for the agent** — it can follow it, never rewrite it.

---

## 🗂 Architecture

```
pragma/
  agent/          FastAPI server · batch runner · ReAct orchestration · skill wrappers
  core/           LLM client · ReAct loop · persistent memory · skill palette
  interface-web/  Vanilla JS + WebSocket UI — no build step
```

**`core/`** — provider-agnostic, reusable:

| File            | Role                                                   |
| --------------- | ------------------------------------------------------ |
| `llm_client.py` | Calls the OpenAI-compatible `/chat/completions` endpoint |
| `react.py`      | Generic ReAct loop with streaming `on_step` callback   |
| `memory.py`     | Context compression *within* one conversation          |
| `episodes.py`   | Persistent episodic store: salience, decay, dormant zone, revival |
| `curator.py`    | Picks which past episodes and beliefs enter the next context |
| `reconsolidate.py` | Rewrites what a past episode or belief *means* — recorded facts stay frozen |
| `skills/`       | One folder per skill — filesystem, shell, web, LLM, code… |

Two different things are called memory here: `memory.py` compresses a single growing
conversation, while `episodes.py` · `curator.py` · `reconsolidate.py` are the store that
persists *between* sessions. Writing an episode and distilling knowledge from recurrence
happen in the `episode_consolidate` skill, at the end of a session.

**`agent/`** — Pragma-specific behavior on top of core:

- Per-thread working directory, concurrency-safe
- Thread persistence on disk as JSON
- WebSocket streaming with async/thread bridging

---

## 📄 Research artifacts

Pragma's memory subsystem is the subject of a paper in preparation, *"Giving Stateless
Agents a Sense of Time: A Reconsolidating Episodic–Semantic Memory Architecture."*

The evaluation corpus, the experimental stimuli, and the derived datasets are deposited
separately from this repository, under a persistent identifier:

**DOI:** [10.5281/zenodo.21474334](https://doi.org/10.5281/zenodo.21474334)
*(the deposit is being finalized; the link resolves once it is published)*

The deposit holds the raw execution traces of every archived run — session transcripts,
episodic and semantic stores with their revision histories, and metadata pinning the
served model, code revision, and memory parameters — so that the reported results can be
inspected independently of this codebase.

---

## 🌱 Part of Homo Agens

Pragma is the first public project under **[Homo Agens](https://github.com/homoagens)** — an open-source effort exploring autonomous agents, local inference, and a simple thesis:

> The model matters less than the architecture around it.  
> Memory, tools, transparency, and execution control are what turn an LLM into something that actually gets things done.

---

## 📬 Contact

If you work on agents, local AI, open-source tooling, or developer experience — let's talk.

[Email](mailto:homoagens1@gmail.com) &nbsp;·&nbsp; [X / Twitter](https://x.com/homoagens1)

---

## License

[AGPL-3.0-or-later](./LICENSE) — free to use, study, modify and share. If you distribute a modified Pragma, or offer it to others as a service, you must release your changes under the same license. That's the deal: take freely, give back freely.

Versions up to commit `12e94d8` (2026-07-12) were published under the MIT license.
