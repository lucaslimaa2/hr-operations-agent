"""
Smoke test for all external services.

Pings Anthropic, OpenAI, Supabase, and Pinecone in sequence using the keys
from .env. Prints a check or cross per service. Run this any time you
suspect a config issue — it'll tell you in seconds whether your environment
is sane.

Usage:
    uv run python scripts/smoke_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (one level up from scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=True)

OK = "[OK]  "
FAIL = "[FAIL]"


def check_anthropic() -> bool:
    """One cheap Haiku call. Verifies the key works and we can reach the API."""
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        )
        text = resp.content[0].text.strip().lower()
        if "ok" in text:
            print(f"{OK} Anthropic — Haiku responded")
            return True
        print(f"{FAIL} Anthropic — unexpected response: {text!r}")
        return False
    except Exception as e:
        print(f"{FAIL} Anthropic — {type(e).__name__}: {e}")
        return False


def check_openai() -> bool:
    """One embedding call. Verifies key + model availability."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.embeddings.create(
            model="text-embedding-3-small",
            input="smoke test",
        )
        dim = len(resp.data[0].embedding)
        if dim == 1536:
            print(f"{OK} OpenAI — embeddings returned {dim} dims")
            return True
        print(f"{FAIL} OpenAI — unexpected embedding dim: {dim}")
        return False
    except Exception as e:
        print(f"{FAIL} OpenAI — {type(e).__name__}: {e}")
        return False


def check_supabase() -> bool:
    """Read from the audit_log table. Verifies URL + key + schema applied."""
    try:
        from supabase import create_client

        client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_KEY"],
        )
        # Lightweight existence check: count=0, no rows fetched.
        resp = client.table("audit_log").select("id", count="exact").limit(0).execute()
        count = resp.count if resp.count is not None else "?"
        print(f"{OK} Supabase — audit_log accessible (rows: {count})")
        return True
    except Exception as e:
        print(f"{FAIL} Supabase — {type(e).__name__}: {e}")
        print("       Hint: did you apply db/schema.sql in the Supabase SQL editor?")
        return False


def check_pinecone() -> bool:
    """List indexes and confirm the configured one exists."""
    try:
        from pinecone import Pinecone

        pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        index_name = os.environ["PINECONE_INDEX"]
        names = [idx.name for idx in pc.list_indexes()]
        if index_name in names:
            stats = pc.Index(index_name).describe_index_stats()
            print(
                f"{OK} Pinecone — index '{index_name}' exists "
                f"(vectors: {stats.get('total_vector_count', 0)})"
            )
            return True
        print(f"{FAIL} Pinecone — index '{index_name}' not found. Existing: {names}")
        return False
    except Exception as e:
        print(f"{FAIL} Pinecone — {type(e).__name__}: {e}")
        return False


def main() -> int:
    print("Running smoke test...\n")
    results = [
        check_anthropic(),
        check_openai(),
        check_supabase(),
        check_pinecone(),
    ]
    print()
    if all(results):
        print("All services healthy.")
        return 0
    failed = sum(1 for r in results if not r)
    print(f"{failed} service(s) failed. Fix before continuing.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
