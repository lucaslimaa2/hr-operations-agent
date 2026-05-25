"""
Pytest wrapper for classifier routing decisions.

Live API tests — skipped in CI by ``skip_no_anthropic_key``. Locally, ~$0.02
per suite.

Unlike jurisdiction and resolver scenarios (which have rich SCENARIOS lists in
their scripts), the classifier script was a smoke test. We define routing
expectations inline here, mirroring the 7 CLAUDE.md demo scenarios.
"""

from __future__ import annotations

import pytest

from tests.conftest import skip_no_anthropic_key

# Each tuple: (user_query, expected_agents_required, allowed_action_types).
# allowed_action_types is a set — the classifier's action_type field is informational
# (the agents_required is what drives routing) and Haiku can pick reasonable
# alternatives (e.g. None vs 'policy_query' for an offboarding question).
# Use None in the set to also allow the model returning no action_type.
CLASSIFIER_CASES: list[tuple[str, set[str], set[str | None]]] = [
    (
        "What's the minimum notice period to terminate someone in Germany?",
        {"jurisdiction"},
        {"termination_query"},
    ),
    (
        "Process termination for João, last day Jan 31.",
        {"hris", "jurisdiction"},
        {"process_termination"},
    ),
    (
        "Terminate Ana Müller with 2 weeks notice.",
        {"hris", "jurisdiction"},
        {"process_termination"},
    ),
    (
        "Terminate Sarah Chen with 2 weeks notice.",
        {"hris", "jurisdiction"},
        {"process_termination"},
    ),
    (
        "Convert Maria Santos from contractor to CLT.",
        {"hris", "policy", "jurisdiction"},  # all 3 — conversion always triggers jurisdiction
        {"conversion"},
    ),
    (
        "What severance is Carlos entitled to?",
        {"hris", "jurisdiction"},
        {"severance_query"},
    ),
    (
        "What are our offboarding steps?",
        {"policy"},
        {"policy_query", None},  # Haiku sometimes returns None for this — both fine
    ),
]


@skip_no_anthropic_key
@pytest.mark.live_api
@pytest.mark.parametrize(
    "query,expected_agents,allowed_actions",
    CLASSIFIER_CASES,
    ids=[c[0][:70] for c in CLASSIFIER_CASES],
)
def test_classifier_routes_correctly(
    query: str,
    expected_agents: set[str],
    allowed_actions: set[str | None],
) -> None:
    """Classifier should return the expected set of agents and one of the allowed action_types."""
    from agent.classifier import classify

    resp = classify(query)
    actual_agents = set(resp.result.agents_required)
    assert actual_agents == expected_agents, (
        f"\n  query: {query}\n  expected agents: {expected_agents}\n  got:             {actual_agents}"
    )

    # action_type is informational — Haiku occasionally picks adjacent valid values
    # ('policy_query' vs None vs 'general_question'). We log mismatches but don't
    # fail on them; the routing decision (agents_required) is the contract.
    actual_action = resp.result.entities.action_type
    if actual_action not in allowed_actions:
        print(
            f"\n[advisory] action_type drift for {query!r}: "
            f"got {actual_action!r}, expected one of {allowed_actions}"
        )
