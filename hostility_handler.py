"""
hostility_handler.py — Ollama-based hostility detection and response management.

Classifies incoming messages into one of four levels:
  none    → normal conversation, no action needed
  mild    → mild rudeness / annoyance; send a soft warning once
  severe  → heavy insults / strong hostility; send final warning and block
  threat  → credible threats; send final warning and block immediately

Fallback: if Ollama is unreachable, a keyword-based classifier is used.

The module is self-contained: it manages its own SQLite table
(hostile_incidents) inside the shared DB and exposes a simple interface
that the main bot calls.
"""

from __future__ import annotations

import json
import os
import random
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import requests

try:
    from insult_detector import detect as _insult_detect, reset_user_score as _reset_score
    _INSULT_DETECTOR_AVAILABLE = True
except ImportError:
    _INSULT_DETECTOR_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration (inherit from environment or use the same defaults as the bot)
# ---------------------------------------------------------------------------
OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
DB_PATH: str = os.getenv("HOSTILITY_DB_PATH", "quiet_reach.db")
OLLAMA_TIMEOUT: int = 15  # seconds — keep short for real-time chat


# ---------------------------------------------------------------------------
# Enums / data structures
# ---------------------------------------------------------------------------

class HostilityLevel(str, Enum):
    NONE = "none"
    MILD = "mild"
    SEVERE = "severe"
    THREAT = "threat"


@dataclass
class HostilityResult:
    level: HostilityLevel = HostilityLevel.NONE
    confidence: float = 1.0          # 0.0–1.0
    matched_pattern: str = ""        # first keyword that triggered (fallback)
    via_ollama: bool = False          # True when Ollama classified it
    response: str = ""               # premade response to send (empty for NONE)


# ---------------------------------------------------------------------------
# Premade response libraries
# ---------------------------------------------------------------------------

MILD_RESPONSES: list[str] = [
    "Hey — let's keep it respectful here. I'm just trying to help. 😊",
    "I get that it can be frustrating, but I'd appreciate a more civil tone. "
    "I'm here to assist, not argue.",
    "Let's dial it back a notch — I'm on your side. What do you actually need?",
    "I understand you're annoyed, but I work best with a bit of kindness. "
    "How can I help you today?",
    "I hear you — but let's keep things friendly. What can I do for you?",
]

SEVERE_RESPONSES: list[str] = [
    "That's beyond what I'm willing to engage with. I'll be stepping back now — "
    "if you need help later, feel free to reach out respectfully.",
    "I'm not going to continue this conversation at this level. "
    "Reach out again when things have cooled down. Take care.",
    "This crosses a line I can't overlook. I'll be stopping here. "
    "You're always welcome back once the tone changes.",
    "That kind of language isn't something I'll respond to. "
    "I'm going quiet — come back anytime you'd like a fresh start.",
]

THREAT_RESPONSES: list[str] = [
    "That's a threat, and I'm not engaging further. You've been blocked.",
    "Threats are an immediate stop for me. Conversation closed.",
    "I won't tolerate threatening language. This conversation is over.",
]


# ---------------------------------------------------------------------------
# Keyword fallback library (tiered)
# ---------------------------------------------------------------------------

_KEYWORD_LIBRARY: dict[HostilityLevel, list[str]] = {
    HostilityLevel.MILD: [
        "stop spamming",
        "not interested",
        "shut up",
        "leave me alone",
        "go away",
        "wasting my time",
        "another ad bot",
        "so irritating",
        "annoying bot",
        "bot pls stop",
        "too pushy",
        "stop messaging me",
        "stop replying",
    ],
    HostilityLevel.SEVERE: [
        "fuck off",
        "fuck you",
        "go fuck",
        "useless piece of shit",
        "piece of shit",
        "this bot is garbage",
        "worthless spammer",
        "absolute garbage",
        "dumb bot",
        "stupid bot",
        "trash bot",
        "retarded",
        "eat shit",
        "go to hell",
        "drop dead",
        "go die",
        "screw you",
        "kiss my ass",
        "kys",
        "get the fuck out",
        "i hate this bot",
        "piss off",
        "get lost",
        "scam bot",
        "obvious scam",
        "stop trying to scam",
        "you're a scam",
    ],
    HostilityLevel.THREAT: [
        "i will kill",
        "i'll kill",
        "i'm going to kill",
        "going to hurt you",
        "i will hurt",
        "i'll hurt",
        "gonna find you",
        "i know where you",
        "you're dead",
        "your dev will pay",
        "hope your dev gets",
    ],
}

# Flattened lookup: pattern -> level (longest patterns first to avoid false positives)
_FLAT_PATTERNS: list[tuple[str, HostilityLevel]] = []
for _level in (HostilityLevel.THREAT, HostilityLevel.SEVERE, HostilityLevel.MILD):
    for _pat in sorted(_KEYWORD_LIBRARY[_level], key=len, reverse=True):
        _FLAT_PATTERNS.append((_pat, _level))


# ---------------------------------------------------------------------------
# Ollama prompt
# ---------------------------------------------------------------------------

_CLASSIFICATION_PROMPT = """\
Classify the hostility level of the following message. Reply with exactly one word:
  none     — polite, neutral, or constructive
  mild     — mildly rude, dismissive, or annoyed (e.g. "shut up", "stop spamming")
  severe   — heavy insults, strong profanity, hate speech
  threat   — explicit threats of harm

Message: {message}

Hostility level:"""


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def setup_hostility_db(db_path: str = DB_PATH) -> None:
    """Create the hostile_incidents table if it doesn't exist."""
    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hostile_incidents (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc        TEXT NOT NULL,
                platform      TEXT NOT NULL,
                user_key      TEXT NOT NULL,
                username      TEXT NOT NULL,
                message       TEXT NOT NULL,
                level         TEXT NOT NULL,
                via_ollama    INTEGER NOT NULL DEFAULT 0,
                response_sent TEXT NOT NULL DEFAULT '',
                hostility_score INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        # Add hostility_score column to existing tables that were created without it
        try:
            conn.execute(
                "ALTER TABLE hostile_incidents ADD COLUMN hostility_score INTEGER NOT NULL DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS blocked_users (
                user_key  TEXT PRIMARY KEY,
                username  TEXT NOT NULL,
                platform  TEXT NOT NULL,
                reason    TEXT NOT NULL DEFAULT '',
                blocked_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def log_incident(
    platform: str,
    user_key: str,
    username: str,
    message: str,
    result: HostilityResult,
    db_path: str = DB_PATH,
    hostility_score: int = 0,
) -> None:
    """Append one hostile incident to SQLite."""
    try:
        ts = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(db_path, timeout=30) as conn:
            conn.execute(
                "INSERT INTO hostile_incidents "
                "(ts_utc, platform, user_key, username, message, level, via_ollama, response_sent, hostility_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts,
                    platform,
                    user_key,
                    username,
                    message[:2000],
                    result.level.value,
                    int(result.via_ollama),
                    result.response[:2000],
                    hostility_score,
                ),
            )
            conn.commit()
    except Exception as exc:
        print(f"⚠️ hostility_handler: log_incident failed: {exc}")


def block_user(
    user_key: str,
    username: str,
    platform: str,
    reason: str = "",
    db_path: str = DB_PATH,
) -> None:
    """Add a user to the blocked_users table."""
    try:
        ts = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(db_path, timeout=30) as conn:
            conn.execute(
                "INSERT INTO blocked_users (user_key, username, platform, reason, blocked_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_key) DO UPDATE SET "
                "username=excluded.username, platform=excluded.platform, "
                "reason=excluded.reason, blocked_at=excluded.blocked_at",
                (user_key, username, platform, reason[:500], ts),
            )
            conn.commit()
    except Exception as exc:
        print(f"⚠️ hostility_handler: block_user failed: {exc}")


def unblock_user(user_key: str, db_path: str = DB_PATH) -> bool:
    """Remove a user from the blocked list. Returns True if a row was removed."""
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            cur = conn.execute(
                "DELETE FROM blocked_users WHERE user_key=?", (user_key,)
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as exc:
        print(f"⚠️ hostility_handler: unblock_user failed: {exc}")
        return False


def is_blocked(user_key: str, db_path: str = DB_PATH) -> bool:
    """Return True when the user is in the blocked_users table."""
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            row = conn.execute(
                "SELECT 1 FROM blocked_users WHERE user_key=?", (user_key,)
            ).fetchone()
            return row is not None
    except Exception as exc:
        print(f"⚠️ hostility_handler: is_blocked failed: {exc}")
        return False


def list_blocked(db_path: str = DB_PATH) -> list[dict]:
    """Return all blocked users as a list of dicts."""
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            rows = conn.execute(
                "SELECT user_key, username, platform, reason, blocked_at "
                "FROM blocked_users ORDER BY blocked_at DESC"
            ).fetchall()
        return [
            {
                "user_key": r[0],
                "username": r[1],
                "platform": r[2],
                "reason": r[3],
                "blocked_at": r[4],
            }
            for r in rows
        ]
    except Exception as exc:
        print(f"⚠️ hostility_handler: list_blocked failed: {exc}")
        return []


def get_incident_count(user_key: str, db_path: str = DB_PATH) -> int:
    """Return the total number of hostile incidents logged for a user."""
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM hostile_incidents WHERE user_key=?", (user_key,)
            ).fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Keyword fallback classifier
# ---------------------------------------------------------------------------

def classify_with_keywords(text: str) -> HostilityResult:
    """
    Fast keyword-based hostility classification.
    Returns HostilityLevel.NONE if nothing matches.
    """
    t = (text or "").lower().strip()
    if not t:
        return HostilityResult(level=HostilityLevel.NONE)

    for pattern, level in _FLAT_PATTERNS:
        if pattern in t:
            return HostilityResult(
                level=level,
                confidence=0.9,
                matched_pattern=pattern,
                via_ollama=False,
            )

    return HostilityResult(level=HostilityLevel.NONE)


# ---------------------------------------------------------------------------
# Ollama classifier
# ---------------------------------------------------------------------------

def classify_with_ollama(text: str) -> Optional[HostilityResult]:
    """
    Call Ollama synchronously. Returns None when Ollama is unavailable.
    The caller should fall back to keyword classification on None.
    """
    prompt = _CLASSIFICATION_PROMPT.format(message=text.strip()[:500])
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        raw = (resp.json().get("response") or "").strip().lower()

        # Accept the first word so "none." → "none", etc.
        word = re.split(r"[\s.,!;:]", raw)[0]

        level_map = {
            "none": HostilityLevel.NONE,
            "mild": HostilityLevel.MILD,
            "severe": HostilityLevel.SEVERE,
            "threat": HostilityLevel.THREAT,
        }
        level = level_map.get(word)
        if level is None:
            # Ollama returned something unexpected — fall back
            return None

        return HostilityResult(level=level, confidence=0.85, via_ollama=True)

    except Exception:
        return None  # Ollama unavailable or timed out


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze(text: str) -> HostilityResult:
    """
    Classify the hostility of *text*.

    Strategy:
      1. Try Ollama first (fast timeout).
      2. On failure/unavailability, fall back to keyword matching.
      3. Attach a premade response to non-NONE results.
    """
    result = classify_with_ollama(text)

    if result is None:
        # Ollama unavailable — use keyword fallback
        result = classify_with_keywords(text)
    elif result.level == HostilityLevel.NONE:
        # Ollama said none — quick sanity check with keywords
        # (catches cases where Ollama under-classifies obvious slurs)
        kw_result = classify_with_keywords(text)
        if kw_result.level in (HostilityLevel.SEVERE, HostilityLevel.THREAT):
            result = kw_result

    # Attach premade response
    if result.level == HostilityLevel.MILD:
        result.response = random.choice(MILD_RESPONSES)
    elif result.level == HostilityLevel.SEVERE:
        result.response = random.choice(SEVERE_RESPONSES)
    elif result.level == HostilityLevel.THREAT:
        result.response = random.choice(THREAT_RESPONSES)

    return result


# ---------------------------------------------------------------------------
# Convenience wrappers for the bot
# ---------------------------------------------------------------------------

def handle_message(
    text: str,
    user_key: str,
    username: str,
    platform: str,
    db_path: str = DB_PATH,
) -> HostilityResult:
    """
    Full pipeline:
      1. Run insult detector (fast, pattern-based) — block immediately if threshold reached.
      2. Classify the message via Ollama / keyword fallback.
      3. Log to DB if hostile.
      4. Block the user on severe/threat.
      5. Return the result (caller sends result.response if non-empty).
    """
    hostility_score = 0

    # --- Step 1: insult detector (runs before Ollama) -----------------------
    if _INSULT_DETECTOR_AVAILABLE and user_key:
        insult_result = _insult_detect(text, user_key=user_key)
        hostility_score = insult_result.cumulative_score

        if insult_result.should_block:
            # Severe threshold reached — block immediately without calling Ollama
            result = HostilityResult(
                level=HostilityLevel.SEVERE,
                confidence=1.0,
                matched_pattern=insult_result.matched_phrase,
                via_ollama=False,
                response=random.choice(SEVERE_RESPONSES),
            )
            log_incident(platform, user_key, username, text, result,
                         db_path=db_path, hostility_score=hostility_score)
            block_user(user_key, username, platform,
                       reason="insult score threshold exceeded", db_path=db_path)
            _reset_score(user_key)
            return result

    # --- Step 2: standard Ollama / keyword classification -------------------
    result = analyze(text)

    if result.level != HostilityLevel.NONE:
        log_incident(platform, user_key, username, text, result,
                     db_path=db_path, hostility_score=hostility_score)

    if result.level in (HostilityLevel.SEVERE, HostilityLevel.THREAT):
        block_user(user_key, username, platform, reason=result.level.value, db_path=db_path)
        if _INSULT_DETECTOR_AVAILABLE and user_key:
            _reset_score(user_key)

    return result
