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

# ---------------------------------------------------------------------------
# Build flat pattern index: list of (canonical_phrase, severity, all_tokens)
# where all_tokens includes the phrase itself + all its listed variations.
# ---------------------------------------------------------------------------

@dataclass
class _PatternEntry:
    phrase: str
    severity: str
    tokens: list[str]   # phrase + all variations (already lowercased)


_PATTERNS: list[_PatternEntry] = []

for _cat_data in _LIBRARY["categories"].values():
    for _entry in _cat_data["entries"]:
        _phrase = _entry["phrase"].lower().strip()
        _variations = [v.lower().strip() for v in _entry.get("variations", [])]
        _tokens = list(dict.fromkeys([_phrase] + _variations))  # deduplicate, preserve order
        _PATTERNS.append(_PatternEntry(phrase=_phrase, severity=_entry["severity"], tokens=_tokens))

# ---------------------------------------------------------------------------
# Per-user hostility score store (in-memory; intentionally lightweight)
# ---------------------------------------------------------------------------

_user_scores: dict[str, int] = {}


# ---------------------------------------------------------------------------
# Detection result
# ---------------------------------------------------------------------------

@dataclass
class InsultDetectionResult:
    detected: bool = False
    severity: str = "none"          # none | mild | moderate | severe
    score_delta: int = 0            # points added for this message
    matched_phrase: str = ""        # canonical phrase that triggered detection
    matched_token: str = ""         # specific token / variation that matched
    should_block: bool = False      # True if cumulative score >= threshold
    cumulative_score: int = 0       # running total for this user after this message


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

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _token_matches(input_token: str, pattern_token: str) -> bool:
    """
    Return True if *input_token* is considered a match for *pattern_token*.
    Exact substring match is tried first; fuzzy match is used as fallback.
    """
    if pattern_token in input_token:
        return True
    # Fuzzy match is only worthwhile when lengths are somewhat close
    max_len = max(len(input_token), len(pattern_token))
    if max_len == 0:
        return False
    len_ratio = min(len(input_token), len(pattern_token)) / max_len
    if len_ratio < 0.5:
        return False
    return _similarity(input_token, pattern_token) >= FUZZY_THRESHOLD


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
    if not text or not text.strip():
        return InsultDetectionResult()

    all_caps = _is_all_caps(text.strip())
    normalized = normalize_text(text)

    best_severity = "none"
    best_phrase = ""
    best_token = ""

    for entry in _PATTERNS:
        for token in entry.tokens:
            norm_token = normalize_text(token)
            if _token_matches(normalized, norm_token):
                # Keep the highest-severity match
                if _severity_rank(entry.severity) > _severity_rank(best_severity):
                    best_severity = entry.severity
                    best_phrase = entry.phrase
                    best_token = token
                break  # found a match for this entry; no need to check more tokens

    if best_severity == "none":
        return InsultDetectionResult()

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
