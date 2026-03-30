"""
pattern_detector_v2.py — Improved sarcasm / tone pattern detection.

Addresses the false-positive problems identified in testing:

  - Fuzzy matching on very short phrases (< 5 chars) caused 100% false
    positive rates on common innocent words.
  - Markers like "wow" and "oh great" triggered on genuinely positive messages.
  - Single-word or two-word messages were classified as sarcastic/hostile.

Improvements over the original intent_classifier.py approach:

  1. Minimum context length (3+ words) before any non-neutral classification.
  2. Positive context indicators (emoji, polite words, warm phrasing) suppress
     detection for ambiguous short sarcasm markers.
  3. Fuzzy matching restricted to patterns of 5+ characters.
  4. Confidence thresholds tightened for borderline / ambiguous cases.
  5. Short-phrase ambiguous sarcasm markers only trigger when accompanied by
     explicit negative context words.

This module provides helper functions that are called by ``IntentClassifier``
(intent_classifier.py) to adjust scores before a final classification is made.
It does **not** replace the classifier — it layers additional guards on top.

Usage::

    from pattern_detector_v2 import adjust_classification_scores

    scores = classifier.score_message(message)
    scores = adjust_classification_scores(scores, message)
    # then pick best category from adjusted scores
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Minimum context requirements
# ---------------------------------------------------------------------------

#: Messages with fewer words than this threshold are classified as neutral
#: regardless of pattern matches, to avoid false positives on very short messages.
MIN_WORDS_FOR_CLASSIFICATION: int = 3

#: Minimum character length a pattern must have to qualify for fuzzy matching.
#: Shorter patterns use exact / word-boundary matching only.
MIN_FUZZY_PATTERN_LENGTH: int = 5

# ---------------------------------------------------------------------------
# Positive context indicators
# ---------------------------------------------------------------------------

# Emoji that strongly signal genuine positive sentiment.
_POSITIVE_EMOJI: frozenset[str] = frozenset({
    "😊", "😄", "😁", "😃", "😀", "🙂", "😍", "🥰", "❤️", "💕",
    "👍", "✌️", "🙌", "👏", "🎉", "🎊", "✨", "💯", "🔥", "⭐",
    "😎", "🤩", "😮", "😲", "🤗", "💪",
})

# Words / phrases that indicate genuine warmth or enthusiasm (not sarcasm).
_POSITIVE_MARKERS: list[str] = [
    "thank you", "thanks", "appreciate", "grateful", "love it",
    "love this", "great job", "good job", "well done", "awesome",
    "that's great", "that's amazing", "so cool", "really cool",
    "very helpful", "super helpful", "very nice", "so nice",
    "actually helpful", "genuinely", "honestly", "seriously though",
    "please", "hi ", "hello", "hey",
]

# Phrases that make ambiguous positive words unambiguously positive.
_EXPLICIT_POSITIVE_PHRASES: list[str] = [
    "i love", "i really love", "i'm so happy", "so happy",
    "this is great", "this is awesome", "this is amazing",
    "can't believe how", "really impressed", "blown away",
    "you're the best", "you're amazing", "you're so helpful",
    "this actually", "this really",
]

# ---------------------------------------------------------------------------
# Ambiguous short sarcasm markers
# ---------------------------------------------------------------------------

# These markers appear in the sarcasm-marker list but are genuinely ambiguous
# in isolation — they are used as real enthusiasm just as often as sarcasm.
# They should only trigger when the message also contains negative context words.
_AMBIGUOUS_SHORT_SARCASM: frozenset[str] = frozenset({
    "wow",
    "amazing",
    "impressive",
    "fascinating",
    "oh great",
    "oh wow",
    "oh sure",
    "oh yeah",
    "noted",
    "brilliant",
    "top tier",
    "cool story",
    "sure buddy",
})

# Words whose presence near an ambiguous sarcasm marker confirms sarcastic intent.
_NEGATIVE_CONTEXT_WORDS: list[str] = [
    "not", "never", "can't", "cannot", "didn't", "isn't", "wasn't",
    "pathetic", "useless", "waste", "stupid", "dumb", "garbage",
    "broken", "terrible", "awful", "horrible", "bad", "wrong",
    "ruin", "ruined", "failed", "failure",
    "ugh", "smh", "seriously", "still broken", "again",
    # Sarcasm-confirmation phrases (common in sarcastically-phrased messages)
    "as always", "missing the point", "completely", "nonsense",
    "just what i needed", "just what i", "guess who", "let me just",
    "random", "typical", "of course", "obviously", "clearly",
    "super useful", "super helpful", "so helpful", "so useful",
    "right, like", "yeah right", "sure thing", "oh really",
]


# ---------------------------------------------------------------------------
# Context analysis helpers
# ---------------------------------------------------------------------------

def has_positive_context(message: str) -> bool:
    """
    Return ``True`` if the message contains strong positive context indicators
    that should suppress ambiguous sarcasm detection.

    Checks are applied in order of strength:
    1. Positive emoji present.
    2. Explicit positive phrases (unambiguously enthusiastic).
    3. Two or more polite / warm markers co-occurring.
    """
    # 1. Emoji check (unicode emoji are not in lowercase so check original)
    for emoji in _POSITIVE_EMOJI:
        if emoji in message:
            return True

    t = message.lower()

    # 2. Explicit positive phrases
    for phrase in _EXPLICIT_POSITIVE_PHRASES:
        if phrase in t:
            return True

    # 3. Multiple polite / warm markers (two or more is a strong signal)
    marker_count = sum(1 for m in _POSITIVE_MARKERS if m in t)
    if marker_count >= 2:
        return True

    return False


def has_negative_context(message: str) -> bool:
    """
    Return ``True`` if the message contains negative context words that
    support classifying it as sarcastic or hostile.
    """
    t = message.lower()
    return any(word in t for word in _NEGATIVE_CONTEXT_WORDS)


def _is_ambiguous_sarcasm_marker(marker: str) -> bool:
    """Return ``True`` if *marker* is in the ambiguous short sarcasm set."""
    return marker.lower().strip() in _AMBIGUOUS_SHORT_SARCASM


# ---------------------------------------------------------------------------
# Score adjustment
# ---------------------------------------------------------------------------

def adjust_classification_scores(
    scores: dict[str, float],
    message: str,
    sarcasm_markers_matched: list[str] | None = None,
) -> dict[str, float]:
    """
    Apply context-aware adjustments to raw classification scores.

    Parameters
    ----------
    scores : dict[str, float]
        Raw scores from :meth:`IntentClassifier.score_message`.
        Expected keys: ``neutral``, ``mildly_frustrated``,
        ``clearly_hostile``, ``sarcastic_cutting``.
    message : str
        The original user message.
    sarcasm_markers_matched : list[str] | None
        Sarcasm markers that were detected in the message (used to
        decide whether positive-context suppression applies).

    Returns
    -------
    dict[str, float]
        Adjusted scores (may have sarcastic_cutting reduced to 0.0 for
        messages that are clearly positive in context).
    """
    adjusted = dict(scores)
    words = message.strip().split()

    # -----------------------------------------------------------------------
    # Rule 1 — very short messages suppress ONLY sarcasm and mild frustration.
    # Explicit hostility ("fuck you", "kill yourself") must still be detected
    # even in short messages — the minimum context check does not apply there.
    # -----------------------------------------------------------------------
    if len(words) < MIN_WORDS_FOR_CLASSIFICATION:
        adjusted["sarcastic_cutting"] = 0.0
        adjusted["mildly_frustrated"] = 0.0
        # Only boost neutral if no strong hostility signal is present
        if adjusted.get("clearly_hostile", 0.0) < 0.3:
            adjusted["neutral"] = max(adjusted.get("neutral", 0.0), 0.90)
        return adjusted

    # -----------------------------------------------------------------------
    # Rule 2 — positive context suppresses ambiguous sarcasm
    # -----------------------------------------------------------------------
    matched = sarcasm_markers_matched or []

    if adjusted.get("sarcastic_cutting", 0.0) > 0.0:
        # If all matched markers are ambiguous, apply context checks
        ambiguous_only = matched and all(_is_ambiguous_sarcasm_marker(m) for m in matched)
        no_markers_matched = not matched  # markers list not provided by caller

        if ambiguous_only or no_markers_matched:
            if has_positive_context(message):
                # Clear positive signal — suppress sarcasm classification
                adjusted["sarcastic_cutting"] = 0.0
                adjusted["neutral"] = max(adjusted.get("neutral", 0.0), 0.70)
            elif not has_negative_context(message):
                # Multiple ambiguous sarcasm markers together is itself a signal
                # (e.g. "impressive, really top tier" — both markers are ambiguous
                # but their co-occurrence strongly implies sarcasm)
                if len(matched) >= 2:
                    pass  # Keep original score — co-occurrence confirms sarcasm
                else:
                    # Single ambiguous marker, no negative context — reduce score significantly
                    # and give neutral a boost so it wins over the reduced sarcasm score
                    reduced = adjusted["sarcastic_cutting"] * 0.30
                    adjusted["neutral"] = max(
                        adjusted.get("neutral", 0.0),
                        adjusted["sarcastic_cutting"] * 0.60,  # neutral beats reduced sarcasm
                    )
                    adjusted["sarcastic_cutting"] = reduced

    # -----------------------------------------------------------------------
    # Rule 3 — positive context also reduces mild frustration when present
    # -----------------------------------------------------------------------
    if adjusted.get("mildly_frustrated", 0.0) > 0.0 and has_positive_context(message):
        adjusted["mildly_frustrated"] *= 0.50

    return adjusted


# ---------------------------------------------------------------------------
# Fuzzy-matching guard
# ---------------------------------------------------------------------------

def should_use_fuzzy_matching(pattern: str) -> bool:
    """
    Return ``True`` if *pattern* is long enough to safely use fuzzy matching.

    Patterns shorter than :data:`MIN_FUZZY_PATTERN_LENGTH` characters are
    restricted to exact / word-boundary matching only because fuzzy comparison
    of short strings produces a very high false-positive rate.
    """
    return len(pattern.strip()) >= MIN_FUZZY_PATTERN_LENGTH
