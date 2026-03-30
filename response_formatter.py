"""
response_formatter.py — Formats knowledge-base data into user-friendly responses.

All formatting functions source data from knowledge_base_loader so every response
is backed by verified facts from knowledge_base.json with zero hallucination risk.

Public API
----------
format_lucas_intro()              → Verified bio string ready to send.
format_platform_info(name)        → Name + content type + frequency + URL block.
format_all_platforms()            → Bulleted list of all platforms with details.
format_faq_answer(faq_entry)      → Plain answer text extracted from an FAQ dict.
"""

from __future__ import annotations

from typing import Optional

from knowledge_base_loader import (
    get_lucas_intro,
    get_platform_info,
    load_knowledge_base,
)


# ---------------------------------------------------------------------------
# Public formatters
# ---------------------------------------------------------------------------

def format_lucas_intro() -> str:
    """Return Lucas's verified bio as a formatted, ready-to-send intro string.

    Prefixes the raw bio with a contextual emoji and label so callers get a
    visually consistent result that differs from the bare loader return value.
    """
    return f"👤 {get_lucas_intro()}"


def format_platform_info(platform_name: str) -> str:
    """Return a formatted info block for *platform_name*.

    Includes the platform name, content type, posting frequency, and URL.
    Returns a helpful prompt when the platform is not found in the KB.
    """
    platform = get_platform_info(platform_name)
    if not platform:
        return (
            f"I don't have details for '{platform_name}'. "
            "Ask for 'all platforms' and I'll list everything!"
        )

    name = platform["name"]
    content = platform.get("content_type", "")
    freq = platform.get("frequency", "")
    url = platform.get("url", "")

    lines = [f"🔗 **{name}**"]
    if content:
        lines.append(f"Content: {content}")
    if freq:
        lines.append(f"Frequency: {freq}")
    if url:
        lines.append(f"Link: {url}")
    return "\n".join(lines)


def format_all_platforms() -> str:
    """Return a bulleted list of all platforms with emojis, descriptions, and links."""
    kb = load_knowledge_base()
    platforms = kb["platforms"]["primary"]
    contact = kb["platforms"]["contact"]

    lines = ["Lucas is active on these platforms:\n"]
    for p in platforms:
        content = p.get("content_type", "")
        freq = p.get("frequency", "")
        details = " — ".join(part for part in [content, freq] if part)
        url = p.get("url", "")
        entry = f"🔗 **{p['name']}**"
        if details:
            entry += f": {details}"
        entry += f"\n   {url}"
        lines.append(entry)

    lines.append(
        f"\n💬 Contact: Telegram {contact['telegram']} | Discord {contact['discord']}"
    )
    return "\n".join(lines)


def format_faq_answer(faq_entry: dict) -> str:
    """Return the answer text from an FAQ entry dict."""
    return faq_entry.get("answer", "")
