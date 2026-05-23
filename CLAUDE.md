# CLAUDE.md — HR Operations Agent

Project context for AI-assisted development. Read this at the start of every session.

---

## What This Is

A Python-based multi-agent system that handles HR workflow requests in natural language. An orchestrator agent classifies the request, routes it to specialized MCP servers, and produces either an autonomous resolution or a structured escalation brief.

Built as a public portfolio demo. Architecture must look production-grade — clean separation of concerns, deterministic compliance logic, full audit trail.

---

## Stack

- **Python 3.12** — `uv` for dependency management
- **Anthropic SDK** — Claude Sonnet 4 for orchestration and reasoning, Claude Haiku for classification
- **MCP Python SDK** (`mcp`) — three MCP servers as separate modules
- **Supabase** — employee records + audit log (Postgres)
- **Pinecone** — vector DB for policy RAG
- **OpenAI** `text-embedding-3-small` — embeddings (same model on index and query side)
- **FastAPI** — API layer, SSE streaming
- **Vanilla HTML/CSS/JS** — chat UI, no framework

---

## Repository Structure

```
hr-ops-agent/
├── CLAUDE.md
├── agent/
│   ├── orchestrator.py        # Main agent loop — Sonnet + MCP client
│   ├── classifier.py          # Intent classification — Haiku, returns routing JSON
│   └── conflict_resolver.py  # Reconciles outputs when multiple agents fire
├── mcp_servers/
│   ├── hris_server.py         # Mock Workday — employee records, payroll calendar
│   ├── jurisdiction_server.py # Labor law rules engine
│   └── policy_server.py       # RAG-backed policy search
├── api/
│   └── index.py               # FastAPI — /api/chat, /api/chat/stream, /api/ping
├── scripts/
│   ├── seed_data.py            # Seed 10 mock employees into Supabase
│   ├── seed_policies.py        # Chunk + embed policy corpus into Pinecone
│   └── test_jurisdiction.py   # CLI to test jurisdiction rules in isolation
├── public/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── db/
│   └── schema.sql
├── docs/
│   ├── jurisdiction.md        # Full rules documentation per country
│   └── adr/                   # Architecture Decision Records
├── tests/
│   ├── test_classifier.py
│   ├── test_jurisdiction.py
│   └── test_orchestrator.py
├── pyproject.toml
├── uv.lock
└── .env.example
```

---

## Architecture

### Request Flow

```
User input (natural language)
        │
        ▼
classifier.py  — Haiku, fast + cheap
Returns: { agents_required, conflict_possible, requires_system_action, entities }
        │
        ▼
orchestrator.py — Sonnet, connects to MCP servers on startup
Invokes only the servers listed in agents_required
Hard cap: 10 tool calls per request
        │
   ┌────┴──────────────────────┐
   ▼                           ▼
Single agent path        Multi-agent path
Direct response          → conflict_resolver.py
                         → auto-execute or escalation brief
        │
        ▼
Audit log written to Supabase (every session, every tool call)
Response streamed via SSE
```

### Classifier Output Schema

```json
{
  "agents_required": ["jurisdiction"],
  "conflict_possible": false,
  "requires_system_action": false,
  "complexity": "simple",
  "entities": {
    "employee_name": null,
    "country": "DE",
    "action_type": "termination_query"
  }
}
```

### Conflict Resolver Output Schema

```json
{
  "resolution": "auto | escalate",
  "action": "...",
  "escalation_brief": {
    "conflict": "...",
    "risk_level": "low | medium | high",
    "recommendation": "...",
    "question_for_hr": "..."
  }
}
```

---

## MCP Servers

### `hris_server.py` — Mock Workday

Tools:
- `get_employee(employee_id: str)` — full employee record
- `search_employees(name: str)` — fuzzy name match, used when user provides a name not an ID
- `get_payroll_calendar(country: str)` — next payroll dates per country (hardcoded)
- `update_employment_status(employee_id, status, effective_date)` — mock write, always logs to audit_log, returns confirmation

Write tools (`update_employment_status`) only fire after conflict resolution. Never fire directly from classifier output.

### `jurisdiction_server.py` — Rules Engine

Countries covered: BR, DE, UK, US-CA, US-TX, ES

Tools:
- `get_termination_rules(country, employment_type, tenure_months)` — notice period, severance, legal requirements
- `validate_action(action, country, context)` → `{ compliant: bool, reason: str, recommendation: str }`
- `get_notice_period(country, tenure_months)` — minimum notice in days

**Critical:** All jurisdiction logic must be hardcoded structured data. Never rely on LLM knowledge for compliance rules — it must be deterministic and auditable. See `docs/jurisdiction.md` for the full rules.

Key rules implemented:
- **BR + CLT + >12mo** → aviso prévio proporcional, FGTS + 40% multa, 13º salary pro-rata
- **BR + PJ** → contractor, different rules from CLT — no FGTS, no aviso prévio
- **DE + >6mo** → Kündigungsschutzgesetz applies, minimum 4 weeks notice to month-end
- **DE probation (<6mo)** → 2 weeks notice, no Kündigungsschutz
- **US-CA** → at-will, final pay same day as termination, check WARN Act threshold
- **US-TX** → at-will, final pay next regular payday
- **UK** → statutory minimum 1 week per year of service (capped at 12)
- **ES** → 20 days per year of service (capped at 12 months salary) for objective dismissal

### `policy_server.py` — RAG Layer

Tools:
- `search_policies(query, country, scenario)` — vector search over policy corpus
- `get_policy(policy_id)` — retrieve by ID

Policy corpus lives as markdown files under `docs/policies/`. Chunked and embedded via `scripts/seed_policies.py`. Documents cover: offboarding process, job change approvals, comp band framework, contractor-to-FTE conversion, approval matrix.

---

## Supabase Schema

```sql
create table employees (
  id text primary key,
  name text not null,
  email text,
  country text not null,
  employment_type text not null,
  start_date date not null,
  role text,
  department text,
  compensation_usd integer,
  employment_status text default 'active',
  manager_id text
);

create table audit_log (
  id uuid default gen_random_uuid() primary key,
  created_at timestamptz default now(),
  session_id text,
  user_input text,
  agents_invoked text[],
  tool_calls jsonb,
  resolution text,
  escalated boolean default false,
  cost_usd numeric(10,6)
);
```

---

## Mock Employees

Seeded via `scripts/seed_data.py`. Chosen to cover jurisdiction edge cases:

| ID | Name | Country | Type | Start Date | Edge Case |
|---|---|---|---|---|---|
| emp_001 | João Silva | BR | CLT | 2021-03-01 | 3yr 10mo, full CLT entitlements |
| emp_002 | Maria Santos | BR | PJ | 2023-06-01 | Contractor, no CLT protections |
| emp_003 | Lucas Oliveira | BR | CLT | 2018-01-15 | 7+ years, maximum aviso prévio |
| emp_004 | Sarah Chen | DE | full-time | 2020-01-15 | 4+ years, full Kündigungsschutz |
| emp_005 | Ana Müller | DE | full-time | 2024-10-01 | Probation <6mo, different rules |
| emp_006 | James Kirk | UK | full-time | 2022-09-01 | 2yr 8mo statutory notice |
| emp_007 | Sophie Williams | UK | full-time | 2019-03-01 | 6+ years, redundancy pay eligibility |
| emp_008 | Emily Ross | US-CA | full-time | 2023-01-01 | CA same-day final pay |
| emp_009 | Raj Patel | US-TX | full-time | 2023-01-01 | Same hire date, different state rules |
| emp_010 | Marcus Johnson | US-NY | full-time | 2021-06-01 | NY WARN Act, final pay next payday |
| emp_011 | Carlos Ruiz | ES | full-time | 2019-05-01 | 5+ years, severance calculation |
| emp_012 | Isabella García | ES | part-time | 2022-11-01 | Part-time severance proration |
| emp_013 | Luca Rossi | IT | full-time | 2020-08-01 | TFR (trattamento fine rapporto) |
| emp_014 | Chiara Bianchi | IT | full-time | 2024-02-01 | Short tenure, TFR still applies |
| emp_015 | Pierre Dubois | FR | full-time | 2019-11-01 | Cadre notice + indemnité de licenciement |
| emp_016 | Camille Martin | FR | full-time | 2023-07-01 | Période d'essai edge case |
| emp_017 | Chen Wei | SG | full-time | 2021-09-01 | Singapore MOM rules |
| emp_018 | Aisha Nkosi | ZA | full-time | 2020-04-01 | South Africa LRA, CCMA process |
| emp_019 | Yuki Tanaka | JP | full-time | 2022-03-01 | Outside core coverage — graceful fallback |
| emp_020 | Priya Sharma | IN | contractor | 2024-01-01 | Outside core coverage — graceful fallback |

---

## Demo Scenarios

The system must handle all of these correctly. Use as a manual test suite during development:

1. `"What's the minimum notice period to terminate someone in Germany?"` → jurisdiction only, no HRIS lookup
2. `"Process termination for João, last day Jan 31."` → HRIS + jurisdiction (CLT, 3yr 10mo) + policy
3. `"Terminate Ana Müller with 2 weeks notice."` → jurisdiction confirms compliant (probation period)
4. `"Terminate Sarah Chen with 2 weeks notice."` → jurisdiction flags non-compliant (4+ years, minimum 4 weeks to month-end)
5. `"Convert Maria Santos from contractor to CLT."` → policy (approval matrix) + jurisdiction (CLT obligations) + HRIS
6. `"What severance is Carlos entitled to?"` → HRIS (tenure) + jurisdiction (ES formula)
7. `"What are our offboarding steps?"` → policy only, no HRIS, no jurisdiction

---

## API

```
POST /api/chat
  body:    { message: str, session_id: str }
  returns: { response: str, agents_invoked: str[], escalated: bool, cost_usd: float }

POST /api/chat/stream
  SSE stream — same body, streams tokens + tool call events

GET /api/ping
  returns: { status: "ok" }
```

---

## UI

Single page, two sections:

**Top:** 4 example prompt buttons — pre-loaded from demo scenarios list above so visitors immediately know what to ask.

**Bottom:** Chat interface. Each response renders:
- Agent pills showing which servers were invoked (HRIS / Jurisdiction / Policy)
- Auto-resolved vs escalated indicator
- Escalation brief as a structured card when applicable
- Cost per request in footer

Aesthetic: clean, minimal — consistent with `growth-analytics-agent` portfolio project.

---

## Non-Negotiable Design Rules

1. **Jurisdiction rules are hardcoded, never LLM-generated.** Compliance logic must be deterministic. If a rule isn't in `jurisdiction_server.py`, the system says it doesn't have coverage for that country — it does not guess.

2. **Haiku for classification, Sonnet for reasoning.** Never use Sonnet for the classification step. Cost discipline is part of the architecture.

3. **MCP servers are separate modules.** The orchestrator connects to them at runtime. Tool logic never lives inline in the agent loop. This is the point of the architecture — swapping mock Workday for real Workday means changing a URL, not the orchestrator.

4. **Write operations always go through audit log.** `update_employment_status` and any future write tools must log to `audit_log` before returning. No exceptions.

5. **10 tool call hard cap per request.** Enforced in `orchestrator.py`. Prevents runaway loops and bounds worst-case cost.

6. **HRIS reads before writes.** Orchestrator always calls `get_employee` or `search_employees` before any write tool fires. Never write blind.

7. **Graceful fallback for uncovered countries.** JP and IN employees are in the dataset intentionally. The system must return a clear "jurisdiction not covered" message, not hallucinate rules.

---

## Environment Variables

```
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_DB_URL=
PINECONE_API_KEY=
PINECONE_INDEX=
```

---

## Local Setup

```bash
git clone ...
cd hr-ops-agent
uv sync

cp .env.example .env  # fill in keys

# One-time setup
uv run python scripts/seed_data.py
uv run python scripts/seed_policies.py

# Run
uv run uvicorn api.index:app --host 127.0.0.1 --port 8000

# Test jurisdiction rules in isolation
uv run python scripts/test_jurisdiction.py

# Tests
uv run pytest
```

---

## Build Tasks

Work through these in order. Do not start Task 2 until Task 1 passes all demo scenarios. Do not start Task 3 until Task 2 is complete.

### Task 1 — `mcp_servers/jurisdiction_server.py`

Research and implement termination rules for all covered countries before writing any code. Document sources and rules in `docs/jurisdiction.md` first, then implement as hardcoded structured data in the server.

Coverage required:

- **BR — CLT:** aviso prévio proporcional (30 days base + 3 days per year of service, capped at 60 additional days), FGTS + 40% multa, 13º salary pro-rata, férias proporcionais
- **BR — PJ:** contractor, no aviso prévio, no FGTS, no 13º salary — governed by contract terms only
- **DE:** Kündigungsschutzgesetz (applies after 6 months), notice periods by tenure (4 weeks to month-end base, scaling to 7 months at 20+ years), probation rules (<6 months = 2 weeks, no Kündigungsschutz)
- **UK:** statutory minimum 1 week per year of service (capped at 12), redundancy pay eligibility after 2 years (age-weighted formula)
- **US-CA:** at-will, final pay same day as termination, WARN Act threshold (100+ employees, 60 days notice for mass layoffs)
- **US-TX:** at-will, final pay next regular payday
- **US-NY:** at-will, final pay next regular payday, WARN Act applies (90 days notice, lower threshold than federal)
- **ES:** objective dismissal = 20 days per year of service capped at 12 months salary; disciplinary = 0 if upheld, 33 days/year if unfair (capped at 24 months); part-time prorated by hours worked
- **IT:** TFR (trattamento fine rapporto) — accrues at ~8.33% of annual gross per year, paid on any termination; notice period varies by CCNL category (use white-collar / impiegato as default)
- **FR:** notice period by category (non-cadre = 1 month, cadre = 3 months) and tenure; indemnité de licenciement after 8 months tenure (1/4 month salary per year for first 10 years); période d'essai rules (cadre = 4 months, renewable once)
- **SG:** Employment Act notice periods by tenure (1 day to 4 weeks), retrenchment benefit norms (2 weeks to 1 month per year of service, MOM guidelines)
- **ZA:** Labour Relations Act — notice periods by tenure (1 week <6mo, 2 weeks 6mo–1yr, 4 weeks 1yr+); fair process required (CCMA); retrenchment = Section 189 consultation
- **JP:** graceful fallback — return structured message: "Jurisdiction not covered. Japan labor law requires specialist advice. Key considerations: 30 days notice or pay in lieu, strong employee protections. Recommend legal review."
- **IN:** graceful fallback — return structured message: "Jurisdiction not covered. India labor law varies by state and establishment size. Recommend local legal review."

After implementing, verify against all 7 demo scenarios in this file. All must pass before proceeding.

---

### Task 2 — Policy Corpus

Write 5 HR policy documents as markdown files under `docs/policies/`. These will be chunked and embedded into Pinecone by `seed_policies.py`.

Write in realistic HR handbook language — not Lorem Ipsum, not bullet summaries. Flowing prose with clear section headers. 600–800 words each. Include country-specific callouts for BR, DE, and FR where the process differs from the global default due to legal requirements.

Documents:

1. **`offboarding-policy.md`** — timeline (notice through last day), IT asset return, system access revocation schedule, knowledge transfer expectations, final pay process, reference policy

2. **`job-change-approval-matrix.md`** — approval requirements by change type (promotion, lateral, compensation adjustment, location change, employment type conversion) and by level (IC, manager, director, VP+); escalation thresholds

3. **`contractor-to-fte-conversion.md`** — eligibility criteria, required approvals, timeline, what changes (benefits, equity, employment type), country-specific notes (BR: CLT obligations trigger on conversion; DE: probation period resets)

4. **`compensation-bands.md`** — level framework (L1–L7), band philosophy, approval requirements for offers and adjustments, out-of-band process, currency and geo-adjustment policy

5. **`performance-improvement-policy.md`** — PIP triggers, structure (30/60/90 day), documentation requirements, manager and HR responsibilities, outcomes, country-specific notes (FR: PIP has specific legal implications; DE: documentation requirements for Kündigungsschutz compliance)

---

### Task 3 — `mcp_servers/hris_server.py`

Implement the mock HRIS server using the employee table in Supabase. All 20 employees must be seeded via `scripts/seed_data.py` before this server is tested.

Tools:
- `get_employee(employee_id)` — full record
- `search_employees(name)` — case-insensitive partial match on name field
- `get_payroll_calendar(country)` — hardcoded next payroll dates per country
- `update_employment_status(employee_id, status, effective_date)` — writes to employees table AND audit_log before returning confirmation

Test against: emp_001 (name search "João"), emp_005 (probation edge case), emp_019 (graceful fallback country).

---

### Task 4 — `mcp_servers/policy_server.py`

RAG server over the policy corpus from Task 2. Chunk docs along H2 boundaries (same pattern as RAG chatbot project). Embed via OpenAI `text-embedding-3-small`. Upsert to Pinecone with metadata: `{ doc_id, section, country_scope }`.

Tools:
- `search_policies(query, country, scenario)` — embed query, top-5 cosine search, filter by country_scope if provided
- `get_policy(policy_id)` — retrieve chunk by stable ID

---

### Task 5 — Agent Layer

Build in this order:
1. `agent/classifier.py` — Haiku call, returns routing JSON schema above
2. `agent/conflict_resolver.py` — reconciliation logic, escalation brief schema
3. `agent/orchestrator.py` — MCP client, connects all three servers, enforces 10 tool call cap, writes audit_log on every request

Test all 7 demo scenarios end-to-end via CLI before touching the API layer.

---

### Task 6 — API + UI

1. `api/index.py` — FastAPI with `/api/chat` and `/api/chat/stream` SSE endpoint
2. `public/index.html` + `app.js` + `style.css` — chat UI with:
   - 4 pre-loaded example prompt buttons (from demo scenarios above)
   - Agent pills per response (HRIS / Jurisdiction / Policy)
   - Escalation brief rendered as a structured card when applicable
   - Cost per request in footer
   - Consistent aesthetic with growth-analytics-agent portfolio project
