# ADR-0001: Bounded deterministic jurisdiction coverage

**Status:** Accepted
**Date:** 2026-06-03
**Phase:** 8 (close-out)

## Context

The jurisdiction MCP server must produce verdicts that a human reviewer can defend. Two failure modes matter:

1. **Confident wrong rule.** The engine returns, say, California severance norms for a Japanese termination. The verdict lands in the audit log, an HRBP acts on it, and the company has legal exposure.
2. **Refuses everything.** The engine is so cautious that no real request gets answered.

Failure mode (1) is materially worse than (2). A wrong verdict gets acted on; an escalation just routes to a human, which is already the safe default in this system.

Two structural facts shape the decision:

1. The agent layer (Sonnet) has plausible-looking labor-law knowledge in its training data for every country. Without a hard wall, it will fluently invent rules. This was directly observed during Phase 1 development before the deterministic engine existed.
2. Labor law is jurisdiction-specific in ways that cannot be inferred from one country to another. Even within a single country, rules diverge sharply: US states (TX vs. NY vs. CA), Brazilian CLT vs. PJ, French cadre vs. non-cadre. There is no shared frame.

## Decision

The jurisdiction engine covers a fixed set of `(country, employment_type)` pairs with hardcoded structured rules sourced from primary statutes. Each rule is a frozen Pydantic model. Every uncovered country resolves to a structured `{covered: False, message, recommendation}` response via `UNCOVERED_COUNTRIES_MESSAGE`. The orchestrator's system prompt forbids the LLM from substituting its own knowledge for an uncovered case.

**Covered jurisdictions as of Phase 8 close (11 entries):**

- BR (CLT, PJ)
- DE (full-time, with probation split under §622 BGB)
- US-CA, US-TX, US-NY
- UK
- FR (cadre, non-cadre)
- ES
- IT (impiegato as default CCNL category)
- SG
- ZA

**Explicitly out of scope, with documented rationale in `docs/jurisdiction.md`:**

- **JP.** Labor Contracts Act Article 16's "objectively reasonable grounds" and "socially appropriate" standard, and the Supreme Court's seiri kaiko four-factor test (Toyo Sanso 1979 and successors), are interpretive judgments developed through case law. A deterministic engine cannot evaluate "socially appropriate". Stating only the LSA Article 20 statutory minimum (30 days notice or pay in lieu) would be technically correct but actively misleading on real outcomes.
- **IN.** Four overlapping sources of variability produce a branching matrix too wide for hardcoded rules: (a) State-by-State Shops and Establishments Acts for white-collar workers, (b) IDA §2(s) workman vs. non-workman classification, (c) §25K to §25N establishment-size thresholds for government-permission retrenchment (100+ workmen under the old regime, 300+ under the new Labor Codes, unevenly notified across States as of 2026), (d) partial notification status of the 2019 / 2020 Labor Codes themselves. "Current Indian labor law" is not one consistent body of rules in 2026.

## Alternatives considered

**Option A: Have the LLM answer for every country, with a "verify with counsel" disclaimer.**

Rejected. The disclaimer does not reduce the cost of a confident wrong answer in the audit log. HRBPs and reviewers read past disclaimers, especially when the body of the response is detailed and authoritative-sounding. The wrong answer would still propagate through the write-gating layer (the conflict resolver lacks deterministic ground truth to reject it, since the resolver is itself an LLM call). And the cost discipline of the architecture, Haiku for routing plus Sonnet for reasoning, would collapse: every request would need Sonnet because every request would be doing primary-source synthesis.

**Option B: Vector-search a policy corpus per jurisdiction and let the LLM read primary law on the fly.**

Rejected for this phase. Even if accurate retrieval over labor-law corpora were solvable, the LLM still performs the interpretation step, and interpretation is the part that fails for case-law jurisdictions like Japan. Retrieval helps when the law is a knowable text; it does not help when the legally binding standard is "what would a Japanese labor court rule given these facts". The structure of the problem is wrong for RAG when the standard is fundamentally evaluative.

**Option C: Cover every country we can, return a generic "consult counsel" for the rest.**

Rejected. A generic refusal teaches the operator nothing about *why* the engine declined. An HRBP who sees a JP refusal with "this engine cannot evaluate the LCA Article 16 abusive-dismissal doctrine; specialist counsel must apply the seiri kaiko four-factor test" understands two things: (a) this is not a missing feature, it is the engine respecting a real cliff in the problem space, and (b) what to brief counsel about. A generic "not supported" produces neither outcome.

## Consequences

**Positive:**

- Every covered verdict is reproducible from the rule data. No LLM stochasticity in compliance outputs.
- Audit-log entries are deterministic for the same input within the covered set. This is what makes the audit log credible as a compliance artifact rather than an LLM transcript.
- The refusal path is legible. The operator gets specific statutory framing for why the engine declined, not a hand-wave.
- Future contributors can extend coverage one `(country, employment_type)` pair at a time with no orchestrator changes. The Phase 8 batches (A: UK + FR + ES; B1: IT + SG + ZA; B2: US-TX + US-NY; C: JP + IN documentation) followed this exact pattern.
- The architectural story is defensible. "I deliberately drew the boundary here, here is the reasoning, here is what would change to extend it" reads as engineering discipline, not as a feature gap.

**Negative:**

- Adding a new jurisdiction requires real research and structured rule data, not a prompt change. Phase 8 batches A, B1, B2, and C each took roughly a working session per country, with most of that time spent in primary sources rather than coding.
- The boundary will look arbitrary to a reviewer who has not read `docs/jurisdiction.md`. Mitigated by the README pointing explicitly at the JP and IN sections and by the structured refusal response surfacing the rationale at runtime.
- The orchestrator must be disciplined enough to not paraphrase the not-covered response into LLM-invented rules. Enforced by (a) the system prompt instruction in `agent/orchestrator.py`, (b) the rules engine being the only source of country-specific facts in the audit log, and (c) the classifier system prompt enumerating exactly which countries the engine covers (updated in commit `e305afb`).
- This decision constrains future product moves. A "we now support every country" marketing claim would require either dropping the deterministic principle (regression) or doing the work to actually cover them (correct but expensive).

## Out of scope for this ADR

- HRIS write-gating policy and the conflict-resolver design (separate concern; future ADR if revisited).
- The classifier scope-gate that blocks non-HR prompts (security feature; separate concern).
- The choice of FastMCP and the in-process adapter for Vercel (Phase 2 / Phase 3 transport detail).
- Policy corpus jurisdiction coverage in the RAG layer (the policy server is global-default with country-specific callouts; not the same axis as the jurisdiction rules engine).

## References

- `mcp_servers/jurisdiction_rules.py`: rule data and `COVERED_COUNTRIES` frozenset.
- `mcp_servers/jurisdiction_server.py`: tool surface and not-covered response shape.
- `docs/jurisdiction.md`: full primary-source documentation per covered jurisdiction, plus the JP and IN graceful-fallback rationale sections.
- `agent/classifier.py` SYSTEM_PROMPT: enumerates the covered set so routing stays aligned with the engine.
- `scripts/test_jurisdiction.py`: 36 deterministic scenarios covering the rule data; runs in CI without LLM calls.
