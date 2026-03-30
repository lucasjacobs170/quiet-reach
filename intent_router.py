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
  5. Final fallback   — every message gets a response (no silent failures)
"""

from __future__ import annotations

import json
import os
import re
import random
from typing import Optional

import requests

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
ROUTE_PLATFORM_INFO  = "platform_info"

# ---------------------------------------------------------------------------
# Ollama configuration (for generating contextual replies)
# ---------------------------------------------------------------------------

_OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
_OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
_OLLAMA_TIMEOUT: int = 10  # seconds — keep short for real-time chat

# System prompt used when asking Ollama to generate a response.
# Guardrails: never invent links/URLs, stay on-brand, keep answers short.
_OLLAMA_SYSTEM_PROMPT = (
    "You are Quiet Reach, a helpful assistant for Lucas Jacobs, a content creator. "
    "Keep responses short (1-3 sentences), warm, and on-brand. "
    "NEVER invent URLs or links — if a user asks for links, tell them you'll DM them. "
    "NEVER make up facts about Lucas. Only mention things you are certain about. "
    "If you don't know something, say so honestly."
)

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
    "asks_for_links":         "Wants all platform links",
    "asks_for_socials":       "Wants social media (Instagram + X) links only",
    "asks_platform_all":      "Wants all platforms with descriptions (location/social-intent queries)",
    "asks_platform_specific": "Asks about a specific named platform",
    "asks_for_help":          "Wants bot to help with something",
    "asks_about_bot":         "Questions about the bot's personality, capabilities, or nature",
    "asks_hostile_handling":  "How does the bot handle mean/hostile people?",
    "casual_greeting":        "Hi, hello, hey",
    "casual_gratitude":       "Thanks, appreciate it",
    "casual_goodbye":         "Bye, see you, catch you",
    "small_talk":             "General conversation, observations",
    "unclear":                "Can't determine intent",
}

# Keywords used to widen intent detection beyond the base classifier categories

# Social-media-only keywords (Instagram + X): checked BEFORE general link keywords
# so "socials"/"social media" requests return only those two platforms.
_SOCIAL_ONLY_KEYWORDS: list[str] = [
    "socials", "social media", "social links", "your socials",
    "twitter", "x account",
]

_LINK_KEYWORDS: list[str] = [
    "link", "links", "url", "website", "follow", "find",
    "chaturbate", "onlyfans", "instagram", "discord", "telegram",
    "x.com", "platform", "profile",
]

_LUCAS_INFO_KEYWORDS: list[str] = [
    "lucas", "tell me about", "about lucas", "does lucas", "lucas do",
    "content", "stream", "show", "game", "ranch", "woods", "ocean",
    "surf", "jenga", "darts", "hottub", "shower", "onlyfans", "chaturbate",
]

_BOT_CAPABILITIES_KEYWORDS: list[str] = [
    "what can you do", "what do you do", "what are you", "who are you",
    "tell me about you", "about you", "your capabilities", "what are your",
    "what's your purpose", "whats your purpose", "your purpose",
    "are you a bot", "you a bot", "how do you work",
]

_HOSTILE_HANDLING_KEYWORDS: list[str] = [
    "mean people", "hostile people", "handle hate", "handle hostility",
    "how do you handle", "when people are mean", "rude people",
    "how do you deal with", "bad people", "trolls",
]

_GREETING_KEYWORDS: list[str] = ["hi", "hey", "hello", "sup", "yo", "what's up", "howdy", "how are you", "how r you"]
_GRATITUDE_KEYWORDS: list[str] = ["thanks", "thank you", "thx", "appreciate", "ty", "cheers"]
_GOODBYE_KEYWORDS: list[str] = ["bye", "goodbye", "see you", "later", "catch you", "peace", "cya"]
_HELP_KEYWORDS: list[str] = ["help", "assist", "can you", "need info", "need help"]

# Location-intent keywords — multi-word phrases that signal the user wants to
# know WHERE to find Lucas across platforms.
_LOCATION_KEYWORDS: list[str] = [
    "where can i find", "where is he", "where do i find", "find him",
    "how do i find", "anywhere else", "where can you be found",
    "where to find", "where can he be found", "find you",
]

# "All platforms" keywords — user wants a comprehensive list of all platforms
# with descriptions rather than a bare link dump.
_ALL_PLATFORMS_KEYWORDS: list[str] = [
    "all platforms", "all links", "all socials", "everywhere", "all of them",
    "all your links", "all his links", "what platforms", "what sites",
    "which platforms", "every platform", "social media", "is he on",
]


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

        # Platform keywords — optional; gracefully degraded when missing.
        # When the file is absent the bot falls back to the legacy _get_links()
        # method for platform queries; keyword lists fall back to the module-level
        # defaults defined below this class.
        pk_path = os.path.join(base_dir, "platform_keywords.json")
        try:
            self.platform_keywords: dict = _load_json(pk_path, "platform_keywords.json")
        except (FileNotFoundError, ValueError):
            self.platform_keywords = {}

        # Keyword lists loaded from JSON so platform_keywords.json is the single
        # source of truth; module-level constants serve only as fallback defaults.
        self._location_kws: list[str] = self.platform_keywords.get(
            "location_keywords", _LOCATION_KEYWORDS
        )
        self._all_platforms_kws: list[str] = self.platform_keywords.get(
            "all_platforms_keywords", _ALL_PLATFORMS_KEYWORDS
        )

        # Pre-compile per-platform regex patterns once at init for efficiency.
        self._platform_patterns: list[tuple[dict, re.Pattern]] = []
        for p in self.platform_keywords.get("platforms", []):
            parts = []
            for kw in p.get("keywords", []):
                if " " in kw:
                    parts.append(re.escape(kw))
                else:
                    parts.append(r"\b" + re.escape(kw) + r"\b")
            if parts:
                pattern = re.compile("|".join(parts))
                self._platform_patterns.append((p, pattern))

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

    def route_message(
        self,
        user_message: str,
        user_key: str = "",
        is_group_chat: bool = False,
    ) -> tuple[str, str]:
        """
        Route *user_message* to the appropriate response.

        Parameters
        ----------
        user_message : str
            Raw message from the user.
        user_key : str
            Opaque per-user identifier used for conversation-context tracking.
            Pass an empty string to skip context tracking.
        is_group_chat : bool
            When True, social/link requests redirect to DM instead of sharing
            links directly.  Group chats should never expose raw URLs.

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

        # 0. Platform detection — takes priority over all other routing, including
        #    hostility checks.  A message mentioning a specific platform always
        #    returns the relevant link regardless of the classifier's tone label.
        #    This ensures messages like "how about his onlyfans?" or "i want his
        #    twitter" are never silently dropped due to a misclassified tone.
        _t = user_message.lower()
        _platform_intent: Optional[str] = None
        if _matches_any(_t, self._location_kws) or _matches_any(_t, self._all_platforms_kws):
            _platform_intent = "asks_platform_all"
        elif self._detect_platform(user_message) is not None:
            _platform_intent = "asks_platform_specific"

        if _platform_intent is not None:
            if is_group_chat:
                response = self._get_group_links_redirect()
            elif _platform_intent == "asks_platform_all":
                response = self._handle_platform_all_request()
            else:
                response = self._handle_platform_specific_request(user_message)
            self._record(user_key, _platform_intent, user_message, response, topic="links")
            return response, ROUTE_PLATFORM_INFO

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
        if extended_intent == "asks_platform_all":
            if is_group_chat:
                response = self._get_group_links_redirect()
            else:
                response = self._handle_platform_all_request()
            self._record(user_key, extended_intent, user_message, response, topic="links")
            return response, ROUTE_PLATFORM_INFO

        if extended_intent == "asks_platform_specific":
            if is_group_chat:
                response = self._get_group_links_redirect()
            else:
                response = self._handle_platform_specific_request(user_message)
            self._record(user_key, extended_intent, user_message, response, topic="links")
            return response, ROUTE_PLATFORM_INFO

        if extended_intent == "asks_about_lucas":
            response = self._answer_about_lucas(user_message)
            response = self._apply_personality(response, topic="lucas_info")
            self._record(user_key, extended_intent, user_message, response, topic="lucas_info")
            return response, ROUTE_KNOWLEDGE_BASE

        if extended_intent == "asks_for_socials":
            if is_group_chat:
                response = self._get_group_links_redirect()
            else:
                response = self._handle_socials_request()
            self._record(user_key, extended_intent, user_message, response, topic="links")
            return response, ROUTE_KNOWLEDGE_BASE

        if extended_intent == "asks_for_links":
            if is_group_chat:
                response = self._get_group_links_redirect()
            else:
                response = self._handle_links_request(user_key)
            self._record(user_key, extended_intent, user_message, response, topic="links")
            return response, ROUTE_KNOWLEDGE_BASE

        if extended_intent == "asks_hostile_handling":
            response = self._get_response("hostile_handling")
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_SAFE_RESPONSE

        if extended_intent == "asks_about_bot":
            # Use dedicated bot_intro template when available; fall back to
            # bot_capabilities + proactive_platform_intro for older deployments.
            if self.safe_responses.get("bot_intro"):
                response = self._get_response("bot_intro")
            else:
                bot_response = self._get_response("bot_capabilities")
                if self.safe_responses.get("proactive_platform_intro"):
                    platform_intro = self._get_response("proactive_platform_intro")
                    response = f"{bot_response}\n\n{platform_intro}"
                else:
                    response = bot_response
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_SAFE_RESPONSE

        if extended_intent == "asks_for_help":
            response = self._get_response("greetings")
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_SAFE_RESPONSE

        # 3. Casual routing (safe responses / light creativity)
        if extended_intent == "casual_greeting":
            # Use dedicated friendly_greeting template when available so that
            # "how are you?" and similar messages receive a natural reply.
            # Falls back to proactive_platform_intro / greetings for older deployments.
            if self.safe_responses.get("friendly_greeting"):
                response = self._get_response("friendly_greeting")
            elif self.safe_responses.get("proactive_platform_intro"):
                response = self._get_response("proactive_platform_intro")
            else:
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

        # Unknown question (has "?" but no matching topic) — try Ollama first
        if extended_intent == "unknown_question":
            ollama_reply = self._generate_with_ollama(user_message)
            if ollama_reply:
                response = self._apply_personality(ollama_reply)
                self._record(user_key, extended_intent, user_message, response)
                return response, ROUTE_CREATIVE
            response = self._get_response("i_dont_know")
            self._record(user_key, extended_intent, user_message, response)
            return response, ROUTE_SAFE_RESPONSE

        # 4. Default fallback — every message must get a response
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
                "verified_facts":   routing_type in (ROUTE_KNOWLEDGE_BASE, ROUTE_PLATFORM_INFO),
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

        # Location queries — multi-word phrases signalling "where to find Lucas"
        # These take priority so "find him" etc. always returns full platform info.
        if _matches_any(t, self._location_kws):
            return "asks_platform_all"

        # All-platforms / comprehensive social-media queries
        if _matches_any(t, self._all_platforms_kws):
            return "asks_platform_all"

        # Specific platform name mentioned → platform-specific response
        if self._detect_platform(message) is not None:
            return "asks_platform_specific"

        # Social-only keywords checked first (before general link keywords)
        # so "socials"/"social media" returns Instagram + X, not the full list.
        if _matches_any(t, _SOCIAL_ONLY_KEYWORDS):
            return "asks_for_socials"

        if _matches_any(t, _LINK_KEYWORDS):
            return "asks_for_links"

        if _matches_any(t, _LUCAS_INFO_KEYWORDS):
            return "asks_about_lucas"

        if _matches_any(t, _HOSTILE_HANDLING_KEYWORDS):
            return "asks_hostile_handling"

        if _matches_any(t, _BOT_CAPABILITIES_KEYWORDS):
            return "asks_about_bot"

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

        # Longer messages with no clear intent → treat as small talk too
        # (ensures every message gets a response instead of the unclear default)
        return "small_talk"

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

    def _get_group_links_redirect(self) -> str:
        """
        Return a DM-redirect message for group chats.

        Links are never shared in group chats; instead the user is directed
        to open a private conversation with the bot.
        """
        redirects = [
            "I keep links out of group chat to avoid spam 📵 — message me privately and I'll send them over!",
            "Links are DM-only 🔒 — shoot me a private message and I'll share everything you need.",
            "I don't drop links in public chats — DM me and I'll send the full list right away! 📲",
            "Sharing links privately keeps things tidy here — DM me and I'll hook you up! 🤫",
        ]
        return random.choice(redirects)

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

    def _handle_socials_request(self) -> str:
        """
        Return only social media links (Instagram + X/Twitter).

        Used when the user asks for "socials", "social media", "twitter", or
        similar — they want the public social accounts, not OnlyFans/Discord.
        """
        platforms = self.knowledge_base["platforms"]["primary"]
        social_names = {"X (Twitter)", "Instagram"}
        social_platforms = [p for p in platforms if p["name"] in social_names]

        lines = ["Here are Lucas's socials 📱\n"]
        for p in social_platforms:
            lines.append(f"🔗 {p['name']}: {p['url']}")

        lines.append(
            "\nIf you want everything (OnlyFans, Chaturbate, Discord too), just ask for `all links`."
        )
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

    def _detect_platform(self, text: str) -> Optional[dict]:
        """
        Return the first platform entry whose keywords appear in *text*, or None.

        *text* is lowercased internally so callers do not need to pre-normalise.
        Uses pre-compiled regex patterns built during __init__ for efficiency.
        """
        t = text.lower()
        for platform, pattern in self._platform_patterns:
            if pattern.search(t):
                return platform
        return None

    def _format_platform_entry(self, platform: dict) -> str:
        """Return a single formatted line for a platform (emoji + name + description + link)."""
        emoji = platform.get("emoji", "🔗")
        name  = platform["display_name"]
        desc  = platform.get("description", "")

        if platform.get("is_handle"):
            link_part = platform["url"]
        elif "free_url" in platform and "paid_url" in platform:
            link_part = (
                f"Free: {platform['free_url']}  |  Paid: {platform['paid_url']}"
            )
        else:
            link_part = platform.get("url", "")

        return f"{emoji} **{name}**: {desc} — {link_part}"

    def _handle_platform_all_request(self) -> str:
        """
        Return all platforms with descriptions, used for location and
        comprehensive social-media queries.
        """
        platforms = self.platform_keywords.get("platforms", [])
        if not platforms:
            # Graceful fallback when platform_keywords.json is absent
            return self._get_links()

        intro = random.choice(
            self.safe_responses.get(
                "platform_all_intro",
                ["You can find Lucas on these platforms! Here's what he offers on each:\n"],
            )
        )
        lines = [intro]
        for p in platforms:
            lines.append(self._format_platform_entry(p))

        followup = random.choice(
            self.safe_responses.get(
                "platform_followup",
                ["Curious about a specific platform? Just ask and I'll tell you more! 😊"],
            )
        )
        lines.append(f"\n{followup}")
        return "\n".join(lines)

    def _handle_platform_specific_request(self, user_message: str) -> str:
        """
        Return information about the specific platform mentioned in *user_message*.

        Falls back to _handle_platform_all_request() when no specific platform
        can be identified.
        """
        platform = self._detect_platform(user_message)
        if not platform:
            return self._handle_platform_all_request()

        emoji = platform.get("emoji", "🔗")
        name  = platform["display_name"]
        desc  = platform.get("description", "")

        if platform.get("is_handle"):
            link_text = f"You can reach Lucas on Telegram at {platform['url']} 💌"
        elif "free_url" in platform and "paid_url" in platform:
            link_text = (
                f"Free tier: {platform['free_url']}\n"
                f"Paid tier: {platform['paid_url']}"
            )
        else:
            link_text = platform.get("url", "")

        lines = [
            f"{emoji} **{name}** — {desc}",
            "",
            link_text,
            "",
            "Want links to his other platforms too? Just ask! 🙌",
        ]
        return "\n".join(lines)

    def _handle_small_talk(self, user_message: str, user_key: str = "") -> str:
        """Handle small talk with light, grounded creativity.

        If the user has sent several unanswered requests, proactively offer help
        instead of a generic small-talk reply.

        When Ollama is available, generate a contextual response. Otherwise fall
        back to pre-written safe responses.
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

        # Try Ollama for a contextual reply first
        ollama_reply = self._generate_with_ollama(user_message)
        if ollama_reply:
            return ollama_reply

        responses = self.safe_responses.get("small_talk", [
            "That sounds cool!",
            "I like where your head's at",
            "Ha, fair point!",
            "You're right about that",
            "Nice one!",
        ])
        return random.choice(responses)

    def _generate_with_ollama(self, user_message: str) -> str:
        """
        Ask Ollama to generate a short, grounded conversational reply.

        Guardrails applied:
          - Short system prompt prevents hallucination of links / facts.
          - Reply is rejected if it contains a URL (likely hallucinated).
          - Returns an empty string when Ollama is unavailable or generates
            a response that fails guardrail checks.
        """
        prompt = (
            f"{_OLLAMA_SYSTEM_PROMPT}\n\n"
            f"User: {user_message.strip()[:400]}\n"
            "Assistant:"
        )
        try:
            resp = requests.post(
                f"{_OLLAMA_URL}/api/generate",
                json={"model": _OLLAMA_MODEL, "prompt": prompt, "stream": False},
                timeout=_OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            reply = (resp.json().get("response") or "").strip()

            # Guardrail: reject if empty or too short
            if not reply or len(reply) < 8:
                return ""

            # Guardrail: reject replies that contain URLs (hallucinated links)
            if re.search(r"https?://|www\.", reply, re.IGNORECASE):
                return ""

            # Guardrail: truncate very long replies to keep responses snappy
            if len(reply) > 400:
                # Cut at the last sentence boundary within 400 chars
                truncated = reply[:400]
                last_period = truncated.rfind(".")
                reply = truncated[: last_period + 1] if last_period > 50 else truncated

            return reply

        except Exception:
            return ""  # Ollama unavailable — caller uses safe_responses fallback

    def _record(self, user_key: str, intent: str, message: str, response: str, topic: str = "") -> None:
        """Record a completed request/response pair in the conversation context."""
        if user_key and self._ctx:
            self._ctx.record(user_key=user_key, intent=intent, message=message, response=response, topic=topic)

    def _get_response(self, category: str) -> str:
        """Return a random response from the given safe_responses category."""
        options = self.safe_responses.get(category, ["I'm not sure. Feel free to ask Lucas!"])
        return random.choice(options)

    def _apply_personality(self, response: str, topic: str = "") -> str:
        """Overlay personality flair onto a response using PersonalityManager if available."""
        if _PM_AVAILABLE:
            try:
                return _get_pm().overlay_personality(response, topic=topic)
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
        ROUTE_PLATFORM_INFO:  "low",
        ROUTE_HOSTILE_BLOCK:  "none",
        ROUTE_BOUNDARY:       "none",
        ROUTE_DEFAULT:        "prevented",
    }.get(routing_type, "unknown")
