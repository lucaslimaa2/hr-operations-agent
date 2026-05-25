-- Cost & observability views for the HR Operations Agent audit_log.
--
-- Paste this into the Supabase SQL editor to install the views. After that,
-- you can query them like any table. They re-compute on every read — no
-- materialization, always fresh.
--
-- These prove the audit_log isn't write-only — it's a queryable observability
-- surface. Useful for cost tracking, escalation rate, agent usage analysis.

-- ----------------------------------------------------------------------------
-- daily_cost: total spend per day, with request count and escalation breakdown
-- ----------------------------------------------------------------------------
create or replace view daily_cost as
select
  date_trunc('day', created_at)::date as day,
  count(*)                            as requests,
  sum(cost_usd)::numeric(10,4)        as total_cost_usd,
  avg(cost_usd)::numeric(10,5)        as avg_cost_usd,
  count(*) filter (where escalated)   as escalated_requests,
  count(*) filter (where resolution = 'auto')      as resolved_auto,
  count(*) filter (where resolution = 'truncated') as truncated_at_cap
from audit_log
group by 1
order by 1 desc;

-- ----------------------------------------------------------------------------
-- session_summary: aggregate per chat session
-- ----------------------------------------------------------------------------
create or replace view session_summary as
select
  session_id,
  min(created_at)              as started_at,
  max(created_at)              as last_request_at,
  count(*)                     as request_count,
  sum(cost_usd)::numeric(10,4) as session_cost_usd,
  count(*) filter (where escalated) as escalations,
  -- jsonb_agg keeps the full tool-call traces per session for deep dives
  array_agg(distinct unnest_agents) as all_agents_invoked
from audit_log,
     lateral unnest(coalesce(agents_invoked, array[]::text[])) as unnest_agents
group by session_id
order by min(created_at) desc;

-- ----------------------------------------------------------------------------
-- agent_usage: how often each MCP server fires + cost attributed
-- ----------------------------------------------------------------------------
create or replace view agent_usage as
select
  unnest(agents_invoked)          as agent,
  count(*)                        as invocations,
  sum(cost_usd)::numeric(10,4)    as total_cost_attributed_usd,
  count(*) filter (where escalated) as escalation_count
from audit_log
where agents_invoked is not null and array_length(agents_invoked, 1) > 0
group by 1
order by 2 desc;

-- ----------------------------------------------------------------------------
-- recent_escalations: the last 50 escalated requests with full context
-- Useful for "what did the resolver block this week?"
-- ----------------------------------------------------------------------------
create or replace view recent_escalations as
select
  created_at,
  session_id,
  user_input,
  agents_invoked,
  tool_calls,
  cost_usd
from audit_log
where escalated = true
order by created_at desc
limit 50;

-- ----------------------------------------------------------------------------
-- Example queries (run these directly, not part of the views)
-- ----------------------------------------------------------------------------

-- Total spend over the last 7 days
-- select sum(cost_usd) from audit_log where created_at > now() - interval '7 days';

-- Most expensive single request
-- select created_at, user_input, cost_usd
-- from audit_log order by cost_usd desc limit 1;

-- Distribution of which agents fire together
-- select agents_invoked, count(*)
-- from audit_log group by agents_invoked order by count(*) desc;

-- All writes (resolution = 'write') with before/after state from tool_calls
-- select created_at, user_input, tool_calls
-- from audit_log where resolution = 'write' order by created_at desc;
