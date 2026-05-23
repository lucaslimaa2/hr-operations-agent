# HR Operations Agent — Jurisdiction Reference

This document is the source of truth for the jurisdiction rules engine implemented in `mcp_servers/jurisdiction_server.py`. Every numeric rule, threshold, and formula in the engine traces back to a statute or regulation cited here. The design principle is deterministic compliance: the LLM does not infer labor law from training data, it queries hardcoded structured data derived from the rules below.

This is a snapshot of law as of **2026-05-23**. Labor statutes are amended periodically (notably collective bargaining agreements in BR and FR, and state-level minimum-wage / final-pay updates in the US). The engine should be re-verified against primary sources annually, and any rule whose citation has been superseded must be updated before the engine returns it. Where the engine has no rule for a given country, it must return a structured "not covered" response rather than guess.

---

## Brazil (BR)

Brazilian employment law treats CLT employees and PJ contractors as fundamentally different legal categories. The engine must branch on `employment_type` before applying any rule. Conflating the two is the single most common source of compliance error in Brazilian HR operations.

### CLT (registered employee — Consolidação das Leis do Trabalho)

#### Legal framework

- **Decreto-Lei 5.452/1943** — Consolidação das Leis do Trabalho (CLT), the master statute for employment relationships.
- **Lei 12.506/2011** — aviso prévio proporcional (proportional notice scaling with tenure).
- **Lei 8.036/1990** — FGTS (Fundo de Garantia do Tempo de Serviço), including the 40% multa rescisória on dismissal without cause.
- **Constituição Federal 1988, Art. 7º** — constitutional employment rights including 13º salário, férias + 1/3, and FGTS.
- **CLT Arts. 477–487** — termination procedure and notice mechanics.

#### Notice period rules

Aviso prévio is required for termination without cause initiated by either party, with the practical asymmetry that employees waive it more often than employers do.

```
notice_days = min(30 + 3 * full_years_of_service, 90)
```

- Base: **30 days** (CLT Art. 487, I).
- Plus **3 additional days per full year of service**, capped at **+60 additional days** (Lei 12.506/2011, parágrafo único). Maximum total = **90 days**.
- The +3 days/year applies to the period beyond the first year of service. Standard market practice (and the Ministério do Trabalho's interpretation) is to count each completed year from year 1 onward.
- The employer may pay the notice period in cash (**aviso prévio indenizado**) or require the employee to work it (**aviso prévio trabalhado**). If worked, the employee is entitled to either a 2-hour daily reduction in working hours or 7 consecutive days off at the end of the notice period (CLT Art. 488).
- Employee-initiated resignation: employee owes 30 days notice to the employer; the +3/year scaling does **not** apply to the employee's side (TST jurisprudence, consolidated interpretation of Lei 12.506/2011).

| Tenure (full years) | Notice (days) |
|---|---|
| <1 | 30 |
| 1 | 33 |
| 5 | 45 |
| 10 | 60 |
| 15 | 75 |
| 20+ | 90 (cap) |

#### Severance / final pay

Termination **without cause (sem justa causa)** — full verbas rescisórias:

1. **Saldo de salário** — salary for days worked in the final month.
2. **Aviso prévio** — paid per above (worked or indemnified).
3. **13º salário proporcional** — pro-rata 13th-month salary. Formula: `(monthly_salary / 12) * months_worked_in_year`, where any month with 15+ days worked counts as a full month (Lei 4.090/1962).
4. **Férias vencidas + 1/3** — any accrued but untaken vacation, plus the constitutional one-third premium (CF Art. 7º, XVII).
5. **Férias proporcionais + 1/3** — pro-rata vacation for the current acquisition period, plus 1/3 premium.
6. **FGTS** — the employer has been depositing 8% of monthly salary into the employee's FGTS account throughout the relationship. On termination without cause, the employer pays a **40% multa rescisória** on the **total accumulated FGTS balance** (not just the portion deposited in the final year). Lei 8.036/1990, Art. 18, §1º. The employee may then withdraw the full FGTS balance plus multa.
7. **Guia para seguro-desemprego** — the employer must issue the form that lets the employee claim unemployment insurance.

Termination **with cause (com justa causa)** — Art. 482 CLT. Drastically reduced entitlements:

- Saldo de salário only.
- Férias vencidas + 1/3 (if any).
- **No** aviso prévio, **no** 13º proporcional, **no** férias proporcionais, **no** FGTS multa, **no** access to FGTS balance, **no** seguro-desemprego.
- Just cause grounds are exhaustively listed in Art. 482 (acts of dishonesty, gross misconduct, abandonment, etc.) and the employer bears the burden of proof in labor court.

**Rescisão indireta** — Art. 483 CLT. Employee-initiated termination on the grounds of employer misconduct (failure to pay wages, harassment, demanding services outside the contract, etc.). Triggers the **same entitlements as termination without cause** — the law treats employer-fault terminations as economically equivalent to dismissal without cause.

**Acordo (mutual agreement)** — Art. 484-A CLT, introduced by the 2017 labor reform (Lei 13.467/2017). Notice and FGTS multa are halved (50% notice, 20% multa), and the employee may withdraw 80% of the FGTS balance. No access to seguro-desemprego.

#### Edge cases

- **Estabilidade (job stability — termination is legally blocked):**
  - **Pregnant employees** — from confirmation of pregnancy through 5 months postpartum (ADCT Art. 10, II, b).
  - **Cipa members** (workplace accident prevention committee) — from candidacy through 1 year after end of mandate (CLT Art. 165).
  - **Union directors** — from candidacy through 1 year after end of mandate (CF Art. 8º, VIII).
  - **Employees on accident leave (auxílio-doença acidentário)** — 12 months stability after return (Lei 8.213/1991, Art. 118).
  - **Pre-retirement** — varies by collective bargaining agreement, typically 12–24 months before retirement eligibility.
- Termination of an employee under estabilidade requires either the legal cause that lifts the protection or a court-approved process. The engine should flag any termination request against an employee in a stability category and refuse to auto-execute.
- **Mass layoffs (dispensa coletiva)** — the STF (Supreme Court) ruled in 2022 (RE 999.435) that prior union negotiation is required for collective dismissals. No fixed numeric threshold in statute, but layoffs affecting "a significant portion of the workforce" trigger the requirement.
- **Contribuição sindical** — voluntary since 2017 (Lei 13.467/2017), not a termination-time obligation.

#### Worked example

Scenario: CLT employee, **4 full years of tenure**, monthly salary R$ 8,000, dismissed without cause in June (5 full months of the current year worked), with 10 days of accrued vacation untaken from the prior acquisition period.

1. Aviso prévio: `min(30 + 3*4, 90)` = **42 days**. Paid as indenizado: `8000 * (42/30)` = **R$ 11,200**.
2. Saldo de salário: assume terminated on the 20th → 20 days × (8000/30) = **R$ 5,333**.
3. 13º proporcional: `8000 / 12 * 5` = **R$ 3,333** (Jan–May counted; June is the termination month).
4. Férias vencidas + 1/3: `8000 + 8000/3` = **R$ 10,667**.
5. Férias proporcionais + 1/3: 5 months accrued in the current period → `(8000 * 5/12) + (8000 * 5/12)/3` = **R$ 4,444**.
6. FGTS multa: assume accumulated FGTS balance of R$ 30,720 (8% × 8000 × 48 months) → 40% multa = **R$ 12,288**. Employee separately withdraws the R$ 30,720 balance.

Total cash to employee at termination: approximately **R$ 47,265** (verbas rescisórias) plus access to **R$ 30,720** FGTS withdrawal.

#### Sources

- Planalto — **CLT (Decreto-Lei 5.452/1943)**: <https://www.planalto.gov.br/ccivil_03/decreto-lei/del5452.htm>
- Planalto — **Lei 12.506/2011 (aviso prévio proporcional)**: <https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2011/lei/l12506.htm>
- Planalto — **Lei 8.036/1990 (FGTS)**: <https://www.planalto.gov.br/ccivil_03/leis/l8036consol.htm>
- Planalto — **Lei 13.467/2017 (reforma trabalhista)**: <https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2017/lei/l13467.htm>
- TST (Tribunal Superior do Trabalho) — jurisprudência consolidada: <https://www.tst.jus.br>
- Baker McKenzie — *Global Employer Guide: Brazil*: <https://www.bakermckenzie.com/en/insight/publications/guides/global-employer-guide>
- DLA Piper — *Guide to Going Global — Employment: Brazil*: <https://www.dlapiperintelligence.com/goingglobal/employment/>
- Deel — *Brazil Employee Termination Guide*: <https://www.deel.com/country/brazil/>

---

### PJ (contractor — Pessoa Jurídica)

#### Legal framework

- **Código Civil (Lei 10.406/2002), Arts. 593–609** — contrato de prestação de serviços (service contract).
- **Lei 11.196/2005, Art. 129** — explicit authorization of PJ arrangements for professional services.
- **CLT Art. 3º** — definition of employment relationship; the test that distinguishes a legitimate PJ from a disguised employment relationship.

A PJ contractor is a legal person (typically a single-member LLC — Sociedade Limitada Unipessoal, or a Microempreendedor Individual) contracting with the company. The contractor invoices the company; the company is not the contractor's employer.

#### Notice period rules

- **No statutory aviso prévio.** Notice is whatever the contract specifies.
- Civil Code Art. 599 provides for "reasonable notice" in indefinite-term service contracts where the contract is silent, with case law typically settling on **30 days** as a reasonable default for ongoing professional services. This is a civil-law principle (boa-fé objetiva — good faith), not a labor entitlement, and damages for breach are limited to demonstrable losses.
- Either party may terminate per the contract terms. Early termination penalties (multa) are enforceable only if expressly written into the contract.

#### Severance / final pay

- **No verbas rescisórias.** No 13º, no férias, no FGTS, no FGTS multa, no seguro-desemprego, no notice-period premium.
- The contractor is paid invoices through the contract end date and nothing else. The contractor handles its own taxes (IRPJ, CSLL, PIS, COFINS, ISS) and social security contributions (INSS as a contribuinte individual).

#### Edge cases

- **Vínculo empregatício (re-classification risk)** — the central risk. CLT Art. 3º defines an employee as someone who performs services for an employer with four characteristics simultaneously:
  1. **Pessoalidade** — the work must be performed personally; the contractor cannot substitute another person.
  2. **Não-eventualidade** — habitual, ongoing work (not a one-off project).
  3. **Onerosidade** — paid work.
  4. **Subordinação** — the worker takes direction from the company (hours, methods, tools, reporting structure).
  
  If all four are present, the Justiça do Trabalho can re-classify the PJ relationship as a CLT employment relationship **retroactively**, regardless of what the contract says (princípio da primazia da realidade — the primacy of facts over form). The company is then liable for the full back-payment of all CLT verbas (FGTS for the entire period, 13º for every year, férias + 1/3 for every year, INSS contributions, fines, plus moral damages in some cases). Statute of limitations: 2 years after end of relationship to file, 5 years of back-claims (CF Art. 7º, XXIX).
- "Pejotização" — the practice of pushing workers into PJ status to avoid CLT obligations — has been the subject of significant TST enforcement. The 2017 labor reform attempted to legitimize "autonomous worker with exclusivity" arrangements (Lei 13.467/2017, CLT Art. 442-B), but the STF has repeatedly upheld re-classification where the four-factor test is met.
- The engine should treat any PJ termination as a contract-law matter only and explicitly flag the re-classification risk in any escalation brief.

#### Worked example

Scenario: PJ contractor, R$ 15,000/month invoiced, 2-year ongoing relationship, terminated by the company.

- Contract has a 30-day notice clause: company pays one final 30-day invoice (R$ 15,000) and the relationship ends.
- Contract is silent on notice: Civil Code Art. 599 / good-faith principles → 30 days reasonable notice (R$ 15,000) is the default safe-harbor.
- **No** 13º, **no** férias, **no** FGTS, **no** multa, **no** seguro-desemprego.
- If, however, the contractor worked exclusively for the company under daily direction, with fixed hours, using company equipment, for 2 years — re-classification risk is high, and a Justiça do Trabalho claim could result in back-payment of approximately R$ 28,800 in FGTS, R$ 30,000 in 13ºs, R$ 40,000 in férias + 1/3, plus 40% FGTS multa (R$ 11,520) and INSS contributions. The engine should escalate, not auto-execute.

#### Sources

- Planalto — **Código Civil (Lei 10.406/2002)**, Arts. 593–609: <https://www.planalto.gov.br/ccivil_03/leis/2002/l10406compilada.htm>
- Planalto — **Lei 11.196/2005**, Art. 129: <https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2005/lei/l11196.htm>
- TST — jurisprudência on vínculo empregatício / pejotização: <https://www.tst.jus.br>
- STF — leading cases on Art. 129 da Lei 11.196/2005 (RE 958.252, ADPF 324)
- Tozzini Freire — *Contratação PJ no Brasil: riscos e estrutura*: <https://tozzinifreire.com.br>
- Deel — *Brazil Contractor vs Employee Classification*: <https://www.deel.com/blog/brazil-contractor-or-employee/>

---

## Germany (DE)

### Employment relationship overview

German employment law layers statutory protections (BGB, KSchG) on top of individual contracts and any applicable collective bargaining agreements (Tarifverträge). The two key thresholds for termination are (1) end of probation (6 months) and (2) employer size (>10 employees, the trigger for Kündigungsschutzgesetz protection).

#### Legal framework

- **Bürgerliches Gesetzbuch (BGB) §§ 620–630** — general employment contract law, including statutory notice periods in **BGB §622**.
- **Kündigungsschutzgesetz (KSchG)** — Act on Protection Against Unfair Dismissal. Applies to employees with >6 months tenure in establishments with >10 employees (KSchG §1, §23).
- **Betriebsverfassungsgesetz (BetrVG) §102** — works council (Betriebsrat) consultation requirement before any termination, in establishments where a works council exists.
- **Mutterschutzgesetz (MuSchG), Bundeselterngeld- und Elternzeitgesetz (BEEG), SGB IX (severely disabled), §15 KSchG (works council members)** — categorical protections against termination.

### Probationary period (Probezeit, <6 months)

#### Notice period rules

- **BGB §622(3)** — during a contractually agreed probation period (max 6 months), notice is **2 weeks**, from either side, with no specified termination date (i.e., the 2 weeks can end on any calendar day).
- The probation period must be expressly stated in the employment contract; it is not automatic. Maximum allowable length is 6 months.
- KSchG does **not** apply during probation, so the employer does not need to justify the termination on operational, conduct, or personal grounds.

#### Severance / final pay

- **No statutory severance** during probation.
- Final wages due on the next regular payroll date per the employment contract (no special "immediate pay" rule analogous to California). Holiday pay (Urlaubsabgeltung) for any accrued but untaken vacation must be paid out (Bundesurlaubsgesetz §7(4)).
- Certificate of employment (Arbeitszeugnis) is owed on request (GewO §109).

#### Edge cases

- **Pregnant employees** — MuSchG §17 — termination is prohibited from the start of pregnancy through 4 months postpartum, **including during probation**. Requires approval from the state labor authority (Aufsichtsbehörde) for any termination, even on probation.
- **Parental leave** — BEEG §18 — same protection during Elternzeit, including probation.
- **Severely disabled employees (Schwerbehinderte)** — SGB IX §168 — Integrationsamt approval required for termination after 6 months of employment. Note: the 6-month threshold is independent of the probation period; some severely disabled employees may be terminable during probation without Integrationsamt consent.
- **Works council consultation** — BetrVG §102 — required if a works council exists, even during probation. Failure to consult renders the termination void.

#### Worked example

Scenario: full-time employee, 3 months tenure, contractually agreed 6-month Probezeit, employer terminates for performance reasons.

- Notice period: **2 weeks** from notice date (BGB §622(3)).
- No justification required under KSchG (does not apply).
- If a Betriebsrat exists: consultation required before notice is issued (BetrVG §102).
- Pay out: final salary through last day worked + accrued vacation (Urlaubsabgeltung). No severance.
- Total employer cost: ~2 weeks salary + vacation payout.

### Post-probationary (>= 6 months)

#### Legal framework

KSchG applies once both conditions are satisfied:
1. Employee has been employed >6 months in the same establishment (KSchG §1(1)).
2. Employer regularly employs >10 full-time-equivalent employees (KSchG §23(1)). Part-timers count as fractions: ≤20 hrs/week = 0.5, ≤30 hrs/week = 0.75.

If KSchG applies, every employer-initiated termination must be "socially justified" (sozial gerechtfertigt) on one of three grounds:

- **Betriebsbedingt (operational)** — business need (restructuring, redundancy). Requires social-selection criteria (Sozialauswahl): age, tenure, dependents, severe disability.
- **Verhaltensbedingt (conduct)** — misconduct. Generally requires prior written warning (Abmahnung) except for severe breaches.
- **Personenbedingt (personal)** — incapacity, such as long-term illness preventing performance of duties.

Wrongful termination challenges go to the Arbeitsgericht (labor court). The employee must file within 3 weeks of receiving the termination notice (KSchG §4). If successful, the employee is reinstated with back-pay — though in practice, courts often broker a severance settlement (Abfindung) instead.

#### Notice period rules — BGB §622(2)

Employer-initiated notice, post-probation, by tenure:

| Tenure | Notice period | Termination date |
|---|---|---|
| <2 years | 4 weeks | 15th or end of calendar month |
| ≥2 years | 1 month | End of calendar month |
| ≥5 years | 2 months | End of calendar month |
| ≥8 years | 3 months | End of calendar month |
| ≥10 years | 4 months | End of calendar month |
| ≥12 years | 5 months | End of calendar month |
| ≥15 years | 6 months | End of calendar month |
| ≥20 years | 7 months | End of calendar month |

```
# Notice in months, employer-initiated, post-probation
if tenure_years < 2:     notice = "4 weeks to 15th or end of month"
elif tenure_years < 5:   notice = "1 month to end of month"
elif tenure_years < 8:   notice = "2 months to end of month"
elif tenure_years < 10:  notice = "3 months to end of month"
elif tenure_years < 12:  notice = "4 months to end of month"
elif tenure_years < 15:  notice = "5 months to end of month"
elif tenure_years < 20:  notice = "6 months to end of month"
else:                    notice = "7 months to end of month"
```

- The "to end of month" requirement means the actual notice period is **longer than the nominal period** unless notice is issued on the exact day that allows it to expire on the last day of a month. E.g., 2-month notice given on April 10 → termination effective June 30, not June 10.
- Employee-initiated notice (resignation): **4 weeks to the 15th or end of month**, regardless of tenure (BGB §622(1)). The longer tenure-scaled periods apply to the employer only, unless the contract reciprocates them.
- A collective bargaining agreement (Tarifvertrag) may modify these periods in either direction.

#### Severance / final pay

- **No statutory severance entitlement for ordinary termination.** This is the most-misunderstood feature of German employment law. KSchG does not award severance; it awards reinstatement.
- **Negotiated severance (Abfindung)** is the practical norm: when an employee challenges termination in Arbeitsgericht, the parties typically settle on a severance payment in exchange for the employee dropping the suit. Market-standard formula:

```
abfindung = monthly_gross_salary * 0.5 * years_of_service
```

  This is the **"Regelabfindung"** factor of 0.5 referenced in KSchG §1a (a voluntary safe-harbor provision the employer can offer for operational terminations). In practice, settlements range from 0.5 to 1.5 monthly salaries per year of service depending on case strength and seniority.

- **KSchG §1a** — if the employer issues a notice citing operational grounds and includes a statement offering severance in lieu of suit, the employee can accept by not filing within 3 weeks. The statutory amount is 0.5 × monthly gross × years of service.
- **Sozialplan** — in mass-layoff scenarios with a works council, a written social plan (Sozialplan) under BetrVG §112 governs severance for all affected employees. Amounts are negotiated between employer and Betriebsrat.

Final-pay components:
- Salary through last day worked.
- Urlaubsabgeltung — payout of any accrued but untaken vacation (BUrlG §7(4)).
- 13th-month / bonus — only if contractually owed, paid pro-rata to the termination date.
- Arbeitszeugnis — written employment certificate (GewO §109), required on request and judicially reviewable for accuracy and tone.

#### Edge cases

- **Mass layoffs (Massenentlassung)** — KSchG §17 — notification to the Bundesagentur für Arbeit required when affecting:
  - 21+ in establishments of 20–59 employees
  - 10% or 25+ in establishments of 60–499 employees
  - 30+ in establishments of 500+ employees
  
  All within a 30-day period. Notification must precede the terminations; failure renders them void.
- **Works council members (Betriebsrat)** — KSchG §15 — protected from termination during their term and for 1 year after, except for extraordinary cause (außerordentliche Kündigung) with Betriebsrat consent.
- **Pregnancy** — MuSchG §17 — full termination block, requires state authority consent.
- **Parental leave (Elternzeit)** — BEEG §18 — full termination block during leave.
- **Severely disabled** — SGB IX §168 — Integrationsamt consent required.
- **Extraordinary termination (außerordentliche / fristlose Kündigung)** — BGB §626 — termination without notice for severe cause (theft, violence, etc.). Must be issued within 2 weeks of the employer learning of the cause. Subject to court review.

#### Worked example

Scenario: full-time employee, **7 years tenure**, monthly gross salary €6,500, employer in a 50-person company terminates on operational grounds (department closure). No works council. Notice issued on March 15, 2026.

1. **KSchG applies** (tenure >6 months, employer >10 employees) → social justification required. Operational ground = department closure, supported by Sozialauswahl among comparable employees.
2. Notice period: tenure ≥5 years, <8 years → **2 months to end of month**. Notice issued March 15 → cannot expire April 30 (would be only ~6 weeks). Expires **May 31, 2026**.
3. Salary through May 31: 2.5 months × €6,500 = **€16,250**.
4. Urlaubsabgeltung: assume 10 untaken vacation days at €6,500 × 12 / 252 working days ≈ €310/day → **€3,100**.
5. Severance offer under KSchG §1a (operational ground, employer chooses to offer): `6500 × 0.5 × 7` = **€22,750**.
6. Total employer cost: ~**€42,100**, plus the obligation to issue an Arbeitszeugnis.

#### Sources

- gesetze-im-internet.de — **BGB §622 (notice periods)**: <https://www.gesetze-im-internet.de/bgb/__622.html>
- gesetze-im-internet.de — **Kündigungsschutzgesetz (KSchG)**: <https://www.gesetze-im-internet.de/kschg/>
- gesetze-im-internet.de — **Betriebsverfassungsgesetz (BetrVG)**: <https://www.gesetze-im-internet.de/betrvg/>
- gesetze-im-internet.de — **Mutterschutzgesetz (MuSchG)**: <https://www.gesetze-im-internet.de/muschg_2018/>
- Bundesministerium für Arbeit und Soziales — overview: <https://www.bmas.de/DE/Arbeit/Arbeitsrecht/arbeitsrecht.html>
- Baker McKenzie — *Global Employer Guide: Germany*: <https://www.bakermckenzie.com/en/insight/publications/guides/global-employer-guide>
- DLA Piper — *Guide to Going Global — Employment: Germany*: <https://www.dlapiperintelligence.com/goingglobal/employment/>
- L&E Global — *Employment Law Overview Germany*: <https://knowledge.leglobal.org/employment-law-overview-germany/>

---

## United States — California (US-CA)

### At-will doctrine

#### Legal framework

- **California Labor Code §2922** — "An employment, having no specified term, may be terminated at the will of either party on notice to the other." This is the statutory foundation of at-will employment in California.
- Common-law exceptions developed by California courts (*Foley v. Interactive Data Corp.*, 47 Cal.3d 654 (1988); *Tameny v. Atlantic Richfield Co.*, 27 Cal.3d 167 (1980)).

At-will means either party may terminate at any time, with or without cause, with or without notice. The default is termination by either side without legal consequence, **except** where one of the following exceptions applies:

- **Discrimination** — California Fair Employment and Housing Act (FEHA), Cal. Gov. Code §12940 et seq. — termination based on race, sex, gender identity, sexual orientation, religion, national origin, age (40+), disability, pregnancy, marital status, veteran status, etc.
- **Retaliation** — for protected activity such as filing a workers' comp claim, whistleblowing (Cal. Lab. Code §1102.5), reporting harassment, union organizing, taking protected leave.
- **Public policy violation** — *Tameny* — termination that contravenes a fundamental public policy embedded in a statute or constitutional provision (e.g., termination for refusing to commit perjury).
- **Implied contract** — *Foley* — employer statements, employee handbooks, or long tenure can create an implied promise of termination only for cause.
- **Implied covenant of good faith and fair dealing** — narrow in CA; *Guz v. Bechtel National*, 24 Cal.4th 317 (2000).
- **WARN Act notification** — see below.

#### Notice period rules

- **No statutory notice period.** Either party may terminate without notice. Exception: WARN Act (below) for qualifying mass layoffs.
- Notice may be required by individual employment contract or collective bargaining agreement (rare in non-unionized California workplaces).

### Final pay obligations

This is the area where California departs most sharply from at-will norms in other US states. The penalty regime is strict and the deadlines are short.

#### Legal framework

- **California Labor Code §201** — involuntary termination.
- **California Labor Code §202** — voluntary resignation.
- **California Labor Code §203** — waiting time penalty.
- **California Labor Code §227.3** — vested vacation must be paid out as wages at termination.
- DLSE (Division of Labor Standards Enforcement) policy guidance.

#### Rules

- **Involuntary termination (employer-initiated)** — **Cal. Lab. Code §201** — all wages due are payable **immediately at the time of termination**. "Immediately" means same day, at the place of termination. This includes:
  - All earned wages through the last hour worked.
  - All accrued but unused vacation (Cal. Lab. Code §227.3 — vested vacation is wages).
  - Any earned commissions or bonuses that are calculable at termination (commissions not yet calculable are paid when calculable).
  - PTO that is structured as vacation (use-it-or-lose-it vacation policies are unlawful in CA).
  - Note: **sick leave is not wages** and is not payable at termination unless the employer's policy treats it as PTO/vacation.

- **Voluntary resignation with 72+ hours notice** — **Cal. Lab. Code §202** — wages due on the **last day of work**.

- **Voluntary resignation without 72 hours notice** — wages due within **72 hours of resignation**, at the employer's office of usual payment (mailing to a forwarding address provided by the employee is permitted).

- **Waiting time penalty** — **Cal. Lab. Code §203** — if the employer willfully fails to pay final wages on time, the employee's daily wage continues to accrue as a penalty for each calendar (not business) day of delay, up to a **maximum of 30 days**.

```
waiting_time_penalty = daily_wage * min(days_late, 30)
# daily_wage = (monthly_salary * 12) / 260 or hourly_rate * regular_hours_per_day
```

  "Willful" is broadly interpreted by California courts — it does not require bad intent, only that the failure to pay was not the result of a good-faith dispute. Administrative error qualifies as willful.

#### Severance

- **No statutory severance** at the state or federal level in the US for ordinary termination.
- Severance is purely a matter of contract: individual employment agreement, severance plan governed by ERISA, or negotiated separation agreement (typically in exchange for a release of claims).
- A release of FEHA / discrimination claims must comply with **Cal. Gov. Code §12964.5** (CA "Silenced No More" Act) — cannot prevent disclosure of harassment/discrimination.

#### Edge cases

- **Health insurance continuation** — federal **COBRA** (29 USC §1161 et seq.) for employers with 20+ employees, **Cal-COBRA** (Cal. Health & Safety Code §1366.20 et seq.) for employers with 2–19 employees. Notification must be sent within 14 days of termination (employer to plan admin) and 44 days to the qualified beneficiary. COBRA continuation runs 18 months (36 in certain dependent scenarios).
- **Unemployment insurance** — administered by California EDD (Employment Development Department). The employer must provide the DE 2320 pamphlet at termination.
- **Final paycheck location** — must be at the place of termination for involuntary terminations (Cal. Lab. Code §208). The employer cannot require the employee to come pick it up elsewhere.
- **Direct deposit** — final wages may be paid by direct deposit only if the employee has authorized it and the funds will be available on the date required by §201/§202.
- **Sick leave** — not payable at termination (Cal. Lab. Code §246(i)), but must be reinstated if the employee is rehired within 1 year.

### WARN Act (federal + Cal-WARN)

Two parallel WARN statutes apply in California; both must be checked, and the **stricter** (broader-coverage) rule controls in practice.

#### Federal WARN Act

- **29 USC §2101–2109** — Worker Adjustment and Retraining Notification Act.
- Applies to employers with **100+ full-time employees** (or 100+ FT and PT combined working ≥4,000 hrs/week excluding overtime).
- Triggers — **60 days advance written notice** is required for:
  - **Plant closing** — permanent or temporary shutdown of a single site of employment, or one or more facilities/operating units within a single site, resulting in employment loss for 50+ FT employees during any 30-day period.
  - **Mass layoff** — reduction in force at a single site affecting either (a) 500+ FT employees, or (b) 50–499 FT employees if they constitute 33%+ of the active workforce at that site, during any 30-day period.
- Notice must be sent to (1) affected employees or their reps, (2) state dislocated-worker unit, (3) local government chief elected official.
- **Penalty** for violation: back pay and benefits for each affected employee, up to 60 days, plus civil penalty up to $500/day to the local government.
- Exceptions: faltering company, unforeseeable business circumstances, natural disaster — each narrowly construed and shifting only the notice timing, not the obligation entirely.

#### Cal-WARN

- **Cal. Lab. Code §§1400–1408**.
- **Broader than federal WARN.** Applies to "covered establishments" — any industrial or commercial facility employing **75+ persons** in the preceding 12 months (counting both FT and PT, and including any employee who worked at any time in that 12 months).
- Triggers — **60 days advance written notice** for:
  - **Mass layoff** — layoff during any 30-day period of **50+ employees** at a covered establishment (no percentage-of-workforce threshold, unlike federal). 
  - **Relocation** — moving a covered establishment 100+ miles.
  - **Termination** — cessation or substantial cessation of operations at a covered establishment.
- Notice recipients: affected employees, the EDD, the local workforce investment board, and the chief elected official of each city/county where the establishment is located.
- **Penalty**: back pay and benefits for up to 60 days, plus $500/day civil penalty, plus attorney's fees.
- The "unforeseeable business circumstances" exception under federal WARN was **not** historically available under Cal-WARN, though the California legislature added a narrow COVID-era exception via Executive Order in 2020 that has since expired.

#### Which applies?

```
applies_federal_warn = (employees >= 100) AND (layoff_size >= 50 at one site over 30 days)
applies_cal_warn = (employees_in_past_12mo >= 75) AND (layoff_size >= 50 at covered establishment over 30 days)
# California employers must comply with whichever applies; usually Cal-WARN is the operative one.
```

#### Worked example

Scenario: employee at California tech company (200 FT employees), monthly salary $12,000 (~$554/day), involuntarily terminated on Monday March 9, 2026. Has 5 days of accrued vacation. Employer fails to issue final paycheck until Friday March 13.

1. **§201 deadline missed.** Final wages were due Monday March 9 at termination. Paid March 13.
2. Final wages owed at termination:
   - Salary through last day worked: pro-rated to March 9.
   - Vacation payout: 5 days × $554 = **$2,769** (Cal. Lab. Code §227.3).
3. **Waiting time penalty (§203):** 4 calendar days late × $554/day = **$2,215**.
4. If the delay had stretched to 30+ days: 30 × $554 = **$16,615** maximum penalty.
5. COBRA notice must go out within 14 days. Employee may elect 18-month continuation, paying up to 102% of the premium.
6. No WARN obligation — this is an individual termination, not a mass layoff.

Now scenario B: same employer eliminates 60 positions in one 30-day window.
- Federal WARN: 200 employees ≥100 ✓, 60 affected ≥ 50, and 60/200 = 30% — **fails the 33% threshold**, so federal WARN does NOT apply (unless 500+ are affected, which they aren't).
- **Cal-WARN: 200 employees ≥75 ✓, 60 affected ≥ 50 ✓** → 60 days notice required.
- Notice to: each affected employee, EDD, local workforce investment board, local elected officials.
- Failure penalty: 60 days × ~$554 × 60 employees = **~$1.99M back pay**, plus $500/day civil penalty, plus attorney's fees.

#### Sources

- California Legislative Information — **Labor Code §201**: <https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?sectionNum=201.&lawCode=LAB>
- California Legislative Information — **Labor Code §202**: <https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?sectionNum=202.&lawCode=LAB>
- California Legislative Information — **Labor Code §203**: <https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?sectionNum=203.&lawCode=LAB>
- California Legislative Information — **Labor Code §§1400–1408 (Cal-WARN)**: <https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?lawCode=LAB&division=2.&title=&part=4.&chapter=4.5.>
- California Legislative Information — **Labor Code §2922 (at-will)**: <https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?sectionNum=2922.&lawCode=LAB>
- California Division of Labor Standards Enforcement (DLSE) — *Final Pay FAQ*: <https://www.dir.ca.gov/dlse/faq_paydays.htm>
- US Department of Labor — **WARN Act**: <https://www.dol.gov/agencies/eta/layoffs/warn>
- California EDD — *Layoff Services and WARN*: <https://edd.ca.gov/Jobs_and_Training/Layoff_Services_WARN.htm>
- *Foley v. Interactive Data Corp.*, 47 Cal.3d 654 (1988)
- *Tameny v. Atlantic Richfield Co.*, 27 Cal.3d 167 (1980)
- Littler — *California Employment Law Letter* (ongoing updates): <https://www.littler.com/publication-press/publication/california-employment-law-letter>
- Baker McKenzie — *Global Employer Guide: United States*: <https://www.bakermckenzie.com/en/insight/publications/guides/global-employer-guide>

---

## Engine integration notes

The rules engine in `mcp_servers/jurisdiction_server.py` should expose the following deterministic outputs derived from this document:

- `get_termination_rules(country, employment_type, tenure_months)` → structured dict containing `notice_period_days`, `severance_formula`, `severance_components[]`, `mandatory_steps[]`, `protections_triggered[]`, `citation[]`.
- `validate_action(action, country, context)` → `{ compliant: bool, reason: str, recommendation: str, citation: str }`.
- `get_notice_period(country, tenure_months)` → integer days (employer-initiated, post-probation, default employment type).

When the orchestrator receives a country not covered here (JP, IN, and any others), the engine must return a structured "jurisdiction not covered — recommend legal review" response. It must never fall back to LLM-generated rules.
