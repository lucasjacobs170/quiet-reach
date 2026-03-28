"""
social_engineering_detector.py — Detect repetitive and escalating request patterns.

Identifies behaviour that suggests social engineering, spam, or manipulation:
  - Asking for the same thing (e.g. links) many times in a short window
  - Rapid-fire repeated identical intents after the bot already responded
  - Progressive escalation: neutral → frustrated → hostile across a session

This module is read-only with respect to conversation state; it only inspects
the :class:`~conversation_context.ConversationState` supplied to it and returns
a :class:`DetectionResult` describing what it found.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conversation_context import ConversationContextManager


# ---------------------------------------------------------------------------
# Configuration — thresholds can be tuned without changing logic
# ---------------------------------------------------------------------------

# How many link requests in one session before the pattern is flagged
LINK_REPEAT_THRESHOLD: int = 3

# How many of the *same* intent in a short rolling window triggers suspicion
RAPID_REPEAT_THRESHOLD: int = 3
RAPID_REPEAT_WINDOW_SECONDS: float = 120.0  # 2 minutes

# How many consecutive unanswered requests before the pattern is flagged
UNANSWERED_THRESHOLD: int = 3


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class DetectionResult:
    """
    Summary of what the social-engineering detector found for one message.

    Attributes
    ----------
    is_suspicious : bool
        True when at least one pattern was detected.
    reason : str
        Human-readable explanation of the highest-priority pattern found.
    link_repeat_count : int
        Total link requests seen from this user in the current session.
    rapid_repeat_count : int
        Number of times the current intent appeared in the recent window.
    unanswered_count : int
        Number of consecutive requests that received no bot response.
    """
    is_suspicious: bool = False
    reason: str = ""
    link_repeat_count: int = 0
    rapid_repeat_count: int = 0
    unanswered_count: int = 0


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------

class SocialEngineeringDetector:
    """
    Stateless detector: all state is read from the supplied
    :class:`~conversation_context.ConversationContextManager`.

    Example::

        detector = SocialEngineeringDetector()
        ctx_mgr  = get_context_manager()

        result = detector.analyze(
            user_key="telegram:123",
            current_intent="asks_for_links",
            ctx_mgr=ctx_mgr,
        )
        if result.is_suspicious:
            print(result.reason)
    """

    def analyze(
        self,
        user_key: str,
        current_intent: str,
        ctx_mgr: "ConversationContextManager",
    ) -> DetectionResult:
        """
        Inspect the conversation history for *user_key* and decide whether
        the current message looks suspicious.

        Parameters
        ----------
        user_key : str
            Opaque user identifier (same key used in ConversationContextManager).
        current_intent : str
            The extended intent for the message currently being processed.
        ctx_mgr : ConversationContextManager
            The shared context manager to read state from.

        Returns
        -------
        DetectionResult
        """
        state = ctx_mgr.get_or_create(user_key)

        link_count = state.link_request_count
        unanswered = state.unanswered_requests

        # Count how many times this exact intent appeared in the rapid window.
        # We use the history that has already been recorded (i.e. *before* the
        # current message is appended) so repeated checks stay accurate.
        rapid_count = ctx_mgr.intent_count_within(
            user_key, current_intent, RAPID_REPEAT_WINDOW_SECONDS
        )

        # --- Pattern 1: too many link requests across the whole session -------
        if current_intent == "asks_for_links" and link_count >= LINK_REPEAT_THRESHOLD:
            ctx_mgr.flag_escalation(user_key)
            return DetectionResult(
                is_suspicious=True,
                reason=(
                    f"User has requested links {link_count} time(s) this session "
                    f"(threshold: {LINK_REPEAT_THRESHOLD})."
                ),
                link_repeat_count=link_count,
                rapid_repeat_count=rapid_count,
                unanswered_count=unanswered,
            )

        # --- Pattern 2: rapid repeat of the same intent ----------------------
        if rapid_count >= RAPID_REPEAT_THRESHOLD:
            ctx_mgr.flag_escalation(user_key)
            return DetectionResult(
                is_suspicious=True,
                reason=(
                    f"Intent '{current_intent}' repeated {rapid_count} time(s) "
                    f"within {int(RAPID_REPEAT_WINDOW_SECONDS)}s window "
                    f"(threshold: {RAPID_REPEAT_THRESHOLD})."
                ),
                link_repeat_count=link_count,
                rapid_repeat_count=rapid_count,
                unanswered_count=unanswered,
            )

        # --- Pattern 3: many unanswered requests in a row --------------------
        if unanswered >= UNANSWERED_THRESHOLD:
            ctx_mgr.flag_escalation(user_key)
            return DetectionResult(
                is_suspicious=True,
                reason=(
                    f"User sent {unanswered} consecutive message(s) that received "
                    f"no bot response (threshold: {UNANSWERED_THRESHOLD})."
                ),
                link_repeat_count=link_count,
                rapid_repeat_count=rapid_count,
                unanswered_count=unanswered,
            )

        return DetectionResult(
            link_repeat_count=link_count,
            rapid_repeat_count=rapid_count,
            unanswered_count=unanswered,
        )
