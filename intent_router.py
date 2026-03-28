"""
intent_router.py — Routes incoming messages to the appropriate response type.

Uses IntentClassifier for hostility/tone detection and applies additional
routing logic to distinguish information requests, social queries, and
casual conversation.

Routing decision order:
  1. Hostility check      — block or apply boundary
  2. Social media links   — Instagram + X only (filtered)
  3. Information          — answer from verified knowledge_base.json
  4. Casual               — reply from safe_responses.json (± light creativity)
  5. Special topics       — hostile-handling, bot capabilities
  6. AI fallback          — personality-wrapped response for unhandled intents
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

try:
    from personality_manager import get_personality_manager as _get_pm
    _PM_AVAILABLE = True
except ImportError:
    _PM_AVAILABLE = False

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
    "clearly_hostile":        "Direct insults, attacks",
    "mildly_frustrated":      "Annoyed but not attacking",
    "sarcastic_cutting":      "Sarcastic/sharp but not pure attack",
    "asks_about_lucas":       "Questions about who Lucas is, what he does",
    "asks_for_links":         "Wants social media links",
    "asks_for_social_links":  "Wants only Instagram + X social links",
    "asks_for_help":          "Wants bot to help with something",
    "asks_about_hostility":   "Asking how bot handles hostile/mean people",
    "asks_about_capabilities":"Questions about what bot can/cannot do",
    "casual_greeting":        "Hi, hello, hey",
    "casual_gratitude":       "Thanks, appreciate it",
    "casual_goodbye":         "Bye, see you, catch you",
    "small_talk":             "General conversation, observations",
    "unclear":                "Can't determine intent",
}

# Keywords used to widen intent detection beyond the base classifier categories
_LINK_KEYWORDS: list[str] = [
    "link", "links", "url", "website", "follow", "find", "socials",
    "chaturbate", "onlyfans", "twitter", "instagram", "discord", "telegram",
    "x.com", "platform", "profile",
]

# Social-media-only keywords: triggers "asks_for_social_links" (Instagram + X)
# These are checked before general link keywords so they take priority.
_SOCIAL_MEDIA_ONLY_KEYWORDS: list[str] = [
    "social media", "socials", "social links", "your socials",
    "his socials", "social platforms",
]
# Single-word social handles that alone indicate a social-only request
_SOCIAL_SINGLE_WORDS: list[str] = ["twitter", "instagram"]

_LUCAS_INFO_KEYWORDS: list[str] = [
    "lucas", "tell me about lucas", "about lucas", "does lucas", "lucas do",
    "content", "stream", "show", "game", "ranch", "woods", "ocean",
    "surf", "jenga", "darts", "hottub", "shower", "onlyfans", "chaturbate",
]

# Hostile-handling detection: user asks how bot deals with mean/rude people
_HOSTILE_HANDLING_KEYWORDS: list[str] = [
    "hostile people", "mean people", "rude people", "handle hostile",
    "handle mean", "handle rude", "if someone is mean", "when someone is rude",
    "what do you do if", "how do you deal with", "how do you handle hostile",
    "how do you handle mean", "how do you handle rude", "mean users",
    "rude users", "someone being rude", "someone being mean",
    "someone being hostile",
]

# Bot capabilities / limitations detection
_BOT_CAPABILITIES_KEYWORDS: list[str] = [
    "what can you do", "what can't you do", "what cant you do",
    "your capabilities", "your limitations", "what are you capable of",
    "what do you know", "what don't you know", "what dont you know",
    "how smart are you", "what can you help with", "your abilities",
    "what you can do", "what you cant do",
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
            response = self._apply_personality(response, topic="lucas_info")
            self._record(user_key, extended_intent, user_message, response, topic="lucas_info")
            return response, ROUTE_KNOWLEDGE_BASE

        if extended_intent == "asks_for_social_links":
            response = self._get_social_links()
            self._record(user_key, extended_intent, user_message, response, topic="links")
            return response, ROUTE_KNOWLEDGE_BASE

        if extended_intent == "asks_for_links":
            response = self._handle_links_request(user_key)
            self._record(user_key, extended_intent, user_message, response, topic="links")
            return response, ROUTE_KNOWLEDGE_BASE

        if extended_intent == "asks_for_help":
            response = self._get_response("greetings")
            response = self._apply_personality(response, topic="general")
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_SAFE_RESPONSE

        # Special topics
        if extended_intent == "asks_about_hostility":
            response = self._get_response("hostile_handling")
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_SAFE_RESPONSE

        if extended_intent == "asks_about_capabilities":
            response = self._get_response("bot_capabilities")
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

        # 4. Comprehensive fallback — unclear intent still gets a response
        # Try a personality-enhanced fallback before the generic unclear_question.
        response = self._get_response("unclear_question")
        response = self._apply_personality(response, topic="general")
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

        # Social-media-only links (Instagram + X) — check before general link keywords
        if _matches_any(t, _SOCIAL_MEDIA_ONLY_KEYWORDS):
            return "asks_for_social_links"
        # Single-word social handles only when no other platform keywords are present
        if (_matches_any(t, _SOCIAL_SINGLE_WORDS)
                and not _matches_any(t, ["chaturbate", "onlyfans", "discord", "telegram"])):
            return "asks_for_social_links"

        # General link request
        if _matches_any(t, _LINK_KEYWORDS):
            return "asks_for_links"

        # Hostile-handling question
        if _matches_any(t, _HOSTILE_HANDLING_KEYWORDS):
            return "asks_about_hostility"

        # Bot capabilities / limitations
        if _matches_any(t, _BOT_CAPABILITIES_KEYWORDS):
            return "asks_about_capabilities"

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

    def _get_social_links(self) -> str:
        """Return ONLY Instagram and X (Twitter) links — the social-media-only response."""
        platforms = self.knowledge_base["platforms"]["primary"]

        social_names = {"X (Twitter)", "Instagram"}
        social_lines: list[str] = []
        for p in platforms:
            if p.get("name") in social_names:
                social_lines.append(f"📱 {p['name']}: {p['url']}")

        if not social_lines:
            # Fallback if KB structure differs
            return "Lucas is active on X and Instagram — let me know if you want the specific links!"

        intro = random.choice([
            "Here are his social media links 📱",
            "Sure! Here's where to find Lucas on social media:",
            "His socials right here 👇",
        ])
        return intro + "\n\n" + "\n".join(social_lines)

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
        responses = self.safe_responses.get("small_talk", [
            "That sounds cool!",
            "I like where your head's at",
            "Ha, fair point!",
            "You're right about that",
            "Nice one!",
        ])
        return random.choice(responses)

    def _record(self, user_key: str, intent: str, message: str, response: str, topic: str = "") -> None:
        """Record a completed request/response pair in the conversation context."""
        if user_key and self._ctx:
            self._ctx.record(user_key=user_key, intent=intent, message=message, response=response, topic=topic)

    def _get_response(self, category: str) -> str:
        """Return a random response from the given safe_responses category."""
        options = self.safe_responses.get(category, ["I'm not sure. Feel free to ask Lucas!"])
        return random.choice(options)

    def _apply_personality(self, response: str, topic: str = "general") -> str:
        """Apply personality overlay if personality_manager is available."""
        if _PM_AVAILABLE:
            try:
                return _get_pm().apply(response, category=topic)
            except Exception:
                pass
        return response


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
