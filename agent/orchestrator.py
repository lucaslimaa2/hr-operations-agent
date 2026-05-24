"""
Orchestrator — Sonnet-based agent loop with MCP client.

Pipeline per request:

    classifier (Haiku, fast routing)
        ↓ agents_required
    orchestrator:
        ↓ connect to MCP servers for agents_required
        ↓ aggregate tools across servers
        ↓ Sonnet tool-call loop (capped at MAX_TOOL_CALLS)
        ↓ final text response
    audit_log writer (Supabase)
        ↓ session_id, user_input, agents_invoked, tool_calls, cost_usd

Design notes:
  - Per-request MCP subprocess. Spawn jurisdiction_server (etc.) at request
    start, close at request end. Simpler than persistent connections, and
    matches the serverless lifecycle on Vercel anyway.
  - Hard cap MAX_TOOL_CALLS=10 per CLAUDE.md. Bounds worst-case cost and
    prevents runaway loops.
  - System prompt instructs Sonnet to ALWAYS use tools for jurisdiction
    questions — never reason from training data. This enforces the
    deterministic-compliance principle from the LLM side; the rules engine
    enforces it from the data side.
  - Cost tracked per Anthropic call (input/output/cache tokens) and summed
    into the per-request total alongside classifier cost.

Public API:
    async run(user_input: str, session_id: str | None = None) -> OrchestratorResponse
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from anthropic import Anthropic
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
MAX_TOOL_CALLS = 10  # Hard cap per CLAUDE.md — prevents runaway loops.

# Sonnet 4.5 pricing (per 1M tokens, as of 2026-05).
SONNET_INPUT_PER_MTOK = 3.00
SONNET_OUTPUT_PER_MTOK = 15.00


# Project root — used when launching MCP servers as subprocesses so they
# find their own imports.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# MCP server registry. agent_name → how to launch.
# Add hris (Phase 4) and policy (Phase 5) here; orchestrator code does not change.
MCP_SERVERS: dict[str, StdioServerParameters] = {
    "jurisdiction": StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_servers.jurisdiction_server"],
        cwd=str(PROJECT_ROOT),
    ),
    # "hris": StdioServerParameters(...)   # Phase 4
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
# Response shape
# =============================================================================


class OrchestratorResponse(BaseModel):
    """End-to-end result of one request."""

    session_id: str
    final_text: str
    agents_invoked: list[str]
    tool_calls: list[dict[str, Any]]  # full log: [{tool, args, result}]
    escalated: bool  # always False in Phase 3 — conflict resolver lands in Phase 6
    cost_usd: float  # classifier + orchestrator combined
    tool_call_count: int
    truncated: bool  # True if 10-call cap hit before end_turn


# =============================================================================
# Helpers
# =============================================================================


def _compute_sonnet_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000) * SONNET_INPUT_PER_MTOK + (
        output_tokens / 1_000_000
    ) * SONNET_OUTPUT_PER_MTOK


def _mcp_tools_to_anthropic(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    """Convert MCP tool definitions to Anthropic's tool format.

    MCP gives us: {name, description, inputSchema}
    Anthropic wants: {name, description, input_schema}
    """
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.inputSchema,
        }
        for t in mcp_tools
    ]


def _extract_final_text(content: list[Any]) -> str:
    """Pull the assistant's text out of an Anthropic response.content list."""
    return "".join(block.text for block in content if block.type == "text").strip()


_anthropic_client: Anthropic | None = None


def _get_anthropic() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client


# =============================================================================
# Main entry point
# =============================================================================


async def run(
    user_input: str,
    session_id: str | None = None,
) -> OrchestratorResponse:
    """Process one HR request end-to-end.

    Steps:
      1. Classify with Haiku → routing decision.
      2. Connect to the MCP servers in agents_required (that we have configured).
      3. Aggregate tools across servers.
      4. Sonnet tool-call loop (capped at MAX_TOOL_CALLS).
      5. Write audit_log row.
      6. Return OrchestratorResponse.
    """
    session_id = session_id or str(uuid.uuid4())

    # ---------- 1. Classify ----------
    classification: ClassificationResponse = classify(user_input)
    agents_required = classification.result.agents_required

    # Phase 3: only jurisdiction server exists. Filter to what we have configured.
    available_agents = [a for a in agents_required if a in MCP_SERVERS]
    missing_agents = [a for a in agents_required if a not in MCP_SERVERS]

    # ---------- 2. Connect to MCP servers + aggregate tools ----------
    tool_calls_log: list[dict[str, Any]] = []
    total_cost = classification.cost_usd
    truncated = False

    async with AsyncExitStack() as stack:
        sessions: dict[str, ClientSession] = {}
        for agent_name in available_agents:
            params = MCP_SERVERS[agent_name]
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            sessions[agent_name] = session

        # Aggregate tools + map each tool name → owning session
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
        # Inform Sonnet which agents the classifier said are missing, so it can
        # be honest with the user (e.g., "I can't look up that employee yet —
        # HRIS isn't connected in this phase").
        system_prompt = SYSTEM_PROMPT
        if missing_agents:
            system_prompt += (
                f"\n\nNOTE: The classifier requested these agents, but they are "
                f"not yet available in this phase: {missing_agents}. "
                f"Answer what you can with the tools you have, and explicitly "
                f"acknowledge what you cannot do (e.g., 'I can't look up the "
                f"specific employee record yet — HRIS will be available in a later phase')."
            )

        tool_iteration = 0
        final_text = ""

        while tool_iteration < MAX_TOOL_CALLS:
            response = client.messages.create(
                model=ORCHESTRATOR_MODEL,
                max_tokens=ORCHESTRATOR_MAX_TOKENS,
                system=system_prompt,
                tools=anthropic_tools if anthropic_tools else None,
                messages=messages,
            )

            total_cost += _compute_sonnet_cost(
                response.usage.input_tokens, response.usage.output_tokens
            )

            if response.stop_reason == "end_turn":
                final_text = _extract_final_text(response.content)
                break

            if response.stop_reason == "tool_use":
                # Append assistant turn (must include the tool_use blocks)
                messages.append({"role": "assistant", "content": response.content})

                # Execute each tool_use block
                tool_result_blocks = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    tool_iteration += 1
                    tool_name = block.name
                    tool_args = block.input

                    session = tool_to_session.get(tool_name)
                    if session is None:
                        result_content = json.dumps(
                            {"error": f"Tool {tool_name} not available in this phase."}
                        )
                        is_error = True
                    else:
                        try:
                            result = await session.call_tool(tool_name, tool_args)
                            # MCP returns content blocks; serialize them.
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

                    tool_result_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_content,
                            "is_error": is_error,
                        }
                    )

                    if tool_iteration >= MAX_TOOL_CALLS:
                        break

                messages.append({"role": "user", "content": tool_result_blocks})

                if tool_iteration >= MAX_TOOL_CALLS:
                    truncated = True
                    # Force a final synthesis turn without tools
                    final_response = client.messages.create(
                        model=ORCHESTRATOR_MODEL,
                        max_tokens=ORCHESTRATOR_MAX_TOKENS,
                        system=system_prompt
                        + "\n\nYou have reached the tool-call limit. Synthesize a final answer with the information you have.",
                        messages=messages,
                    )
                    total_cost += _compute_sonnet_cost(
                        final_response.usage.input_tokens,
                        final_response.usage.output_tokens,
                    )
                    final_text = _extract_final_text(final_response.content)
                    break

                # Continue loop — more tool calls expected
                continue

            # Unexpected stop_reason — bail with what we have.
            final_text = _extract_final_text(response.content) or (
                f"[orchestrator] Unexpected stop_reason: {response.stop_reason}"
            )
            break
        else:
            # While-loop exited without break (shouldn't happen given the
            # truncation path above, but defense-in-depth)
            truncated = True
            final_text = final_text or "[orchestrator] Tool-call loop exhausted."

    # ---------- 4. Audit log ----------
    log_request(
        session_id=session_id,
        user_input=user_input,
        agents_invoked=available_agents,
        tool_calls=tool_calls_log,
        resolution="auto" if not truncated else "truncated",
        escalated=False,  # Phase 6: conflict resolver may set this True
        cost_usd=total_cost,
    )

    return OrchestratorResponse(
        session_id=session_id,
        final_text=final_text,
        agents_invoked=available_agents,
        tool_calls=tool_calls_log,
        escalated=False,
        cost_usd=total_cost,
        tool_call_count=tool_iteration,
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
    resp = asyncio.run(run(query))
    print(f"AGENT: {resp.final_text}\n")
    print("---")
    print(f"agents_invoked:  {resp.agents_invoked}")
    print(f"tool_call_count: {resp.tool_call_count}")
    print(f"cost_usd:        ${resp.cost_usd:.5f}")
    print(f"truncated:       {resp.truncated}")
    if resp.tool_calls:
        print(f"\ntool_calls:")
        for tc in resp.tool_calls:
            print(f"  - {tc['tool']}({json.dumps(tc['args'], ensure_ascii=False)})")
