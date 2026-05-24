# Offboarding Policy

## Scope and intent

This policy governs the offboarding of all employees and contractors leaving the company, whether the separation is voluntary (resignation, retirement, end of fixed-term contract) or involuntary (performance-based termination, role elimination, mutual agreement). It applies globally, with country-specific addenda where local statute requires a different process. The People team owns end-to-end coordination; the departing employee's manager owns knowledge transfer and the closeout conversation; IT, Finance, and Security own their respective execution lanes.

The intent is twofold. First, every separation must protect the company against legal, security, and operational risk — final pay must land on time, system access must close on schedule, and customer-facing relationships must be transitioned without disruption. Second, every separation must protect the dignity of the departing employee. Tone matters. People who leave well become alumni referrals, future boomerangs, and credible character witnesses. People who leave badly become Glassdoor reviews and, occasionally, plaintiffs.

## Notice period and timeline

The standard notice expectation for voluntary resignation is **two weeks** for individual contributors and managers, and **four weeks** for Director-level and above. For involuntary separations, notice follows the controlling jurisdiction's statutory minimum (see country-specific addenda below) or the employment contract, whichever is longer.

On receipt of a resignation, the manager has **two business days** to acknowledge in writing and notify their HR Business Partner. The HRBP opens an offboarding ticket which automatically triggers the IT, Security, Finance, and Payroll work-streams. A separation date is confirmed in writing within **five business days** of notice. Counter-offers, if any, must be approved by the skip-level manager and the CHRO before being extended; they are not the default response and are not appropriate in performance-driven exits.

For involuntary terminations, the notice conversation is held in person where reasonably possible (or by video for fully remote employees), in the presence of the manager and an HRBP. A written termination letter and separation packet are provided at the meeting or within 24 hours.

## IT asset return

All company-issued assets must be returned by the final day of employment. The standard inventory includes the primary laptop, any secondary devices (monitor, tablet, mobile phone if company-issued), peripherals, security keys (YubiKey, FIDO2), and any access cards or building fobs.

For remote employees, IT ships a pre-paid return mailer **ten business days** before the last day. Receipt is confirmed at IT's receiving facility; the offboarding ticket cannot be closed until inventory reconciliation is complete. Unreturned assets are reported to Finance for payroll deduction where local law permits; in jurisdictions where deduction from final wages is restricted (notably California, Germany, France, and Brazil), the matter is escalated to Legal for recovery via separate channels rather than withheld from final pay.

Personal data on company devices is the employee's responsibility to remove before return. The standard separation packet includes a 48-hour window before access revocation specifically to allow personal-file extraction.

## System access revocation schedule

Access revocation is tiered to balance operational continuity against security risk. The default schedule:

- **T-0 (last day, end of business):** SSO and all production systems disabled. Email auto-responder set with the manager's contact as the forwarding point. Calendar handed off.
- **T+1:** Email account converted to a no-login forwarding mailbox for 30 days, then archived to the manager.
- **T+7:** All shared-drive permissions revoked. Saved credentials in password managers expired.
- **T+30:** Email forwarding ends. Slack/Teams account deactivated. Code repository access removed (read-only for individual contributors with no commit history in the past 90 days; immediate full revocation for engineers with active commit access).
- **T+90:** Personnel record archived to long-term storage per local retention requirements.

For involuntary terminations and any separation where the company has elevated risk concerns, access revocation happens at the moment notice is given, in coordination with Security. This is the default for any role with access to customer data, payment systems, or source code at scale.

## Knowledge transfer expectations

Knowledge transfer is the departing employee's manager's responsibility, not the employee's. The manager owns identifying what must be transferred, to whom, and on what timeline. The departing employee is expected to participate in good faith during the notice period but is not asked to extend their tenure to complete transfer work.

Standard deliverables include: a written handoff document covering active projects and stakeholders; documented runbooks for any operationally critical systems owned by the employee; introductions to key external contacts; and a 30-minute recorded walk-through for any role-specific tooling not covered in existing internal documentation.

## Final pay process

Final pay is processed by Payroll within the timeline mandated by the controlling jurisdiction. The standard inclusions are: salary through the last day worked, accrued and unused vacation paid out as wages where local law requires (California, Germany), pro-rated 13th-month or equivalent statutory payments where applicable (Brazil, Italy, France), and any earned but unpaid commissions or bonuses that are calculable at the separation date.

Equity treatment follows the equity plan: the last day of employment is the cessation-of-service date, after which unvested equity is forfeited and the post-termination exercise window begins for vested options. Departing employees receive a written equity summary as part of the separation packet.

## References policy

The company provides employment verification (dates of employment, position held, and — with the employee's written consent — final compensation) through a designated verifier. Managers may provide personal references in their individual capacity but are asked not to do so on company letterhead or through company channels. This policy protects both the company and the manager from defamation exposure.

## Country-specific addenda

### Brazil (BR) — CLT verbas rescisórias workflow

For CLT employees terminated without cause, Payroll calculates and pays the full verbas rescisórias package within **10 calendar days** of the termination date: saldo de salário, aviso prévio (worked or indenizado), 13º proporcional, férias vencidas and proporcionais with the constitutional 1/3 premium, and the 40% FGTS multa rescisória on the total accumulated FGTS balance. The company issues the chave de conectividade so the employee can withdraw FGTS, and provides the guia de seguro-desemprego. The termination paperwork (TRCT) is countersigned by the employee. Employees under any stability category — pregnancy, CIPA membership, accident leave, union directorship — cannot be terminated without cause and any such request is blocked by the system pending Legal review. PJ contractors are out of scope for this workflow; the contract governs.

### Germany (DE) — Arbeitszeugnis obligation

Every separating employee is entitled to a written employment certificate (Arbeitszeugnis) under GewO §109, on request, regardless of whether the separation was voluntary or involuntary and regardless of tenure. A simple certificate (einfaches Zeugnis) confirms dates and role; a qualified certificate (qualifiziertes Zeugnis) additionally evaluates performance and conduct. The qualified version is the default expectation and uses the established Zeugnissprache — coded performance language where phrasing maps to a German school-grade equivalent. Drafting is done by the manager and reviewed by HR for tone and legal defensibility. The certificate must be truthful, benevolent in tone, and clearly worded; the employee can challenge it in Arbeitsgericht and an inaccurate or unfavorably-coded certificate is a recurring source of post-termination litigation. Where a works council (Betriebsrat) exists, BetrVG §102 consultation must be completed before any termination notice is issued.

### France (FR) — solde de tout compte

At separation the employer issues three documents within the legal timeframe: the **solde de tout compte** (final settlement statement itemizing all amounts paid at separation), the **certificat de travail** (certificate of employment), and the **attestation Pôle Emploi** (now France Travail) for unemployment-insurance claims. The solde de tout compte is signed by the employee with a six-month window to contest its content; signature alone does not constitute a release of claims, only an acknowledgment of receipt. The certificat de travail is required by law and is held at the employee's disposal — the employer cannot make it contingent on anything. For terminations after 8 months of tenure, the **indemnité de licenciement** is calculated per the Code du travail formula and paid as part of the final settlement. Where the company has a CSE (Comité Social et Économique), consultation obligations apply for certain termination categories; the HRBP confirms scope before notice is issued.
