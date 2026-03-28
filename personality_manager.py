"""
personality_manager.py — Personality and boot-response management.

Loads personality configuration and boot responses from JSON files and
provides helpers to:
  - Select a random startup message for the on_ready event
  - Apply the current mood's emoji palette / tone to a response string
  - Switch moods at runtime
  - Return varied initial DM greetings with conversational hooks
  - Overlay personality onto AI-generated replies
  - Provide context-aware follow-up hooks

Usage::

    pm = PersonalityManager()

    # On bot startup
    print(pm.get_startup_message())   # → "🌲 Quiet Reach is live — let's get wild!"

    # Get a varied initial greeting for a new DM user
    print(pm.get_initial_dm_greeting())

    # Optionally apply personality to an outgoing response
    resp = pm.apply("Here are Lucas's links", category="greetings")

    # Overlay personality on an AI-generated reply
    resp = pm.overlay_personality(ai_reply, topic="links", exchange_count=2)
"""

from __future__ import annotations

import json
import os
import random
from typing import Optional


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BASE_DIR = os.path.dirname(__file__)
_PERSONALITY_CONFIG_PATH = os.path.join(_BASE_DIR, "personality_config.json")
_BOOT_RESPONSES_PATH = os.path.join(_BASE_DIR, "boot_responses.json")


# ---------------------------------------------------------------------------
# PersonalityManager
# ---------------------------------------------------------------------------

# Emojis and characters that indicate the response already has a closing symbol.
# If the last character of a response is in this set, no emoji is appended.
_RESPONSE_END_SKIP: frozenset[str] = frozenset(
    "!?😊🙌🔥🌲🏕️⛰️🌊✨🎪🌿🌙🔮👀🌌🎉😄😂⚡"
)


# Minimum response length for personality overlay to be applied (characters).
# Responses shorter than this are returned as-is to avoid awkward wrapping.
_MIN_OVERLAY_LENGTH: int = 20


class PersonalityManager:
    """
    Manages bot personality state and provides helpers for personalising
    outgoing responses.

    Attributes
    ----------
    config : dict
        Loaded personality_config.json content.
    boot : dict
        Loaded boot_responses.json content.
    current_mood : str
        Active mood key (e.g. ``"upbeat"``).
    """

    def __init__(
        self,
        personality_path: str = "",
        boot_path: str = "",
    ) -> None:
        self.config = _load_json(personality_path or _PERSONALITY_CONFIG_PATH)
        self.boot = _load_json(boot_path or _BOOT_RESPONSES_PATH)
        self.current_mood: str = self.config.get("default_mood", "upbeat")

    # ------------------------------------------------------------------
    # Mood management
    # ------------------------------------------------------------------

    def set_mood(self, mood: str) -> None:
        """Set the active mood.  Falls back to the default if unknown."""
        available = self.config.get("moods", {})
        if mood in available:
            self.current_mood = mood
        else:
            self.current_mood = self.config.get("default_mood", "upbeat")

    def random_mood(self) -> str:
        """Pick a random mood, set it as active, and return its key."""
        moods = list(self.config.get("moods", {}).keys())
        if moods:
            self.set_mood(random.choice(moods))
        return self.current_mood

    def get_mood_indicator(self) -> str:
        """Return the emoji + label string for the current mood."""
        indicators = self.boot.get("mood_indicators", {})
        return indicators.get(self.current_mood, "")

    # ------------------------------------------------------------------
    # Startup / shutdown
    # ------------------------------------------------------------------

    def get_startup_message(self) -> str:
        """Return a random startup message from boot_responses.json."""
        messages = self.boot.get("startup_messages", ["Bot is online."])
        return random.choice(messages)

    def get_shutdown_message(self) -> str:
        """Return a random shutdown message from boot_responses.json."""
        messages = self.boot.get("shutdown_messages", ["Bot is going offline."])
        return random.choice(messages)

    # ------------------------------------------------------------------
    # Initial greetings
    # ------------------------------------------------------------------

    def get_initial_dm_greeting(self) -> str:
        """
        Return a varied, energetic initial DM greeting with a conversational hook.

        These are used for first-touch interactions to avoid the generic
        "I'm Lucas's assistant" opener.
        """
        greetings = self.config.get("initial_greetings", [
            "Hey! I'm Quiet Reach — Lucas's assistant. What can I help you with? 🌲",
            "Hey there! What brings you here today?",
            "Hi! I'm here to help with anything Lucas-related — ask away!",
        ])
        return random.choice(greetings)

    def get_followup_hook(self, topic: str = "general") -> str:
        """
        Return a natural follow-up hook appropriate for the given topic.

        Parameters
        ----------
        topic : str
            The conversation topic. One of: ``"lore"``, ``"links"``,
            ``"lucas_info"``, ``"general"``.

        Returns
        -------
        str
            A short follow-up prompt to keep the conversation going.
        """
        hooks = self.config.get("followup_hooks", {})
        topic_hooks = hooks.get(topic) or hooks.get("general") or [
            "Anything else I can help with?"
        ]
        return random.choice(topic_hooks)

    # ------------------------------------------------------------------
    # Response application
    # ------------------------------------------------------------------

    def apply(self, response: str, category: str = "") -> str:
        """
        Optionally append a mood-appropriate emoji to *response*.

        The emoji is added only when the response doesn't already end with
        an emoji or punctuation character, to avoid doubling up.

        Parameters
        ----------
        response : str
            The outgoing response text.
        category : str
            Optional hint about the response type (``"greetings"``,
            ``"boundary_responses"``, etc.).  Currently unused but reserved
            for future category-specific tone adjustments.

        Returns
        -------
        str
            The (possibly decorated) response string.
        """
        if not response:
            return response

        mood_data = self.config.get("moods", {}).get(self.current_mood, {})
        palette = mood_data.get("emoji_palette", [])
        if not palette:
            return response

        # Don't add an emoji if the response already ends with one or with a
        # common punctuation mark that closes the sentence cleanly.
        last_char = response.rstrip()[-1] if response.rstrip() else ""
        if last_char in _RESPONSE_END_SKIP:
            return response

        return response + " " + random.choice(palette)

    def overlay_personality(
        self,
        response: str,
        topic: str = "",
        exchange_count: int = 1,
    ) -> str:
        """
        Overlay personality flair onto an AI-generated reply.

        Adds a context-appropriate prefix and/or suffix drawn from
        ``personality_config.json`` based on conversation engagement level.
        Does not modify responses that already start with a casual opener or
        are very short (≤ 20 chars).

        Parameters
        ----------
        response : str
            The AI-generated reply text.
        topic : str
            Conversation topic hint (e.g. ``"links"``, ``"lucas_info"``).
            Used to select a follow-up hook.
        exchange_count : int
            Number of exchanges so far in this conversation (used to pick
            an engagement-appropriate wrapper).

        Returns
        -------
        str
            The response with personality flair applied.
        """
        if not response or len(response.strip()) <= _MIN_OVERLAY_LENGTH:
            return response

        # Determine engagement level
        if exchange_count <= 1:
            level = "low"
        elif exchange_count <= 3:
            level = "medium"
        else:
            level = "high"

        wrappers = self.config.get("engagement_wrappers", {})
        level_wrappers = wrappers.get(level, ["{response}"])
        template = random.choice(level_wrappers)

        result = template.replace("{response}", response.strip())

        # Apply mood emoji if appropriate
        result = self.apply(result, category=topic)
        return result


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_manager: Optional[PersonalityManager] = None


def get_personality_manager() -> PersonalityManager:
    """Return the module-level singleton :class:`PersonalityManager`."""
    global _default_manager
    if _default_manager is None:
        _default_manager = PersonalityManager()
    return _default_manager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: str) -> dict:
    """Load a JSON file; return an empty dict on any error."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"⚠️ personality_manager: could not load '{path}': {exc}")
        return {}
