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

<img src="https://img.shields.io/badge/runs%20on-Ollama-f97316?style=flat-square" alt="Ollama">
</p>

<p align="center">
  <img src="pragma.gif" alt="Pragma demo" width="800">
</p>

---

Most AI agents are cloud-dependent black boxes. **Pragma runs** entirely **on your machine**, uses **open-source models** through **Ollama**, and streams every reasoning step live in the UI as it happens. You see the thinking, the tools, the observations — nothing hidden.

*From the Greek pragma — something accomplished through action.*

---

## ✦ What makes it different

**🏠 Everything runs locally.**
Ollama, your models, your files. No data leaves your machine. No account, no API key, no vendor.

**🔍 The reasoning loop is visible.**
Every thought, action, and observation streams live in the UI. Watch the agent plan, execute, and react — step by step, in real time.

**🧠 Two models, two jobs.**
Pragma routes code generation to a dedicated coding model while a lighter model handles reasoning and orchestration. Better output without forcing one model to do everything.

**📐 Plain, readable stack.**
FastAPI · Vanilla JS · WebSocket. No framework magic. Every file is understandable in isolation.

---

## ⚡ Quickstart

**Requirements:** Python 3.10+ · [Ollama](https://ollama.com) with at least one model

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
LLM_BASE_URL=http://localhost:11434/v1
DEFAULT_MODEL=your-model-name
```

Start:

```bat
start.bat       # Windows
./start.sh      # Linux / macOS
```

Opens at **http://localhost:8006**. The settings panel in the UI shows the active `.env` entries (sensitive values masked) and lets you reload the config without restarting.

---

## 🦙 Local models with Ollama

Ollama is the primary and most tested way to run Pragma. Pull any model and point Pragma at it.

```env
LLM_PROVIDER=openai
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=
DEFAULT_MODEL=your-model-name
```

#### Separate model for code

One of Pragma's strongest features: the `code` skill uses a dedicated coding model instead of burdening the reasoning model with everything. The two active models are shown and highlighted in the UI as each one is used.

```env
CODING_MODEL=qwen2.5-coder
CODING_PROVIDER=openai
CODING_BASE_URL=http://localhost:11434/v1
```

Keep a small general model for orchestration, route code generation to something specialized — `qwen2.5-coder`, `deepseek-coder`, or any other coding-focused model available in Ollama.

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

The exact local setup used during development. Both models run entirely on Ollama — no internet connection needed after download.

| Role       | Model                      | Quantization | RAM   |
| ---------- | -------------------------- | ------------ | ----- |
| Reasoning  | Google Gemma 4 E4B         | Q8\_0        | ~8 GB |
| Code skill | Qwen 2.5 Coder 7B Instruct | Q4\_K\_M     | ~5 GB |

**Step 1 — Download the GGUF files**

- [bartowski/google\_gemma-4-E4B-it-GGUF](https://huggingface.co/bartowski/google_gemma-4-E4B-it-GGUF) → `google_gemma-4-E4B-it-Q8_0.gguf`
- [bartowski/Qwen2.5-Coder-7B-Instruct-GGUF](https://huggingface.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF) → `Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf`

**Step 2 — Register with Ollama**

The Modelfiles are in [`ollama/`](./ollama/). Place each GGUF in the same folder as its Modelfile, then:

```bash
ollama create gemma4-e4b     -f ollama/gemma4-e4b.Modelfile
ollama create qwen2.5-coder  -f ollama/qwen2.5-coder.Modelfile
```

**Step 3 — Point Pragma at them**

```env
DEFAULT_MODEL=gemma4-e4b
CODING_MODEL=qwen2.5-coder
```

> New to Ollama? Two-minute setup at [ollama.com](https://ollama.com).

---

## 🗂 Architecture

```
pragma/
  agent/          FastAPI server · ReAct orchestration · skill wrappers
  core/           LLM client · memory compression · skill palette
  interface-web/  Vanilla JS + WebSocket UI — no build step
  ollama/         Modelfiles for the reference local setup
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
