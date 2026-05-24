"""
Seed Pinecone with policy chunks from docs/policies/*.md.

Pipeline per file:
  1. Read the markdown.
  2. Extract the title from the first '# ' heading.
  3. Split into chunks along H2 boundaries (sections starting with '## ').
  4. Detect country_scope per chunk from the section heading (BR / DE / FR / global).
  5. Embed each chunk via OpenAI text-embedding-3-small (1536 dims).
  6. Upsert all chunks to Pinecone with metadata, including the chunk text itself
     so retrieval doesn't require a second lookup.

Why H2 boundaries (not arbitrary char counts):
  HR policy markdown is already structured into coherent sections. Cutting at
  H2 preserves topical coherence. Semantic chunking exists but is overkill for
  well-structured documents like these.

Idempotent: re-run safely. Pinecone upsert overwrites existing vectors at the
same ID. Chunk IDs are stable: '<doc_id>#<chunk_index>'.

Usage:
    uv run python scripts/seed_policies.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

from openai import OpenAI  # noqa: E402
from pinecone import Pinecone  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
POLICIES_DIR = PROJECT_ROOT / "docs" / "policies"

EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536  # must match the Pinecone index dim
BATCH_SIZE = 100  # Pinecone upsert batch limit


# =============================================================================
# Country scope detection
# =============================================================================

# Patterns to detect country-specific sections from the H2 heading.
# Looks for "(BR)" / "(DE)" / "(FR)" or "Brazil " / "Germany " / "France ".
COUNTRY_PATTERNS = {
    "BR": re.compile(r"\b(BR|Brazil|Brasil)\b", re.IGNORECASE),
    "DE": re.compile(r"\b(DE|Germany|Deutschland)\b", re.IGNORECASE),
    "FR": re.compile(r"\b(FR|France)\b", re.IGNORECASE),
}


def detect_country_scope(section_heading: str) -> str:
    """Return 'BR' / 'DE' / 'FR' / 'multi' / 'global'.

    'multi' means the section heading explicitly covers multiple countries
    (e.g., "Country-specific notes — BR, DE, FR"). Those chunks come up in
    any country search.
    """
    matches = [c for c, pat in COUNTRY_PATTERNS.items() if pat.search(section_heading)]
    if len(matches) == 0:
        return "global"
    if len(matches) == 1:
        return matches[0]
    return "multi"


# =============================================================================
# Markdown parsing
# =============================================================================


def parse_markdown(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (title, [(section_heading, section_body), ...]).

    Primary split is at H2 boundaries. If an H2 section contains H3 sub-headings
    (used in our policies for country-specific addenda like '### Brazil (BR)'),
    we sub-split at H3 so each country gets its own chunk. The combined heading
    becomes 'H2 — H3' so the country pattern matches when detecting scope.
    """
    lines = text.splitlines()

    # Extract title from first '# ' line
    title = ""
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break
    if not title:
        title = "Untitled"

    # First pass: split at H2 boundaries.
    h2_sections: list[tuple[str, list[str]]] = []
    current_heading = "Overview"
    current_body: list[str] = []
    in_intro = True

    for line in lines:
        if line.startswith("# ") and in_intro:
            continue
        if line.startswith("## "):
            if current_body:
                h2_sections.append((current_heading, current_body))
            current_heading = line[3:].strip()
            current_body = []
            in_intro = False
        else:
            current_body.append(line)
    if current_body:
        h2_sections.append((current_heading, current_body))

    # Second pass: within each H2, sub-split at H3 boundaries (if any).
    chunks: list[tuple[str, str]] = []
    for h2_heading, h2_lines in h2_sections:
        # Check whether this H2 contains any H3s.
        has_h3 = any(line.startswith("### ") for line in h2_lines)

        if not has_h3:
            body = "\n".join(h2_lines).strip()
            if body:
                chunks.append((h2_heading, body))
            continue

        # H2 has H3s — sub-split.
        sub_heading = ""
        sub_body: list[str] = []
        preamble_body: list[str] = []
        in_sub = False

        for line in h2_lines:
            if line.startswith("### "):
                # Flush previous sub or the preamble
                if in_sub and sub_body:
                    combined = f"{h2_heading} — {sub_heading}"
                    chunks.append((combined, "\n".join(sub_body).strip()))
                elif not in_sub and preamble_body and any(s.strip() for s in preamble_body):
                    chunks.append((h2_heading, "\n".join(preamble_body).strip()))
                sub_heading = line[4:].strip()
                sub_body = []
                in_sub = True
            elif in_sub:
                sub_body.append(line)
            else:
                preamble_body.append(line)

        # Flush final sub
        if in_sub and sub_body:
            combined = f"{h2_heading} — {sub_heading}"
            chunks.append((combined, "\n".join(sub_body).strip()))

    return title, chunks


# =============================================================================
# Pipeline
# =============================================================================


def main() -> int:
    api_key = os.environ.get("OPENAI_API_KEY")
    pc_key = os.environ.get("PINECONE_API_KEY")
    pc_index = os.environ.get("PINECONE_INDEX")
    if not api_key or not pc_key or not pc_index:
        print(
            "Missing one of OPENAI_API_KEY / PINECONE_API_KEY / PINECONE_INDEX in .env",
            file=sys.stderr,
        )
        return 1

    if not POLICIES_DIR.exists():
        print(f"No policies directory at {POLICIES_DIR}", file=sys.stderr)
        return 1

    policy_files = sorted(POLICIES_DIR.glob("*.md"))
    if not policy_files:
        print(f"No .md files found in {POLICIES_DIR}", file=sys.stderr)
        return 1

    print(f"Found {len(policy_files)} policy files. Reading + chunking…\n")

    # Collect every chunk + metadata before embedding (so we batch the API call).
    pending: list[dict] = []
    for path in policy_files:
        doc_id = path.stem
        text = path.read_text(encoding="utf-8")
        title, chunks = parse_markdown(text)
        print(f"  {path.name}: '{title}' → {len(chunks)} chunks")
        for idx, (section, body) in enumerate(chunks):
            country_scope = detect_country_scope(section)
            chunk_id = f"{doc_id}#{idx}"
            pending.append(
                {
                    "id": chunk_id,
                    "doc_id": doc_id,
                    "doc_title": title,
                    "section": section,
                    "country_scope": country_scope,
                    "chunk_index": idx,
                    "text": body,
                }
            )

    print(f"\nTotal chunks to embed: {len(pending)}\n")

    # ---- Embed (batched API call) ----
    openai = OpenAI(api_key=api_key)
    texts = [p["text"] for p in pending]
    embed_resp = openai.embeddings.create(model=EMBED_MODEL, input=texts)
    if len(embed_resp.data) != len(pending):
        print(
            f"Embedding count mismatch: got {len(embed_resp.data)}, expected {len(pending)}",
            file=sys.stderr,
        )
        return 1

    for i, item in enumerate(pending):
        item["embedding"] = embed_resp.data[i].embedding

    print(f"Embedded {len(pending)} chunks via {EMBED_MODEL}.")

    # ---- Upsert to Pinecone (batched) ----
    pc = Pinecone(api_key=pc_key)
    index = pc.Index(pc_index)

    # Clean rebuild: wipe the index before upserting. Avoids orphan chunks if
    # the chunker logic or doc structure changes between runs (otherwise old
    # chunk IDs that no longer correspond to anything stay around and pollute
    # search results).
    try:
        existing_count = index.describe_index_stats().get("total_vector_count", 0)
        if existing_count:
            print(f"Wiping {existing_count} existing vectors for clean rebuild…")
            index.delete(delete_all=True)
    except Exception as e:  # noqa: BLE001
        # If the index is empty, delete_all may return an error on some Pinecone
        # serverless tiers; that's fine — proceed.
        print(f"(delete_all skipped: {type(e).__name__}: {e})")

    vectors = [
        {
            "id": p["id"],
            "values": p["embedding"],
            "metadata": {
                "doc_id": p["doc_id"],
                "doc_title": p["doc_title"],
                "section": p["section"],
                "country_scope": p["country_scope"],
                "chunk_index": p["chunk_index"],
                "text": p["text"],
            },
        }
        for p in pending
    ]

    upserted = 0
    for batch_start in range(0, len(vectors), BATCH_SIZE):
        batch = vectors[batch_start : batch_start + BATCH_SIZE]
        index.upsert(vectors=batch)
        upserted += len(batch)

    stats = index.describe_index_stats()
    total_in_index = stats.get("total_vector_count", 0)

    print(f"\nUpserted {upserted} vectors to Pinecone index '{pc_index}'.")
    print(f"Index now contains {total_in_index} vectors total.")

    # Sample readback to confirm
    print("\nSample chunks (by country_scope):")
    for scope in ("global", "BR", "DE", "FR"):
        sample = [p for p in pending if p["country_scope"] == scope][:1]
        if sample:
            p = sample[0]
            print(
                f"  [{scope:6}] {p['id']:50} · '{p['section'][:50]}'"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
