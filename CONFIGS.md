# Pragma — ready-made setups

Three tested `llama.cpp` configurations to copy-paste, with the matching
`.env` values for Pragma. Pick the one closest to your hardware.

All three expose the same OpenAI-compatible API on port `11434`, so the
only thing Pragma sees is the model name and context size.

> [!IMPORTANT]
> **`-np 2` is mandatory** in every setup. It enables two parallel slots
> on the llama.cpp server: one for your foreground task, one for the
> background consolidation worker (`session_reflect`) that learns from
> each completed task. With `-np 1` Pragma still works but the UI stays
> blocked on "Consolidating learnings…" while the worker runs serially
> behind every user message.

---

## 🐦 Starter — 4 GB VRAM, partial GPU offload  (RECOMMENDED for first-time users)

Model: **Qwen 3.5 9B** dense, `Q4_K_M` (~5.5 GB). Roughly half the layers
go on GPU, the rest on CPU. Around **10 tok/s** on an RTX 3050 Ti Laptop
(4 GB VRAM). Slower than the 4B but actually completes multi-step
debugging / refactor tasks without spiraling.

This is the sweet spot if you want to **try Pragma and have it work**
without buying a workstation GPU.

### `llama-server` (Windows batch)

```bat
@echo off
set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\x64;%PATH%
cd C:\Users\io\llama.cpp
llama-server.exe ^
  -hf bartowski/Qwen_Qwen3.5-9B-GGUF ^
  -hff Qwen_Qwen3.5-9B-Q4_K_M.gguf ^
  -ngl 20 ^
  -np 2 ^
  -c 32768 ^
  -ctk q8_0 ^
  -ctv q8_0 ^
  --flash-attn on ^
  -t 8 ^
  --no-mmap ^
  --jinja ^
  --host 127.0.0.1 ^
  --port 11434
```

Tuning knobs:
- `-ngl 20` — number of layers placed on GPU (~half of the 9B's layers). On 4 GB VRAM start at 20; if VRAM overflows drop to 18; if you have headroom go up to 24.
- `-c 32768` — max supported by Qwen 3.5 9B.
- `-ctk q8_0 -ctv q8_0` — 8-bit KV cache (better quality than q4_0; you can afford it because the model itself is partially on CPU).
- `-np 2` — see banner above.
- `-t 8` — physical core count.

### Matching `.env`

```env
LLM_PROVIDER=openai
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=
DEFAULT_MODEL=Qwen_Qwen3.5-9B-Q4_K_M

CODING_PROVIDER=openai
CODING_BASE_URL=http://127.0.0.1:11434/v1
CODING_MODEL=Qwen_Qwen3.5-9B-Q4_K_M

CONTEXT_WINDOW=32768
MAX_TOKENS=8192
CODING_MAX_TOKENS=8192
```

---

## 🐉 Reference — 12 GB VRAM workstation  (daily driver)

The setup used to develop Pragma. Model: **Qwen 3.6 35B A3B** (MoE) with
full **128k context**. Larger model = better tool use, longer reasoning,
robust JSON compliance. Needs lots of host RAM because most MoE experts
live on CPU.

### `llama-server`

```bash
llama-server \
    -hf bartowski/Qwen_Qwen3.6-35B-A3B-GGUF \
    -hff Qwen_Qwen3.6-35B-A3B-Q5_K_M.gguf \
    --mmproj /path/to/qwen36-35b-a3b-mmproj-f16.gguf \
    --port 11434 \
    -ngl 999 \
    -ncmoe 30 \
    -c 131072 \
    -np 2 \
    -ctk f16 \
    -ctv f16 \
    --flash-attn on \
    -t 16 \
    --no-mmap \
    --jinja \
    --host 127.0.0.1
```

Tuning knobs:
- `-c 131072` — full 128k context window.
- `-ncmoe 30` — keeps 30 MoE expert layers on CPU/RAM. Trades GPU speed for VRAM headroom: more layers offloaded means we can afford an f16 KV cache. Drop entirely if you have ≥ 24 GB VRAM.
- `-ctk f16 -ctv f16` — full-precision KV cache. Slightly better quality than q4_0 on long-context multi-turn reasoning. Affordable because the heavier MoE offload (`-ncmoe 30`) frees the VRAM the f16 cache needs. If you hit OOM at fill, fall back to `q4_0` for both.
- `-np 2` — see banner above.
- `--jinja` — required for Qwen3's chat template.

### Matching `.env`

```env
LLM_PROVIDER=openai
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=
DEFAULT_MODEL=Qwen_Qwen3.6-35B-A3B-Q5_K_M

CODING_PROVIDER=openai
CODING_BASE_URL=http://127.0.0.1:11434/v1
CODING_MODEL=Qwen_Qwen3.6-35B-A3B-Q5_K_M

CONTEXT_WINDOW=131072
MAX_TOKENS=32768
CODING_MAX_TOKENS=32768
```

### Reference hardware

| Component  | Tested on                                            |
| ---------- | ---------------------------------------------------- |
| GPU VRAM   | NVIDIA RTX A2000 12 GB                               |
| System RAM | 128 GB                                               |
| CPU        | Intel Xeon Silver 4314 (32 cores, `-t 16` threads)   |

- 128 GB RAM is what makes `-ncmoe 30` viable: 30 MoE expert layers stream from system RAM, leaving GPU VRAM for the active experts and the f16 KV cache.
- With more VRAM, drop `-ncmoe` (and consider keeping the KV cache at `f16`) for a substantial speedup.

---

## ⚡ Ultra-light — 4 GB VRAM, maximum speed  (advanced, expect rough edges)

Model: **Qwen 3 4B** `Q5_K_M`, **all on GPU**. Around **25–35 tok/s** on
an RTX 3050 Ti Laptop. Fast, but small enough that on multi-step
debugging it sometimes loops — Pragma's action-loop watchdog mitigates
this but doesn't eliminate it.

Pick this only if you've already used the Starter tier and want
maximum throughput, knowing that the model itself will occasionally
need to be steered back on track.

### `llama-server` (Windows batch)

```bat
@echo off
set PATH=C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\x64;%PATH%
cd C:\Users\io\llama.cpp
llama-server.exe ^
  -hf bartowski/Qwen_Qwen3-4B-GGUF ^
  -hff Qwen_Qwen3-4B-Q5_K_M.gguf ^
  -ngl 999 ^
  -c 32768 ^
  -np 2 ^
  -ctk q4_0 ^
  -ctv q4_0 ^
  --flash-attn on ^
  -t 8 ^
  --no-mmap ^
  --jinja ^
  --host 127.0.0.1 ^
  --port 11434
```

### Matching `.env`

```env
LLM_PROVIDER=openai
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_API_KEY=
DEFAULT_MODEL=Qwen_Qwen3-4B-Q5_K_M

CODING_PROVIDER=openai
CODING_BASE_URL=http://127.0.0.1:11434/v1
CODING_MODEL=Qwen_Qwen3-4B-Q5_K_M

CONTEXT_WINDOW=32768
MAX_TOKENS=8192
CODING_MAX_TOKENS=8192
```

---

## Tuning rules of thumb

Patterns that apply to every tier:

1. **`CONTEXT_WINDOW` must match `-c` on the server.** If they disagree, Pragma's memory compression triggers at the wrong time.
2. **`MAX_TOKENS` ≈ 25 % of `CONTEXT_WINDOW`** is a safe default. Higher = more room for `write_file` content; lower = more room for conversation history.
3. **`-np 2` is mandatory** for the asynchronous consolidation worker to run in parallel with foreground tasks. Without it the UI stays blocked.
    Heavy users of Settings → Knowledge → 📝 *Summarize* on a busy thread can bump to `-np 3` to avoid the summary waiting behind an in-flight reflection. Costs a bit more VRAM, not required.
4. **`Q5_K_M`** is the size/quality sweet spot. Try `Q4_K_M` for ~20 % less VRAM at a small quality loss. Avoid Q4 quantization on models < 7B — accuracy drops sharply.
5. **KV cache precision** is a quality/VRAM trade-off. `f16` is full precision (best quality), `q8_0` is the usual sweet spot, `q4_0` is the most aggressive. The Reference tier above runs `f16` thanks to heavy MoE offload (`-ncmoe 30`); if you OOM at context fill, drop both `-ctk` and `-ctv` one step down (`q8_0` first, then `q4_0`).
6. **Two-model split** is optional. Point `CODING_*` to a second `llama-server` instance running a coding specialist (e.g. `qwen2.5-coder-7b`, `deepseek-coder-v2`) to route the `code` skill there. Leave the values identical to use one model for everything.

---

## Don't see your hardware here?

Paste the meta-prompt from the [main README](./README.md#-dont-know-llamacpp) into any LLM with your specs filled in — it produces a tailored `llama-server` invocation plus the matching `.env`.
