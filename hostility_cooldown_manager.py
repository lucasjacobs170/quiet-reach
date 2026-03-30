"""
hostility_cooldown_manager.py — Tiered cooldown system for hostile users.

Implements per-user cooldown periods after hostile interactions:

  Mild hostility   → 10-minute cooldown before the user can interact again.
  Severe / Threat  → Indefinite cooldown (manual ``clear_cooldown()`` required).

This is distinct from the ``blocked_users`` table (permanent ban).
Cooldowns are temporary and allow rehabilitation over time.

The cooldown state is stored in the ``hostility_cooldowns`` SQLite table,
which is created by ``database_manager.initialize()``.

Usage::

    from hostility_cooldown_manager import set_cooldown, is_in_cooldown

    # After detecting mild hostility:
    set_cooldown(user_key, level="mild", username=username, platform="discord")

    # Before processing a message:
    if is_in_cooldown(user_key):
        response = get_cooldown_response(user_key)
        # optionally send response, then return
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

DB_PATH: str = os.getenv("QUIET_REACH_DB_PATH", "quiet_reach.db")

# ---------------------------------------------------------------------------
# Cooldown durations
# ---------------------------------------------------------------------------

#: Minutes a user must wait after a mild-hostility incident before re-engaging.
MILD_COOLDOWN_MINUTES: int = 10

# Severe / threat cooldowns are indefinite (expires_at stored as NULL).


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------

def set_cooldown(
    user_key: str,
    level: str,
    username: str = "",
    platform: str = "",
    db_path: str = DB_PATH,
) -> None:
    """
    Set a cooldown for *user_key* based on hostility *level*.

    Parameters
    ----------
    user_key : str
        Opaque per-user identifier (e.g. ``"discord:12345"``).
    level : str
        Hostility level — ``"mild"``, ``"severe"``, or ``"threat"``.
    username : str
        Display name used for logging / diagnostics.
    platform : str
        Platform identifier for logging (e.g. ``"discord"``).
    db_path : str
        Path to the SQLite database.
    """
    now = datetime.now(timezone.utc)
    starts_at = now.isoformat()

    if level == "mild":
        expires_at: Optional[str] = (
            now + timedelta(minutes=MILD_COOLDOWN_MINUTES)
        ).isoformat()
    else:
        # severe / threat: indefinite — expires_at NULL
        expires_at = None

    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            conn.execute(
                """
                INSERT INTO hostility_cooldowns
                    (user_key, username, platform, level, starts_at, expires_at, incident_count)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(user_key) DO UPDATE SET
                    username       = excluded.username,
                    platform       = excluded.platform,
                    level          = CASE
                                       WHEN excluded.level IN ('severe', 'threat')
                                       THEN excluded.level
                                       ELSE hostility_cooldowns.level
                                     END,
                    starts_at      = excluded.starts_at,
                    expires_at     = CASE
                                       WHEN excluded.level IN ('severe', 'threat')
                                       THEN NULL
                                       ELSE excluded.expires_at
                                     END,
                    incident_count = hostility_cooldowns.incident_count + 1
                """,
                (user_key, username, platform, level, starts_at, expires_at),
            )
            conn.commit()
    except Exception as exc:
        print(f"⚠️ hostility_cooldown_manager: set_cooldown failed: {exc}")


def is_in_cooldown(user_key: str, db_path: str = DB_PATH) -> bool:
    """
    Return ``True`` if *user_key* is currently subject to a cooldown.

    Expired timed cooldowns are treated as inactive (returns ``False``).
    Indefinite cooldowns (``expires_at IS NULL``) always return ``True``.
    """
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            row = conn.execute(
                "SELECT level, expires_at FROM hostility_cooldowns WHERE user_key = ?",
                (user_key,),
            ).fetchone()

        if row is None:
            return False

        _level, expires_at = row

        # Indefinite cooldown
        if expires_at is None:
            return True

        # Timed cooldown: check expiry
        try:
            expiry = datetime.fromisoformat(expires_at)
            return datetime.now(timezone.utc) < expiry
        except ValueError:
            return True  # Malformed timestamp → treat as still active

    except Exception as exc:
        print(f"⚠️ hostility_cooldown_manager: is_in_cooldown failed: {exc}")
        return False


def get_cooldown_info(
    user_key: str,
    db_path: str = DB_PATH,
) -> Optional[dict]:
    """
    Return cooldown metadata for *user_key*, or ``None`` if not in cooldown.

    Expired timed cooldowns are removed from the DB and ``None`` is returned.

    Returns a dict with keys:
        ``user_key``, ``level``, ``starts_at``, ``expires_at``, ``incident_count``
    """
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            row = conn.execute(
                "SELECT user_key, level, starts_at, expires_at, incident_count "
                "FROM hostility_cooldowns WHERE user_key = ?",
                (user_key,),
            ).fetchone()

        if row is None:
            return None

        uk, level, starts_at, expires_at, incident_count = row

        # Check whether a timed cooldown has expired
        if expires_at is not None:
            try:
                expiry = datetime.fromisoformat(expires_at)
                if datetime.now(timezone.utc) >= expiry:
                    # Expired — clean up and report as inactive
                    clear_cooldown(user_key, db_path=db_path)
                    return None
            except ValueError:
                pass  # Malformed timestamp → keep treating as active

        return {
            "user_key": uk,
            "level": level,
            "starts_at": starts_at,
            "expires_at": expires_at,
            "incident_count": incident_count,
        }

    except Exception as exc:
        print(f"⚠️ hostility_cooldown_manager: get_cooldown_info failed: {exc}")
        return None


def clear_cooldown(user_key: str, db_path: str = DB_PATH) -> bool:
    """
    Remove the cooldown for *user_key*.

    Required for manual rehabilitation of users on indefinite cooldowns.

    Returns
    -------
    bool
        ``True`` if a row was removed, ``False`` if the user had no cooldown.
    """
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            cur = conn.execute(
                "DELETE FROM hostility_cooldowns WHERE user_key = ?",
                (user_key,),
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception as exc:
        print(f"⚠️ hostility_cooldown_manager: clear_cooldown failed: {exc}")
        return False


def get_cooldown_response(user_key: str, db_path: str = DB_PATH) -> str:
    """
    Return a user-facing message to send to *user_key* while they are
    in a cooldown period.

    Returns an empty string if the user is not in cooldown.
    """
    info = get_cooldown_info(user_key, db_path=db_path)
    if info is None:
        return ""

    if info["level"] in ("severe", "threat"):
        return (
            "I'm not able to continue this conversation right now. "
            "Reach out again when you're ready for a fresh start."
        )

    # Mild cooldown — show approximate time remaining
    expires_at = info.get("expires_at")
    if expires_at:
        try:
            expiry = datetime.fromisoformat(expires_at)
            remaining = expiry - datetime.now(timezone.utc)
            minutes_left = max(1, int(remaining.total_seconds() // 60))
            return (
                f"Let's take a short break — feel free to come back "
                f"in {minutes_left} minute(s). 😊"
            )
        except ValueError:
            pass

    return "Let's take a short break — feel free to come back in a few minutes. 😊"
