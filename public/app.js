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

// Session-stats footer
const $sessionRequests = document.getElementById("session-requests");
const $sessionToolCalls = document.getElementById("session-tool-calls");
const $sessionCost = document.getElementById("session-cost");

// Session memory — orchestrator returns a session_id on the first done event;
// we reuse it so audit_log rows group by session.
let sessionId = null;

// Session rollup counters — updated on every 'done' event.
const session = { requests: 0, toolCalls: 0, costUsd: 0 };

// Wire up the suggestion chips
document.querySelectorAll(".suggest").forEach((btn) => {
  btn.addEventListener("click", () => {
    input.value = btn.textContent.trim();
    input.focus();
  });
});

// Wire up the test-dataset rows: each row has its own data-prompt tailored
// to the edge case that employee was seeded for. Clicking pre-fills the
// input and collapses the disclosure for clean focus on the input.
document.querySelectorAll(".dataset-row").forEach((row) => {
  row.addEventListener("click", () => {
    const prompt = row.dataset.prompt;
    if (!prompt) return;
    input.value = prompt;
    input.focus();
    const details = document.getElementById("dataset");
    if (details) details.open = false;
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
      const { title, hint } = classifyHttpError(resp.status, errText);
      finalizeAgentMessage(agentMsg, `${title}${hint ? "  ·  " + hint : ""}`, true);
      return;
    }

    await consumeSSE(resp, agentMsg);
  } catch (err) {
    const { title, hint } = classifyNetworkError(err);
    finalizeAgentMessage(agentMsg, `${title}${hint ? "  ·  " + hint : ""}`, true);
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
    case "resolver_check":
      // Show the resolver firing inline — informational only.
      addResolverChip(agentMsg, event.tool);
      break;
    case "escalation":
      // Conflict resolver returned 'escalate'. Render a structured card with
      // the brief (conflict / risk / recommendation / question for HR).
      renderEscalationCard(agentMsg, event.action_summary, event.brief);
      break;
    case "text_delta":
      appendDeltaText(agentMsg, event.text);
      break;
    case "done":
      sessionId = event.session_id;
      finalizeAgentMessage(agentMsg);
      addCostFooter(
        agentMsg,
        event.cost_usd,
        event.tool_call_count,
        event.truncated,
        event.escalated
      );
      updateSessionStats(event.cost_usd, event.tool_call_count);
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
    // Per-agent class so each gets its own color (see style.css).
    pill.className = `agent-pill ${cssSafe(a)}`;
    pill.textContent = a;
    agentMsg.agents.appendChild(pill);
  }
  for (const m of missing) {
    const pill = document.createElement("span");
    pill.className = `agent-pill deferred ${cssSafe(m)}`;
    pill.textContent = `${m} · deferred`;
    agentMsg.agents.appendChild(pill);
  }
}

function cssSafe(s) {
  return String(s).toLowerCase().replace(/[^a-z0-9_-]/g, "-");
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

function addResolverChip(agentMsg, toolName) {
  const chip = document.createElement("div");
  chip.className = "tool-pill resolver";
  chip.innerHTML = `<span class="dot"></span> <span class="tool-name">conflict_resolver</span><span class="tool-state"> · gating ${escapeHtml(toolName)}</span>`;
  agentMsg.tools.appendChild(chip);
  scrollToBottom();
}

function renderEscalationCard(agentMsg, actionSummary, brief) {
  if (!brief) return;
  const risk = (brief.risk_level || "medium").toLowerCase();
  const card = document.createElement("div");
  card.className = `escalation-card risk-${risk}`;
  card.innerHTML = `
    <div class="escalation-header">
      <span class="escalation-badge">⚠ Escalated to HR</span>
      <span class="escalation-risk risk-${risk}">${risk.toUpperCase()} RISK</span>
    </div>
    <div class="escalation-action">${escapeHtml(actionSummary || "")}</div>
    <dl class="escalation-fields">
      <dt>Conflict</dt><dd>${escapeHtml(brief.conflict || "")}</dd>
      <dt>Recommendation</dt><dd>${escapeHtml(brief.recommendation || "")}</dd>
      <dt>Question for HR</dt><dd>${escapeHtml(brief.question_for_hr || "")}</dd>
    </dl>
  `;
  // Insert the card before the bubble so it appears above the agent's text.
  agentMsg.msg.insertBefore(card, agentMsg.bubble);
  scrollToBottom();
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

function addCostFooter(agentMsg, costUsd, toolCallCount, truncated, escalated) {
  const footer = document.createElement("div");
  footer.className = "cost-footer";
  const costStr = costUsd < 0.01 ? `${(costUsd * 100).toFixed(2)}¢` : `$${costUsd.toFixed(4)}`;
  const tools = toolCallCount === 1 ? "1 tool call" : `${toolCallCount} tool calls`;
  let txt = `${tools} · ${costStr}`;
  if (escalated) txt += " · escalated";
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

function updateSessionStats(reqCost, reqToolCalls) {
  session.requests += 1;
  session.toolCalls += reqToolCalls || 0;
  session.costUsd += reqCost || 0;
  $sessionRequests.textContent = `${session.requests} request${session.requests === 1 ? "" : "s"}`;
  $sessionToolCalls.textContent = `${session.toolCalls} tool call${session.toolCalls === 1 ? "" : "s"}`;
  $sessionCost.textContent = formatCostFull(session.costUsd);
}

function formatCostFull(usd) {
  return `$${usd.toFixed(5)}`;
}

function formatDuration(ms) {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function scrollToBottom() {
  // Scroll the chat container, not the page. With #history capped at 60vh,
  // the page itself doesn't need to scroll on new messages — only the
  // conversation panel does.
  historyEl.scrollTo({ top: historyEl.scrollHeight, behavior: "smooth" });
}

async function safeText(resp) {
  try { return await resp.text(); } catch { return ""; }
}

function classifyHttpError(status, body) {
  if (status === 429) {
    return {
      title: "Rate limited",
      hint: "Too many requests in a short window. Wait a moment and try again.",
    };
  }
  if (status === 504) {
    return {
      title: "Agent timed out",
      hint: "The serverless function exceeded its 60s limit. Try a simpler request, or wait a moment for the function to recycle.",
    };
  }
  if (status >= 500) {
    return {
      title: `Server error (${status})`,
      hint: "The agent service may be cold-starting or restarting. Try again in a few seconds.",
    };
  }
  if (status === 401 || status === 403) {
    return {
      title: "Authentication failed",
      hint: "An API key is likely missing or misconfigured server-side.",
    };
  }
  return {
    title: `Request rejected (HTTP ${status})`,
    hint: body ? body.slice(0, 240) : "No additional detail from server.",
  };
}

function classifyNetworkError(err) {
  if (err && err.name === "TypeError" && /fetch/i.test(err.message || "")) {
    return {
      title: "Couldn't reach the agent",
      hint: "Check your connection. If the page is deployed, the function may be cold-starting.",
    };
  }
  return {
    title: "Unexpected error",
    hint: err && err.message ? err.message : String(err),
  };
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
