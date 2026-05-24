"""Quick classifier sanity check on the CLAUDE.md demo scenarios.

Runs each scenario through the classifier and prints the routing decision
+ token cost. Useful for verifying that prompt + tool schema produce sensible
routing.

Usage:
    uv run python scripts/test_classifier.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.classifier import classify  # noqa: E402

SCENARIOS = [
    "What's the minimum notice period to terminate someone in Germany?",
    "Process termination for João, last day Jan 31.",
    "Terminate Ana Müller with 2 weeks notice.",
    "Terminate Sarah Chen with 2 weeks notice.",
    "Convert Maria Santos from contractor to CLT.",
    "What severance is Carlos entitled to?",
    "What are our offboarding steps?",
]


def main() -> int:
    total = 0.0
    for i, q in enumerate(SCENARIOS, 1):
        print(f"--- Demo #{i} ---")
        print(f"Input: {q}")
        resp = classify(q)
        r = resp.result
        print(f"  agents: {r.agents_required}")
        print(
            f"  conflict_possible={r.conflict_possible}  "
            f"requires_action={r.requires_system_action}  "
            f"complexity={r.complexity}"
        )
        e = r.entities
        print(
            f"  entities: name={e.employee_name!r}  country={e.country!r}  "
            f"action={e.action_type!r}"
        )
        print(
            f"  cost: ${resp.cost_usd:.5f}  "
            f"(in={resp.input_tokens} out={resp.output_tokens})"
        )
        total += resp.cost_usd
        print()

    print(f"Total cost for {len(SCENARIOS)} classifications: ${total:.5f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
