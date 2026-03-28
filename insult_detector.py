"""
insult_detector.py — Pattern-based insult detection with fuzzy matching.

Features:
  - Loads insult patterns from insult_library.json
  - Leet speak normalization (0→o, 1→i, 3→e, 4→a, 5→s, 7→t, etc.)
  - Fuzzy matching via difflib to catch typos / minor variations
  - ALL CAPS boost: phrases typed entirely in uppercase in the "severe" category
    get an extra severity point added to the running score
  - Per-user hostility score tracking across a conversation
  - Blocks engagement when a user's cumulative score exceeds the configured threshold
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

# ---------------------------------------------------------------------------
# Load library
# ---------------------------------------------------------------------------

_LIB_PATH = os.path.join(os.path.dirname(__file__), "insult_library.json")

with open(_LIB_PATH, encoding="utf-8") as _f:
    _LIBRARY: dict = json.load(_f)

_LEET_MAP: dict[str, str] = _LIBRARY.get("leet_speak_map", {})
_SEVERITY_WEIGHTS: dict[str, int] = _LIBRARY.get("severity_weights", {"mild": 1, "moderate": 2, "severe": 4})
_THRESHOLDS: dict = _LIBRARY.get("thresholds", {"block_score": 10, "caps_severity_boost": True})
BLOCK_SCORE: int = int(_THRESHOLDS.get("block_score", 10))
CAPS_BOOST: bool = bool(_THRESHOLDS.get("caps_severity_boost", True))

# Fuzzy similarity threshold — tweak to taste (0.80 catches most single-char typos)
FUZZY_THRESHOLD: float = 0.80

# Minimum confidence for a match to be reported (below this the match is ignored)
MIN_CONFIDENCE: float = 0.7

# Words that are commonly misidentified as insults through fuzzy matching.
# Any word appearing in this set is excluded from the fuzzy-matching fallback
# so that innocent messages like "hello" cannot match against "hell".
_FUZZY_WHITELIST: frozenset[str] = frozenset({
    # "hell" false positives
    "hello", "shell", "shells", "shellfish", "well", "yell", "bell",
    "bells", "sell", "fell", "tell", "tells", "cell", "cells",
    # "damn" false positives
    "damp", "dame", "name",
    # "shit" false positives
    "shift", "shirt",
    # other common benign words
    "assassin", "classic", "assessment",
})

# Question words whose presence before a matched term signals a non-hostile context
_QUESTION_WORDS: frozenset = frozenset({
    "what", "how", "why", "when", "where", "who", "which", "whose", "whom"
})

# Negation words whose presence before a matched term signals benign intent
_NEGATION_WORDS: frozenset = frozenset({
    "not", "no", "never", "didnt", "didn't", "dont", "don't", "wasnt",
    "wasn't", "isnt", "isn't", "wont", "won't", "wouldnt", "wouldn't",
})

# ---------------------------------------------------------------------------
# Build flat pattern index: list of (canonical_phrase, severity, all_tokens)
# where all_tokens includes the phrase itself + all its listed variations.
# ---------------------------------------------------------------------------

@dataclass
class _PatternEntry:
    phrase: str
    severity: str
    category: str       # category label from the library
    tokens: list[str]   # phrase + all variations (already lowercased)


_PATTERNS: list[_PatternEntry] = []

for _cat_key, _cat_data in _LIBRARY["categories"].items():
    _cat_label = _cat_data.get("label", _cat_key)
    for _entry in _cat_data["entries"]:
        _phrase = _entry["phrase"].lower().strip()
        _variations = [v.lower().strip() for v in _entry.get("variations", [])]
        _tokens = list(dict.fromkeys([_phrase] + _variations))  # deduplicate, preserve order
        _PATTERNS.append(_PatternEntry(phrase=_phrase, severity=_entry["severity"], category=_cat_label, tokens=_tokens))

# Pre-compile word-boundary regex patterns for every normalised token to avoid
# recompiling the same pattern on every call to detect().
_WB_REGEX_CACHE: dict[str, re.Pattern] = {}

def _wb_pattern(token: str) -> re.Pattern:
    """Return a compiled word-boundary regex for *token* (cached)."""
    if token not in _WB_REGEX_CACHE:
        _WB_REGEX_CACHE[token] = re.compile(r'\b' + re.escape(token) + r'\b')
    return _WB_REGEX_CACHE[token]

# ---------------------------------------------------------------------------
# Per-user hostility score store (in-memory; intentionally lightweight)
# ---------------------------------------------------------------------------

_user_scores: dict[str, int] = {}


# ---------------------------------------------------------------------------
# Detection result
# ---------------------------------------------------------------------------

@dataclass
class MatchDetail:
    """Details of a single pattern match."""
    pattern: str
    category: str
    severity: str
    confidence: float
    position_in_text: int   # character offset of the matched token in normalized text
    matched_token: str      # the specific token/variation that matched


@dataclass
class InsultDetectionResult:
    detected: bool = False
    severity: str = "none"          # none | mild | moderate | severe
    score_delta: int = 0            # points added for this message
    matched_phrase: str = ""        # canonical phrase that triggered detection (best match)
    matched_token: str = ""         # specific token / variation that matched (best match)
    should_block: bool = False      # True if cumulative score >= threshold
    cumulative_score: int = 0       # running total for this user after this message
    # Rich fields for transcript logging
    all_matches: list[MatchDetail] = field(default_factory=list)
    leet_speak_conversions: list[str] = field(default_factory=list)
    all_caps: bool = False
    all_caps_ratio: float = 0.0
    normalized_text: str = ""
    detection_time_ms: float = 0.0


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_leet(text: str) -> str:
    """Replace common leet-speak characters with their letter equivalents."""
    return "".join(_LEET_MAP.get(ch, ch) for ch in text)


def normalize_text(text: str) -> str:
    """
    Prepare text for pattern matching:
      1. Replace leet-speak characters.
      2. Collapse repeated characters (e.g. "stuuupid" → "stupid").
      3. Strip punctuation except spaces and apostrophes.
      4. Lowercase.
      5. Normalize common abbreviations (u→you, ur→your/you're).
    """
    t = text.lower()
    t = normalize_leet(t)
    # Collapse 3+ repeated chars to 2 (helps with "stoooopid", "fuuuck", etc.)
    t = re.sub(r"(.)\1{2,}", r"\1\1", t)
    # Strip punctuation (keep spaces and apostrophes)
    t = re.sub(r"[^\w\s']", " ", t)
    # Normalize common chat abbreviations
    t = re.sub(r"\bur\b", "your", t)
    t = re.sub(r"\bu\b", "you", t)
    t = re.sub(r"\baf\b", "as fuck", t)
    t = re.sub(r"\bbtw\b", "by the way", t)
    # Collapse multiple spaces
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _is_all_caps(text: str) -> bool:
    """Return True if the text has letters and they are all uppercase."""
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


# ---------------------------------------------------------------------------
# Fuzzy similarity
# ---------------------------------------------------------------------------

def _caps_ratio(text: str) -> float:
    """Return the fraction of alphabetic characters that are uppercase."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _find_leet_conversions(original: str) -> list[str]:
    """Return a list of human-readable notes for leet-speak substitutions found."""
    conversions: list[str] = []
    for ch, replacement in _LEET_MAP.items():
        if ch in original.lower():
            conversions.append(f"'{ch}' → '{replacement}'")
    return conversions


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _token_matches(input_text: str, pattern_token: str) -> bool:
    """
    Return True if *pattern_token* appears as a whole-word match inside
    *input_text*.

    Word-boundary matching (`\\b`) is used so that short variations such as
    "fu" (a variation of "fuck you") cannot match inside innocent words like
    "useful" or "respectful".

    Fuzzy matching is kept as a fallback but is restricted to patterns of
    4+ characters to prevent short abbreviations from generating false
    positives on dissimilar words.

    For single-word patterns the fuzzy comparison is done word-by-word against
    the tokens of *input_text* rather than against the full string.  This
    prevents "hello" from fuzzy-matching "hell" (the words are compared
    individually and "hello" appears in the ``_FUZZY_WHITELIST``).
    """
    # Whole-word exact match via word boundaries (uses cache)
    if _wb_pattern(pattern_token).search(input_text):
        return True
    # Fuzzy fallback: only for patterns long enough to be meaningful
    if len(pattern_token) < 4:
        return False

    if " " not in pattern_token:
        # Single-word pattern: compare each word in the text individually.
        # This prevents short benign words from matching offensive short
        # tokens just because their lengths are similar.
        for word in input_text.split():
            if word in _FUZZY_WHITELIST:
                continue
            max_len = max(len(word), len(pattern_token))
            if max_len == 0:
                continue
            len_ratio = min(len(word), len(pattern_token)) / max_len
            if len_ratio < 0.5:
                continue
            if _similarity(word, pattern_token) >= FUZZY_THRESHOLD:
                return True
        return False

    # Multi-word pattern: compare against the full normalised text
    max_len = max(len(input_text), len(pattern_token))
    if max_len == 0:
        return False
    len_ratio = min(len(input_text), len(pattern_token)) / max_len
    if len_ratio < 0.5:
        return False
    return _similarity(input_text, pattern_token) >= FUZZY_THRESHOLD


def _is_question_context(normalized: str, pattern_token: str) -> bool:
    """
    Return True if *pattern_token* appears in a benign (non-hostile) context:

    - **Question context**: a question word (what, how, why, etc.) precedes the
      matched term within five tokens.
      Example: "what do you mean?" → "mean" follows "what" → not hostile.

    - **Negation context**: a negation word (not, didn't, don't, etc.) precedes
      the matched term within five tokens.
      Example: "I did not mean to sound annoyed" → "not" before "mean" → not hostile.
    """
    tokens = normalized.split()
    pattern_parts = pattern_token.split()
    if not pattern_parts:
        return False
    first_part = pattern_parts[0]
    for i, tok in enumerate(tokens):
        if tok == first_part:
            look_back = tokens[max(0, i - 5):i]
            if any(w in _QUESTION_WORDS for w in look_back):
                return True
            if any(w in _NEGATION_WORDS for w in look_back):
                return True
    return False


# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------

def detect(text: str, user_key: str = "") -> InsultDetectionResult:
    """
    Scan *text* for insults from the library.

    Parameters
    ----------
    text : str
        The raw message from the user.
    user_key : str
        An opaque identifier for the user (e.g. platform + user ID).
        Used to accumulate per-user hostility scores.  Pass an empty string
        to skip score tracking.

    Returns
    -------
    InsultDetectionResult
    """
    _start = time.monotonic()

    if not text or not text.strip():
        return InsultDetectionResult()

    all_caps = _is_all_caps(text.strip())
    caps_ratio = _caps_ratio(text.strip())
    normalized = normalize_text(text)
    leet_conversions = _find_leet_conversions(text)

    best_severity = "none"
    best_phrase = ""
    best_token = ""
    all_matches: list[MatchDetail] = []

    for entry in _PATTERNS:
        for token in entry.tokens:
            norm_token = normalize_text(token)
            if _token_matches(normalized, norm_token):
                # Compute confidence: word-boundary exact match = 1.0,
                # fuzzy fallback = similarity ratio
                wb_match = _wb_pattern(norm_token).search(normalized)
                if wb_match:
                    confidence = 1.0
                else:
                    confidence = _similarity(normalized, norm_token)

                # Skip low-confidence token matches; try the next variation
                if confidence < MIN_CONFIDENCE:
                    continue

                # Skip token matches that appear in a benign context (question/negation);
                # try the next variation in case a more explicit one also appears
                if _is_question_context(normalized, norm_token):
                    continue

                # Find position of matched token in normalized text (best effort)
                pos = wb_match.start() if wb_match else 0

                all_matches.append(MatchDetail(
                    pattern=entry.phrase,
                    category=entry.category,
                    severity=entry.severity,
                    confidence=round(confidence, 4),
                    position_in_text=pos,
                    matched_token=token,
                ))

                # Keep the highest-severity match as the primary result
                if _severity_rank(entry.severity) > _severity_rank(best_severity):
                    best_severity = entry.severity
                    best_phrase = entry.phrase
                    best_token = token
                break  # found a match for this entry; no need to check more tokens

    detection_time_ms = (time.monotonic() - _start) * 1000

    if best_severity == "none":
        return InsultDetectionResult(
            all_caps=all_caps,
            all_caps_ratio=caps_ratio,
            normalized_text=normalized,
            leet_speak_conversions=leet_conversions,
            detection_time_ms=round(detection_time_ms, 3),
        )

    # Compute base score delta
    score_delta = _SEVERITY_WEIGHTS.get(best_severity, 1)

    # ALL CAPS boost: severe messages shouted in full caps get an extra point
    if CAPS_BOOST and all_caps and best_severity == "severe":
        score_delta += 1

    # Update per-user cumulative score
    if user_key:
        _user_scores[user_key] = _user_scores.get(user_key, 0) + score_delta
        cumulative = _user_scores[user_key]
    else:
        cumulative = score_delta

    should_block = cumulative >= BLOCK_SCORE

    return InsultDetectionResult(
        detected=True,
        severity=best_severity,
        score_delta=score_delta,
        matched_phrase=best_phrase,
        matched_token=best_token,
        should_block=should_block,
        cumulative_score=cumulative,
        all_matches=all_matches,
        leet_speak_conversions=leet_conversions,
        all_caps=all_caps,
        all_caps_ratio=caps_ratio,
        normalized_text=normalized,
        detection_time_ms=round(detection_time_ms, 3),
    )


def get_user_score(user_key: str) -> int:
    """Return the current cumulative hostility score for a user."""
    return _user_scores.get(user_key, 0)


def reset_user_score(user_key: str) -> None:
    """Reset the hostility score for a user (e.g. after a successful block)."""
    _user_scores.pop(user_key, None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _severity_rank(severity: str) -> int:
    ranks = {"none": 0, "mild": 1, "moderate": 2, "severe": 3}
    return ranks.get(severity, 0)
