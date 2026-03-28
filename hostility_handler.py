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
    from insult_detector import detect as _insult_detect, reset_user_score as _reset_score, InsultDetectionResult as _InsultDetectionResult
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

# Minimum confidence required before acting on a detection result.
# Below this threshold the message is treated as non-hostile to avoid
# false positives (Ollama was generating 50% false positives at confidence 0.0).
MIN_CONFIDENCE_THRESHOLD: float = 0.7


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

# Pre-compile word-boundary regex for every keyword to avoid per-call recompilation
_KW_REGEX_CACHE: dict[str, re.Pattern] = {
    pat: re.compile(r'\b' + re.escape(pat) + r'\b')
    for pat, _ in _FLAT_PATTERNS
}


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
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_utc              TEXT NOT NULL,
                platform            TEXT NOT NULL,
                user_key            TEXT NOT NULL,
                username            TEXT NOT NULL,
                message             TEXT NOT NULL,
                level               TEXT NOT NULL,
                via_ollama          INTEGER NOT NULL DEFAULT 0,
                response_sent       TEXT NOT NULL DEFAULT '',
                hostility_score     INTEGER NOT NULL DEFAULT 0,
                normalized_message  TEXT NOT NULL DEFAULT '',
                all_patterns_matched TEXT NOT NULL DEFAULT '[]',
                detection_method    TEXT NOT NULL DEFAULT '',
                confidence_scores   TEXT NOT NULL DEFAULT '[]',
                hostility_score_before INTEGER NOT NULL DEFAULT 0,
                response_template   TEXT NOT NULL DEFAULT '',
                false_positive_flag INTEGER NOT NULL DEFAULT 0,
                context_notes       TEXT NOT NULL DEFAULT ''
            )
            """
        )
        # Migrate existing tables that were created without the newer columns
        _migrate_column(conn, "hostile_incidents", "hostility_score", "INTEGER NOT NULL DEFAULT 0")
        _migrate_column(conn, "hostile_incidents", "normalized_message", "TEXT NOT NULL DEFAULT ''")
        _migrate_column(conn, "hostile_incidents", "all_patterns_matched", "TEXT NOT NULL DEFAULT '[]'")
        _migrate_column(conn, "hostile_incidents", "detection_method", "TEXT NOT NULL DEFAULT ''")
        _migrate_column(conn, "hostile_incidents", "confidence_scores", "TEXT NOT NULL DEFAULT '[]'")
        _migrate_column(conn, "hostile_incidents", "hostility_score_before", "INTEGER NOT NULL DEFAULT 0")
        _migrate_column(conn, "hostile_incidents", "response_template", "TEXT NOT NULL DEFAULT ''")
        _migrate_column(conn, "hostile_incidents", "false_positive_flag", "INTEGER NOT NULL DEFAULT 0")
        _migrate_column(conn, "hostile_incidents", "context_notes", "TEXT NOT NULL DEFAULT ''")
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


def _migrate_column(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
    """Add *column* to *table* if it doesn't exist yet."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
    except sqlite3.OperationalError:
        pass  # Column already exists


def log_incident(
    platform: str,
    user_key: str,
    username: str,
    message: str,
    result: HostilityResult,
    db_path: str = DB_PATH,
    hostility_score: int = 0,
    normalized_message: str = "",
    all_patterns_matched: Optional[list] = None,
    detection_method: str = "",
    confidence_scores: Optional[list] = None,
    hostility_score_before: int = 0,
    response_template: str = "",
) -> Optional[int]:
    """Append one hostile incident to SQLite. Returns the new row ID."""
    try:
        ts = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(db_path, timeout=30) as conn:
            cur = conn.execute(
                "INSERT INTO hostile_incidents "
                "(ts_utc, platform, user_key, username, message, level, via_ollama, response_sent, "
                "hostility_score, normalized_message, all_patterns_matched, detection_method, "
                "confidence_scores, hostility_score_before, response_template) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    normalized_message[:2000],
                    json.dumps(all_patterns_matched or []),
                    detection_method,
                    json.dumps(confidence_scores or []),
                    hostility_score_before,
                    response_template,
                ),
            )
            conn.commit()
            return cur.lastrowid
    except Exception as exc:
        print(f"⚠️ hostility_handler: log_incident failed: {exc}")
        return None


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
    Fast keyword-based hostility classification using whole-word matching.
    Returns HostilityLevel.NONE if nothing matches.
    """
    t = (text or "").lower().strip()
    if not t:
        return HostilityResult(level=HostilityLevel.NONE)

    for pattern, level in _FLAT_PATTERNS:
        # Use pre-compiled word-boundary patterns to avoid substring false positives
        if _KW_REGEX_CACHE[pattern].search(t):
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

    Strategy (revised to eliminate Ollama false positives):
      1. Run keyword matching first (fast, reliable, word-boundary based).
      2. If keyword matching finds nothing → return NONE immediately.
         Do NOT call Ollama — Ollama was flagging innocent messages as "mild"
         with 0.0 confidence, causing a 50% false positive rate.
      3. If keywords matched but confidence is below MIN_CONFIDENCE_THRESHOLD
         → treat as NONE (uncertain = silent).
      4. Attach a premade response to non-NONE results.

    Ollama is preserved in classify_with_ollama() for optional advanced use
    but is no longer called automatically during normal message handling.
    """
    result = classify_with_keywords(text)

    # Enforce confidence threshold: only act on high-confidence detections
    if result.level != HostilityLevel.NONE and result.confidence < MIN_CONFIDENCE_THRESHOLD:
        result = HostilityResult(level=HostilityLevel.NONE)

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
    import time as _time
    _msg_start = _time.monotonic()

    hostility_score = 0
    hostility_score_before = 0
    insult_result = None

    # --- Step 1: insult detector (runs before Ollama) -----------------------
    if _INSULT_DETECTOR_AVAILABLE and user_key:
        from insult_detector import get_user_score as _get_score
        hostility_score_before = _get_score(user_key)
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
            _patterns_for_db = [
                {"pattern": m.pattern, "category": m.category,
                 "severity": m.severity, "confidence": m.confidence}
                for m in insult_result.all_matches
            ]
            _confidence_scores = [m.confidence for m in insult_result.all_matches]
            db_incident_id = log_incident(
                platform, user_key, username, text, result,
                db_path=db_path,
                hostility_score=hostility_score,
                normalized_message=insult_result.normalized_text,
                all_patterns_matched=_patterns_for_db,
                detection_method="detector",
                confidence_scores=_confidence_scores,
                hostility_score_before=hostility_score_before,
                response_template="SEVERE_RESPONSES",
            )
            block_user(user_key, username, platform,
                       reason="insult score threshold exceeded", db_path=db_path)
            _reset_score(user_key)
            _incident_count = get_incident_count(user_key, db_path=db_path)

            # Transcript logging
            _log_to_transcript(
                text=text,
                user_key=user_key,
                platform=platform,
                insult_result=insult_result,
                result=result,
                hostility_score_before=hostility_score_before,
                hostility_score_after=hostility_score,
                action_taken="blocked_user",
                db_incident_id=db_incident_id,
                response_template="SEVERE_RESPONSES",
                via_ollama=False,
                msg_start=_msg_start,
                username=username,
                score_delta=insult_result.score_delta,
                incident_count=_incident_count,
            )
            return result

    # --- Step 2: keyword / pattern classification ----------------------------
    # If the insult detector ran and found NO patterns, default to NONE without
    # calling analyze().  Previously this path called Ollama, which was
    # generating ~50% false positives on innocent messages.
    if _INSULT_DETECTOR_AVAILABLE and insult_result is not None and not insult_result.detected:
        result = HostilityResult(level=HostilityLevel.NONE)
    else:
        result = analyze(text)

    # Enforce confidence threshold — uncertain detections are treated as NONE
    if result.level != HostilityLevel.NONE and result.confidence < MIN_CONFIDENCE_THRESHOLD:
        result = HostilityResult(level=HostilityLevel.NONE)

    if result.level != HostilityLevel.NONE:
        _patterns_for_db: list = []
        _confidence_scores: list = []
        _normalized = ""
        if insult_result is not None:
            _patterns_for_db = [
                {"pattern": m.pattern, "category": m.category,
                 "severity": m.severity, "confidence": m.confidence}
                for m in insult_result.all_matches
            ]
            _confidence_scores = [m.confidence for m in insult_result.all_matches]
            _normalized = insult_result.normalized_text

        _response_template = {
            HostilityLevel.MILD: "MILD_RESPONSES",
            HostilityLevel.SEVERE: "SEVERE_RESPONSES",
            HostilityLevel.THREAT: "THREAT_RESPONSES",
        }.get(result.level, "")

        _det_method = "ollama" if result.via_ollama else "keyword"

        db_incident_id = log_incident(
            platform, user_key, username, text, result,
            db_path=db_path,
            hostility_score=hostility_score,
            normalized_message=_normalized,
            all_patterns_matched=_patterns_for_db,
            detection_method=_det_method,
            confidence_scores=_confidence_scores,
            hostility_score_before=hostility_score_before,
            response_template=_response_template,
        )
    else:
        db_incident_id = None
        _response_template = ""
        _det_method = "ollama" if result.via_ollama else "keyword"

    if result.level in (HostilityLevel.SEVERE, HostilityLevel.THREAT):
        block_user(user_key, username, platform, reason=result.level.value, db_path=db_path)
        if _INSULT_DETECTOR_AVAILABLE and user_key:
            _reset_score(user_key)
        _action = "blocked_user"
    elif result.level != HostilityLevel.NONE:
        _action = "warned_user"
    else:
        _action = "none"

    _score_delta = hostility_score - hostility_score_before
    _incident_count = get_incident_count(user_key, db_path=db_path) if user_key else 0

    # Transcript logging for all messages (including NONE) for full coverage
    _log_to_transcript(
        text=text,
        user_key=user_key,
        platform=platform,
        insult_result=insult_result,
        result=result,
        hostility_score_before=hostility_score_before,
        hostility_score_after=hostility_score,
        action_taken=_action,
        db_incident_id=db_incident_id,
        response_template=_response_template,
        via_ollama=result.via_ollama,
        msg_start=_msg_start,
        username=username,
        score_delta=_score_delta,
        incident_count=_incident_count,
    )

    return result


def _log_to_transcript(
    text: str,
    user_key: str,
    platform: str,
    insult_result,
    result: HostilityResult,
    hostility_score_before: int,
    hostility_score_after: int,
    action_taken: str,
    db_incident_id: Optional[int],
    response_template: str,
    via_ollama: bool,
    msg_start: float,
    username: str = "",
    score_delta: int = 0,
    incident_count: int = 0,
) -> None:
    """Fire-and-forget call to the transcript logger (never raises)."""
    try:
        import time as _time
        from transcript_logger import TranscriptLogger
        TranscriptLogger.get_instance().log(
            text=text,
            user_key=user_key,
            platform=platform,
            insult_result=insult_result,
            hostility_result=result,
            hostility_score_before=hostility_score_before,
            hostility_score_after=hostility_score_after,
            action_taken=action_taken,
            db_incident_id=db_incident_id,
            response_template=response_template,
            via_ollama=via_ollama,
            total_time_ms=(_time.monotonic() - msg_start) * 1000,
            username=username,
            score_delta=score_delta,
            incident_count=incident_count,
        )
    except Exception:
        pass  # Never let logging errors crash the bot
