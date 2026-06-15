"""
app.py

Gradio interface for FitFindr. The layout and wiring are already set up —
your job is to fill in handle_query() so it calls run_agent() and maps
the session results to the three output panels.

Run with:
    python app.py

Then open the localhost URL shown in your terminal (usually http://localhost:7860,
but check your terminal — the port may differ).
"""

import gradio as gr

from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe
from utils.profile import load_profile, save_wardrobe_as_profile


# ── wardrobe selection ──────────────────────────────────────────────────────

WARDROBE_CHOICES = [
    "Example wardrobe",
    "Empty wardrobe (new user)",
    "My saved profile",
]


def _resolve_wardrobe(wardrobe_choice: str) -> tuple[dict, list]:
    """Map the radio choice to a (wardrobe, style_preferences) pair."""
    if wardrobe_choice == "Empty wardrobe (new user)":
        return get_empty_wardrobe(), []
    if wardrobe_choice == "My saved profile":
        profile = load_profile()
        wardrobe = profile["wardrobe"] if profile["wardrobe"]["items"] else get_empty_wardrobe()
        return wardrobe, profile["style_preferences"]
    return get_example_wardrobe(), []


# ── query handler ─────────────────────────────────────────────────────────────

def handle_query(user_query: str, wardrobe_choice: str) -> tuple[str, str, str]:
    """
    Called by Gradio when the user submits a query.

    Args:
        user_query:     The text the user typed into the search box.
        wardrobe_choice: Either "Example wardrobe" or "Empty wardrobe (new user)".

    Returns:
        A tuple of three strings:
            (listing_text, outfit_suggestion, fit_card)
        Each string maps to one of the three output panels in the UI.

    TODO:
        1. Guard against an empty query (return early with an error message).
        2. Select the wardrobe based on wardrobe_choice.
        3. Call run_agent() with the query and selected wardrobe.
        4. If session["error"] is set, return the error in the first panel
           and empty strings for the other two.
        5. Otherwise, format session["selected_item"] into a readable listing_text
           string and return it along with session["outfit_suggestion"] and
           session["fit_card"].
    """
    # 1. Guard against an empty query.
    if not user_query or not user_query.strip():
        return "Please type what you're looking for first.", "", ""

    # 2. Pick the wardrobe (and any saved style preferences).
    wardrobe, style_preferences = _resolve_wardrobe(wardrobe_choice)

    # 3. Run the agent.
    session = run_agent(
        query=user_query,
        wardrobe=wardrobe,
        style_preferences=style_preferences,
    )

    # 4. Early exit on error (includes the trending suggestion from the agent).
    if session["error"]:
        return session["error"], "", ""

    # 5. Format the selected listing for the first panel.
    item = session["selected_item"]
    colors = ", ".join(item.get("colors", [])) or "—"
    tags = ", ".join(item.get("style_tags", [])) or "—"

    header_lines = []
    # Stretch: note any constraints the retry/fallback relaxed to find this.
    if session["adjustments"]:
        header_lines.append(
            "ℹ️ No exact match, so I loosened "
            + " and ".join(session["adjustments"])
            + ".\n"
        )

    listing_text = (
        "".join(header_lines)
        + f"{item.get('title', 'Untitled')}\n"
        f"${item.get('price', 0):.0f}  ·  {item.get('platform', '?')}\n\n"
        f"Brand:     {item.get('brand') or 'Unbranded'}\n"
        f"Category:  {item.get('category', '?')}\n"
        f"Size:      {item.get('size', '?')}\n"
        f"Condition: {item.get('condition', '?')}\n"
        f"Colors:    {colors}\n"
        f"Style:     {tags}\n\n"
        f"{item.get('description', '')}"
    )

    # Stretch: price-fairness check.
    assessment = session.get("price_assessment")
    if assessment and assessment.get("summary"):
        listing_text += f"\n\n💸 Price check: {assessment['summary']}"

    # Stretch: trending styles in this size range.
    if session.get("trending"):
        tags_str = ", ".join(t["tag"] for t in session["trending"][:5])
        listing_text += f"\n\n🔥 Trending now: {tags_str}"

    return listing_text, session["outfit_suggestion"], session["fit_card"]


# ── save-profile handler (stretch: style profile memory) ─────────────────────

def handle_save_profile(wardrobe_choice: str) -> str:
    """Persist the currently-selected wardrobe as the user's saved profile."""
    if wardrobe_choice == "Empty wardrobe (new user)":
        return "Nothing to save — pick a wardrobe with items first."
    wardrobe, _ = _resolve_wardrobe(wardrobe_choice)
    if not wardrobe["items"]:
        return "Nothing to save — that wardrobe is empty."
    profile = save_wardrobe_as_profile(wardrobe)
    prefs = ", ".join(profile["style_preferences"]) or "none detected"
    return (
        f"✅ Saved your profile ({len(wardrobe['items'])} items). "
        f"Learned style preferences: {prefs}. "
        "Select 'My saved profile' next time to reuse it."
    )


# ── interface ─────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "black combat boots size 8",
    "designer ballgown size XXS under $5",   # deliberate no-results test
]

def build_interface():
    with gr.Blocks(title="FitFindr") as demo:
        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
        """)

        with gr.Row():
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            wardrobe_choice = gr.Radio(
                choices=WARDROBE_CHOICES,
                value="Example wardrobe",
                label="Wardrobe",
                scale=1,
            )

        with gr.Row():
            submit_btn = gr.Button("Find it", variant="primary", scale=3)
            save_btn = gr.Button("💾 Save as my profile", scale=1)

        profile_status = gr.Markdown("")

        with gr.Row():
            listing_output = gr.Textbox(
                label="🛍️ Top listing found",
                lines=8,
                interactive=False,
            )
            outfit_output = gr.Textbox(
                label="👗 Outfit idea",
                lines=8,
                interactive=False,
            )
            fitcard_output = gr.Textbox(
                label="✨ Your fit card",
                lines=8,
                interactive=False,
            )

        submit_btn.click(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice],
            outputs=[listing_output, outfit_output, fitcard_output],
        )
        query_input.submit(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice],
            outputs=[listing_output, outfit_output, fitcard_output],
        )
        save_btn.click(
            fn=handle_save_profile,
            inputs=[wardrobe_choice],
            outputs=[profile_status],
        )

    return demo


if __name__ == "__main__":
    demo = build_interface()
    demo.launch()
