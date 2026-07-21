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

**🧠 Two models, two jobs.**
Pragma routes code generation to a dedicated coding model while a lighter model handles reasoning and orchestration. Better output without forcing one model to do everything.

**📐 Plain, readable stack.**
FastAPI · Vanilla JS · WebSocket. No framework magic. Every file is understandable in isolation.

---

## ⚡ Quickstart

Three things, two terminals, you're online.

### 1. Install Pragma

Pick one of two ways.

#### Option A — prebuilt executable (no Python, no setup)

Download the single-file build for your OS from the
[**Releases page**](https://github.com/homoagens/pragma/releases):

| OS | File | Run it |
| --- | --- | --- |
| Windows | `pragma.exe` | double-click, or run `pragma.exe` in a terminal |
| Linux / macOS | `pragma` | `chmod +x pragma && ./pragma` |

One file, nothing to install. It still needs a model (step 2) — point it at
one by loading a `.env` from **Settings → Load .env file…** in the UI.

> [!NOTE]
> On an **older Linux** (or an **ARM** machine) a prebuilt binary may refuse
> to start due to a system-library mismatch. Use Option B there — run from
> source, or build the executable on that machine with `build.sh`.

#### Option B — from source

```bash
git clone https://github.com/homoagens/pragma
cd pragma
```

The from-source pipeline is **three twin scripts**, in order — `install` → `configure` → `start`:

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

`configure` asks for your **OpenAI-compatible backend URL** (must end in `/v1`), the model name, and an optional API key, then verifies the endpoint is reachable. Run it again any time to change them.

### 2. Serve a model

Pragma talks to any OpenAI-compatible endpoint. The path of least resistance is `llama.cpp`. Grab a prebuilt binary from [github.com/ggml-org/llama.cpp/releases](https://github.com/ggml-org/llama.cpp/releases) (CUDA for NVIDIA, Vulkan for AMD/Intel, AVX2 for CPU-only), then pick a ready-made `llama-server` recipe for your hardware in **[CONFIGS.md](./CONFIGS.md)**:

| Tier | Hardware | Model | Speed |
| --- | --- | --- | --- |
| 🐦 **Starter** | 4 GB VRAM | Qwen 3.5 9B, partial CPU offload | ~10 tok/s |
| 🐉 **Reference** | 12 GB VRAM | Qwen 3.6 35B A3B MoE, 128k context | (daily driver) |
| ⚡ **Ultra-light** | 4 GB VRAM | Qwen 3 4B, all-on-GPU | ~30 tok/s (expect rough edges) |

> [!TIP]
> **→ [Copy the matching `llama-server` command from CONFIGS.md](./CONFIGS.md)** and run it. Leave the terminal open.

Different hardware? See [Don't know llama.cpp?](#-dont-know-llamacpp) below — there's a prompt you can paste into any LLM and it generates a tuned command for your exact box.

### 3. Point Pragma at it

`configure` already wrote the backend URL, model and key into `.env`. For the per-tier extras (`CONTEXT_WINDOW`, `MAX_TOKENS`):

> [!TIP]
> **→ [Copy the matching `.env` block from CONFIGS.md](./CONFIGS.md)** for your tier and merge the extra lines into your `.env`.

Then just `start`:

```bat
start.bat       :: Windows
./start.sh      # Linux / macOS
```

> [!TIP]
> **Using the prebuilt executable (Option A)?** No scripts needed — just run the
> executable. It opens the UI automatically; load your `.env` from
> **Settings → Load .env file…**.

Opens at **http://localhost:8006**. The settings panel in the UI shows the active `.env` entries and the global learnings store; you can reload config without restarting.

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

## 🔌 Cloud providers (optional)

Prefer a hosted API to a local server? Any OpenAI-compatible endpoint works — just point `LLM_BASE_URL` at it.

<details>
<summary>OpenAI / OpenAI-compatible (Groq, OpenRouter, DeepSeek, …)</summary>

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
DEFAULT_MODEL=gpt-4o-mini
```

For Groq, OpenRouter, DeepSeek, etc. swap `LLM_BASE_URL` for their `/v1` endpoint and use their key.

</details>

---

## 🖥 Batch mode — Pragma without the UI

Need Pragma in a script, a scheduled job, or a CI step? `agent.batch` runs **one task start-to-finish** from the terminal — no browser, no interaction, every reasoning step streamed live to stdout.

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
- `--memory` — episodic memory, see below

Exit codes: `0` clean conclusion · `2` step budget exhausted (forced verdict) · `1` failure.

> [!NOTE]
> **No user, no blocking.** In batch `ask_user` never waits: confirmation
> requests for destructive actions fail safe to *no*, unless the operation is
> explicitly authorized in the task text or in `PRAGMA.md` (below).

### Memory (`--memory`)

With `--memory` each batch run remembers and learns:

- **at the start**, the most relevant *episodes* from past sessions (plus distilled learnings) are injected into the task;
- **at the end**, the session is consolidated into a new episode — what was done, what surprised, what it means — stored in `~/.pragma/episodes/`;
- when a pattern **recurs across episodes**, it is distilled into a general assertion with sources and confidence — the same knowledge store you see in **Settings → Knowledge** in the UI.

No `--memory`, no traces: batch runs are stateless by default.

### PRAGMA.md — the project contract

Drop a `PRAGMA.md` in the workspace root and every batch run injects it as user-authored project instructions: conventions, constraints, standing authorizations (*"deletions in this folder are pre-authorized"*). The file is **read-only for the agent** — it can follow it, never rewrite it.

---

## 🗂 Architecture

```
pragma/
  agent/          FastAPI server · batch runner · ReAct orchestration · skill wrappers
  core/           LLM client · memory compression · skill palette
  interface-web/  Vanilla JS + WebSocket UI — no build step
```

**`core/`** — provider-agnostic, reusable:

| File            | Role                                                   |
| --------------- | ------------------------------------------------------ |
| `llm_client.py` | Calls the OpenAI-compatible `/chat/completions` endpoint |
| `react.py`      | Generic ReAct loop with streaming `on_step` callback   |
| `memory.py`     | Transparent context compression as conversations grow  |
| `skills/`       | One folder per skill — filesystem, shell, web, LLM, code… |

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
