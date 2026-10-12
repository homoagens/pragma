# vision_interpret

Send a local image to a vision-capable LLM and return its textual interpretation.

---

## Parameters

- `image_path` (str): Local path to the image file (PNG, JPG, WEBP, or GIF).
- `question` (str): What to interpret or extract from the image.
- `model` (str, optional, default ""): Vision-capable model; defaults to `config.DEFAULT_MODEL`.
- `detail` (str, optional, default "auto"): Token detail level: `"low"`, `"high"`, or `"auto"`.

## Returns

LLM response text or `"ERROR: ..."`.

## Notes

- The image is base64-encoded and sent as an OpenAI vision-style `image_url` payload.
- Returns a descriptive error if the backend does not support multimodal calls (HTTP 422).
- MIME type is inferred from the file extension; defaults to `image/png` if unknown.
