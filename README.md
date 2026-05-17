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
  <a href="https://github.com/homoagens/pragma/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-5c6bc0?style=flat-square" alt="License">
  </a>

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

```bash
git clone https://github.com/homoagens/pragma
cd pragma
```

```bat
install.bat          :: Windows
```

```bash
chmod +x install.sh start.sh && ./install.sh    # Linux / macOS
```

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

```bash
cp .env.example .env
```

> [!TIP]
> **→ [Copy the matching `.env` block from CONFIGS.md](./CONFIGS.md)** for the same tier — model name, `CONTEXT_WINDOW`, `MAX_TOKENS`. Paste it into your local `.env`, save.

```bat
start.bat       :: Windows
./start.sh      # Linux / macOS
```

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
     LLM_PROVIDER=openai
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

Prefer a hosted API to a local server? Pragma also speaks OpenAI-compatible and Anthropic.

<details>
<summary>OpenAI / OpenAI-compatible (Groq, OpenRouter, DeepSeek, …)</summary>

```env
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
DEFAULT_MODEL=gpt-4o-mini
```

</details>

<details>
<summary>Anthropic</summary>

```env
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
DEFAULT_MODEL=claude-haiku-4-5
```

</details>

---

## 🗂 Architecture

```
pragma/
  agent/          FastAPI server · ReAct orchestration · skill wrappers
  core/           LLM client · memory compression · skill palette
  interface-web/  Vanilla JS + WebSocket UI — no build step
```

**`core/`** — provider-agnostic, reusable:

| File            | Role                                                   |
| --------------- | ------------------------------------------------------ |
| `llm_client.py` | Dispatches to OpenAI-compatible or Anthropic endpoints |
| `agent.py`      | Generic ReAct loop with streaming `on_step` callback   |
| `memory.py`     | Transparent context compression as conversations grow  |
| `skills/`       | One folder per skill — filesystem, shell, web, LLM, code… |

**`agent/`** — Pragma-specific behavior on top of core:

- Per-thread working directory, concurrency-safe
- Thread persistence on disk as JSON
- WebSocket streaming with async/thread bridging

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

[MIT](./LICENSE)
