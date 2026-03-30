"""
knowledge_base_loader.py — Centralised loader and query interface for knowledge_base.json.

Provides a single, cached copy of the verified KB and clean query helpers so that
intent_router.py, response_formatter.py, and the main bot can all query Lucas's
verified facts without duplicating JSON-loading or parsing logic.

All data returned by these functions comes directly from knowledge_base.json, which
is the declared source of truth.  Zero hallucination risk.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

_KB_PATH: str = os.path.join(os.path.dirname(__file__), "knowledge_base.json")
_kb_cache: Optional[dict] = None


# ---------------------------------------------------------------------------
# Core loader
# ---------------------------------------------------------------------------

def load_knowledge_base() -> dict:
    """Load (and cache) knowledge_base.json.

    The file is read only once; subsequent calls return the cached dict.
    Raises FileNotFoundError or ValueError on missing/malformed file.
    """
    global _kb_cache
    if _kb_cache is None:
        try:
            with open(_KB_PATH, encoding="utf-8") as f:
                _kb_cache = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"knowledge_base_loader: 'knowledge_base.json' not found at '{_KB_PATH}'. "
                "Ensure knowledge_base.json is present in the bot directory."
            )
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"knowledge_base_loader: 'knowledge_base.json' is not valid JSON: {exc}"
            ) from exc
    return _kb_cache


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_lucas_intro() -> str:
    """Return Lucas's verified introductory description from who_is_lucas.description."""
    return load_knowledge_base()["who_is_lucas"]["description"]


def get_platform_info(platform_name: str) -> Optional[dict]:
    """Return the knowledge-base platform dict for *platform_name*, or None.

    Matches case-insensitively against the 'name' field of each platform
    in knowledge_base["platforms"]["primary"].  A partial substring match
    is accepted so callers can pass "chaturbate" or "onlyfans" directly.
    """
    kb = load_knowledge_base()
    name_lower = platform_name.lower()
    for platform in kb["platforms"]["primary"]:
        if name_lower in platform["name"].lower():
            return platform
    return None


def get_faq_answer(question_keyword: str) -> Optional[str]:
    """Return the best-matching FAQ answer for *question_keyword*, or None.

    Uses word-overlap scoring against FAQ questions.  Stop words are excluded
    from the overlap count so that short function words do not inflate the score.
    Requires at least 2 meaningful words in common before returning an answer.
    """
    kb = load_knowledge_base()
    stop_words = {
        "a", "an", "the", "is", "his", "he", "does",
        "what", "where", "can", "i", "you", "me", "my",
    }
    t_words = set(re.findall(r"[a-z]+", question_keyword.lower()))

    best_faq: Optional[dict] = None
    best_overlap = 0

    for faq in kb.get("faqs", []):
        q_words = set(re.findall(r"[a-z]+", faq["question"].lower()))
        overlap = len((t_words & q_words) - stop_words)
        if overlap > best_overlap:
            best_overlap = overlap
            best_faq = faq

    if best_faq and best_overlap >= 2:
        return best_faq["answer"]
    return None


def get_all_platforms_formatted() -> str:
    """Return all platforms as a formatted string with names, URLs, and contact info."""
    kb = load_knowledge_base()
    platforms = kb["platforms"]["primary"]
    contact = kb["platforms"]["contact"]

    lines = ["Here's where you can find Lucas:\n"]
    for p in platforms:
        lines.append(f"🔗 {p['name']}: {p['url']}")
    lines.append("\n💬 Contact Lucas:")
    lines.append(f"Telegram: {contact['telegram']}")
    lines.append(f"Discord: {contact['discord']}")
    return "\n".join(lines)


def search_knowledge_base(keyword: str) -> Optional[str]:
    """Search the knowledge base for *keyword* across FAQs, platforms, and activity data.

    Search order:
      1. FAQ word-overlap match (via get_faq_answer)
      2. Platform name match (via get_platform_info)
      3. Activity/frequency keyword shortcut → FAQ index 3
      4. Contact keyword shortcut → FAQ index 4

    Returns a descriptive string when a match is found, or None when nothing
    in the knowledge base is relevant to the keyword.
    """
    # 1. FAQ match
    answer = get_faq_answer(keyword)
    if answer:
        return answer

    # 2. Platform name match
    platform = get_platform_info(keyword)
    if platform:
        content = platform.get("content_type", "")
        url = platform["url"]
        return f"{platform['name']}: {content} — {url}" if content else f"{platform['name']}: {url}"

    # 3. Activity / frequency shortcut — match against FAQ question text
    kb = load_knowledge_base()
    kw_lower = keyword.lower()
    if any(w in kw_lower for w in ["active", "activity", "often", "frequency", "how much"]):
        for faq in kb.get("faqs", []):
            if any(w in faq["question"].lower() for w in ["active", "activity", "often", "frequency"]):
                return faq["answer"]

    # 4. Contact shortcut — match against FAQ question text
    if any(w in kw_lower for w in ["contact", "reach", "message", "talk to"]):
        for faq in kb.get("faqs", []):
            if "contact" in faq["question"].lower():
                return faq["answer"]

    return None
