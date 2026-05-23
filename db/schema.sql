-- HR Operations Agent — database schema
-- Applied once to Supabase via the SQL editor.
-- Two tables: `employees` (mock HRIS) and `audit_log` (every agent request).

-- ----------------------------------------------------------------------------
-- employees: mock Workday records. Seeded by scripts/seed_data.py.
-- ----------------------------------------------------------------------------
create table if not exists employees (
  id                text primary key,                 -- e.g. 'emp_001' (HRIS-style string IDs)
  name              text not null,
  email             text,
  country           text not null,                    -- ISO-ish code, e.g. 'BR', 'DE', 'US-CA'
  employment_type   text not null,                    -- e.g. 'CLT', 'PJ', 'full-time', 'contractor'
  start_date        date not null,
  role              text,
  department        text,
  compensation_usd  integer,
  employment_status text default 'active',            -- 'active' | 'terminated' | 'on_leave'
  manager_id        text
);

-- ----------------------------------------------------------------------------
-- audit_log: one row per agent request. Non-negotiable per CLAUDE.md —
-- every write tool MUST log here before returning, and every request
-- (read or write) is captured for cost + observability.
-- ----------------------------------------------------------------------------
create table if not exists audit_log (
  id              uuid default gen_random_uuid() primary key,
  created_at      timestamptz default now(),
  session_id      text,                               -- groups requests by chat session
  user_input      text,                               -- the raw natural-language request
  agents_invoked  text[],                             -- e.g. ARRAY['jurisdiction','hris']
  tool_calls      jsonb,                              -- full tool invocation log per request
  resolution      text,                               -- 'auto' | 'escalate' | 'read_only'
  escalated       boolean default false,
  cost_usd        numeric(10,6)                       -- per-request token cost (Anthropic + OpenAI)
);

-- Indexes for the two access patterns we actually have:
-- 1. retrieve all requests in a chat session (UI history, debugging)
-- 2. time-range queries (dashboards, recent escalations)
create index if not exists audit_log_session_id_idx on audit_log (session_id);
create index if not exists audit_log_created_at_idx on audit_log (created_at desc);
