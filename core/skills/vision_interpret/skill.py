from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

import llm_client


def vision_interpret(image_path: str, question: str,
                     model: str = "", detail: str = "auto") -> str:
    """
    [G] Multimodal LLM call: image → textual interpretation.
    Distinct signature from llm_invoke because the payload differs (base64 image).

    image_path : local path of the image (PNG/JPG/WEBP/GIF)
    question   : what to interpret or extract from the image
    model      : vision-capable model (default config.DEFAULT_MODEL)
    detail     : "low" | "high" | "auto" (token detail level)
    """
    p = Path(image_path)
    if not p.exists():
        return f"ERROR: image not found — {image_path}"

    try:
        raw_bytes = p.read_bytes()
        b64       = base64.b64encode(raw_bytes).decode()
        mime      = mimetypes.guess_type(str(p))[0] or "image/png"
    except OSError as e:
        return f"ERROR reading image: {e}"

    # OpenAI vision-style payload
    content = [
        {
            "type": "image_url",
            "image_url": {
                "url":    f"data:{mime};base64,{b64}",
                "detail": detail,
            },
        },
        {"type": "text", "text": question},
    ]

    kwargs: dict[str, Any] = {}
    if model:
        kwargs["model"] = model

    try:
        return llm_client.call_llm(
            messages=[{"role": "user", "content": content}],
            **kwargs,
        )
    except Exception as e:
        msg = str(e)
        if "422" in msg:
            return (
                "ERROR: the backend does not support multimodal calls. "
                "Use a vision-capable model (e.g. gpt-4o, claude-3) "
                f"and verify that the endpoint accepts image_url payloads. [{msg}]"
            )
        return f"ERROR: LLM vision call failed — {e}"
