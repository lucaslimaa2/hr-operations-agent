"""
Structured jurisdiction rules data.

Single source of truth is docs/jurisdiction.md. Every numeric value, every
formula, every citation here traces back to that document, which in turn
traces back to a primary legal source (statute or regulation).

Coverage:
  - BR + CLT  (Brazilian registered employee)
  - BR + PJ   (Brazilian contractor)
  - DE        (German employment — single rule covers probation + post-probation
              via tenure brackets, per BGB §622)
  - US-CA     (California at-will + final-pay obligations)

Any other country resolves to a "not covered" response — see
UNCOVERED_COUNTRIES_MESSAGE. This is deliberate: per the architectural
principle in CLAUDE.md, the engine must never hallucinate rules.

Design notes:
  - Notice periods support two value modes (days OR months-to-end-of-month)
    because DE's BGB §622 is calendar-aware, not a day count.
  - All models are frozen pydantic BaseModels for immutability.
  - Lookup is by (country, employment_type) composite key.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# =============================================================================
# Models
# =============================================================================


class _Frozen(BaseModel):
    """Base for immutable rule models."""

    model_config = ConfigDict(frozen=True)


class NoticeBracket(_Frozen):
    """A tenure range and its corresponding notice period.

    Either `days` or `months` will be set, not both. `months` + `to_end_of_month`
    captures DE's "X months to the end of the calendar month" rule, which
    cannot be honestly expressed as a fixed day count.
    """

    min_tenure_months: int  # inclusive
    max_tenure_months: int | None = None  # exclusive; None = unbounded
    days: int = 0
    months: int = 0
    to_end_of_month: bool = False
    description: str = ""
    citation: str = ""

    def matches(self, tenure_months: int) -> bool:
        if tenure_months < self.min_tenure_months:
            return False
        if self.max_tenure_months is None:
            return True
        return tenure_months < self.max_tenure_months

    def minimum_days_estimate(self) -> int:
        """Conservative day count for comparison purposes only.

        For day-based rules: exact.
        For month-based rules: months * 30 (lower bound — actual notice extends
        to end of calendar month).
        """
        if self.days:
            return self.days
        return self.months * 30


class NoticeRule(_Frozen):
    """How to compute the notice period for one country/employment_type.

    Two forms:
      - `brackets`: tenure-graded lookup (used by DE).
      - `base_days` + `days_per_year` + `max_additional_days`: linear formula
        (used by BR CLT aviso prévio proporcional).
      - If neither is populated, falls back to `base_days` only (flat rule).
    """

    base_days: int = 0
    days_per_year: int = 0
    max_additional_days: int | None = None
    brackets: tuple[NoticeBracket, ...] = ()
    description: str = ""
    citation: str = ""

    def resolve(self, tenure_months: int) -> NoticeBracket:
        """Return the bracket (or synthesized bracket) that applies."""
        if self.brackets:
            for b in self.brackets:
                if b.matches(tenure_months):
                    return b
            raise ValueError(
                f"No notice bracket matches tenure {tenure_months}mo "
                f"(brackets cover {self.brackets[0].min_tenure_months}+ months)"
            )
        full_years = tenure_months // 12
        additional = self.days_per_year * full_years
        if self.max_additional_days is not None:
            additional = min(additional, self.max_additional_days)
        return NoticeBracket(
            min_tenure_months=0,
            days=self.base_days + additional,
            description=self.description,
            citation=self.citation,
        )


class SeveranceComponent(_Frozen):
    """One line item of severance / final pay (e.g., 13º proporcional, FGTS multa)."""

    name: str
    formula: str  # human-readable formula, e.g. "0.40 * accumulated_fgts_balance"
    citation: str
    notes: str = ""


class Protection(_Frozen):
    """A protected category that blocks ordinary termination (e.g., pregnancy)."""

    name: str
    scope: str  # human-readable scope, e.g. "from confirmation through 5mo postpartum"
    citation: str
    blocks_termination: bool = True


class JurisdictionRule(_Frozen):
    """Complete termination rule set for one country + employment_type."""

    country: str
    employment_type: str
    legal_framework: str
    employer_notice: NoticeRule
    employee_notice: NoticeRule | None = None  # falls back to employer_notice if None
    severance_components: tuple[SeveranceComponent, ...] = ()
    protections: tuple[Protection, ...] = ()
    mandatory_steps: tuple[str, ...] = ()
    at_will: bool = False
    final_pay_deadline: str = ""  # e.g., "immediate at termination"
    notes: str = ""


# =============================================================================
# Country rules
# =============================================================================
# Citations reference jurisdiction.md sections + the primary statute. When
# updating, edit jurisdiction.md FIRST, then update here.
# =============================================================================


# -----------------------------------------------------------------------------
# Brazil — CLT (registered employee)
# Source: docs/jurisdiction.md §"Brazil (BR) → CLT"
# -----------------------------------------------------------------------------

BR_CLT = JurisdictionRule(
    country="BR",
    employment_type="CLT",
    legal_framework=(
        "CLT (Decreto-Lei 5.452/1943), Lei 12.506/2011 (aviso prévio proporcional), "
        "Lei 8.036/1990 (FGTS), Constituição Federal Art. 7º"
    ),
    employer_notice=NoticeRule(
        base_days=30,
        days_per_year=3,
        max_additional_days=60,  # caps total at 90 days
        description="Aviso prévio proporcional: 30 base + 3/year, +60 cap (max 90 days total)",
        citation="Lei 12.506/2011, parágrafo único; CLT Art. 487",
    ),
    employee_notice=NoticeRule(
        base_days=30,
        description="Employee resignation: fixed 30 days. The +3/year scaling applies only to employer-initiated termination.",
        citation="CLT Art. 487 + TST consolidated jurisprudence on Lei 12.506/2011",
    ),
    severance_components=(
        SeveranceComponent(
            name="Saldo de salário",
            formula="(monthly_salary / 30) * days_worked_in_final_month",
            citation="CLT Art. 462",
        ),
        SeveranceComponent(
            name="Aviso prévio",
            formula="monthly_salary * (notice_days / 30)  # if indenizado",
            citation="CLT Art. 487, Lei 12.506/2011",
        ),
        SeveranceComponent(
            name="13º salário proporcional",
            formula="(monthly_salary / 12) * months_worked_in_year",
            notes="Months with 15+ days worked count as full months.",
            citation="Lei 4.090/1962",
        ),
        SeveranceComponent(
            name="Férias vencidas + 1/3",
            formula="monthly_salary + monthly_salary / 3  # per accrued vacation period",
            citation="CF Art. 7º, XVII; CLT Art. 142",
        ),
        SeveranceComponent(
            name="Férias proporcionais + 1/3",
            formula="(monthly_salary * months_in_period / 12) * (1 + 1/3)",
            citation="CF Art. 7º, XVII; CLT Art. 146",
        ),
        SeveranceComponent(
            name="FGTS multa rescisória (40%)",
            formula="0.40 * accumulated_fgts_balance",
            notes="Only on termination WITHOUT cause. Employee separately withdraws the full FGTS balance.",
            citation="Lei 8.036/1990, Art. 18 §1º",
        ),
        SeveranceComponent(
            name="Guia para seguro-desemprego",
            formula="form_issuance_only",
            notes="Employer must issue the form; the unemployment benefit itself is paid by the government.",
            citation="Lei 7.998/1990",
        ),
    ),
    protections=(
        Protection(
            name="pregnant_employee",
            scope="from confirmation of pregnancy through 5 months postpartum",
            citation="ADCT Art. 10, II, b",
        ),
        Protection(
            name="cipa_member",
            scope="from candidacy through 1 year after end of mandate",
            citation="CLT Art. 165",
        ),
        Protection(
            name="union_director",
            scope="from candidacy through 1 year after end of mandate",
            citation="CF Art. 8º, VIII",
        ),
        Protection(
            name="accident_leave_return",
            scope="12 months after return from auxílio-doença acidentário",
            citation="Lei 8.213/1991, Art. 118",
        ),
        Protection(
            name="pre_retirement",
            scope="varies by CBA, typically 12-24 months before retirement eligibility",
            citation="Per applicable collective bargaining agreement (CCT/ACT)",
        ),
    ),
    mandatory_steps=(
        "Pay all verbas rescisórias within 10 days of termination notice (CLT Art. 477 §6º).",
        "Deposit FGTS multa rescisória into employee's FGTS account.",
        "Issue Guia GRRF and Guia CD/SD (seguro-desemprego).",
        "Issue Termo de Rescisão de Contrato de Trabalho (TRCT).",
        "Annotate carteira de trabalho (CTPS) with termination date and reason.",
    ),
    final_pay_deadline="Within 10 days of termination notice (CLT Art. 477 §6º)",
    notes=(
        "Three termination modes (rescisão): sem justa causa (without cause — full verbas), "
        "com justa causa (with cause — drastically reduced, Art. 482), and rescisão indireta "
        "(employee-initiated for employer fault — equivalent to without-cause entitlements, Art. 483). "
        "Acordo (mutual agreement, Art. 484-A) halves notice and FGTS multa to 20%."
    ),
)


# -----------------------------------------------------------------------------
# Brazil — PJ (contractor / pessoa jurídica)
# Source: docs/jurisdiction.md §"Brazil (BR) → PJ"
# -----------------------------------------------------------------------------

BR_PJ = JurisdictionRule(
    country="BR",
    employment_type="PJ",
    legal_framework=(
        "Código Civil (Lei 10.406/2002), Arts. 593–609 (contrato de prestação de serviços); "
        "Lei 11.196/2005, Art. 129; CLT Art. 3º (vínculo empregatício test)"
    ),
    employer_notice=NoticeRule(
        base_days=30,
        description=(
            "No statutory aviso prévio. Civil Code 'reasonable notice' default ≈ 30 days "
            "for indefinite-term service contracts if contract is silent. Boa-fé objetiva principle."
        ),
        citation="Código Civil Art. 599 + boa-fé objetiva (Art. 422)",
    ),
    employee_notice=None,  # symmetric — same as employer
    severance_components=(),  # none — contract terms only
    protections=(),
    mandatory_steps=(
        "Honor contractual notice period (or 30-day default if silent).",
        "Pay any outstanding invoices through contract end date.",
        "Issue final nota fiscal acceptance and any contractual settlement.",
    ),
    final_pay_deadline="Per contract terms (typically final invoice cycle).",
    notes=(
        "CRITICAL RISK: vínculo empregatício re-classification. If the relationship meets all "
        "four CLT Art. 3º criteria (pessoalidade, não-eventualidade, onerosidade, subordinação), "
        "the Justiça do Trabalho can re-classify retroactively as CLT employment, triggering full "
        "back-payment of FGTS, 13º, férias, INSS plus 40% multa and moral damages. Statute of "
        "limitations: 2yr to file after end of relationship, 5yr of back-claims (CF Art. 7º, XXIX). "
        "ENGINE BEHAVIOR: any PJ termination should surface this risk in the escalation brief."
    ),
)


# -----------------------------------------------------------------------------
# Germany — full-time employee
# Source: docs/jurisdiction.md §"Germany (DE)"
#
# Single rule covers probation AND post-probation via tenure brackets:
#   <6mo  → 2 weeks (BGB §622(3)) — Probezeit
#   ≥6mo  → BGB §622(2) tenure-graded schedule, to end of calendar month
# -----------------------------------------------------------------------------

DE_NOTICE_BRACKETS = (
    NoticeBracket(
        min_tenure_months=0,
        max_tenure_months=6,
        days=14,
        description="Probezeit: 2 weeks, no specified termination date",
        citation="BGB §622(3)",
    ),
    NoticeBracket(
        min_tenure_months=6,
        max_tenure_months=24,
        days=28,  # 4 weeks
        description="4 weeks to the 15th or end of calendar month",
        citation="BGB §622(1)",
    ),
    NoticeBracket(
        min_tenure_months=24,
        max_tenure_months=60,
        months=1,
        to_end_of_month=True,
        description="1 month to end of calendar month",
        citation="BGB §622(2) Nr. 1",
    ),
    NoticeBracket(
        min_tenure_months=60,
        max_tenure_months=96,
        months=2,
        to_end_of_month=True,
        description="2 months to end of calendar month",
        citation="BGB §622(2) Nr. 2",
    ),
    NoticeBracket(
        min_tenure_months=96,
        max_tenure_months=120,
        months=3,
        to_end_of_month=True,
        description="3 months to end of calendar month",
        citation="BGB §622(2) Nr. 3",
    ),
    NoticeBracket(
        min_tenure_months=120,
        max_tenure_months=144,
        months=4,
        to_end_of_month=True,
        description="4 months to end of calendar month",
        citation="BGB §622(2) Nr. 4",
    ),
    NoticeBracket(
        min_tenure_months=144,
        max_tenure_months=180,
        months=5,
        to_end_of_month=True,
        description="5 months to end of calendar month",
        citation="BGB §622(2) Nr. 5",
    ),
    NoticeBracket(
        min_tenure_months=180,
        max_tenure_months=240,
        months=6,
        to_end_of_month=True,
        description="6 months to end of calendar month",
        citation="BGB §622(2) Nr. 6",
    ),
    NoticeBracket(
        min_tenure_months=240,
        max_tenure_months=None,
        months=7,
        to_end_of_month=True,
        description="7 months to end of calendar month",
        citation="BGB §622(2) Nr. 7",
    ),
)


DE_FULL_TIME = JurisdictionRule(
    country="DE",
    employment_type="full-time",
    legal_framework=(
        "BGB §§620–630 (employment contracts), §622 (notice periods), §626 (extraordinary termination); "
        "Kündigungsschutzgesetz (KSchG) — applies post-6mo in establishments >10 employees; "
        "BetrVG §102 (Betriebsrat consultation); MuSchG, BEEG, SGB IX (categorical protections)"
    ),
    employer_notice=NoticeRule(
        brackets=DE_NOTICE_BRACKETS,
        description="Statutory notice scales with tenure; >6mo notice ends on the last day of a calendar month.",
        citation="BGB §622",
    ),
    employee_notice=NoticeRule(
        base_days=28,  # 4 weeks
        description=(
            "Employee resignation: 4 weeks to the 15th or end of month, regardless of tenure "
            "(unless contract reciprocates the longer employer periods)."
        ),
        citation="BGB §622(1)",
    ),
    severance_components=(
        SeveranceComponent(
            name="Urlaubsabgeltung (vacation payout)",
            formula="daily_wage * untaken_vacation_days",
            citation="BUrlG §7(4)",
        ),
        SeveranceComponent(
            name="Regelabfindung (severance — voluntary safe-harbor)",
            formula="0.5 * monthly_gross_salary * years_of_service",
            notes=(
                "Not automatic. Offered by employer per KSchG §1a for operational terminations, "
                "or negotiated in Arbeitsgericht settlement. Market range: 0.5–1.5 monthly salaries per year."
            ),
            citation="KSchG §1a",
        ),
        SeveranceComponent(
            name="13. Monatsgehalt / Weihnachtsgeld pro-rata",
            formula="contractual_13th * (months_worked_in_year / 12)",
            notes="Only if contractually owed; not statutory.",
            citation="Contract / CBA dependent",
        ),
    ),
    protections=(
        Protection(
            name="pregnant_employee",
            scope="from start of pregnancy through 4 months postpartum (Aufsichtsbehörde consent required)",
            citation="MuSchG §17",
        ),
        Protection(
            name="parental_leave",
            scope="during Elternzeit",
            citation="BEEG §18",
        ),
        Protection(
            name="severely_disabled",
            scope="after 6 months of employment (Integrationsamt consent required)",
            citation="SGB IX §168",
        ),
        Protection(
            name="works_council_member",
            scope="during term + 1 year after (ordinary termination blocked except with Betriebsrat consent)",
            citation="KSchG §15",
        ),
    ),
    mandatory_steps=(
        "If a Betriebsrat exists: consult before issuing termination (BetrVG §102). Failure renders termination void.",
        "If KSchG applies (>6mo tenure + >10 employees): document social justification (operational, conduct, or personal).",
        "Issue Arbeitszeugnis (employment certificate) on request — GewO §109.",
        "Pay Urlaubsabgeltung for accrued vacation.",
        "If mass layoff thresholds met (KSchG §17): notify Bundesagentur für Arbeit BEFORE terminations.",
    ),
    final_pay_deadline="Next regular payroll date per employment contract.",
    notes=(
        "KSchG applies only when BOTH conditions met: (1) employee tenure >6mo and (2) employer "
        ">10 employees. When KSchG applies, termination requires social justification on one of "
        "three grounds: betriebsbedingt, verhaltensbedingt, personenbedingt. Severance is NOT "
        "automatic — it is offered or negotiated. Employee has 3 weeks from termination notice "
        "to file at Arbeitsgericht (KSchG §4)."
    ),
)


# -----------------------------------------------------------------------------
# United States — California
# Source: docs/jurisdiction.md §"United States — California (US-CA)"
# -----------------------------------------------------------------------------

US_CA_FULL_TIME = JurisdictionRule(
    country="US-CA",
    employment_type="full-time",
    legal_framework=(
        "California Labor Code §2922 (at-will), §§201–203 (final pay), §227.3 (vacation as wages), "
        "§§1400–1408 (Cal-WARN); 29 USC §§2101–2109 (federal WARN); "
        "FEHA (Gov Code §12940+) and common-law exceptions (Tameny, Foley)"
    ),
    employer_notice=NoticeRule(
        base_days=0,
        description=(
            "At-will: no statutory notice. Either party may terminate at any time without notice. "
            "EXCEPTION: WARN/Cal-WARN require 60 days notice for qualifying mass layoffs."
        ),
        citation="Cal. Lab. Code §2922",
    ),
    employee_notice=NoticeRule(
        base_days=0,
        description="At-will: no statutory notice required from employee.",
        citation="Cal. Lab. Code §2922",
    ),
    severance_components=(
        SeveranceComponent(
            name="Earned wages through last hour worked",
            formula="hourly_or_salaried_wages_through_termination",
            citation="Cal. Lab. Code §201",
        ),
        SeveranceComponent(
            name="Accrued vacation / vested PTO",
            formula="daily_wage * accrued_vacation_days",
            notes="Vested vacation is wages; use-it-or-lose-it policies are unlawful in CA.",
            citation="Cal. Lab. Code §227.3",
        ),
        SeveranceComponent(
            name="Earned commissions / bonuses (if calculable)",
            formula="per_commission_plan",
            notes="If not calculable at termination, paid when calculable.",
            citation="Cal. Lab. Code §204",
        ),
        SeveranceComponent(
            name="Waiting time penalty (if final pay is late)",
            formula="daily_wage * min(days_late, 30)",
            notes="Triggered by any willful failure to pay on time, including administrative error.",
            citation="Cal. Lab. Code §203",
        ),
    ),
    protections=(
        Protection(
            name="protected_class_FEHA",
            scope="termination based on race, sex, religion, age 40+, disability, pregnancy, etc.",
            citation="Cal. Gov. Code §12940 (FEHA)",
        ),
        Protection(
            name="retaliation_for_protected_activity",
            scope="workers' comp claim, whistleblower, harassment report, union activity, protected leave",
            citation="Cal. Lab. Code §1102.5 and related",
        ),
        Protection(
            name="public_policy_violation",
            scope="termination contravening a fundamental public policy (Tameny)",
            citation="Tameny v. Atlantic Richfield Co., 27 Cal.3d 167 (1980)",
        ),
        Protection(
            name="implied_contract",
            scope="employer statements, handbooks, or long tenure creating implied for-cause term",
            citation="Foley v. Interactive Data Corp., 47 Cal.3d 654 (1988)",
        ),
    ),
    mandatory_steps=(
        "Pay final wages IMMEDIATELY at termination for involuntary terminations (Cal. Lab. Code §201).",
        "Include accrued vacation in final paycheck (§227.3).",
        "Provide CA EDD pamphlet DE 2320 (For Your Benefit).",
        "Send COBRA / Cal-COBRA notification within 14 days (employer to plan admin).",
        "If layoff size + employer size cross WARN thresholds: 60 days advance written notice required (whichever is broader between federal WARN and Cal-WARN applies).",
    ),
    at_will=True,
    final_pay_deadline=(
        "Involuntary: immediate at termination (Cal. Lab. Code §201). "
        "Voluntary with 72+ hr notice: last day worked (§202). "
        "Voluntary without notice: within 72 hours."
    ),
    notes=(
        "At-will is the default rule but has five major exceptions (FEHA, retaliation, public policy, "
        "implied contract, implied covenant). The strictest practical constraint in CA is not "
        "termination itself but the final-pay timing — the §203 waiting time penalty accrues at "
        "the employee's daily wage for up to 30 days of delay. "
        "For mass layoffs: federal WARN (100+ ee, 50+ affected, 33% threshold) AND Cal-WARN "
        "(75+ ee, 50+ affected, no percentage threshold) — Cal-WARN is broader and usually controls."
    ),
)


# =============================================================================
# Registry + lookup
# =============================================================================

# Key: (country, employment_type) → JurisdictionRule.
# Aliases for common synonyms are added below.
_RULES: dict[tuple[str, str], JurisdictionRule] = {
    ("BR", "CLT"): BR_CLT,
    ("BR", "PJ"): BR_PJ,
    ("DE", "full-time"): DE_FULL_TIME,
    ("US-CA", "full-time"): US_CA_FULL_TIME,
}

# Synonyms — let the orchestrator pass natural variants without forcing
# canonical strings at the call site.
_EMPLOYMENT_TYPE_ALIASES: dict[str, str] = {
    "clt": "CLT",
    "registered": "CLT",
    "employee": "CLT",  # only valid for BR
    "pj": "PJ",
    "contractor": "PJ",  # only valid for BR
    "pessoa juridica": "PJ",
    "full_time": "full-time",
    "fulltime": "full-time",
    "ft": "full-time",
}


COVERED_COUNTRIES: frozenset[str] = frozenset({"BR", "DE", "US-CA"})


UNCOVERED_COUNTRIES_MESSAGE = (
    "Jurisdiction not covered. This engine has rules for: BR (CLT, PJ), DE, US-CA. "
    "For other jurisdictions, recommend specialist legal review before any termination action."
)


def normalize_employment_type(employment_type: str, country: str) -> str:
    """Map common synonyms to the canonical employment_type for a country."""
    normalized = _EMPLOYMENT_TYPE_ALIASES.get(employment_type.lower(), employment_type)
    # For non-BR countries, 'contractor'/'employee' don't map cleanly — they're BR-specific concepts.
    if country != "BR" and normalized in {"CLT", "PJ"}:
        return employment_type  # let lookup fail meaningfully
    return normalized


def get_rule(country: str, employment_type: str) -> JurisdictionRule | None:
    """Look up the rule for a (country, employment_type) pair.

    Returns None if no rule is registered for that combination.
    Use is_covered() to distinguish "not covered" from "wrong employment_type".
    """
    et = normalize_employment_type(employment_type, country)
    return _RULES.get((country, et))


def is_covered(country: str) -> bool:
    """True if the engine has any rules for this country."""
    return country in COVERED_COUNTRIES
