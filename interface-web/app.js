// Pragma — frontend

// ── Quit ───────────────────────────────────────────────────────────────────

async function quitApp() {
  if (!confirm("Shut down the Pragma server?")) return;
  try { await fetch("/api/quit", { method: "POST" }); } catch (_) {}
  document.body.innerHTML =
    '<div style="display:flex;align-items:center;justify-content:center;height:100vh;'
    + 'font-family:system-ui;color:#888;font-size:.9rem;">Server stopped.</div>';
}

// ── Theme ──────────────────────────────────────────────────────────────────

(function initTheme() {
  const saved = localStorage.getItem("pragma-theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = saved || (prefersDark ? "dark" : "light");
  document.documentElement.setAttribute("data-theme", theme);
})();

function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("pragma-theme", theme);
  const sun  = document.getElementById("theme-icon-sun");
  const moon = document.getElementById("theme-icon-moon");
  if (!sun || !moon) return;
  if (theme === "dark") {
    sun.style.display  = "block";
    moon.style.display = "none";
    document.getElementById("theme-toggle").title = "Switch to light mode";
  } else {
    sun.style.display  = "none";
    moon.style.display = "block";
    document.getElementById("theme-toggle").title = "Switch to dark mode";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const current = document.documentElement.getAttribute("data-theme") || "light";
  setTheme(current);
  document.getElementById("theme-toggle")
    ?.addEventListener("click", () => {
      const c = document.documentElement.getAttribute("data-theme") || "light";
      setTheme(c === "dark" ? "light" : "dark");
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
  if (typeof marked === "undefined")      return escHtml(text);
  if (typeof marked.parse === "function") return marked.parse(text);
  if (typeof marked === "function")       return marked(text);
  return escHtml(text);
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
  activateBadge("reasoning");  // highlight immediately; model is thinking
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

    case "thought":
      if (ev.step != null) liveStep = ev.step;
      liveChars += (ev.content || "").length;
      removeThinking();
      activateBadge("reasoning");
      appendCollapsible("thought", "Thought", ev.content, ev.step);
      showThinking();
      break;

    case "action":
      liveChars += (ev.content || "").length + JSON.stringify(ev.args || {}).length;
      removeThinking();
      activateBadge(ev.name === "code" ? "coding" : "reasoning");
      appendCollapsible("action", ev.name || "Action", formatArgs(ev.args), ev.step, ev.name);
      showThinking("Executing…");
      break;

    case "observation":
      if (ev.step != null) liveStep = ev.step;
      liveChars += (ev.content || "").length;
      removeThinking();
      activateBadge("reasoning");
      appendCollapsible("observation", "Observation", ev.content, ev.step);
      showThinking();
      break;

    case "final":
      liveChars += (ev.content || "").length;
      removeThinking();
      appendFinal(ev.content);
      break;

    case "error":
      removeThinking();
      appendCollapsible("error", "Error", ev.content, ev.step);
      break;

    case "ask_user":
      removeThinking();
      appendAskUser(ev.question, ev.hint, ev.mode);
      break;

    case "stats":
      pendingStats = ev;
      break;

    case "done":
      removeThinking();
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

function appendUserMessage(text) {
  hideWelcome();
  const div = document.createElement("div");
  div.className = "msg-user";
  div.textContent = text;
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
  const useMarkdown = (type === "thought" || type === "observation" || type === "error");
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

function scrollBottom() { $messages.scrollTop = $messages.scrollHeight; }

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
}

$sendBtn.addEventListener("click", submit);
$input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
});

function autoResize() {
  $input.style.height = "auto";
  $input.style.height = Math.min($input.scrollHeight, 150) + "px";
}
$input.addEventListener("input", autoResize);


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
  document.getElementById("settings-envpath").textContent = cfg.env_path;
  document.getElementById("s-provider").value         = cfg.provider || "openai";
  document.getElementById("s-base-url").value         = cfg.base_url || "";
  document.getElementById("s-default-model").value    = cfg.default_model || "";
  document.getElementById("s-max-steps").value        = cfg.max_steps ?? maxStepsConfig;
  document.getElementById("s-backend-url").value      = cfg.backend_url || "";
  document.getElementById("s-coding-model").value     = cfg.coding_model || "";
  document.getElementById("s-coding-provider").value  = cfg.coding_provider || "";
  document.getElementById("s-coding-base-url").value  = cfg.coding_base_url || "";

  // Don't pre-fill keys; show preview as hint
  document.getElementById("s-api-key").value = "";
  document.getElementById("s-backend-key").value = "";
  document.getElementById("s-api-key-current").textContent =
    cfg.api_key_set ? `Currently set: ${cfg.api_key_preview}` : "Not set.";
  document.getElementById("s-backend-key-current").textContent =
    cfg.backend_key_set ? `Currently set: ${cfg.backend_key_preview}` : "Not set.";

  document.getElementById("settings-error").textContent = "";
  $settingsBackdrop.classList.remove("hidden");
  updateProviderUI();
}

function closeSettings() {
  $settingsBackdrop.classList.add("hidden");
}

function updateProviderUI() {
  const prov = document.getElementById("s-provider").value;
  const isBackend = prov === "backend";
  document.getElementById("s-backend-url-row").style.display = isBackend ? "" : "none";
  document.getElementById("s-backend-key-row").style.display = isBackend ? "" : "none";

  const hint = document.getElementById("s-base-url-hint");
  if (prov === "openai")    hint.textContent = "Leave empty to use the provider default (Ollama at http://localhost:11434/v1).";
  if (prov === "anthropic") hint.textContent = "Leave empty to use https://api.anthropic.com (default).";
  if (prov === "backend")   hint.textContent = "Optional. If set, overrides the Backend URL below.";
}

async function saveSettings() {
  const $btn = document.getElementById("settings-save");
  const $err = document.getElementById("settings-error");
  $err.textContent = "";

  const maxStepsVal = parseInt(document.getElementById("s-max-steps").value, 10);
  const body = {
    provider:        document.getElementById("s-provider").value,
    base_url:        document.getElementById("s-base-url").value.trim(),
    default_model:   document.getElementById("s-default-model").value.trim(),
    max_steps:       isNaN(maxStepsVal) ? maxStepsConfig : Math.max(1, maxStepsVal),
    backend_url:     document.getElementById("s-backend-url").value.trim(),
    coding_model:    document.getElementById("s-coding-model").value.trim(),
    coding_provider: document.getElementById("s-coding-provider").value.trim(),
    coding_base_url: document.getElementById("s-coding-base-url").value.trim(),
  };
  // Only send keys if user typed something — empty means "keep current"
  const apiKey = document.getElementById("s-api-key").value;
  const beKey  = document.getElementById("s-backend-key").value;
  if (apiKey) body.api_key     = apiKey;
  if (beKey)  body.backend_key = beKey;

  $btn.disabled = true;
  $btn.textContent = "Saving…";
  try {
    await api("POST", "/api/settings", body);
    closeSettings();
    // Refresh config (model badge + max steps) after save
    try {
      const cfg = await api("GET", "/api/config");
      llmConfig      = cfg.llm || null;
      maxStepsConfig = cfg.max_steps ?? maxStepsConfig;
      renderModelBadge();
    } catch (_) {}
  } catch (e) {
    $err.textContent = "Save failed: " + e.message;
  } finally {
    $btn.disabled = false;
    $btn.textContent = "Save";
  }
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
  $r.id = "badge-reasoning";
  $r.className = "badge-item";
  $r.textContent = `reasoning: ${def}`;
  $r.title = `Reasoning: ${def}\nProvider: ${llmConfig.provider}`;
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
  document.getElementById("badge-reasoning")?.classList.toggle("active", which === "reasoning");
  document.getElementById("badge-coding")   ?.classList.toggle("active", which === "coding");
}

function resetBadges() {
  document.getElementById("badge-reasoning")?.classList.remove("active");
  document.getElementById("badge-coding")   ?.classList.remove("active");
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
