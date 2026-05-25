"""
Pytest wrapper for the conflict resolver scenarios.

Live API tests — skipped in CI (no ANTHROPIC_API_KEY) by the ``skip_no_anthropic_key``
marker from conftest.py. Locally with .env loaded, all six scenarios run and
the suite costs ~$0.02 per execution.

Source of truth: scripts/test_resolver.py's SCENARIOS list.
"""

from __future__ import annotations

import pytest

from scripts.test_resolver import SCENARIOS
from tests.conftest import skip_no_anthropic_key


def _scenario_id(scenario) -> str:
    return scenario.description.split("\n")[0][:80]


@skip_no_anthropic_key
@pytest.mark.live_api
@pytest.mark.parametrize("scenario", SCENARIOS, ids=_scenario_id)
def test_resolver_scenario(scenario) -> None:
    """Run one conflict-resolver scenario; assert the predicate passes."""
    from agent.conflict_resolver import resolve

    resp = resolve(scenario.context)
    passed, reason = scenario.predicate(resp)
    assert passed, f"\n  user_input:  {scenario.context.user_input}\n  fail:  {reason}"
