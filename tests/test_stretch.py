"""
tests/test_stretch.py

Coverage for the four stretch features:
    A. Retry logic with fallback   (agent._search_with_fallback / run_agent)
    B. Style profile memory         (utils.profile)
    C. Trend awareness              (tools.get_trending_styles)
    D. Price comparison             (tools.compare_price)

LLM-backed steps in run_agent (query parsing, suggest_outfit, create_fit_card)
are monkeypatched so these tests are fast, deterministic, and need no API key.

Run with:  pytest -q
"""

import agent
import tools
from tools import compare_price, get_trending_styles
from utils import profile
from utils.data_loader import get_example_wardrobe


# ── small synthetic dataset so price/trend math is predictable ──────────────

FAKE_LISTINGS = [
    {"id": "a", "title": "Tee 1", "category": "tops", "style_tags": ["y2k"],
     "size": "M", "price": 10.0, "colors": [], "description": ""},
    {"id": "b", "title": "Tee 2", "category": "tops", "style_tags": ["y2k"],
     "size": "M", "price": 20.0, "colors": [], "description": ""},
    {"id": "c", "title": "Tee 3", "category": "tops", "style_tags": ["y2k"],
     "size": "L", "price": 30.0, "colors": [], "description": ""},
    {"id": "d", "title": "Tee 4", "category": "tops", "style_tags": ["grunge"],
     "size": "M", "price": 40.0, "colors": [], "description": ""},
    {"id": "e", "title": "Boot", "category": "shoes", "style_tags": ["grunge"],
     "size": "8", "price": 60.0, "colors": [], "description": ""},
]


# ── D. price comparison ──────────────────────────────────────────────────────

def test_compare_price_great_deal():
    """A price well below the comparable median → 'great deal'."""
    item = {"id": "x", "category": "tops", "style_tags": ["y2k"], "price": 8.0}
    result = compare_price(item, listings=FAKE_LISTINGS)
    assert result["verdict"] == "great deal"
    assert result["comparable_count"] >= 3
    assert result["median"] is not None


def test_compare_price_overpriced():
    """A price well above the comparable median → 'overpriced'."""
    item = {"id": "x", "category": "tops", "style_tags": ["y2k"], "price": 200.0}
    result = compare_price(item, listings=FAKE_LISTINGS)
    assert result["verdict"] == "overpriced"


def test_compare_price_no_comparables():
    """Too few comparables → 'no comparables', never raises."""
    item = {"id": "x", "category": "accessories", "style_tags": ["boho"], "price": 25.0}
    result = compare_price(item, listings=FAKE_LISTINGS)
    assert result["verdict"] == "no comparables"
    assert result["comparable_count"] < 3


def test_compare_price_missing_price():
    """An item with no numeric price is handled gracefully."""
    item = {"id": "x", "category": "tops", "style_tags": ["y2k"], "price": None}
    result = compare_price(item, listings=FAKE_LISTINGS)
    assert result["verdict"] == "no comparables"
    assert result["item_price"] is None


# ── C. trend awareness ───────────────────────────────────────────────────────

def test_trending_ranks_by_frequency():
    """Most common style tag comes first."""
    trends = get_trending_styles(listings=FAKE_LISTINGS, top_n=5)
    assert trends[0]["tag"] == "y2k"  # appears 3x, more than any other
    assert trends[0]["count"] == 3


def test_trending_scopes_to_size_then_falls_back():
    """Size filter narrows the pool; an absent size falls back to all listings."""
    only_l = get_trending_styles(size="L", listings=FAKE_LISTINGS)
    assert only_l[0]["tag"] == "y2k" and only_l[0]["count"] == 1

    # No listing has size ZZ → fall back to dataset-wide trends (non-empty).
    fallback = get_trending_styles(size="ZZ", listings=FAKE_LISTINGS)
    assert fallback and fallback[0]["tag"] == "y2k"


# ── A. retry logic with fallback ─────────────────────────────────────────────

def test_fallback_drops_size_when_no_exact_match():
    """size filter that matches nothing → loosened, results found, adjustment noted."""
    parsed = {"description": "graphic tee", "size": "ZZ", "max_price": 100.0}
    results, adjustments = agent._search_with_fallback(parsed)
    assert results, "expected results after loosening the size filter"
    assert adjustments == ["the size filter"]


def test_fallback_no_adjustment_when_first_search_succeeds():
    """A query that matches directly should report no adjustments."""
    parsed = {"description": "graphic tee", "size": None, "max_price": None}
    results, adjustments = agent._search_with_fallback(parsed)
    assert results
    assert adjustments == []


def test_run_agent_records_adjustments(monkeypatch):
    """Through run_agent: a loosened search populates session['adjustments']."""
    # Avoid real LLM calls for parse + styling steps.
    monkeypatch.setattr(
        agent, "_parse_query",
        lambda q: {"description": "graphic tee", "size": "ZZ", "max_price": 100.0},
    )
    monkeypatch.setattr(agent, "suggest_outfit", lambda new_item, wardrobe: "outfit")
    monkeypatch.setattr(agent, "create_fit_card", lambda outfit, new_item: "card")

    session = agent.run_agent("graphic tee size ZZ under $100", get_example_wardrobe())
    assert session["error"] is None
    assert session["adjustments"] == ["the size filter"]
    assert session["selected_item"] is not None
    assert session["price_assessment"] is not None  # price check attached
    assert session["trending"]                       # trending attached


def test_run_agent_still_fails_when_truly_impossible(monkeypatch):
    """If even loosened search finds nothing, the loop stops with an error."""
    monkeypatch.setattr(
        agent, "_parse_query",
        lambda q: {"description": "designer ballgown", "size": "XXS", "max_price": 5.0},
    )
    # These must NOT be reached on the no-results branch.
    monkeypatch.setattr(
        agent, "suggest_outfit",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    session = agent.run_agent("designer ballgown size XXS under $5", get_example_wardrobe())
    assert session["error"] is not None
    assert session["fit_card"] is None
    assert session["selected_item"] is None


# ── B. style profile memory ──────────────────────────────────────────────────

def test_profile_load_empty_when_missing(tmp_path, monkeypatch):
    """Loading with no file returns an empty profile, never raises."""
    monkeypatch.setattr(profile, "_PROFILE_PATH", str(tmp_path / "p.json"))
    loaded = profile.load_profile()
    assert loaded == {"style_preferences": [], "wardrobe": {"items": []}}


def test_profile_save_and_reload_roundtrip(tmp_path, monkeypatch):
    """Saving a wardrobe persists items and derives style preferences."""
    monkeypatch.setattr(profile, "_PROFILE_PATH", str(tmp_path / "p.json"))
    wardrobe = get_example_wardrobe()

    saved = profile.save_wardrobe_as_profile(wardrobe)
    assert saved["wardrobe"]["items"]
    assert saved["style_preferences"]  # derived from tag frequency

    reloaded = profile.load_profile()
    assert len(reloaded["wardrobe"]["items"]) == len(wardrobe["items"])
    assert reloaded["style_preferences"] == saved["style_preferences"]


def test_profile_clear(tmp_path, monkeypatch):
    """clear_profile removes the file and a subsequent load is empty."""
    monkeypatch.setattr(profile, "_PROFILE_PATH", str(tmp_path / "p.json"))
    profile.save_wardrobe_as_profile(get_example_wardrobe())
    profile.clear_profile()
    assert profile.load_profile()["wardrobe"]["items"] == []
