"""
Seed the Supabase `employees` table with the 20 mock employees from CLAUDE.md.

Idempotent — uses upsert on the primary key `id`, so re-running is safe and
will not create duplicates.

Date-freshness note (important):
    CLAUDE.md lists start_dates that were written assuming a 2025 demo date.
    A few employees' edge cases depend on tenure being in a specific range
    (e.g., Ana Müller is meant to be in probation, <6 months tenure).
    Because Python's `date.today()` advances and the demo is meant to keep
    working, we ADJUST those few dates so the demo scenarios remain coherent.

    Specifically:
      - Ana Müller (emp_005): adjusted to ~3 months ago so she's still in
        DE Probezeit (demo scenario #3 depends on this).

    All other employees use their CLAUDE.md dates verbatim.

Usage:
    uv run python scripts/seed_data.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

from supabase import create_client  # noqa: E402

# -----------------------------------------------------------------------------
# Date adjustments — keep demo scenarios coherent over time.
# -----------------------------------------------------------------------------

TODAY = date.today()


def months_ago(months: int) -> str:
    """Return an ISO date string approximately N months before today."""
    # 30-day approximation is fine here — we only need "in probation" or "past probation".
    d = TODAY - timedelta(days=months * 30)
    return d.isoformat()


# Ana must be in Probezeit (<6 months). Pick ~3 months ago to leave margin.
ANA_MULLER_START_DATE = months_ago(3)


# -----------------------------------------------------------------------------
# Employee dataset (from CLAUDE.md table)
# -----------------------------------------------------------------------------

EMPLOYEES: list[dict] = [
    {
        "id": "emp_001",
        "name": "João Silva",
        "email": "joao.silva@example.com",
        "country": "BR",
        "employment_type": "CLT",
        "start_date": "2021-03-01",
        "role": "Senior Software Engineer",
        "department": "Engineering",
        "compensation_usd": 95_000,
        "manager_id": "emp_003",
    },
    {
        "id": "emp_002",
        "name": "Maria Santos",
        "email": "maria.santos@example.com",
        "country": "BR",
        "employment_type": "PJ",
        "start_date": "2023-06-01",
        "role": "Product Designer",
        "department": "Design",
        "compensation_usd": 72_000,
        "manager_id": None,
    },
    {
        "id": "emp_003",
        "name": "Lucas Oliveira",
        "email": "lucas.oliveira@example.com",
        "country": "BR",
        "employment_type": "CLT",
        "start_date": "2018-01-15",
        "role": "Engineering Manager",
        "department": "Engineering",
        "compensation_usd": 135_000,
        "manager_id": None,
    },
    {
        "id": "emp_004",
        "name": "Sarah Chen",
        "email": "sarah.chen@example.com",
        "country": "DE",
        "employment_type": "full-time",
        "start_date": "2020-01-15",
        "role": "Staff Software Engineer",
        "department": "Engineering",
        "compensation_usd": 110_000,
        "manager_id": "emp_003",
    },
    {
        "id": "emp_005",
        "name": "Ana Müller",
        "email": "ana.muller@example.com",
        "country": "DE",
        "employment_type": "full-time",
        "start_date": ANA_MULLER_START_DATE,  # Adjusted — see header note
        "role": "Software Engineer",
        "department": "Engineering",
        "compensation_usd": 78_000,
        "manager_id": "emp_004",
    },
    {
        "id": "emp_006",
        "name": "James Kirk",
        "email": "james.kirk@example.com",
        "country": "UK",
        "employment_type": "full-time",
        "start_date": "2022-09-01",
        "role": "Sales Director",
        "department": "Sales",
        "compensation_usd": 145_000,
        "manager_id": None,
    },
    {
        "id": "emp_007",
        "name": "Sophie Williams",
        "email": "sophie.williams@example.com",
        "country": "UK",
        "employment_type": "full-time",
        "start_date": "2019-03-01",
        "role": "Account Executive",
        "department": "Sales",
        "compensation_usd": 92_000,
        "manager_id": "emp_006",
    },
    {
        "id": "emp_008",
        "name": "Emily Ross",
        "email": "emily.ross@example.com",
        "country": "US-CA",
        "employment_type": "full-time",
        "start_date": "2023-01-01",
        "role": "Marketing Manager",
        "department": "Marketing",
        "compensation_usd": 115_000,
        "manager_id": None,
    },
    {
        "id": "emp_009",
        "name": "Raj Patel",
        "email": "raj.patel@example.com",
        "country": "US-TX",
        "employment_type": "full-time",
        "start_date": "2023-01-01",
        "role": "Data Engineer",
        "department": "Engineering",
        "compensation_usd": 125_000,
        "manager_id": "emp_003",
    },
    {
        "id": "emp_010",
        "name": "Marcus Johnson",
        "email": "marcus.johnson@example.com",
        "country": "US-NY",
        "employment_type": "full-time",
        "start_date": "2021-06-01",
        "role": "Director of Product",
        "department": "Product",
        "compensation_usd": 175_000,
        "manager_id": None,
    },
    {
        "id": "emp_011",
        "name": "Carlos Ruiz",
        "email": "carlos.ruiz@example.com",
        "country": "ES",
        "employment_type": "full-time",
        "start_date": "2019-05-01",
        "role": "Senior Designer",
        "department": "Design",
        "compensation_usd": 75_000,
        "manager_id": "emp_002",
    },
    {
        "id": "emp_012",
        "name": "Isabella García",
        "email": "isabella.garcia@example.com",
        "country": "ES",
        "employment_type": "part-time",
        "start_date": "2022-11-01",
        "role": "Content Writer",
        "department": "Marketing",
        "compensation_usd": 38_000,
        "manager_id": "emp_008",
    },
    {
        "id": "emp_013",
        "name": "Luca Rossi",
        "email": "luca.rossi@example.com",
        "country": "IT",
        "employment_type": "full-time",
        "start_date": "2020-08-01",
        "role": "DevOps Engineer",
        "department": "Engineering",
        "compensation_usd": 82_000,
        "manager_id": "emp_003",
    },
    {
        "id": "emp_014",
        "name": "Chiara Bianchi",
        "email": "chiara.bianchi@example.com",
        "country": "IT",
        "employment_type": "full-time",
        "start_date": "2024-02-01",
        "role": "QA Engineer",
        "department": "Engineering",
        "compensation_usd": 58_000,
        "manager_id": "emp_013",
    },
    {
        "id": "emp_015",
        "name": "Pierre Dubois",
        "email": "pierre.dubois@example.com",
        "country": "FR",
        "employment_type": "full-time",
        "start_date": "2019-11-01",
        "role": "Engineering Lead (Cadre)",
        "department": "Engineering",
        "compensation_usd": 105_000,
        "manager_id": None,
    },
    {
        "id": "emp_016",
        "name": "Camille Martin",
        "email": "camille.martin@example.com",
        "country": "FR",
        "employment_type": "full-time",
        "start_date": "2023-07-01",
        "role": "Frontend Engineer",
        "department": "Engineering",
        "compensation_usd": 68_000,
        "manager_id": "emp_015",
    },
    {
        "id": "emp_017",
        "name": "Chen Wei",
        "email": "chen.wei@example.com",
        "country": "SG",
        "employment_type": "full-time",
        "start_date": "2021-09-01",
        "role": "Regional Sales Manager",
        "department": "Sales",
        "compensation_usd": 98_000,
        "manager_id": "emp_006",
    },
    {
        "id": "emp_018",
        "name": "Aisha Nkosi",
        "email": "aisha.nkosi@example.com",
        "country": "ZA",
        "employment_type": "full-time",
        "start_date": "2020-04-01",
        "role": "Customer Success Manager",
        "department": "Customer Success",
        "compensation_usd": 62_000,
        "manager_id": None,
    },
    {
        "id": "emp_019",
        "name": "Yuki Tanaka",
        "email": "yuki.tanaka@example.com",
        "country": "JP",
        "employment_type": "full-time",
        "start_date": "2022-03-01",
        "role": "Business Development",
        "department": "Sales",
        "compensation_usd": 88_000,
        "manager_id": "emp_006",
    },
    {
        "id": "emp_020",
        "name": "Priya Sharma",
        "email": "priya.sharma@example.com",
        "country": "IN",
        "employment_type": "contractor",
        "start_date": "2024-01-01",
        "role": "Software Engineer",
        "department": "Engineering",
        "compensation_usd": 45_000,
        "manager_id": "emp_003",
    },
]


# -----------------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------------


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_KEY in .env", file=sys.stderr)
        return 1

    client = create_client(url, key)

    print(f"Seeding {len(EMPLOYEES)} employees into Supabase (upsert)...")
    print(f"  Ana Müller adjusted start_date: {ANA_MULLER_START_DATE} (~3 months ago)\n")

    # Upsert in a single batch — Supabase's PostgREST supports it.
    resp = client.table("employees").upsert(EMPLOYEES, on_conflict="id").execute()

    inserted = len(resp.data) if resp.data else 0
    print(f"Upserted {inserted}/{len(EMPLOYEES)} rows.")

    # Quick sanity check — read a few back
    print("\nSample reads:")
    for emp_id in ["emp_001", "emp_005", "emp_019"]:
        row = client.table("employees").select("*").eq("id", emp_id).execute()
        if row.data:
            r = row.data[0]
            print(f"  {r['id']:8} {r['name']:20} {r['country']:6} {r['employment_type']:12} start={r['start_date']}")
        else:
            print(f"  {emp_id} — NOT FOUND")

    return 0


if __name__ == "__main__":
    sys.exit(main())
