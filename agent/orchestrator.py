"""
Orchestrator — Sonnet-based agent loop with MCP client.

Two public entry points:

  - run_stream(user_input, session_id) -> AsyncGenerator[dict, None]
        Yields events as they happen: classifier decision, tool_use,
        tool_result, text_delta (streamed Sonnet tokens), and finally done.
        Used by /api/chat/stream for SSE.

  - run(user_input, session_id) -> OrchestratorResponse
        Thin wrapper that consumes run_stream() and aggregates into a single
        final response. Used by CLI and /api/chat (non-streaming).

Pipeline per request:

    classifier (Haiku, fast routing)
        ↓ agents_required
    orchestrator:
        ↓ connect to MCP servers for agents_required
        ↓ aggregate tools across servers
        ↓ Sonnet tool-call loop (capped at MAX_TOOL_CALLS)
        ↓ stream tokens + tool events to caller
    audit_log writer (Supabase)
        ↓ session_id, user_input, agents_invoked, tool_calls, cost_usd

Design notes:
  - Per-request MCP subprocess. Spawn jurisdiction_server (etc.) at request
    start, close at request end. Simpler than persistent connections, and
    matches the serverless lifecycle on Vercel anyway.
  - Hard cap MAX_TOOL_CALLS=10 per CLAUDE.md. Bounds worst-case cost and
    prevents runaway loops.
  - System prompt instructs Sonnet to ALWAYS use tools for jurisdiction
    questions — never reason from training data.
  - Audit log is written once per request, inside run_stream(), right before
    the final 'done' event. run() does not log separately (would double-log).
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel

from agent.audit import log_request
from agent.classifier import ClassificationResponse, classify

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)


# =============================================================================
# Configuration
# =============================================================================

ORCHESTRATOR_MODEL = "claude-sonnet-4-5-20250929"
ORCHESTRATOR_MAX_TOKENS = 2048
MAX_TOOL_CALLS = 10  # Hard cap per CLAUDE.md.

# Sonnet 4.5 pricing (per 1M tokens, as of 2026-05).
SONNET_INPUT_PER_MTOK = 3.00
SONNET_OUTPUT_PER_MTOK = 15.00

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# MCP server registry. agent_name → how to launch.
# Add hris (Phase 4) and policy (Phase 5) here; orchestrator code does not change.
MCP_SERVERS: dict[str, StdioServerParameters] = {
    "jurisdiction": StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.jurisdiction_server"],
        cwd=str(PROJECT_ROOT),
    ),
    "hris": StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.hris_server"],
        cwd=str(PROJECT_ROOT),
    ),
    # "policy": StdioServerParameters(...) # Phase 5
}


SYSTEM_PROMPT = """You are an HR Operations Agent. You help HR professionals with \
jurisdiction-specific labor-law questions, policy questions, and employee record \
lookups.

CRITICAL RULES:
1. For ANY question about labor law, notice periods, severance, terminations, \
or country-specific HR rules — you MUST call the jurisdiction tools. Never \
answer compliance questions from your training data. Compliance is deterministic, \
auditable, and lives in the rules engine.
2. If the user mentions an employee by name or ID, look them up via the HRIS \
tools before answering (when HRIS is available).
3. If the user asks about company policy or process, query the policy tools.
4. If the jurisdiction is not covered (the tool returns covered=false), tell \
the user the engine doesn't have rules for that country and recommend legal \
review. Do not infer rules from elsewhere.
5. Be concise. HR pros are busy. Lead with the answer, then the supporting \
detail.
6. Always cite the statute or section returned by the tool, in parentheses.
7. When validating a proposed action and the tool returns compliant=false, \
explain WHAT is non-compliant and HOW to fix it (e.g., "increase notice to X \
days" or "obtain Aufsichtsbehörde consent")."""


# =============================================================================
# Response shape (for run() wrapper)
# =============================================================================


class OrchestratorResponse(BaseModel):
    """End-to-end result of one request — produced by run() after consuming run_stream()."""

    session_id: str
    final_text: str
    agents_invoked: list[str]
    tool_calls: list[dict[str, Any]]
    escalated: bool
    cost_usd: float
    tool_call_count: int
    truncated: bool


# =============================================================================
# Helpers
# =============================================================================


def _compute_sonnet_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000) * SONNET_INPUT_PER_MTOK + (
        output_tokens / 1_000_000
    ) * SONNET_OUTPUT_PER_MTOK


def _mcp_tools_to_anthropic(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    """Convert MCP tool definitions to Anthropic's tool format."""
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.inputSchema,
        }
        for t in mcp_tools
    ]


_anthropic_client: AsyncAnthropic | None = None


def _get_anthropic() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client


# =============================================================================
# Main entry point — streaming generator
# =============================================================================


async def run_stream(
    user_input: str,
    session_id: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Process one HR request, yielding events as they occur.

    Event shapes:
      {"type": "classifier", "agents_required": [...], "complexity": "...", "entities": {...}}
      {"type": "tool_use", "id": "...", "tool": "...", "args": {...}}
      {"type": "tool_result", "id": "...", "tool": "...", "is_error": bool, "result": "..."}
      {"type": "text_delta", "text": "..."}
      {"type": "done", "session_id": "...", "agents_invoked": [...], "cost_usd": float,
       "tool_call_count": int, "truncated": bool, "escalated": False}
      {"type": "error", "message": "..."}  (terminal — followed by no further events)
    """
    session_id = session_id or str(uuid.uuid4())
    tool_calls_log: list[dict[str, Any]] = []
    total_cost = 0.0
    truncated = False
    tool_iteration = 0
    available_agents: list[str] = []

    try:
        # ---------- 1. Classify ----------
        classification: ClassificationResponse = classify(user_input)
        total_cost += classification.cost_usd
        agents_required = classification.result.agents_required

        # Filter to what we have configured.
        available_agents = [a for a in agents_required if a in MCP_SERVERS]
        missing_agents = [a for a in agents_required if a not in MCP_SERVERS]

        yield {
            "type": "classifier",
            "agents_required": agents_required,
            "agents_available": available_agents,
            "agents_missing": missing_agents,
            "complexity": classification.result.complexity,
            "entities": classification.result.entities.model_dump(),
        }

        # ---------- 2. Connect to MCP servers + aggregate tools ----------
        async with AsyncExitStack() as stack:
            sessions: dict[str, ClientSession] = {}
            for agent_name in available_agents:
                params = MCP_SERVERS[agent_name]
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                sessions[agent_name] = session

            anthropic_tools: list[dict[str, Any]] = []
            tool_to_session: dict[str, ClientSession] = {}
            for agent_name, session in sessions.items():
                tools_response = await session.list_tools()
                anthropic_tools.extend(_mcp_tools_to_anthropic(tools_response.tools))
                for t in tools_response.tools:
                    tool_to_session[t.name] = session

            # ---------- 3. Tool-call loop ----------
            client = _get_anthropic()
            messages: list[dict[str, Any]] = [
                {"role": "user", "content": user_input}
            ]
            system_prompt = SYSTEM_PROMPT
            if missing_agents:
                system_prompt += (
                    f"\n\nNOTE: The classifier requested these agents, but they are "
                    f"not yet available in this phase: {missing_agents}. "
                    f"Answer what you can with the tools you have, and explicitly "
                    f"acknowledge what you cannot do."
                )

            while True:
                # Stream this Sonnet turn — yield text_delta events as tokens arrive.
                kwargs: dict[str, Any] = {
                    "model": ORCHESTRATOR_MODEL,
                    "max_tokens": ORCHESTRATOR_MAX_TOKENS,
                    "system": system_prompt,
                    "messages": messages,
                }
                if anthropic_tools:
                    kwargs["tools"] = anthropic_tools

                async with client.messages.stream(**kwargs) as stream:
                    async for event in stream:
                        if (
                            event.type == "content_block_delta"
                            and event.delta.type == "text_delta"
                        ):
                            yield {"type": "text_delta", "text": event.delta.text}
                    final_message = await stream.get_final_message()

                total_cost += _compute_sonnet_cost(
                    final_message.usage.input_tokens,
                    final_message.usage.output_tokens,
                )

                if final_message.stop_reason == "end_turn":
                    break

                if final_message.stop_reason == "tool_use":
                    # Append assistant turn with full content (must include tool_use blocks).
                    messages.append(
                        {"role": "assistant", "content": final_message.content}
                    )

                    tool_result_blocks = []
                    hit_cap = False
                    for block in final_message.content:
                        if block.type != "tool_use":
                            continue

                        tool_iteration += 1
                        tool_name = block.name
                        tool_args = block.input
                        tool_id = block.id

                        yield {
                            "type": "tool_use",
                            "id": tool_id,
                            "tool": tool_name,
                            "args": tool_args,
                        }

                        session = tool_to_session.get(tool_name)
                        if session is None:
                            result_content = json.dumps(
                                {"error": f"Tool {tool_name} not available in this phase."}
                            )
                            is_error = True
                        else:
                            try:
                                result = await session.call_tool(tool_name, tool_args)
                                result_content = "".join(
                                    c.text for c in result.content if hasattr(c, "text")
                                )
                                is_error = bool(result.isError)
                            except Exception as e:  # noqa: BLE001
                                result_content = json.dumps(
                                    {"error": f"{type(e).__name__}: {e}"}
                                )
                                is_error = True

                        tool_calls_log.append(
                            {
                                "tool": tool_name,
                                "args": tool_args,
                                "result": result_content,
                                "is_error": is_error,
                            }
                        )

                        yield {
                            "type": "tool_result",
                            "id": tool_id,
                            "tool": tool_name,
                            "is_error": is_error,
                            "result": result_content,
                        }

                        tool_result_blocks.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": result_content,
                                "is_error": is_error,
                            }
                        )

                        if tool_iteration >= MAX_TOOL_CALLS:
                            hit_cap = True
                            break

                    messages.append({"role": "user", "content": tool_result_blocks})

                    if hit_cap:
                        truncated = True
                        # Force a final non-tool synthesis turn.
                        async with client.messages.stream(
                            model=ORCHESTRATOR_MODEL,
                            max_tokens=ORCHESTRATOR_MAX_TOKENS,
                            system=system_prompt
                            + "\n\nYou have reached the tool-call limit. Synthesize a final answer with the information you have.",
                            messages=messages,
                        ) as final_stream:
                            async for event in final_stream:
                                if (
                                    event.type == "content_block_delta"
                                    and event.delta.type == "text_delta"
                                ):
                                    yield {"type": "text_delta", "text": event.delta.text}
                            final_synth = await final_stream.get_final_message()
                        total_cost += _compute_sonnet_cost(
                            final_synth.usage.input_tokens,
                            final_synth.usage.output_tokens,
                        )
                        break

                    # otherwise: continue the loop, another tool call cycle
                    continue

                # Unexpected stop_reason — bail.
                break

    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
        # Still try to log the request as failed, then return.
        log_request(
            session_id=session_id,
            user_input=user_input,
            agents_invoked=available_agents,
            tool_calls=tool_calls_log,
            resolution="error",
            escalated=False,
            cost_usd=total_cost,
        )
        return

    # ---------- 4. Audit log + done event ----------
    log_request(
        session_id=session_id,
        user_input=user_input,
        agents_invoked=available_agents,
        tool_calls=tool_calls_log,
        resolution="auto" if not truncated else "truncated",
        escalated=False,
        cost_usd=total_cost,
    )

    yield {
        "type": "done",
        "session_id": session_id,
        "agents_invoked": available_agents,
        "cost_usd": round(total_cost, 6),
        "tool_call_count": tool_iteration,
        "truncated": truncated,
        "escalated": False,
    }


# =============================================================================
# Non-streaming wrapper
# =============================================================================


async def run(
    user_input: str,
    session_id: str | None = None,
) -> OrchestratorResponse:
    """Non-streaming variant. Consumes run_stream() and aggregates into one response.

    Used by the CLI and the non-streaming /api/chat endpoint.
    """
    final_text_parts: list[str] = []
    agents_invoked: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    cost_usd = 0.0
    resolved_session_id = session_id or ""
    tool_count = 0
    truncated = False
    escalated = False

    pending_tool_calls: dict[str, dict[str, Any]] = {}

    async for event in run_stream(user_input, session_id):
        etype = event.get("type")
        if etype == "text_delta":
            final_text_parts.append(event["text"])
        elif etype == "tool_use":
            pending_tool_calls[event["id"]] = {
                "tool": event["tool"],
                "args": event["args"],
            }
        elif etype == "tool_result":
            entry = pending_tool_calls.pop(event["id"], {"tool": event["tool"], "args": {}})
            entry["result"] = event["result"]
            entry["is_error"] = event["is_error"]
            tool_calls.append(entry)
        elif etype == "done":
            resolved_session_id = event["session_id"]
            agents_invoked = event["agents_invoked"]
            cost_usd = event["cost_usd"]
            tool_count = event["tool_call_count"]
            truncated = event["truncated"]
            escalated = event["escalated"]
        elif etype == "error":
            final_text_parts.append(f"\n\n[error] {event['message']}")

    return OrchestratorResponse(
        session_id=resolved_session_id,
        final_text="".join(final_text_parts).strip(),
        agents_invoked=agents_invoked,
        tool_calls=tool_calls,
        escalated=escalated,
        cost_usd=cost_usd,
        tool_call_count=tool_count,
        truncated=truncated,
    )


# =============================================================================
# CLI — direct test runner
# =============================================================================

if __name__ == "__main__":
    import asyncio

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    query = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else "What's the minimum notice period to terminate someone in Germany?"
    )

    print(f"USER: {query}\n")

    async def _main() -> None:
        # Stream events live to stdout so the CLI shows what the SSE endpoint will.
        print("AGENT: ", end="", flush=True)
        meta: dict[str, Any] = {}
        async for event in run_stream(query):
            if event["type"] == "text_delta":
                print(event["text"], end="", flush=True)
            elif event["type"] == "tool_use":
                print(
                    f"\n[tool] → {event['tool']}({json.dumps(event['args'], ensure_ascii=False)})",
                    flush=True,
                )
                print("AGENT: ", end="", flush=True)
            elif event["type"] == "tool_result":
                # Brief — full result is too noisy for CLI.
                pass
            elif event["type"] == "done":
                meta = event
            elif event["type"] == "error":
                print(f"\n[error] {event['message']}", flush=True)

        print("\n\n---")
        print(f"session_id:      {meta.get('session_id')}")
        print(f"agents_invoked:  {meta.get('agents_invoked')}")
        print(f"tool_call_count: {meta.get('tool_call_count')}")
        print(f"cost_usd:        ${meta.get('cost_usd', 0):.5f}")
        print(f"truncated:       {meta.get('truncated')}")

    asyncio.run(_main())
