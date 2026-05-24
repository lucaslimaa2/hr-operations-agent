"""
Policy MCP server — RAG over the HR policy corpus.

Backed by Pinecone (vector store, seeded by scripts/seed_policies.py) + OpenAI
embeddings (text-embedding-3-small, 1536 dim). Source markdown lives in
docs/policies/ and is read directly by get_policy for full-document retrieval.

Two tools:
  - search_policies(query, country="", scenario="") -> top-5 semantic matches
  - get_policy(doc_id) -> full policy document

Why both:
  search_policies is the workhorse — "what's our offboarding process?" returns
  the most relevant chunks. get_policy is the follow-up — "show me the full
  conversion policy" returns the entire document, useful when the agent needs
  more context than the top-5 chunks contain.

Why client-side embedding (not Pinecone integrated inference):
  Keeps the embedding model swappable. Today text-embedding-3-small; tomorrow
  voyage-3 or text-embedding-3-large; same Pinecone index, no migration. The
  embedding step is a tool concern, not a vector-store concern.

Country filter:
  When country='BR' is passed, we filter to chunks scoped 'global', 'multi',
  or 'BR'. This means BR-specific addenda surface in BR searches, FR addenda
  do not, and global chunks always do. Same logic for DE/FR/etc.

Run standalone for testing:
    uv run python -m mcp_servers.policy_server
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from openai import OpenAI
from pinecone import Pinecone

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POLICIES_DIR = PROJECT_ROOT / "docs" / "policies"

EMBED_MODEL = "text-embedding-3-small"
TOP_K = 5

mcp = FastMCP("policy")


# =============================================================================
# Lazy clients
# =============================================================================

_openai: OpenAI | None = None
_pc_index = None


def _get_openai() -> OpenAI:
    global _openai
    if _openai is None:
        _openai = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai


def _get_pinecone_index():
    global _pc_index
    if _pc_index is None:
        pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
        _pc_index = pc.Index(os.environ["PINECONE_INDEX"])
    return _pc_index


# =============================================================================
# Tools
# =============================================================================


@mcp.tool()
def search_policies(
    query: str,
    country: str = "",
    scenario: str = "",
) -> dict[str, Any]:
    """Semantic search over the HR policy corpus.

    Use this for any question about company policy, process, or approval
    requirements (e.g., "what's our offboarding process?", "who needs to approve
    a contractor-to-FTE conversion?", "what's the PIP timeline?").

    Args:
        query: The user's question or topic. Will be embedded and used for
            cosine similarity search.
        country: Optional ISO-ish code (e.g., 'BR', 'DE', 'FR'). When provided,
            filters to chunks tagged 'global', 'multi', or the specific country.
            BR-specific addenda surface in BR searches; FR addenda do not.
            Leave empty for global policy chunks only.
        scenario: Optional free-text scenario hint (e.g., 'termination',
            'conversion'). Currently appended to the query for richer
            embedding; future versions may use it as a stronger filter.

    Returns:
        {"matches": [{doc_id, doc_title, section, country_scope, text, score}, ...],
         "count": int, "query_used": str}. Top-5 results by cosine similarity.
    """
    try:
        # Build the embedding query. Prepending scenario context to the query
        # helps embedding capture the operational intent.
        query_text = f"{scenario}. {query}".strip(". ") if scenario else query

        openai = _get_openai()
        embed_resp = openai.embeddings.create(model=EMBED_MODEL, input=query_text)
        query_vector = embed_resp.data[0].embedding

        # Build country filter if requested.
        pc_filter: dict[str, Any] | None = None
        if country:
            pc_filter = {
                "country_scope": {"$in": ["global", "multi", country]}
            }

        index = _get_pinecone_index()
        result = index.query(
            vector=query_vector,
            top_k=TOP_K,
            include_metadata=True,
            filter=pc_filter,
        )

        matches = []
        for m in result.matches:
            md = m.metadata or {}
            matches.append(
                {
                    "doc_id": md.get("doc_id"),
                    "doc_title": md.get("doc_title"),
                    "section": md.get("section"),
                    "country_scope": md.get("country_scope"),
                    "text": md.get("text"),
                    "score": round(float(m.score), 4),
                }
            )

        return {
            "matches": matches,
            "count": len(matches),
            "query_used": query_text,
            "country_filter": country or None,
        }

    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def get_policy(doc_id: str) -> dict[str, Any]:
    """Retrieve the full text of a policy document by its ID.

    Use this when search_policies returned relevant chunks but you need the
    surrounding context — full sections, headings, and country-specific
    addenda included.

    Args:
        doc_id: Stable identifier matching the markdown filename without
            extension. Returned by search_policies in the 'doc_id' field.
            Examples: 'offboarding-policy', 'compensation-bands',
            'contractor-to-fte-conversion'.

    Returns:
        {"doc_id": ..., "title": ..., "content": "...full markdown...",
         "available_docs": [...]} on success.
        {"error": ..., "available_docs": [...]} if the doc_id is unknown.
    """
    if not doc_id:
        return {"error": "doc_id is required."}

    # Sanitize — only allow simple filename-safe chars to prevent path traversal.
    if "/" in doc_id or "\\" in doc_id or ".." in doc_id:
        return {"error": "Invalid doc_id."}

    file_path = POLICIES_DIR / f"{doc_id}.md"
    available = sorted(p.stem for p in POLICIES_DIR.glob("*.md"))

    if not file_path.exists():
        return {
            "error": f"Policy '{doc_id}' not found.",
            "available_docs": available,
        }

    try:
        content = file_path.read_text(encoding="utf-8")
        # Extract title from first '# ' line
        title = ""
        for line in content.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        return {
            "doc_id": doc_id,
            "title": title,
            "content": content,
            "available_docs": available,
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    mcp.run()
