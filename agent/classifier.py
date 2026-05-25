"""
Intent classifier — Haiku-based router.

Takes a user's natural-language HR request and returns a structured routing
decision: which MCP servers to invoke, whether multi-agent conflict is
possible, whether a write/system-action is implied, and extracted entities.

Design:
  - Haiku 4.5 (not Sonnet) for cost discipline. Routing decisions are simple;
    using Sonnet here would 3-5x the cost with no quality gain.
  - Output schema is enforced via Anthropic's tool-calling: we define a single
    "route" tool whose input schema is the routing decision shape, and force
    Claude to call it. Output is guaranteed to match the schema.
  - Pydantic validates the result as a defense-in-depth check.

Public surface:
  - classify(user_input: str) -> ClassifierResult
  - cost-tracking returned alongside the result for audit-log logging
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# override=True so .env wins over shell-set empty values (common gotcha on Windows).
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

# Haiku is the right choice for routing — fast, cheap, plenty smart for this.
CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"

# Hard cap on output tokens. Classifier output is tiny JSON — 256 is generous.
CLASSIFIER_MAX_TOKENS = 256


# =============================================================================
# Schema — what the classifier returns
# =============================================================================


class ClassifierEntities(BaseModel):
    """Entities extracted from the user input. All optional — present only if
    the model could identify them."""

    employee_name: str | None = Field(
        default=None,
        description="Full name of the employee mentioned, if any. e.g. 'João Silva', 'Sarah Chen'.",
    )
    employee_id: str | None = Field(
        default=None,
        description="Employee ID if the user provided one explicitly, e.g. 'emp_001'.",
    )
    country: str | None = Field(
        default=None,
        description=(
            "ISO-ish country code mentioned or implied. Use 'BR' for Brazil, 'DE' for Germany, "
            "'US-CA' for California, 'US-TX' for Texas, etc. Null if the user did not specify "
            "a country and one cannot be inferred."
        ),
    )
    action_type: str | None = Field(
        default=None,
        description=(
            "What the user wants to do. One of: 'termination_query' (asking about rules), "
            "'process_termination' (execute one), 'severance_query', 'policy_query', "
            "'conversion' (e.g. contractor-to-employee), 'general_question', or 'other'."
        ),
    )


class ClassifierResult(BaseModel):
    """Routing decision from the classifier."""

    agents_required: list[Literal["jurisdiction", "hris", "policy"]] = Field(
        description=(
            "Which MCP servers the orchestrator must invoke. "
            "'jurisdiction' for labor-law/termination rules questions; "
            "'hris' for anything about a specific employee (name, ID, or status); "
            "'policy' for company-policy questions (offboarding process, approval matrices, etc.). "
            "List is order-independent. May be multiple."
        )
    )
    conflict_possible: bool = Field(
        description=(
            "True if multiple agents are required AND their outputs might conflict "
            "(e.g. policy says X, jurisdiction says Y). False for single-agent requests "
            "or independent multi-agent reads."
        )
    )
    requires_system_action: bool = Field(
        description=(
            "True if the user is asking for a write/mutation (e.g. 'process termination', "
            "'update status', 'convert to FTE'). False for pure read questions ('what is the rule')."
        )
    )
    complexity: Literal["simple", "moderate", "complex"] = Field(
        description=(
            "'simple' = single-agent read with no entities to resolve; "
            "'moderate' = multi-agent OR requires entity resolution OR requires a system action; "
            "'complex' = multi-agent AND conflict_possible AND/OR system action."
        )
    )
    entities: ClassifierEntities = Field(description="Entities extracted from the user input.")


# Cost-tracking sidecar (not in the schema returned by Claude — added by classify()).
class ClassificationResponse(BaseModel):
    """Result + telemetry, returned by classify()."""

    result: ClassifierResult
    input_tokens: int
    output_tokens: int
    cost_usd: float


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """You are the routing classifier for an HR Operations Agent.

Your job: given a user's HR request in natural language, decide which downstream
servers should handle it and extract any entities.

The downstream servers available are:
  - jurisdiction: labor-law rules engine (notice periods, severance, compliance) \
for BR, DE, US-CA. Use for any question about termination rules, what's allowed, \
notice/severance amounts, or country-specific labor law.
  - hris: employee records (name lookup, employment status, country, tenure). \
Use whenever a specific employee is mentioned by name or ID.
  - policy: company HR policies (offboarding process, approval matrices, comp \
bands, PIPs, contractor conversion process). Use for "what's our policy on...", \
"what are the steps for...", "who needs to approve...".

Routing principles:
  - If the user asks an abstract rule question with no employee ("what's the \
notice in Germany?"), just jurisdiction.
  - If the user mentions a specific employee ("terminate João"), at minimum \
hris is required to look them up.
  - If the user proposes an action ("terminate X with Y notice"), both hris \
(to confirm the employee) AND jurisdiction (to validate the action) are required.
  - If the user asks about process/policy ("how do we offboard", "who approves"), \
policy is required.
  - Conversion scenarios (contractor → FTE, level change) ALWAYS require all three. \
A contractor-to-employee conversion triggers (a) HRIS lookup of the contractor, \
(b) policy for the approval matrix and process, AND (c) jurisdiction because the \
target employment type carries labor-law obligations (e.g. BR PJ → CLT activates \
FGTS, 13º, aviso prévio, férias). Never omit jurisdiction from a conversion.

Conflict possibility:
  - True only when multiple servers might return contradictory or competing \
information that needs reconciliation (e.g. policy says one thing, jurisdiction \
requires another).
  - For simple multi-agent reads where outputs are complementary, set False.

System action (requires_system_action):
  - True if the user is asking to PERFORM something (terminate, update, convert).
  - False for pure questions (what is, how much, what are our steps).

You MUST call the `route_request` tool exactly once with your decision. Do not respond in free text."""


# =============================================================================
# Tool definition — what we force Claude to call
# =============================================================================

# Build the input_schema from the Pydantic model. This is the schema Claude
# sees — every field's description above becomes a docstring for the model.
ROUTE_TOOL = {
    "name": "route_request",
    "description": (
        "Submit the routing decision for the user's HR request. You MUST call this exactly once per request."
    ),
    "input_schema": ClassifierResult.model_json_schema(),
}


# =============================================================================
# Cost calculation
# =============================================================================

# Haiku 4.5 pricing (per million tokens, as of 2026-05).
HAIKU_INPUT_PER_MTOK = 1.00
HAIKU_OUTPUT_PER_MTOK = 5.00
HAIKU_CACHE_WRITE_PER_MTOK = 1.25  # 1.25× input — first call writes the cache
HAIKU_CACHE_READ_PER_MTOK = 0.10  # 0.10× input — cache hits cost ~10%


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
# Public API
# =============================================================================

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def classify(user_input: str) -> ClassificationResponse:
    """Classify a user request into a routing decision.

    Returns a ClassificationResponse with the parsed ClassifierResult plus
    token usage and computed cost for audit-log purposes.

    Raises:
        ValueError: if Claude failed to call the route tool (should not happen
            with tool_choice forcing, but guarded as a safety net).
    """
    client = _get_client()

    # Cache breakpoint on the last tool — caches system + tools in one block.
    # System prompt + tool schema are stable across requests; only the user
    # message changes. After the first call within the 5-minute window, the
    # static portion (~80% of input tokens) drops to ~10% of input cost.
    cached_tool = {**ROUTE_TOOL, "cache_control": {"type": "ephemeral"}}

    response = client.messages.create(
        model=CLASSIFIER_MODEL,
        max_tokens=CLASSIFIER_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[cached_tool],
        tool_choice={"type": "tool", "name": "route_request"},
        messages=[{"role": "user", "content": user_input}],
    )

    # Find the tool_use block. With tool_choice forcing route_request, there
    # should always be exactly one.
    tool_blocks = [b for b in response.content if b.type == "tool_use"]
    if not tool_blocks:
        raise ValueError(f"Classifier did not call route_request tool. Response: {response.content}")

    tool_input = tool_blocks[0].input
    # Pydantic validates and coerces. If the model returned something off-schema
    # (unlikely but possible), this raises a ValidationError.
    parsed = ClassifierResult.model_validate(tool_input)

    usage = response.usage
    cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cost = _compute_cost(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_creation_tokens=cache_creation,
        cache_read_tokens=cache_read,
    )

    return ClassificationResponse(
        result=parsed,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=cost,
    )


# =============================================================================
# CLI for direct testing
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "What's the minimum notice period to terminate someone in Germany?"

    print(f"Input: {query}\n")
    resp = classify(query)
    print(json.dumps(resp.model_dump(), indent=2, ensure_ascii=False))
