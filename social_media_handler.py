"""
social_media_handler.py — Detects social media platform queries and returns
data-driven formatted responses.

All platform data (URLs, descriptions, emojis) is loaded from
social_media_data.json so the bot never invents or hallucinates links.

Usage example:
    from social_media_handler import SocialMediaHandler
    handler = SocialMediaHandler()
    response = handler.handle("what is his instagram?")
    # Returns a formatted string or None if the message is not a social media query.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Data file path
# ---------------------------------------------------------------------------

_DATA_PATH = os.path.join(os.path.dirname(__file__), "social_media_data.json")

# ---------------------------------------------------------------------------
# SocialMediaHandler
# ---------------------------------------------------------------------------


class SocialMediaHandler:
    """
    Detects social media platform queries and returns formatted responses
    sourced entirely from social_media_data.json.

    Attributes
    ----------
    data : dict
        Full contents of social_media_data.json.
    """

    def __init__(self, data_path: str = _DATA_PATH) -> None:
        with open(data_path, encoding="utf-8") as f:
            self.data: dict = json.load(f)

        # Build a flat keyword → platform dict for O(1) look-up per keyword
        self._kw_map: dict[str, dict] = {}
        for platform in self.data.get("platforms", []):
            for kw in platform.get("keywords", []):
                self._kw_map[kw.lower()] = platform

        # Pre-compile the wildcard query patterns into regexes
        self._query_regexes: list[re.Pattern] = [
            _wildcard_to_regex(p)
            for p in self.data.get("social_query_patterns", [])
        ]

        # All-platforms trigger phrases (lower-cased for fast membership test)
        self._all_triggers: list[str] = [
            t.lower() for t in self.data.get("all_platforms_triggers", [])
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def handle(self, text: str) -> Optional[str]:
        """
        Return a formatted platform response if *text* is a social media
        query, or ``None`` if the message is not a social media query.

        Parameters
        ----------
        text : str
            Raw incoming message from the user.

        Returns
        -------
        str or None
            Formatted response string, or None if no match.
        """
        t = (text or "").strip().lower()
        if not t:
            return None

        # 1. Check for "all platforms" / comprehensive social-media queries
        if self._is_all_platforms_query(t):
            return self._format_all_platforms()

        # 2. Check for a specific platform query
        platform = self._detect_platform_query(t)
        if platform:
            return self._format_single_platform(platform)

        return None

    def is_social_query(self, text: str) -> bool:
        """Return True if *text* is a social media query (any platform or all)."""
        t = (text or "").strip().lower()
        if not t:
            return False
        return self.is_all_platforms_query(t) or self._detect_platform_query(t) is not None

    def is_all_platforms_query(self, text: str) -> bool:
        """
        Return True if *text* is asking about all platforms / social media in general.

        Does NOT fire when the user mentions a specific platform by name —
        specific queries take priority.
        """
        t = (text or "").strip().lower()
        if not t:
            return False
        return self._is_all_platforms_query(t)

    def get_platform_by_id(self, platform_id: str) -> Optional[dict]:
        """Return the platform dict for the given id, or None."""
        for p in self.data.get("platforms", []):
            if p.get("id") == platform_id:
                return p
        return None

    # ------------------------------------------------------------------
    # Detection helpers
    # ------------------------------------------------------------------

    def _is_all_platforms_query(self, text: str) -> bool:
        """
        Return True if *text* is asking about all platforms / social media in general.

        Does NOT fire when the user mentions a specific platform by name —
        specific queries take priority.
        """
        for trigger in self._all_triggers:
            if " " in trigger:
                if trigger in text:
                    return True
            else:
                if re.search(r"\b" + re.escape(trigger) + r"\b", text):
                    return True
        return False

    def _detect_platform_query(self, text: str) -> Optional[dict]:
        """
        Return the platform dict if *text* is a social media query about a
        specific platform, or None.

        Detection strategy (in order):
        1. The text matches one of the social_query_patterns from the JSON *and*
           contains a known platform keyword.
        2. The text contains a known platform keyword AND both a question signal
           AND a possessive/contextual word (e.g. "his", "lucas", "he", "him").
           This prevents generic statements like "what is instagram?" from firing.
        """
        platform = self._find_platform_in_text(text)
        if not platform:
            return None

        # Strategy 1 — structured query pattern match
        for pattern_re in self._query_regexes:
            if pattern_re.search(text):
                return platform

        # Strategy 2 — platform keyword + question signal + possessive context
        # Requires a word that anchors the query to Lucas ("his", "he", "lucas",
        # "him") to avoid false-positives on generic questions about the platform.
        if _has_question_signal(text) and _has_possessive_context(text):
            return platform

        return None

    def _find_platform_in_text(self, text: str) -> Optional[dict]:
        """
        Return the first platform whose keywords appear in *text* (word boundary),
        or None.  Multi-word keywords are checked first to avoid partial matches.
        """
        # Sort by keyword length (longest first) to prefer multi-word matches
        sorted_kws = sorted(self._kw_map.keys(), key=lambda k: (-len(k), k))

        for kw in sorted_kws:
            if " " in kw:
                if kw in text:
                    return self._kw_map[kw]
            else:
                if re.search(r"\b" + re.escape(kw) + r"\b", text):
                    return self._kw_map[kw]
        return None

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_single_platform(self, platform: dict) -> str:
        """
        Return a neat, formatted response for *platform*.

        Format:
            {emoji} **{Name}**
            {description}
            {url}

            Want links to his other platforms? Just ask! 🙌
        """
        emoji = platform.get("emoji", "🔗")
        name = platform["display_name"]
        desc = platform.get("description", "")

        if platform.get("is_handle"):
            link_line = platform["url"]
        elif "free_url" in platform and "paid_url" in platform:
            link_line = (
                f"Free: {platform['free_url']}\n"
                f"Paid: {platform['paid_url']}"
            )
        else:
            link_line = platform.get("url", "")

        lines = [
            f"{emoji} **{name}**",
        ]
        if desc:
            lines.append(desc)
        lines.append(link_line)
        lines.append("")
        lines.append("Want links to his other platforms? Just ask! 🙌")
        return "\n".join(lines)

    def _format_all_platforms(self) -> str:
        """
        Return a formatted response listing all platforms with descriptions and links.
        """
        platforms = self.data.get("platforms", [])
        lines = ["Here's where you can find Lucas! 🌐\n"]
        for p in platforms:
            lines.append(self._format_platform_entry(p))
        lines.append("\nAsk about any specific platform for more details! 😊")
        return "\n".join(lines)

    def _format_platform_entry(self, platform: dict) -> str:
        """Return a single-line summary for a platform (for the all-platforms list)."""
        emoji = platform.get("emoji", "🔗")
        name = platform["display_name"]
        desc = platform.get("description", "")

        if platform.get("is_handle"):
            link_part = platform["url"]
        elif "free_url" in platform and "paid_url" in platform:
            link_part = (
                f"Free: {platform['free_url']}  |  Paid: {platform['paid_url']}"
            )
        else:
            link_part = platform.get("url", "")

        return f"{emoji} **{name}**: {desc} — {link_part}"


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_handler_instance: Optional[SocialMediaHandler] = None


def get_handler() -> SocialMediaHandler:
    """Return the module-level SocialMediaHandler singleton."""
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = SocialMediaHandler()
    return _handler_instance


# ---------------------------------------------------------------------------
# Convenience functions (thin wrappers around the singleton)
# ---------------------------------------------------------------------------


def handle_social_query(text: str) -> Optional[str]:
    """
    Return a formatted platform response if *text* is a social media query,
    or ``None`` otherwise.

    This is the primary entry point for external callers.
    """
    return get_handler().handle(text)


def is_social_query(text: str) -> bool:
    """Return True if *text* is a social media platform query."""
    return get_handler().is_social_query(text)


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------


def _wildcard_to_regex(pattern: str) -> re.Pattern:
    r"""
    Convert a wildcard pattern (``*`` = one or more words) into a compiled
    ``re.Pattern``.

    The ``*`` wildcard is replaced with ``\s+\S+.*?`` when the pattern has
    text both before and after it, allowing one or more words in between.
    When the wildcard is only at the end, it becomes ``\s+\S+``.

    Examples::

        "what is his *"  ->  re.compile(r"what\ is\ his\s+\S+")
        "his * link"     ->  re.compile(r"his\s+\S+.*?link")
    """
    parts = pattern.lower().split("*")
    if len(parts) == 1:
        # No wildcard — exact phrase match (word-boundary safe)
        return re.compile(re.escape(pattern.lower()))

    before = re.escape(parts[0].strip())
    after = re.escape(parts[1].strip()) if len(parts) > 1 else ""

    if before and after:
        regex = before + r"\s+\S+.*?" + after
    elif before:
        regex = before + r"\s+\S+"
    elif after:
        regex = r"\S+\s+" + after
    else:
        regex = r"\S+"

    return re.compile(regex)


def _has_question_signal(text: str) -> bool:
    """
    Return True if *text* contains a question mark or an interrogative word
    that signals a query intent.
    """
    if "?" in text:
        return True
    interrogatives = [
        "what", "where", "does", "is", "can", "could", "would",
        "how", "which", "who",
    ]
    words = text.split()
    if words and words[0] in interrogatives:
        return True
    return False


def _has_possessive_context(text: str) -> bool:
    """
    Return True if *text* contains a word that anchors the query to Lucas,
    preventing generic questions about a platform (e.g. "what is instagram?")
    from being treated as queries about Lucas's account.
    """
    possessive_words = ["his", "he", "him", "lucas"]
    words = re.findall(r"\b\w+\b", text)
    return any(w in possessive_words for w in words)
