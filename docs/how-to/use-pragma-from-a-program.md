# Use Pragma from another program

*For the terminal on Linux and macOS, which serve the project; the program can run anywhere that reaches it. [Where each interface stands](../explanation/interfaces.md).*

Pragma can be the model of another program. The program talks to it exactly
as it would talk to any OpenAI-compatible model, and behind that one address
it gets a whole agent: what the project remembers, recalled before each turn;
the tools, working in the project's folder; and a memory that keeps what was
said once the conversation is over.

Nothing in the program has to know it is Pragma. Pragma, for its part, keeps
the turn in its own hands: which model it thinks with is chosen in
`/configure`, and that can be a stronger one than the program would have used.

## In two minutes

1. In Pragma, on the home screen: `/serve`, then `add`, then the project.
   [Serve a project](serve-a-project.md) has the page in full.
2. The project's page shows three lines. Give them to the program wherever it
   takes the settings of its model:

   ```text
   LLM_BASE_URL=http://127.0.0.1:8300/v1
   LLM_MODEL=pragma:lezioni
   LLM_API_KEY=pgk_…
   ```

3. **Raise the program's timeout to ten minutes or so.** A turn of Pragma can
   use several tools before it answers, and a program that gives a model two
   minutes will cut it off.

That is all for a program that already lets you choose its model: a chat
panel, a presentation tool, an editor plugin. The names of the three settings
are the program's own; what goes in them is the address, the key and — when
it insists on one — the model's name. The port alone chooses the project.

## In your own code

The OpenAI chat API, nothing more: `GET /v1/models` and
`POST /v1/chat/completions`, with or without `stream`.

**curl**, for a first look:

```bash
curl http://127.0.0.1:8300/v1/chat/completions \
  -H "Authorization: Bearer pgk_..." -H "Content-Type: application/json" \
  -d '{"model": "pragma", "messages": [{"role": "user", "content": "Hello"}]}'
```

**Python**, standard library only, streaming what Pragma does while it works:

```python
import json
import urllib.request

BASE = "http://127.0.0.1:8300/v1"      # what /serve shows
KEY = "pgk_..."                         # what /serve shows


def ask(messages):
    """Stream one turn: what Pragma is doing, then its answer."""
    req = urllib.request.Request(
        f"{BASE}/chat/completions",
        data=json.dumps({"model": "pragma", "messages": messages, "stream": True}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    answer = ""
    with urllib.request.urlopen(req, timeout=600) as resp:
        for line in resp:
            line = line.decode().strip()
            if not line.startswith("data: {"):
                continue                        # keep-alives, and the final [DONE]
            delta = json.loads(line[6:])["choices"][0]["delta"]
            if delta.get("reasoning_content"):
                print(delta["reasoning_content"], end="", flush=True)
            answer += delta.get("content") or ""
    return answer


messages = [{"role": "system", "content": "Slide 3 of 12: photosynthesis"},
            {"role": "user", "content": "Explain this slide in two sentences."}]
reply = ask(messages)
print("\n---\n" + reply)

# The next turn sends the whole conversation, as with any model.
messages += [{"role": "assistant", "content": reply},
             {"role": "user", "content": "And a question I could ask the class?"}]
print("\n---\n" + ask(messages))
```

**JavaScript**, in Node 18 or later, or a server of your own:

```js
const BASE = "http://127.0.0.1:8300/v1";   // what /serve shows
const KEY = "pgk_...";                      // what /serve shows

// Stream one turn: onReasoning gets what Pragma is doing, the answer is returned.
async function ask(messages, onReasoning = (t) => process.stdout.write(t)) {
  const resp = await fetch(`${BASE}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${KEY}` },
    body: JSON.stringify({ model: "pragma", messages, stream: true }),
    signal: AbortSignal.timeout(600_000),
  });
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  const decoder = new TextDecoder();
  let answer = "", rest = "";
  for await (const bytes of resp.body) {
    rest += decoder.decode(bytes, { stream: true });
    const lines = rest.split("\n");
    rest = lines.pop();
    for (const line of lines) {
      if (!line.startsWith("data: {")) continue;   // keep-alives, and the final [DONE]
      const delta = JSON.parse(line.slice(6)).choices[0].delta;
      if (delta.reasoning_content) onReasoning(delta.reasoning_content);
      answer += delta.content ?? "";
    }
  }
  return answer;
}

const messages = [
  { role: "system", content: "Slide 3 of 12: photosynthesis" },
  { role: "user", content: "Explain this slide in two sentences." },
];
console.log("\n---\n" + (await ask(messages)));
```

Any OpenAI client library works the same way: give it the address as its
base URL and the key as its API key. Keep the key on your server: a page in
a browser should talk to your server, and your server to Pragma.

## What Pragma makes of a request

- **The last message from the person is the turn.** Only their words are
  remembered.
- **System messages are context, for that turn only.** Put there what the
  person is looking at — the slide, the document, the selection. The agent
  reads it; the memory never keeps it. Long context is cut to fit the
  model's window, and Pragma says so in the reasoning.
- **Send the whole conversation every time**, as to any model. While the
  person's earlier messages are the ones Pragma has had, it is the same
  conversation. A request that starts over — a "clear" button — starts a new
  one, and the one before is handed to the memory, as closing a project does
  in the terminal. So is one nobody writes to for 20 minutes.
- **`content` is the answer**, and arrives when the turn is done.
  **`reasoning_content`** streams while it runs: what was recalled, the
  model's reasoning, each tool and how it came out. Show it in a "thinking"
  panel, or ignore it. Without `stream`, both come back in one response.
- **Nobody can answer in the middle of a turn.** When the agent needs
  something, its answer is the question; the person's reply is the next
  request. A command that cannot be undone is not run unless the project
  allows it in `/settings`.
- **`model`, `temperature`, `max_tokens` and the rest are not used.** The
  model, its sampling and its reasoning are the endpoint's in `/configure`.

## When it answers with an error

| Code | Why | What to do |
|---|---|---|
| `401` | The key is not this project's. | The key `/serve` shows; a new one there replaces the old. |
| `409` | The conversation is still answering the previous message. | One request at a time per project: wait for the answer. |
| `502` | Pragma cannot reach its own model. | Look at the endpoint in `/configure`. |
| `400` | The request has no message from the person last. | End the list of messages with a `user` one. |
| no answer | The service is not running. | `/serve`: its line says why, and `log` shows what it did. |

## Things worth knowing

- **One program at a time per project.** Two programs on one project would
  start each other's conversations over. Serve a second project instead.
- **Without memory**, a served project is the agent alone, quicker, and
  nothing a program says reaches the project's memory: the `memory` row of
  its page in `/serve`.
- **Over the network**, set the address to `0.0.0.0` in `/serve`; every
  request must then carry the key. From another machine the address is this
  machine's, not `127.0.0.1`.
- **Pragma in WSL, the program on Windows**: `127.0.0.1` reaches it from
  Windows as it is.
