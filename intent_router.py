"""
intent_router.py — Routes incoming messages to the appropriate response type.

Uses IntentClassifier for hostility/tone detection and applies additional
routing logic to distinguish information requests, social queries, and
casual conversation.

Routing decision order:
  1. Hostility check  — block or apply boundary
  2. Information      — answer from verified knowledge_base.json
  3. Casual           — reply from safe_responses.json (± light creativity)
  4. Default          — unclear_question fallback
"""

from __future__ import annotations

import json
import os
import re
import random
from typing import Optional

from intent_classifier import IntentClassifier

try:
    from conversation_context import ConversationContextManager
    _CONTEXT_AVAILABLE = True
except ImportError:
    _CONTEXT_AVAILABLE = False

try:
    from social_engineering_detector import SocialEngineeringDetector
    _SE_DETECTOR_AVAILABLE = True
except ImportError:
    _SE_DETECTOR_AVAILABLE = False

# ---------------------------------------------------------------------------
# Routing type constants
# ---------------------------------------------------------------------------

ROUTE_KNOWLEDGE_BASE = "knowledge_base"
ROUTE_SAFE_RESPONSE  = "safe_response"
ROUTE_CREATIVE       = "creative"
ROUTE_HOSTILE_BLOCK  = "hostile_block"
ROUTE_BOUNDARY       = "boundary"
ROUTE_DEFAULT        = "default"

# ---------------------------------------------------------------------------
# Proactive-engagement thresholds
# ---------------------------------------------------------------------------

# How many unanswered requests must accumulate before a proactive offer fires
PROACTIVE_UNANSWERED_THRESHOLD: int = 2

# How many link requests must be seen before a proactive offer fires
PROACTIVE_LINK_COUNT_THRESHOLD: int = 2

# ---------------------------------------------------------------------------
# Extended intent categories used by the router
# ---------------------------------------------------------------------------

INTENT_CATEGORIES: dict[str, str] = {
    "clearly_hostile":   "Direct insults, attacks",
    "mildly_frustrated": "Annoyed but not attacking",
    "sarcastic_cutting": "Sarcastic/sharp but not pure attack",
    "asks_about_lucas":  "Questions about who Lucas is, what he does",
    "asks_for_links":    "Wants social media links",
    "asks_for_help":     "Wants bot to help with something",
    "casual_greeting":   "Hi, hello, hey",
    "casual_gratitude":  "Thanks, appreciate it",
    "casual_goodbye":    "Bye, see you, catch you",
    "small_talk":        "General conversation, observations",
    "unclear":           "Can't determine intent",
}

# Keywords used to widen intent detection beyond the base classifier categories
_LINK_KEYWORDS: list[str] = [
    "link", "links", "url", "website", "follow", "find", "socials",
    "chaturbate", "onlyfans", "twitter", "instagram", "discord", "telegram",
    "x.com", "platform", "profile",
]

_LUCAS_INFO_KEYWORDS: list[str] = [
    "lucas", "tell me about", "about lucas", "does lucas", "lucas do",
    "content", "stream", "show", "game", "ranch", "woods", "ocean",
    "surf", "jenga", "darts", "hottub", "shower", "onlyfans", "chaturbate",
]

_GREETING_KEYWORDS: list[str] = ["hi", "hey", "hello", "sup", "yo", "what's up", "howdy"]
_GRATITUDE_KEYWORDS: list[str] = ["thanks", "thank you", "thx", "appreciate", "ty", "cheers"]
_GOODBYE_KEYWORDS: list[str] = ["bye", "goodbye", "see you", "later", "catch you", "peace", "cya"]
_HELP_KEYWORDS: list[str] = ["help", "assist", "can you", "need info", "need help"]


# ---------------------------------------------------------------------------
# IntentRouter
# ---------------------------------------------------------------------------

class IntentRouter:
    """
    Routes a user message to a response and a routing_type label.

    Attributes:
        classifier:      IntentClassifier instance for tone/hostility detection.
        knowledge_base:  Loaded knowledge_base.json dict.
        safe_responses:  Loaded safe_responses.json dict.
        creative_mode:   Loaded creative_mode.json dict.
    """

    def __init__(
        self,
        knowledge_base_path: str = "",
        safe_responses_path: str = "",
        creative_mode_path: str = "",
        context_manager: Optional["ConversationContextManager"] = None,
    ) -> None:
        self.classifier = IntentClassifier()

        base_dir = os.path.dirname(__file__)

        kb_path = knowledge_base_path or os.path.join(base_dir, "knowledge_base.json")
        sr_path = safe_responses_path or os.path.join(base_dir, "safe_responses.json")
        cm_path = creative_mode_path or os.path.join(base_dir, "creative_mode.json")

        self.knowledge_base: dict = _load_json(kb_path, "knowledge_base.json")
        self.safe_responses: dict = _load_json(sr_path, "safe_responses.json")
        self.creative_mode: dict = _load_json(cm_path, "creative_mode.json")

        # Optional conversation-context manager (injected or sourced from module singleton)
        if context_manager is not None:
            self._ctx = context_manager
        elif _CONTEXT_AVAILABLE:
            from conversation_context import get_context_manager
            self._ctx = get_context_manager()
        else:
            self._ctx = None

        # Social-engineering detector (stateless helper)
        self._se_detector = SocialEngineeringDetector() if _SE_DETECTOR_AVAILABLE else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route_message(self, user_message: str, user_key: str = "") -> tuple[str, str]:
        """
        Route *user_message* to the appropriate response.

        Parameters
        ----------
        user_message : str
            Raw message from the user.
        user_key : str
            Opaque per-user identifier used for conversation-context tracking.
            Pass an empty string to skip context tracking.

        Returns:
            (response_text, routing_type)

        routing_type is one of:
            'knowledge_base', 'safe_response', 'creative',
            'hostile_block', 'boundary', 'default'
        """
        base_intent, _confidence, _explanation = self.classifier.classify_message(user_message)
        extended_intent = self._extend_intent(user_message, base_intent)

        # Run social-engineering check before routing (does not change intent)
        if user_key and self._se_detector and self._ctx:
            self._se_detector.analyze(
                user_key=user_key,
                current_intent=extended_intent,
                ctx_mgr=self._ctx,
            )

        # 1. Hostility routing
        if extended_intent == "clearly_hostile":
            response = self._get_response("firm_boundary")
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_HOSTILE_BLOCK

        if extended_intent in ("mildly_frustrated", "sarcastic_cutting"):
            response = self._get_response("boundary_responses")
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_BOUNDARY

        # 2. Information routing (verified facts only)
        if extended_intent == "asks_about_lucas":
            response = self._answer_about_lucas(user_message)
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_KNOWLEDGE_BASE

        if extended_intent == "asks_for_links":
            response = self._handle_links_request(user_key)
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_KNOWLEDGE_BASE

        if extended_intent == "asks_for_help":
            response = self._get_response("greetings")
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_SAFE_RESPONSE

        # 3. Casual routing (safe responses / light creativity)
        if extended_intent == "casual_greeting":
            response = self._get_response("greetings")
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_SAFE_RESPONSE

        if extended_intent == "casual_gratitude":
            response = self._get_response("thank_you")
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_SAFE_RESPONSE

        if extended_intent == "casual_goodbye":
            response = self._get_response("goodbyes")
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_SAFE_RESPONSE

        if extended_intent == "small_talk":
            response = self._handle_small_talk(user_message, user_key)
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_CREATIVE

        # Unknown question (has "?" but no matching topic) → i_dont_know
        if extended_intent == "unknown_question":
            response = self._get_response("i_dont_know")
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_SAFE_RESPONSE

        # 4. Default fallback
        response = self._get_response("unclear_question")
        self._record(user_key, extended_intent, user_message, response)
        return response, ROUTE_DEFAULT

    def get_conversation_log(self, response_text: str, routing_type: str) -> dict:
        """
        Build a metadata dict suitable for inclusion in a transcript entry.

        Returns a dict with response text, routing_type, and source flags.
        """
        return {
            "response": response_text,
            "routing_type": routing_type,
            "source": {
                "verified_facts":   routing_type == ROUTE_KNOWLEDGE_BASE,
                "safe_response":    routing_type == ROUTE_SAFE_RESPONSE,
                "creative":         routing_type == ROUTE_CREATIVE,
                "hostile":          routing_type in (ROUTE_HOSTILE_BLOCK, ROUTE_BOUNDARY),
                "hallucination_risk": _hallucination_risk(routing_type),
            },
        }

    # ------------------------------------------------------------------
    # Intent extension
    # ------------------------------------------------------------------

    def _extend_intent(self, message: str, base_intent: str) -> str:
        """
        Map the base classifier intent (neutral / mildly_frustrated /
        clearly_hostile / sarcastic_cutting) to the expanded set used by
        the router.

        For 'neutral' messages, applies keyword matching to select the most
        specific intent; hostile/frustrated intents pass through unchanged.
        """
        # Hostile / frustrated categories pass through directly
        if base_intent in ("clearly_hostile", "mildly_frustrated", "sarcastic_cutting"):
            return base_intent

        # Neutral → inspect content for a more specific intent
        t = message.lower()

        if _matches_any(t, _LINK_KEYWORDS):
            return "asks_for_links"

        if _matches_any(t, _LUCAS_INFO_KEYWORDS):
            return "asks_about_lucas"

        if _matches_any(t, _HELP_KEYWORDS):
            return "asks_for_help"

        if _matches_any(t, _GREETING_KEYWORDS):
            return "casual_greeting"

        if _matches_any(t, _GRATITUDE_KEYWORDS):
            return "casual_gratitude"

        if _matches_any(t, _GOODBYE_KEYWORDS):
            return "casual_goodbye"

        # Messages containing a question mark but no known topic → i_dont_know
        # Check this before the short-message small_talk fallback so that
        # short unknown questions (e.g. "What's his favorite food?") get
        # an "I don't know" rather than a casual small-talk reply.
        if "?" in message:
            return "unknown_question"

        # Short messages with no clear intent → small talk
        if len(message.split()) <= 6:
            return "small_talk"

        return "unclear"

    # ------------------------------------------------------------------
    # Response builders
    # ------------------------------------------------------------------

    def _answer_about_lucas(self, user_message: str) -> str:
        """Return a verified answer about Lucas based on the user's question."""
        t = user_message.lower()
        t_words = set(re.findall(r"[a-z]+", t))

        best_faq = None
        best_overlap = 0

        for faq in self.knowledge_base.get("faqs", []):
            if not faq.get("critical"):
                continue
            q_words = set(re.findall(r"[a-z]+", faq["question"].lower()))
            # Require at least 2 meaningful words in common (ignore short stop words)
            meaningful_overlap = len(
                t_words & q_words - {"a", "an", "the", "is", "his", "he", "do", "does"}
            )
            if meaningful_overlap > best_overlap:
                best_overlap = meaningful_overlap
                best_faq = faq

        if best_faq and best_overlap >= 2:
            return best_faq["answer"]

        # Fall back to general description
        return self.knowledge_base["who_is_lucas"]["description"]

    def _get_links(self) -> str:
        """Return all verified platform links as a formatted string."""
        platforms = self.knowledge_base["platforms"]["primary"]
        contact   = self.knowledge_base["platforms"]["contact"]

        lines = ["Here's where you can find Lucas:\n"]
        for p in platforms:
            lines.append(f"🔗 {p['name']}: {p['url']}")

        lines.append("\n💬 Contact Lucas:")
        lines.append(f"Telegram: {contact['telegram']}")
        lines.append(f"Discord: {contact['discord']}")

        return "\n".join(lines)

    def _handle_links_request(self, user_key: str = "") -> str:
        """
        Return platform links, with context-aware messaging on repeated requests.

        On the first request, returns the full link list.
        On subsequent requests, adds a friendly acknowledgment that links were
        already shared.
        """
        link_count = 0
        if user_key and self._ctx:
            link_count = self._ctx.link_request_count(user_key)

        links = self._get_links()

        if link_count >= 1:
            # Repeat request — acknowledge it warmly before the links
            repeats = self.safe_responses.get("link_repeat_acknowledgment", [
                "I already shared those earlier — here they are again:",
                "Happy to share again! Here are Lucas's links:",
                "Sure thing! Here they are once more:",
            ])
            return random.choice(repeats) + "\n\n" + links

        return links

    def _handle_small_talk(self, user_message: str, user_key: str = "") -> str:
        """Handle small talk with light, grounded creativity.

        If the user has sent several unanswered requests, proactively offer help
        instead of a generic small-talk reply.
        """
        if user_key and self._ctx:
            unanswered = self._ctx.unanswered_count(user_key)
            link_count = self._ctx.link_request_count(user_key)
            if unanswered >= PROACTIVE_UNANSWERED_THRESHOLD or link_count >= PROACTIVE_LINK_COUNT_THRESHOLD:
                proactive = self.safe_responses.get("proactive_offer", [
                    "Hey, I notice you've been looking for something — can I help?",
                    "It looks like you might need something — what can I do for you?",
                    "I'm here! Ask me anything about Lucas or his links.",
                ])
                return random.choice(proactive)
        responses = [
            "That sounds cool!",
            "I like where your head's at",
            "Ha, fair point!",
            "You're right about that",
            "Nice one!",
        ]
        return random.choice(responses)

    def _record(self, user_key: str, intent: str, message: str, response: str) -> None:
        """Record a completed request/response pair in the conversation context."""
        if user_key and self._ctx:
            self._ctx.record(user_key=user_key, intent=intent, message=message, response=response)

    def _get_response(self, category: str) -> str:
        """Return a random response from the given safe_responses category."""
        options = self.safe_responses.get(category, ["I'm not sure. Feel free to ask Lucas!"])
        return random.choice(options)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: str, label: str) -> dict:
    """Load a JSON file, raising a clear error if it is missing or malformed."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"intent_router: required file '{label}' not found at '{path}'. "
            "Ensure all guardrail JSON files are present."
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"intent_router: '{label}' at '{path}' is not valid JSON: {exc}"
        ) from exc


def _matches_any(text: str, keywords: list[str]) -> bool:
    """
    Return True if *text* contains any keyword from *keywords*.

    Single-word keywords are matched as whole words (word boundary) to avoid
    false positives like "hi" inside "his".  Multi-word phrases use simple
    substring matching since word boundaries are implicit at phrase edges.
    """
    for kw in keywords:
        if " " in kw:
            # Multi-word phrase — substring match is fine
            if kw in text:
                return True
        else:
            # Single word — require word boundary
            if re.search(r"\b" + re.escape(kw) + r"\b", text):
                return True
    return False


def _hallucination_risk(routing_type: str) -> str:
    return {
        ROUTE_KNOWLEDGE_BASE: "low",
        ROUTE_SAFE_RESPONSE:  "low",
        ROUTE_CREATIVE:       "low",
        ROUTE_HOSTILE_BLOCK:  "none",
        ROUTE_BOUNDARY:       "none",
        ROUTE_DEFAULT:        "prevented",
    }.get(routing_type, "unknown")
