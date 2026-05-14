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

<img src="https://img.shields.io/badge/runs%20on-llama.cpp%20%2F%20Ollama-f97316?style=flat-square" alt="llama.cpp / Ollama">
</p>

<p align="center">
  <img src="pragma.gif" alt="Pragma demo" width="800">
</p>

---

Most AI agents are cloud-dependent black boxes. **Pragma runs** entirely **on your machine**, uses **open-source models** served by **llama.cpp** or **Ollama**, and streams every reasoning step live in the UI as it happens. You see the thinking, the tools, the observations — nothing hidden.

*From the Greek pragma — something accomplished through action.*

---

## ✦ What makes it different

**🏠 Everything runs locally.**
llama.cpp / Ollama, your models, your files. No data leaves your machine. No account, no API key, no vendor.

**🔍 The reasoning loop is visible.**
Every thought, action, and observation streams live in the UI. Watch the agent plan, execute, and react — step by step, in real time.

**🧠 Two models, two jobs.**
Pragma routes code generation to a dedicated coding model while a lighter model handles reasoning and orchestration. Better output without forcing one model to do everything.

**📐 Plain, readable stack.**
FastAPI · Vanilla JS · WebSocket. No framework magic. Every file is understandable in isolation.

---

## ⚡ Quickstart

**Requirements:** Python 3.10+ · a local LLM endpoint that speaks the OpenAI `/v1` protocol — typically [llama.cpp](https://github.com/ggerganov/llama.cpp) (reference setup, see below) or [Ollama](https://ollama.com)

```bash
git clone https://github.com/homoagens/pragma
cd pragma
```

```bat
install.bat          # Windows
```

```bash
chmod +x install.sh start.sh && ./install.sh   # Linux / macOS
```

Configure your model:

```bash
cp .env.example .env
```

```env
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:8091/v1   # llama.cpp default — use 11434 for Ollama
DEFAULT_MODEL=your-model-name
```

Start:

```bat
start.bat       # Windows
./start.sh      # Linux / macOS
```

Opens at **http://localhost:8006**. The settings panel in the UI shows the active `.env` entries (sensitive values masked) and lets you reload the config without restarting.

---

## 🦙 Local models

Pragma talks to any OpenAI-compatible `/v1/chat/completions` endpoint, so it
runs on top of:

- **llama.cpp** — primary reference, fastest path to large MoE models with
  custom KV-cache quantization and offloading. See the [Reference setup](#-reference-setup)
  below for the exact command.
- **Ollama** — easiest install if you don't want to manage flags. Pull a model
  with `ollama pull <name>` then point Pragma at `http://localhost:11434/v1`.

```env
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:8091/v1   # llama.cpp default — use 11434 for Ollama
LLM_API_KEY=
DEFAULT_MODEL=your-model-name
```

#### Separate model for code (optional)

The `code` skill can route to a dedicated coding model instead of using the
default one. The two active models are shown and highlighted in the UI as
each one is used. Leave the same value to use a single model for everything
(the reference setup does exactly this — one Qwen3 MoE handles both roles).

```env
CODING_MODEL=qwen2.5-coder
CODING_PROVIDER=openai
CODING_BASE_URL=http://localhost:11434/v1
```

---

## 🔌 Other providers

Pragma also supports OpenAI and Anthropic. These paths work but are not the main focus of the project and are less thoroughly tested.

<summary><strong>OpenAI / OpenAI-compatible APIs</strong> (Groq, Mistral, OpenRouter, DeepSeek…)</summary>

```env
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1   # or any compatible endpoint
LLM_API_KEY=sk-...
DEFAULT_MODEL=gpt-4o-mini
```

Any OpenAI-compatible endpoint works: set `LLM_BASE_URL` to the provider's URL and `DEFAULT_MODEL` to the model name.

</details>

<summary><strong>Anthropic</strong></summary>

```env
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
DEFAULT_MODEL=claude-haiku-4-5
```

</details>

<summary><strong>Custom backend proxy</strong></summary>

If you run your own inference proxy with a non-standard response schema, Pragma has a dedicated `backend` provider that handles it. The proxy must expose a `/llm` endpoint and return:

```json
{ "raw": { "choices": [{ "message": { "content": "..." } }] } }
```

```env
LLM_PROVIDER=backend
BACKEND_URL=http://your-proxy-host:port
BACKEND_KEY=your-key
DEFAULT_MODEL=your-model-name
```


</details>

---

## 📦 Reference setup

The exact local setup used during development. A single MoE model handles both
the ReAct reasoning loop and the `code` skill — no internet connection needed
after download.

| Role             | Model                          | Quantization | Context |
| ---------------- | ------------------------------ | ------------ | ------- |
| Default + Code   | Qwen 3.6 35B A3B (MoE)         | Q5\_K\_M     | 128k    |

**Step 1 — Download the GGUF**

[bartowski/Qwen\_Qwen3.6-35B-A3B-GGUF](https://huggingface.co/bartowski/Qwen_Qwen3.6-35B-A3B-GGUF)
→ `Qwen_Qwen3.6-35B-A3B-Q5_K_M.gguf`
(optional) the matching `mmproj-f16.gguf` for vision input.

**Step 2 — Serve it with llama.cpp**

```bash
llama-server \
    -hf bartowski/Qwen_Qwen3.6-35B-A3B-GGUF \
    -hff Qwen_Qwen3.6-35B-A3B-Q5_K_M.gguf \
    --mmproj /path/to/qwen36-35b-a3b-mmproj-f16.gguf \
    --port 8091 \
    -ngl 999 \
    -ncmoe 27 \
    -c 131072 \
    -ctk q4_0 \
    -ctv q4_0 \
    --flash-attn on \
    -t 16 \
    --no-mmap \
    --jinja
```

Key flags:
- `-c 131072` — full 128k context (matches `CONTEXT_WINDOW` in `.env`).
- `-ctk q4_0 -ctv q4_0` — KV cache quantized to 4-bit, fits the 12 GB VRAM budget.
- `-ncmoe 27` — keeps 27 MoE expert layers on CPU so the model loads in tight VRAM.
- `-ngl 999` — push everything else to GPU.
- `--jinja` — required for Qwen3's chat template.

**Step 3 — Point Pragma at the server**

```env
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:8091/v1
DEFAULT_MODEL=qwen36-35b-a3b
CODING_MODEL=qwen36-35b-a3b
CONTEXT_WINDOW=131072
MAX_TOKENS=32768
```

#### Hardware

Tested daily on:

| Component | Tested on |
|---|---|
| GPU VRAM | NVIDIA RTX A2000 12 GB |
| System RAM | 128 GB |
| CPU | Intel Xeon Silver 4314 (32 cores, 16 threads used via `-t 16`) |

- The 12 GB VRAM holds the active experts, KV cache (q4\_0), and the vision projector.
- The 128 GB RAM is what makes `-ncmoe 27` viable: 27 MoE expert layers stay on
  CPU and stream in as needed.
- CPU-only is possible with smaller / more quantized models but will be slow.
- If you have more VRAM, drop `-ncmoe` and you'll get a substantial speedup.

---

## 🗂 Architecture

```
pragma/
  agent/          FastAPI server · ReAct orchestration · skill wrappers
  core/           LLM client · memory compression · skill palette
  interface-web/  Vanilla JS + WebSocket UI — no build step
  ollama/         Optional Modelfiles for older Ollama-based setups
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
