"""
Structured jurisdiction rules data.

Single source of truth is docs/jurisdiction.md. Every numeric value, every
formula, every citation here traces back to that document, which in turn
traces back to a primary legal source (statute or regulation).

Coverage:
  - BR + CLT      (Brazilian registered employee)
  - BR + PJ       (Brazilian contractor)
  - DE            (German employment — single rule covers probation + post-probation
                   via tenure brackets, per BGB §622)
  - US-CA         (California at-will + final-pay obligations)
  - UK            (ERA 1996 §86 tenure-scaled notice + statutory redundancy pay)
  - FR + non-cadre (default for FR — Art. L1234-1 1/2 month rule)
  - FR + cadre    (manager-level — typically 3 months notice via CCN)
  - ES            (Estatuto de los Trabajadores — despido objetivo / improcedente split)

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


# -----------------------------------------------------------------------------
# United Kingdom — full-time
# Source: docs/jurisdiction.md §"United Kingdom (UK)"
#
# ERA 1996 §86 notice scaling: 0 days <1mo; 1 week 1mo to <2yr; then 1 week per
# year of service from year 2 to year 12; capped at 12 weeks. Modeled as 13
# explicit brackets to keep each year cleanly auditable.
# -----------------------------------------------------------------------------

UK_NOTICE_BRACKETS = (
    NoticeBracket(
        min_tenure_months=0,
        max_tenure_months=1,
        days=0,
        description="No statutory notice under 1 month tenure",
        citation="ERA 1996 §86",
    ),
    NoticeBracket(
        min_tenure_months=1,
        max_tenure_months=24,
        days=7,
        description="1 week (tenure 1 month to <2 years)",
        citation="ERA 1996 §86(1)(a)",
    ),
    NoticeBracket(
        min_tenure_months=24,
        max_tenure_months=36,
        days=14,
        description="2 weeks at 2 years tenure",
        citation="ERA 1996 §86(1)(b)",
    ),
    NoticeBracket(
        min_tenure_months=36,
        max_tenure_months=48,
        days=21,
        description="3 weeks at 3 years tenure",
        citation="ERA 1996 §86(1)(b)",
    ),
    NoticeBracket(
        min_tenure_months=48,
        max_tenure_months=60,
        days=28,
        description="4 weeks at 4 years tenure",
        citation="ERA 1996 §86(1)(b)",
    ),
    NoticeBracket(
        min_tenure_months=60,
        max_tenure_months=72,
        days=35,
        description="5 weeks at 5 years tenure",
        citation="ERA 1996 §86(1)(b)",
    ),
    NoticeBracket(
        min_tenure_months=72,
        max_tenure_months=84,
        days=42,
        description="6 weeks at 6 years tenure",
        citation="ERA 1996 §86(1)(b)",
    ),
    NoticeBracket(
        min_tenure_months=84,
        max_tenure_months=96,
        days=49,
        description="7 weeks at 7 years tenure",
        citation="ERA 1996 §86(1)(b)",
    ),
    NoticeBracket(
        min_tenure_months=96,
        max_tenure_months=108,
        days=56,
        description="8 weeks at 8 years tenure",
        citation="ERA 1996 §86(1)(b)",
    ),
    NoticeBracket(
        min_tenure_months=108,
        max_tenure_months=120,
        days=63,
        description="9 weeks at 9 years tenure",
        citation="ERA 1996 §86(1)(b)",
    ),
    NoticeBracket(
        min_tenure_months=120,
        max_tenure_months=132,
        days=70,
        description="10 weeks at 10 years tenure",
        citation="ERA 1996 §86(1)(b)",
    ),
    NoticeBracket(
        min_tenure_months=132,
        max_tenure_months=144,
        days=77,
        description="11 weeks at 11 years tenure",
        citation="ERA 1996 §86(1)(b)",
    ),
    NoticeBracket(
        min_tenure_months=144,
        max_tenure_months=None,
        days=84,
        description="12 weeks (statutory cap at 12+ years)",
        citation="ERA 1996 §86(1)(c)",
    ),
)


UK_FULL_TIME = JurisdictionRule(
    country="UK",
    employment_type="full-time",
    legal_framework=(
        "Employment Rights Act 1996 (notice §86, unfair dismissal §§94-98, "
        "redundancy pay §§135, 162); TULRCA 1992 §188 (collective redundancy); "
        "PIDA 1998 (whistleblowing); Equality Act 2010; ACAS Code of Practice"
    ),
    employer_notice=NoticeRule(
        brackets=UK_NOTICE_BRACKETS,
        description="Statutory minimum: 1 week per year of service, capped at 12 weeks. Contract may extend.",
        citation="ERA 1996 §86",
    ),
    employee_notice=NoticeRule(
        base_days=7,
        description="Employee resignation: 1 week statutory minimum after 1 month of service, regardless of tenure (contract may extend).",
        citation="ERA 1996 §86(2)",
    ),
    severance_components=(
        SeveranceComponent(
            name="Statutory redundancy pay (after 2 years tenure, age-weighted)",
            formula="0.5*weeks_pay*years_under_22 + 1.0*weeks_pay*years_22_to_40 + 1.5*weeks_pay*years_41_plus",
            notes="Only paid when dismissal qualifies as redundancy (role/site closed). Cap: 20 years of service (most recent). Week's pay capped at statutory weekly maximum (~£700; verify current government source). Tax-free up to £30,000 under ITEPA 2003 §403.",
            citation="ERA 1996 §§135, 162",
        ),
        SeveranceComponent(
            name="Accrued holiday payout",
            formula="daily_pay * untaken_holiday_days",
            citation="Working Time Regulations 1998 reg. 14",
        ),
        SeveranceComponent(
            name="PILON (where contract permits)",
            formula="weekly_pay * statutory_or_contractual_notice_weeks",
            notes="Taxable as earnings since April 2018 (ITEPA 2003 §402B). Without a PILON clause, paying in lieu is a technical contract breach (rarely actionable in practice).",
            citation="ITEPA 2003 §402B",
        ),
    ),
    protections=(
        Protection(
            name="pregnancy_or_maternity",
            scope="from pregnancy through end of maternity leave; dismissal automatically unfair (no qualifying period)",
            citation="ERA 1996 §99",
        ),
        Protection(
            name="trade_union_activity",
            scope="dismissal for trade union membership or activities is automatically unfair (no qualifying period)",
            citation="TULRCA 1992 §152",
        ),
        Protection(
            name="whistleblower",
            scope="qualifying protected disclosure under PIDA 1998; dismissal automatically unfair (no qualifying period)",
            citation="ERA 1996 §103A; PIDA 1998",
        ),
        Protection(
            name="protected_characteristic",
            scope="any Equality Act 2010 protected characteristic (age, disability, race, sex, etc.); no qualifying period",
            citation="Equality Act 2010",
        ),
    ),
    mandatory_steps=(
        "Follow ACAS Code of Practice: investigation, written allegations, hearing, decision, right of appeal. Failure can produce up to 25% uplift on tribunal awards (TULRCA 1992 §207A).",
        "ACAS Early Conciliation mandatory before any tribunal claim (Employment Tribunals Act 1996 §18A).",
        "Issue P45 within statutory timescale.",
        "Pay accrued holiday under Working Time Regulations 1998 reg. 14.",
        "For collective redundancy (20+ in 90 days at one establishment): notify Secretary of State via BEIS form HR1 and consult appropriate representatives (TULRCA 1992 §188).",
    ),
    final_pay_deadline="Next regular payday after termination; P45 within statutory timescale.",
    notes=(
        "Two key tenure thresholds: 2 years unlocks ordinary unfair dismissal under ERA 1996 §94 and statutory redundancy pay; 12 years caps statutory notice at 12 weeks. "
        "Contract may specify longer notice; the contractual period applies if it exceeds the statutory minimum. "
        "Five potentially fair reasons under §98(2): capability, conduct, redundancy, statutory restriction, 'some other substantial reason'. "
        "Settlement agreements under ERA 1996 §203 are the only enforceable mechanism for the employee to waive statutory claims (require independent legal advice paid by the employer). "
        "Wrongful dismissal (contract-law claim for breach of notice) is distinct from unfair dismissal: no qualifying period, no statutory cap, damages limited to the notice period."
    ),
)


# -----------------------------------------------------------------------------
# France — non-cadre (default for "FR" when category not specified)
# Source: docs/jurisdiction.md §"France (FR)"
# -----------------------------------------------------------------------------

FR_NON_CADRE_NOTICE_BRACKETS = (
    NoticeBracket(
        min_tenure_months=0,
        max_tenure_months=6,
        days=0,
        description="Less than 6 months tenure: notice per contract / CCN; no statutory floor under Art. L1234-1",
        citation="Code du travail Art. L1234-1",
    ),
    NoticeBracket(
        min_tenure_months=6,
        max_tenure_months=24,
        days=30,
        months=1,
        description="1 month statutory notice for non-cadre, tenure 6 months to <2 years",
        citation="Code du travail Art. L1234-1",
    ),
    NoticeBracket(
        min_tenure_months=24,
        max_tenure_months=None,
        days=60,
        months=2,
        description="2 months statutory notice for non-cadre, tenure ≥2 years",
        citation="Code du travail Art. L1234-1",
    ),
)

# Shared components between FR non-cadre and cadre (same statutory base).
_FR_SEVERANCE_COMPONENTS = (
    SeveranceComponent(
        name="Indemnité de licenciement (after 8 months tenure)",
        formula="(0.25 * monthly_salary * min(years_of_service, 10)) + (0.333 * monthly_salary * max(years_of_service - 10, 0))",
        notes="1/4 month per year first 10 years; 1/3 month per year thereafter. Pro-rata in months, not just full years. Applicable CCN may provide a more generous formula; the more generous applies. Not payable for faute grave or faute lourde. Tax-free within statutory limits (CGI Art. 80 duodecies).",
        citation="Code du travail Art. L1234-9 and R1234-2",
    ),
    SeveranceComponent(
        name="Indemnité compensatrice de préavis (PILON equivalent)",
        formula="monthly_salary * notice_period_months",
        notes="Paid where notice is not worked (employer-initiated dispense de préavis). Not owed where dismissal is for faute grave or faute lourde.",
        citation="Code du travail Art. L1234-5",
    ),
    SeveranceComponent(
        name="Indemnité compensatrice de congés payés",
        formula="(monthly_salary * acquired_days_remaining) / 21.67",
        notes="Settlement of accrued but untaken paid leave at termination.",
        citation="Code du travail Art. L3141-28",
    ),
)

_FR_PROTECTIONS = (
    Protection(
        name="salaries_proteges",
        scope="CSE members, union delegates, conseillers du salarié, conseillers prud'hommes; dismissal requires prior Inspection du travail authorisation. Lack of authorisation renders dismissal automatically null.",
        citation="Code du travail Art. L2411-1 et seq.",
    ),
    Protection(
        name="pregnancy_or_maternity",
        scope="during pregnancy, maternity leave, and the 10 weeks following return. Exceptions narrowly limited to faute grave unconnected to pregnancy or impossibility unconnected to pregnancy.",
        citation="Code du travail Art. L1225-4",
    ),
    Protection(
        name="parental_leave",
        scope="during congé parental d'éducation; same protective regime as maternity",
        citation="Code du travail Art. L1225-55",
    ),
    Protection(
        name="inaptitude_medicale",
        scope="medical inaptitude requires the employer to search for reclassement options before dismissal can proceed",
        citation="Code du travail Art. L1226-2 (non-occupational), L1226-10 (occupational origin)",
    ),
)

_FR_MANDATORY_STEPS = (
    "Convocation à entretien préalable: written notice (registered or hand-delivered), at least 5 working days before the interview (Art. L1232-2).",
    "Entretien préalable: employer states grounds and hears employee response. No decision communicated at the interview itself (Art. L1232-3).",
    "Notification du licenciement: registered letter with acknowledgement, minimum 2 working days after the interview. Letter must state precise grounds (Art. L1232-6).",
    "For licenciement économique: CSE consultation, priority-of-rehiring obligation, and a PSE if collective thresholds are crossed.",
    "For salariés protégés: prior Inspection du travail authorisation required.",
)

_FR_NOTES = (
    "Statute of limitations for unfair dismissal claims: 12 months from notification (Code du travail Art. L1471-1). "
    "Barème Macron (Art. L1235-3) caps unfair dismissal damages between 1 and 20 months of gross salary by tenure. "
    "Scale does not apply to dismissals tainted by discrimination, harassment, or violation of fundamental rights (minimum 6 months, uncapped, under Art. L1235-3-1). "
    "Rupture conventionnelle (Art. L1237-11) is a common negotiated alternative: written agreement, 15-day withdrawal period each side, DREETS homologation, employee retains unemployment benefits."
)


FR_NON_CADRE = JurisdictionRule(
    country="FR",
    employment_type="non-cadre",
    legal_framework=(
        "Code du travail: Art. L1221-19 (période d'essai), L1232-2 to L1232-6 (procédure), "
        "L1234-1 (notice), L1234-9 and R1234-2 (indemnité de licenciement), "
        "L1233-3 to L1233-90 (licenciement économique), L1235-3 (barème Macron). "
        "Applicable Convention collective nationale (CCN). Conseil de prud'hommes jurisdiction."
    ),
    employer_notice=NoticeRule(
        brackets=FR_NON_CADRE_NOTICE_BRACKETS,
        description="Statutory minimum for non-cadre: 1 month if 6mo-2yr, 2 months if ≥2yr. Applicable CCN may extend.",
        citation="Code du travail Art. L1234-1",
    ),
    employee_notice=NoticeRule(
        base_days=30,
        description="Employee resignation: per applicable CCN (typically 1 month for non-management roles).",
        citation="Per applicable CCN",
    ),
    severance_components=_FR_SEVERANCE_COMPONENTS,
    protections=_FR_PROTECTIONS,
    mandatory_steps=_FR_MANDATORY_STEPS,
    final_pay_deadline="Solde de tout compte payable at end of notice period (worked or indemnified).",
    notes=_FR_NOTES,
)


# -----------------------------------------------------------------------------
# France — cadre (manager-level, typically 3 months notice by CCN)
# -----------------------------------------------------------------------------

FR_CADRE_NOTICE_BRACKETS = (
    NoticeBracket(
        min_tenure_months=0,
        max_tenure_months=6,
        days=0,
        description="Less than 6 months tenure: per contract / CCN; no statutory floor",
        citation="Code du travail Art. L1234-1 + CCN",
    ),
    NoticeBracket(
        min_tenure_months=6,
        max_tenure_months=None,
        days=90,
        months=3,
        description="3 months notice for cadre, market-standard via CCN (e.g. Syntec). Verify against applicable CCN.",
        citation="Convention collective nationale (industry-specific)",
    ),
)


FR_CADRE = JurisdictionRule(
    country="FR",
    employment_type="cadre",
    legal_framework=(
        "Code du travail (as for non-cadre) plus cadre-specific provisions in the applicable Convention collective nationale (CCN). "
        "Notice typically 3 months by CCN. Période d'essai up to 4 months, renewable once (up to 8 months total) under Art. L1221-19."
    ),
    employer_notice=NoticeRule(
        brackets=FR_CADRE_NOTICE_BRACKETS,
        description="Cadre notice: typically 3 months by industry CCN. Code du travail does not set a cadre-specific statutory floor; verify against applicable CCN.",
        citation="Convention collective nationale (e.g., Syntec)",
    ),
    employee_notice=NoticeRule(
        base_days=90,
        description="Cadre resignation: typically 3 months by CCN.",
        citation="Per applicable CCN",
    ),
    severance_components=_FR_SEVERANCE_COMPONENTS,
    protections=_FR_PROTECTIONS,
    mandatory_steps=_FR_MANDATORY_STEPS,
    final_pay_deadline="Solde de tout compte payable at end of notice period (worked or indemnified).",
    notes=(
        "Cadre notice is set by industry CCN (the Code du travail does not specify a cadre-specific statutory floor). "
        "Période d'essai for cadres can extend to 4 months, renewable once (up to 8 months total) under Art. L1221-19 and applicable CCN. "
        "All other provisions (indemnité de licenciement formula, protections, procedure) mirror the non-cadre rule. "
        + _FR_NOTES
    ),
)


# -----------------------------------------------------------------------------
# Spain — full-time
# Source: docs/jurisdiction.md §"Spain (ES)"
#
# Spanish dismissal law splits into three categories with different severance:
#   despido objetivo (20 days/year, cap 12 months)
#   despido disciplinario (no severance if upheld)
#   despido improcedente (33 days/year, cap 24 months; 45 days/year for pre-2012 service)
# The rule below models despido objetivo as the default; the improcedente
# formula is exposed as a separate severance component for when courts
# reclassify.
# -----------------------------------------------------------------------------

ES_FULL_TIME = JurisdictionRule(
    country="ES",
    employment_type="full-time",
    legal_framework=(
        "Estatuto de los Trabajadores (Real Decreto Legislativo 2/2015): Art. 49 (causes of termination), "
        "Art. 51 (despido colectivo), Art. 52-53 (despido objetivo), Art. 54-55 (despido disciplinario), "
        "Art. 56 (despido improcedente), Art. 14 (período de prueba). "
        "Ley 36/2011 (LRJS). SMAC conciliation mandatory before tribunal. Juzgado de lo Social jurisdiction."
    ),
    employer_notice=NoticeRule(
        base_days=15,
        description="Despido objetivo: 15 calendar days advance written notice from the carta de despido. Despido disciplinario: no statutory notice (effective on delivery of carta).",
        citation="Estatuto de los Trabajadores Art. 53.1.c",
    ),
    employee_notice=NoticeRule(
        base_days=15,
        description="Employee resignation (baja voluntaria): per applicable convenio colectivo, typically 15 days for non-management roles.",
        citation="Per applicable convenio colectivo",
    ),
    severance_components=(
        SeveranceComponent(
            name="Indemnización despido objetivo",
            formula="20 * daily_salary * years_of_service",
            notes="Capped at 12 monthly salaries. Pro-rata for incomplete years (calculation in months, not just full years). Severance must be tendered simultaneously with the carta de despido; failure renders despido improcedente by formal defect (Tribunal Supremo consolidated doctrine; partial exception for ETOP causes where employer can prove lack of liquidity).",
            citation="Estatuto de los Trabajadores Art. 53.1.b",
        ),
        SeveranceComponent(
            name="Indemnización despido improcedente (when dismissal found unfair)",
            formula="33 * daily_salary * years_after_12_feb_2012 + 45 * daily_salary * years_before_12_feb_2012",
            notes="Post-12-Feb-2012 service: 33 days/year, capped at 24 monthly salaries. Pre-reform service for legacy hires: 45 days/year. Combined cap of 42 monthly salaries (or 720 days, whichever more favourable) per Disposición transitoria 11ª. Following improcedencia finding, employer (or in defined cases the employee, e.g. union reps) elects within 5 days between paying indemnización + confirming termination, or reinstating with salarios de tramitación.",
            citation="Estatuto de los Trabajadores Art. 56",
        ),
        SeveranceComponent(
            name="Pagas extraordinarias pro-rata",
            formula="(annual_extras / 365) * days_worked_in_accrual_period",
            notes="Standard Spanish 14-payment structure: summer and Christmas extra payments accrue throughout the year; unaccrued portion paid at termination.",
            citation="Estatuto de los Trabajadores Art. 31",
        ),
        SeveranceComponent(
            name="Vacation accrued but untaken",
            formula="daily_salary * untaken_vacation_days",
            citation="Estatuto de los Trabajadores Art. 38",
        ),
    ),
    protections=(
        Protection(
            name="pregnancy_maternity_or_paternity",
            scope="pregnancy, maternity / paternity leave, breastfeeding leave, parental leave, and up to 12 months following maternity-related reinstatement. Dismissal is nulo (mandatory reinstatement) unless the employer proves a cause wholly unconnected to the protected status.",
            citation="Estatuto de los Trabajadores Art. 55.5",
        ),
        Protection(
            name="victim_of_gender_violence",
            scope="dismissal nulo with mandatory reinstatement",
            citation="Estatuto de los Trabajadores Art. 55.5.b",
        ),
        Protection(
            name="union_representative_or_works_council",
            scope="enhanced protection: priority in redundancy selection, contradictory expediente (internal hearing) procedure required before dismissal",
            citation="Estatuto de los Trabajadores Art. 68.c",
        ),
        Protection(
            name="discrimination_or_fundamental_rights_violation",
            scope="dismissal violating Constitutional rights (Art. 14 CE) or anti-discrimination provisions is nulo, requiring mandatory reinstatement",
            citation="Estatuto de los Trabajadores Art. 55.5; Constitución Española Art. 14",
        ),
    ),
    mandatory_steps=(
        "Carta de despido (written dismissal letter) mandatory for every dismissal: precise grounds (specific facts, dates, ET article invoked), effective date.",
        "For despido objetivo: simultaneous tender of severance and 15-day notice at delivery of the carta. Failure renders despido improcedente by formal defect.",
        "For despido colectivo: período de consultas with worker representatives (15 days if firm <50 employees, 30 days if 50+). Notification to Autoridad Laboral at the start of consultation.",
        "SMAC conciliation step mandatory before tribunal claim (LRJS Art. 63). Submit papeleta de conciliación within 20 working days of dismissal.",
        "Employer is locked into grounds stated in the carta (principio de invariabilidad de la causa); new grounds raised in litigation are inadmissible.",
    ),
    final_pay_deadline="Finiquito at termination: salary through last day, pro-rata pagas extraordinarias, accrued vacation, and any severance owed.",
    notes=(
        "Three principal dismissal classifications drive different outcomes: despido objetivo (20 days/year, cap 12 months), despido disciplinario (no severance if upheld), despido improcedente (33 days/year, cap 24 months; 45 days/year for pre-2012 service). "
        "Despido nulo (for protected categories or fundamental rights violations) requires mandatory reinstatement; the employer has no option to pay indemnización instead. "
        "Despido colectivo thresholds within a 90-day window: 10 employees if firm has <100 staff; 10% if 100-300; 30 employees if >300; OR any dismissal affecting entire workforce >5 employees regardless of firm size. "
        "Statute of limitations: 20 working days from effective dismissal date to file papeleta at SMAC (Art. 59.3 ET) — hard caducidad (forfeiture) deadline, not prescripción."
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
    ("UK", "full-time"): UK_FULL_TIME,
    ("FR", "non-cadre"): FR_NON_CADRE,
    ("FR", "cadre"): FR_CADRE,
    ("ES", "full-time"): ES_FULL_TIME,
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
    # FR-specific (cadre = manager-level, non-cadre = everyone else)
    "cadre": "cadre",
    "non-cadre": "non-cadre",
    "non_cadre": "non-cadre",
    "noncadre": "non-cadre",
    "manager": "cadre",  # only valid for FR
}


COVERED_COUNTRIES: frozenset[str] = frozenset({"BR", "DE", "US-CA", "UK", "FR", "ES"})


UNCOVERED_COUNTRIES_MESSAGE = (
    "Jurisdiction not covered. This engine has rules for: "
    "BR (CLT, PJ), DE, US-CA, UK, FR (cadre, non-cadre), ES. "
    "For other jurisdictions, recommend specialist legal review before any termination action."
)


def normalize_employment_type(employment_type: str, country: str) -> str:
    """Map common synonyms to the canonical employment_type for a country."""
    normalized = _EMPLOYMENT_TYPE_ALIASES.get(employment_type.lower(), employment_type)
    # BR-specific aliases shouldn't leak to other countries.
    if country != "BR" and normalized in {"CLT", "PJ"}:
        return employment_type  # let lookup fail meaningfully
    # FR-specific aliases shouldn't leak to other countries.
    if country != "FR" and normalized in {"cadre", "non-cadre"}:
        return employment_type
    # FR default: when the caller passes a generic 'full-time' for France, treat
    # as non-cadre (the broader of the two categories; cadre must be explicit).
    if country == "FR" and normalized == "full-time":
        return "non-cadre"
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
