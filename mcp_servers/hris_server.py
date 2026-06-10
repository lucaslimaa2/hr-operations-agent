"""
HRIS MCP server — mock Workday.

Backed by Supabase `employees` table. In production, this server's function
bodies would call Workday/BambooHR/Rippling REST APIs instead of Supabase.
The tool surface (names, signatures, return shapes) stays identical — that's
the architectural promise of the MCP boundary.

Exposes four tools:
  - get_employee(employee_id)
  - search_employees(name)
  - get_payroll_calendar(country)
  - update_employment_status(employee_id, status, effective_date)   ← WRITE

Write-tool contract (per CLAUDE.md non-negotiable):
  Every write writes to `audit_log` BEFORE returning. We log the write at the
  TOOL level (here) in addition to the orchestrator's per-request log, so the
  mutation survives even if someone bypasses the orchestrator. Two rows per
  write — different observability angles.

Run standalone for testing:
    uv run python -m mcp_servers.hris_server
The orchestrator launches this as a subprocess via stdio.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from supabase import Client, create_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

mcp = FastMCP("hris")

# Hard cap on search_employees results. Prevents bulk-roster enumeration via
# a single broad query (e.g., empty name, single character). The orchestrator
# also forbids bulk-listing at the system-prompt layer; this is defense in
# depth so a future prompt regression cannot reopen the data-exfil vector.
MAX_SEARCH_RESULTS = 5


# =============================================================================
# Supabase client (lazy)
# =============================================================================

_supabase: Client | None = None


def _get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL or SUPABASE_KEY not set. HRIS server cannot start.")
        _supabase = create_client(url, key)
    return _supabase


# =============================================================================
# Payroll calendar — hardcoded reasonable next-payroll-date estimates per country
# In production, this would query the actual payroll system (ADP, Gusto, etc.).
# =============================================================================

# Frequency conventions vary by country. These reflect common employer practice:
#   - BR: 5th of the month (monthly)
#   - DE: last working day (monthly)
#   - US-CA / US-TX / US-NY: 15th and last day (bi-monthly)
PAYROLL_CALENDAR: dict[str, dict[str, str]] = {
    "BR": {
        "frequency": "monthly",
        "next_payroll_dates": "5th of each month; 13º salário paid in two installments (Nov 30, Dec 20)",
    },
    "DE": {
        "frequency": "monthly",
        "next_payroll_dates": "Last working day of each month",
    },
    "US-CA": {
        "frequency": "semi-monthly",
        "next_payroll_dates": "15th and last day of each month",
    },
    "US-TX": {
        "frequency": "semi-monthly",
        "next_payroll_dates": "15th and last day of each month",
    },
    "US-NY": {
        "frequency": "bi-weekly",
        "next_payroll_dates": "Every other Friday",
    },
    "ES": {
        "frequency": "monthly",
        "next_payroll_dates": "Last day of each month; paga extra in July and December",
    },
    "IT": {
        "frequency": "monthly",
        "next_payroll_dates": "Last working day of each month; 13ª mensilità in December, 14ª in June (where CCNL applies)",
    },
    "FR": {
        "frequency": "monthly",
        "next_payroll_dates": "Last working day of each month",
    },
    "UK": {
        "frequency": "monthly",
        "next_payroll_dates": "Last working day of each month (most common)",
    },
    "SG": {
        "frequency": "monthly",
        "next_payroll_dates": "Last working day of each month; AWS (13th-month bonus) in December where contractual",
    },
    "ZA": {
        "frequency": "monthly",
        "next_payroll_dates": "25th of each month (most common)",
    },
    "JP": {
        "frequency": "monthly",
        "next_payroll_dates": "25th of each month; semi-annual bonuses (June, December)",
    },
    "IN": {
        "frequency": "monthly",
        "next_payroll_dates": "Last working day of each month",
    },
}


# =============================================================================
# Tools
# =============================================================================


@mcp.tool()
def get_employee(employee_id: str) -> dict[str, Any]:
    """Retrieve a full employee record by ID.

    Use this when you have the exact employee ID (e.g., 'emp_001'). For name-based
    lookups, use `search_employees` first.

    Args:
        employee_id: HRIS-style string ID, e.g. 'emp_001'.

    Returns:
        Full employee record with: id, name, email, country, employment_type,
        start_date, role, department, compensation_usd, employment_status,
        manager_id. Returns {"error": ...} if not found.
    """
    try:
        client = _get_supabase()
        resp = client.table("employees").select("*").eq("id", employee_id).execute()
        if not resp.data:
            return {"error": f"Employee {employee_id} not found."}
        emp = resp.data[0]
        emp["tenure_months"] = _tenure_months(emp["start_date"])
        return emp
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def search_employees(name: str) -> dict[str, Any]:
    """Search employees by name (case-insensitive, partial match).

    Use this when the user mentions a SPECIFIC employee by name (e.g., 'Sarah
    Chen', 'João'). Returns at most 5 matches. The query string must be at
    least 2 non-whitespace characters; broader patterns are rejected to
    prevent bulk-roster enumeration. If the user asks for "every employee" or
    "the full roster" or similar, do NOT call this tool — refuse the request.

    Args:
        name: full or partial name. Case-insensitive. Minimum 2 characters.

    Returns:
        {"matches": [...], "count": int, "truncated": bool, "note"?: str}.
        Each employee includes the same fields as get_employee. Empty matches
        list if no hits; "truncated": true if more than 5 employees matched
        and results were capped.
    """
    name = (name or "").strip()
    if len(name) < 2:
        return {
            "matches": [],
            "count": 0,
            "error": (
                "Name query must be at least 2 characters. Bulk-roster lookups are "
                "not supported by this tool; provide a specific name fragment."
            ),
        }
    try:
        client = _get_supabase()
        # PostgREST `ilike` = case-insensitive LIKE. Wrap in %...% for partial match.
        # Fetch one extra row beyond the cap so we can detect overflow without a separate count query.
        pattern = f"%{name}%"
        resp = client.table("employees").select("*").ilike("name", pattern).limit(MAX_SEARCH_RESULTS + 1).execute()
        raw_matches = resp.data or []
        truncated = len(raw_matches) > MAX_SEARCH_RESULTS
        matches = raw_matches[:MAX_SEARCH_RESULTS]
        for emp in matches:
            emp["tenure_months"] = _tenure_months(emp["start_date"])
        result: dict[str, Any] = {"matches": matches, "count": len(matches), "truncated": truncated}
        if truncated:
            result["note"] = (
                f"More than {MAX_SEARCH_RESULTS} matches; results capped at {MAX_SEARCH_RESULTS}. "
                "Ask the user for a more specific name."
            )
        return result
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def get_payroll_calendar(country: str) -> dict[str, Any]:
    """Return the payroll calendar (frequency + next dates) for a country.

    Use this for ANY question about payroll cycles, next payroll dates, pay
    frequency, or final-paycheck timing in a country. Common triggers:
    "when's the next payroll in BR?", "what's the pay schedule for our DE team?",
    "how often are people paid in Italy?", and for terminations, "when will the
    final paycheck go out?". Especially relevant for US-CA where final pay is
    due IMMEDIATELY at termination, not on the next payroll date.

    Args:
        country: ISO-ish code, e.g. 'BR', 'DE', 'US-CA'.

    Returns:
        {country, frequency, next_payroll_dates}, or {"error": ...} if the country
        isn't in our calendar.
    """
    info = PAYROLL_CALENDAR.get(country)
    if info is None:
        return {
            "error": f"No payroll calendar configured for country '{country}'.",
            "covered_countries": sorted(PAYROLL_CALENDAR.keys()),
        }
    return {"country": country, **info}


@mcp.tool()
def update_employment_status(
    employee_id: str,
    status: str,
    effective_date: str | None = None,
) -> dict[str, Any]:
    """Update an employee's employment_status. WRITE OPERATION.

    Mutates the HRIS employee record. Every call writes a dedicated row to
    `audit_log` BEFORE returning, capturing the before/after state. This is
    non-negotiable per the project's audit requirements.

    Common transitions:
      active → terminated     (offboarding completed)
      active → on_leave       (parental, medical, sabbatical)
      on_leave → active       (return)
      active → resigned       (employee-initiated separation)

    Args:
        employee_id: HRIS-style string ID.
        status: New employment_status. One of: 'active', 'terminated', 'on_leave', 'resigned'.
        effective_date: ISO date string (YYYY-MM-DD). Defaults to today.

    Returns:
        {"success": true, "employee_id": ..., "before": {...}, "after": {...},
         "audit_log_id": "..."} on success, or {"error": ...} on failure.
    """
    valid_statuses = {"active", "terminated", "on_leave", "resigned"}
    if status not in valid_statuses:
        return {"error": (f"Invalid status '{status}'. Must be one of: {sorted(valid_statuses)}.")}

    effective_date = effective_date or date.today().isoformat()

    try:
        client = _get_supabase()

        # ---- 1. Read current state (the "before") ----
        before_resp = client.table("employees").select("*").eq("id", employee_id).execute()
        if not before_resp.data:
            return {"error": f"Employee {employee_id} not found — cannot update."}
        before = before_resp.data[0]

        # ---- 2. Apply the update ----
        update_resp = client.table("employees").update({"employment_status": status}).eq("id", employee_id).execute()
        if not update_resp.data:
            return {"error": "Update returned no data — write may have failed."}
        after = update_resp.data[0]

        # ---- 3. Write tool-level audit_log row BEFORE returning ----
        # This is the non-negotiable requirement. The orchestrator ALSO logs a
        # per-request row that contains this tool call in its tool_calls list,
        # but this row is written by the tool itself for defense-in-depth.
        audit_row = {
            "session_id": f"write:hris:{employee_id}",
            "user_input": (
                f"update_employment_status(employee_id={employee_id}, status={status}, effective_date={effective_date})"
            ),
            "agents_invoked": ["hris"],
            "tool_calls": [
                {
                    "tool": "update_employment_status",
                    "args": {
                        "employee_id": employee_id,
                        "status": status,
                        "effective_date": effective_date,
                    },
                    "before": {"employment_status": before.get("employment_status")},
                    "after": {"employment_status": after.get("employment_status")},
                }
            ],
            "resolution": "write",
            "escalated": False,
            "cost_usd": 0,
        }
        audit_resp = client.table("audit_log").insert(audit_row).execute()
        audit_id = audit_resp.data[0]["id"] if audit_resp.data else None

        return {
            "success": True,
            "employee_id": employee_id,
            "effective_date": effective_date,
            "before": {"employment_status": before.get("employment_status")},
            "after": {"employment_status": after.get("employment_status")},
            "audit_log_id": audit_id,
        }

    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


# =============================================================================
# Helpers
# =============================================================================


def _tenure_months(start_date_str: str) -> int:
    """Months between start_date and today. Approximate (30-day months)."""
    try:
        from datetime import date as _date

        start = _date.fromisoformat(start_date_str)
        today = _date.today()
        delta = today - start
        return max(0, delta.days // 30)
    except Exception:  # noqa: BLE001
        return 0


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    mcp.run()
