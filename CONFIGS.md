# Pragma — ready-made setups

Two tested `llama.cpp` configurations to copy-paste, with the matching
`.env` values for Pragma. Pick the one closest to your hardware.

Both setups expose the same OpenAI-compatible API on port `11434`, so
the only difference Pragma sees is the model name and context size.

---

## 🪶 Small — 4 GB VRAM laptop

For a portable setup that runs anywhere. Model: **Qwen 3 4B** dense.
Limited context (32k), but fast and responsive on a modest GPU.

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

Linux/macOS equivalent: same flags, single line with `\` for line continuation,
and adjust the CUDA path if needed (or drop it entirely for ROCm/Vulkan/CPU).

What each flag does:
- `-c 32768` — the maximum supported by Qwen3 4B.
- `-np 2` — two parallel slots: the consolidation worker (`session_reflect`) can run while your next task starts.
- `-ctk q4_0 -ctv q4_0` — 4-bit KV cache, fits the tight VRAM budget.
- `-ngl 999` — push everything to GPU.
- `--flash-attn on`, `--jinja` — necessary for Qwen-family chat templates and modern attention.
- `-t 8` — set to your CPU's physical core count.

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

Notes:
- `CONTEXT_WINDOW=32768` matches `-c 32768` on the server.
- `MAX_TOKENS=8192` is the output cap PER STEP of the ReAct loop. Keeping it ≤ 25% of the context window leaves room for the conversation history.
- For very long tasks Pragma will compress the message history automatically.

---

## 🐉 Reference — 12 GB VRAM workstation

The setup used to develop Pragma. Model: **Qwen 3.6 35B A3B** (MoE) with
full 128k context. Larger model = better tool use and longer reasoning.
Heavier RAM requirement because most MoE experts live on CPU.

### `llama-server`

```bash
llama-server \
    -hf bartowski/Qwen_Qwen3.6-35B-A3B-GGUF \
    -hff Qwen_Qwen3.6-35B-A3B-Q5_K_M.gguf \
    --mmproj /path/to/qwen36-35b-a3b-mmproj-f16.gguf \
    --port 11434 \
    -ngl 999 \
    -ncmoe 27 \
    -c 131072 \
    -np 2 \
    -ctk q4_0 \
    -ctv q4_0 \
    --flash-attn on \
    -t 16 \
    --no-mmap \
    --jinja \
    --host 127.0.0.1
```

What each flag does:
- `-c 131072` — full 128k context window.
- `-ncmoe 27` — keeps 27 MoE expert layers on CPU/RAM so the rest fits in 12 GB VRAM. Drop this flag if you have ≥ 24 GB VRAM.
- `-ctk q4_0 -ctv q4_0` — 4-bit KV cache. Halves VRAM with no measurable quality loss.
- `-np 2` — two parallel slots (foreground task + background reflection).
- `-ngl 999` — push every non-offloaded layer to GPU.
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

- 128 GB RAM is what makes `-ncmoe 27` viable.
- With more VRAM, drop `-ncmoe` for a substantial speedup.
- CPU-only is possible with smaller / more quantized models — use the 4 GB recipe above as a starting point.

---

## Tuning rules of thumb

A few patterns that apply to either recipe:

1. **`CONTEXT_WINDOW` must match `-c` on the server.** If they disagree, Pragma's memory compression triggers at the wrong time.
2. **`MAX_TOKENS` should sit at roughly 25 % of `CONTEXT_WINDOW`.** Higher = the model has more headroom for long files in `write_file`; lower = more room for conversation history. The defaults above are conservative.
3. **`-np 2`** is what makes the asynchronous reflection genuinely parallel. With `-np 1` Pragma still works but the reflection runs after the next foreground task instead of beside it.
4. **`Q5_K_M`** is the sweet spot for size vs quality. Try `Q4_K_M` for ~20 % less VRAM at a small quality loss, or `Q6_K`/`Q8_0` if you have headroom.
5. **Two-model split (optional).** Set `CODING_MODEL` / `CODING_BASE_URL` to a second `llama-server` instance running a coding specialist (e.g. `qwen2.5-coder-7b` or `deepseek-coder-v2`) to route the `code` skill to it. Leave them identical to use a single model everywhere.

---

## Don't see your hardware here?

Paste the meta-prompt from the [main README](./README.md#-dont-know-llamacpp) into any LLM with your specs filled in — it produces a tailored `llama-server` invocation plus the matching `.env`.
