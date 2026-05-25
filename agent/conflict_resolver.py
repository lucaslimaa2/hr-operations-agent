"""
Conflict resolver — Haiku-based write gating.

Sits between Sonnet's intent ("I want to call update_employment_status") and
the actual mutation. Receives the request context (user input, classifier
routing, prior tool calls, proposed write) and returns a structured verdict:

    {
      "resolution": "auto" | "escalate",
      "action_summary": "...",
      "escalation_brief": {
        "conflict": "...",
        "risk_level": "low" | "medium" | "high",
        "recommendation": "...",
        "question_for_hr": "..."
      }
    }

Design choices:
  - Haiku (not Sonnet) for cost discipline. Same model as the classifier.
  - Structured output via forced tool call — schema-guaranteed JSON.
  - Pydantic validates the result as a defense-in-depth check.
  - When resolution='auto', escalation_brief is None.
  - Only fires when the orchestrator detects a write-tool invocation. Reads
    pass through unchanged.

Public surface:
  - resolve(context: ResolveContext) -> ResolveResponse
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

RESOLVER_MODEL = "claude-haiku-4-5-20251001"
RESOLVER_MAX_TOKENS = 512

# Haiku 4.5 pricing (matches classifier.py).
HAIKU_INPUT_PER_MTOK = 1.00
HAIKU_OUTPUT_PER_MTOK = 5.00
HAIKU_CACHE_WRITE_PER_MTOK = 1.25
HAIKU_CACHE_READ_PER_MTOK = 0.10


# =============================================================================
# Schema — what the resolver returns
# =============================================================================


class EscalationBrief(BaseModel):
    """Structured brief presented to HR when a write is escalated.

    Shape comes from CLAUDE.md. All four fields are required when the resolver
    returns 'escalate' — they together constitute a complete handoff to a human.
    """

    conflict: str = Field(
        description=(
            "1-2 sentence description of what's blocking auto-execution. "
            "What's the conflict, contradiction, or risk that requires "
            "human judgment? Be specific — cite the rule, the threshold, "
            "or the protected category by name."
        )
    )
    risk_level: Literal["low", "medium", "high"] = Field(
        description=(
            "Severity of getting this wrong. 'low' = minor procedural; "
            "'medium' = compliance or money exposure; "
            "'high' = legal liability, protected category, mass-impact, irreversible."
        )
    )
    recommendation: str = Field(
        description=(
            "What HR should DO. Concrete next steps (e.g., 'extend notice to 60 days', "
            "'obtain Aufsichtsbehörde consent', 'document Art. 482 grounds'). "
            "Not 'consult legal' — that's the lazy answer."
        )
    )
    question_for_hr: str = Field(
        description=(
            "The specific clarifying question whose answer would resolve the "
            "uncertainty. Phrased as a question. e.g., 'Has the works council "
            "been notified under BetrVG §102?' — not 'Please review.'"
        )
    )


class ResolverResult(BaseModel):
    """The resolver's decision."""

    resolution: Literal["auto", "escalate"] = Field(
        description=(
            "'auto' = the proposed write is safe to execute. 'escalate' = "
            "the write must NOT fire; an escalation brief is returned instead."
        )
    )
    action_summary: str = Field(
        description=(
            "Short, factual one-sentence description of what was about to happen "
            "(e.g., 'Terminate emp_004 (Sarah Chen, DE) without cause with 14 days notice')."
        )
    )
    escalation_brief: EscalationBrief | None = Field(
        default=None,
        description=("Required when resolution='escalate'. Omit (null) when resolution='auto'."),
    )


class ResolveContext(BaseModel):
    """Input context passed to the resolver."""

    user_input: str
    agents_invoked: list[str]
    tool_calls: list[dict[str, Any]]  # full log: [{tool, args, result}]
    proposed_tool: str  # the write tool Sonnet wants to call
    proposed_args: dict[str, Any]


class ResolveResponse(BaseModel):
    """Resolver output + telemetry."""

    result: ResolverResult
    input_tokens: int
    output_tokens: int
    cost_usd: float


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """You are the conflict resolver for an HR Operations Agent. \
You sit between the AI agent's decision to perform a write (mutation on the \
employee record system) and the actual mutation. Your job is to gate that \
write: either approve it for auto-execution or escalate it to HR with a \
structured brief.

You are NOT executing the write. You are NOT generating user-facing text. \
You are deciding whether the proposed write is safe, and if not, what HR \
needs to know.

Decision principles:

ESCALATE when:
  - A jurisdiction tool already returned compliant=false. Do not approve a \
write that has been flagged non-compliant.
  - The write would terminate an employee in a protected category (pregnancy, \
union role, parental leave, severely disabled, accident-leave return, etc.).
  - The action triggers mass-layoff thresholds (federal WARN, Cal-WARN, \
Massenentlassung under KSchG §17, BR collective dismissal per STF RE 999.435).
  - The relevant jurisdiction is not covered by the engine (the tool returned \
covered=false). Never approve a write into an unknown jurisdiction.
  - Multiple agent outputs contradict each other (e.g., policy says one thing, \
jurisdiction requires another).
  - Required prior steps are missing (e.g., Betriebsrat consultation, FR \
entretien préalable, BR sindicato negotiation for collective dismissal).
  - The action is irreversible AND there's any uncertainty about correctness.

AUTO-APPROVE when:
  - The relevant jurisdiction tools already confirmed compliant=true.
  - No protected category applies.
  - All procedural prerequisites visible in the tool history have been met.
  - The action is reversible (e.g., status change to 'on_leave').
  - The user's intent is clear from the input.

Risk level guidance:
  - 'low' — procedural or documentation, easily fixable
  - 'medium' — compliance or financial exposure, requires careful action
  - 'high' — legal liability, protected category, mass-impact, irreversible

You MUST call the `submit_resolution` tool exactly once. When resolution='auto', \
omit the escalation_brief (it's null). When resolution='escalate', the \
escalation_brief is REQUIRED and all four sub-fields must be filled."""


# =============================================================================
# Tool definition — forced structured output
# =============================================================================

RESOLVE_TOOL = {
    "name": "submit_resolution",
    "description": (
        "Submit the resolver verdict. Call exactly once. Set escalation_brief "
        "to null when resolution='auto'; provide all four sub-fields when "
        "resolution='escalate'."
    ),
    "input_schema": ResolverResult.model_json_schema(),
}


# =============================================================================
# Cost
# =============================================================================


def _compute_cost(
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    return (
        input_tokens * HAIKU_INPUT_PER_MTOK
        + cache_creation_tokens * HAIKU_CACHE_WRITE_PER_MTOK
        + cache_read_tokens * HAIKU_CACHE_READ_PER_MTOK
        + output_tokens * HAIKU_OUTPUT_PER_MTOK
    ) / 1_000_000


# =============================================================================
# Client
# =============================================================================

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


# =============================================================================
# Public API
# =============================================================================


def _render_tool_calls(tool_calls: list[dict[str, Any]]) -> str:
    """Render the prior tool calls + results as text the resolver can read.

    Truncates long tool results to keep the prompt bounded. The resolver doesn't
    need the entire policy document text — it needs the structured fields.
    """
    if not tool_calls:
        return "  (no prior tool calls)"
    lines = []
    for i, tc in enumerate(tool_calls, 1):
        tool = tc.get("tool", "?")
        args = json.dumps(tc.get("args", {}), ensure_ascii=False)
        result = tc.get("result", "")
        if isinstance(result, str) and len(result) > 800:
            result = result[:800] + " …[truncated]"
        is_err = tc.get("is_error")
        err_tag = " [ERROR]" if is_err else ""
        lines.append(f"  {i}. {tool}({args}){err_tag}\n     → {result}")
    return "\n".join(lines)


def resolve(context: ResolveContext) -> ResolveResponse:
    """Gate a proposed write. Returns auto or escalate verdict."""
    client = _get_client()

    user_message = (
        f"USER INPUT (original request):\n  {context.user_input}\n\n"
        f"AGENTS INVOKED so far:\n  {context.agents_invoked}\n\n"
        f"TOOL CALLS so far (with results):\n"
        f"{_render_tool_calls(context.tool_calls)}\n\n"
        f"PROPOSED WRITE (this is what the agent wants to execute next):\n"
        f"  Tool: {context.proposed_tool}\n"
        f"  Args: {json.dumps(context.proposed_args, ensure_ascii=False)}\n\n"
        "Decide: auto or escalate. Call submit_resolution exactly once."
    )

    # Cache breakpoint on the tool — system + tool schema cached as one block.
    cached_tool = {**RESOLVE_TOOL, "cache_control": {"type": "ephemeral"}}

    response = client.messages.create(
        model=RESOLVER_MODEL,
        max_tokens=RESOLVER_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[cached_tool],
        tool_choice={"type": "tool", "name": "submit_resolution"},
        messages=[{"role": "user", "content": user_message}],
    )

    tool_blocks = [b for b in response.content if b.type == "tool_use"]
    if not tool_blocks:
        raise ValueError(f"Resolver did not call submit_resolution. Response: {response.content}")

    parsed = ResolverResult.model_validate(tool_blocks[0].input)

    # Defense in depth: if resolution=escalate but brief is missing, force a fail-safe.
    if parsed.resolution == "escalate" and parsed.escalation_brief is None:
        parsed = ResolverResult(
            resolution="escalate",
            action_summary=parsed.action_summary,
            escalation_brief=EscalationBrief(
                conflict="Resolver returned escalate without a brief.",
                risk_level="high",
                recommendation="Hold the action. Manually review before proceeding.",
                question_for_hr="Why did the resolver escalate without a brief?",
            ),
        )

    usage = response.usage
    cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cost = _compute_cost(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_creation_tokens=cache_creation,
        cache_read_tokens=cache_read,
    )

    return ResolveResponse(
        result=parsed,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=cost,
    )


# =============================================================================
# CLI test
# =============================================================================

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Simulated context: Sarah Chen (DE, 77mo) 2-week notice — should escalate.
    ctx = ResolveContext(
        user_input="Terminate Sarah Chen with 2 weeks notice.",
        agents_invoked=["hris", "jurisdiction"],
        tool_calls=[
            {
                "tool": "search_employees",
                "args": {"name": "Sarah Chen"},
                "result": '{"matches": [{"id": "emp_004", "name": "Sarah Chen", "country": "DE", "employment_type": "full-time", "tenure_months": 77, "employment_status": "active"}]}',  # noqa: E501
            },
            {
                "tool": "validate_action",
                "args": {
                    "action": "terminate_without_cause",
                    "country": "DE",
                    "context": {
                        "employment_type": "full-time",
                        "tenure_months": 77,
                        "notice_days_given": 14,
                    },
                },
                "result": '{"compliant": false, "reason": "Proposed 14 days notice is BELOW the statutory minimum of 60 days", "citation": "BGB §622(2) Nr. 2"}',  # noqa: E501
            },
        ],
        proposed_tool="update_employment_status",
        proposed_args={
            "employee_id": "emp_004",
            "status": "terminated",
            "effective_date": "2026-06-08",
        },
    )

    print("Test 1 — Sarah Chen non-compliant termination (should escalate):\n")
    resp = resolve(ctx)
    print(json.dumps(resp.model_dump(), indent=2, ensure_ascii=False))
