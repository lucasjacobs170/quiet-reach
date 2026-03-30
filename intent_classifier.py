"""
intent_classifier.py — Context-aware intent classification using training data.

Loads the 80 manually-curated examples from training_data.json and builds a
keyword/pattern-based scorer that classifies each incoming message into one of
four base intent categories:

  neutral          — genuine question / normal conversation, no hostility
  mildly_frustrated — annoyed or confused but not attacking; recoverable with empathy
  clearly_hostile  — direct insults / pure disrespect; needs strong boundary
  sarcastic_cutting — sarcasm/cutting remarks; frustration through irony, soft boundary

The IntentRouter (intent_router.py) maps neutral messages to more specific
extended categories for routing purposes:

  asks_about_lucas  — Questions about who Lucas is, what he does
  asks_for_links    — Wants social media links / platform URLs
  asks_for_help     — Wants bot to help with something
  casual_greeting   — Hi, hello, hey
  casual_gratitude  — Thanks, appreciate it
  casual_goodbye    — Bye, see you, catch you
  small_talk        — General conversation, observations
  unclear           — Can't determine intent

Usage (standalone validation):
    python intent_classifier.py
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

try:
    from pattern_detector_v2 import adjust_classification_scores as _adjust_scores
    _PATTERN_DETECTOR_V2_AVAILABLE = True
except ImportError:
    _PATTERN_DETECTOR_V2_AVAILABLE = False

# ---------------------------------------------------------------------------
# Training data path
# ---------------------------------------------------------------------------

_TRAINING_FILE: str = os.path.join(os.path.dirname(__file__), "training_data.json")

# ---------------------------------------------------------------------------
# Category constants
# ---------------------------------------------------------------------------

NEUTRAL = "neutral"
MILDLY_FRUSTRATED = "mildly_frustrated"
CLEARLY_HOSTILE = "clearly_hostile"
SARCASTIC_CUTTING = "sarcastic_cutting"

CATEGORIES = [NEUTRAL, MILDLY_FRUSTRATED, CLEARLY_HOSTILE, SARCASTIC_CUTTING]

# ---------------------------------------------------------------------------
# Recommended responses per category
# ---------------------------------------------------------------------------

RESPONSE_TEMPLATES: dict[str, list[str]] = {
    "no_response": [""],  # Neutral — just answer the question

    "empathetic_boundary": [
        "I know this is frustrating, but I'd appreciate if we could keep it respectful.",
        "I get that you're annoyed—let me actually try to help you.",
        "I hear you. Let me try to make this simpler.",
    ],

    "strong_boundary": [
        "That's beyond what I'm willing to engage with. I'm stepping back.",
        "That kind of language isn't something I'll respond to.",
        "I'm going quiet now—reach out when you're ready for a fresh start.",
    ],

    "gentle_boundary": [
        "I hear the sarcasm, and I get it—but let me actually try to help.",
        "I know that sounds frustrating, but I'm genuinely here to assist.",
        "I get the eye roll, but I really am trying to help here.",
    ],
}

_CATEGORY_RESPONSE_MAP: dict[str, str] = {
    NEUTRAL: "no_response",
    MILDLY_FRUSTRATED: "empathetic_boundary",
    CLEARLY_HOSTILE: "strong_boundary",
    SARCASTIC_CUTTING: "gentle_boundary",
}


# ---------------------------------------------------------------------------
# Tone marker definitions
# ---------------------------------------------------------------------------

# Markers that strongly indicate each category regardless of training keywords.
_SARCASM_MARKERS: list[str] = [
    "oh brilliant",
    "what a genius",
    "so helpful",
    "said no one ever",
    "totally believable",
    "top tier",
    "sure buddy",
    "whatever you say",
    "genius level",
    "eye roll",
    "eye rolls",
    "oh wow",
    "oh sure",
    "oh yeah",
    "amazing",
    "impressive",
    "fascinating",
    "noted",
    "brilliant strategy",
    "cool story",
    "cool story bro",
    "for nothing",
    "thanks for nothing",
    "thanks a lot for",
]

_FRUSTRATION_MARKERS: list[str] = [
    "why can't you",
    "why are you",
    "why is this",
    "just tell me",
    "just send",
    "just give me",
    "just answer",
    "this is frustrating",
    "this is annoying",
    "this is getting",
    "seriously",
    "come on",
    "i don't get it",
    "i'm confused",
    "i'm losing patience",
    "going nowhere",
    "making this so hard",
    "doesn't answer",
    "not really helping",
    "confusing right now",
    "hurry up",
    "what the hell",
    "what the fuck does",
    "ugh",
    "can't you just",
    "fine whatever",
    "taking forever",
    "damn link",
    "what do you mean",
    "try again",
]

_HOSTILITY_MARKERS: list[str] = [
    "fuck you",
    "fuck off",
    "fuck this",
    "fuck lucas",
    "useless piece of shit",
    "piece of shit",
    "kill yourself",
    "go to hell",
    "you're worthless",
    "you're garbage",
    "you're trash",
    "you're stupid",
    "you're broken",
    "you're dumb",
    "you're an idiot",
    "stupid bot",
    "dumb bot",
    "idiot bot",
    "worthless code",
    "complete garbage",
    "shut the fuck up",
    "you asshole",
    "loser creator",
    "pathetic loser",
    "pathetic",
    "fucking stupid",
    "i hate you",
    "worst ai",
    "die already",
    "block me",
    "dumber than a rock",
]

_QUESTION_INDICATORS: list[str] = ["?", "who", "what", "where", "when", "how", "why", "can you", "could you", "please"]

_POLITE_INDICATORS: list[str] = [
    "thank",
    "thanks",
    "please",
    "appreciate",
    "hi ",
    "hello",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
    "have a great",
]


# ---------------------------------------------------------------------------
# IntentClassifier
# ---------------------------------------------------------------------------

class IntentClassifier:
    """
    Context-aware intent classifier built from training_data.json.

    Classification steps:
      1. Extract keywords from each training category.
      2. For each new message, score it against keyword/tone-marker lists.
      3. Return the highest-scoring category with a confidence estimate.
    """

    def __init__(self) -> None:
        self.training_data: dict = _load_training_data()
        self.category_keywords: dict[str, set[str]] = {}
        self.category_patterns: dict[str, list[re.Pattern]] = {}
        self.build_classifier()

    # ------------------------------------------------------------------
    # Build phase
    # ------------------------------------------------------------------

    def build_classifier(self) -> None:
        """Extract keyword sets and compile regex patterns from training examples."""
        self.extract_keywords_per_category()
        self._compile_patterns()

    def extract_keywords_per_category(self) -> None:
        """
        Learn which tokens appear most in each category.
        Stopwords are filtered so only meaningful tokens remain.
        """
        stopwords = {
            "a", "an", "the", "is", "it", "i", "me", "my", "you", "your",
            "he", "his", "she", "her", "we", "they", "them", "their",
            "and", "or", "but", "if", "in", "on", "at", "to", "for",
            "of", "with", "by", "as", "be", "do", "so", "up", "out",
            "this", "that", "these", "those", "was", "are", "were",
            "have", "has", "had", "can", "could", "will", "would",
            "should", "may", "might", "not", "no", "from", "just",
        }

        examples = self.training_data.get("training_examples", {})
        for category, messages in examples.items():
            tokens: set[str] = set()
            for msg in messages:
                words = re.findall(r"[a-z']+", msg.lower())
                for w in words:
                    if w not in stopwords and len(w) >= 3:
                        tokens.add(w)
            self.category_keywords[category] = tokens

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns for every multi-word tone marker."""
        for category, markers in [
            (NEUTRAL, _POLITE_INDICATORS),
            (MILDLY_FRUSTRATED, _FRUSTRATION_MARKERS),
            (CLEARLY_HOSTILE, _HOSTILITY_MARKERS),
            (SARCASTIC_CUTTING, _SARCASM_MARKERS),
        ]:
            compiled = [
                re.compile(r"\b" + re.escape(m.lower()) + r"\b")
                for m in markers
            ]
            self.category_patterns[category] = compiled

    # ------------------------------------------------------------------
    # Tone analysis
    # ------------------------------------------------------------------

    def analyze_tone_markers(self, message: str) -> dict[str, list[str]]:
        """
        Detect tone indicators in *message*.

        Returns a dict with keys 'sarcasm', 'frustration', 'hostility',
        'questions', 'polite' mapping to lists of matched markers.
        """
        t = message.lower()
        detected: dict[str, list[str]] = {
            "sarcasm": [],
            "frustration": [],
            "hostility": [],
            "questions": [],
            "polite": [],
        }

        for marker in _SARCASM_MARKERS:
            if marker in t:
                detected["sarcasm"].append(marker)

        for marker in _FRUSTRATION_MARKERS:
            if marker in t:
                detected["frustration"].append(marker)

        for marker in _HOSTILITY_MARKERS:
            if marker in t:
                detected["hostility"].append(marker)

        for indicator in _QUESTION_INDICATORS:
            if indicator in t:
                detected["questions"].append(indicator)

        for indicator in _POLITE_INDICATORS:
            if indicator in t:
                detected["polite"].append(indicator)

        return detected

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_message(self, message: str) -> dict[str, float]:
        """
        Score *message* across all categories, returning a dict of
        {category: score} where scores are in [0.0, 1.0].

        Scoring combines:
          - Tone-marker hits (weighted heavily — these are hand-crafted signals)
          - Training keyword overlap (lightweight background signal)
        """
        t = message.lower()
        words = set(re.findall(r"[a-z']+", t))
        scores: dict[str, float] = {c: 0.0 for c in CATEGORIES}

        # --- Tone-marker scoring (primary signal) ---
        tone = self.analyze_tone_markers(message)

        # Hostility markers → clearly_hostile (strong signal)
        for _ in tone["hostility"]:
            scores[CLEARLY_HOSTILE] += 0.35

        # Frustration markers → mildly_frustrated
        for _ in tone["frustration"]:
            scores[MILDLY_FRUSTRATED] += 0.25

        # Sarcasm markers → sarcastic_cutting
        for _ in tone["sarcasm"]:
            scores[SARCASTIC_CUTTING] += 0.25

        # Polite + question markers → neutral
        for _ in tone["polite"]:
            scores[NEUTRAL] += 0.20
        for _ in tone["questions"]:
            scores[NEUTRAL] += 0.10

        # --- Keyword overlap scoring (secondary signal) ---
        for category in CATEGORIES:
            kws = self.category_keywords.get(category, set())
            overlap = len(words & kws)
            if overlap > 0:
                scores[category] += min(0.30, overlap * 0.06)

        # --- Context disambiguation: question with frustration word ---
        # e.g. "what the fuck does that mean?" is frustrated inquiry, not attack
        if "?" in message:
            # If there are hostility markers but also question structure,
            # downgrade clearly_hostile and boost mildly_frustrated
            if tone["hostility"] and tone["questions"]:
                scores[CLEARLY_HOSTILE] *= 0.5
                scores[MILDLY_FRUSTRATED] += 0.20

        # --- Normalize so max is 1.0 ---
        max_score = max(scores.values()) if scores else 0.0
        if max_score > 1.0:
            for c in CATEGORIES:
                scores[c] = min(1.0, scores[c] / max_score)

        # --- Apply context-aware score adjustments (pattern_detector_v2) ---
        if _PATTERN_DETECTOR_V2_AVAILABLE:
            scores = _adjust_scores(
                scores,
                message,
                sarcasm_markers_matched=tone.get("sarcasm", []),
            )

        return scores

    # ------------------------------------------------------------------
    # Main classify method
    # ------------------------------------------------------------------

    def classify_message(self, message: str) -> tuple[str, float, str]:
        """
        Classify *message* into one of the four intent categories.

        Returns:
            (category, confidence, explanation)

        Categories:
            neutral          — Genuine question / normal conversation
            mildly_frustrated — Annoyed but not attacking
            clearly_hostile  — Direct insults / attack
            sarcastic_cutting — Sharp/sarcastic but not pure attack
        """
        if not message or not message.strip():
            return NEUTRAL, 1.0, "Empty message — treated as neutral."

        scores = self.score_message(message)
        tone = self.analyze_tone_markers(message)

        # Pick the highest-scoring category
        best_category = max(scores, key=lambda c: scores[c])
        best_score = scores[best_category]

        # If all scores are very low (no signals detected) → neutral
        if best_score < 0.05:
            return NEUTRAL, 0.90, "No hostility or frustration markers detected."

        # Build confidence: ratio of best score to sum of all scores
        total = sum(scores.values())
        confidence = round(best_score / total, 2) if total > 0 else 0.5
        # Clamp to [0.5, 0.99] so it never implies perfect/random certainty
        confidence = max(0.50, min(0.99, confidence))

        # Build explanation
        explanation = _build_explanation(best_category, tone, scores)

        return best_category, confidence, explanation

    # ------------------------------------------------------------------
    # Response recommendation
    # ------------------------------------------------------------------

    def get_recommended_response(self, category: str) -> str:
        """
        Return the response template key for *category*.

        Returns one of: 'no_response', 'empathetic_boundary',
                        'strong_boundary', 'gentle_boundary'.
        """
        return _CATEGORY_RESPONSE_MAP.get(category, "no_response")


# ---------------------------------------------------------------------------
# Module-level singleton (lazy)
# ---------------------------------------------------------------------------

_classifier_instance: Optional[IntentClassifier] = None


def get_classifier() -> IntentClassifier:
    """Return the module-level singleton IntentClassifier (created on first call)."""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = IntentClassifier()
    return _classifier_instance


def classify(message: str) -> tuple[str, float, str]:
    """
    Convenience wrapper — classify *message* using the singleton classifier.

    Returns (category, confidence, explanation).
    """
    return get_classifier().classify_message(message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_training_data(path: str = _TRAINING_FILE) -> dict:
    """Load training_data.json from *path*. Returns empty dict on error."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"⚠️ intent_classifier: could not load training data from {path}: {exc}")
        return {}


def _build_explanation(
    category: str,
    tone: dict[str, list[str]],
    scores: dict[str, float],
) -> str:
    """Build a human-readable explanation for a classification result."""
    parts: list[str] = [f"Category '{category}' selected."]

    if tone["hostility"]:
        parts.append(f"Hostility markers: {tone['hostility'][:3]}.")
    if tone["frustration"]:
        parts.append(f"Frustration markers: {tone['frustration'][:3]}.")
    if tone["sarcasm"]:
        parts.append(f"Sarcasm markers: {tone['sarcasm'][:3]}.")
    if tone["polite"]:
        parts.append(f"Polite markers: {tone['polite'][:3]}.")
    if tone["questions"]:
        parts.append("Question structure detected.")

    score_summary = ", ".join(f"{c}: {round(v, 2)}" for c, v in scores.items())
    parts.append(f"Scores — {score_summary}.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Standalone validation (accuracy test against training data)
# ---------------------------------------------------------------------------

def test_classifier_accuracy() -> None:
    """
    Test each training example against the classifier.

    Target: 95%+ accuracy on training data.
    """
    clf = IntentClassifier()
    data = clf.training_data.get("training_examples", {})

    category_map = {
        "neutral": NEUTRAL,
        "mildly_frustrated": MILDLY_FRUSTRATED,
        "clearly_hostile": CLEARLY_HOSTILE,
        "sarcastic_cutting": SARCASTIC_CUTTING,
    }

    total = 0
    correct = 0
    failures: list[str] = []

    for raw_category, expected_category in category_map.items():
        examples = data.get(raw_category, [])
        for msg in examples:
            total += 1
            predicted, confidence, _ = clf.classify_message(msg)
            if predicted == expected_category:
                correct += 1
            else:
                failures.append(
                    f"  FAIL [{raw_category}] '{msg}' → predicted '{predicted}' "
                    f"(conf={confidence:.2f})"
                )

    accuracy = (correct / total * 100) if total else 0.0
    print(f"\n{'='*60}")
    print(f"Intent Classifier Accuracy: {correct}/{total} = {accuracy:.1f}%")
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for f in failures:
            print(f)
    else:
        print("No failures! ✅")
    print("=" * 60)


if __name__ == "__main__":
    test_classifier_accuracy()
