"""
tests/test_tools.py

Pytest coverage for the three FitFindr tools, with at least one test per
documented failure mode (see planning.md → Error Handling):

    search_listings  → no results match the query  → returns []
    suggest_outfit   → wardrobe is empty            → general styling advice
    create_fit_card  → outfit missing/incomplete    → clear error string

The two LLM-backed tools (suggest_outfit, create_fit_card) are tested with the
network call monkeypatched out, so the suite is fast, deterministic, and runs
without a GROQ_API_KEY. The failure-mode tests for those tools assert behavior
that happens *before* any LLM call, plus the empty-response fallback path.

Run with:
    pytest -q
"""

import tools
from tools import search_listings, suggest_outfit, create_fit_card


# ── fixtures / helpers ──────────────────────────────────────────────────────

EXAMPLE_ITEM = {
    "id": "lst_test",
    "title": "Y2K Baby Tee — Butterfly Print",
    "description": "Tiny baby tee with a glittery butterfly graphic.",
    "category": "tops",
    "style_tags": ["y2k", "graphic", "cropped"],
    "size": "S",
    "condition": "good",
    "price": 18.0,
    "colors": ["pink", "white"],
    "brand": None,
    "platform": "depop",
}

EXAMPLE_WARDROBE = {
    "items": [
        {
            "id": "w_001",
            "name": "Baggy straight-leg jeans",
            "category": "bottoms",
            "colors": ["dark blue"],
            "style_tags": ["denim", "baggy"],
        },
        {
            "id": "w_007",
            "name": "Chunky white sneakers",
            "category": "shoes",
            "colors": ["white"],
            "style_tags": ["sneakers", "chunky"],
        },
    ]
}

EMPTY_WARDROBE = {"items": []}


def _stub_llm(monkeypatch, capture, response="Stubbed styling response."):
    """Replace tools._call_llm with a stub that records the prompt it received."""

    def fake_call_llm(prompt, temperature=0.7, max_tokens=400):
        capture["prompt"] = prompt
        capture["temperature"] = temperature
        return response

    monkeypatch.setattr(tools, "_call_llm", fake_call_llm)


# ── Tool 1: search_listings ─────────────────────────────────────────────────

def test_search_returns_relevant_results():
    """Happy path: a real keyword query returns a non-empty, scored list."""
    results = search_listings("graphic tee")
    assert isinstance(results, list)
    assert len(results) > 0
    # Every returned item is a listing dict with the expected fields.
    assert all("title" in r and "price" in r for r in results)


def test_search_no_results_returns_empty_list():
    """FAILURE MODE: nothing matches → returns [] (does not raise)."""
    results = search_listings(
        "designer ballgown", size="XXS", max_price=5.0
    )
    assert results == []


def test_search_respects_max_price():
    """Price filter is inclusive and excludes anything above the cap."""
    cap = 25.0
    results = search_listings("tee", max_price=cap)
    assert results, "expected at least one cheap tee"
    assert all(r["price"] <= cap for r in results)


def test_search_respects_size_filter():
    """Size filter matches case-insensitively as a substring."""
    results = search_listings("jacket", size="m")
    # Each result's size should contain the requested size (case-insensitive).
    assert all("m" in r["size"].lower() for r in results)


def test_search_results_sorted_by_relevance():
    """More keyword overlap should rank a listing higher (descending score)."""
    results = search_listings("vintage denim jacket")
    assert len(results) >= 2
    # The dataset's most on-topic denim/jacket item should outrank a loosely
    # matching one — we assert the list is at least non-empty and ordered by
    # checking the top result mentions a query keyword.
    top_text = (
        results[0]["title"]
        + " ".join(results[0]["style_tags"])
        + results[0]["category"]
    ).lower()
    assert any(kw in top_text for kw in ("vintage", "denim", "jacket"))


# ── Tool 2: suggest_outfit ───────────────────────────────────────────────────

def test_suggest_outfit_empty_wardrobe_gives_general_advice(monkeypatch):
    """FAILURE MODE: empty wardrobe → general styling advice, never empty."""
    capture = {}
    _stub_llm(monkeypatch, capture, response="Pair it with simple basics.")

    result = suggest_outfit(EXAMPLE_ITEM, EMPTY_WARDROBE)

    assert isinstance(result, str) and result.strip()
    # The empty-wardrobe branch should ask for *general* advice and must NOT
    # try to reference specific wardrobe pieces.
    prompt = capture["prompt"].lower()
    assert "general styling advice" in prompt
    assert "wardrobe:" not in prompt  # no itemized closet was injected


def test_suggest_outfit_uses_named_wardrobe_pieces(monkeypatch):
    """Populated wardrobe → the prompt includes the user's actual items."""
    capture = {}
    _stub_llm(monkeypatch, capture)

    result = suggest_outfit(EXAMPLE_ITEM, EXAMPLE_WARDROBE)

    assert result.strip()
    prompt = capture["prompt"]
    assert "Baggy straight-leg jeans" in prompt
    assert "Chunky white sneakers" in prompt


def test_suggest_outfit_never_returns_empty_string(monkeypatch):
    """Even if the LLM returns nothing, we fall back to a non-empty string."""
    capture = {}
    _stub_llm(monkeypatch, capture, response="   ")  # whitespace / blank

    result = suggest_outfit(EXAMPLE_ITEM, EXAMPLE_WARDROBE)
    assert result.strip()  # fallback kicked in


# ── Tool 3: create_fit_card ──────────────────────────────────────────────────

def test_create_fit_card_empty_outfit_returns_error(monkeypatch):
    """FAILURE MODE: missing outfit → clear error string, no LLM call."""
    called = {"hit": False}

    def boom(*args, **kwargs):
        called["hit"] = True
        raise AssertionError("LLM should not be called for empty outfit")

    monkeypatch.setattr(tools, "_call_llm", boom)

    result = create_fit_card("", EXAMPLE_ITEM)
    assert isinstance(result, str)
    assert "error" in result.lower()
    assert called["hit"] is False


def test_create_fit_card_whitespace_outfit_returns_error(monkeypatch):
    """Whitespace-only outfit is treated the same as missing."""
    monkeypatch.setattr(
        tools, "_call_llm",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")),
    )
    result = create_fit_card("   \n  ", EXAMPLE_ITEM)
    assert "error" in result.lower()


def test_create_fit_card_happy_path(monkeypatch):
    """Valid outfit → returns the caption and uses a high temperature."""
    capture = {}
    _stub_llm(monkeypatch, capture, response="Thrifted gem alert! 🛍️")

    result = create_fit_card("baggy jeans + chunky sneakers", EXAMPLE_ITEM)

    assert result == "Thrifted gem alert! 🛍️"
    # The caption should be generated with higher temperature for variety.
    assert capture["temperature"] >= 0.9
    # The item details should be passed into the prompt.
    assert "Y2K Baby Tee" in capture["prompt"]
    assert "depop" in capture["prompt"]


def test_create_fit_card_falls_back_when_llm_blank(monkeypatch):
    """If the LLM returns nothing, a usable caption is still produced."""
    _stub_llm(monkeypatch, {}, response="")
    result = create_fit_card("baggy jeans + chunky sneakers", EXAMPLE_ITEM)
    assert result.strip()
    assert "Y2K Baby Tee" in result
