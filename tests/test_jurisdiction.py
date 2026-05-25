"""
Pytest wrapper for the jurisdiction rules engine scenarios.

The deterministic rules engine has no API dependencies — these tests are FREE
and FAST. They run on every CI push.

Source of truth is scripts/test_jurisdiction.py's SCENARIOS list. This file
parametrizes over it so each scenario becomes its own pytest test case.
"""

from __future__ import annotations

import pytest

from scripts.test_jurisdiction import SCENARIOS


def _scenario_id(scenario) -> str:
    """First line of the description, truncated — pytest's display name."""
    return scenario.description.split("\n")[0][:80]


@pytest.mark.parametrize("scenario", SCENARIOS, ids=_scenario_id)
def test_jurisdiction_scenario(scenario) -> None:
    """Run one jurisdiction-engine scenario; assert the predicate passes."""
    result = scenario.call()
    passed, reason = scenario.predicate(result)
    assert passed, f"\n  call:  {scenario.call_repr}\n  fail:  {reason}"
