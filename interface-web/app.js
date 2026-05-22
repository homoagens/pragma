// Pragma — frontend

// ── Quit ───────────────────────────────────────────────────────────────────

async function quitApp() {
  if (!confirm("Shut down the Pragma server?")) return;
  try { await fetch("/api/quit", { method: "POST" }); } catch (_) {}
  // Try to close the tab. Browsers only allow this on tabs that were
  // opened via window.open() from JS — i.e. almost never for a tab the
  // user typed in or that start.bat launched via `start http://...`.
  // We attempt it anyway because it's free, and fall back to a static
  // "Server stopped" page when the browser refuses.
  try { window.close(); } catch (_) {}
  // Some browsers silently ignore window.close() without throwing, so we
  // also replace the page content as a guaranteed fallback. The user can
  // close the tab manually if the browser refused.
  setTimeout(() => {
    document.body.innerHTML =
      '<div style="display:flex;flex-direction:column;align-items:center;'
      + 'justify-content:center;height:100vh;font-family:system-ui;color:#888;'
      + 'font-size:.9rem;gap:8px;">'
      + '<div>Server stopped.</div>'
      + '<div style="font-size:.75rem;color:#aaa">'
      + 'Your browser blocked auto-close — you can close this tab manually.'
      + '</div></div>';
  }, 100);
}

// ── Theme ──────────────────────────────────────────────────────────────────
// Single source of truth = localStorage. The IIFE applies the attribute before
// the page paints (no FOUC). DOMContentLoaded only updates icons and wires the
// toggle — it MUST NOT re-derive the theme, otherwise a missing attribute (rare
// race) would silently downgrade dark to light and overwrite localStorage.

function _resolveTheme() {
  const saved = localStorage.getItem("pragma-theme");
  if (saved === "dark" || saved === "light") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

(function initTheme() {
  document.documentElement.setAttribute("data-theme", _resolveTheme());
})();

function setTheme(theme) {
  if (theme !== "dark" && theme !== "light") return;  // refuse invalid values
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("pragma-theme", theme);
  const sun  = document.getElementById("theme-icon-sun");
  const moon = document.getElementById("theme-icon-moon");
  const tgl  = document.getElementById("theme-toggle");
  if (sun && moon) {
    sun.style.display  = theme === "dark" ? "block" : "none";
    moon.style.display = theme === "dark" ? "none"  : "block";
  }
  if (tgl) {
    tgl.title = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  // Re-apply the resolved theme — but use the SAME resolver, never trust
  // the DOM attribute. Idempotent and safe.
  setTheme(_resolveTheme());
  document.getElementById("theme-toggle")
    ?.addEventListener("click", () => {
      const next = _resolveTheme() === "dark" ? "light" : "dark";
      setTheme(next);
    });
});

// REST API:
//   GET    /api/config
//   GET    /api/threads
//   POST   /api/threads           { cwd?, title? }
//   GET    /api/threads/:id
//   PATCH  /api/threads/:id       { title?, cwd? }
//   DELETE /api/threads/:id
// WS:
//   in  : {type:"task"|"user_answer"|"set_cwd", ...}
//   out : {type:"thread_state"|"thread_created"|"thought"|"action"|"observation"|
//                "final"|"error"|"ask_user"|"done"|"stats"|"cwd_updated"}

const $messages    = document.getElementById("messages");
const $input       = document.getElementById("task-input");
const $sendBtn     = document.getElementById("send-btn");
const $stopBtn     = document.getElementById("stop-btn");
const $statusDot   = document.getElementById("status-dot");
const $statusLbl   = document.getElementById("status-label");
const $workdir     = document.getElementById("workdir");
const $workdirText = document.getElementById("workdir-text");
const $inputArea   = document.getElementById("input-area");
const $runStats    = document.getElementById("run-stats");
const $threadList  = document.getElementById("thread-list");

const WELCOME_HTML = `
  <div id="welcome">
    <img class="wlogo" src="/static/logo.png" alt="">
    <h2>Pragma</h2>
    <p>Select a conversation from the sidebar,<br>or click <strong>New conversation</strong> to choose a working directory and start.</p>
  </div>`;

let ws          = null;
let running     = false;
let isReadOnly  = false;
let answerMode  = false;
let thinkingEl  = null;
let streamingEl = null;
let thinkingStreamEl  = null;   // live preview while the model's <think> block streams
let thinkingStreamRaw = "";     // accumulated <think> text
let askUserEl   = null;

let defaultCwd     = "";
let threads        = [];         // [{id, title, cwd, updated_at, message_count}]
let activeId       = null;       // thread bound to the current WS
let currentCwd     = "";         // cwd of active thread
let llmConfig      = null;       // { provider, default_model, coding_model, coding_distinct, ... }
let maxStepsConfig = 15;         // synced from /api/config, editable via settings


// ── Markdown ───────────────────────────────────────────────────────────────

function renderMd(text) {
  if (!text) return "";
  let html;
  if (typeof marked === "undefined")           html = escHtml(text);
  else if (typeof marked.parse === "function") html = marked.parse(text);
  else if (typeof marked === "function")       html = marked(text);
  else                                          html = escHtml(text);
  return _sanitizeRenderedHtml(html);
}

// Models often include <style> / <script> blocks in their conclusion text
// when they're showing generated CSS/JS to the user. marked.parse() passes
// raw HTML through verbatim, so those blocks get injected into the page DOM
// and apply GLOBALLY — typically overriding the active theme. We strip them
// here. Other potentially scope-leaking or unsafe tags get the same treatment.
const _DANGEROUS_TAGS = ["style", "script", "link", "iframe", "object", "embed", "meta", "base"];

function _sanitizeRenderedHtml(html) {
  if (!html || typeof DOMParser === "undefined") return html;
  // Use a detached document so the dangerous tags don't run / load as we parse.
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");
  for (const tag of _DANGEROUS_TAGS) {
    doc.body.querySelectorAll(tag).forEach(el => el.remove());
  }
  return doc.body.innerHTML;
}


// ── REST helpers ───────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = "";
    try { detail = (await r.json()).detail || ""; } catch (_) {}
    throw new Error(detail || `${method} ${path} → ${r.status}`);
  }
  return r.json();
}


// ── Status / workdir ───────────────────────────────────────────────────────

function setStatus(state, label) {
  $statusDot.className = state;
  if ($statusLbl) $statusLbl.textContent = label;
}

function setWorkdir(cwd) {
  currentCwd = cwd || "";
  $workdirText.textContent = cwd || "—";
  $workdir.title = cwd ? `Working directory: ${cwd}\nClick to change.` : "Click to set a working directory";
}


// ── Sidebar / thread list ──────────────────────────────────────────────────

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60)    return "just now";
  if (diff < 3600)  return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return d.toLocaleDateString();
}

function renderSidebar() {
  $threadList.innerHTML = "";
  if (!threads.length) return;

  const label = document.createElement("div");
  label.className = "thread-section-label";
  label.textContent = "Conversations";
  $threadList.appendChild(label);

  threads.forEach(t => {
    const item = document.createElement("div");
    item.className = "thread-item";
    if (t.id === activeId) item.classList.add("active");

    const title = document.createElement("div");
    title.className = "thread-title";
    title.textContent = t.title || "Untitled";

    const meta = document.createElement("div");
    meta.className = "thread-meta";
    meta.textContent = fmtDate(t.updated_at || t.created_at);

    const del = document.createElement("button");
    del.className = "thread-delete";
    del.title = "Delete conversation";
    del.innerHTML = `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor"
         stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 4h10M6 4V2.5h4V4M5 4v9a1 1 0 0 0 1 1h4a1 1 0 0 0 1-1V4M7 7v4M9 7v4"/>
    </svg>`;
    del.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteThread(t.id);
    });

    item.appendChild(title);
    item.appendChild(meta);
    item.appendChild(del);
    item.addEventListener("click", () => openThread(t.id));
    $threadList.appendChild(item);
  });
}

async function reloadThreads() {
  try {
    const { threads: list } = await api("GET", "/api/threads");
    threads = list || [];
    renderSidebar();
  } catch (e) {
    console.error("reloadThreads failed:", e);
  }
}

async function deleteThread(id) {
  if (running && id === activeId) {
    alert("A task is running in this conversation — wait for it to finish.");
    return;
  }
  if (!confirm("Delete this conversation? This cannot be undone.")) return;
  try {
    await api("DELETE", `/api/threads/${id}`);
    if (id === activeId) {
      activeId = null;
      closeWS();
      $messages.innerHTML = WELCOME_HTML;
      setWorkdir(defaultCwd);
    }
    await reloadThreads();
    // After deletion, just show the welcome screen — let the user choose.
    if (!activeId) {
      $messages.innerHTML = WELCOME_HTML;
    }
  } catch (e) {
    alert(`Delete failed: ${e.message}`);
  }
}


// ── Thread open / new ──────────────────────────────────────────────────────

async function openThread(id) {
  if (id === activeId) return;
  if (running) {
    alert("A task is running — wait for it to finish before switching threads.");
    return;
  }
  try {
    const data = await api("GET", `/api/threads/${id}`);
    activeId = id;
    setWorkdir(data.cwd || defaultCwd);
    reconstructMessages(data.messages || []);
    connectWS(id);
    renderSidebar();
  } catch (e) {
    alert(`Open failed: ${e.message}`);
  }
}

async function newThread(cwdOverride) {
  if (running) {
    alert("A task is running — wait for it to finish.");
    return;
  }
  try {
    // If no cwd was given, open the native OS folder picker
    let cwd = cwdOverride || "";
    if (!cwd) {
      try {
        const res = await api("POST", "/api/browse");
        cwd = res.path || "";
      } catch (_) {
        // browse failed (e.g. no tkinter) — fall back to server default
        cwd = "";
      }
    }
    const body = cwd ? { cwd } : {};
    const data = await api("POST", "/api/threads", body);
    activeId = data.id;
    setWorkdir(data.cwd || defaultCwd);
    $messages.innerHTML = WELCOME_HTML;
    await reloadThreads();
    connectWS(activeId);
  } catch (e) {
    alert(`New conversation failed: ${e.message}`);
  }
}

document.getElementById("new-thread-btn")
  .addEventListener("click", () => newThread());


// ── Message reconstruction ─────────────────────────────────────────────────

function reconstructMessages(msgs) {
  $messages.innerHTML = "";
  if (!msgs.length) {
    $messages.innerHTML = WELCOME_HTML;
    return;
  }
  for (const m of msgs) {
    switch (m.type) {
      case "user":        appendUserMessage(m.content); break;
      case "thought":     appendCollapsible("thought", "Thought", m.content, m.step); break;
      case "action":      appendCollapsible("action", m.name || "Action", formatArgs(m.args), m.step, m.name); break;
      case "observation": appendCollapsible("observation", "Observation", m.content, m.step); break;
      case "final":       appendFinal(m.content); break;
      case "error":       appendCollapsible("error", "Error", m.content, m.step); break;
      case "reflection_queued": /* historical: superseded by final reflection event */ break;
      case "reflection_start":  /* historical: superseded by final reflection event */ break;
      case "reflection": {
        // History restore: skip the queued/spinner phases and render only the
        // final result with the (persisted) entries available for expansion.
        // finalizeReflectionIndicator detaches the element so the next
        // reflection in the thread gets its own block.
        showReflectionIndicator("", false);
        finalizeReflectionIndicator(m.content || "", m.added || []);
        break;
      }
      case "knowledge_cleared":
        appendKnowledgeClearedMarker(m.removed, m.ts);
        break;
      case "ask_user": {
        const el = appendAskUserInert(m.question, m.hint, m.mode);
        if (m.answer !== undefined) {
          const body = el.querySelector(".ask-body");
          const a = document.createElement("div");
          a.className = "ask-answered";
          a.textContent = `→ ${m.answer}`;
          body.appendChild(a);
        }
        break;
      }
      case "stats": /* silent in replay */ break;
    }
  }
  scrollBottom();
}


// ── Stats tracking ─────────────────────────────────────────────────────────

let startTime     = null;
let timerInterval = null;
let pendingStats  = null;
let liveStep      = 0;
let liveChars     = 0;

function fmtNum(n) {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

function fmtSecs(ms) {
  const s = Math.floor(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`;
}

function updateRunStats() {
  if (!startTime || !$runStats) return;
  const parts = [`⏱ ${fmtSecs(Date.now() - startTime)}`];
  if (liveStep  > 0) parts.push(`step ${liveStep}/${maxStepsConfig}`);
  if (liveChars > 0) parts.push(`~${fmtNum(Math.round(liveChars / 4))} tok`);
  $runStats.textContent = parts.join(" · ");
}

function showFinalStats() {
  if (!$runStats) return;
  const elapsed = startTime ? fmtSecs(Date.now() - startTime) : null;
  const steps   = pendingStats?.steps  ?? liveStep;
  const tokens  = pendingStats?.tokens ?? Math.round(liveChars / 4);
  const parts   = [];
  if (elapsed)    parts.push(elapsed);
  if (steps  > 0) parts.push(`${steps} step`);
  if (tokens > 0) parts.push(`~${fmtNum(tokens)} tok`);
  $runStats.className = "done";
  $runStats.textContent = parts.length ? `✓ ${parts.join(" · ")}` : "✓ Done";
}

function startNewTask() {
  pendingStats = null;
  liveStep     = 0;
  liveChars    = 0;
  startTime    = Date.now();
  clearInterval(timerInterval);
  timerInterval = setInterval(updateRunStats, 500);
  if ($runStats) { $runStats.className = "running"; }
  activateBadge("default");  // highlight the default-role model on start
}


// ── WebSocket ──────────────────────────────────────────────────────────────

function closeWS() {
  if (ws) {
    ws.onopen = ws.onclose = ws.onerror = ws.onmessage = null;
    try { ws.close(); } catch (_) {}
    ws = null;
  }
}

function connectWS(threadId) {
  closeWS();
  const url = `ws://${location.host}/ws?thread_id=${encodeURIComponent(threadId)}`;
  ws = new WebSocket(url);
  ws.onopen    = () => setStatus("connected", "Connected");
  ws.onclose   = () => setStatus("disconnected", "Disconnected");
  ws.onerror   = () => setStatus("disconnected", "Error");
  ws.onmessage = (e) => {
    try { handleEvent(JSON.parse(e.data)); }
    catch (_) {}
  };
}

function sendWS(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}


// ── Event handler ──────────────────────────────────────────────────────────

function handleEvent(ev) {
  switch (ev.type) {

    case "thread_state":
      if (ev.thread) {
        activeId = ev.thread.id;
        setWorkdir(ev.thread.cwd || defaultCwd);
      }
      break;

    case "thread_created":
      activeId = ev.thread.id;
      setWorkdir(ev.thread.cwd || defaultCwd);
      reloadThreads();
      break;

    case "cwd_updated":
      setWorkdir(ev.cwd);
      reloadThreads();
      break;

    case "thinking":
      removeThinking();
      if (!thinkingStreamEl) {
        hideWelcome();
        thinkingStreamEl = document.createElement("div");
        thinkingStreamEl.className = "block-streaming block-streaming-thinking";
        thinkingStreamRaw = "";
        $messages.appendChild(thinkingStreamEl);
      }
      thinkingStreamRaw += ev.content;
      // Live preview: show the TAIL of the <think> stream so the user sees
      // motion (text scrolls like a terminal). Earlier we showed a fixed
      // head and the visible text froze once the cap was hit, making long
      // thinking look stuck. A counter beside it confirms the stream is alive.
      {
        const TAIL = 1200;
        const total = thinkingStreamRaw.length;
        const tail = total > TAIL
          ? "… " + thinkingStreamRaw.slice(-TAIL)
          : thinkingStreamRaw;
        thinkingStreamEl.textContent = tail;
        thinkingStreamEl.dataset.chars = String(total);
      }
      scrollBottom();
      break;

    case "token":
      removeThinking();
      finalizeThinking();
      if (!streamingEl) {
        hideWelcome();
        streamingEl = document.createElement("div");
        streamingEl.className = "block-streaming";
        streamingEl.dataset.raw = "";
        $messages.appendChild(streamingEl);
      }
      streamingEl.dataset.raw += ev.content;
      streamingEl.textContent = extractStreamingPreview(streamingEl.dataset.raw);
      streamingEl.dataset.chars = String(streamingEl.dataset.raw.length);
      scrollBottom();
      break;

    case "thought":
      if (ev.step != null) liveStep = ev.step;
      liveChars += (ev.content || "").length;
      removeStreaming();
      removeThinking();
      finalizeThinking();
      activateBadge("default");
      appendCollapsible("thought", "Thought", ev.content, ev.step);
      // Do not show a spinner here — the action event will show "Executing…"
      // Showing "Thinking…" at this point is misleading if a tool is about to run.
      break;

    case "action":
      liveChars += (ev.content || "").length + JSON.stringify(ev.args || {}).length;
      removeThinking();
      activateBadge(ev.name === "code" ? "coding" : "default");
      appendCollapsible("action", ev.name || "Action", formatArgs(ev.args), ev.step, ev.name);
      showThinking("Executing…");
      break;

    case "observation":
      if (ev.step != null) liveStep = ev.step;
      liveChars += (ev.content || "").length;
      removeThinking();
      activateBadge("default");
      appendCollapsible("observation", "Observation", ev.content, ev.step);
      showThinking();
      break;

    case "final":
      liveChars += (ev.content || "").length;
      removeStreaming();
      removeThinking();
      finalizeThinking();
      appendFinal(ev.content);
      break;

    case "error":
      removeStreaming();
      removeThinking();
      finalizeThinking();
      appendCollapsible("error", "Error", ev.content, ev.step);
      break;

    case "ask_user":
      removeThinking();
      appendAskUser(ev.question, ev.hint, ev.mode);
      break;

    case "stats":
      pendingStats = ev;
      break;

    case "reflection_queued":
      // Reflection has been pushed to the background queue but the worker
      // hasn't picked it up yet (something is running ahead of it).
      // Emit a static indicator so the user sees the work is acknowledged.
      showReflectionIndicator("Consolidating learnings… (queued)", false);
      break;

    case "reflection_start":
      // The background worker picked this reflection up and started the
      // LLM call. Swap the indicator to a spinning state.
      showReflectionIndicator("Consolidating learnings…", true);
      break;

    case "reflection":
      // session_reflect finished. Replace the spinner with the final result
      // and leave it permanently visible in the conversation. `ev.added`
      // contains the specific entries written to the global store (one of
      // {lessons, patterns, user_prefs, mistakes}); clicking the indicator
      // expands to show them.
      finalizeReflectionIndicator(ev.content || "(no result)", ev.added || []);
      break;

    case "knowledge_cleared":
      // The user wiped the global learnings store (from Settings →
      // Knowledge). Drop a permanent visual marker in this conversation
      // so it's clear that everything Pragma had learned up to here is
      // gone — anything the model does next can no longer rely on prior
      // consolidations.
      appendKnowledgeClearedMarker(ev.removed, ev.ts);
      break;

    case "stopped":
      removeThinking();
      finalizeThinking();
      clearInterval(timerInterval); timerInterval = null;
      if ($runStats) { $runStats.className = ""; $runStats.textContent = "↓ Stopped"; }
      resetBadges();
      setStatus("connected", "Connected");
      setRunning(false);
      if ($stopBtn) { $stopBtn.disabled = false; }
      break;

    case "done":
      removeThinking();
      finalizeThinking();
      clearInterval(timerInterval); timerInterval = null;
      showFinalStats();
      resetBadges();
      setStatus("connected", "Connected");
      setRunning(false);
      reloadThreads();  // updates title / updated_at
      break;
  }
}


// ── DOM builders ───────────────────────────────────────────────────────────

function hideWelcome() { document.getElementById("welcome")?.remove(); }

/**
 * Extract an unescaped JSON string value starting right after the opening ".
 * Returns the decoded text (partial if the closing " hasn't arrived yet).
 */
function _jsonStrValue(raw, afterOpenQuote) {
  const content = raw.slice(afterOpenQuote);
  let result = "";
  for (let i = 0; i < content.length; i++) {
    if (content[i] === "\\") {
      i++;
      if (i < content.length) {
        if      (content[i] === "n") result += "\n";
        else if (content[i] === "t") result += "\t";
        else                          result += content[i];
      }
    } else if (content[i] === '"') {
      break;
    } else {
      result += content[i];
    }
  }
  return result;
}

/**
 * Given a buffer of streaming tokens from the model (raw JSON like
 * {"thought":"...","action":"...","args":{...}}), build a human-readable
 * preview extracting thought, action name, and args as they arrive.
 * If the buffer is not JSON (backend provider already extracts thought),
 * return it as-is.
 */
function extractStreamingPreview(raw) {
  // Strip optional markdown code fence (```json ... ``` or ``` ... ```)
  const stripped = raw.replace(/^```[a-z]*\n?/i, "").replace(/```\s*$/, "").trim();
  if (!stripped.startsWith("{")) return stripped;

  const parts = [];

  // ── action — once detected, show only "→ name" and stop. ────────────────
  // Never show args: they can contain full file contents (thousands of chars).
  const aMatch = stripped.match(/"action"\s*:\s*"/);
  if (aMatch) {
    const action = _jsonStrValue(stripped, aMatch.index + aMatch[0].length);
    if (action) parts.push("→ " + action);
    return parts.join("\n");
  }

  // Show a sliding TAIL while streaming long fields (was head-capped, which
  // froze the visible text once the cap was hit — the user could not tell
  // the stream was still alive). 1200 chars matches the thinking preview.
  const TAIL = 1200;
  const _tail = (s) => s.length > TAIL ? "… " + s.slice(-TAIL) : s;

  // ── thought — only while action hasn't appeared yet ───────────────────
  const tMatch = stripped.match(/"thought"\s*:\s*"/);
  if (tMatch) {
    const thought = _jsonStrValue(stripped, tMatch.index + tMatch[0].length);
    if (thought) parts.push(_tail(thought));
  }

  // ── conclusion (final answer, no action) ─────────────────────────────────
  const cMatch = stripped.match(/"conclusion"\s*:\s*"/);
  if (cMatch) {
    const concl = _jsonStrValue(stripped, cMatch.index + cMatch[0].length);
    if (concl) parts.push(_tail(concl));
  }

  return parts.join("\n");
}

function appendUserMessage(text) {
  hideWelcome();
  const div = document.createElement("div");
  div.className = "msg-user markdown-body";
  // Render the user's own message as markdown too — pasted prompts with
  // lists / paragraphs read far better than one collapsed text blob.
  div.innerHTML = renderMd(text);
  $messages.appendChild(div);
  scrollBottom();
}

function showThinking(label = "Thinking…") {
  removeThinking();
  thinkingEl = document.createElement("div");
  thinkingEl.className = "block-thinking";
  thinkingEl.innerHTML = `<div class="spin"></div><span>${label}</span>`;
  $messages.appendChild(thinkingEl);
  scrollBottom();
}

function removeThinking() {
  if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; }
}

function removeStreaming() {
  if (streamingEl) { streamingEl.remove(); streamingEl = null; }
}

/**
 * Replace the lightweight live thinking stream with a collapsed
 * `· THINKING` summary line (same structure as thought/observation),
 * clickable to expand the full accumulated text.
 */
function finalizeThinking() {
  if (!thinkingStreamEl) return;
  thinkingStreamEl.remove();
  thinkingStreamEl = null;
  const text = thinkingStreamRaw.trim();
  thinkingStreamRaw = "";
  if (text) appendCollapsible("thinking", "Thinking", text, null);
}

// Compact inline collapsible — arrow + label + step, body reveals on click.
function appendCollapsible(type, label, content, step, actionName = "") {
  hideWelcome();
  const el = document.createElement("details");
  el.className = `agent-line line-${type}`;

  const sum = document.createElement("summary");
  const stepStr = step != null ? `<span class="line-step">·${step}</span>` : "";
  const labelHtml = actionName
    ? `<span class="line-label action-name">${escHtml(actionName)}</span>`
    : "";
  sum.innerHTML = `
    <span class="line-chevron">▸</span>
    <span class="line-type">${escHtml(type)}</span>
    ${labelHtml}
    ${stepStr}
  `;

  const body = document.createElement("div");
  const useMarkdown = (type === "thought" || type === "observation"
                       || type === "error" || type === "thinking");
  if (useMarkdown) {
    body.className = "line-body markdown-body";
    body.innerHTML = renderMd(content);
  } else {
    body.className = "line-body line-body-mono";
    body.textContent = content || "";
  }

  el.appendChild(sum);
  el.appendChild(body);
  $messages.appendChild(el);
  scrollBottom();
  return el;
}

function appendFinal(text) {
  hideWelcome();
  const el = document.createElement("div");
  el.className = "block-final";
  const body = document.createElement("div");
  body.className = "final-body markdown-body";
  body.innerHTML = renderMd(text);
  el.appendChild(body);
  $messages.appendChild(el);
  scrollBottom();
}


// ── Knowledge cleared marker ──────────────────────────────────────────────
// Permanent in-conversation trace that the user wiped the global learnings
// store from Settings → Knowledge. Rendered as a centered divider, similar
// to "this is the start of a new chapter".

function appendKnowledgeClearedMarker(removed, ts) {
  hideWelcome();
  const el = document.createElement("div");
  el.className = "block-knowledge-cleared";
  const ago = (() => {
    if (!ts) return "";
    try {
      const d = new Date(ts);
      return d.toLocaleString(undefined, { hour: "2-digit", minute: "2-digit",
        day: "2-digit", month: "short" });
    } catch (_) { return ""; }
  })();
  const removedStr = (typeof removed === "number" && removed > 0)
    ? ` · ${removed} entr${removed === 1 ? "y" : "ies"} removed` : "";
  el.innerHTML =
    `<span class="kc-line"></span>` +
    `<span class="kc-label">🧹 Knowledge cleared${removedStr}` +
    (ago ? ` <span class="kc-ts">· ${escHtml(ago)}</span>` : "") +
    `</span>` +
    `<span class="kc-line"></span>`;
  $messages.appendChild(el);
  scrollBottom();
}

// ── Reflection indicator ──────────────────────────────────────────────────
// Shown while the auto-reflect skill runs after a successful conclusion.
// Lives in the messages flow so it scrolls with everything else.

let reflectionIndicatorEl = null;
let reflectionFadeTimer   = null;

function showReflectionIndicator(text, spinning) {
  hideWelcome();
  if (reflectionFadeTimer) { clearTimeout(reflectionFadeTimer); reflectionFadeTimer = null; }
  if (!reflectionIndicatorEl) {
    reflectionIndicatorEl = document.createElement("div");
    reflectionIndicatorEl.className = "block-reflection";
    $messages.appendChild(reflectionIndicatorEl);
  }
  reflectionIndicatorEl.classList.remove("block-reflection-done", "block-reflection-fade");
  reflectionIndicatorEl.innerHTML =
    (spinning ? `<span class="spin"></span>` : `<span class="block-reflection-icon">📚</span>`) +
    `<span class="block-reflection-text">${escHtml(text)}</span>`;
  scrollBottom();
}

const _KIND_ICON = {
  lessons:    "💡",
  patterns:   "🔧",
  user_prefs: "👤",
  mistakes:   "💥",
};

function finalizeReflectionIndicator(rawResult, added) {
  if (!reflectionIndicatorEl) {
    // The "queued" / "start" events were missed (e.g. UI reopened mid-flight).
    // Create the element now so we have something to finalize.
    showReflectionIndicator("…", false);
  }
  // Compact the message: "OK: saved learnings to ... (lessons=2 ...)" → "Saved 2 lessons, 1 pattern"
  let label = rawResult;
  const m = /^OK:.*lessons=(\d+)\s+patterns=(\d+)\s+user_prefs=(\d+)\s+mistakes=(\d+)/.exec(rawResult || "");
  if (m) {
    const parts = [];
    if (+m[1]) parts.push(`${m[1]} lesson${+m[1] > 1 ? "s" : ""}`);
    if (+m[2]) parts.push(`${m[2]} pattern${+m[2] > 1 ? "s" : ""}`);
    if (+m[3]) parts.push(`${m[3]} pref${+m[3] > 1 ? "s" : ""}`);
    if (+m[4]) parts.push(`${m[4]} mistake${+m[4] > 1 ? "s" : ""}`);
    label = parts.length ? `Saved ${parts.join(", ")}` : "Saved learnings";
  } else if (/^SKIP:/i.test(rawResult || "")) {
    label = "Nothing worth saving";
  } else if (/^ERROR:/i.test(rawResult || "")) {
    label = rawResult.length > 80 ? rawResult.slice(0, 77) + "…" : rawResult;
  }

  reflectionIndicatorEl.classList.add("block-reflection-done");

  // Build header (chevron + icon + label). Clickable only if there are
  // entries to expand.
  const hasEntries = Array.isArray(added) && added.length > 0;
  const chevron = hasEntries
    ? `<span class="block-reflection-chevron">▸</span>`
    : `<span class="block-reflection-chevron block-reflection-chevron-mute">·</span>`;
  reflectionIndicatorEl.innerHTML =
    `<div class="block-reflection-header">` +
      chevron +
      `<span class="block-reflection-icon">📚</span>` +
      `<span class="block-reflection-text">${escHtml(label)}</span>` +
    `</div>`;

  if (hasEntries) {
    // Pre-render the body, hidden by default. Click on header toggles.
    const body = document.createElement("div");
    body.className = "block-reflection-body";
    body.style.display = "none";
    // Group by kind, preserve order from `added`.
    const groups = { lessons: [], patterns: [], user_prefs: [], mistakes: [] };
    for (const e of added) {
      if (groups[e.kind]) groups[e.kind].push(e);
    }
    const groupHtml = [];
    for (const kind of ["lessons", "patterns", "user_prefs", "mistakes"]) {
      if (!groups[kind].length) continue;
      groupHtml.push(
        `<div class="block-reflection-group-title">` +
          `${_KIND_ICON[kind] || "·"} ${kind.replace("_", " ")} ` +
          `<span class="block-reflection-count">(${groups[kind].length})</span>` +
        `</div>` +
        `<ul class="block-reflection-list">` +
          groups[kind].map(e => `<li>${escHtml(e.text)}</li>`).join("") +
        `</ul>`
      );
    }
    body.innerHTML = groupHtml.join("");
    reflectionIndicatorEl.appendChild(body);

    const header = reflectionIndicatorEl.querySelector(".block-reflection-header");
    header.style.cursor = "pointer";
    header.addEventListener("click", () => {
      const open = body.style.display !== "none";
      body.style.display = open ? "none" : "block";
      const ch = header.querySelector(".block-reflection-chevron");
      if (ch) ch.textContent = open ? "▸" : "▾";
    });
  }

  // Detach the reference so the NEXT task's reflection creates a brand
  // new indicator block instead of overwriting this one. The user gets a
  // permanent visual log of every consolidation that ran in this thread.
  if (reflectionFadeTimer) { clearTimeout(reflectionFadeTimer); reflectionFadeTimer = null; }
  reflectionIndicatorEl = null;
}

function appendAskUserInert(question, hint, mode) {
  hideWelcome();
  const el = document.createElement("div");
  el.className = "block-ask";
  const modeLabel = mode === "confirm" ? " (y / n)" : "";
  el.innerHTML = `
    <div class="ask-header"><span>✦</span><span>Pragma asks${modeLabel}</span></div>
    <div class="ask-body">
      <div class="ask-question">${escHtml(question || "")}</div>
      ${hint ? `<div class="ask-hint">${escHtml(hint)}</div>` : ""}
    </div>
  `;
  $messages.appendChild(el);
  return el;
}

function appendAskUser(question, hint, mode) {
  askUserEl = appendAskUserInert(question, hint, mode);
  scrollBottom();
  setAnswerMode(true, mode);
}

function setAnswerMode(active, mode = "input") {
  answerMode = active;
  if (active) {
    $inputArea.classList.add("answer-mode");
    $input.placeholder = mode === "confirm" ? "y / n…" : "Your answer…";
    $input.disabled   = false;
    $sendBtn.disabled = false;
    setTimeout(() => $input.focus(), 50);
  } else {
    $inputArea.classList.remove("answer-mode");
    $input.placeholder = isReadOnly
      ? "View only — start a new conversation to continue"
      : "Ask Pragma to do something… (Enter to send, Shift+Enter for newline)";
  }
}

function resolveAskUser(val) {
  if (askUserEl) {
    const body = askUserEl.querySelector(".ask-body");
    const answered = document.createElement("div");
    answered.className = "ask-answered";
    answered.textContent = `→ ${val}`;
    body.appendChild(answered);
    askUserEl = null;
  }
  setAnswerMode(false);
  sendWS({ type: "user_answer", content: val });
  showThinking();
}

function formatArgs(args) {
  if (!args || !Object.keys(args).length) return "{}";
  return Object.entries(args)
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("\n");
}

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Only auto-scroll if the user is already near the bottom (within 120px).
// This lets the user freely scroll up during streaming without being dragged back.
function scrollBottom() {
  const distFromBottom = $messages.scrollHeight - $messages.scrollTop - $messages.clientHeight;
  if (distFromBottom < 120) {
    $messages.scrollTop = $messages.scrollHeight;
  }
}

function setReadOnly(val) {
  isReadOnly = val;
  $sendBtn.disabled = val || running;
  $input.disabled   = val || running;
  $input.placeholder = val
    ? "View only — start a new conversation to continue"
    : "Ask Pragma to do something… (Enter to send, Shift+Enter for newline)";
}

function setRunning(val) {
  running = val;
  $sendBtn.disabled = val || isReadOnly;
  $input.disabled   = val || isReadOnly;
  if ($stopBtn) $stopBtn.style.display = val ? "flex" : "none";
}


// ── Input ──────────────────────────────────────────────────────────────────

function submit() {
  if (isReadOnly) return;
  const val = $input.value.trim();
  if (!val) return;

  if (answerMode) {
    appendUserMessage(val);
    $input.value = "";
    autoResize();
    document.getElementById("prompt-coach")?.classList.add("hidden");
    resolveAskUser(val);
    return;
  }

  if (running) return;
  if (!activeId) { alert("No active conversation. Create one from the sidebar."); return; }

  startNewTask();
  appendUserMessage(val);
  sendWS({ type: "task", content: val, max_steps: maxStepsConfig });
  setRunning(true);
  setStatus("running", "Running");
  showThinking();
  $input.value = "";
  autoResize();
  // Hide the coach: the user committed to this prompt, no point nagging
  // about it now. It re-evaluates on the next keystroke.
  document.getElementById("prompt-coach")?.classList.add("hidden");
}

$sendBtn.addEventListener("click", submit);
$stopBtn?.addEventListener("click", () => {
  sendWS({ type: "stop" });
  $stopBtn.style.display = "none";
  $stopBtn.disabled = true;
});
$input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
});

function autoResize() {
  $input.style.height = "auto";
  $input.style.height = Math.min($input.scrollHeight, 150) + "px";
}
$input.addEventListener("input", autoResize);


// ── Prompt coach ───────────────────────────────────────────────────────────
// Soft, never-blocking hints shown above the textarea while the user types.
// Purely heuristic, no LLM call. The goal is to nudge the user toward
// including the kind of context Pragma typically needs to avoid early-step
// fumbling: which file, what was observed, what was expected.

const $coach = document.getElementById("prompt-coach");

// Each rule returns either null (not applicable) or a string (the hint).
// At most ONE hint is shown at a time — the first matching rule wins, so
// rules are ordered most-actionable-first.
const _COACH_RULES = [
  // Very short prompts — almost always need elaboration.
  (text) => {
    const words = text.trim().split(/\s+/).filter(Boolean);
    if (words.length > 0 && words.length < 4) {
      return "💡 Very short — consider what Pragma would need: which file? what to do? what's the expected result?";
    }
    return null;
  },

  // Symptom words without observation/expectation contrast.
  (text) => {
    const symptom = /\b(broken|doesn[' ]?t work|doesn[' ]?t open|fails?|crashes?|nothing happens|not working|hangs?)\b/i;
    const expectation = /\b(should|expected?|supposed|want it to)\b/i;
    if (symptom.test(text) && !expectation.test(text)) {
      return "💡 You're describing a symptom. Add what you EXPECT to happen vs what you actually SEE — Pragma diagnoses faster with both sides.";
    }
    return null;
  },

  // Pronouns or vague references without a filename / path.
  (text) => {
    const vague = /^\s*(fix|find|check|debug|update|change|make)\s+(this|it|that|the\s+(bug|thing|issue|problem))\b/i;
    const hasFile = /[\w-]+\.[a-z]{1,5}\b|[A-Za-z]:[\\/][^\s]+|\/[\w-./]+\.[a-z]{1,5}/i;
    if (vague.test(text) && !hasFile.test(text)) {
      return "💡 'this / it' is ambiguous. Mention the specific file or path, or describe where Pragma should look.";
    }
    return null;
  },

  // Build/create requests without spec details — soft nudge only.
  (text) => {
    const verb = /^\s*(create|build|make|write|generate)\b/i;
    if (verb.test(text) && text.trim().split(/\s+/).length < 8) {
      return "💡 Building something — a one-line spec helps (language? framework? files? interface?).";
    }
    return null;
  },
];

function _runCoach() {
  const txt = $input.value;
  if (!txt.trim()) {
    $coach.classList.add("hidden");
    $coach.textContent = "";
    return;
  }
  for (const rule of _COACH_RULES) {
    const hint = rule(txt);
    if (hint) {
      $coach.textContent = hint;
      $coach.classList.remove("hidden");
      return;
    }
  }
  $coach.classList.add("hidden");
  $coach.textContent = "";
}

// Debounce so we don't recompute on every keystroke of a long paragraph.
let _coachTimer = null;
$input.addEventListener("input", () => {
  if (_coachTimer) clearTimeout(_coachTimer);
  _coachTimer = setTimeout(_runCoach, 180);
});
// Also hide after submit (the textarea is cleared elsewhere).
$input.addEventListener("blur", _runCoach);


// ── Modal (cwd selector) ───────────────────────────────────────────────────

const $backdrop   = document.getElementById("modal-backdrop");
const $modalInput = document.getElementById("modal-input");
const $modalError = document.getElementById("modal-error");
const $modalOk    = document.getElementById("modal-ok");
const $modalCancel= document.getElementById("modal-cancel");
const $modalTitle = document.getElementById("modal-title");
const $modalDesc  = document.getElementById("modal-desc");

let modalResolver = null;

function openModal({ title, desc, value }) {
  $modalTitle.textContent = title || "Working directory";
  $modalDesc.textContent  = desc  || "Absolute path — the agent will operate here.";
  $modalInput.value       = value || "";
  $modalError.textContent = "";
  $backdrop.classList.remove("hidden");
  setTimeout(() => $modalInput.focus(), 30);
  return new Promise(resolve => { modalResolver = resolve; });
}

function closeModal(val) {
  $backdrop.classList.add("hidden");
  if (modalResolver) { modalResolver(val); modalResolver = null; }
}

$modalCancel.addEventListener("click", () => closeModal(null));
$backdrop.addEventListener("click", (e) => { if (e.target === $backdrop) closeModal(null); });
$modalOk.addEventListener("click", () => {
  const v = $modalInput.value.trim();
  if (!v) { $modalError.textContent = "Please enter a path."; return; }
  closeModal(v);
});
$modalInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter")  { e.preventDefault(); $modalOk.click(); }
  if (e.key === "Escape") { e.preventDefault(); closeModal(null); }
});

$workdir.addEventListener("click", async () => {
  if (!activeId) {
    // No active thread → create one with a chosen cwd
    const val = await openModal({
      title: "New conversation",
      desc:  "Working directory for this conversation (absolute path).",
      value: currentCwd || defaultCwd,
    });
    if (val) newThread(val);
    return;
  }
  if (running) { alert("Cannot change directory while a task is running."); return; }
  const val = await openModal({
    title: "Working directory",
    desc:  "Change working directory for this conversation.",
    value: currentCwd || defaultCwd,
  });
  if (!val) return;
  try {
    const data = await api("PATCH", `/api/threads/${activeId}`, { cwd: val });
    setWorkdir(data.cwd);
    // Notifica il WS handler in-memory così la prossima task usa subito la nuova cwd
    sendWS({ type: "set_cwd", cwd: data.cwd });
    reloadThreads();
  } catch (e) {
    alert(`Change failed: ${e.message}`);
  }
});


// ── Settings modal ─────────────────────────────────────────────────────────

const $settingsBackdrop = document.getElementById("settings-backdrop");

async function openSettings() {
  let cfg;
  try {
    cfg = await api("GET", "/api/settings");
  } catch (e) {
    alert("Failed to load settings: " + e.message);
    return;
  }
  document.getElementById("settings-envpath").textContent = cfg.env_path || ".env";
  document.getElementById("s-env-lines").textContent =
    cfg.env_lines && cfg.env_lines.length ? cfg.env_lines.join("\n") : "(no .env found)";
  // Default to the Configuration tab whenever the modal opens.
  switchSettingsTab("config");
  $settingsBackdrop.classList.remove("hidden");
}

function switchSettingsTab(name) {
  document.querySelectorAll(".settings-tab").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === name));
  document.getElementById("settings-tab-config")
    .classList.toggle("hidden", name !== "config");
  document.getElementById("settings-tab-knowledge")
    .classList.toggle("hidden", name !== "knowledge");
  if (name === "knowledge") loadLearnings();
}

async function loadLearnings() {
  const $box = document.getElementById("learnings-container");
  const $path = document.getElementById("settings-learnings-path");
  $box.innerHTML = `<div class="hint">Loading…</div>`;
  let data;
  try {
    data = await api("GET", "/api/learnings");
  } catch (e) {
    $box.innerHTML = `<div class="hint" style="color:var(--error-color)">Failed: ${escHtml(e.message)}</div>`;
    return;
  }
  if (data.path) $path.textContent = data.path;
  const entries = data.entries || [];
  if (!entries.length) {
    $box.innerHTML = `<div class="hint">No learnings yet. Complete a task and Pragma will consolidate one.</div>`;
    return;
  }
  // Group by kind, preserving insertion order for stable display.
  const groups = { lessons: [], patterns: [], user_prefs: [], mistakes: [] };
  for (const e of entries) {
    if (groups[e.kind]) groups[e.kind].push(e);
    else (groups[e.kind] = []).push(e);
  }
  const html = [];
  html.push(`<div class="learnings-total">${entries.length} total entries</div>`);
  // Each kind becomes a collapsible group — closed by default to mirror the
  // conversation collapsibles (thought/action/observation). Click the header
  // to reveal the bullets.
  for (const kind of ["lessons", "patterns", "user_prefs", "mistakes"]) {
    const items = groups[kind] || [];
    if (!items.length) continue;
    html.push(
      `<div class="learnings-group">` +
        `<div class="learnings-group-title" data-kind="${kind}">` +
          `<span class="learnings-group-chevron">▸</span>` +
          `<span class="learnings-group-icon">${_KIND_ICON[kind] || "·"}</span>` +
          `<span class="learnings-group-label">${kind.replace("_"," ")}</span>` +
          `<span class="block-reflection-count">(${items.length})</span>` +
        `</div>` +
        `<ul class="learnings-list" style="display:none">` +
          items.map(e =>
            `<li>` +
              `<span class="learnings-text">${escHtml(e.text)}</span>` +
              (e.label ? ` <span class="learnings-meta">[${escHtml(e.label)}]</span>` : "") +
              `<button class="learnings-del" title="Delete this learning" data-text="${escHtml(e.text)}">✕</button>` +
            `</li>`
          ).join("") +
        `</ul>` +
      `</div>`
    );
  }
  $box.innerHTML = html.join("");

  // Wire group toggles.
  $box.querySelectorAll(".learnings-group-title").forEach(hdr => {
    hdr.addEventListener("click", (ev) => {
      // Ignore clicks on the delete buttons (they bubble from the list,
      // but the list is hidden until we open it — defensive anyway).
      if (ev.target.closest(".learnings-del")) return;
      const list = hdr.parentElement.querySelector(".learnings-list");
      if (!list) return;
      const open = list.style.display !== "none";
      list.style.display = open ? "none" : "block";
      const ch = hdr.querySelector(".learnings-group-chevron");
      if (ch) ch.textContent = open ? "▸" : "▾";
    });
  });

  // Wire delete buttons. stopPropagation so clicking ✕ doesn't toggle the group.
  $box.querySelectorAll(".learnings-del").forEach(btn => {
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const text = btn.dataset.text;
      if (!confirm("Remove this learning permanently?")) return;
      try {
        await api("POST", "/api/learnings/delete", { text });
        loadLearnings();
      } catch (e) {
        alert("Delete failed: " + e.message);
      }
    });
  });
}

async function summarizeLearnings() {
  const $btn = document.getElementById("learnings-summarize-btn");
  const $box = document.getElementById("learnings-summary");
  if ($btn && $btn.disabled) return;
  if ($btn) {
    $btn.disabled = true;
    $btn.innerHTML = `<span class="spin"></span> Summarizing…`;
  }
  // Mark the gear icon in the header so the user knows there's something
  // brewing in the background even if they close the modal.
  document.getElementById("settings-btn")?.classList.add("has-pending");
  $box.classList.remove("hidden");
  $box.innerHTML =
    `<div class="hint" style="display:flex;align-items:center;gap:8px">` +
      `<span class="spin"></span>` +
      `<span>Running a single LLM call over the store… this can take a few seconds.</span>` +
    `</div>`;
  try {
    const res = await api("POST", "/api/learnings/summarize");
    const md  = res.summary || "_(empty)_";
    // Render the summary as a collapsible block, open by default (the user
    // just clicked Summarize so they obviously want to see the result).
    $box.innerHTML =
      `<div class="learnings-summary-header" id="learnings-summary-header">` +
        `<span class="learnings-summary-chevron">▾</span>` +
        `<span class="learnings-summary-icon">📝</span>` +
        `<span class="learnings-summary-title">Summary</span>` +
        `<span class="learnings-summary-meta">based on ${res.count || 0} entries</span>` +
        `<button class="learnings-summary-close" title="Hide summary"` +
        ` onclick="event.stopPropagation();document.getElementById('learnings-summary').classList.add('hidden')">✕</button>` +
      `</div>` +
      `<div class="learnings-summary-body markdown-body" id="learnings-summary-body">${renderMd(md)}</div>`;
    // Wire toggle on the header (click anywhere except the ✕ button).
    const $hdr  = document.getElementById("learnings-summary-header");
    const $body = document.getElementById("learnings-summary-body");
    $hdr.addEventListener("click", () => {
      const open = $body.style.display !== "none";
      $body.style.display = open ? "none" : "block";
      const $ch = $hdr.querySelector(".learnings-summary-chevron");
      if ($ch) $ch.textContent = open ? "▸" : "▾";
    });
  } catch (e) {
    $box.innerHTML = `<div class="hint" style="color:var(--error-color)">Summary failed: ${escHtml(e.message)}</div>`;
  } finally {
    if ($btn) { $btn.disabled = false; $btn.innerHTML = "📝 Summarize"; }
    document.getElementById("settings-btn")?.classList.remove("has-pending");
  }
}

async function clearAllLearnings() {
  const $btn = document.getElementById("learnings-clear-btn");
  if ($btn && $btn.disabled) return;
  if (!confirm(
    "Wipe ALL consolidated knowledge?\n\n" +
    "This deletes every entry from the global store and drops a " +
    "'knowledge cleared' marker into every conversation so you have a " +
    "visual trace of when it happened.\n\nThis cannot be undone."
  )) return;
  if ($btn) { $btn.disabled = true; $btn.textContent = "Clearing…"; }
  try {
    const res = await api("POST", "/api/learnings/clear");
    // Hide any stale summary panel — its content is no longer valid.
    document.getElementById("learnings-summary")?.classList.add("hidden");
    loadLearnings();
    if ($btn) {
      $btn.textContent = `Cleared ${res.removed} (marked ${res.threads_marked} threads)`;
      setTimeout(() => {
        $btn.textContent = "🧹 Clear all knowledge";
        $btn.disabled = false;
      }, 2200);
    }
  } catch (e) {
    if ($btn) { $btn.disabled = false; $btn.textContent = "🧹 Clear all knowledge"; }
    alert("Clear failed: " + e.message);
  }
}

function closeSettings() {
  $settingsBackdrop.classList.add("hidden");
}

async function reloadEnv() {
  const $btn = document.getElementById("settings-reload-btn");
  if ($btn.disabled) return;
  $btn.disabled = true;
  $btn.dataset.orig = $btn.innerHTML;
  $btn.innerHTML = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13.5 8A5.5 5.5 0 1 1 10 3.07"/><polyline points="10 1 10 4 13 4"/></svg> Loading…';
  try {
    const res = await api("POST", "/api/settings/reload");
    document.getElementById("s-env-lines").textContent =
      res.env_lines && res.env_lines.length ? res.env_lines.join("\n") : "(no .env found)";
    $btn.innerHTML = '✓ Loaded';
    $btn.classList.add("btn-loaded");
    setTimeout(() => {
      $btn.innerHTML = $btn.dataset.orig;
      $btn.classList.remove("btn-loaded");
      $btn.disabled = false;
    }, 1500);
  } catch (e) {
    $btn.innerHTML = $btn.dataset.orig;
    $btn.disabled = false;
    alert("Reload failed: " + e.message);
  }
}

// Pick a .env file via the browser's native file dialog, send its content
// to the backend (the browser cannot expose the real path, only the bytes),
// which persists it and reloads the config immediately.
async function uploadEnvFile(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  let content;
  try {
    content = await file.text();
  } catch (e) {
    alert("Could not read the file: " + e.message);
    input.value = "";
    return;
  }
  try {
    const res = await api("POST", "/api/settings/env", { content });
    if (!res.ok) throw new Error(res.error || "unknown error");
    document.getElementById("settings-envpath").textContent = res.env_path || ".env";
    document.getElementById("s-env-lines").textContent =
      res.env_lines && res.env_lines.length ? res.env_lines.join("\n") : "(no .env found)";
    alert("Loaded and applied: " + file.name);
  } catch (e) {
    alert("Upload failed: " + e.message);
  }
  input.value = "";  // reset so the same file can be re-selected
}

$settingsBackdrop.addEventListener("click", (e) => {
  if (e.target === $settingsBackdrop) closeSettings();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$settingsBackdrop.classList.contains("hidden")) {
    closeSettings();
  }
});


// ── Boot ───────────────────────────────────────────────────────────────────

function renderModelBadge() {
  const $badge = document.getElementById("model-badge");
  if (!$badge || !llmConfig) return;
  const def      = llmConfig.default_model || "";
  const cod      = llmConfig.coding_model  || def;
  const distinct = llmConfig.coding_distinct;

  $badge.innerHTML = "";

  const $r = document.createElement("span");
  $r.id = "badge-default";
  $r.className = "badge-item";
  $r.textContent = `default: ${def}`;
  $r.title = `Default model (reasoning role of the ReAct loop): ${def}\nProvider: ${llmConfig.provider}`;
  $badge.appendChild($r);

  if (distinct) {
    const $sep = document.createElement("span");
    $sep.className = "badge-sep";
    $sep.textContent = "|";
    $badge.appendChild($sep);

    const $c = document.createElement("span");
    $c.id = "badge-coding";
    $c.className = "badge-item";
    $c.textContent = `code: ${cod}`;
    $c.title = `Code skill: ${cod}`;
    $badge.appendChild($c);
  }
}

function activateBadge(which) {
  document.getElementById("badge-default")?.classList.toggle("active", which === "default");
  document.getElementById("badge-coding") ?.classList.toggle("active", which === "coding");
}

function resetBadges() {
  document.getElementById("badge-default")?.classList.remove("active");
  document.getElementById("badge-coding") ?.classList.remove("active");
}

(async function boot() {
  try {
    const cfg = await api("GET", "/api/config");
    defaultCwd     = cfg.default_cwd || "";
    llmConfig      = cfg.llm || null;
    maxStepsConfig = cfg.max_steps ?? maxStepsConfig;
    setWorkdir(defaultCwd);
    renderModelBadge();
  } catch (_) {}

  await reloadThreads();
  // Do not auto-open any thread — let the user pick from the sidebar
  // or create a new one (which will trigger the folder picker).
  $messages.innerHTML = WELCOME_HTML;
})();
