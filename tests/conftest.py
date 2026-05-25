"""
Shared pytest configuration.

Adds the project root to sys.path so tests can import `agent.*`,
`mcp_servers.*`, and `scripts.*` modules directly.

Defines the `live_api` marker, used to opt OUT of API-dependent tests when no
key is configured. In CI (where ANTHROPIC_API_KEY is unset), live tests are
skipped automatically — so PRs run free, fast, and deterministically.
Locally with .env loaded, all tests run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env so local pytest runs have the API keys available.
# In CI, this is a no-op (no .env file present) and the live_api skip kicks in.
load_dotenv(PROJECT_ROOT / ".env", override=True)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_api: test requires live Anthropic API key. Skipped in CI.",
    )


skip_no_anthropic_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="requires ANTHROPIC_API_KEY (live API test)",
)
