"""
conversation_context.py — Per-user conversation state and request-pattern tracking.

Tracks what each user has asked for during a session so that the bot can:
  - Acknowledge repeated requests rather than staying silent ("I already shared those links")
  - Detect escalating or suspicious patterns (e.g. same request 4+ times in 2 minutes)
  - Provide context to downstream modules (intent_router, hostility_handler)

This module is intentionally lightweight (in-memory only).  State is scoped to
the lifetime of the bot process; it is not persisted to disk.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Per-request snapshot
# ---------------------------------------------------------------------------

@dataclass
class RequestRecord:
    """A single user message and how the bot responded."""
    intent: str          # Extended intent string from IntentRouter
    message: str         # Raw user message
    response: str        # Bot response that was sent
    timestamp: float     # monotonic clock value at the time of the request


# ---------------------------------------------------------------------------
# Per-user conversation state
# ---------------------------------------------------------------------------

@dataclass
class ConversationState:
    """
    Mutable state for a single user across their current conversation.

    Attributes
    ----------
    history : list[RequestRecord]
        All recorded request/response pairs in chronological order.
    link_request_count : int
        How many times this user has asked for links in this session.
    link_last_sent : float | None
        Monotonic timestamp of the most recent time links were sent.
    unanswered_requests : int
        Number of consecutive requests that did not receive a substantive reply.
    escalation_flagged : bool
        Set to True once the social-engineering detector flags this user.
    current_topic : str
        The most recent conversation topic (e.g. ``"links"``, ``"lore"``,
        ``"lucas_info"``, ``"general"``).
    exchange_count : int
        Total number of completed request/response pairs in this session.
        Used by the personality system to gauge engagement level.
    """
    history: list[RequestRecord] = field(default_factory=list)
    link_request_count: int = 0
    link_last_sent: Optional[float] = None
    unanswered_requests: int = 0
    escalation_flagged: bool = False
    current_topic: str = "general"
    exchange_count: int = 0


# ---------------------------------------------------------------------------
# ConversationContextManager
# ---------------------------------------------------------------------------

class ConversationContextManager:
    """
    Central registry of per-user :class:`ConversationState` objects.

    Usage::

        ctx = ConversationContextManager()

        # Retrieve (or create) state for a user
        state = ctx.get_or_create(user_key)

        # Record a completed request/response round-trip
        ctx.record(user_key, intent="asks_for_links", message=msg, response=resp)

        # Check how many times the user has asked for links
        n = ctx.link_request_count(user_key)
    """

    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}

    # ------------------------------------------------------------------
    # State access
    # ------------------------------------------------------------------

    def get_or_create(self, user_key: str) -> ConversationState:
        """Return the existing state for *user_key*, creating one if needed."""
        if user_key not in self._states:
            self._states[user_key] = ConversationState()
        return self._states[user_key]

    def reset(self, user_key: str) -> None:
        """Discard the conversation state for *user_key* (e.g. after a block)."""
        self._states.pop(user_key, None)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        user_key: str,
        intent: str,
        message: str,
        response: str,
        topic: str = "",
    ) -> None:
        """
        Append a completed request/response pair to the user's history.

        Also updates convenience counters on :class:`ConversationState`.

        Parameters
        ----------
        user_key : str
            Opaque per-user identifier.
        intent : str
            Extended intent label from the router.
        message : str
            Raw user message.
        response : str
            Bot response that was sent.
        topic : str
            Optional conversation topic to record (e.g. ``"links"``,
            ``"lore"``, ``"lucas_info"``).  When non-empty, updates
            :attr:`ConversationState.current_topic`.
        """
        state = self.get_or_create(user_key)
        rec = RequestRecord(
            intent=intent,
            message=message,
            response=response,
            timestamp=time.monotonic(),
        )
        state.history.append(rec)

        if intent == "asks_for_links":
            state.link_request_count += 1
            if response:
                state.link_last_sent = rec.timestamp

        # A non-empty response resets the "unanswered" counter;
        # an empty response (bot stayed silent) increments it.
        if response:
            state.unanswered_requests = 0
            state.exchange_count += 1
        else:
            state.unanswered_requests += 1

        # Update topic when explicitly provided
        if topic:
            state.current_topic = topic

    # ------------------------------------------------------------------
    # Convenience queries
    # ------------------------------------------------------------------

    def link_request_count(self, user_key: str) -> int:
        """Return how many times this user has asked for links in this session."""
        return self.get_or_create(user_key).link_request_count

    def unanswered_count(self, user_key: str) -> int:
        """Return the number of consecutive unanswered requests for *user_key*."""
        return self.get_or_create(user_key).unanswered_requests

    def last_intents(self, user_key: str, n: int = 5) -> list[str]:
        """Return the last *n* intent labels for *user_key*, oldest-first."""
        history = self.get_or_create(user_key).history
        return [r.intent for r in history[-n:]]

    def intent_count_within(
        self,
        user_key: str,
        intent: str,
        seconds: float,
    ) -> int:
        """
        Return how many times *intent* appeared in the last *seconds* window.

        Useful for detecting spammy or escalating behaviour.
        """
        cutoff = time.monotonic() - seconds
        history = self.get_or_create(user_key).history
        return sum(1 for r in history if r.intent == intent and r.timestamp >= cutoff)

    def flag_escalation(self, user_key: str) -> None:
        """Mark this user as having triggered an escalation flag."""
        self.get_or_create(user_key).escalation_flagged = True

    def is_escalation_flagged(self, user_key: str) -> bool:
        """Return True if this user has been flagged for escalating behaviour."""
        return self.get_or_create(user_key).escalation_flagged

    def set_topic(self, user_key: str, topic: str) -> None:
        """Update the current conversation topic for *user_key*."""
        self.get_or_create(user_key).current_topic = topic

    def get_topic(self, user_key: str) -> str:
        """Return the current conversation topic for *user_key*."""
        return self.get_or_create(user_key).current_topic

    def get_exchange_count(self, user_key: str) -> int:
        """Return the total number of completed exchanges for *user_key*."""
        return self.get_or_create(user_key).exchange_count


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_manager: Optional[ConversationContextManager] = None


def get_context_manager() -> ConversationContextManager:
    """Return the module-level singleton :class:`ConversationContextManager`."""
    global _default_manager
    if _default_manager is None:
        _default_manager = ConversationContextManager()
    return _default_manager
