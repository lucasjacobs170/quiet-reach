"""
question_detector.py — Pattern-based question intent pre-detection.

Features:
  - Loads question patterns from question_patterns.json
  - Wildcard matching: "send me his *" matches "send me his instagram"
  - Platform alias resolution: "ig" → "instagram", "x" → "x"
  - Case-insensitive matching
  - Fuzzy matching for common typos (instgram, only fans, etc.)
  - Returns intent, confidence_boost, matched_pattern, entities, and priority

This pre-detector runs BEFORE the intent classifier to boost confidence for
natural-language questions that the keyword-based classifier may miss.
It follows the same design as insult_detector.py, using a JSON pattern
library as the single source of truth.
"""

from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from typing import Any

# ---------------------------------------------------------------------------
# Load patterns
# ---------------------------------------------------------------------------

_LIB_PATH = os.path.join(os.path.dirname(__file__), "question_patterns.json")

# ---------------------------------------------------------------------------
# Fuzzy match threshold for platform name typo detection
# ---------------------------------------------------------------------------
_FUZZY_THRESHOLD: float = 0.82


# ---------------------------------------------------------------------------
# QuestionDetector
# ---------------------------------------------------------------------------

class QuestionDetector:
    """
    Pattern-based pre-detector for question intent classification.

    Attributes
    ----------
    patterns_file : str
        Path to the question_patterns.json library.
    """

    def __init__(self, patterns_file: str = _LIB_PATH) -> None:
        with open(patterns_file, encoding="utf-8") as f:
            self._library: dict = json.load(f)

        self._platform_aliases: dict[str, str] = self._build_alias_map()
        self._compiled_patterns: list[dict] = self._compile_patterns()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_intent(self, message: str) -> dict[str, Any]:
        """
        Detect the question intent of *message* using pattern matching.

        Returns a dict with the following keys:

        .. code-block:: python

            {
                "intent":           "asks_for_platform_links",  # or "" if no match
                "confidence_boost": 0.25,
                "matched_pattern":  "send me his *",
                "entities":         {"platform": "x"},
                "priority":         1,
            }

        When no pattern matches, ``"intent"`` is an empty string.
        """
        if not message or not message.strip():
            return self._empty_result()

        t = message.lower().strip()

        best: dict[str, Any] | None = None

        for entry in self._compiled_patterns:
            if not self.match_pattern(t, entry["pattern"]):
                continue

            entities = self.extract_entities(t, entry)

            # Skip platform patterns that require an entity but found none
            if entry.get("entity_type") == "platform" and not entities.get("platform"):
                # Only skip if the pattern explicitly demands a platform match
                # (i.e. the wildcard is the main differentiator).  Patterns
                # without a wildcard (*) are exact and don't need an entity.
                if "*" in entry["pattern"]:
                    continue

            # Pick the highest-priority (lowest priority number) match;
            # break ties by highest confidence_boost.
            if best is None:
                best = self._make_result(entry, entities)
            else:
                if (entry["priority"] < best["priority"]) or (
                    entry["priority"] == best["priority"]
                    and entry["confidence_boost"] > best["confidence_boost"]
                ):
                    best = self._make_result(entry, entities)

        return best if best is not None else self._empty_result()

    def match_pattern(self, message: str, pattern: str) -> bool:
        """
        Return True if *message* (lower-cased) matches *pattern*.

        Supports a single ``*`` wildcard that matches one or more words.
        The ``*`` must be surrounded by whitespace or be at the end/start of
        the pattern.  Matching is case-insensitive.

        Examples::

            match_pattern("send me his instagram", "send me his *")  # True
            match_pattern("send me his x",          "send me his *")  # True
            match_pattern("what social media does lucas have", "what social media does lucas have")  # True
        """
        p = pattern.lower().strip()
        if "*" not in p:
            # Phrase match — use word boundaries to prevent "hi" from
            # triggering inside "his" or "this".
            return _word_boundary_contains(message, p)

        parts = p.split("*", 1)
        before = parts[0].strip()
        after = parts[1].strip() if len(parts) > 1 else ""

        if before and not _word_boundary_contains(message, before):
            return False

        if after:
            # Check the after-part appears after the before-part
            idx = message.find(before) + len(before) if before else 0
            remainder = message[idx:].strip()
            if not _word_boundary_contains(remainder, after):
                # Also check if "after" is at the end of the message
                if not message.endswith(after):
                    return False

        return True

    def extract_entities(self, message: str, pattern_entry: dict) -> dict[str, str]:
        """
        Extract named entities from *message* given a *pattern_entry*.

        Currently supports:
        - ``"platform"`` — returns the canonical platform ID (e.g. "instagram", "x")
        - ``"bot_capabilities"`` — signals a bot-meta query

        Returns a dict, e.g. ``{"platform": "instagram"}``.
        """
        entity_type = pattern_entry.get("entity_type")
        if not entity_type:
            return {}

        if entity_type == "platform":
            platform = self._extract_platform(message)
            if platform:
                return {"platform": platform}
            return {}

        if entity_type == "bot_capabilities":
            return {"type": "bot_capabilities"}

        return {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_alias_map(self) -> dict[str, str]:
        """
        Build a flat alias → canonical_id mapping from platform_aliases.

        Example output::

            {"instagram": "instagram", "insta": "instagram", "ig": "instagram", ...}
        """
        alias_map: dict[str, str] = {}
        for canonical_id, aliases in self._library.get("platform_aliases", {}).items():
            for alias in aliases:
                alias_map[alias.lower()] = canonical_id
        return alias_map

    def _compile_patterns(self) -> list[dict]:
        """
        Build a flat list of pattern entries with resolved category/intent info.
        """
        compiled: list[dict] = []
        for intent, cat_data in self._library.get("categories", {}).items():
            for pattern_entry in cat_data.get("patterns", []):
                compiled.append({
                    "intent":           intent,
                    "pattern":          pattern_entry["pattern"].lower().strip(),
                    "confidence_boost": float(pattern_entry.get("confidence_boost", 0.20)),
                    "priority":         int(pattern_entry.get("priority", 3)),
                    "entity_type":      pattern_entry.get("entity_type"),
                    "variations":       [v.lower() for v in pattern_entry.get("variations", [])],
                })
        # Sort by priority ascending (1 = highest priority) so iteration
        # exits early for the most important patterns.
        compiled.sort(key=lambda e: (e["priority"], -e["confidence_boost"]))
        return compiled

    def _extract_platform(self, message: str) -> str:
        """
        Return the canonical platform ID found in *message*, or ``""`` if none.

        Detection order:
        1. Multi-word aliases (e.g. "only fans", "x account") — checked first
           to avoid partial matches by single-word aliases.
        2. Single-word aliases (sorted longest-first to avoid "ig" matching
           before "instagram").
        3. Fuzzy matching against all known aliases for common typos.
        """
        t = message.lower()

        # Sort aliases: multi-word first, then single-word longest-first
        sorted_aliases = sorted(
            self._platform_aliases.items(),
            key=lambda kv: (-len(kv[0].split()), -len(kv[0]))
        )

        for alias, canonical in sorted_aliases:
            if " " in alias:
                if alias in t:
                    return canonical
            else:
                if re.search(r"\b" + re.escape(alias) + r"\b", t):
                    return canonical

        # Fuzzy fallback — catches typos like "instgram", "onlyfan"
        words = t.split()
        for word in words:
            if len(word) < 3:
                continue
            best_alias = ""
            best_ratio = 0.0
            for alias in self._platform_aliases:
                if len(alias) < 4:
                    continue  # Skip very short aliases in fuzzy matching
                ratio = SequenceMatcher(None, word, alias).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_alias = alias
            if best_ratio >= _FUZZY_THRESHOLD and best_alias:
                return self._platform_aliases[best_alias]

        return ""

    @staticmethod
    def _make_result(entry: dict, entities: dict) -> dict[str, Any]:
        return {
            "intent":           entry["intent"],
            "confidence_boost": entry["confidence_boost"],
            "matched_pattern":  entry["pattern"],
            "entities":         entities,
            "priority":         entry["priority"],
        }

    @staticmethod
    def _empty_result() -> dict[str, Any]:
        return {
            "intent":           "",
            "confidence_boost": 0.0,
            "matched_pattern":  "",
            "entities":         {},
            "priority":         0,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _word_boundary_contains(text: str, phrase: str) -> bool:
    """Return True if *phrase* appears in *text* at a word boundary."""
    if not phrase:
        return True
    if " " in phrase:
        return phrase in text
    return bool(re.search(r"\b" + re.escape(phrase) + r"\b", text))


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_detector_instance: QuestionDetector | None = None


def get_detector() -> QuestionDetector:
    """Return the module-level QuestionDetector singleton."""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = QuestionDetector()
    return _detector_instance
