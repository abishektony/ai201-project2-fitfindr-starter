"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Model used for all LLM-backed tools. llama-3.3-70b-versatile is a solid,
# widely-available Groq model for short generative tasks like styling advice
# and captions.
_MODEL = "llama-3.3-70b-versatile"

# Words that carry no signal when scoring keyword overlap.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "in", "on", "of", "to",
    "i", "im", "i'm", "am", "looking", "want", "need", "find", "something",
    "some", "any", "my", "me", "under", "size", "price", "cheap", "please",
    "that", "this", "is", "are", "it", "out", "there", "would", "how",
}


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _tokenize(text: str) -> list[str]:
    """Lowercase a string and split it into meaningful word tokens."""
    words = re.findall(r"[a-z0-9']+", text.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 1]


def _call_llm(prompt: str, temperature: float = 0.7, max_tokens: int = 400) -> str:
    """Send a single-turn prompt to the LLM and return the text response."""
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (response.choices[0].message.content or "").strip()


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()
    query_tokens = _tokenize(description or "")

    scored: list[tuple[int, dict]] = []
    for listing in listings:
        # 1. Price filter (inclusive).
        if max_price is not None and listing["price"] > max_price:
            continue

        # 2. Size filter — case-insensitive substring match so "M" matches
        #    "S/M" and "W30 L30" etc. Items with no size still pass when the
        #    user didn't ask for one.
        if size:
            listing_size = (listing.get("size") or "").lower()
            if size.lower() not in listing_size:
                continue

        # 3. Score by keyword overlap against the searchable text fields.
        haystack = " ".join([
            listing.get("title", ""),
            listing.get("description", ""),
            listing.get("category", ""),
            listing.get("brand") or "",
            " ".join(listing.get("style_tags", [])),
            " ".join(listing.get("colors", [])),
        ])
        listing_tokens = set(_tokenize(haystack))
        score = sum(1 for tok in query_tokens if tok in listing_tokens)

        # 4. Drop listings with no keyword overlap. If the user gave no
        #    keywords at all (only size/price filters), keep everything.
        if query_tokens and score == 0:
            continue

        scored.append((score, listing))

    # 5. Highest score first; ties keep dataset order (stable sort).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = (
        f"{new_item.get('title', 'this item')} "
        f"(category: {new_item.get('category', 'unknown')}, "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'}, "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'})"
    )

    items = (wardrobe or {}).get("items", [])

    if not items:
        # Empty wardrobe → general styling advice, no specific pieces to name.
        prompt = (
            "You are a friendly personal stylist. A shopper is considering this "
            f"secondhand item:\n\n{item_desc}\n\n"
            "They haven't told you what's in their closet yet. Give general "
            "styling advice for this piece: what kinds of items pair well with "
            "it, what vibe it suits, and one or two complete outfit directions "
            "they could build. Keep it to 3-5 sentences, warm and practical."
        )
    else:
        # Describe the wardrobe so the LLM can name specific pieces.
        wardrobe_lines = []
        for w in items:
            tags = ", ".join(w.get("style_tags", []))
            wardrobe_lines.append(
                f"- {w.get('name', 'item')} "
                f"({w.get('category', '?')}; {tags})"
            )
        wardrobe_text = "\n".join(wardrobe_lines)

        prompt = (
            "You are a friendly personal stylist. A shopper is considering this "
            f"secondhand item:\n\n{item_desc}\n\n"
            "Here is what's already in their wardrobe:\n"
            f"{wardrobe_text}\n\n"
            "Suggest 1-2 complete outfits that combine the new item with "
            "specific named pieces from their wardrobe above. Refer to the "
            "wardrobe pieces by name. Keep each outfit to a sentence or two and "
            "explain briefly why it works."
        )

    suggestion = _call_llm(prompt, temperature=0.7, max_tokens=400)

    # Never return an empty string — fall back to a minimal styling note.
    if not suggestion.strip():
        return (
            f"Style {new_item.get('title', 'this piece')} with simple basics — "
            "a clean top or bottom in a neutral color lets it stand out."
        )
    return suggestion


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # 1. Guard against missing/empty outfit input.
    if not outfit or not outfit.strip():
        return (
            "Error: no outfit suggestion was provided, so a fit card could not "
            "be created. Run suggest_outfit first."
        )

    title = new_item.get("title", "this find")
    price = new_item.get("price")
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "a steal"
    platform = new_item.get("platform", "secondhand")

    # 2. Build a caption prompt with the item details and outfit context.
    prompt = (
        "Write a short, shareable social-media caption (2-4 sentences) for a "
        "secondhand fashion find, like a real OOTD/thrift-haul post — casual, "
        "authentic, and a little excited. Do NOT sound like a product listing.\n\n"
        f"Item: {title}\n"
        f"Price: {price_str}\n"
        f"Platform: {platform}\n"
        f"Outfit it's styled in: {outfit}\n\n"
        "Mention the item name, the price, and the platform naturally — each "
        "exactly once. Capture the specific vibe of the outfit. A tasteful "
        "hashtag or two is fine. Return only the caption text."
    )

    # 3. Higher temperature so captions vary across runs/inputs.
    caption = _call_llm(prompt, temperature=0.95, max_tokens=200)

    if not caption.strip():
        return (
            f"Thrifted this {title} for {price_str} on {platform} and I'm "
            "obsessed — styled it up and it's an instant go-to. 🛍️"
        )
    return caption


# ── Tool 4: compare_price (stretch) ──────────────────────────────────────────

def compare_price(item: dict, listings: list[dict] | None = None) -> dict:
    """
    Estimate whether `item`'s price is fair relative to comparable listings.

    Comparables are other listings in the same category. If at least three share
    a style tag with the item, we narrow to those for a tighter comparison;
    otherwise we use the whole category.

    Args:
        item:     The selected listing dict (must have 'price' and 'category').
        listings: Optional pool of listings to compare against. Defaults to the
                  full dataset loaded from disk.

    Returns:
        A dict with:
            verdict          - "great deal" | "fair" | "overpriced" | "no comparables"
            item_price       - the item's price (float) or None
            comparable_count - number of comparables used
            median, min, max - price stats for the comparables (None if too few)
            summary          - a short human-readable sentence

    Never raises — if there aren't enough comparables, returns
    verdict="no comparables".
    """
    pool = listings if listings is not None else load_listings()
    price = item.get("price")
    item_id = item.get("id")
    category = item.get("category")
    item_tags = set(item.get("style_tags", []))

    if not isinstance(price, (int, float)):
        return {
            "verdict": "no comparables", "item_price": None,
            "comparable_count": 0, "median": None, "min": None, "max": None,
            "summary": "No price on this item, so it can't be compared.",
        }

    # Same category, excluding the item itself.
    same_cat = [
        l for l in pool
        if l.get("category") == category and l.get("id") != item_id
        and isinstance(l.get("price"), (int, float))
    ]
    # Tighten to style-tag overlap when we have enough of them.
    tag_matches = [l for l in same_cat if item_tags & set(l.get("style_tags", []))]
    comparables = tag_matches if len(tag_matches) >= 3 else same_cat

    prices = sorted(l["price"] for l in comparables)
    if len(prices) < 3:
        return {
            "verdict": "no comparables", "item_price": float(price),
            "comparable_count": len(prices), "median": None,
            "min": None, "max": None,
            "summary": (
                f"Only {len(prices)} comparable item(s) in the dataset — "
                "not enough to judge the price."
            ),
        }

    n = len(prices)
    median = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2

    # Classify against the median with a 15% tolerance band.
    if price <= median * 0.85:
        verdict = "great deal"
    elif price <= median * 1.15:
        verdict = "fair"
    else:
        verdict = "overpriced"

    summary = (
        f"This is priced at ${price:.0f}; similar {category} run "
        f"${prices[0]:.0f}–${prices[-1]:.0f} (median ${median:.0f}) "
        f"across {n} comparable listings — {verdict}."
    )
    return {
        "verdict": verdict, "item_price": float(price), "comparable_count": n,
        "median": float(median), "min": float(prices[0]), "max": float(prices[-1]),
        "summary": summary,
    }


# ── Tool 5: get_trending_styles (stretch) ────────────────────────────────────

def get_trending_styles(
    size: str | None = None,
    top_n: int = 5,
    listings: list[dict] | None = None,
) -> list[dict]:
    """
    Surface the most popular styles. There is no live external platform in this
    project, so "trending" is derived from style-tag frequency in the local
    dataset, optionally scoped to the user's size range.

    Args:
        size:     Optional size filter (case-insensitive substring, like search).
                  If no listings match the size, falls back to dataset-wide trends.
        top_n:    How many trending tags to return.
        listings: Optional pool; defaults to the full dataset.

    Returns:
        A list of {"tag": str, "count": int} dicts, most popular first.
        May be empty if there are no listings at all.
    """
    pool = listings if listings is not None else load_listings()

    scoped = pool
    if size:
        in_size = [l for l in pool if size.lower() in (l.get("size") or "").lower()]
        if in_size:  # only narrow if the size actually exists in the data
            scoped = in_size

    counts: dict[str, int] = {}
    for listing in scoped:
        for tag in listing.get("style_tags", []):
            counts[tag] = counts.get(tag, 0) + 1

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"tag": tag, "count": count} for tag, count in ranked[:top_n]]
