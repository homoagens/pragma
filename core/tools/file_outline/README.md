# file_outline

A file's map without its content: size, line count, top-level symbols and headings with their line numbers, and its last lines. Run it before reading a file you have not seen: it costs a fraction of the context and tells you which part to read, or where to anchor a change.

---

## Parameters

- `path` (str): File to summarize.
- `tail_lines` (int, optional, default 5): Number of trailing lines to include verbatim.
- `encoding` (str, optional, default "utf-8"): File encoding.

## Returns

A multi-line summary with:

- File size in bytes, total line count, extension.
- Top-level symbols with line numbers, depending on extension:
    - `.py` → classes, def, async def, top-level CONSTANTS
    - `.js` / `.ts` / `.jsx` / `.tsx` / `.mjs` / `.cjs` → exported/internal functions, classes, const/let/var
    - `.md` → heading tree
    - `.json` → top-level keys with types and previews
- The last `tail_lines` lines verbatim (so you can see how the file ends).

## Notes

- Pure regex + plain file read. Cannot hit the LLM token limit.
- Use this BEFORE reading any file you don't already know.
- Lets you decide whether to read it whole, read a slice (`sed -n '40,120p'`), or skip
  straight to `insert_after`/`replace_in_file` with the anchor of interest.

## Examples

```json
{ "action": "file_outline", "args": { "path": "/home/me/proj/app.py" } }
{ "action": "file_outline", "args": { "path": "/home/me/proj/sim.js", "tail_lines": 10 } }
```

## When to prefer this

- Any file > 100 lines: outline first, then targeted read.
- Unknown codebase: outline a few files to map the project quickly.
- Before `insert_after` / `insert_before`: pick the right anchor by looking at the symbol table.
