"""
Jurisdiction MCP server.

Exposes three tools to the orchestrator:

  - get_notice_period(country, tenure_months, employment_type)
        Narrow lookup: minimum statutory notice for a tenure.

  - get_termination_rules(country, employment_type, tenure_months)
        Full rule set: notice, severance components, protections, mandatory steps.
        Use this when the agent needs comprehensive context for a termination.

  - validate_action(action, country, context)
        Compliance check on a proposed action. Returns {compliant, reason,
        recommendation, citation}. Use this when the user proposes a specific
        action (e.g., "terminate Sarah with 2 weeks notice").

Architecture notes:
  - Pure rule data lives in jurisdiction_rules.py. This server is the
    MCP interface layer — it owns the tool surface, not the rules.
  - Every uncovered country resolves to a structured "not covered" message.
    The server NEVER falls back to LLM-generated rules — that is the
    deterministic-compliance principle in CLAUDE.md.
  - Run standalone for testing:
        uv run python mcp_servers/jurisdiction_server.py
    The orchestrator launches this as a subprocess in Phase 3.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_servers.jurisdiction_rules import (
    UNCOVERED_COUNTRIES_MESSAGE,
    JurisdictionRule,
    NoticeBracket,
    get_rule,
    is_covered,
)

mcp = FastMCP("jurisdiction")


# =============================================================================
# Response helpers
# =============================================================================


def _not_covered(country: str) -> dict[str, Any]:
    """Structured response for countries with no rule coverage."""
    return {
        "covered": False,
        "country": country,
        "message": UNCOVERED_COUNTRIES_MESSAGE,
        "recommendation": "Escalate to specialist legal counsel before any action.",
    }


def _rule_not_found(country: str, employment_type: str) -> dict[str, Any]:
    """Country IS covered, but the employment_type doesn't match a known rule."""
    return {
        "covered": True,
        "country": country,
        "employment_type": employment_type,
        "error": (
            f"No rule registered for ({country}, {employment_type}). "
            f"For BR, valid employment_types are: 'CLT', 'PJ'. "
            f"For DE and US-CA, use 'full-time'."
        ),
    }


def _notice_response(bracket: NoticeBracket, rule: JurisdictionRule) -> dict[str, Any]:
    """Serialize a resolved NoticeBracket as a dict for tool return."""
    return {
        "minimum_days": bracket.minimum_days_estimate(),
        "days": bracket.days or None,
        "months": bracket.months or None,
        "to_end_of_calendar_month": bracket.to_end_of_month,
        "description": bracket.description or rule.employer_notice.description,
        "citation": bracket.citation or rule.employer_notice.citation,
    }


# =============================================================================
# Tools
# =============================================================================


@mcp.tool()
def get_notice_period(
    country: str,
    tenure_months: int,
    employment_type: str = "full-time",
) -> dict[str, Any]:
    """Return the minimum statutory notice period for an employer-initiated termination.

    Use this for narrow questions like "What's the minimum notice in Germany?"
    or "How much notice does João (5 years CLT) need?"

    Args:
        country: ISO-ish country code. Supported: 'BR', 'DE', 'US-CA'.
        tenure_months: Total months of service. Affects DE (tenure-graded) and BR (proportional).
        employment_type: 'full-time' (default), or 'CLT'/'PJ' for Brazil. Case-insensitive.

    Returns:
        A dict with the notice period in days and/or months, end-of-month flag for DE,
        description, and the statute citation. If the country is not covered, returns
        a structured "not covered" response — do not infer rules from elsewhere.
    """
    if not is_covered(country):
        return _not_covered(country)

    rule = get_rule(country, employment_type)
    if rule is None:
        return _rule_not_found(country, employment_type)

    bracket = rule.employer_notice.resolve(tenure_months)
    return {
        "covered": True,
        "country": country,
        "employment_type": rule.employment_type,
        "tenure_months": tenure_months,
        "notice": _notice_response(bracket, rule),
    }


@mcp.tool()
def get_termination_rules(
    country: str,
    employment_type: str = "full-time",
    tenure_months: int = 0,
) -> dict[str, Any]:
    """Return the complete termination rule set for a country + employment type.

    Use this when the agent needs comprehensive context to reason about a termination:
    notice period, severance components, protected categories, mandatory procedural steps,
    final-pay deadlines, and legal-framework citations.

    Args:
        country: ISO-ish country code. Supported: 'BR', 'DE', 'US-CA'.
        employment_type: 'full-time' (default), or 'CLT'/'PJ' for Brazil.
        tenure_months: Months of service. Used to compute the applicable notice bracket.

    Returns:
        A dict with: notice (resolved for the given tenure), severance_components,
        protections, mandatory_steps, final_pay_deadline, legal_framework, notes,
        and at_will flag. Each component includes its citation.
    """
    if not is_covered(country):
        return _not_covered(country)

    rule = get_rule(country, employment_type)
    if rule is None:
        return _rule_not_found(country, employment_type)

    bracket = rule.employer_notice.resolve(tenure_months)

    return {
        "covered": True,
        "country": rule.country,
        "employment_type": rule.employment_type,
        "tenure_months": tenure_months,
        "legal_framework": rule.legal_framework,
        "at_will": rule.at_will,
        "notice": _notice_response(bracket, rule),
        "severance_components": [c.model_dump() for c in rule.severance_components],
        "protections": [p.model_dump() for p in rule.protections],
        "mandatory_steps": list(rule.mandatory_steps),
        "final_pay_deadline": rule.final_pay_deadline,
        "notes": rule.notes,
    }


@mcp.tool()
def validate_action(
    action: str,
    country: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Check whether a proposed HR action is compliant with the jurisdiction's rules.

    Use this when the user proposes a specific action (e.g., "terminate Sarah with
    2 weeks notice", "lay off 60 people in California"). Returns a structured
    compliance verdict with reason, recommendation, and statute citation.

    Args:
        action: One of:
            'terminate_without_cause' — ordinary employer-initiated termination.
            'terminate_with_cause' — termination for documented cause (just cause / verhaltensbedingt / for-cause).
            'mass_layoff' — group termination at a single site.
            'terminate_protected_employee' — termination of someone in a protected category.
        country: ISO-ish country code.
        context: Action-specific parameters. Common keys:
            employment_type: str — for 'terminate_*' actions
            tenure_months: int — for 'terminate_*' actions
            notice_days_given: int — for 'terminate_without_cause' (days of notice the user proposes)
            affected_count: int — for 'mass_layoff' (employees being laid off)
            total_employees: int — for 'mass_layoff' (employer headcount)
            protection_type: str — for 'terminate_protected_employee' (e.g., 'pregnant_employee')

    Returns:
        {compliant: bool, reason: str, recommendation: str, citation: str}
    """
    if not is_covered(country):
        return {
            "compliant": False,
            "reason": UNCOVERED_COUNTRIES_MESSAGE,
            "recommendation": "Do not auto-execute. Escalate to specialist legal review.",
            "citation": "",
        }

    if action == "terminate_without_cause":
        return _validate_terminate_without_cause(country, context)
    if action == "terminate_with_cause":
        return _validate_terminate_with_cause(country, context)
    if action == "mass_layoff":
        return _validate_mass_layoff(country, context)
    if action == "terminate_protected_employee":
        return _validate_terminate_protected(country, context)

    return {
        "compliant": False,
        "reason": f"Unknown action '{action}'. Cannot validate.",
        "recommendation": "Use one of: terminate_without_cause, terminate_with_cause, mass_layoff, terminate_protected_employee.",
        "citation": "",
    }


# =============================================================================
# validate_action sub-handlers
# =============================================================================


def _validate_terminate_without_cause(country: str, ctx: dict[str, Any]) -> dict[str, Any]:
    employment_type = ctx.get("employment_type", "full-time")
    tenure_months = int(ctx.get("tenure_months", 0))
    notice_days_given = ctx.get("notice_days_given")

    rule = get_rule(country, employment_type)
    if rule is None:
        return {
            "compliant": False,
            "reason": f"No rule for ({country}, {employment_type}).",
            "recommendation": "Verify employment_type. For BR use 'CLT' or 'PJ'.",
            "citation": "",
        }

    required = rule.employer_notice.resolve(tenure_months)
    required_min = required.minimum_days_estimate()

    # PJ — no statutory notice, contract governs.
    if rule.employment_type == "PJ":
        return {
            "compliant": True,
            "reason": (
                "PJ (contractor) termination is governed by contract terms, not labor law. "
                "Civil Code reasonable-notice default ≈ 30 days if contract silent. "
                "However, vínculo empregatício re-classification risk should be reviewed."
            ),
            "recommendation": (
                "Confirm contract terms. If the relationship meets the four-factor employment test "
                "(pessoalidade, não-eventualidade, onerosidade, subordinação), escalate to legal "
                "before terminating — re-classification exposure may apply."
            ),
            "citation": "Código Civil Art. 599; CLT Art. 3º (re-classification test)",
        }

    # At-will (US-CA) — no notice required for an individual termination.
    if rule.at_will:
        # But: final-pay timing is the binding constraint.
        return {
            "compliant": True,
            "reason": (
                "At-will jurisdiction: no statutory notice required for an individual termination. "
                "The binding obligation is FINAL PAY at termination, not notice."
            ),
            "recommendation": (
                "Final wages (including accrued vacation) must be paid IMMEDIATELY at termination. "
                "Late payment triggers a §203 waiting-time penalty of the employee's daily wage per "
                "day of delay, capped at 30 days. Confirm protected-class and retaliation analyses."
            ),
            "citation": "Cal. Lab. Code §2922 (at-will); §201 (final pay); §203 (waiting-time penalty)",
        }

    # Day- or month-graded notice rule — compare given to required.
    if notice_days_given is None:
        return {
            "compliant": False,
            "reason": "notice_days_given not provided in context; cannot validate.",
            "recommendation": (
                f"Statutory minimum is {required_min} days "
                f"({required.description}). Provide notice_days_given to validate."
            ),
            "citation": required.citation,
        }

    notice_days_given = int(notice_days_given)
    if notice_days_given >= required_min:
        return {
            "compliant": True,
            "reason": (
                f"Proposed {notice_days_given} days notice meets the statutory minimum of "
                f"{required_min} days for a {employment_type} employee with {tenure_months} months tenure."
            ),
            "recommendation": (
                f"Proceed. Note: {required.description}."
                if required.to_end_of_month
                else "Proceed with documented termination notice."
            ),
            "citation": required.citation,
        }

    # Under minimum
    return {
        "compliant": False,
        "reason": (
            f"Proposed {notice_days_given} days notice is BELOW the statutory minimum of "
            f"{required_min} days ({required.description}) for a {employment_type} employee "
            f"with {tenure_months} months tenure."
        ),
        "recommendation": (
            f"Increase notice to at least {required_min} days, OR pay in lieu of notice "
            f"(notice indenizado) for the shortfall. Issuing termination with insufficient "
            f"notice exposes the employer to wrongful-termination liability."
        ),
        "citation": required.citation,
    }


def _validate_terminate_with_cause(country: str, ctx: dict[str, Any]) -> dict[str, Any]:
    employment_type = ctx.get("employment_type", "full-time")
    rule = get_rule(country, employment_type)
    if rule is None:
        return {
            "compliant": False,
            "reason": f"No rule for ({country}, {employment_type}).",
            "recommendation": "Verify employment_type.",
            "citation": "",
        }

    if country == "BR" and rule.employment_type == "CLT":
        return {
            "compliant": True,
            "reason": (
                "Termination com justa causa is permitted only on grounds exhaustively listed in CLT Art. 482 "
                "(dishonesty, gross misconduct, abandonment, etc.). The employer bears the burden of proof "
                "in labor court."
            ),
            "recommendation": (
                "Document the cause thoroughly (Art. 482 ground, evidence, prior warnings if applicable). "
                "Just-cause termination strips most verbas: saldo and férias vencidas only — no aviso, "
                "no 13º proporcional, no FGTS multa, no seguro-desemprego. High litigation risk if "
                "documentation is weak."
            ),
            "citation": "CLT Art. 482; burden of proof on employer (TST consolidated jurisprudence)",
        }

    if country == "DE":
        return {
            "compliant": True,
            "reason": (
                "Verhaltensbedingte Kündigung (conduct-based termination) is permitted under KSchG when "
                "social justification can be shown. Generally requires a prior written warning (Abmahnung) "
                "for the same conduct, except for severe breaches."
            ),
            "recommendation": (
                "Issue Abmahnung first unless conduct is severe enough for außerordentliche Kündigung "
                "(BGB §626 — within 2 weeks of learning of cause). If a Betriebsrat exists, consult per "
                "BetrVG §102. Employee has 3 weeks to challenge at Arbeitsgericht (KSchG §4)."
            ),
            "citation": "KSchG §1 (social justification); BGB §626 (extraordinary); BetrVG §102",
        }

    if country == "US-CA":
        return {
            "compliant": True,
            "reason": (
                "California is at-will: cause is not legally required, though documenting cause defends "
                "against wrongful-termination claims under FEHA, Tameny (public policy), or Foley "
                "(implied contract)."
            ),
            "recommendation": (
                "Documentation reduces litigation risk even though not statutorily required. Confirm "
                "no protected-class or retaliation analysis triggers. Final pay is due immediately."
            ),
            "citation": "Cal. Lab. Code §2922; FEHA exceptions (Cal. Gov. Code §12940+)",
        }

    return {
        "compliant": False,
        "reason": "For-cause termination logic not implemented for this country.",
        "recommendation": "Escalate.",
        "citation": "",
    }


def _validate_mass_layoff(country: str, ctx: dict[str, Any]) -> dict[str, Any]:
    affected = int(ctx.get("affected_count", 0))
    total = int(ctx.get("total_employees", 0))

    if country == "US-CA":
        # Federal WARN: 100+ employees, 50+ affected at single site OR 500+, with 33% threshold
        # for layoffs of 50-499.
        federal_triggered = total >= 100 and (affected >= 500 or (affected >= 50 and affected / max(total, 1) >= 0.33))
        # Cal-WARN: 75+ employees in past 12mo, 50+ affected — no percentage threshold.
        cal_triggered = total >= 75 and affected >= 50

        if not federal_triggered and not cal_triggered:
            return {
                "compliant": True,
                "reason": (
                    f"Layoff of {affected} at a {total}-employee site does NOT trigger federal WARN "
                    "(under 50 affected OR fails 33% threshold) nor Cal-WARN (under 50 affected OR "
                    "fewer than 75 employees)."
                ),
                "recommendation": (
                    "Proceed as individual terminations. Each requires §201 immediate final pay. "
                    "Confirm no protected-class patterns in the selection."
                ),
                "citation": "29 USC §2101; Cal. Lab. Code §§1400–1408",
            }

        trigger_summary = []
        if federal_triggered:
            trigger_summary.append("Federal WARN")
        if cal_triggered:
            trigger_summary.append("Cal-WARN")

        return {
            "compliant": False,
            "reason": (
                f"Layoff of {affected} at a {total}-employee site triggers {' and '.join(trigger_summary)}. "
                "60 days advance written notice required."
            ),
            "recommendation": (
                "Issue 60 days advance written notice to (1) affected employees, (2) CA EDD, "
                "(3) local workforce investment board, (4) chief elected official of each city/county "
                "where the establishment is located. Failure exposes the employer to 60 days back-pay "
                "per affected employee plus $500/day civil penalty plus attorney's fees."
            ),
            "citation": "29 USC §§2101–2109 (federal WARN); Cal. Lab. Code §§1400–1408 (Cal-WARN)",
        }

    if country == "DE":
        # Massenentlassung thresholds per KSchG §17.
        triggered = (
            (20 <= total <= 59 and affected >= 21)
            or (60 <= total <= 499 and (affected >= 25 or affected / max(total, 1) >= 0.10))
            or (total >= 500 and affected >= 30)
        )
        if not triggered:
            return {
                "compliant": True,
                "reason": (
                    f"Layoff of {affected} at a {total}-employee establishment does not meet "
                    "Massenentlassung thresholds (KSchG §17)."
                ),
                "recommendation": (
                    "Proceed as individual terminations. Each requires KSchG social justification "
                    "(operational/conduct/personal) and Betriebsrat consultation if a works council exists."
                ),
                "citation": "KSchG §17",
            }
        return {
            "compliant": False,
            "reason": (
                f"Layoff of {affected} at a {total}-employee establishment meets Massenentlassung "
                "thresholds (KSchG §17). Notification to Bundesagentur für Arbeit required BEFORE "
                "any terminations are issued."
            ),
            "recommendation": (
                "(1) Notify Bundesagentur für Arbeit prior to termination notices. "
                "(2) If a Betriebsrat exists: negotiate Interessenausgleich and Sozialplan (BetrVG §§111–112). "
                "(3) Apply Sozialauswahl criteria to selection. Failure to notify renders terminations void."
            ),
            "citation": "KSchG §17; BetrVG §§111–112",
        }

    if country == "BR":
        return {
            "compliant": False,
            "reason": (
                "STF jurisprudence (RE 999.435, 2022) requires prior union negotiation for "
                "dispensa coletiva (collective dismissal). No fixed numeric threshold; the rule "
                "applies whenever a 'significant portion' of the workforce is affected."
            ),
            "recommendation": (
                "Open negotiation with the relevant sindicato (union) prior to issuing terminations. "
                "Document the operational/economic justification. Each individual termination still "
                "requires full CLT verbas. Consider Acordo (Art. 484-A) as a negotiated alternative."
            ),
            "citation": "STF RE 999.435 (2022); CLT Art. 477-A (Lei 13.467/2017 attempted to relax, partially overturned)",
        }

    if country == "UK":
        # TULRCA 1992 §188: 20+ proposed redundancies at one establishment in a 90-day period.
        if affected < 20:
            return {
                "compliant": True,
                "reason": (
                    f"Layoff of {affected} at a {total}-employee establishment does not meet "
                    "the TULRCA §188 collective-redundancy threshold of 20+ proposed dismissals "
                    "at one establishment within a 90-day period."
                ),
                "recommendation": (
                    "Proceed as individual dismissals. Each requires the ACAS Code procedure "
                    "(investigation, written allegations, hearing, decision, appeal). For redundancy, "
                    "follow individual consultation and statutory redundancy pay where qualifying."
                ),
                "citation": "TULRCA 1992 §188",
            }
        consultation_days = 45 if affected >= 100 else 30
        return {
            "compliant": False,
            "reason": (
                f"Proposed redundancy of {affected} employees at a {total}-employee establishment "
                f"triggers TULRCA 1992 §188. Statutory consultation period of {consultation_days} "
                f"days is required before the first dismissal takes effect."
            ),
            "recommendation": (
                f"(1) Consult appropriate representatives (recognised trade union or elected "
                f"employee representatives) for at least {consultation_days} days before the first "
                f"dismissal. (2) Notify the Secretary of State via BEIS form HR1 at the same time "
                f"as consultation begins (criminal offence to omit). (3) Failure to consult exposes "
                f"the employer to a protective award of up to 90 days' gross pay per affected "
                f"employee under TULRCA §189, in addition to ordinary unfair dismissal liability."
            ),
            "citation": "TULRCA 1992 §188; §189 (protective award); §193 (HR1 notification)",
        }

    if country == "FR":
        # Code du travail Art. L1233-61: PSE for 10+ dismissals in 30 days at firms with 50+ employees.
        if total >= 50 and affected >= 10:
            return {
                "compliant": False,
                "reason": (
                    f"Proposed dismissal of {affected} employees in 30 days at a {total}-employee "
                    "firm triggers PSE (Plan de Sauvegarde de l'Emploi) requirement under Code du "
                    "travail Art. L1233-61."
                ),
                "recommendation": (
                    "(1) Draft a PSE including: measures to avoid or limit dismissals, reclassement "
                    "options within the group (including international), outplacement support (cellule "
                    "de reclassement or congé de reclassement). (2) Consult the CSE on the project "
                    "and the PSE. (3) Either negotiate an accord collectif majoritaire with unions OR "
                    "submit unilateral PSE for DREETS validation/approval. (4) Without an approved PSE, "
                    "individual dismissals in the collective procedure are null (Art. L1235-10)."
                ),
                "citation": "Code du travail Art. L1233-61 (PSE); Art. L1235-10 (nullity if PSE invalid)",
            }
        # Firms <50 employees with 10+ dismissals or firms 50+ with <10: still have CSE consultation duties,
        # but no PSE. Surface that distinction.
        if affected >= 10:
            return {
                "compliant": False,
                "reason": (
                    f"Proposed dismissal of {affected} employees in 30 days at a {total}-employee firm "
                    "is below the PSE threshold (firms <50 employees) but still triggers collective "
                    "consultation duties under Code du travail Art. L1233-8 et seq."
                ),
                "recommendation": (
                    "Consult CSE (where one exists), inform DREETS, and respect priority-of-rehiring "
                    "obligation. No PSE required at this firm size, but individual dismissals must still "
                    "follow the standard licenciement économique procedure."
                ),
                "citation": "Code du travail Art. L1233-8 et seq.",
            }
        return {
            "compliant": True,
            "reason": (
                f"Dismissal of {affected} employees does not meet the collective threshold "
                "(10+ in 30 days). Proceed as individual licenciement économique."
            ),
            "recommendation": (
                "Follow standard licenciement économique procedure for each employee: convocation, "
                "entretien préalable, notification with precise economic grounds. CSE information "
                "where applicable."
            ),
            "citation": "Code du travail Art. L1233-3, L1233-8",
        }

    if country == "US-TX":
        # Federal WARN only. No state WARN supplement in Texas.
        # 100+ employees, 50+ affected at single site OR 500+ affected, with 33% threshold
        # applying to layoffs of 50-499 (same as the US-CA federal WARN logic).
        federal_triggered = total >= 100 and (affected >= 500 or (affected >= 50 and affected / max(total, 1) >= 0.33))
        if not federal_triggered:
            return {
                "compliant": True,
                "reason": (
                    f"Layoff of {affected} at a {total}-employee Texas site does not trigger federal WARN "
                    "(under 50 affected OR fails 33% threshold) and Texas has no state WARN supplement."
                ),
                "recommendation": (
                    "Proceed as individual at-will terminations. For each: pay final wages within 6 calendar "
                    "days of discharge (Texas Labor Code §61.014(a)). Confirm no protected-class or retaliation "
                    "concerns. Send COBRA / Texas mini-COBRA notification."
                ),
                "citation": "29 USC §§2101-2109 (federal WARN); Texas Labor Code §61.014",
            }
        return {
            "compliant": False,
            "reason": (
                f"Layoff of {affected} at a {total}-employee Texas site triggers federal WARN. "
                "60 days advance written notice required."
            ),
            "recommendation": (
                "Issue 60 days advance written notice to: (1) affected employees or their representatives, "
                "(2) Texas state dislocated-worker unit, (3) chief elected official of the city or county where "
                "the site is located. Failure exposes the employer to 60 days back pay + benefits per affected "
                "employee plus $500/day civil penalty to the local government."
            ),
            "citation": "29 USC §§2101-2109 (federal WARN)",
        }

    if country == "US-NY":
        # NY WARN is broader than federal WARN. Both checked; the stricter controls.
        # NY WARN: 50+ employees AND (250+ affected OR (25+ affected AND 33% threshold)).
        # Federal WARN: 100+ employees AND (500+ OR (50+ AND 33%)).
        ny_triggered = total >= 50 and (affected >= 250 or (affected >= 25 and affected / max(total, 1) >= 0.33))
        federal_triggered = total >= 100 and (affected >= 500 or (affected >= 50 and affected / max(total, 1) >= 0.33))

        if not ny_triggered and not federal_triggered:
            return {
                "compliant": True,
                "reason": (
                    f"Layoff of {affected} at a {total}-employee NY site does not trigger NY WARN "
                    "(under 25 affected OR fails 33% threshold OR under 50 employees) nor federal WARN."
                ),
                "recommendation": (
                    "Proceed as individual at-will terminations. For each: pay final wages on the next "
                    "regularly scheduled payday (NY Labor Law §191). Late payment triggers §198(1-a) "
                    "liquidated damages of 100% plus attorney's fees. Confirm no NYSHRL or NYCHRL "
                    "discrimination or retaliation concerns. Send COBRA / NY State Continuation notice."
                ),
                "citation": "NY Labor Law §860 et seq. (NY WARN); 29 USC §§2101-2109 (federal WARN)",
            }

        trigger_summary = []
        if ny_triggered:
            trigger_summary.append("NY WARN")
        if federal_triggered:
            trigger_summary.append("Federal WARN")

        notice_days = 90 if ny_triggered else 60
        return {
            "compliant": False,
            "reason": (
                f"Layoff of {affected} at a {total}-employee NY site triggers "
                f"{' and '.join(trigger_summary)}. "
                f"{notice_days} days advance written notice required (NY WARN's 90-day rule controls "
                f"where applicable, being stricter than federal WARN's 60 days)."
            ),
            "recommendation": (
                f"Issue {notice_days} days advance written notice to: (1) affected employees, (2) NY "
                f"Department of Labor, (3) local Workforce Investment Board, (4) chief elected official "
                f"of the municipality where the site is located. Failure exposes employer to 60 days back "
                f"pay + benefits per affected employee plus $500/day civil penalty plus reasonable "
                f"attorney's fees recoverable by the State or in private action."
            ),
            "citation": "NY Labor Law §860 et seq. (NY WARN); 29 USC §§2101-2109 (federal WARN)",
        }

    if country == "IT":
        # Legge 223/1991 Arts. 4-5: firms 15+ employees, 5+ dismissals at the same
        # provincia within a 120-day window for the same economic/organisational reasons.
        triggered = total >= 15 and affected >= 5
        if not triggered:
            return {
                "compliant": True,
                "reason": (
                    f"Dismissal of {affected} at a {total}-employee firm does not meet the "
                    "licenziamento collettivo threshold under Legge 223/1991 (15+ employees AND "
                    "5+ dismissals in 120 days at the same provincia)."
                ),
                "recommendation": (
                    "Proceed as individual giustificato motivo oggettivo dismissals. Each requires "
                    "written form, motivated grounds, and (for pre-7-March-2015 hires at firms 15+) "
                    "prior conciliation at the Ispettorato Territoriale del Lavoro."
                ),
                "citation": "Legge 223/1991 Arts. 4-5",
            }
        return {
            "compliant": False,
            "reason": (
                f"Dismissal of {affected} at a {total}-employee firm triggers licenziamento "
                "collettivo procedure under Legge 223/1991. Mandatory three-phase consultation "
                "(comunicazione di avvio, esame congiunto, notification) with up to 45 days of "
                "esame congiunto with union representatives."
            ),
            "recommendation": (
                "(1) Comunicazione di avvio: written notification to RSU/sectoral unions AND "
                "concurrently to Ufficio Provinciale del Lavoro and Direzione Provinciale del "
                "Lavoro, detailing reasons, profiles of affected employees, timeline, and selection "
                "criteria. (2) Esame congiunto: up to 45 days of joint consultation. (3) On "
                "conclusion: notify labour authority of outcome and proceed with individual "
                "dismissal letters applying selection criteria (carichi di famiglia, anzianità di "
                "servizio, esigenze tecnico-produttive e organizzative per Art. 5). Failure to "
                "follow procedure renders dismissals null under the applicable Art. 18 / tutele "
                "crescenti regime."
            ),
            "citation": "Legge 223/1991 Arts. 4-5; selection criteria Art. 5",
        }

    if country == "SG":
        # MOM Mandatory Retrenchment Notification: firms with 10+ employees retrenching
        # 5+ within any 6-month period must file MRN with MOM within 5 working days.
        mrn_triggered = total >= 10 and affected >= 5
        if not mrn_triggered:
            return {
                "compliant": True,
                "reason": (
                    f"Retrenchment of {affected} at a {total}-employee firm does not meet the "
                    "Mandatory Retrenchment Notification threshold (employer 10+ employees AND "
                    "5+ retrenchments within any 6-month period)."
                ),
                "recommendation": (
                    "Proceed individually. Pay retrenchment benefit per MOM tripartite norm (2 "
                    "weeks to 1 month of salary per year of service for employees with 2+ years "
                    "tenure) and salary in lieu of statutory notice under §10 Employment Act."
                ),
                "citation": "MOM Tripartite Advisory (Dec 2020); Employment Act §10",
            }
        return {
            "compliant": False,
            "reason": (
                f"Retrenchment of {affected} at a {total}-employee firm triggers the MOM "
                "Mandatory Retrenchment Notification (MRN) requirement. The MRN must be filed "
                "within 5 working days of notifying affected employees."
            ),
            "recommendation": (
                "(1) Notify affected employees and pay retrenchment benefit per MOM tripartite "
                "norm: 2 weeks to 1 month of salary per year of service for employees with 2+ "
                "years tenure. Profitable employers in good standing pay at the upper end of the "
                "band. (2) File MRN with MOM via the MyMOM Portal within 5 working days of "
                "employee notification. (3) For foreign workers (EP/S Pass/Work Permit): cancel "
                "work pass within 7 days of last day and pay repatriation costs where applicable. "
                "(4) Final salary on last day or within 3 working days (Employment Act §22)."
            ),
            "citation": "MOM MRN rule (effective 2021-11-01); MOM Tripartite Advisory; Employment Act §22",
        }

    if country == "ZA":
        # LRA §189A scaled thresholds for large-scale retrenchment.
        # Employer must have 50+ employees AND affected employees must meet a tenure-scaled
        # threshold table. Simplified here: trigger §189A if total ≥ 50 AND affected ≥ 10.
        # §189 (small-scale) always applies if any retrenchment is proposed.
        if total < 50 or affected < 10:
            return {
                "compliant": False,
                "reason": (
                    f"Retrenchment of {affected} at a {total}-employee firm triggers LRA §189 "
                    "(small-scale retrenchment). Joint consensus-seeking consultation required."
                ),
                "recommendation": (
                    "(1) Issue §189(3) notice inviting consultation, covering reasons, proposed "
                    "dismissals, selection criteria, severance terms, and assistance with finding "
                    "alternative employment. (2) Joint consensus-seeking consultation with "
                    "consulting parties (registered union, workplace forum, or affected employees). "
                    "(3) Pay BCEA §41 severance: minimum 1 week's remuneration per completed year "
                    "of service. (4) Disputes refer to CCMA within 30 days under LRA §191. Failure "
                    "to consult procedurally fairly renders the dismissal procedurally unfair "
                    "(compensation up to 12 months under LRA §194)."
                ),
                "citation": "LRA §189; BCEA §41; LRA §191 (CCMA referral)",
            }
        return {
            "compliant": False,
            "reason": (
                f"Retrenchment of {affected} at a {total}-employee firm triggers LRA §189A "
                "(large-scale retrenchment). Extended 60-day consultation period required."
            ),
            "recommendation": (
                "(1) Issue §189(3) notice. (2) 60-day consultation period under §189A(2). "
                "(3) Either request CCMA-appointed facilitator OR (without facilitator) parties "
                "may proceed to strike action / Labour Court adjudication after consultation. "
                "(4) Pay BCEA §41 severance: minimum 1 week's remuneration per completed year of "
                "service. (5) Disputes refer to CCMA within 30 days under LRA §191. (6) "
                "Substantive fairness still required under LRA §188: economic / organisational "
                "rationale must hold up to scrutiny."
            ),
            "citation": "LRA §189A; LRA §189; BCEA §41; LRA §191",
        }

    if country == "ES":
        # Estatuto de los Trabajadores Art. 51: despido colectivo thresholds within 90-day window.
        # <100 employees: 10+. 100-300: 10%. >300: 30+. Plus any dismissal of entire workforce >5.
        if total < 100:
            threshold_met = affected >= 10
            threshold_desc = "10+ employees at a firm with <100 staff"
        elif total <= 300:
            threshold_met = affected >= max(1, int(0.10 * total))
            threshold_desc = f"10% of workforce (≥{max(1, int(0.10 * total))} at this firm size)"
        else:
            threshold_met = affected >= 30
            threshold_desc = "30+ employees at a firm with >300 staff"

        if not threshold_met:
            return {
                "compliant": True,
                "reason": (
                    f"Dismissal of {affected} at a {total}-employee firm does not meet the despido "
                    f"colectivo threshold ({threshold_desc}, 90-day window)."
                ),
                "recommendation": (
                    "Proceed as individual despido objetivo for each employee. Carta de despido with "
                    "ETOP justification, simultaneous tender of 20-day/year severance (capped 12 months), "
                    "and 15 days notice. SMAC conciliation step applies if challenged."
                ),
                "citation": "Estatuto de los Trabajadores Art. 51, Art. 53",
            }
        consultation_days = 30 if total >= 50 else 15
        return {
            "compliant": False,
            "reason": (
                f"Dismissal of {affected} at a {total}-employee firm triggers despido colectivo under "
                f"Estatuto de los Trabajadores Art. 51 ({threshold_desc}, 90-day window). Mandatory "
                f"período de consultas of {consultation_days} days with worker representatives."
            ),
            "recommendation": (
                f"(1) Notify the Autoridad Laboral at the start of the período de consultas. "
                f"(2) Conduct {consultation_days}-day consultation with worker representatives, "
                f"providing the substantial information dossier (causes, selection criteria, "
                f"redeployment measures, outplacement). (3) Apply the statutory floor of 20 days "
                f"per year of service per affected employee (cap 12 months), or the more generous "
                f"convenio colectivo terms where applicable. (4) Without consultation, individual "
                f"dismissals are improcedente / nulo."
            ),
            "citation": "Estatuto de los Trabajadores Art. 51",
        }

    return {
        "compliant": False,
        "reason": "Mass-layoff logic not implemented for this country.",
        "recommendation": "Escalate.",
        "citation": "",
    }


def _validate_terminate_protected(country: str, ctx: dict[str, Any]) -> dict[str, Any]:
    protection_type = ctx.get("protection_type", "")
    employment_type = ctx.get("employment_type", "full-time")
    rule = get_rule(country, employment_type)
    if rule is None:
        return {
            "compliant": False,
            "reason": f"No rule for ({country}, {employment_type}).",
            "recommendation": "Verify employment_type.",
            "citation": "",
        }

    matching = [p for p in rule.protections if p.name == protection_type]
    if not matching:
        return {
            "compliant": False,
            "reason": (
                f"Protection type '{protection_type}' not recognized for {country}/{employment_type}. "
                f"Known protections: {[p.name for p in rule.protections]}."
            ),
            "recommendation": "Verify the protection category and re-query, or escalate.",
            "citation": "",
        }

    p = matching[0]
    return {
        "compliant": False,
        "reason": (
            f"Ordinary termination of an employee in protected category '{p.name}' is BLOCKED. Scope: {p.scope}."
        ),
        "recommendation": (
            "Do NOT auto-execute. Escalate to HR/legal. Termination of a protected employee "
            "typically requires (a) authority approval (e.g., Aufsichtsbehörde for DE pregnancy, "
            "Integrationsamt for DE severely-disabled), (b) extraordinary cause, or "
            "(c) a court-approved process. Specific requirements vary by category."
        ),
        "citation": p.citation,
    }


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    mcp.run()
