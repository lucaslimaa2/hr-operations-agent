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

## United Kingdom (UK)

### Employment relationship overview

UK employment law is primarily statutory, layered over a contractual base. The two key tenure thresholds are (1) 2 years (unlocks unfair dismissal rights and statutory redundancy pay) and (2) the per-year scaling of statutory minimum notice. Probationary periods are contractual and have no special statutory status; statutory notice applies from the start of employment.

#### Legal framework

- **Employment Rights Act 1996 (ERA 1996)** the master statute. Notice in **§86**, unfair dismissal in **§§94–98**, statutory redundancy pay in **§§135, 155, 162**, automatically unfair grounds in **§§99–104**.
- **Trade Union and Labour Relations (Consolidation) Act 1992 (TULRCA) §188** collective redundancy consultation.
- **Public Interest Disclosure Act 1998 (PIDA)** whistleblower protection, amending ERA 1996 to make whistleblowing-related dismissal automatically unfair from day one.
- **Equality Act 2010** discrimination protections (no qualifying period).
- **ACAS Code of Practice on Disciplinary and Grievance Procedures** non-statutory, but tribunals may uplift compensation by up to 25% for unreasonable failure to follow it.

### Notice period rules

Statutory minimum notice under **ERA 1996 §86**, employer-initiated:

| Tenure | Statutory minimum notice |
|---|---|
| <1 month | None |
| 1 month to <2 years | 1 week |
| 2 years to <12 years | 1 week per full year of service |
| 12+ years | 12 weeks (cap) |

```
# Statutory minimum, employer-initiated
if tenure_months < 1:           notice_weeks = 0
elif tenure_years < 2:          notice_weeks = 1
else:                           notice_weeks = min(int(tenure_years), 12)
```

- Employee-initiated resignation: statutory minimum is **1 week** after 1 month of service, regardless of tenure (ERA 1996 §86(2)).
- The contract may specify longer notice (typically 1 to 3 months for professional employees, 3 to 6 months for senior roles); the contractual period applies if it exceeds the statutory minimum.
- **Payment in lieu of notice (PILON)** is permitted where the contract contains a PILON clause; otherwise, paying in lieu without such a clause is technically a breach of contract (though it rarely generates a claim because the employee is fully compensated). Since April 2018, all PILON payments are taxable as earnings (ITEPA 2003 §402B).
- **Garden leave** placing the employee on paid leave during their notice period to keep them out of the market is enforceable where the contract permits it.

### Severance and final pay

#### Statutory redundancy pay (ERA 1996 §§135, 162)

Available after **2 years of continuous service** where the dismissal qualifies as redundancy (the role has ceased to exist, the workplace has closed, or the business no longer needs work of that kind). The formula is age-weighted:

```
# For each full year of service, capped at 20 years (most recent 20)
years_under_22  = years employed while under age 22
years_22_to_40  = years employed while aged 22 to 40
years_41_plus   = years employed while aged 41 or older

statutory_redundancy_pay = (
    0.5 * weeks_pay * years_under_22 +
    1.0 * weeks_pay * years_22_to_40 +
    1.5 * weeks_pay * years_41_plus
)
# weeks_pay is capped at the statutory weekly maximum
# (verify against current government source for the 2026 figure; around £700 as of recent guidance)
# years_of_service capped at 20
```

- Only the **most recent 20 years** of service count (ERA 1996 §162(3)).
- A "week's pay" is capped at the statutory weekly maximum, set annually by the Secretary of State and published in the Employment Rights (Increase of Limits) Order. **Verify against the current government source for the 2026 figure** (recent years have been around £700/week).
- The statutory minimum is a floor; many employers offer enhanced redundancy on a contractual or discretionary basis.
- Statutory redundancy pay up to £30,000 is income-tax-free (ITEPA 2003 §403).

#### Final pay components

- Salary through last day worked.
- Accrued but untaken holiday, paid out under the Working Time Regulations 1998 reg. 14.
- Statutory redundancy pay if applicable.
- Any contractual notice pay or PILON.
- Bonus or commission per contract terms (pro-rata where the contract provides).

There is no general statutory severance outside redundancy. Negotiated exit packages typically use a **settlement agreement** (formerly "compromise agreement") under ERA 1996 §203, which is the only enforceable mechanism for the employee to waive statutory claims and requires independent legal advice paid for by the employer (market-standard contribution: £500 to £750).

### Unfair dismissal

#### Qualifying period and grounds

- **2 years of continuous service** required to bring an ordinary unfair dismissal claim (ERA 1996 §108(1)).
- **No qualifying period** for "automatically unfair" dismissals: pregnancy/maternity (§99), trade union activity (§152 TULRCA), whistleblowing (§103A, via PIDA 1998), health and safety activities (§100), assertion of statutory rights (§104), part-time worker discrimination (Part-time Workers Regulations 2000), or any Equality Act 2010 protected characteristic.
- Five potentially fair reasons under **ERA 1996 §98(2)**: capability, conduct, redundancy, statutory restriction (continued employment would breach a statute), and "some other substantial reason" (SOSR).
- The employer must show (a) the reason falls within one of these five categories and (b) it acted reasonably in treating that reason as sufficient for dismissal (§98(4)). Tribunals apply the "range of reasonable responses" test (*British Home Stores v Burchell* [1978] IRLR 379, *Iceland Frozen Foods v Jones* [1982] IRLR 439).

#### Process expectations

- The ACAS Code of Practice sets out the expected procedure: investigation, written allegations, hearing, decision, right of appeal. Failure to follow it can result in a tribunal uplift of compensation by up to 25% (TULRCA 1992 §207A).
- **ACAS Early Conciliation** is a mandatory pre-claim step: the employee must notify ACAS before issuing a tribunal claim (Employment Tribunals Act 1996 §18A).

#### Remedies (ERA 1996 §§112–117, §124)

- **Reinstatement or re-engagement** rarely ordered in practice.
- **Compensation:** a basic award (calculated like statutory redundancy pay) plus a compensatory award capped at the lower of one year's gross pay or the statutory cap (**verify against current government source for the 2026 figure**, recently around £115,000). The cap does not apply to automatically unfair dismissals on whistleblowing or discrimination grounds.

### Collective redundancy

Under **TULRCA 1992 §188**, where an employer proposes to dismiss as redundant **20 or more employees at one establishment within a 90-day period**, statutory consultation is required:

| Proposed redundancies (90-day window) | Minimum consultation period |
|---|---|
| 20 to 99 | 30 days before the first dismissal takes effect |
| 100+ | 45 days before the first dismissal takes effect |

- Consultation is with appropriate representatives (recognised trade union, or elected employee representatives if no union).
- Notification to the Secretary of State (via the BEIS form HR1) is required at the same time. Failure to notify is a criminal offence.
- Failure to consult exposes the employer to a **protective award** of up to 90 days' gross pay per affected employee (TULRCA §189), in addition to ordinary unfair dismissal liability.

### Edge cases

- **Protected categories blocking ordinary dismissal:** pregnancy/maternity (ERA 1996 §99), trade union membership and activity (TULRCA §152), whistleblowing (PIDA 1998, ERA §103A), part-time worker status (Part-time Workers Regulations 2000), fixed-term worker status (Fixed-term Employees Regulations 2002), assertion of statutory rights (ERA §104), jury service, working time complaints. Dismissal for any of these is automatically unfair with no qualifying period.
- **TUPE (Transfer of Undertakings (Protection of Employment) Regulations 2006)** dismissals connected to a relevant transfer are automatically unfair unless for an ETO reason (economic, technical, or organisational entailing changes in the workforce).
- **Wrongful dismissal** distinct from unfair dismissal; a contract-law claim for breach of notice provisions. No qualifying period and no statutory cap, but damages are limited to the notice period the employer should have given. Can be brought in the High Court or Employment Tribunal (tribunal cap of £25,000 applies).
- **Summary dismissal** dismissal without notice for gross misconduct. Permitted at common law; still subject to the unfair dismissal regime if the employee has 2+ years of service.

### Worked example

Scenario: full-time UK employee, **6 years 4 months tenure**, age 44, weekly pay £900 (above the statutory weekly cap), made redundant on operational grounds. No collective redundancy threshold triggered (single dismissal).

1. Statutory minimum notice: tenure 6 years → **6 weeks** (ERA 1996 §86).
2. Contractual notice (typical professional contract): 3 months. The longer applies → **3 months notice**, paid as PILON.
3. Statutory redundancy pay (ERA 1996 §162):
   - All 6 full years were worked while aged 22 to 40 (age 38 to 44 over the period). Years split: 2 years at ages 38 to 40 (factor 1.0) + 4 years at ages 41 to 44 (factor 1.5).
   - Week's pay capped at statutory weekly maximum (**verify against current government source for the 2026 figure**; assume £700 for this worked example).
   - Computation: `(1.0 * 700 * 2) + (1.5 * 700 * 4)` = `1,400 + 4,200` = **£5,600**.
4. Accrued holiday payout: assume 8 untaken days at £900/5 = £180/day → **£1,440** (Working Time Regulations 1998 reg. 14).
5. PILON: 3 months × £900 × 52/12 = **£11,700** (taxable as earnings under ITEPA 2003 §402B).
6. Total exit cost: approximately **£18,740**. Statutory redundancy element (£5,600) is income-tax-free up to £30,000.

If the employer had skipped consultation and the dismissal had been one of 25 at the same establishment in a 90-day window, TULRCA §188 would have applied: 30-day consultation period plus a potential protective award of up to 90 days' pay per affected employee.

### Sources

- legislation.gov.uk **Employment Rights Act 1996**: <https://www.legislation.gov.uk/ukpga/1996/18/contents>
- legislation.gov.uk **Trade Union and Labour Relations (Consolidation) Act 1992**: <https://www.legislation.gov.uk/ukpga/1992/52/contents>
- legislation.gov.uk **Public Interest Disclosure Act 1998**: <https://www.legislation.gov.uk/ukpga/1998/23/contents>
- legislation.gov.uk **Equality Act 2010**: <https://www.legislation.gov.uk/ukpga/2010/15/contents>
- GOV.UK **Calculate your statutory redundancy pay**: <https://www.gov.uk/calculate-your-redundancy-pay>
- GOV.UK **Notice periods**: <https://www.gov.uk/handing-in-your-notice>
- ACAS **Code of Practice on Disciplinary and Grievance Procedures**: <https://www.acas.org.uk/acas-code-of-practice-on-disciplinary-and-grievance-procedures>
- ACAS **Redundancy guidance**: <https://www.acas.org.uk/redundancy>
- *British Home Stores v Burchell* [1978] IRLR 379
- *Iceland Frozen Foods v Jones* [1982] IRLR 439
- Baker McKenzie *Global Employer Guide: United Kingdom*: <https://www.bakermckenzie.com/en/insight/publications/guides/global-employer-guide>
- DLA Piper *Guide to Going Global Employment: United Kingdom*: <https://www.dlapiperintelligence.com/goingglobal/employment/>

---

## France (FR)

### Employment relationship overview

French employment law combines a strongly protective statutory base (Code du travail) with industry-wide collective bargaining agreements (conventions collectives nationales, CCN) that frequently extend statutory minima. Almost every employee is covered by a CCN, and the engine must treat the CCN as potentially overriding the statutory floor (always in the employee's favour). Employee category (cadre / non-cadre) drives many of the statutory thresholds.

#### Legal framework

- **Code du travail** the master labour code. Key articles: **Art. L1221-19 to L1221-26** (période d'essai), **Art. L1232-2 to L1232-6** (entretien préalable and procedure), **Art. L1234-1 and L1234-9** (notice and indemnité de licenciement), **Art. L1233-3 to L1233-90** (licenciement économique), **Art. L1235-1 to L1235-17** (sanctions and Macron scale).
- **Conventions collectives nationales (CCN)** binding sectoral agreements (Syntec, Métallurgie, etc.) that typically extend statutory minima.
- **Ordonnance Macron du 22 septembre 2017 (n° 2017-1387)** introduced the indemnity scale (barème Macron) for unfair dismissal (licenciement sans cause réelle et sérieuse).
- **Conseil de prud'hommes** the employment tribunal of first instance; appeals to the Cour d'appel chambre sociale and ultimately the Cour de cassation.

### Période d'essai (probationary period)

The probation period must be in writing in the contract; it is not implied. Statutory maxima under **Art. L1221-19**:

| Employee category | Initial period | Maximum with renewal |
|---|---|---|
| Ouvriers / employés | 2 months | 4 months |
| Agents de maîtrise / techniciens | 3 months | 6 months |
| Cadres | 4 months | 8 months |

- Renewal must be expressly permitted by the applicable CCN and accepted in writing by the employee before the initial period expires (Cour de cassation, Soc. 25 février 2009, n° 07-40.155).
- During période d'essai, either party may terminate without cause and without indemnité de licenciement, subject to a short statutory **délai de prévenance** (warning period) scaling with tenure (Art. L1221-25): from 24 hours if employed less than 8 days, up to 1 month if employed 3+ months.
- KSchG-style social justification does **not** apply during période d'essai. The procedure remains lighter, though abuse of right (rupture abusive) remains actionable.

### Notice period rules (post-période d'essai)

Statutory minimum notice under **Art. L1234-1** for employer-initiated termination outside gross misconduct:

| Employee category | Tenure 6 months to <2 years | Tenure >=2 years |
|---|---|---|
| Non-cadre | 1 month | 2 months |
| Cadre | Typically 3 months by CCN | Typically 3 months by CCN |

- For non-cadres, the statute itself sets 1 month (6 mo to <2 yrs) and 2 months (≥2 yrs).
- For cadres, the Code du travail does not set a statutory cadre-specific period; the **3-month standard is set by industry-wide CCN** (e.g., Syntec for digital/consulting; the Convention collective nationale des cadres of 14 mars 1947 historically governed). The engine must treat 3 months as market-standard practice for cadres, with a flag to verify against the applicable CCN.
- The contract or CCN can lengthen these periods but cannot shorten them.
- Notice may be worked or indemnified (indemnité compensatrice de préavis), at the employer's discretion (Art. L1234-5).

### Indemnité de licenciement (statutory severance)

Available after **8 months of continuous service** under **Art. L1234-9** (threshold reduced from 1 year by the 2017 Macron ordonnances). Statutory minimum formula under **Art. R1234-2**:

```
indemnite_licenciement = (
    (1/4) * monthly_salary_de_reference * min(years_of_service, 10) +
    (1/3) * monthly_salary_de_reference * max(years_of_service - 10, 0)
)
# monthly_salary_de_reference is the higher of:
#   (a) average gross monthly salary over the 12 months preceding the termination notice
#   (b) one-third of the gross salary over the last 3 months (annualised), counting bonuses pro-rata
```

- 1/4 month per year for the first 10 years, 1/3 month per year thereafter.
- Pro-rata for incomplete years (the calculation runs in months, not just full years).
- The applicable CCN frequently provides a more generous formula; the more generous applies.
- The indemnité is income-tax-free within statutory limits (Code général des impôts Art. 80 duodecies); above those limits it becomes taxable.
- Not payable for licenciement pour faute grave or faute lourde (Art. L1234-9 by exclusion).

### Termination procedure

Every termination of an indefinite-term contract (CDI), regardless of grounds, requires the following procedure. Skipping any step exposes the employer to procedural unfairness damages even where substantive grounds are valid.

1. **Convocation à un entretien préalable** (Art. L1232-2): written notice by registered letter or hand-delivered against receipt, summoning the employee to a preliminary interview. Minimum **5 working days advance notice** between receipt of the convocation and the interview. Letter must state the purpose, date, time, place, and the employee's right to be assisted (by a coworker, or by a conseiller du salarié if there is no CSE in the firm).
2. **Entretien préalable** (Art. L1232-3): the employer states the grounds being considered and hears the employee's response. No decision may be communicated at the interview itself.
3. **Notification du licenciement** (Art. L1232-6): minimum **2 working days after the interview**, by registered letter with acknowledgement of receipt. The letter must state the precise grounds for dismissal; subsequent litigation is confined to the grounds set out in this letter (Cass. Soc., principe de fixation des motifs).
4. **Notice period** begins on receipt of the dismissal letter and runs through the dates set by Art. L1234-1 or the CCN.

For **licenciement économique** (economic grounds: redundancy), additional steps apply: CSE (Comité Social et Économique) consultation, priority-of-rehiring obligations, and where applicable a PSE (see below).

### Grounds for termination

- **Licenciement pour motif personnel** (Art. L1232-1): personal grounds. Subdivides into:
  - **Faute simple / sérieuse** misconduct warranting dismissal with notice and indemnité.
  - **Faute grave** misconduct so serious that continued employment is impossible; no notice, no indemnité, but accrued vacation still paid.
  - **Faute lourde** misconduct with intent to harm the employer; same as faute grave plus potential civil damages.
  - **Insuffisance professionnelle** inadequate performance, not misconduct. Notice and indemnité owed.
  - **Inaptitude médicale** medical incapacity certified by occupational health; specific reclassification obligations apply.
- **Licenciement pour motif économique** (Art. L1233-3): economic grounds. Definition expanded by the 2017 Macron ordonnances to include economic difficulties, technological change, reorganisation needed to safeguard competitiveness, and cessation of activity.

### Plan de sauvegarde de l'emploi (PSE)

Under **Art. L1233-61**, a PSE is mandatory for collective economic redundancies of **10 or more employees within a 30-day period at a firm with 50 or more employees**. The PSE must include:

- Concrete measures to avoid or limit dismissals (internal redeployment, reduced hours, training).
- Reclassement (redeployment) measures within the group, including international where applicable.
- Outplacement support (cellule de reclassement, congé de reclassement).
- A consultation procedure with the CSE.

The PSE must be either negotiated with trade unions (accord collectif majoritaire) or unilaterally drawn up by the employer and validated/approved by the **DREETS** (Direction régionale de l'économie, de l'emploi, du travail et des solidarités). Without an approved PSE, individual dismissals in the collective procedure are null (Art. L1235-10).

### Unfair dismissal and the barème Macron

Where the Conseil de prud'hommes finds the dismissal to be without cause réelle et sérieuse, indemnities are set on the **barème Macron** scale codified at **Art. L1235-3**:

- Floor and ceiling expressed in months of gross salary, varying by tenure (e.g., 1 year tenure: 1 to 2 months; 10 years: 3 to 10 months; 30+ years: 3 to 20 months).
- This scale is binding on labour courts since 2017; the Cour de cassation upheld its conformity with international labour standards (Cass. Soc. 11 mai 2022, n° 21-14.490).
- The scale does **not** apply to dismissals tainted by discrimination, harassment, breach of fundamental freedoms, or violation of protected status (pregnancy, whistleblowing, etc.), where indemnities remain uncapped (minimum 6 months) under Art. L1235-3-1.
- Statute of limitations to bring a claim before the Conseil de prud'hommes: **12 months** from notification of the dismissal (Art. L1471-1).

### Edge cases

- **Salariés protégés** (protected employees): CSE members, union delegates, conseillers du salarié, conseillers prud'hommes. Termination requires prior authorisation from the Inspection du travail (Art. L2411-1 et seq.). Failure to obtain authorisation makes the dismissal automatically null.
- **Pregnant employees and maternity leave** (Art. L1225-4): termination is prohibited during pregnancy, maternity leave, and the 10 weeks following return. Exceptions narrowly limited to faute grave unconnected to pregnancy or impossibility of maintaining the contract for reasons unconnected to pregnancy.
- **Inaptitude médicale**: where occupational health certifies inaptitude, the employer must search for reclassement options before any dismissal can proceed (Art. L1226-2 for non-occupational, L1226-10 for occupational origin).
- **Rupture conventionnelle** (Art. L1237-11 et seq.): negotiated mutual termination, separate from licenciement. Requires at least one interview, a written agreement, a 15-day withdrawal period for each party, and DREETS homologation. Employee receives at minimum the indemnité de licenciement and retains unemployment benefits. Increasingly common in practice as a faster, lower-litigation alternative.
- **CDD (fixed-term contract) early termination**: only permitted for faute grave, force majeure, mutual agreement, inaptitude, or where the employee has secured a CDI elsewhere (Art. L1243-1). Unjustified early termination by the employer owes the employee all remaining salary through the original term plus indemnité de fin de contrat.

### Worked example

Scenario: cadre (manager) in a 200-employee firm, **6 years tenure**, monthly gross salary EUR 5,500 (no significant variable comp), licenciement pour motif personnel (insuffisance professionnelle), procedure followed correctly.

1. **Convocation à entretien préalable** sent 13 May, interview held 22 May (more than 5 working days). Dismissal letter sent 26 May (more than 2 working days after the interview).
2. **Notice period (cadre, ≥2 yrs tenure)**: 3 months by CCN (Syntec assumed) → notice runs 26 May to 26 August 2026.
3. **Indemnité de licenciement** (Art. R1234-2):
   - Tenure: 6 years. Salaire de référence: EUR 5,500/month.
   - `(1/4) * 5500 * 6` = `1375 * 6` = **EUR 8,250**.
4. **Indemnité compensatrice de congés payés**: assume 12 days of acquired but untaken leave at EUR 5500 × 12 / 217 working days ≈ EUR 304/day → **EUR 3,650**.
5. **Notice paid as worked** (no PILON in this scenario): 3 months × EUR 5,500 = **EUR 16,500** as ordinary salary.
6. Total exit cost: approximately **EUR 28,400**, plus social charges on the salary components.

If the employee had then filed at the Conseil de prud'hommes and succeeded in having the dismissal qualified as sans cause réelle et sérieuse, the barème Macron for 6 years tenure would set additional damages at between roughly 3 and 7 months of gross salary, on top of the indemnité de licenciement already paid.

### Sources

- Legifrance **Code du travail**: <https://www.legifrance.gouv.fr/codes/texte_lc/LEGITEXT000006072050/>
- Legifrance **Art. L1234-1 (préavis)**: <https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000019071190>
- Legifrance **Art. L1234-9 (indemnité de licenciement)**: <https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000035644154>
- Legifrance **Art. R1234-2 (calcul de l'indemnité)**: <https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000036482086>
- Legifrance **Art. L1232-2 et seq. (procédure)**: <https://www.legifrance.gouv.fr/codes/section_lc/LEGITEXT000006072050/LEGISCTA000006177833/>
- Legifrance **Art. L1233-61 (PSE)**: <https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000036762105>
- Legifrance **Art. L1235-3 (barème Macron)**: <https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000036762052>
- Ministère du Travail **Le licenciement pour motif personnel**: <https://travail-emploi.gouv.fr/le-licenciement-pour-motif-personnel>
- Ministère du Travail **Le licenciement pour motif économique**: <https://travail-emploi.gouv.fr/le-licenciement-pour-motif-economique>
- Cass. Soc. 11 mai 2022, n° 21-14.490 (conformité du barème Macron)
- Cass. Soc. 25 février 2009, n° 07-40.155 (renouvellement de la période d'essai)
- Baker McKenzie *Global Employer Guide: France*: <https://www.bakermckenzie.com/en/insight/publications/guides/global-employer-guide>
- DLA Piper *Guide to Going Global Employment: France*: <https://www.dlapiperintelligence.com/goingglobal/employment/>

---

## Spain (ES)

### Employment relationship overview

Spanish employment law is codified in the **Estatuto de los Trabajadores** (Workers' Statute, Royal Legislative Decree 2/2015), with sectoral collective bargaining agreements (convenios colectivos) overlaying the statute. The core distinction in termination is between **despido objetivo** (objective dismissal, with severance), **despido disciplinario** (disciplinary dismissal, no severance if upheld), and **despido improcedente** (unfair dismissal, higher severance). Procedure is heavily formalised: a carta de despido (written dismissal letter) is mandatory for every dismissal, and the SMAC conciliation step precedes any tribunal claim.

#### Legal framework

- **Estatuto de los Trabajadores (ET)** Real Decreto Legislativo 2/2015, de 23 de octubre. Key articles: **Art. 49** (causes of termination), **Art. 51** (despido colectivo), **Art. 52 to 53** (despido objetivo), **Art. 54 to 55** (despido disciplinario), **Art. 56** (despido improcedente), **Art. 14** (período de prueba).
- **Ley Reguladora de la Jurisdicción Social (LRJS)** Ley 36/2011, governing labor court procedure.
- **Ley 3/2012, de 6 de julio** the 2012 labour reform that reduced unfair-dismissal severance from 45 to 33 days per year of service for service accruing from 12 February 2012.
- **SMAC** (Servicio de Mediación, Arbitraje y Conciliación, regionally named e.g., SMAC, CMAC, UMAC) mandatory conciliation step before filing in the Juzgado de lo Social.
- **Juzgado de lo Social** labor court of first instance; appeals to the Sala de lo Social of the Tribunal Superior de Justicia and ultimately the Tribunal Supremo.

### Período de prueba (probationary period)

Under **Art. 14 ET**, the probation period must be in writing and respect the maxima set by the applicable convenio colectivo; statutory defaults where the convenio is silent:

- **Técnicos titulados** (qualified technical staff): up to 6 months.
- **Other employees**: up to 2 months (or 3 months in companies of fewer than 25 employees).
- During período de prueba, either party may terminate without cause and without indemnización, subject only to good faith.

### Notice period rules

- **Despido objetivo** (Art. 53.1.c ET): **15 calendar days** advance written notice from the date of the carta de despido to the effective termination date. If the employer skips the notice, the carta remains valid but the employer owes 15 days of salary in lieu (Art. 53.4 hands of the courts).
- **Despido disciplinario** (Art. 55 ET): **no statutory notice period**. Effective immediately on delivery of the carta de despido.
- **Despido colectivo** (Art. 51 ET): no individual notice as such, but the consultation period (período de consultas) of 15 to 30 days precedes any dismissal.
- **Employee resignation (baja voluntaria)**: notice period set by the convenio colectivo, typically 15 days for non-management roles. Failure to give notice exposes the employee to damages equal to the missed notice days.

### Severance and final pay

#### Despido objetivo (Art. 53 ET)

Available where the employer can demonstrate one of the Art. 52 grounds: incapacity discovered post-hire, failure to adapt to technical changes, economic / technical / organisational / production reasons (causas ETOP), or excessive justified absences (since constitutional revision of Art. 52.d).

```
indemnizacion_despido_objetivo = (
    20 * daily_salary * years_of_service
)
# Capped at 12 monthly salaries (Art. 53.1.b ET)
# Pro-rata for incomplete years (full periods in months, not just full years)
# daily_salary = (annual_gross_including_pro_rata_bonuses) / 365
```

- **20 days of salary per year of service**, capped at **12 monthly salaries**.
- Severance paid simultaneously with delivery of the carta de despido (Art. 53.1.b). Failure to put the severance at the employee's disposal at the moment of notification renders the despido improcedente by formal defect (Tribunal Supremo, Sala de lo Social, doctrina consolidada; partial exception where the employer alleges and proves a lack of liquidity for ETOP causes).
- Plus **15 calendar days notice** or pay in lieu (Art. 53.1.c).

#### Despido disciplinario (Art. 54 to 55 ET)

For serious and culpable misconduct: repeated unjustified absences, indiscipline, verbal or physical abuse, breach of contractual good faith, drug or alcohol use affecting work, harassment, etc. (exhaustive list at Art. 54.2).

- **Upheld (procedente)**: **no severance, no notice**. Employee receives only finiquito (settlement of salary through last day worked plus accrued vacation and pro-rata extra payments).
- **Reduced to unfair (improcedente)**: see Art. 56 below.

#### Despido improcedente (Art. 56 ET)

When the despido is found procedurally or substantively defective by the Juzgado de lo Social, or when the employer recognises improcedencia from the outset:

```
indemnizacion_despido_improcedente = (
    33 * daily_salary * years_after_12_feb_2012 +
    45 * daily_salary * years_before_12_feb_2012
)
# Service before 12 February 2012 retains the pre-reform 45-days rate.
# Combined cap: the lower of (a) 720 days' salary (24 months) for post-reform service alone,
# or (b) the amount that would have applied under the pre-reform formula for hires before 12 Feb 2012,
# with absolute ceiling of 42 monthly salaries for legacy hires (Disposición transitoria 11ª).
```

- **33 days of salary per year of service** for service from 12 February 2012, capped at **24 monthly salaries**.
- For employees hired **before 12 February 2012**, the pre-reform **45 days per year** rate continues to apply to service accrued before that date, then 33 days for service after; the combined indemnity is capped at 42 monthly salaries (or 720 days, whichever is more favourable, under Disposición transitoria 11ª ET).
- Following a finding of improcedencia, the employer (or in some statutorily defined cases the employee, e.g., union representatives) elects within 5 days between (a) paying the indemnización and confirming the termination, or (b) reinstating the employee with back-pay of "salarios de tramitación" from dismissal to reinstatement (Art. 56.2).
- No notice owed separately when improcedencia is paid.

#### Despido nulo

Reserved for dismissals tainted by discrimination, violation of fundamental rights, or in respect of protected categories (pregnancy, maternity leave, parental leave, victims of gender violence, etc., under Art. 55.5 ET). Consequence: **mandatory reinstatement** with back-pay; the employer has no option to pay indemnización instead.

#### Finiquito

The settlement document signed at termination, covering:

- Salary through the last day worked.
- Pro-rata extra payments (pagas extraordinarias) the standard Spanish 14-payment structure means employees accrue summer and Christmas extra payments throughout the year; the unaccrued portion is paid out at termination.
- Vacation accrued but untaken (Art. 38 ET).
- Any severance owed.

Signing the finiquito with a "saldo y finiquito" clause can have a settlement effect; employees frequently sign "no conforme" to preserve the right to challenge.

### Termination procedure

Every dismissal requires a **carta de despido** under **Art. 53.1.a (objetivo) and Art. 55.1 (disciplinario)** containing:

1. The precise grounds for dismissal (specific facts, dates, and where applicable the ET article invoked).
2. The effective date of termination.
3. For despido objetivo: simultaneous tender of the severance and the 15-day notice.

The employer is locked into the grounds stated in the carta; new grounds raised later in litigation are inadmissible (principio de invariabilidad de la causa). Procedural defects in the carta (missing grounds, vague description, wrong date) typically result in a finding of improcedencia.

Before any litigation, the **SMAC conciliation step is mandatory** under LRJS Art. 63. The employee must submit a papeleta de conciliación within **20 working days** of the dismissal (Art. 59.3 ET) this is the statute of limitations for filing a despido claim. Failing or unsuccessful conciliation, the claim proceeds to the Juzgado de lo Social.

### Despido colectivo (Art. 51 ET)

Collective dismissal thresholds within a **90-day period**:

| Firm size | Threshold for collective dismissal |
|---|---|
| <100 employees | 10 employees dismissed |
| 100 to 300 employees | 10% of the workforce dismissed |
| >300 employees | 30 employees dismissed |

Additionally, any dismissal of the entire workforce affecting more than 5 employees is treated as collective regardless of firm size.

- Triggers a mandatory **período de consultas** with worker representatives lasting **15 days** (firms under 50 employees) or **30 days** (firms of 50+).
- Notification to the labour authority (Autoridad Laboral) at the start of the período de consultas.
- During consultation, the employer must provide a substantial information dossier including causes, criteria for selection of affected employees, redeployment measures, and outplacement plan.
- The statutory floor of 20 days per year of service / 12-month cap applies to each affected employee (same as despido objetivo); convenios colectivos frequently negotiate enhanced packages.
- A negotiated agreement at the end of the período de consultas is binding; absent agreement, the employer may proceed but exposes itself to enhanced judicial scrutiny.

### Edge cases

- **Protected categories under Art. 55.5 ET**: pregnancy, maternity / paternity leave, breastfeeding leave, parental leave, victims of gender-based violence, and reinstatement following maternity for up to 12 months. Dismissal of these employees is **nulo** (mandatory reinstatement) unless the employer proves a cause wholly unconnected to the protected status.
- **Union representatives and works council members**: enhanced protection under Art. 68.c ET, with priority in any redundancy selection and additional procedural safeguards. Dismissal opens a contradictory expediente (internal procedure) where the employer must hear the representative and the other members of the body.
- **Fixed-term contracts (contratos de duración determinada)** since the 2021 reform (Real Decreto-ley 32/2021), fixed-term contracts are restricted to specific objective causes (production-related or substitution) and improperly used FTCs are deemed indefinidos.
- **Statute of limitations**: 20 working days from the effective date of dismissal to file the papeleta de conciliación at SMAC (Art. 59.3 ET). This is a hard caducidad (forfeiture) deadline, not prescripción; missing it extinguishes the claim entirely.
- **Pro-rata for part-time employees**: Art. 12.4 ET prorates severance entitlements by hours worked relative to a comparable full-time employee. The 20-days-per-year and 33-days-per-year formulas use the part-time salary directly, so proration is implicit through the daily salary input.

### Worked example

Scenario: full-time Spanish employee, **5 years 6 months tenure**, monthly gross salary EUR 3,200 (14 payments = EUR 44,800 annual gross), dismissed via despido objetivo for economic causes (causa ETOP). Hired in 2020 (entirely post-12-Feb-2012 service).

1. **Carta de despido** delivered on 1 June 2026 stating economic causes, 15 days notice, severance tendered simultaneously with the carta. Effective termination date: 16 June 2026.
2. **Daily salary**: EUR 44,800 / 365 = approximately **EUR 122.74/day**.
3. **Indemnización despido objetivo** (Art. 53.1.b):
   - 5.5 years × 20 days = 110 days of salary.
   - 110 × 122.74 = **EUR 13,501**.
   - Cap check: 12 monthly salaries = EUR 38,400. Below cap, full amount payable.
4. **15 days notice paid as worked**: salary through 16 June.
5. **Finiquito**:
   - Salary through 16 June.
   - Pro-rata summer extra payment (paga extraordinaria de verano), accrued January through June: approximately EUR 1,600.
   - Vacation accrued but untaken: assume 8 days at EUR 122.74 = **EUR 982**.
6. Total exit cost: approximately **EUR 17,650** including severance, accrued extras, and vacation; plus the worked notice period salary.

Now scenario B: same employee, but the Juzgado de lo Social finds the economic causa was not adequately substantiated and qualifies the despido as improcedente.

1. **Indemnización despido improcedente** (Art. 56):
   - 5.5 years × 33 days = 181.5 days of salary.
   - 181.5 × 122.74 = **EUR 22,277**.
   - Cap check: 24 monthly salaries = EUR 76,800. Below cap.
2. The employer elects to pay the indemnización and confirm the termination (the typical choice for individual contributor roles). Difference owed beyond the EUR 13,501 already paid as despido objetivo: approximately **EUR 8,776**.
3. No back-pay (salarios de tramitación) owed because the employer elected indemnización rather than reinstatement.

### Sources

- BOE **Real Decreto Legislativo 2/2015 (Estatuto de los Trabajadores)**: <https://www.boe.es/buscar/act.php?id=BOE-A-2015-11430>
- BOE **Ley 36/2011 (LRJS)**: <https://www.boe.es/buscar/act.php?id=BOE-A-2011-15936>
- BOE **Ley 3/2012, de 6 de julio (reforma laboral)**: <https://www.boe.es/buscar/act.php?id=BOE-A-2012-9110>
- BOE **Real Decreto-ley 32/2021 (reforma de la contratación temporal)**: <https://www.boe.es/buscar/act.php?id=BOE-A-2021-21788>
- Ministerio de Trabajo y Economía Social **Extinción del contrato de trabajo**: <https://www.mites.gob.es/es/Guia/texto/guia_5/contenidos/guia_5_15_1.htm>
- Tribunal Supremo, Sala de lo Social doctrina sobre puesta a disposición de la indemnización (e.g., STS 17 enero 2011, rec. 4314/2009).
- Baker McKenzie *Global Employer Guide: Spain*: <https://www.bakermckenzie.com/en/insight/publications/guides/global-employer-guide>
- DLA Piper *Guide to Going Global Employment: Spain*: <https://www.dlapiperintelligence.com/goingglobal/employment/>
- Cuatrecasas *Despidos colectivos en España*: <https://www.cuatrecasas.com/es/spain/employment/>

---

## Italy (IT)

### Employment relationship overview

Italian employment law combines the **Codice Civile** (master civil code, governing the employment contract as a species of subordinate work obligation) with a layered set of statutes (the **Statuto dei Lavoratori**, the **Jobs Act**, the **Law 223/1991** collective dismissal framework) and an extensive network of national collective bargaining agreements (**CCNL**, contratti collettivi nazionali di lavoro) that fix the operational detail of notice periods, leave, and severance treatments. The applicable CCNL is determined by the employer's sector (Commercio, Metalmeccanico, Credito, etc.) and the employee's qualifica (operaio, impiegato, quadro, dirigente). The engine treats the **Commercio CCNL impiegato** schedule as the default reference and flags that the sectoral CCNL actually applicable to the employer controls in practice.

#### Legal framework

- **Codice Civile, Art. 2118 to 2120**: notice (Art. 2118), giusta causa (Art. 2119), and trattamento di fine rapporto (TFR, Art. 2120).
- **Statuto dei Lavoratori (Legge 20 maggio 1970, n. 300)**: foundational employee-protection statute. **Art. 18** historically required reinstatement at firms with 15+ employees for unfair dismissals; partially superseded by the Jobs Act for new hires from 7 March 2015.
- **Legge 15 luglio 1966, n. 604**: requires a written, justified dismissal letter and sets the giustificato motivo framework.
- **Legge 23 luglio 1991, n. 223 (Arts. 4 and 5)**: licenziamento collettivo procedure.
- **Jobs Act, Decreto Legislativo 4 marzo 2015, n. 23**: introduced the **contratto a tutele crescenti** for new hires from 7 March 2015, replacing reinstatement with monetary indemnity in most unfair-dismissal cases.
- **Decreto Legislativo 26 marzo 2001, n. 151**: protection of pregnant employees and parents (Art. 54 prohibits dismissal during pregnancy and the first year of the child's life).
- **CCNL**: sector-level collective agreements. The Commercio CCNL is treated as the engine's default reference for white-collar impiegato roles; the Metalmeccanico, Credito, Studi Professionali, and other CCNL govern in their respective sectors.

### Notice period rules (preavviso, Art. 2118 CC)

Statutory Art. 2118 requires "congruo preavviso" but defers the schedule to the CCNL. The **Commercio CCNL** impiegato schedule, used here as the default reference, scales by qualifica and tenure:

| Qualifica (Commercio CCNL, impiegato default) | Tenure <5 yrs | Tenure 5 to 10 yrs | Tenure >10 yrs |
|---|---|---|---|
| Quadri / 1° livello | 60 days | 90 days | 120 days |
| 2° livello | 45 days | 60 days | 75 days |
| 3° livello | 30 days | 45 days | 60 days |
| 4° to 7° livello | 20 days | 30 days | 45 days |

- The engine's default for a white-collar impiegato at the 3°/4° livello is **30 days at <5 years tenure, scaling to 60 days at 10+ years**; for dirigenti and quadri, durations are materially longer and should be looked up against the actual CCNL.
- The applicable sectoral CCNL controls in practice; the schedule above is illustrative for the default Commercio impiegato case.
- Notice runs from the 1st or the 16th of the calendar month (a CCNL convention known as the "regola della quindicina") in most agreements; verify the exact rule against the controlling CCNL.
- Notice can be worked or paid in lieu (**indennità sostitutiva del preavviso**) at the employer's election (Art. 2118 CC).
- **No notice** is owed where the dismissal is for **giusta causa** (Art. 2119 CC): conduct so serious that the employment relationship cannot continue even temporarily.

### TFR (trattamento di fine rapporto, Art. 2120 CC)

TFR is a deferred-compensation entitlement that accrues each year of service and is paid on **any termination**, including voluntary resignation, dismissal for any cause (including giusta causa), retirement, and end of fixed-term contracts. It is a hard statutory entitlement and cannot be waived.

```
# Annual TFR accrual under Art. 2120 CC
tfr_accrual_year_n = gross_annual_salary_year_n / 13.5
# Roughly 7.41% per year (1/13.5 = 0.07407...), NOT the often-quoted 8.33%.

# Annual revaluation of the cumulative TFR stock under Art. 2120 para. 4:
#   revaluation_rate = 1.5% fixed + 75% of the annual ISTAT cost-of-living index
tfr_stock_year_end = (tfr_stock_year_start + tfr_accrual_year_n) * (1 + revaluation_rate)
```

- Statutory formula: **gross annual salary divided by 13.5** per year of service. This works out to approximately 7.41% (1 / 13.5), not the 8.33% (1 / 12) sometimes quoted in informal sources. The 13.5 denominator dates from a legislative quirk and is the figure that appears in Art. 2120.
- The accrued TFR stock is **revalued annually** at a fixed 1.5% plus 75% of the ISTAT cost-of-living index for the year (Art. 2120 para. 4).
- The employee may opt to redirect ongoing TFR accruals to a supplementary pension fund (fondo pensione) under D.Lgs. 252/2005; the employer's payment obligation transfers to the fund but the underlying accrual mechanic is unchanged.
- A statutory advance of up to 70% of accrued TFR is available after 8 years of service for specific purposes (purchase of first home, medical expenses; Art. 2120 paras. 6 to 11).
- For small firms (<50 employees), TFR is paid directly by the employer at termination; for larger firms, the **Fondo di Tesoreria** managed by INPS receives the contributions and pays the employee on termination.

### Grounds for termination

- **Giustificato motivo soggettivo** (Legge 604/1966 Art. 3, second limb): notable breach of contractual obligations short of giusta causa. Notice is owed; TFR and accrued items paid in full.
- **Giustificato motivo oggettivo** (Legge 604/1966 Art. 3, first limb): reasons inherent to the productive activity, work organisation, or its regular functioning. Examples: role suppression, economic difficulties at the unit level, technological reorganisation. Notice is owed; TFR and accrued items paid in full. Where the dismissal is for economic reasons, the employer should have considered redeployment (repêchage) within the firm.
- **Giusta causa** (Codice Civile Art. 2119): conduct so serious that the relationship cannot continue even for the duration of the notice period. Examples: theft from the employer, gross insubordination, serious breach of fiduciary duty. **No notice**, but TFR and accrued vacation are still paid.
- **Licenziamento collettivo** (Legge 223/1991): firms with **15+ employees** proposing **5+ dismissals** within the same provincia within a **120-day period**. Triggers a mandatory consultation procedure (see below).

### Termination procedure for individual dismissals

Under **Legge 604/1966 Art. 2**, every dismissal must be:

1. **In writing** (forma scritta ad substantiam). An oral dismissal is null and the employee can demand reinstatement regardless of firm size or hire date.
2. **Motivated in writing**, with the specific grounds set out in the letter. The grounds bind the employer in any subsequent litigation; new grounds cannot be added later.
3. **Notified** to the employee (registered letter with acknowledgement of receipt, hand delivery against signed receipt, or PEC certified email).

For **giustificato motivo soggettivo and giusta causa**, the disciplinary procedure under **Art. 7 of the Statuto dei Lavoratori** must be followed: written contestation of the disciplinary facts (contestazione disciplinare), minimum 5-day window for the employee to provide written defence and request a hearing, then the dismissal letter. Skipping these steps renders the dismissal procedurally defective.

For **giustificato motivo oggettivo** at firms with **15+ employees** and hires **before 7 March 2015**, the prior conciliation procedure before the **Ispettorato Territoriale del Lavoro** is required (Legge 604/1966 Art. 7 as amended by Legge 92/2012, Fornero reform). The Jobs Act removed this for new hires under the contratto a tutele crescenti.

### Unfair dismissal regimes (tutele crescenti vs Art. 18)

The applicable regime depends on the **date of hire** and the **firm size**.

#### Hires from 7 March 2015 (contratto a tutele crescenti, D.Lgs. 23/2015)

- **Firms with 15+ employees**: monetary indemnity in most cases, calibrated by tenure. Indemnity for unfair dismissal on substantive grounds: **2 months' salary per year of service, with a floor of 6 months and a ceiling of 36 months** (D.Lgs. 23/2015 Art. 3.1, as amended after Constitutional Court ruling 194/2018 struck down the original rigid formula).
- **Firms under 15 employees**: floor of 3 months, ceiling of 6 months (Art. 9).
- Reinstatement is reserved for **dismissal that is null** (discrimination, retaliation, pregnancy, oral form) and for **manifest fact-finding defects** (i.e., the alleged misconduct did not occur; Art. 3.2).

#### Hires before 7 March 2015 (Statuto dei Lavoratori Art. 18, as modified by Fornero reform)

- **Firms with 15+ employees**: graduated regime introduced by the Fornero reform (Legge 92/2012). Reinstatement remains available for the most serious categories of unfair dismissal (discriminatory, retaliatory, lacking material grounds entirely). For ordinary unfair dismissal on inadequate grounds, the remedy is an indemnity of 12 to 24 months' salary (Art. 18 paras. 4 to 7).
- **Firms under 15 employees**: indemnity of 2.5 to 6 months' salary under Legge 604/1966 Art. 8, no reinstatement.

### Licenziamento collettivo (Legge 223/1991, Arts. 4 and 5)

Applies to firms with **15+ employees** proposing **5+ dismissals at the same provincia within a 120-day period** for the same economic / organisational reasons. The procedure has three phases:

1. **Comunicazione di avvio** (Art. 4 para. 2): written notification to the **RSU** (rappresentanze sindacali unitarie) or to the sectoral unions, and concurrently to the **Ufficio Provinciale del Lavoro** and **Direzione Provinciale del Lavoro**. The notification details the reasons, the number and profiles of affected employees, the proposed timeline, and the selection criteria.
2. **Esame congiunto** (consultation, Art. 4 paras. 5 to 8): joint examination with union representatives over a maximum of 45 days (extendable). The aim is to identify alternatives, redeployment options, and to negotiate selection criteria.
3. **Notification of dismissals** (Art. 4 para. 9): if no agreement is reached, the employer notifies the labour authority of the outcome of the consultation and proceeds with individual dismissal letters, applying the agreed or statutorily required selection criteria (carichi di famiglia, anzianità di servizio, esigenze tecnico-produttive e organizzative; Art. 5).

Failure to follow the procedure exposes the employer to dismissal annulment (with the same remedies as unfair individual dismissal under the applicable regime) plus potential collective sanctions.

### Edge cases

- **Pregnant employees and parents** (D.Lgs. 151/2001 Art. 54): dismissal is prohibited from the start of pregnancy until the child's first birthday. Narrow exceptions: giusta causa, cessation of the firm's activity, end of fixed-term contract, or completion of the task for which the worker was hired. Dismissal in violation is null.
- **Employees on sick leave for work-related injury or illness** (Codice Civile Art. 2110): employment is protected for a "periodo di comporto" determined by the applicable CCNL (typically 6 to 12 months). Dismissal during the comporto for absence-related reasons is null.
- **Union representatives** (Statuto dei Lavoratori Art. 22): transfers and dismissals of RSA / RSU members require prior consent of the union or judicial authorisation.
- **Parental leave** (D.Lgs. 151/2001): protection extends to fathers exercising parental leave rights.
- **Dirigenti**: senior managers have a separate regime. Termination requires "giustificatezza" rather than "giustificato motivo" (a lower standard); CCNL Dirigenti del Commercio and equivalent agreements set additional severance ("indennità supplementare") payable on unjustified termination.

### Worked example

Scenario: white-collar **impiegato 3° livello** under the Commercio CCNL, hired on **1 September 2020** (post-7 March 2015, so contratto a tutele crescenti applies), firm has **80 employees**, gross annual salary EUR 36,000 (13 monthly payments of EUR 2,770 approximately, plus thirteenth month). Dismissal date **15 December 2026** for giustificato motivo oggettivo (role suppression following reorganisation).

1. **Tenure at dismissal**: 6 years 3 months.
2. **Notice (preavviso)**: Commercio CCNL impiegato 3° livello, tenure 5 to 10 years → **45 days**. Paid as indennità sostitutiva (PILON-equivalent): 45/30 × EUR 2,770 ≈ **EUR 4,155**.
3. **TFR accrued through dismissal**:
   - Annual accrual: EUR 36,000 / 13.5 = EUR 2,667 per year.
   - 6.25 years of accruals, with annual revaluation. Ignoring revaluation for simplicity: 6.25 × EUR 2,667 ≈ **EUR 16,667**. With cumulative revaluation at average 2% per year, the actual stock would be approximately **EUR 17,200 to EUR 17,500**.
4. **Pro-rata thirteenth month** (tredicesima) accrued January through 15 December: approximately 11.5/12 × EUR 2,770 ≈ **EUR 2,655**.
5. **Pro-rata fourteenth month** if the CCNL provides one (Commercio does not; some sectors do): EUR 0 in this scenario.
6. **Vacation accrued but untaken**: assume 10 days at EUR 2,770/22 ≈ EUR 126/day → **EUR 1,260**.
7. **Total exit cost**: approximately **EUR 25,700 to EUR 26,000** before social charges on salary components.

If the Tribunale del Lavoro had subsequently found the giustificato motivo oggettivo to be inadequately substantiated, the contratto a tutele crescenti regime would set an indemnity of 2 months' salary per year of service, here ≈ 12.5 months × EUR 2,770 = EUR 34,625, within the 6 to 36 month range under Art. 3.1 D.Lgs. 23/2015.

### Sources

- Normattiva **Codice Civile, Libro V, Titolo II, Capo I (Arts. 2094 to 2134)**: <https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:codice.civile>
- Normattiva **Legge 20 maggio 1970, n. 300 (Statuto dei Lavoratori)**: <https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1970-05-20;300>
- Normattiva **Legge 15 luglio 1966, n. 604**: <https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1966-07-15;604>
- Normattiva **Legge 23 luglio 1991, n. 223**: <https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1991-07-23;223>
- Normattiva **D.Lgs. 4 marzo 2015, n. 23 (Jobs Act, contratto a tutele crescenti)**: <https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:decreto.legislativo:2015-03-04;23>
- Normattiva **D.Lgs. 26 marzo 2001, n. 151 (tutela genitorialità)**: <https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:decreto.legislativo:2001-03-26;151>
- Corte Costituzionale, sentenza n. 194/2018 (illegittimità del meccanismo rigido di calcolo dell'indennità).
- Ministero del Lavoro e delle Politiche Sociali **Cessazione del rapporto di lavoro**: <https://www.lavoro.gov.it/temi-e-priorita/rapporti-di-lavoro-e-relazioni-industriali>
- INPS **TFR e Fondo di Tesoreria**: <https://www.inps.it/it/it/dettaglio-scheda.schede-servizio-strumento.schede-servizi.fondo-di-tesoreria-50441.fondo-di-tesoreria.html>
- CCNL Commercio (Confcommercio / Filcams-Cgil, Fisascat-Cisl, Uiltucs-Uil): consultable via CNEL archive at <https://www.cnel.it/Archivio-Contratti>
- Baker McKenzie *Global Employer Guide: Italy*: <https://www.bakermckenzie.com/en/insight/publications/guides/global-employer-guide>
- DLA Piper *Guide to Going Global Employment: Italy*: <https://www.dlapiperintelligence.com/goingglobal/employment/>

---

## Singapore (SG)

### Employment relationship overview

Singapore employment law is anchored in the **Employment Act (Chapter 91)**, supplemented by Ministry of Manpower (**MOM**) guidelines and the tripartite advisories produced jointly by MOM, the National Trades Union Congress (NTUC), and the Singapore National Employers Federation (SNEF). The Employment Act covers all employees earning up to certain thresholds and most managerial / executive staff after the 2019 amendments, with carve-outs for seafarers, domestic workers, and public-sector employees governed by separate regimes. Disputes flow through mandatory mediation at the **Tripartite Alliance for Dispute Management (TADM)** before reaching the **Employment Claims Tribunal (ECT)**.

#### Legal framework

- **Employment Act (Chapter 91)**: the master statute. Notice in **§10**, dismissal in **§14**, retrenchment-related provisions and salary in lieu in **Part IV**.
- **Tripartite Advisory on Managing Excess Manpower and Responsible Retrenchment (December 2020, updated)**: MOM / NTUC / SNEF guidance on retrenchment process and benefit norms.
- **Tripartite Guidelines on Wrongful Dismissal (2019)**: define the categories of dismissal considered wrongful (dismissal without notice or salary in lieu absent misconduct, dismissal to deprive the employee of statutory entitlements, discriminatory dismissal, etc.).
- **Tripartite Guidelines on Fair Employment Practices (TGFEP)**: the workplace fairness framework; statutory enactment expected via the Workplace Fairness Legislation (Workplace Fairness Act, passed 2025, phased commencement).
- **Employment Claims Act 2016**: established the ECT and the mandatory TADM mediation step.
- **Industrial Relations Act**: governs collective bargaining via registered trade unions; less salient for individual termination than the Employment Act.

### Notice period rules (§10 Employment Act)

Statutory minimum notice applies where the employment contract is silent or specifies a shorter period. The longer of contract or statutory minimum prevails. Either party may pay salary in lieu (§11).

| Tenure | Statutory minimum notice (§10) |
|---|---|
| Less than 26 weeks | 1 day |
| 26 weeks to <2 years | 1 week |
| 2 to <5 years | 2 weeks |
| 5+ years | 4 weeks |

- The statutory schedule is symmetrical: the same minima apply whether the termination is employer-initiated or employee-initiated.
- Employment contracts almost universally extend notice beyond the statutory minimum, particularly for professional and managerial roles (typically 1 to 3 months).
- **Salary in lieu of notice** is calculated under §11 at the employee's "gross rate of pay" excluding overtime, bonuses, and reimbursements.
- **No notice** is required where the dismissal is for misconduct after due inquiry (§14(1)); the employer must conduct an inquiry before summary dismissal.

### Termination and severance

#### Routine termination (with notice or salary in lieu)

- Employee is entitled to salary through last day worked, salary in lieu of any unworked notice, and accrued but unused annual leave (§43 Employment Act).
- **No statutory severance** is owed on ordinary termination outside the retrenchment context.
- Final salary must be paid on the last day of employment where practicable, and in any event within 3 working days (§22 Employment Act).

#### Retrenchment (redundancy)

Retrenchment is treated as a distinct category. There is **no statutory severance entitlement**, but a strong tripartite norm based on the MOM Tripartite Advisory:

- **Customary retrenchment benefit: 2 weeks to 1 month of salary per year of service** for employees with **at least 2 years** of service.
- Employees with under 2 years of service typically receive an **ex-gratia goodwill payment** rather than a benefit calibrated by tenure.
- Where a collective agreement applies, its retrenchment benefit clause controls (typically more generous).
- The actual amount varies by industry, employer financial condition, and union agreement. Profitable employers in good standing are expected to pay at the upper end of the band.

#### Mandatory Retrenchment Notification (MRN)

Under MOM rules effective since 1 November 2021, employers with **10 or more employees** must notify MOM via the **Mandatory Retrenchment Notification (MRN)** of any retrenchment exercise involving **5 or more employees within any 6-month period**. The notification is filed online via the MyMOM Portal within **5 working days** of notifying the affected employees. The MRN data feeds into MOM's employment-support programmes (e.g., Workforce Singapore career-matching support).

#### Foreign workers

Foreign employees on **Employment Pass (EP), S Pass, or Work Permit** require additional steps:

- The employer must **cancel the work pass within 7 days** of the last day of employment via the MOM EP Online or Work Permit Online portal.
- The employer is responsible for **repatriation costs** to the worker's home country if no alternative employment is secured (§85 Employment of Foreign Manpower Act for Work Permit holders; similar contractual obligation typically embedded in EP / S Pass terms).
- The foreign worker is given a short grace period (typically 30 days for EP holders) to find new employment and have a new pass approved, failing which they must leave Singapore.

### Wrongful dismissal and the dispute pathway

Under the **Tripartite Guidelines on Wrongful Dismissal**, dismissal is wrongful where:

- The employer dismisses without notice or salary in lieu absent misconduct that warrants summary dismissal.
- The dismissal is aimed at depriving the employee of statutory entitlements due to vest imminently (e.g., dismissal just before a maternity-protected period).
- The dismissal is on discriminatory grounds (age, race, gender, religion, nationality, family status, disability, mental health). With the **Workplace Fairness Act** coming into phased force, these grounds gain explicit statutory protection beyond the existing tripartite norm.
- The dismissal is in retaliation for the employee exercising statutory rights (filing a salary claim, reporting workplace safety violations).

The dispute pathway:

1. **TADM mediation** (mandatory): the claimant lodges the dispute online; TADM convenes a mediator. Most disputes settle here.
2. **Employment Claims Tribunal (ECT)**: where mediation fails, the dispute proceeds to the ECT. ECT jurisdiction covers salary-related claims (up to SGD 20,000, or SGD 30,000 with union representation) and wrongful-dismissal claims.
3. Statute of limitations: the dismissal claim must be lodged at TADM within **1 month** of the last day of employment (Employment Claims Act).

### Edge cases

- **Probation**: not statutorily defined. Contractual probation periods are common (typically 3 to 6 months). Notice during probation often shortened by contract to 1 day or 1 week; the longer of contract or statutory minimum (§10) still applies.
- **Pregnant employees**: under §84 Employment Act, an employee who has completed 3 months of service and notifies the employer of pregnancy is entitled to maternity protection. Dismissal without sufficient cause during pregnancy entitles her to maternity benefits as if not dismissed.
- **Medical leave**: §86 prohibits dismissal during certified hospitalisation leave or while the employee is on certified sick leave.
- **Domestic workers (foreign domestic helpers)**: governed by the Employment of Foreign Manpower Act and a separate set of MOM rules, not the Employment Act.
- **Managerial and executive employees**: covered by the Employment Act since the 2019 amendments removed the prior salary cap that excluded most professionals, managers, and executives (PMEs) from Part IV protections. Notice provisions in §10 apply universally.
- **Collective bargaining**: where a registered trade union has a collective agreement covering the employee, the CA terms (including any enhanced retrenchment benefit) apply.

### Worked example

Scenario: Singapore-based professional, **3 years 6 months tenure**, monthly gross salary SGD 8,000, retrenched due to organisational restructuring. Employer has 60 employees. Contract specifies 1 month notice.

1. **Notice**: contract (1 month) vs statutory (§10, 2 to <5 years tenure = 2 weeks). Contract applies as it is the longer period → **1 month notice**, paid as salary in lieu = **SGD 8,000**.
2. **Retrenchment benefit**: tripartite norm of 2 weeks to 1 month per year of service, 3.5 years tenure.
   - Lower bound (2 weeks/year): 3.5 × (SGD 8,000 / 2) ≈ **SGD 14,000**.
   - Upper bound (1 month/year): 3.5 × SGD 8,000 = **SGD 28,000**.
   - Assume mid-band practice for a profitable employer: approximately **SGD 21,000**.
3. **Accrued but unused annual leave**: assume 8 days untaken at SGD 8,000 / 21 working days ≈ SGD 381/day → **SGD 3,048**.
4. **Final salary**: through last day worked, paid within 3 working days of termination.
5. **MRN notification**: if this retrenchment is part of an exercise involving 5+ employees within 6 months and the employer has 10+ employees, the employer files the Mandatory Retrenchment Notification within 5 working days.
6. **Total exit cost (excluding routine salary)**: approximately **SGD 32,000** at the mid-band retrenchment benefit, plus statutory contributions and any CPF obligations on salary components.

If instead this had been a summary dismissal without due inquiry, the employee would have had **1 month from the last day of employment** to lodge a wrongful-dismissal claim at TADM, with potential remedies including reinstatement (rare) or compensation in lieu (typical).

### Sources

- Singapore Statutes Online **Employment Act 1968 (Chapter 91)**: <https://sso.agc.gov.sg/Act/EmA1968>
- Singapore Statutes Online **Employment Claims Act 2016**: <https://sso.agc.gov.sg/Act/ECA2016>
- Singapore Statutes Online **Employment of Foreign Manpower Act 1990**: <https://sso.agc.gov.sg/Act/EFMA1990>
- Singapore Statutes Online **Workplace Fairness Act 2025**: <https://sso.agc.gov.sg/Acts-Supp/3-2025/>
- MOM **Tripartite Advisory on Managing Excess Manpower and Responsible Retrenchment**: <https://www.mom.gov.sg/employment-practices/retrenchment>
- MOM **Mandatory Retrenchment Notifications**: <https://www.mom.gov.sg/employment-practices/retrenchment/mandatory-retrenchment-notifications>
- MOM **Tripartite Guidelines on Wrongful Dismissal**: <https://www.mom.gov.sg/employment-practices/termination-of-employment/wrongful-dismissal>
- MOM **Tripartite Guidelines on Fair Employment Practices (TGFEP)**: <https://www.tal.sg/tafep/Resources/Tripartite-Guidelines>
- Tripartite Alliance for Dispute Management **TADM**: <https://www.tal.sg/tadm>
- State Courts of Singapore **Employment Claims Tribunal**: <https://www.judiciary.gov.sg/employment-claims>
- Baker McKenzie *Global Employer Guide: Singapore*: <https://www.bakermckenzie.com/en/insight/publications/guides/global-employer-guide>
- DLA Piper *Guide to Going Global Employment: Singapore*: <https://www.dlapiperintelligence.com/goingglobal/employment/>

---

## South Africa (ZA)

### Employment relationship overview

South African employment law is built on a constitutional foundation (the right to fair labour practices, §23 of the Constitution) operationalised through two principal statutes: the **Basic Conditions of Employment Act (BCEA)** sets minimum substantive terms (notice, leave, severance), and the **Labour Relations Act (LRA)** governs dismissal fairness, collective bargaining, and the dispute-resolution architecture centred on the **Commission for Conciliation, Mediation and Arbitration (CCMA)**. Every dismissal must pass a dual test: **fair reason** AND **fair procedure**. Failing either renders the dismissal unfair, with reinstatement as the default remedy.

#### Legal framework

- **Constitution of the Republic of South Africa, 1996, §23**: right to fair labour practices.
- **Labour Relations Act 66 of 1995 (LRA)**: the master statute on dismissal. **§185** (right not to be unfairly dismissed), **§188** (fair reason and fair procedure), **§189** (operational requirements / retrenchment), **§189A** (large-scale retrenchments), **§187** (automatically unfair dismissals), **§197** (transfer of business as going concern).
- **Basic Conditions of Employment Act 75 of 1997 (BCEA)**: **§37** (notice periods), **§41** (severance pay on retrenchment), **§40** (payments on termination).
- **Employment Equity Act 55 of 1998 (EEA)**: anti-discrimination and affirmative-action framework.
- **Code of Good Practice: Dismissal** (Schedule 8 to the LRA): the procedural standard for misconduct and incapacity dismissals.
- **CCMA Rules**: govern conciliation and arbitration procedure.

### Notice period rules (BCEA §37)

Statutory minimum notice, employer-initiated or employee-initiated:

| Tenure | Statutory minimum notice (BCEA §37) |
|---|---|
| Less than 6 months | 1 week |
| 6 months to 1 year | 2 weeks |
| More than 1 year | 4 weeks |

- The contract may extend the statutory minimum but cannot shorten it (BCEA §37(2) and §49).
- **Domestic workers and farm workers** previously had distinct schedules; the 2018 BCEA amendments and Sectoral Determinations have aligned most categories to the schedule above, with limited differences remaining for specific sectors.
- Notice must be given in writing, except where the employee is illiterate, in which case verbal notice is permitted (BCEA §37(4)).
- **Payment in lieu of notice** is permitted (BCEA §38): the employer can pay the employee's remuneration for the notice period in lieu of working it.
- **No notice** is owed for summary dismissal for serious misconduct, provided a fair procedure was followed under Schedule 8 of the LRA.

### Substantive fairness (LRA §188)

A dismissal is substantively fair only if the employer can show the reason is one of:

- **Misconduct** (e.g., theft, dishonesty, gross insubordination, fraud, assault). Schedule 8 sets out the disciplinary framework.
- **Incapacity** (poor performance or ill health). Distinct procedures: poor-performance dismissal requires prior counselling and a reasonable opportunity to improve; ill-health dismissal requires investigation into the extent of incapacity and consideration of alternatives.
- **Operational requirements** (economic, technological, structural, or similar needs of the employer). This is the LRA's retrenchment category under §189.

Dismissal for any other reason fails the substantive-fairness test.

### Procedural fairness

For misconduct and incapacity, the **Code of Good Practice: Dismissal** (Schedule 8) requires:

- Investigation of the alleged misconduct or poor performance.
- Written notification of the allegations and the disciplinary hearing.
- A hearing at which the employee can state a case, be assisted by a co-employee or shop steward, and call witnesses.
- A written outcome with reasons.
- A right of internal appeal (typical but not statutorily mandated).

Failure to follow procedural fairness renders the dismissal **procedurally unfair** even where the reason was sound; compensation may be ordered (typically up to 12 months' remuneration) without reinstatement.

### Retrenchment (LRA §189): operational-requirements dismissal

#### Small-scale retrenchment (§189)

Applies to all retrenchments not meeting the §189A threshold. The procedure is a **joint consensus-seeking consultation**:

1. **Written notice** (§189(3)): the employer issues a written notification to consult, including the reasons for the proposed retrenchment, the alternatives considered, the number and categories of employees likely to be affected, the proposed selection method, the proposed severance, the timing, and any assistance offered.
2. **Consultation** with the affected employees or their representatives (workplace forum, trade union, or elected employee representatives) on:
   - Alternatives to retrenchment.
   - Measures to minimise the number of dismissals.
   - Selection criteria.
   - Severance and other terminal benefits.
   - Assistance with finding alternative employment.
3. **Selection criteria** must be fair and objective; LIFO (last-in, first-out) is the default fair criterion in the absence of agreement, though skill-based criteria are accepted where genuinely required.
4. **Final notice** of retrenchment to affected employees.

#### Severance pay (BCEA §41)

```
minimum_severance = 1 * weeks_remuneration * completed_years_of_service
# "Remuneration" includes basic salary plus regular allowances.
# Applies to dismissals on operational requirements grounds.
# Refusal of a reasonable offer of alternative employment forfeits severance (§41(4)).
```

- **Minimum of 1 week's remuneration per completed year of service** (BCEA §41(2)).
- Many employers and collective agreements provide enhanced severance (typically 2 to 4 weeks per year for managerial roles).
- An employee who unreasonably refuses an offer of alternative employment forfeits the statutory severance (BCEA §41(4)).

#### Large-scale retrenchment (LRA §189A)

Triggered where the employer has **50+ employees** AND the retrenchment affects a threshold number based on workforce size:

| Employer headcount | Threshold for §189A application |
|---|---|
| 50 to 200 | 10 employees retrenched |
| 201 to 300 | 20 employees retrenched |
| 301 to 400 | 30 employees retrenched |
| 401 to 500 | 40 employees retrenched |
| 500+ | 50 employees retrenched |

Additionally, §189A applies where the cumulative retrenchments over a **12-month period** reach the threshold.

§189A consultation differs from §189 in three respects:

- **Minimum 60-day consultation period** before notices of dismissal may issue (§189A(7)).
- **CCMA facilitator** may be appointed (either at the employer's request or by request of consulting parties representing the majority of affected employees) to facilitate the consultation.
- Disputes may proceed via **strike action** (§189A(7)) or **adjudication at the Labour Court** (§189A(13)), rather than CCMA arbitration. The §189 standard CCMA pathway is unavailable.

### CCMA dispute-resolution pathway

For any dismissal claim, the LRA prescribes a structured pathway:

1. **Referral to the CCMA** within **30 days of the dismissal** (LRA §191(1)(b)(i)). Late referrals require a condonation application showing good cause.
2. **Conciliation** at the CCMA: a commissioner attempts to settle the dispute. Most disputes settle here.
3. If conciliation fails (a certificate of non-resolution is issued), the matter proceeds to either:
   - **CCMA arbitration** for misconduct and incapacity dismissal disputes (§191(5)(a)), with the award binding subject to limited review on Labour Court.
   - **Labour Court adjudication** for retrenchment, automatically unfair dismissal, and other complex categories (§191(5)(b)).
4. **Remedies** (LRA §193):
   - **Reinstatement** with back-pay (the default for unfair dismissal absent compelling reasons against).
   - **Re-employment** on different terms.
   - **Compensation**: up to **12 months' remuneration** for ordinary unfair dismissal; up to **24 months' remuneration** for automatically unfair dismissal (LRA §194).

### Automatically unfair dismissals (LRA §187)

Dismissal is automatically unfair (no need to show ordinary unfairness; remedies enhanced) where the reason is:

- Participation in protected industrial action.
- Refusing to do work normally done by employees on strike.
- Disclosure of information that the employee was lawfully entitled to disclose to a third party.
- Pregnancy, intended pregnancy, or any reason related to pregnancy.
- Discrimination on grounds of race, gender, sex, ethnic or social origin, sexual orientation, age, disability, religion, conscience, belief, political opinion, culture, language, marital status, or family responsibility.
- Transfer of business as a going concern (§197) where the dismissal is for a reason related to the transfer.
- Exercising any right conferred by the LRA.
- Trade union activity or membership.

Maximum compensation: **24 months' remuneration** (LRA §194(3)).

### Edge cases

- **Transfer of business as a going concern (§197)**: employees transfer automatically to the new employer on existing terms, with continuity of service preserved. Dismissals connected to the transfer are automatically unfair under §187(1)(g). The buyer inherits all collective agreements and any disciplinary or grievance matters in progress.
- **Probationary employees**: subject to a lower bar for dismissal during probation, but not exempt from fairness. The Code of Good Practice (Schedule 8 item 8) requires the employer to evaluate, give reasonable evaluation and instruction, allow time for improvement, and give a hearing before terminating on probation grounds.
- **Limited-duration contracts**: a series of fixed-term contracts may be deemed a permanent employment relationship (§198B), with non-renewal then constituting a dismissal.
- **Sectoral Determinations**: certain sectors (domestic work, farm work, contract cleaning, private security, hospitality, wholesale and retail) are governed by Sectoral Determinations under the BCEA that set sector-specific minima. Where the Sectoral Determination is more favourable than the BCEA, it applies.
- **Strike-related dismissal**: an employee dismissed for participating in a protected strike is automatically unfair (§187(1)(a)); participation in an unprotected strike may justify dismissal subject to fair procedure.
- **Operational-requirements selection criteria challenge**: even where the §189 consultation is properly followed, the chosen selection criteria can be substantively reviewed at the Labour Court for fairness.

### Worked example

Scenario: South African employee, **5 years 8 months tenure**, monthly remuneration ZAR 45,000 (weekly = ZAR 10,385 approximately, based on 4.33 weeks/month), retrenched as part of an operational-requirements process. Employer has 120 employees and is retrenching 12 employees in this exercise, so **§189A applies** (50+ employees, 10+ retrenched in the 50 to 200 band).

1. **Notice (BCEA §37)**: tenure >1 year → **4 weeks**, paid as salary or worked.
2. **Consultation period (§189A)**: minimum **60 days** before notice may be issued. CCMA facilitator either appointed or declined within the statutory window.
3. **Selection**: criteria agreed during consultation (e.g., LIFO within affected role categories), applied transparently.
4. **Severance (BCEA §41)**:
   - 5 completed years of service × 1 week's remuneration = 5 × ZAR 10,385 ≈ **ZAR 51,925**.
   - Many employers in this scenario voluntarily enhance to 2 weeks per year, yielding ≈ ZAR 103,850.
5. **Accrued but untaken annual leave**: assume 10 days at ZAR 45,000 / 21.67 working days ≈ ZAR 2,077/day → **ZAR 20,770**.
6. **Pro-rata 13th cheque or bonus**: per contract; assume none for this example.
7. **Notice (paid as worked)**: 4 weeks × ZAR 10,385 = **ZAR 41,540**.
8. **Total exit cost**: approximately **ZAR 114,000 at the statutory minimum**, scaling to **ZAR 166,000 at common enhanced practice** (2 weeks per year severance).

Now alternative scenario: the same employee is dismissed for alleged misconduct (theft), but the employer skips the disciplinary hearing entirely.

1. The employee refers the dispute to the **CCMA within 30 days** of the dismissal.
2. Conciliation fails. The matter proceeds to **CCMA arbitration**.
3. The commissioner finds the dismissal procedurally unfair (no hearing) regardless of whether the misconduct is proved. Remedy: typically compensation rather than reinstatement, often in the range of **3 to 6 months' remuneration** (ZAR 135,000 to ZAR 270,000) at the commissioner's discretion under LRA §194(1).
4. If the dismissal is also found substantively unfair (misconduct not proved on the balance of probabilities), reinstatement with back-pay becomes the default remedy.

### Sources

- South African Government **Constitution of the Republic of South Africa, 1996**: <https://www.gov.za/documents/constitution-republic-south-africa-1996>
- South African Government **Labour Relations Act 66 of 1995**: <https://www.gov.za/documents/labour-relations-act>
- South African Government **Basic Conditions of Employment Act 75 of 1997**: <https://www.gov.za/documents/basic-conditions-employment-act>
- South African Government **Employment Equity Act 55 of 1998**: <https://www.gov.za/documents/employment-equity-act>
- Department of Employment and Labour **Code of Good Practice: Dismissal (Schedule 8 LRA)**: <https://www.labour.gov.za/code-of-good-practice-dismissal>
- CCMA **Information Sheets and Rules**: <https://www.ccma.org.za/>
- CCMA **Guidelines on Misconduct Arbitration**: <https://www.ccma.org.za/resources/guidelines/>
- Labour Court of South Africa: <https://www.judiciary.org.za/index.php/labour-court>
- Baker McKenzie *Global Employer Guide: South Africa*: <https://www.bakermckenzie.com/en/insight/publications/guides/global-employer-guide>
- DLA Piper *Guide to Going Global Employment: South Africa*: <https://www.dlapiperintelligence.com/goingglobal/employment/>
- Cliffe Dekker Hofmeyr *Employment Law Alert*: <https://www.cliffedekkerhofmeyr.com/en/news/publications/employment.html>

---

## United States — Texas (US-TX)

### At-will doctrine

#### Legal framework

- Texas is an **at-will employment** state under common law. Codified parallels appear in the Texas Labor Code throughout.
- **Texas Labor Code Chapter 61** (Texas Payday Law): governs final-pay timing.
- **Texas Labor Code Chapter 21** (TCHRA, Texas Commission on Human Rights Act): state anti-discrimination protections, applies to employers with 15+ employees. Parallels Title VII.
- Federal overlay: Title VII of the Civil Rights Act of 1964, ADEA (Age Discrimination in Employment Act), ADA (Americans with Disabilities Act), FMLA, USERRA, federal WARN Act (29 USC §§2101 to 2109).
- **No state WARN supplement** in Texas, unlike CA and NY.

At-will means either party may terminate at any time, with or without cause, with or without notice, subject only to the narrow exceptions below.

#### At-will exceptions in Texas

- **Discrimination** under Title VII, ADEA, ADA, and TCHRA.
- **Retaliation** for filing a workers' comp claim (Texas Labor Code §451.001), participating in protected concerted activity under the NLRA, or filing OSHA / wage complaints. The Texas Whistleblower Act (Texas Government Code Chapter 554) covers public-sector employees only; private-sector whistleblower protection comes from federal statutes such as Sarbanes-Oxley and Dodd-Frank.
- **Public policy exception** is narrowly construed in Texas. The **Sabine Pilot doctrine** (*Sabine Pilot Service Inc. v. Hauck*, 687 S.W.2d 733 (Tex. 1985)) recognises only one common-law exception: discharge for refusing to perform an illegal act that would expose the employee to criminal liability.
- **Implied-contract exception**: Texas recognises this only narrowly; employee handbooks typically contain at-will disclaimers that defeat implied-contract claims.

#### Notice period rules

- **No statutory notice period** required from either party. Exception: federal WARN Act for qualifying mass layoffs (below).
- Notice may be required by individual employment contract or collective bargaining agreement (rare in Texas).

### Final pay obligations

#### Legal framework

- **Texas Labor Code §61.014** (Texas Payday Law): final-pay timing.
- Texas Workforce Commission (TWC) administers wage claims under Chapter 61.

#### Rules

- **Involuntary termination (discharge or layoff)**: wages due **no later than 6 calendar days** after the discharge date (Texas Labor Code §61.014(a)).
- **Voluntary resignation**: wages due on the **next regularly scheduled payday** (§61.014(b)).
- Wages include earned commissions and bonuses calculable at termination. Accrued vacation is payable **only if** the employer's written policy or contract treats vacation as a wage; Texas does **not** statutorily require accrued vacation to be paid out.
- Final pay can be made by direct deposit, mailed, or paid in person at the employer's option.

#### Severance

- **No statutory severance** at the state or federal level. Severance is purely contractual or via a severance plan governed by ERISA.

### Federal WARN Act (29 USC §§2101 to 2109)

Texas has no state WARN supplement, so federal WARN is the only mass-layoff notice obligation.

- Applies to employers with **100+ full-time employees** (or 100+ FT and PT combined working 4,000+ hours/week excluding overtime).
- Triggers: **60 days advance written notice** required for:
  - **Plant closing**: permanent or temporary shutdown of a single site of employment (or operating unit within a site) resulting in employment loss for 50+ FT employees in any 30-day period.
  - **Mass layoff**: reduction in force at a single site affecting either (a) 500+ FT employees, or (b) 50 to 499 FT employees if they constitute 33%+ of the active workforce at that site, in any 30-day period.
- Notice recipients: affected employees or their representatives, the state dislocated-worker unit, and the local government chief elected official.
- **Penalty**: back pay and benefits for each affected employee up to 60 days, plus civil penalty up to $500/day to the local government.
- Exceptions (faltering company, unforeseeable business circumstances, natural disaster) are narrowly construed.

### Edge cases

- **COBRA** (federal) for employers with 20+ employees; state mini-COBRA equivalent under **Texas Insurance Code §1251.252** for smaller employers (2 to 19 employees), providing up to 9 months of continuation coverage.
- **TWC unemployment**: employer must provide notice of the right to apply for unemployment benefits at termination.
- **Right-to-work state** under Texas Labor Code §101.052 et seq.: employees cannot be required to join or pay dues to a union as a condition of employment.

### Worked example

Scenario: Texas-based full-time employee at a 200-employee firm, 4 years tenure, salary $7,000/month (~$323/day), involuntarily terminated on a Monday. No state WARN supplement applies; this is a single dismissal (not a mass layoff), so federal WARN does not trigger.

1. **Final wages** due by the following Sunday: 6 calendar days after discharge (§61.014(a)).
2. Accrued vacation payout depends on the employer's written policy; if policy is silent or explicitly disclaims payout, none is owed.
3. Variation: if the same employer instead terminates **60+ employees at a single 200-employee site within a 30-day window**, federal WARN does trigger (60+ employees affected, ≥33% of workforce, ≥50 absolute threshold met). Required: 60-day advance written notice.
4. Failure to provide WARN notice: 60 days of back pay and benefits per affected employee, plus $500/day civil penalty to the local government.

### Sources

- Texas Statutes **Labor Code Chapter 61 (Payday Law)**: <https://statutes.capitol.texas.gov/Docs/LA/htm/LA.61.htm>
- Texas Statutes **Labor Code Chapter 21 (TCHRA)**: <https://statutes.capitol.texas.gov/Docs/LA/htm/LA.21.htm>
- Texas Workforce Commission **Texas Payday Law**: <https://www.twc.texas.gov/programs/wage-and-hour/texas-payday-law>
- US DOL **WARN Act**: <https://www.dol.gov/agencies/eta/layoffs/warn>
- *Sabine Pilot Service Inc. v. Hauck*, 687 S.W.2d 733 (Tex. 1985)
- Baker McKenzie *Global Employer Guide: United States*: <https://www.bakermckenzie.com/en/insight/publications/guides/global-employer-guide>
- DLA Piper *Guide to Going Global Employment: United States*: <https://www.dlapiperintelligence.com/goingglobal/employment/>

---

## United States — New York (US-NY)

### At-will doctrine

#### Legal framework

- **At-will employment** under New York common law.
- **NY Labor Law §191** (Frequency of payments): governs final-pay timing.
- **NY Labor Law §195** (notice and recordkeeping): notice-of-wage-rate and pay-statement requirements.
- **NY Labor Law §198** (penalties): liquidated damages for unpaid wages.
- **NY Labor Law §860 et seq.** (NY WARN Act): state mass-layoff notice requirement, broader than federal.
- **NY Executive Law §296** (NY State Human Rights Law, NYSHRL): state anti-discrimination protections. Coverage was expanded by the 2019 amendments and now applies to **all employers** for discrimination and harassment claims (not just those with 4+ employees).
- **NYC Human Rights Law** (NYC Admin Code §8-101 et seq.): for NYC employers, broader protections still.
- Federal overlay: Title VII, ADEA, ADA, FMLA, federal WARN Act.

At-will means either party may terminate at any time, with or without cause, with or without notice, subject to the exceptions below.

#### At-will exceptions in NY

- **Discrimination** under Title VII, ADEA, ADA, NYSHRL, and NYCHRL (where applicable). NYSHRL and NYCHRL have lower coverage thresholds and broader protections than federal law.
- **Retaliation** for whistleblowing (NY Labor Law §740, substantially expanded by the 2021 amendment to cover a broader range of activities), workers' comp claims (NY Workers' Compensation Law §120), filing OSHA complaints, or exercising rights under the NY Healthy Workplace framework.
- **Implied-contract exception** more readily recognised than in Texas: *Weiner v. McGraw-Hill, Inc.*, 57 N.Y.2d 458 (1982) established that employer statements (handbooks, offer letters) can create binding modifications to the at-will default.
- **Public policy exception** is narrower in NY than in CA; NY courts have largely declined to create a free-standing common-law wrongful-discharge tort, deferring instead to statutory schemes.

#### Notice period rules

- **No statutory notice period** for individual terminations. Exception: NY WARN for qualifying mass layoffs (below).
- Notice may be required by individual employment contract or collective bargaining agreement.

### Final pay obligations

New York does **not** require immediate same-day final pay (unlike CA), but the timing rule is uniform across involuntary and voluntary departures and the penalty regime under §198 is significant.

#### Legal framework

- **NY Labor Law §191** (frequency of payments).
- **NY Labor Law §192** (direct deposit authorisation).
- **NY Labor Law §198(1-a)** (liquidated damages).
- **NY Labor Law §198-c** (benefits and wage supplements).

#### Rules

- **Final wages due by the next regularly scheduled payday** following termination, for both involuntary discharge and voluntary resignation (§191).
- Wages include earned wages, commissions, and bonuses calculable at termination.
- **Accrued vacation**: under NY DOL guidance and §198-c, accrued vacation is treated as wages where the employer's policy or contract creates a vested benefit. An employer policy explicitly stating "use it or lose it" or non-vesting can be enforceable if clearly communicated in writing to employees in advance.
- **Direct deposit** of final pay requires written employee authorisation (§192).
- **Penalty for late payment**: §198(1-a) allows liquidated damages of **100% of unpaid wages** plus interest and attorney's fees, in addition to the unpaid wages themselves, unless the employer proves a good-faith basis for believing the underpayment complied with law.

#### Severance

- **No statutory severance** at the state or federal level. Severance is contractual or via an ERISA-governed severance plan.

### NY WARN Act (NY Labor Law §860 et seq.)

NY WARN is **broader than federal WARN** on every key dimension: lower employer threshold, lower employee triggers, longer notice period, and additional covered events.

- Applies to employers with **50 or more employees** (excluding part-time workers) in New York State. Federal WARN threshold is 100+.
- Triggers: **90 days advance written notice** required (vs federal 60), for:
  - **Plant closing**: permanent or temporary shutdown of a single site of employment, or one or more facilities or operating units within a single site, resulting in employment loss for 25+ employees in any 30-day period.
  - **Mass layoff**: reduction in force affecting either (a) 250+ employees at a single site, or (b) 25+ employees if they constitute 33%+ of the workforce at that site, in any 30-day period.
  - **Relocation**: moving operations 50+ miles away resulting in employment loss for 25+ employees.
  - **Covered reduction in work hours**: 50%+ reduction in work hours for 6+ consecutive months affecting 25+ employees.
- Notice recipients: affected employees, NY Department of Labor, local Workforce Investment Board, and the chief elected official of the municipality where the site is located.
- **Penalty**: back pay and benefits for each affected employee up to 60 days, plus civil penalty of up to $500/day for each day of violation, plus reasonable attorney's fees recoverable by the State or by the employees in a private action.
- Exceptions (faltering company for plant closings only, unforeseeable business circumstances, natural disaster) are narrowly construed.

### Edge cases

- **COBRA** federal continuation for 18 months (employers with 20+ employees).
- **NY State Continuation** ("mini-COBRA") for smaller employers, extending the total continuation period up to 36 months when combined with federal COBRA.
- **NY Paid Family Leave** (NY Workers' Compensation Law §§200 to 211): job-protected leave for bonding with a new child, caring for a family member with a serious health condition, or military exigency. Benefit rate (percentage of average weekly wage and weekly cap) is adjusted annually; verify against current NY State PFL government source rather than relying on a stale figure.
- **NY Paid Sick Leave** (NY Labor Law §196-b): all NY employers must provide paid or unpaid sick leave depending on employer size.
- **NYC and Westchester** local sick-leave and predictive-scheduling ordinances may impose additional requirements on top of state law.

### Worked example

Scenario A (individual termination): NY-based full-time employee at an 80-employee firm, 5 years tenure, weekly salary $2,000. Involuntarily terminated on a Friday; next regular payday is the following Friday.

1. **Final wages** due on the following Friday (§191). No same-day rule.
2. Accrued vacation payable as wages unless a clearly communicated "use it or lose it" policy applies.
3. Late payment exposes the employer to liquidated damages of 100% of the unpaid amount under §198(1-a), plus interest and attorney's fees.

Scenario B (mass layoff at the same 80-employee firm): employer proposes to lay off 30 employees in a 30-day window. That is 37.5% of the workforce and 25+ absolute, so **NY WARN triggers** (50+ employee threshold met, plus event threshold met).

1. Required: **90 days advance written notice** to affected employees, NY DOL, local Workforce Investment Board, and the chief elected official.
2. Federal WARN does **not** trigger at this firm size (under the 100-employee threshold).
3. Failure to provide NY WARN notice: 60 days of back pay and benefits per affected employee (× 30 employees = significant exposure), plus $500/day civil penalty, plus attorney's fees.

### Sources

- NY Senate **Labor Law §191**: <https://www.nysenate.gov/legislation/laws/LAB/191>
- NY Senate **Labor Law §195**: <https://www.nysenate.gov/legislation/laws/LAB/195>
- NY Senate **Labor Law §198**: <https://www.nysenate.gov/legislation/laws/LAB/198>
- NY Senate **Labor Law §740 (Whistleblower)**: <https://www.nysenate.gov/legislation/laws/LAB/740>
- NY Senate **Labor Law §860 et seq. (NY WARN)**: <https://www.nysenate.gov/legislation/laws/LAB/A25-A>
- NY State DOL **Worker Adjustment and Retraining Notification (WARN)**: <https://dol.ny.gov/worker-adjustment-and-retraining-notification-warn>
- NY State Division of Human Rights: <https://dhr.ny.gov/>
- NYC Commission on Human Rights: <https://www.nyc.gov/site/cchr/index.page>
- US DOL **Federal WARN Act**: <https://www.dol.gov/agencies/eta/layoffs/warn>
- *Weiner v. McGraw-Hill, Inc.*, 57 N.Y.2d 458 (1982)
- Baker McKenzie *Global Employer Guide: United States*: <https://www.bakermckenzie.com/en/insight/publications/guides/global-employer-guide>

---

## Engine integration notes

The rules engine in `mcp_servers/jurisdiction_server.py` should expose the following deterministic outputs derived from this document:

- `get_termination_rules(country, employment_type, tenure_months)` → structured dict containing `notice_period_days`, `severance_formula`, `severance_components[]`, `mandatory_steps[]`, `protections_triggered[]`, `citation[]`.
- `validate_action(action, country, context)` → `{ compliant: bool, reason: str, recommendation: str, citation: str }`.
- `get_notice_period(country, tenure_months)` → integer days (employer-initiated, post-probation, default employment type).

When the orchestrator receives a country not covered here (JP, IN, and any others), the engine must return a structured "jurisdiction not covered — recommend legal review" response. It must never fall back to LLM-generated rules.
