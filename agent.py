"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import json
import re

from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    compare_price,
    get_trending_styles,
    _call_llm,
)


# ── query parsing ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract a clean item description, optional size, and optional max_price from
    a free-form (possibly conversational) query.

    Strategy: ask the LLM to pull out the three fields as JSON, because users
    write things like "I'm looking for a vintage graphic tee under $30, I mostly
    wear baggy jeans..." where the buy intent is buried in a sentence. If the LLM
    call fails for any reason, fall back to the deterministic regex parser so the
    agent still works offline / without an API key.

    Examples:
        "vintage graphic tee under $30, size M"
            → {"description": "vintage graphic tee", "size": "M", "max_price": 30.0}
        "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans."
            → {"description": "vintage graphic tee", "size": None, "max_price": 30.0}
    """
    text = query or ""
    if not text.strip():
        return {"description": "", "size": None, "max_price": None}

    prompt = (
        "Extract secondhand-clothing search filters from the shopper's message. "
        "Return ONLY a JSON object with exactly these keys:\n"
        '  "description": a short noun phrase of the item they want to BUY '
        "(strip out price, size, and anything about what they already own),\n"
        '  "size": the requested size as a string, or null,\n'
        '  "max_price": the price ceiling as a number, or null.\n\n'
        f"Message: {text}\n\n"
        "JSON:"
    )
    try:
        raw = _call_llm(prompt, temperature=0.0, max_tokens=120)
        # Be forgiving about code fences / surrounding prose.
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        data = json.loads(match.group(0) if match else raw)
        description = (data.get("description") or "").strip()
        size = data.get("size")
        size = str(size).strip().upper() if size else None
        max_price = data.get("max_price")
        max_price = float(max_price) if max_price is not None else None
        if description:
            return {"description": description, "size": size, "max_price": max_price}
    except Exception:
        pass  # fall through to the regex parser below

    return _parse_query_regex(text)


def _parse_query_regex(query: str) -> dict:
    """
    Deterministic regex fallback parser (no LLM). Strips matched size/price
    fragments out of the description so they don't pollute the keyword search.
    """
    text = query or ""
    description = text

    # max_price: "under $30", "below 40", "less than $25", "$30", "max 50"
    max_price = None
    price_match = re.search(
        r"(?:under|below|less than|max(?:imum)?|up to|<)\s*\$?\s*(\d+(?:\.\d+)?)"
        r"|\$\s*(\d+(?:\.\d+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if price_match:
        raw = price_match.group(1) or price_match.group(2)
        max_price = float(raw)
        description = description.replace(price_match.group(0), " ")

    # size: "size M", "size 8", "in a size 10"
    size = None
    size_match = re.search(
        r"\b(?:in\s+)?(?:a\s+)?size\s+([a-z0-9]+(?:/[a-z0-9]+)?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if size_match:
        size = size_match.group(1).upper()
        description = description.replace(size_match.group(0), " ")

    # Clean up leftover punctuation/whitespace in the description.
    description = re.sub(r"\s+", " ", description).strip(" ,.-")

    return {"description": description, "size": size, "max_price": max_price}


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
        # ── stretch features ──
        "adjustments": [],           # constraints relaxed by the retry fallback
        "price_assessment": None,    # dict from compare_price
        "trending": [],              # list of {tag, count} from get_trending_styles
    }


# ── retry with loosened constraints (stretch) ──────────────────────────────────

def _search_with_fallback(parsed: dict) -> tuple[list[dict], list[str]]:
    """
    Run search_listings, and if it returns nothing, retry with progressively
    loosened constraints. Returns (results, adjustments) where `adjustments` is a
    human-readable list of what was relaxed to get those results (empty if the
    first, unmodified search already succeeded).

    Loosening order:
        1. drop the size filter
        2. drop the price ceiling
        3. drop both
    """
    desc, size, max_price = parsed["description"], parsed["size"], parsed["max_price"]

    # Attempt 0: exactly what the user asked for.
    results = search_listings(desc, size=size, max_price=max_price)
    if results:
        return results, []

    # Build the loosened attempts only for filters the user actually set.
    attempts = []
    if size and max_price is not None:
        attempts.append(((desc, None, max_price), ["the size filter"]))
        attempts.append(((desc, size, None), ["the price limit"]))
        attempts.append(((desc, None, None), ["the size filter and price limit"]))
    elif size:
        attempts.append(((desc, None, None), ["the size filter"]))
    elif max_price is not None:
        attempts.append(((desc, None, None), ["the price limit"]))

    for (d, s, p), adjustments in attempts:
        results = search_listings(d, size=s, max_price=p)
        if results:
            return results, adjustments

    return [], []


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict, style_preferences: list | None = None) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: fresh session.
    session = _new_session(query, wardrobe)

    # Guard: empty query.
    if not query or not query.strip():
        session["error"] = "Please describe what you're looking for."
        return session

    # Step 2: parse the query into search parameters.
    parsed = _parse_query(query)
    # Stretch (style profile memory): bias the search toward saved preferences
    # by folding them into the description keywords.
    if style_preferences:
        extra = " ".join(style_preferences)
        parsed = {**parsed, "description": f"{parsed['description']} {extra}".strip()}
    session["parsed"] = parsed

    # Stretch (trend awareness): note what's popular in the user's size range —
    # useful both as context and as a suggestion if the search comes up empty.
    session["trending"] = get_trending_styles(size=parsed["size"])

    # Step 3: search — with the retry/fallback loosening (stretch).
    results, adjustments = _search_with_fallback(parsed)
    session["search_results"] = results
    session["adjustments"] = adjustments

    # Branch: still nothing even after loosening → stop with a helpful message.
    if not results:
        bits = []
        if parsed["description"]:
            bits.append(f"\"{parsed['description']}\"")
        if parsed["size"]:
            bits.append(f"size {parsed['size']}")
        if parsed["max_price"] is not None:
            bits.append(f"under ${parsed['max_price']:.0f}")
        criteria = ", ".join(bits) if bits else "your search"
        msg = (
            f"No listings matched {criteria}, even after loosening the filters. "
            "Try a different style description or a higher price."
        )
        if session["trending"]:
            tags = ", ".join(t["tag"] for t in session["trending"][:3])
            msg += f" Popular right now in the dataset: {tags}."
        session["error"] = msg
        return session

    # Step 4: select the top-scoring result.
    session["selected_item"] = results[0]

    # Stretch (price comparison): is this a fair price vs. similar listings?
    session["price_assessment"] = compare_price(session["selected_item"])

    # Step 5: outfit suggestion.
    session["outfit_suggestion"] = suggest_outfit(
        new_item=session["selected_item"],
        wardrobe=wardrobe,
    )

    # Step 6: fit card caption.
    session["fit_card"] = create_fit_card(
        outfit=session["outfit_suggestion"],
        new_item=session["selected_item"],
    )

    # Step 7: done.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
