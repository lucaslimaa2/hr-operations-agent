"""
Isolated CLI test for the conflict resolver.

Runs scenarios that exercise both decision paths (auto / escalate) and
verifies the resolver returns sensible verdicts with well-formed briefs.

Why a dedicated test:
  In the end-to-end agent flow, Sonnet itself refuses to propose writes that
  the jurisdiction tools flag non-compliant — its system prompt enforces that.
  So the escalate path rarely fires from Sonnet's side in normal operation.
  This script exercises the resolver DIRECTLY with handcrafted contexts so we
  can verify the safety net works even when (hypothetically) Sonnet would not
  self-gate.

Usage:
    uv run python scripts/test_resolver.py
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.conflict_resolver import ResolveContext, ResolveResponse, resolve  # noqa: E402


@dataclass
class Scenario:
    description: str
    context: ResolveContext
    predicate: Callable[[ResolveResponse], tuple[bool, str]]


def expect_auto(resp: ResolveResponse) -> tuple[bool, str]:
    ok = resp.result.resolution == "auto"
    return ok, f"resolution={resp.result.resolution}, summary={resp.result.action_summary[:60]}"


def expect_escalate(resp: ResolveResponse) -> tuple[bool, str]:
    ok = resp.result.resolution == "escalate"
    brief = resp.result.escalation_brief
    has_full_brief = brief is not None and all([brief.conflict, brief.recommendation, brief.question_for_hr])
    return (
        ok and has_full_brief,
        f"resolution={resp.result.resolution}, brief_complete={has_full_brief}, "
        f"risk={brief.risk_level if brief else 'n/a'}",
    )


# =============================================================================
# Scenarios
# =============================================================================

SCENARIOS: list[Scenario] = [
    Scenario(
        description=(
            "AUTO — Ana Müller (DE, 3mo probation), terminate with 14 days notice.\n"
            "        Compliant per BGB §622(3). No protected category. Reversible-ish action.\n"
            "        Expected: resolution=auto."
        ),
        context=ResolveContext(
            user_input="Terminate Ana Müller. She handed in her notice today, 14 days notice.",
            agents_invoked=["hris", "jurisdiction"],
            tool_calls=[
                {
                    "tool": "search_employees",
                    "args": {"name": "Ana Müller"},
                    "result": '{"matches": [{"id": "emp_005", "name": "Ana Müller", "country": "DE", "employment_type": "full-time", "tenure_months": 3, "employment_status": "active"}]}',
                },
                {
                    "tool": "validate_action",
                    "args": {
                        "action": "terminate_without_cause",
                        "country": "DE",
                        "context": {
                            "employment_type": "full-time",
                            "tenure_months": 3,
                            "notice_days_given": 14,
                        },
                    },
                    "result": '{"compliant": true, "reason": "Proposed 14 days notice meets the statutory minimum of 14 days for a full-time employee with 3 months tenure (Probezeit).", "citation": "BGB §622(3)"}',
                },
            ],
            proposed_tool="update_employment_status",
            proposed_args={
                "employee_id": "emp_005",
                "status": "terminated",
                "effective_date": "2026-06-08",
            },
        ),
        predicate=expect_auto,
    ),
    Scenario(
        description=(
            "ESCALATE — Sarah Chen (DE, 77mo) terminate with 14 days notice.\n"
            "        Jurisdiction flagged compliant=false. Statutory minimum is 60 days.\n"
            "        Expected: escalate with brief naming BGB §622(2)."
        ),
        context=ResolveContext(
            user_input="Terminate Sarah Chen with 2 weeks notice.",
            agents_invoked=["hris", "jurisdiction"],
            tool_calls=[
                {
                    "tool": "search_employees",
                    "args": {"name": "Sarah Chen"},
                    "result": '{"matches": [{"id": "emp_004", "name": "Sarah Chen", "country": "DE", "employment_type": "full-time", "tenure_months": 77, "employment_status": "active"}]}',
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
                    "result": '{"compliant": false, "reason": "Proposed 14 days notice is BELOW the statutory minimum of 60 days for a full-time employee with 77 months tenure.", "citation": "BGB §622(2) Nr. 2", "recommendation": "Increase notice to at least 60 days, OR pay in lieu."}',
                },
            ],
            proposed_tool="update_employment_status",
            proposed_args={
                "employee_id": "emp_004",
                "status": "terminated",
                "effective_date": "2026-06-08",
            },
        ),
        predicate=expect_escalate,
    ),
    Scenario(
        description=(
            "ESCALATE — Protected employee (pregnant CLT employee).\n"
            "        Validate_action returned compliant=false due to estabilidade gestante.\n"
            "        Expected: escalate, risk=high, brief cites ADCT Art. 10."
        ),
        context=ResolveContext(
            user_input="Terminate emp_xyz, she's been underperforming for months.",
            agents_invoked=["hris", "jurisdiction"],
            tool_calls=[
                {
                    "tool": "get_employee",
                    "args": {"employee_id": "emp_xyz"},
                    "result": '{"id": "emp_xyz", "name": "Sample Employee", "country": "BR", "employment_type": "CLT", "tenure_months": 24}',
                },
                {
                    "tool": "validate_action",
                    "args": {
                        "action": "terminate_protected_employee",
                        "country": "BR",
                        "context": {
                            "employment_type": "CLT",
                            "protection_type": "pregnant_employee",
                        },
                    },
                    "result": '{"compliant": false, "reason": "Ordinary termination of an employee in protected category pregnant_employee is BLOCKED. Scope: from confirmation of pregnancy through 5 months postpartum.", "citation": "ADCT Art. 10, II, b"}',
                },
            ],
            proposed_tool="update_employment_status",
            proposed_args={"employee_id": "emp_xyz", "status": "terminated"},
        ),
        predicate=expect_escalate,
    ),
    Scenario(
        description=(
            "ESCALATE — Mass layoff that triggers Cal-WARN.\n"
            "        60 affected at 200-employee CA company → Cal-WARN 60-day notice required.\n"
            "        Expected: escalate, brief mentions WARN."
        ),
        context=ResolveContext(
            user_input="We need to lay off 60 people in our CA office next week.",
            agents_invoked=["hris", "jurisdiction"],
            tool_calls=[
                {
                    "tool": "validate_action",
                    "args": {
                        "action": "mass_layoff",
                        "country": "US-CA",
                        "context": {"total_employees": 200, "affected_count": 60},
                    },
                    "result": '{"compliant": false, "reason": "Layoff of 60 at a 200-employee site triggers Cal-WARN. 60 days advance written notice required.", "citation": "Cal. Lab. Code §§1400-1408 (Cal-WARN)", "recommendation": "Issue 60 days advance written notice to affected employees, CA EDD, local workforce investment board, and local elected officials."}',
                },
            ],
            proposed_tool="update_employment_status",
            proposed_args={"employee_id": "emp_xyz", "status": "terminated"},
        ),
        predicate=expect_escalate,
    ),
    Scenario(
        description=(
            "ESCALATE — Uncovered jurisdiction (JP).\n"
            "        Engine returned covered=false. Resolver must refuse to auto-approve.\n"
            "        Expected: escalate."
        ),
        context=ResolveContext(
            user_input="Terminate Yuki Tanaka in Tokyo.",
            agents_invoked=["hris", "jurisdiction"],
            tool_calls=[
                {
                    "tool": "search_employees",
                    "args": {"name": "Yuki Tanaka"},
                    "result": '{"matches": [{"id": "emp_019", "name": "Yuki Tanaka", "country": "JP", "employment_type": "full-time", "tenure_months": 50}]}',
                },
                {
                    "tool": "get_termination_rules",
                    "args": {"country": "JP", "employment_type": "full-time", "tenure_months": 50},
                    "result": '{"covered": false, "country": "JP", "message": "Jurisdiction not covered. This engine has rules for: BR, DE, US-CA.", "recommendation": "Escalate to specialist legal counsel before any action."}',
                },
            ],
            proposed_tool="update_employment_status",
            proposed_args={"employee_id": "emp_019", "status": "terminated"},
        ),
        predicate=expect_escalate,
    ),
    Scenario(
        description=(
            "AUTO — Reversible status change (active → on_leave) for a clearly-stated reason.\n"
            "        Marcus Johnson sabbatical. No compliance issues. Reversible.\n"
            "        Expected: auto."
        ),
        context=ResolveContext(
            user_input="Move Marcus Johnson to on_leave starting June 1. He's taking sabbatical.",
            agents_invoked=["hris"],
            tool_calls=[
                {
                    "tool": "search_employees",
                    "args": {"name": "Marcus Johnson"},
                    "result": '{"matches": [{"id": "emp_010", "name": "Marcus Johnson", "country": "US-NY", "employment_type": "full-time", "tenure_months": 59, "employment_status": "active"}]}',
                },
            ],
            proposed_tool="update_employment_status",
            proposed_args={
                "employee_id": "emp_010",
                "status": "on_leave",
                "effective_date": "2026-06-01",
            },
        ),
        predicate=expect_auto,
    ),
]


# =============================================================================
# Runner
# =============================================================================


def main() -> int:
    print("=" * 78)
    print("Conflict resolver — isolated test")
    print("=" * 78)
    print()

    failed = 0
    total_cost = 0.0
    for i, sc in enumerate(SCENARIOS, 1):
        print(f"--- Scenario {i}/{len(SCENARIOS)} ---")
        print(sc.description)
        try:
            resp = resolve(sc.context)
            total_cost += resp.cost_usd
            passed, reason = sc.predicate(resp)
            tag = "[PASS]" if passed else "[FAIL]"
            print(f"  {tag} {reason}")
            if resp.result.escalation_brief:
                b = resp.result.escalation_brief
                print(f"    conflict: {b.conflict[:90]}")
                print(f"    risk: {b.risk_level} | question: {b.question_for_hr[:80]}")
            if not passed:
                failed += 1
                print(f"  Full result: {json.dumps(resp.result.model_dump(), indent=2, ensure_ascii=False)[:400]}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  [ERROR] {type(e).__name__}: {e}")
        print()

    print("=" * 78)
    print(f"Result: {len(SCENARIOS) - failed}/{len(SCENARIOS)} passed   ·   total cost: ${total_cost:.5f}")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
