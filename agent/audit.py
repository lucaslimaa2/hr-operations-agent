"""
Audit log writer.

Single function: log_request(...). Writes one row to the Supabase `audit_log`
table per HR request. Used by the orchestrator (and later, the conflict
resolver).

The audit log is non-negotiable per CLAUDE.md:
  - Every request (read or write) is captured.
  - Every tool call is recorded with arguments + result.
  - Cost is captured.
  - Write operations (e.g., update_employment_status) MUST be logged before
    they return — but that's the write tool's responsibility, separate from
    this per-request audit row.

Failure mode:
  - If Supabase is unreachable, log a warning to stderr and continue.
  - We do NOT block the user response on audit-log success. Observability
    failure must not become a user-visible failure.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)


_client: Client | None = None


def _get_client() -> Client:
    """Lazy Supabase client init. We avoid creating it at import time so
    importing this module doesn't fail in environments without Supabase
    credentials (e.g., unit tests)."""
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "Supabase credentials missing (SUPABASE_URL / SUPABASE_KEY). "
                "Cannot write audit log."
            )
        _client = create_client(url, key)
    return _client


def log_request(
    session_id: str,
    user_input: str,
    agents_invoked: list[str],
    tool_calls: list[dict[str, Any]],
    resolution: str,
    escalated: bool,
    cost_usd: float,
) -> str | None:
    """Insert one audit_log row. Returns the inserted row's id, or None on failure.

    Args:
        session_id: client-supplied chat session ID (groups requests).
        user_input: the raw natural-language message.
        agents_invoked: list of agent/server names invoked, e.g. ['jurisdiction'].
        tool_calls: list of {tool, args, result} dicts. Full tool-call log.
        resolution: 'auto' | 'escalate' | 'read_only' | 'error'.
        escalated: True if the conflict resolver escalated this request.
        cost_usd: total per-request cost (classifier + orchestrator + ...).
    """
    try:
        client = _get_client()
        row = {
            "session_id": session_id,
            "user_input": user_input,
            "agents_invoked": agents_invoked,
            "tool_calls": tool_calls,
            "resolution": resolution,
            "escalated": escalated,
            "cost_usd": cost_usd,
        }
        resp = client.table("audit_log").insert(row).execute()
        if resp.data:
            return resp.data[0].get("id")
        return None
    except Exception as e:  # noqa: BLE001 — observability MUST NOT break user response
        print(
            f"[audit] WARNING: failed to write audit_log row: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return None
