"""
conversation_context.py — Per-user conversation state and request-pattern tracking.

Tracks what each user has asked for during a session so that the bot can:
  - Acknowledge repeated requests rather than staying silent ("I already shared those links")
  - Detect escalating or suspicious patterns (e.g. same request 4+ times in 2 minutes)
  - Provide context to downstream modules (intent_router, hostility_handler)

State is held in memory for fast access and optionally persisted to the
``user_context`` SQLite table (created by ``database_manager.initialize()``)
so that conversation history survives bot restarts.

To enable DB persistence supply a *db_path* when constructing
:class:`ConversationContextManager`, or set the ``QUIET_REACH_DB_PATH``
environment variable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

# Number of past messages to load from the DB when a user_context row exists.
_HISTORY_LOAD_LIMIT: int = 10

#: Spacing (seconds) between synthetic monotonic timestamps for DB-loaded history records.
_SYNTHETIC_TIMESTAMP_SPACING_SECONDS: float = 10.0

#: Maximum character length for messages/responses stored in the DB history JSON.
_MAX_MESSAGE_LENGTH_DB: int = 500


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

        ctx = ConversationContextManager(db_path="quiet_reach.db")

        # Retrieve (or create) state for a user
        state = ctx.get_or_create(user_key)

        # Record a completed request/response round-trip
        ctx.record(user_key, intent="asks_for_links", message=msg, response=resp)

        # Check how many times the user has asked for links
        n = ctx.link_request_count(user_key)

    Parameters
    ----------
    db_path : str | None
        Path to the SQLite database for optional persistence.  When ``None``
        (or when the DB is unavailable), the manager operates in memory-only
        mode with no data loss risk.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._states: dict[str, ConversationState] = {}
        self._db_path: Optional[str] = db_path or os.getenv("QUIET_REACH_DB_PATH")

    # ------------------------------------------------------------------
    # State access
    # ------------------------------------------------------------------

    def get_or_create(self, user_key: str) -> ConversationState:
        """Return the existing state for *user_key*, creating one if needed.

        When a DB path is configured and the user has no in-memory state yet,
        the last :data:`_HISTORY_LOAD_LIMIT` exchanges are loaded from the DB.
        """
        if user_key not in self._states:
            self._states[user_key] = ConversationState()
            if self._db_path:
                self._load_from_db(user_key)
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

        Also updates convenience counters on :class:`ConversationState` and
        optionally persists the updated state to the database.

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

        # Keep in-memory history bounded to avoid unbounded growth
        if len(state.history) > _HISTORY_LOAD_LIMIT * 2:
            state.history = state.history[-_HISTORY_LOAD_LIMIT:]

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

        # Persist to DB (non-blocking; errors are swallowed to never crash the bot)
        if self._db_path:
            self._save_to_db(user_key, state)

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

    # ------------------------------------------------------------------
    # DB persistence helpers
    # ------------------------------------------------------------------

    def _load_from_db(self, user_key: str) -> None:
        """
        Populate in-memory state from the DB row for *user_key*.

        Only the last :data:`_HISTORY_LOAD_LIMIT` exchanges are loaded.
        Errors are swallowed — the bot always runs even without DB access.
        """
        try:
            with sqlite3.connect(self._db_path, timeout=10) as conn:
                row = conn.execute(
                    "SELECT history_json, link_request_count, exchange_count, "
                    "current_topic, escalation_flagged "
                    "FROM user_context WHERE user_key = ?",
                    (user_key,),
                ).fetchone()

            if row is None:
                return

            history_json, link_request_count, exchange_count, current_topic, escalation_flagged = row

            state = self._states[user_key]
            state.link_request_count = int(link_request_count or 0)
            state.exchange_count = int(exchange_count or 0)
            state.current_topic = current_topic or "general"
            state.escalation_flagged = bool(escalation_flagged)

            # Reconstruct history records from JSON
            try:
                entries = json.loads(history_json or "[]")
                # Use a synthetic monotonic timestamp so ordering is preserved
                base_ts = time.monotonic() - len(entries) * _SYNTHETIC_TIMESTAMP_SPACING_SECONDS
                for i, entry in enumerate(entries[-_HISTORY_LOAD_LIMIT:]):
                    state.history.append(
                        RequestRecord(
                            intent=entry.get("intent", ""),
                            message=entry.get("message", ""),
                            response=entry.get("response", ""),
                            timestamp=base_ts + i * _SYNTHETIC_TIMESTAMP_SPACING_SECONDS,
                        )
                    )
            except (json.JSONDecodeError, TypeError):
                pass

        except Exception:
            pass  # DB might not have the table yet — in-memory fallback is fine

    def _save_to_db(self, user_key: str, state: ConversationState) -> None:
        """
        Persist *state* for *user_key* to the ``user_context`` table.

        Only the last :data:`_HISTORY_LOAD_LIMIT` history entries are saved to
        keep the DB row size bounded.
        Errors are swallowed — the bot always runs even without DB access.
        """
        try:
            history_entries = [
                {
                    "intent": r.intent,
                    "message": r.message[:_MAX_MESSAGE_LENGTH_DB],
                    "response": r.response[:_MAX_MESSAGE_LENGTH_DB],
                }
                for r in state.history[-_HISTORY_LOAD_LIMIT:]
            ]
            history_json = json.dumps(history_entries)
            updated_at = datetime.now(timezone.utc).isoformat()

            with sqlite3.connect(self._db_path, timeout=10) as conn:
                conn.execute(
                    """
                    INSERT INTO user_context
                        (user_key, history_json, link_request_count, exchange_count,
                         current_topic, escalation_flagged, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_key) DO UPDATE SET
                        history_json       = excluded.history_json,
                        link_request_count = excluded.link_request_count,
                        exchange_count     = excluded.exchange_count,
                        current_topic      = excluded.current_topic,
                        escalation_flagged = excluded.escalation_flagged,
                        updated_at         = excluded.updated_at
                    """,
                    (
                        user_key,
                        history_json,
                        state.link_request_count,
                        state.exchange_count,
                        state.current_topic,
                        int(state.escalation_flagged),
                        updated_at,
                    ),
                )
                conn.commit()
        except Exception:
            pass  # Never let DB errors crash the bot


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_manager: Optional[ConversationContextManager] = None


def get_context_manager() -> ConversationContextManager:
    """Return the module-level singleton :class:`ConversationContextManager`.

    The singleton is initialized with the DB path from the
    ``QUIET_REACH_DB_PATH`` environment variable (if set), enabling
    conversation history to persist across bot restarts.
    """
    global _default_manager
    if _default_manager is None:
        db_path = os.getenv("QUIET_REACH_DB_PATH")
        _default_manager = ConversationContextManager(db_path=db_path)
    return _default_manager
