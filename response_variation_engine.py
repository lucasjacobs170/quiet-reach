"""
response_variation_engine.py — Multi-template response selection engine.

Provides varied, context-aware response templates across different scenarios
to prevent the bot from sounding repetitive. Templates are organized by
topic and engagement level, and selection is randomized within each category.

Usage::

    engine = ResponseVariationEngine()

    # Get a varied greeting
    greeting = engine.get("greeting")

    # Get a context-aware response for a topic
    reply = engine.get("how_are_you")

    # Get a follow-up hook for a given topic
    hook = engine.get_followup("links")

    # Wrap an AI/KB reply with a personality-appropriate opener
    wrapped = engine.wrap_reply(reply, topic="lucas_info", exchange_count=3)
"""

from __future__ import annotations

import random
from typing import Optional


# ---------------------------------------------------------------------------
# Tunable thresholds
# ---------------------------------------------------------------------------

# Responses shorter than this (chars) are returned unchanged to avoid awkward wrapping.
MIN_WRAPPABLE_RESPONSE_LENGTH: int = 20

# exchange_count <= LOW_ENGAGEMENT_THRESHOLD → "low" wrapper
LOW_ENGAGEMENT_THRESHOLD: int = 1
# LOW < exchange_count <= MEDIUM_ENGAGEMENT_THRESHOLD → "medium" wrapper
MEDIUM_ENGAGEMENT_THRESHOLD: int = 3


# ---------------------------------------------------------------------------
# Template bank
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, list[str]] = {
    # Initial greetings — first-touch interactions
    "greeting": [
        "Hey! Glad you swung by — I'm Quiet Reach, Lucas's assistant. What can I do for you? 🌲",
        "Oh hey! You caught me at the perfect time. I'm here to help with anything Lucas-related — what's on your mind?",
        "What's up! I'm Quiet Reach — think of me as Lucas's digital sidekick. Ask away!",
        "Hey there! I'm Quiet Reach, and I'm all ears. What brings you here today?",
        "Yo! Quiet Reach here — Lucas's go-to assistant. What are you looking for? ⚡",
        "Hey — nice to see you! I'm here to help with anything Lucas: links, info, the whole deal. Where do you want to start?",
        "Oh, a visitor! I'm Quiet Reach — Lucas built me to be the friendliest guide around. What can I help you with?",
        "Hey! You've reached Quiet Reach — Lucas's assistant. Pretty good at this, so ask me anything 🙌",
    ],

    # Welfare-check greetings ("how are you?")
    "how_are_you": [
        "Doing great, thanks for asking! 🌲 What can I help you with?",
        "Pretty good — ready to help with anything Lucas-related. What's on your mind?",
        "All good over here! What brings you by today?",
        "Good, thanks! What can I do for you? ⚡",
        "Solid! Always here and ready. What are you looking for?",
        "Honestly, thriving. What can I help you with? 🙌",
    ],

    # Affirmations / acknowledgments — short confirms
    "affirmation": [
        "Got it!",
        "On it.",
        "Absolutely.",
        "Sure thing!",
        "No problem.",
        "You got it.",
        "Roger that.",
        "Easy — let me help.",
    ],

    # Follow-up prompts to keep the conversation going
    "followup_general": [
        "Anything else I can help with?",
        "That's what I'm here for — what else do you need?",
        "Feel free to ask more — I'm not going anywhere 🌿",
        "What else can I do for you?",
        "Got more questions? Fire away.",
        "Let me know if there's anything else.",
    ],

    # Offer-to-DM variations (less sales-y)
    "offer_dm": [
        "If you want the full picture, just DM me.",
        "I can send more over DM if you're curious.",
        "Hit me up in DMs for the specifics.",
        "Feel free to DM me for more detail.",
        "More info available in DM — just say the word.",
    ],

    # Closing statements
    "closing": [
        "Take care! Come back anytime.",
        "Nice chatting — feel free to reach out again.",
        "Later! Don't be a stranger 🌲",
        "See you around! Drop by whenever.",
        "Catch you next time — have a good one!",
    ],

    # For unknown/generic questions the bot can't fully answer
    "unknown_question": [
        "That one's outside my wheelhouse, but Lucas would know — Telegram or Discord works.",
        "Not sure on that one! Best bet is asking Lucas directly.",
        "Hmm, I don't have that info — try reaching Lucas on Telegram or Discord.",
        "That's a tough one for me. Lucas would be the one to ask — he's on Telegram and Discord.",
        "I honestly don't have that answer. Hit up Lucas directly for the best response.",
    ],

    # Engagement wrappers — low engagement (first couple exchanges)
    "wrapper_low": [
        "{response}",
        "{response} — let me know if you need more.",
        "{response} Hope that helps!",
    ],

    # Engagement wrappers — medium engagement
    "wrapper_medium": [
        "{response} What else can I do for you?",
        "{response} — anything else on your mind?",
        "{response} Feel free to keep going!",
    ],

    # Engagement wrappers — high engagement (deep conversation)
    "wrapper_high": [
        "{response} You're full of great questions! 🙌",
        "{response} — love the curiosity, keep it coming.",
        "{response} Nice! Anything else you want to dig into?",
    ],
}

# Follow-up hooks keyed by conversation topic
_FOLLOWUP_HOOKS: dict[str, list[str]] = {
    "lore": [
        "There's actually more to the story if you want the full picture — just say `full story`.",
        "Curious type, I like it. Want to go deeper? Just say `full story` and I'll lay it all out.",
        "That's the short version — the full lore goes way further. Say `full story` if you're up for it.",
    ],
    "links": [
        "Those are the best ways to find him. Anything specific you're looking for?",
        "Let me know if you want the breakdown on any of those — happy to explain what each one's about.",
        "Got it — if you're wondering which platform to check first, I can point you in the right direction.",
    ],
    "lucas_info": [
        "Anything else you want to know about Lucas? I've got the full rundown.",
        "Happy to go deeper on any of that — just ask.",
        "That's the highlight reel. Want more detail on a specific part?",
    ],
    "general": [
        "Anything else I can help with?",
        "That's what I'm here for — what else do you need?",
        "Feel free to ask more — I'm not going anywhere 🌿",
    ],
}


# ---------------------------------------------------------------------------
# ResponseVariationEngine
# ---------------------------------------------------------------------------

class ResponseVariationEngine:
    """
    Selects varied response templates to prevent repetitive bot replies.

    Provides context-aware template selection based on conversation topic
    and engagement level.
    """

    def get(self, category: str, fallback: str = "") -> str:
        """
        Return a random response from *category*.

        Parameters
        ----------
        category : str
            A key from the template bank (e.g. ``"greeting"``, ``"how_are_you"``).
        fallback : str
            Returned as-is when *category* is not found and no fallback
            templates exist.

        Returns
        -------
        str
            A randomly selected response string.
        """
        templates = _TEMPLATES.get(category)
        if templates:
            return random.choice(templates)
        return fallback

    def get_followup(self, topic: str = "general") -> str:
        """
        Return a context-appropriate follow-up hook for *topic*.

        Parameters
        ----------
        topic : str
            Conversation topic. One of: ``"lore"``, ``"links"``,
            ``"lucas_info"``, ``"general"``.

        Returns
        -------
        str
            A short follow-up prompt.
        """
        hooks = _FOLLOWUP_HOOKS.get(topic) or _FOLLOWUP_HOOKS["general"]
        return random.choice(hooks)

    def wrap_reply(
        self,
        response: str,
        topic: str = "general",
        exchange_count: int = 1,
    ) -> str:
        """
        Wrap *response* in an engagement-appropriate template.

        Selects a wrapper based on conversation depth (exchange_count) and
        appends a follow-up hook for deeper conversations.

        Parameters
        ----------
        response : str
            The reply text to wrap.
        topic : str
            Conversation topic for follow-up hook selection.
        exchange_count : int
            Number of exchanges so far (used to pick engagement level).

        Returns
        -------
        str
            The wrapped response. If *response* is too short
            (≤ ``MIN_WRAPPABLE_RESPONSE_LENGTH`` chars), it is returned
            unchanged to avoid awkward wrapping.
        """
        if not response or len(response.strip()) <= MIN_WRAPPABLE_RESPONSE_LENGTH:
            return response

        if exchange_count <= LOW_ENGAGEMENT_THRESHOLD:
            wrapper = random.choice(_TEMPLATES["wrapper_low"])
        elif exchange_count <= MEDIUM_ENGAGEMENT_THRESHOLD:
            wrapper = random.choice(_TEMPLATES["wrapper_medium"])
        else:
            wrapper = random.choice(_TEMPLATES["wrapper_high"])

        return wrapper.replace("{response}", response.strip())


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_engine: Optional[ResponseVariationEngine] = None


def get_variation_engine() -> ResponseVariationEngine:
    """Return the module-level singleton :class:`ResponseVariationEngine`."""
    global _default_engine
    if _default_engine is None:
        _default_engine = ResponseVariationEngine()
    return _default_engine
