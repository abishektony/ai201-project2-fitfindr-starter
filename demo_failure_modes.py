"""
demo_failure_modes.py

Milestone 5 — deliberately trigger every documented failure mode and show that
the agent recovers gracefully (an informative string, never a Python exception).

Run it live for your demo video:

    python demo_failure_modes.py
"""

from agent import run_agent
from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


def banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


# ── Failure 1: search_listings returns zero results ─────────────────────────
banner("FAILURE 1 — search_listings: no listing matches the query")
raw = search_listings("designer ballgown", size="XXS", max_price=5)
print(f"search_listings(...) returned: {raw!r}")
print(f"  → empty list, no exception: {raw == []}")

print("\nSame impossible query through the full agent:")
session = run_agent("designer ballgown size XXS under $5", get_example_wardrobe())
print(f"  error     : {session['error']}")
print(f"  fit_card  : {session['fit_card']}   (stays None — downstream tools skipped)")


# ── Failure 2: suggest_outfit with an empty wardrobe ────────────────────────
banner("FAILURE 2 — suggest_outfit: empty wardrobe (new user, no closet)")
results = search_listings("vintage graphic tee", size=None, max_price=50)
advice = suggest_outfit(results[0], get_empty_wardrobe())
print(f"Item: {results[0]['title']}")
print(f"Returned a non-empty string: {bool(advice.strip())}")
print(f"General styling advice:\n  {advice}")


# ── Failure 3: create_fit_card with an empty outfit string ──────────────────
banner("FAILURE 3 — create_fit_card: missing/empty outfit input")
card = create_fit_card("", results[0])
print(f"create_fit_card('', item) returned a string: {isinstance(card, str)}")
print(f"Descriptive error message:\n  {card}")

banner("All three failure modes handled gracefully — no exceptions raised.")
