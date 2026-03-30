"""
context_analyzer.py — Conversation history analysis for hostility trend detection.

Maintains a rolling window of recent user messages and their detected hostility
levels to determine whether ambiguous (context_required) patterns should be
flagged given the surrounding conversation.

Usage
-----
    from context_analyzer import ContextAnalyzer

    analyzer = ContextAnalyzer()

    # Record each message result AFTER detection
    analyzer.record(user_key="discord:12345", hostility_level="none", score_delta=0)

    # Check before deciding to flag a context_required match
    if analyzer.is_hostile_context(user_key="discord:12345"):
        # Prior messages were hostile — lower the threshold and flag it
        ...

    # Get a numeric prior-hostility score for the user
    score = analyzer.get_prior_hostility_score("discord:12345")
"""

from __future__ import annotations

import os
import json
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------

_CFG_PATH = os.path.join(os.path.dirname(__file__), "hostility_config.json")
try:
    with open(_CFG_PATH, encoding="utf-8") as _f:
        _CFG: dict = json.load(_f)
except (FileNotFoundError, json.JSONDecodeError):
    _CFG = {}

_CTX_CFG: dict = _CFG.get("context_window", {})
LOOK_BACK: int = int(_CTX_CFG.get("look_back_messages", 3))
DECAY_TURNS: int = int(_CTX_CFG.get("hostility_decay_turns", 5))
DECAY_AMOUNT: int = int(_CTX_CFG.get("hostility_decay_amount", 1))
HOSTILE_LOWER: bool = bool(_CTX_CFG.get("hostile_history_lower_threshold", True))
FRIENDLY_RAISE: bool = bool(_CTX_CFG.get("friendly_history_raise_threshold", True))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class _MessageRecord:
    """A lightweight record of one user message's hostility result."""
    hostility_level: str   # none | mild | moderate | severe | threat
    score_delta: int       # points that message contributed
    turn_index: int        # monotonically increasing; used for decay


@dataclass
class _UserHistory:
    """Rolling conversation history for a single user."""
    # Buffer size: keep enough records for both the look-back window AND the
    # decay window.  The extra +2 provides a small overlap so that a single
    # call to _apply_decay() always has DECAY_TURNS complete records available
    # even if look-back and decay windows end at the same position.
    records: deque = field(default_factory=lambda: deque(maxlen=max(LOOK_BACK, DECAY_TURNS) + 2))
    turn_counter: int = 0
    cumulative_score: int = 0  # running total, decayed over time
    last_decay_turn: int = 0   # turn index when decay was last applied


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class ContextAnalyzer:
    """
    Tracks recent message hostility for each user.

    Thread-safety note: this class is intentionally simple and not
    thread-safe.  The bot is expected to call it from a single async
    event loop without concurrent writes for the same user_key.
    """

    def __init__(self) -> None:
        self._histories: dict[str, _UserHistory] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        user_key: str,
        hostility_level: str,
        score_delta: int,
    ) -> None:
        """
        Record the result of one message for *user_key*.

        Parameters
        ----------
        user_key : str
            Opaque user identifier (same as used in insult_detector).
        hostility_level : str
            One of: none, mild, moderate, severe, threat.
        score_delta : int
            Score points that this message contributed (0 for non-hostile).
        """
        history = self._get_or_create(user_key)
        history.turn_counter += 1
        history.cumulative_score = max(0, history.cumulative_score + score_delta)
        history.records.append(
            _MessageRecord(
                hostility_level=hostility_level,
                score_delta=score_delta,
                turn_index=history.turn_counter,
            )
        )
        self._apply_decay(history)

    def is_hostile_context(self, user_key: str) -> bool:
        """
        Return True if the recent conversation history suggests hostility.

        Looks at the last LOOK_BACK messages.  Returns True if any of them
        were at or above "mild" hostility level.
        """
        history = self._histories.get(user_key)
        if not history or not history.records:
            return False

        recent = list(history.records)[-LOOK_BACK:]
        hostile_levels = {"mild", "moderate", "severe", "threat"}
        return any(r.hostility_level in hostile_levels for r in recent)

    def is_friendly_context(self, user_key: str) -> bool:
        """
        Return True if the most recent LOOK_BACK messages were all non-hostile.
        """
        history = self._histories.get(user_key)
        if not history or not history.records:
            return True  # no history → assume friendly

        recent = list(history.records)[-LOOK_BACK:]
        hostile_levels = {"mild", "moderate", "severe", "threat"}
        return all(r.hostility_level not in hostile_levels for r in recent)

    def get_prior_hostility_score(self, user_key: str) -> int:
        """
        Return the running (decayed) hostility score for *user_key*.
        0 = no prior hostility.
        """
        history = self._histories.get(user_key)
        return history.cumulative_score if history else 0

    def get_recent_hostility_count(self, user_key: str, window: Optional[int] = None) -> int:
        """
        Count the number of hostile messages in the last *window* turns.
        """
        if window is None:
            window = LOOK_BACK
        history = self._histories.get(user_key)
        if not history:
            return 0
        recent = list(history.records)[-window:]
        hostile_levels = {"mild", "moderate", "severe", "threat"}
        return sum(1 for r in recent if r.hostility_level in hostile_levels)

    def should_lower_threshold(self, user_key: str) -> bool:
        """
        Return True when prior hostility warrants lowering the detection threshold
        (i.e. flag context_required entries more readily).
        """
        if not HOSTILE_LOWER:
            return False
        return self.is_hostile_context(user_key)

    def should_raise_threshold(self, user_key: str) -> bool:
        """
        Return True when a friendly conversation warrants raising the detection
        threshold (i.e. suppress context_required entries more aggressively).
        """
        if not FRIENDLY_RAISE:
            return False
        return self.is_friendly_context(user_key)

    def reset(self, user_key: str) -> None:
        """Clear all history for *user_key* (e.g. after a block or new session)."""
        self._histories.pop(user_key, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, user_key: str) -> _UserHistory:
        if user_key not in self._histories:
            self._histories[user_key] = _UserHistory()
        return self._histories[user_key]

    def _apply_decay(self, history: _UserHistory) -> None:
        """
        Reduce the cumulative hostility score over time.

        Every DECAY_TURNS friendly (score_delta == 0) messages since the last
        decay event, subtract DECAY_AMOUNT from the running score (floor at 0).
        Decay fires repeatedly: after each DECAY_TURNS friendly messages the
        score drops by DECAY_AMOUNT again.  This prevents the bot from holding
        a permanent grudge while still requiring sustained friendliness to
        fully reset the score.
        """
        if not history.records or history.cumulative_score <= 0:
            return

        # Count friendly messages since the last decay turn
        friendly_since_decay = sum(
            1 for r in history.records
            if r.turn_index > history.last_decay_turn and r.score_delta == 0
        )
        if friendly_since_decay >= DECAY_TURNS:
            history.cumulative_score = max(0, history.cumulative_score - DECAY_AMOUNT)
            history.last_decay_turn = history.turn_counter


# ---------------------------------------------------------------------------
# Module-level singleton (shared across the process)
# ---------------------------------------------------------------------------

_GLOBAL_ANALYZER: Optional[ContextAnalyzer] = None


def get_analyzer() -> ContextAnalyzer:
    """Return (or lazily create) the global ContextAnalyzer instance."""
    global _GLOBAL_ANALYZER
    if _GLOBAL_ANALYZER is None:
        _GLOBAL_ANALYZER = ContextAnalyzer()
    return _GLOBAL_ANALYZER
