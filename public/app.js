// HR Operations Agent — frontend
// Consumes /api/chat/stream (SSE) and renders events live, growth-ai-agent style:
//   classifier   → agent pills above the bubble
//   tool_use     → running tool pill (animated dot)
//   tool_result  → pill turns ✓ done (with duration) or ✗ error
//   text_delta   → tokens appended to bubble (streaming cursor at end)
//   done         → cost footer attached to message
//   error        → red error block

const historyEl = document.getElementById("history");
const form = document.getElementById("composer");
const input = document.getElementById("question");
const sendBtn = document.getElementById("send");

// Session memory — orchestrator returns a session_id on the first done event;
// we reuse it so audit_log rows group by session.
let sessionId = null;

// Wire up the suggestion chips
document.querySelectorAll(".suggest").forEach((btn) => {
  btn.addEventListener("click", () => {
    input.value = btn.textContent.trim();
    input.focus();
  });
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = input.value.trim();
  if (!question) return;

  appendUserMessage(question);
  input.value = "";
  setSending(true);

  // Build the agent message shell — we'll fill it as events arrive.
  const agentMsg = startAgentMessage();

  try {
    const resp = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: question, session_id: sessionId }),
    });

    if (!resp.ok) {
      const errText = await safeText(resp);
      finalizeAgentMessage(agentMsg, `Error ${resp.status}: ${errText || resp.statusText}`, true);
      return;
    }

    await consumeSSE(resp, agentMsg);
  } catch (err) {
    finalizeAgentMessage(agentMsg, `Network error: ${err.message}`, true);
  } finally {
    setSending(false);
    input.focus();
  }
});

// ============================================================================
// SSE consumer
// ============================================================================

async function consumeSSE(resp, agentMsg) {
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = chunk.startsWith("data: ") ? chunk.slice(6) : chunk;
      if (!line) continue;
      let event;
      try { event = JSON.parse(line); } catch { continue; }
      handleEvent(event, agentMsg);
    }
  }
}

function handleEvent(event, agentMsg) {
  switch (event.type) {
    case "classifier":
      renderAgentPills(agentMsg, event.agents_available || [], event.agents_missing || []);
      break;
    case "tool_use":
      addToolPill(agentMsg, event.id, event.tool);
      break;
    case "tool_result":
      markToolPill(agentMsg, event.id, event.is_error ? "error" : "done");
      break;
    case "text_delta":
      appendDeltaText(agentMsg, event.text);
      break;
    case "done":
      sessionId = event.session_id;
      finalizeAgentMessage(agentMsg);
      addCostFooter(agentMsg, event.cost_usd, event.tool_call_count, event.truncated);
      break;
    case "error":
      finalizeAgentMessage(agentMsg, event.message, true);
      break;
  }
}

// ============================================================================
// Agent message DOM
// ============================================================================

function startAgentMessage() {
  const msg = document.createElement("div");
  msg.className = "message agent";

  const agents = document.createElement("div");
  agents.className = "agent-pills";
  msg.appendChild(agents);

  const tools = document.createElement("div");
  tools.className = "tool-pills";
  msg.appendChild(tools);

  const bubble = document.createElement("div");
  bubble.className = "bubble streaming";
  msg.appendChild(bubble);

  historyEl.appendChild(msg);
  scrollToBottom();

  return {
    msg,
    agents,
    tools,
    bubble,
    textBuffer: "",
    toolStartTimes: new Map(), // id → ts
  };
}

function renderAgentPills(agentMsg, available, missing) {
  agentMsg.agents.innerHTML = "";
  for (const a of available) {
    const pill = document.createElement("span");
    pill.className = "agent-pill";
    pill.textContent = a;
    agentMsg.agents.appendChild(pill);
  }
  for (const m of missing) {
    const pill = document.createElement("span");
    pill.className = "agent-pill deferred";
    pill.textContent = `${m} · deferred`;
    agentMsg.agents.appendChild(pill);
  }
}

function addToolPill(agentMsg, id, toolName) {
  const pill = document.createElement("div");
  pill.className = "tool-pill running";
  pill.dataset.id = id;
  pill.innerHTML = `<span class="dot"></span> <span class="tool-name">${escapeHtml(toolName)}</span><span class="tool-state">…</span>`;
  agentMsg.tools.appendChild(pill);
  agentMsg.toolStartTimes.set(id, performance.now());
  scrollToBottom();
}

function markToolPill(agentMsg, id, state) {
  const pill = agentMsg.tools.querySelector(`.tool-pill[data-id="${id}"]`);
  if (!pill) return;
  pill.classList.remove("running");
  pill.classList.add(state);
  const stateEl = pill.querySelector(".tool-state");
  if (stateEl) {
    if (state === "done") {
      const started = agentMsg.toolStartTimes.get(id);
      const dur = started ? Math.round(performance.now() - started) : null;
      stateEl.textContent = dur != null ? ` · ${formatDuration(dur)}` : "";
    } else {
      stateEl.textContent = " · failed";
    }
  }
}

function appendDeltaText(agentMsg, text) {
  agentMsg.textBuffer += text;
  agentMsg.bubble.innerHTML = formatMarkdownish(agentMsg.textBuffer);
  scrollToBottom();
}

function finalizeAgentMessage(agentMsg, errorMsg, isError) {
  agentMsg.bubble.classList.remove("streaming");
  if (isError) {
    const err = document.createElement("div");
    err.className = "error";
    err.textContent = errorMsg;
    agentMsg.msg.appendChild(err);
  } else if (!agentMsg.textBuffer) {
    agentMsg.bubble.textContent = "(agent returned no text)";
  }
  scrollToBottom();
}

function addCostFooter(agentMsg, costUsd, toolCallCount, truncated) {
  const footer = document.createElement("div");
  footer.className = "cost-footer";
  const costStr = costUsd < 0.01 ? `${(costUsd * 100).toFixed(2)}¢` : `$${costUsd.toFixed(4)}`;
  const tools = toolCallCount === 1 ? "1 tool call" : `${toolCallCount} tool calls`;
  let txt = `${tools} · ${costStr}`;
  if (truncated) txt += " · ⚠ truncated (10-call cap)";
  footer.textContent = txt;
  agentMsg.msg.appendChild(footer);
}

// ============================================================================
// Helpers
// ============================================================================

function appendUserMessage(text) {
  const msg = document.createElement("div");
  msg.className = "message user";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  msg.appendChild(bubble);
  historyEl.appendChild(msg);
  scrollToBottom();
}

function setSending(isSending) {
  sendBtn.disabled = isSending;
  sendBtn.textContent = isSending ? "Thinking…" : "Ask";
}

function formatDuration(ms) {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function scrollToBottom() {
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
}

async function safeText(resp) {
  try { return await resp.text(); } catch { return ""; }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Minimal markdown — **bold**, *italic*, `code`, line breaks. Escapes HTML first.
function formatMarkdownish(text) {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|\s)\*([^*\s][^*]*?)\*(?=\s|[.,!?;:]|$)/g, "$1<em>$2</em>");
  html = html.replace(/\n/g, "<br>");
  return html;
}

input.focus();
