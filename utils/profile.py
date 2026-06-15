"""
utils/profile.py  (stretch: style profile memory)

Persists a user's style profile across sessions so they don't have to
re-describe their wardrobe or taste every time. The profile is a single JSON
file on disk:

    {
      "style_preferences": ["streetwear", "y2k", ...],
      "wardrobe": {"items": [...]}        # same shape as the wardrobe schema
    }

All functions are safe to call when the file doesn't exist yet — load_profile()
returns an empty profile rather than raising.
"""

import json
import os

# Stored alongside the dataset. Listed in .gitignore so personal data isn't
# committed.
_PROFILE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "user_profile.json"
)


def _empty_profile() -> dict:
    return {"style_preferences": [], "wardrobe": {"items": []}}


def load_profile() -> dict:
    """
    Load the saved profile, or return an empty profile if none exists / the file
    is unreadable. Never raises.
    """
    try:
        with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _empty_profile()

    # Normalize shape so callers can rely on the keys.
    profile = _empty_profile()
    if isinstance(data.get("style_preferences"), list):
        profile["style_preferences"] = data["style_preferences"]
    if isinstance(data.get("wardrobe"), dict) and "items" in data["wardrobe"]:
        profile["wardrobe"] = data["wardrobe"]
    return profile


def save_profile(profile: dict) -> dict:
    """
    Persist a profile dict to disk and return the normalized profile that was
    written.
    """
    to_write = _empty_profile()
    to_write["style_preferences"] = list(profile.get("style_preferences", []))
    wardrobe = profile.get("wardrobe")
    if isinstance(wardrobe, dict) and "items" in wardrobe:
        to_write["wardrobe"] = wardrobe

    os.makedirs(os.path.dirname(_PROFILE_PATH), exist_ok=True)
    with open(_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(to_write, f, indent=2)
    return to_write


def save_wardrobe_as_profile(wardrobe: dict) -> dict:
    """
    Convenience: save the given wardrobe as the profile, deriving style
    preferences from the most common style tags across the wardrobe items.
    """
    counts: dict[str, int] = {}
    for item in wardrobe.get("items", []):
        for tag in item.get("style_tags", []):
            counts[tag] = counts.get(tag, 0) + 1
    preferences = [
        tag for tag, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ][:6]
    return save_profile({"style_preferences": preferences, "wardrobe": wardrobe})


def clear_profile() -> None:
    """Delete the saved profile file if it exists. Never raises."""
    try:
        os.remove(_PROFILE_PATH)
    except (FileNotFoundError, OSError):
        pass
