"""
Isolated CLI test for the jurisdiction rules engine.

Runs the demo scenarios from CLAUDE.md against the jurisdiction MCP server's
tool functions DIRECTLY — no orchestrator, no LLM. The point is to verify the
rules engine is correct before any agent logic is wired in.

Each scenario has:
  - a human-readable description (also serves as living docs)
  - the tool call being exercised
  - the expected outcome (compliant/non-compliant, key fields)
  - a predicate that decides PASS/FAIL

Usage:
    uv run python scripts/test_jurisdiction.py

Exit code:
    0 if all scenarios pass; 1 otherwise.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Make project root importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_servers.jurisdiction_server import (  # noqa: E402 — must follow sys.path manipulation
    get_notice_period,
    get_termination_rules,
    validate_action,
)


@dataclass
class Scenario:
    description: str
    call_repr: str  # human-readable call, e.g. "get_notice_period('DE', 84)"
    call: Callable[[], dict[str, Any]]
    predicate: Callable[[dict[str, Any]], tuple[bool, str]]


def expect_compliant(result: dict[str, Any]) -> tuple[bool, str]:
    return (
        bool(result.get("compliant")),
        f"compliant={result.get('compliant')}, reason={result.get('reason', '')[:80]}",
    )


def expect_non_compliant(result: dict[str, Any]) -> tuple[bool, str]:
    return (
        result.get("compliant") is False,
        f"compliant={result.get('compliant')}, reason={result.get('reason', '')[:80]}",
    )


def expect_not_covered(result: dict[str, Any]) -> tuple[bool, str]:
    covered = result.get("covered", True)
    return (covered is False, f"covered={covered}")


def expect_notice_days(expected: int) -> Callable[[dict[str, Any]], tuple[bool, str]]:
    def predicate(result: dict[str, Any]) -> tuple[bool, str]:
        actual = result.get("notice", {}).get("minimum_days")
        return (
            actual == expected,
            f"minimum_days={actual} (expected {expected})",
        )

    return predicate


# =============================================================================
# Scenarios — these mirror CLAUDE.md's demo list
# =============================================================================

SCENARIOS: list[Scenario] = [
    # ---------- Demo scenario 1: pure jurisdiction lookup ----------
    Scenario(
        description=(
            "DEMO #1 — 'What's the minimum notice period to terminate someone in Germany?'\n"
            "        Generic question, no specific employee. Default to a tenured employee."
        ),
        call_repr="get_notice_period('DE', tenure_months=60)",
        call=lambda: get_notice_period("DE", 60),
        predicate=expect_notice_days(60),  # 5yr → 2 months → 60 days minimum
    ),
    # ---------- Demo scenario 2: BR CLT, ~4 years tenure (João) ----------
    Scenario(
        description=(
            "DEMO #2 — 'Process termination for João, last day Jan 31.'\n"
            "        João = emp_001, BR CLT, 3yr 10mo tenure → aviso prévio = 30 + 3*3 = 39 days."
        ),
        call_repr="get_notice_period('BR', tenure_months=46, employment_type='CLT')",
        call=lambda: get_notice_period("BR", 46, "CLT"),
        predicate=expect_notice_days(39),
    ),
    Scenario(
        description=(
            "DEMO #2 (extended) — get_termination_rules should include FGTS multa and "
            "all severance components for BR CLT."
        ),
        call_repr="get_termination_rules('BR', 'CLT', tenure_months=46)",
        call=lambda: get_termination_rules("BR", "CLT", 46),
        predicate=lambda r: (
            any("FGTS multa" in c["name"] for c in r.get("severance_components", []))
            and any("13º" in c["name"] for c in r.get("severance_components", [])),
            f"severance components: {[c['name'] for c in r.get('severance_components', [])][:3]}...",
        ),
    ),
    # ---------- Demo scenario 3: Ana Müller probation ----------
    Scenario(
        description=(
            "DEMO #3 — 'Terminate Ana Müller with 2 weeks notice.'\n"
            "        Ana = emp_005, DE full-time, <6mo (probation) → 2 weeks compliant."
        ),
        call_repr="validate_action('terminate_without_cause', 'DE', {tenure_months: 3, notice_days_given: 14})",
        call=lambda: validate_action(
            "terminate_without_cause",
            "DE",
            {"employment_type": "full-time", "tenure_months": 3, "notice_days_given": 14},
        ),
        predicate=expect_compliant,
    ),
    # ---------- Demo scenario 4: Sarah Chen NON-compliant ----------
    Scenario(
        description=(
            "DEMO #4 — 'Terminate Sarah Chen with 2 weeks notice.'\n"
            "        Sarah = emp_004, DE full-time, 4+ years → minimum 1 month → 2 weeks NON-compliant."
        ),
        call_repr="validate_action('terminate_without_cause', 'DE', {tenure_months: 52, notice_days_given: 14})",
        call=lambda: validate_action(
            "terminate_without_cause",
            "DE",
            {"employment_type": "full-time", "tenure_months": 52, "notice_days_given": 14},
        ),
        predicate=expect_non_compliant,
    ),
    # ---------- Demo scenario 5: PJ → CLT conversion (Maria Santos) ----------
    Scenario(
        description=(
            "DEMO #5 — 'Convert Maria Santos from contractor to CLT.'\n"
            "        Maria = emp_002, BR PJ. Querying her CURRENT rules should return PJ "
            "(contract-only, no verbas, vínculo risk noted)."
        ),
        call_repr="get_termination_rules('BR', 'PJ', tenure_months=24)",
        call=lambda: get_termination_rules("BR", "PJ", 24),
        predicate=lambda r: (
            r.get("employment_type") == "PJ"
            and len(r.get("severance_components", [])) == 0
            and "vínculo empregatício" in r.get("notes", ""),
            f"employment_type={r.get('employment_type')}, severance_count={len(r.get('severance_components', []))}",
        ),
    ),
    # ---------- US-CA at-will + same-day final pay ----------
    Scenario(
        description=(
            "US-CA at-will — individual termination requires no notice, but final pay rules apply.\n"
            "        Emily Ross (emp_008), CA, 3yr+ tenure → notice required = 0 days."
        ),
        call_repr="validate_action('terminate_without_cause', 'US-CA', {tenure_months: 40, notice_days_given: 0})",
        call=lambda: validate_action(
            "terminate_without_cause",
            "US-CA",
            {"employment_type": "full-time", "tenure_months": 40, "notice_days_given": 0},
        ),
        predicate=lambda r: (
            r.get("compliant") is True
            and any(
                kw in r.get("recommendation", "").lower() for kw in ("final wage", "final pay", "§203", "waiting-time")
            ),
            f"compliant={r.get('compliant')}, recommendation surfaces final-pay rule: "
            f"{any(kw in r.get('recommendation', '').lower() for kw in ('final wage', 'final pay', '§203'))}",
        ),
    ),
    # ---------- US-CA Cal-WARN trigger (the federal-WARN-fails-but-Cal-WARN-triggers case) ----------
    Scenario(
        description=(
            "US-CA Cal-WARN — 60-person layoff at a 200-employee company.\n"
            "        Federal WARN: fails 33% threshold (60/200 = 30%). Cal-WARN: triggered (75+ ee, 50+ affected)."
        ),
        call_repr="validate_action('mass_layoff', 'US-CA', {total_employees: 200, affected_count: 60})",
        call=lambda: validate_action(
            "mass_layoff",
            "US-CA",
            {"total_employees": 200, "affected_count": 60},
        ),
        predicate=lambda r: (
            r.get("compliant") is False and "Cal-WARN" in r.get("reason", ""),
            f"compliant={r.get('compliant')}, mentions Cal-WARN: {'Cal-WARN' in r.get('reason', '')}",
        ),
    ),
    # ---------- BR CLT — large tenure tests the cap ----------
    Scenario(
        description=(
            "BR CLT cap — 25-year tenure should cap notice at 90 days (Lei 12.506/2011 maximum).\n"
            "        Lucas Oliveira (emp_003), BR CLT, 7+ years already at 51 days; 25yr is at the cap."
        ),
        call_repr="get_notice_period('BR', tenure_months=300, employment_type='CLT')",
        call=lambda: get_notice_period("BR", 300, "CLT"),
        predicate=expect_notice_days(90),
    ),
    # ---------- Protected employee block ----------
    Scenario(
        description=(
            "Protected employee — terminating a pregnant CLT employee must be BLOCKED.\n"
            "        ADCT Art. 10, II, b — estabilidade gestante."
        ),
        call_repr="validate_action('terminate_protected_employee', 'BR', {protection_type: 'pregnant_employee'})",
        call=lambda: validate_action(
            "terminate_protected_employee",
            "BR",
            {"employment_type": "CLT", "protection_type": "pregnant_employee"},
        ),
        predicate=expect_non_compliant,
    ),
    # ---------- UK (Phase 8 batch A) ----------
    Scenario(
        description=(
            "UK notice scales by tenure — 5yr employee → 5 weeks (35 days) per ERA 1996 §86(1)(b).\n"
            "        The per-year scaling from year 2 to year 12, before the 12-week cap kicks in."
        ),
        call_repr="get_notice_period('UK', tenure_months=60)",
        call=lambda: get_notice_period("UK", 60),
        predicate=expect_notice_days(35),
    ),
    Scenario(
        description=(
            "UK notice cap — 20yr employee → 12 weeks (84 days), the ERA 1996 §86(1)(c) cap.\n"
            "        Anything above 12 years tenure caps at 12 weeks."
        ),
        call_repr="get_notice_period('UK', tenure_months=240)",
        call=lambda: get_notice_period("UK", 240),
        predicate=expect_notice_days(84),
    ),
    Scenario(
        description=(
            "UK collective redundancy — 25 employees at a 60-person site triggers TULRCA 1992 §188.\n"
            "        30-day consultation + HR1 notification required (45 days if 100+ affected)."
        ),
        call_repr="validate_action('mass_layoff', 'UK', {total_employees: 60, affected_count: 25})",
        call=lambda: validate_action(
            "mass_layoff",
            "UK",
            {"total_employees": 60, "affected_count": 25},
        ),
        predicate=lambda r: (
            r.get("compliant") is False and "TULRCA" in r.get("citation", ""),
            f"compliant={r.get('compliant')}, mentions TULRCA: {'TULRCA' in r.get('citation', '')}",
        ),
    ),
    # ---------- FR (Phase 8 batch A) ----------
    Scenario(
        description=(
            "FR non-cadre notice — 5yr employee → 60 days (2 months) per Code du travail Art. L1234-1.\n"
            "        Statutory floor for non-cadres with ≥2yr tenure."
        ),
        call_repr="get_notice_period('FR', tenure_months=60, employment_type='non-cadre')",
        call=lambda: get_notice_period("FR", 60, "non-cadre"),
        predicate=expect_notice_days(60),
    ),
    Scenario(
        description=(
            "FR cadre notice — 1yr employee → 90 days (3 months by CCN, e.g. Syntec).\n"
            "        Cadre 3-month notice is market-standard, set by industry agreement, not the Code."
        ),
        call_repr="get_notice_period('FR', tenure_months=12, employment_type='cadre')",
        call=lambda: get_notice_period("FR", 12, "cadre"),
        predicate=expect_notice_days(90),
    ),
    Scenario(
        description=(
            "FR default routing — 'full-time' should auto-resolve to non-cadre.\n"
            "        Lets the orchestrator stay agnostic about cadre vs non-cadre distinction."
        ),
        call_repr="get_termination_rules('FR', 'full-time', tenure_months=36)",
        call=lambda: get_termination_rules("FR", "full-time", 36),
        predicate=lambda r: (
            r.get("employment_type") == "non-cadre",
            f"employment_type={r.get('employment_type')} (expected non-cadre)",
        ),
    ),
    Scenario(
        description=(
            "FR PSE — 15 dismissals in 30 days at a 100-employee firm triggers Plan de Sauvegarde de l'Emploi.\n"
            "        Code du travail Art. L1233-61: 10+ at firms with 50+ employees."
        ),
        call_repr="validate_action('mass_layoff', 'FR', {total_employees: 100, affected_count: 15})",
        call=lambda: validate_action(
            "mass_layoff",
            "FR",
            {"total_employees": 100, "affected_count": 15},
        ),
        predicate=lambda r: (
            r.get("compliant") is False and "L1233-61" in r.get("citation", ""),
            f"compliant={r.get('compliant')}, mentions L1233-61: {'L1233-61' in r.get('citation', '')}",
        ),
    ),
    # ---------- ES (Phase 8 batch A) ----------
    Scenario(
        description=(
            "ES despido objetivo notice — 5yr employee → 15 calendar days per ET Art. 53.1.c.\n"
            "        Spanish notice is a flat 15 days for objective dismissal, regardless of tenure."
        ),
        call_repr="get_notice_period('ES', tenure_months=60)",
        call=lambda: get_notice_period("ES", 60),
        predicate=expect_notice_days(15),
    ),
    Scenario(
        description=(
            "ES despido colectivo — 12 dismissals at an 80-employee firm triggers ET Art. 51.\n"
            "        Firms with <100 staff: 10+ dismissals in 90-day window triggers collective procedure."
        ),
        call_repr="validate_action('mass_layoff', 'ES', {total_employees: 80, affected_count: 12})",
        call=lambda: validate_action(
            "mass_layoff",
            "ES",
            {"total_employees": 80, "affected_count": 12},
        ),
        predicate=lambda r: (
            r.get("compliant") is False and "Art. 51" in r.get("citation", ""),
            f"compliant={r.get('compliant')}, mentions Art. 51: {'Art. 51' in r.get('citation', '')}",
        ),
    ),
    # ---------- Graceful fallback for uncovered country ----------
    Scenario(
        description=(
            "Uncovered country — JP must return 'not covered' structured response.\n"
            "        No LLM fallback; this is the deterministic-compliance principle in CLAUDE.md."
        ),
        call_repr="get_notice_period('JP', tenure_months=24)",
        call=lambda: get_notice_period("JP", 24),
        predicate=expect_not_covered,
    ),
    Scenario(
        description="Uncovered country (IN) — same fallback path as JP.",
        call_repr="get_termination_rules('IN', 'contractor', tenure_months=12)",
        call=lambda: get_termination_rules("IN", "contractor", 12),
        predicate=expect_not_covered,
    ),
]


# =============================================================================
# Runner
# =============================================================================


def main() -> int:
    # Windows console defaults to cp1252; force UTF-8 so the doc-string Unicode renders.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 78)
    print("Jurisdiction rules engine — isolated test")
    print("=" * 78)
    print()

    failed = 0
    for i, scenario in enumerate(SCENARIOS, start=1):
        print(f"--- Scenario {i}/{len(SCENARIOS)} ---")
        print(scenario.description)
        print(f"  Call:  {scenario.call_repr}")

        try:
            result = scenario.call()
            passed, reason = scenario.predicate(result)
            tag = "[PASS]" if passed else "[FAIL]"
            print(f"  {tag} {reason}")
            if not passed:
                failed += 1
                print(f"  Full result: {json.dumps(result, ensure_ascii=False, default=str)[:400]}")
        except Exception as e:  # noqa: BLE001 — test runner deliberately catches all
            failed += 1
            print(f"  [ERROR] {type(e).__name__}: {e}")

        print()

    print("=" * 78)
    print(f"Result: {len(SCENARIOS) - failed}/{len(SCENARIOS)} passed")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
