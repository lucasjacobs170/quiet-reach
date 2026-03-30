"""
database_manager.py — Centralized database schema initialization and migrations.

Ensures all required tables exist before the bot starts processing messages.
This eliminates "no such table" errors caused by tables being created in
multiple places or queried before they have been initialized.

Usage:
    import database_manager
    database_manager.initialize(db_path)   # once at startup

All other modules still create their own tables with CREATE TABLE IF NOT EXISTS,
but calling initialize() guarantees every table is present from the very first
message the bot handles.
"""

from __future__ import annotations

import os
import sqlite3

DB_PATH: str = os.getenv("QUIET_REACH_DB_PATH", "quiet_reach.db")


def initialize(db_path: str = DB_PATH) -> None:
    """
    Create all required tables and run any pending schema migrations.

    Call this once at startup before the bot starts processing messages.
    It is safe to call multiple times — all statements use
    ``CREATE TABLE IF NOT EXISTS`` and ``ALTER TABLE … ADD COLUMN IF NOT EXISTS``
    equivalents.
    """
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            _create_tables(conn)
            _run_migrations(conn)
            conn.commit()
        print("✅ DatabaseManager: all tables verified.")
    except Exception as exc:
        print(f"❌ DatabaseManager: initialization failed: {exc}")
        raise


# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------

def _create_tables(conn: sqlite3.Connection) -> None:
    """Create all required tables if they don't already exist."""

    # conversation_log — stores all inbound/outbound messages
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc      TEXT    NOT NULL DEFAULT '',
            guild_id    TEXT    NOT NULL DEFAULT '',
            channel_id  TEXT    NOT NULL DEFAULT '',
            user_id     TEXT    NOT NULL DEFAULT '',
            username    TEXT    NOT NULL DEFAULT '',
            is_dm       INTEGER NOT NULL DEFAULT 0,
            direction   TEXT    NOT NULL DEFAULT '',
            message     TEXT    NOT NULL DEFAULT ''
        )
        """
    )

    # user_context — per-user conversation state for DB persistence
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_context (
            user_key           TEXT    PRIMARY KEY,
            platform           TEXT    NOT NULL DEFAULT '',
            history_json       TEXT    NOT NULL DEFAULT '[]',
            link_request_count INTEGER NOT NULL DEFAULT 0,
            exchange_count     INTEGER NOT NULL DEFAULT 0,
            current_topic      TEXT    NOT NULL DEFAULT 'general',
            escalation_flagged INTEGER NOT NULL DEFAULT 0,
            updated_at         TEXT    NOT NULL DEFAULT ''
        )
        """
    )

    # hostile_incidents — record of every detected hostile message
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hostile_incidents (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc                  TEXT    NOT NULL DEFAULT '',
            platform                TEXT    NOT NULL DEFAULT '',
            user_key                TEXT    NOT NULL DEFAULT '',
            username                TEXT    NOT NULL DEFAULT '',
            message                 TEXT    NOT NULL DEFAULT '',
            level                   TEXT    NOT NULL DEFAULT '',
            via_ollama              INTEGER NOT NULL DEFAULT 0,
            response_sent           TEXT    NOT NULL DEFAULT '',
            hostility_score         INTEGER NOT NULL DEFAULT 0,
            normalized_message      TEXT    NOT NULL DEFAULT '',
            all_patterns_matched    TEXT    NOT NULL DEFAULT '[]',
            detection_method        TEXT    NOT NULL DEFAULT '',
            confidence_scores       TEXT    NOT NULL DEFAULT '[]',
            hostility_score_before  INTEGER NOT NULL DEFAULT 0,
            response_template       TEXT    NOT NULL DEFAULT '',
            false_positive_flag     INTEGER NOT NULL DEFAULT 0,
            context_notes           TEXT    NOT NULL DEFAULT ''
        )
        """
    )

    # blocked_users — permanently blocked users
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS blocked_users (
            user_key   TEXT PRIMARY KEY,
            username   TEXT NOT NULL DEFAULT '',
            platform   TEXT NOT NULL DEFAULT '',
            reason     TEXT NOT NULL DEFAULT '',
            blocked_at TEXT NOT NULL DEFAULT ''
        )
        """
    )

    # hostility_cooldowns — temporary cooldowns for hostile users
    # Mild hostility = timed (10 min); severe/threat = indefinite (expires_at IS NULL)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hostility_cooldowns (
            user_key       TEXT    PRIMARY KEY,
            username       TEXT    NOT NULL DEFAULT '',
            platform       TEXT    NOT NULL DEFAULT '',
            level          TEXT    NOT NULL DEFAULT 'mild',
            starts_at      TEXT    NOT NULL DEFAULT '',
            expires_at     TEXT,
            incident_count INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    # users — Discord user list / engagement state
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            discord_id     TEXT PRIMARY KEY,
            username       TEXT NOT NULL DEFAULT '',
            list_type      TEXT NOT NULL DEFAULT 'neutral',
            last_contacted TEXT NOT NULL DEFAULT '',
            opt_out        INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # server_caps — daily DM count caps per guild
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS server_caps (
            server_id TEXT NOT NULL,
            date      TEXT NOT NULL,
            dm_count  INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (server_id, date)
        )
        """
    )

    # keywords — engagement trigger words
    conn.execute(
        "CREATE TABLE IF NOT EXISTS keywords ("
        "word TEXT PRIMARY KEY, list_name TEXT NOT NULL DEFAULT '')"
    )

    # dm_optins — users who have explicitly opted into DMs
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dm_optins (
            discord_id TEXT PRIMARY KEY,
            username   TEXT NOT NULL DEFAULT '',
            opted_in   INTEGER NOT NULL DEFAULT 0,
            opted_in_at TEXT NOT NULL DEFAULT ''
        )
        """
    )

    # public_touches — how many times the bot has addressed a user publicly
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS public_touches (
            discord_id TEXT PRIMARY KEY,
            username   TEXT NOT NULL DEFAULT '',
            touches    INTEGER NOT NULL DEFAULT 0,
            last_touch TEXT NOT NULL DEFAULT ''
        )
        """
    )

    # ambiguous — messages whose intent couldn't be determined
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ambiguous (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id TEXT NOT NULL DEFAULT '',
            username   TEXT NOT NULL DEFAULT '',
            message    TEXT NOT NULL DEFAULT '',
            timestamp  TEXT NOT NULL DEFAULT ''
        )
        """
    )

    # promo_channels — per-guild promotional channel configuration
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_channels (
            guild_id         TEXT PRIMARY KEY,
            channel_id       TEXT NOT NULL DEFAULT '',
            enabled          INTEGER NOT NULL DEFAULT 0,
            window_start_pt  INTEGER NOT NULL DEFAULT 18,
            window_end_pt    INTEGER NOT NULL DEFAULT 22,
            next_post_at_utc TEXT NOT NULL DEFAULT '',
            last_post_at_utc TEXT NOT NULL DEFAULT ''
        )
        """
    )

    # promo_history — log of every promotional post sent
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id     TEXT NOT NULL DEFAULT '',
            channel_id   TEXT NOT NULL DEFAULT '',
            posted_at_utc TEXT NOT NULL DEFAULT '',
            image_path   TEXT NOT NULL DEFAULT '',
            caption      TEXT NOT NULL DEFAULT ''
        )
        """
    )


# ---------------------------------------------------------------------------
# Migrations — add new columns to existing tables without dropping data
# ---------------------------------------------------------------------------

def _run_migrations(conn: sqlite3.Connection) -> None:
    """Add any columns that are missing from pre-existing tables."""

    # hostile_incidents — extended logging columns added in later versions
    _add_column_if_missing(conn, "hostile_incidents", "hostility_score",
                           "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "hostile_incidents", "normalized_message",
                           "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "hostile_incidents", "all_patterns_matched",
                           "TEXT NOT NULL DEFAULT '[]'")
    _add_column_if_missing(conn, "hostile_incidents", "detection_method",
                           "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "hostile_incidents", "confidence_scores",
                           "TEXT NOT NULL DEFAULT '[]'")
    _add_column_if_missing(conn, "hostile_incidents", "hostility_score_before",
                           "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "hostile_incidents", "response_template",
                           "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "hostile_incidents", "false_positive_flag",
                           "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "hostile_incidents", "context_notes",
                           "TEXT NOT NULL DEFAULT ''")

    # conversation_log — ensure all expected columns exist on older DBs
    _add_column_if_missing(conn, "conversation_log", "guild_id",
                           "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "conversation_log", "channel_id",
                           "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "conversation_log", "user_id",
                           "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "conversation_log", "username",
                           "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "conversation_log", "is_dm",
                           "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "conversation_log", "direction",
                           "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "conversation_log", "message",
                           "TEXT NOT NULL DEFAULT ''")

    # hostility_cooldowns — incident_count may be missing on early installs
    _add_column_if_missing(conn, "hostility_cooldowns", "incident_count",
                           "INTEGER NOT NULL DEFAULT 1")


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    col_def: str,
) -> None:
    """Add *column* with *col_def* to *table* if it doesn't already exist."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
    except sqlite3.OperationalError:
        pass  # Column already exists — this is the expected path on re-runs
