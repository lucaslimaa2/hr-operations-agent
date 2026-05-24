# HR Operations Agent — Roadmap

Phase-by-phase build plan. Every phase has a clear goal, the tasks that make it
up, and a brief description of what ships at the end. Marked status reflects
current state.

**Status legend:**
- ✅ done — committed to `main`
- 🔨 in progress — partially landed; see in-progress task IDs
- ⏳ pending — not started

Cross-cutting threads (run alongside phases):
- Every phase ends in a clean commit with a descriptive message.
- README + architecture diagram are drafted as we go (polished in Phase 10).
- Architectural decisions worth defending get a short note in the relevant phase entry below.

---

## Phase 0 — Project setup ✅

**Goal:** Reproducible local dev environment + all external services wired and verified.

**Commit:** `c9c236a` (+ `b48ddae` env template extension)

**Tasks:**
- ✅ Init git repo + `.gitignore` + first commit
- ✅ `uv init` + `pyproject.toml` with deps (anthropic, mcp, openai, fastapi, supabase, pinecone, pydantic, httpx, python-dotenv; dev: pytest, pytest-asyncio, ruff)
- ✅ Folder structure scaffolded (`agent/`, `mcp_servers/`, `api/`, `scripts/`, `public/`, `db/`, `docs/`, `tests/`) with `__init__.py` docstrings
- ✅ `.env.example` (committed) + `.env` (gitignored) for Anthropic / OpenAI / Supabase URL+key+direct+pooler / Pinecone keys
- ✅ `db/schema.sql` — `employees` + `audit_log` tables with indexes on `session_id` and `created_at`; applied to Supabase
- ✅ Pinecone index `hr-policies` created (1536 dims, cosine, serverless, manual config — client-side embedding via OpenAI)
- ✅ `scripts/smoke_test.py` — pings Anthropic, OpenAI, Supabase, Pinecone in sequence; the diagnostic to run any time config feels off
- ⏳ Vercel link — **deferred to Phase 3** (no point linking an empty project)

**What's defensible after this phase:**
- "uv is the modern Python dep manager — deterministic via uv.lock"
- "Smoke test catches config issues in 5 seconds before they leak into the agent"
- "Schema is one file (`db/schema.sql`), checked into git; that's the source of truth"

---

## Phase 1 — Jurisdiction research ✅

**Goal:** Authoritative source-of-truth document for the rules engine. Pure research, no code.

**Commit:** `ce8177d`

**Tasks:**
- ✅ Research labor law for BR (CLT + PJ), DE (probation + post-probation), US-CA (at-will + WARN/Cal-WARN)
- ✅ Write `docs/jurisdiction.md` — 460 lines, every rule cited to primary statute (planalto.gov.br, gesetze-im-internet.de, leginfo.legislature.ca.gov), worked examples per jurisdiction, engine-integration notes mapping rules to tool signatures

**Coverage in scope for Phase 1:**
- BR CLT — aviso prévio proporcional, FGTS multa, 13º, férias, estabilidade
- BR PJ — contract-only + vínculo empregatício re-classification risk
- DE — BGB §622 tenure brackets, KSchG protection, Probezeit, Abfindung, Massenentlassung
- US-CA — Lab Code §201/§202/§203, federal WARN + Cal-WARN

**What's defensible after this phase:**
- "I researched the rules first, before writing code. The doc is the source of truth; the rules engine is the transcription."
- "Every numeric rule cites a primary source. A recruiter could ask 'where does the 90-day cap come from?' and I point at Lei 12.506/2011."

---

## Phase 2 — Jurisdiction MCP server ✅

**Goal:** Rules engine accessible to the agent via MCP tools. Deterministic, citable, isolated process.

**Commit:** `2f15900`

**Tasks:**
- ✅ `mcp_servers/jurisdiction_rules.py` — Pydantic models for `NoticeBracket`, `NoticeRule`, `SeveranceComponent`, `Protection`, `JurisdictionRule`. Hardcoded rule objects for BR CLT, BR PJ, DE, US-CA. Lookup helpers with employment-type alias normalization. `COVERED_COUNTRIES` registry + uncovered-message constant.
- ✅ `mcp_servers/jurisdiction_server.py` — FastMCP server exposing three tools:
    - `get_notice_period(country, tenure_months, employment_type)` — narrow lookup
    - `get_termination_rules(country, employment_type, tenure_months)` — full rule set
    - `validate_action(action, country, context)` — compliance check on a proposed action (handles `terminate_without_cause`, `terminate_with_cause`, `mass_layoff`, `terminate_protected_employee`)
- ✅ `scripts/test_jurisdiction.py` — 12 isolated scenarios covering CLAUDE.md demos #1–5; Sarah-vs-Ana probation contrast; Cal-WARN trigger where federal WARN fails 33% threshold; JP/IN graceful fallback. All 12 pass.

**What's defensible after this phase:**
- "Data and logic are split — `jurisdiction_rules.py` is the encyclopedia, `jurisdiction_server.py` is the librarian. Adding a country in Phase 8 touches only the encyclopedia."
- "Tool docstrings are written for the LLM — they describe *when* to call each tool, not what the code does."
- "The engine never falls back to LLM guesses. Uncovered countries return a structured 'not covered' message."

---

## Phase 3 — Agent loop + API + UI 🔨

**Goal:** End-to-end agent live in a browser. Classifier routes → orchestrator reasons → tool calls hit MCP servers → response streams to the UI. Everything audit-logged.

**Commits:** `e082c2e` (3a), `7534173` (3b), `3661f41` (3c). UI not yet committed.

**Tasks:**
- ✅ **3a — `agent/classifier.py`** (Haiku, JSON routing via forced tool call)
    - Pydantic `ClassifierResult` schema auto-serialized to Anthropic tool `input_schema`
    - `tool_choice={"type":"tool","name":"route_request"}` forces structured output — no string-parsing
    - Returns `ClassificationResponse` with input/output tokens + cost for the audit log
    - `scripts/test_classifier.py` — runs all 7 CLAUDE.md demo scenarios; routing decisions all correct; ~$0.003/call

- ✅ **3b — `agent/orchestrator.py`** (Sonnet + MCP client + audit log)
    - Async tool-call loop, hard cap **10 tool calls per request** (circuit breaker against runaway loops)
    - `MCP_SERVERS` registry — Phase 4 adds `hris`, Phase 5 adds `policy`; orchestrator code does not change
    - Per-request MCP subprocess spawn (acceptable cold-start cost, matches Vercel lifecycle)
    - Cost tracked across classifier + every Sonnet turn, summed into one per-request total
    - `agent/audit.py` — writes one row to Supabase `audit_log` per request; observability failures degrade gracefully (warn to stderr, do not block user response)

- ✅ **3c — `api/index.py`** (FastAPI surface)
    - `GET /api/ping` — health check
    - `POST /api/chat` — non-streaming JSON (for scripts/curl)
    - `POST /api/chat/stream` — SSE: emits `classifier` → `tool_use` → `tool_result` → `text_delta` → `done` events
    - Static `public/` mount at root for local dev (one port serves both API + UI)
    - Refactor of orchestrator: `run_stream()` is the primary async generator; `run()` becomes a thin consumer of the stream (single source of truth, no divergence risk)

- ✅ 🔨 **3d — Chat UI** (`public/index.html` + `style.css` + `app.js`)
    - Matches `growth-ai-agent` portfolio aesthetic (Inter + Playfair Display, white bg, dark bubbles, rounded chat card)
    - 4 suggestion chips pre-loaded with demo prompts
    - Streams events live: agent pills, tool pills with running/done/error state + duration, ChatGPT-style cursor while text streams in, per-message cost footer
    - Pending: commit + final styling polish (Phase 7 also iterates on this)

- ✅ ⏳ **3e — `vercel.json` + first deploy**
    - `vercel.json` routes `/api/*` → Python serverless function, everything else → static `public/`
    - `vercel link` + `vercel --prod`
    - Set env vars in Vercel dashboard (mirror `.env`)
    - Verify live URL end-to-end
    - **Cold-start caveat:** Vercel Python functions take ~2s on first hit; subsequent requests stay warm. Fine for a demo. In production, switch to Railway / Fly.io / Render for long-running server with no cold starts.

**What's defensible after this phase:**
- "Haiku classifies, Sonnet reasons — cost discipline is architectural, not optional"
- "Tool-call loop is capped at 10 — circuit breaker against runaway loops, bounds worst-case cost and latency"
- "Audit log captures every request: session, input, agents invoked, tool calls log, cost, resolution"
- "Streaming over SSE — chat is one-way, SSE is the right primitive vs WebSocket overkill"
- "`run_stream()` is the single source of truth; `run()` consumes it. No divergence between streaming and non-streaming paths"

---

## Phase 4 — HRIS server + seeded employees ✅

**Goal:** Agent can resolve employees by name or ID and query their records. First proof that adding a server to the orchestrator is a one-line registry change.

**Tasks:**
- ✅ `scripts/seed_data.py` — seeded 20 mock employees from CLAUDE.md. Ana Müller's start_date adjusted to ~3 months ago (so demo scenario #3 still demonstrates probation; date-freshness caveat documented in the script header).
- ✅ `mcp_servers/hris_server.py` — FastMCP server with four tools:
    - `get_employee(employee_id)` — full record, includes computed `tenure_months`
    - `search_employees(name)` — case-insensitive partial match via PostgREST `ilike`
    - `get_payroll_calendar(country)` — hardcoded next payroll cadence for 13 countries
    - `update_employment_status(employee_id, status, effective_date)` — **WRITE tool**. Writes to `employees` AND `audit_log` BEFORE returning. Two audit rows per write (tool-level + orchestrator-level) for defense-in-depth.
- ✅ Added `"hris"` to `MCP_SERVERS` registry in `orchestrator.py` — **6 lines of config, no logic changes.** End-to-end verified:
    - "Terminate Sarah Chen with 2 weeks notice" → orchestrator looks up Sarah via HRIS (tenure 77mo), then validates via jurisdiction → non-compliant (BGB §622(2) Nr. 2 minimum 60 days)
    - "Terminate Ana Müller with 2 weeks notice" → HRIS lookup (tenure 3mo, probation), then jurisdiction → compliant (BGB §622(3))

**What's defensible after this phase:**
- "Audit log is enforced at the data layer — write tools log to audit_log before returning, no exceptions. Two audit rows per write: one tool-level (survives even if the orchestrator is bypassed) and one orchestrator-level (request context)."
- "Adding a new MCP server is a config change. Orchestrator code didn't change between Phase 3 and Phase 4 — just one new entry in the server registry."
- "HRIS reads happen before any write — the system prompt enforces it, and the demo scenarios prove it."

**What's defensible after this phase:**
- "Audit log is enforced at the data layer — write tools log before returning, no exceptions"
- "Adding a new MCP server is a config change. Orchestrator code did not change between Phase 3 and Phase 4."
- "HRIS reads happen before any write — orchestrator system prompt enforces it"

---

## Phase 5 — Policy RAG server ✅

**Goal:** Agent can answer policy/process questions ("what's our offboarding process?"). Vector search over a real policy corpus.

**Tasks:**
- ✅ Drafted 5 policy markdown documents in `docs/policies/` (research agent wrote, ~800-1200 words each):
    - `offboarding-policy.md` — 10 chunks
    - `job-change-approval-matrix.md` — 6 chunks (incl. L1–L7 approval table)
    - `contractor-to-fte-conversion.md` — 8 chunks (incl. BR/DE/FR addenda)
    - `compensation-bands.md` — 8 chunks (incl. L1–L7 framework + EU Pay Transparency Directive)
    - `performance-improvement-policy.md` — 9 chunks (incl. FR licenciement procedure + DE Abmahnung)
    - All five docs reference real statutes (CLT Art. 3º, BGB §622, KSchG, GewO §109, indemnité de licenciement) aligned with `docs/jurisdiction.md`
- ✅ `scripts/seed_policies.py` — chunks docs at H2 boundaries, sub-splits at H3 boundaries for country addenda (so each country gets its own chunk + scope tag). Embeds via OpenAI `text-embedding-3-small`. Wipes-and-rebuilds the Pinecone index for idempotency. 41 vectors total in the `hr-policies` index.
- ✅ `mcp_servers/policy_server.py` — FastMCP server with:
    - `search_policies(query, country, scenario)` — embed query, top-5 cosine search, optional metadata filter (`country_scope IN [global, multi, country]`)
    - `get_policy(doc_id)` — read full markdown from disk; path-traversal-safe doc_id sanitization
- ✅ Added `"policy"` to `MCP_SERVERS` registry — one entry, no orchestrator code changes.
- ✅ Verified end-to-end:
    - Demo #7 "What are our offboarding steps?" → `[policy]` only → 2 tool calls, $0.044, comprehensive offboarding answer including country addenda
    - Demo #5 "Convert Maria Santos contractor to CLT" → all 3 servers fired → HRIS lookup, conversion policy retrieval, jurisdiction obligations, vínculo empregatício re-classification risk all integrated. 3 tool calls, $0.072.

**What's defensible after this phase:**
- "Chunking strategy is structure-aware. H2 boundaries preserve topical coherence; we sub-split at H3 when country-specific addenda appear so each country gets its own embedding + scope tag. Country filter actually filters — searching for FR policy returns FR + global chunks but excludes BR/DE addenda."
- "Embedding is client-side via OpenAI, not Pinecone integrated inference. Lets us swap the embedding model without migrating the vector store. Tomorrow it could be voyage-3 or text-embedding-3-large — same index."
- "Seed pipeline is wipe-and-rebuild. Idempotent runs, no orphan chunks when doc structure changes. Safe to re-run after any policy edit."
- "Three MCP servers, all production-shaped. Demo #5 (contractor conversion) exercises all three in one request — proves the orchestrator handles N-server fan-out cleanly."

**What's defensible after this phase:**
- "Embedding happens client-side via OpenAI — Pinecone is pure vector storage. Embedding model is swappable without touching the vector store."
- "Chunks have metadata for country scope — same query can filter to BR-specific policy overlays"
- "Vector RAG for policy ('what does this mean'); deterministic rules engine for jurisdiction ('what is the value'). Right tool for each access pattern."

---

## Phase 6 — Conflict resolver + auto vs escalate ✅

**Goal:** The headline multi-agent piece. When multiple servers fire, reconcile their outputs and decide: auto-execute, or escalate with a structured brief.

**Tasks:**
- ⏳ `agent/conflict_resolver.py` — reconciliation logic returning:
    ```json
    {
      "resolution": "auto" | "escalate",
      "action": "...",
      "escalation_brief": {
        "conflict": "...",
        "risk_level": "low | medium | high",
        "recommendation": "...",
        "question_for_hr": "..."
      }
    }
    ```
- ⏳ Wire into `orchestrator.py`: after the tool-call loop completes, if `classifier.conflict_possible == True` AND multiple servers fired, route through the resolver
- ⏳ Gate write tools on resolver verdict — writes only fire when resolution is `auto`. The agent never directly calls `update_employment_status` without going through the resolver
- ⏳ Update `audit_log.resolution` to capture `auto` / `escalate` per request; set `escalated: true` accordingly
- ⏳ Stream escalation brief as a structured event in the SSE stream (`{"type":"escalation","brief":{...}}`)

**What's defensible after this phase:**
- "Writes are gated on conflict resolution. The orchestrator never calls write tools directly — only the resolver can authorize. Two layered safety mechanisms: per-tool audit log (Phase 4) + cross-agent conflict gating (Phase 6)."
- "Escalation briefs are structured, not free-form text. HR receives a consistent shape: conflict, risk, recommendation, question."

---

## Phase 7 — UI polish ⏳

**Goal:** Take the UI from "functional demo" to "portfolio-ready."

**Tasks:**
- ⏳ Escalation brief rendered as a dedicated structured card (not just text) when `resolution: escalate`
- ⏳ Agent pills get distinct colors (jurisdiction = blue, hris = green, policy = purple — or similar)
- ⏳ Session cost rollup in footer (alongside per-message costs)
- ⏳ Better error states (network failure, rate limit, etc.)
- ⏳ Mobile responsiveness pass

---

## Phase 8 — Expand jurisdiction to remaining countries ⏳

**Goal:** Broaden coverage from 3 → 13 jurisdictions. Mechanical work that proves the architecture scales.

**Tasks:**
- ⏳ Research + add to `docs/jurisdiction.md` (I draft, user reviews):
    - IT (TFR), FR (cadre/non-cadre + indemnité de licenciement), UK (statutory notice + redundancy), ES (objective dismissal), SG (Employment Act), ZA (LRA + CCMA), US-TX (at-will + next payday), US-NY (WARN + payday)
- ⏳ Translate to structured Python in `mcp_servers/jurisdiction_rules.py`
- ⏳ Graceful fallback for JP and IN — `UNCOVERED_COUNTRIES_MESSAGE` already handles these; add explicit per-country notes
- ⏳ Update `scripts/test_jurisdiction.py` with new scenarios

**What's defensible after this phase:**
- "Adding a country is data work, not architecture work. The rules engine and tool surface did not change between Phase 2 and Phase 8."

---

## Phase 9 — Hardening ⏳

**Goal:** Production-grade observability and cost discipline. Not features — operational maturity.

**Tasks:**
- ⏳ Per-IP rate limit on `/api/chat/stream` (slowapi or similar)
- ⏳ Prompt caching on Anthropic calls — cache the system prompt + tool schemas (the ~2k input tokens that repeat every classifier/orchestrator call). Cuts cost by ~80% on those portions
- ⏳ `ruff check` + `pytest` wired into `pre-commit` (optional) and GitHub Actions CI
- ⏳ Basic test coverage: classifier (mock Anthropic), rules engine (deterministic, easy to test), orchestrator integration test
- ⏳ Cost dashboard query: simple Supabase view that aggregates `audit_log.cost_usd` by day / session / agent

**What's defensible after this phase:**
- "Prompt caching cuts classifier cost by ~80% because system prompt + tool schema are stable. I waited until I had traffic patterns to confirm what was worth caching."
- "Rate limiting per-IP is the minimum bar for a public demo. Not a substitute for auth, but enough to prevent obvious abuse."

---

## Phase 10 — Custom domain + portfolio launch ⏳

**Goal:** Make it findable. Drive traffic from your portfolio.

**Tasks:**
- ⏳ Custom domain on Vercel (e.g. `hr.lucaslima.xyz`)
- ⏳ Portfolio card on `lucaslima.xyz/ai-portfolio` linking to the live URL
- ⏳ `README.md` polish — one-paragraph summary, architecture diagram (mermaid), quickstart, links to `CLAUDE.md` + `docs/jurisdiction.md` + this roadmap
- ⏳ Optional: blog post or LinkedIn write-up on the architectural decisions (MCP boundary, classifier/orchestrator split, deterministic compliance, tool-call cap)

---

## Cross-references

- **Spec / non-negotiables:** `CLAUDE.md` (`## Non-Negotiable Design Rules`)
- **Jurisdiction source of truth:** `docs/jurisdiction.md`
- **Demo scenarios:** `CLAUDE.md` (`## Demo Scenarios`) — 7 scenarios that gate phase completion
- **Mock employee dataset:** `CLAUDE.md` (`## Mock Employees`) — 20 employees chosen to cover edge cases
- **DB schema:** `db/schema.sql`
- **Smoke test:** `scripts/smoke_test.py`
- **Jurisdiction test:** `scripts/test_jurisdiction.py`
- **Classifier test:** `scripts/test_classifier.py`

## Quick commands

```powershell
# Verify services
uv run python scripts/smoke_test.py

# Verify rules engine
uv run python scripts/test_jurisdiction.py

# Verify classifier routing
uv run python scripts/test_classifier.py

# Run agent end-to-end (CLI)
uv run python -m agent.orchestrator "your question here"

# Run the full app (UI + API) locally
uv run uvicorn api.index:app --host 127.0.0.1 --port 8000
# Then open http://127.0.0.1:8000
```
