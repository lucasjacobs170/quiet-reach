"""
resource_manager.py — Centralized resource tracking and cleanup.

Tracks all SQLite connections, file handles, and background tasks so that
calling cleanup_all() guarantees every resource is released when the bot stops.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Internal state (module-level, protected by a lock)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_connections: list[sqlite3.Connection] = []
_background_tasks: list["asyncio.Task[Any]"] = []


# ---------------------------------------------------------------------------
# SQLite connection factory
# ---------------------------------------------------------------------------

def tracked_connect(db_path: str, timeout: float = 30) -> sqlite3.Connection:
    """Open a SQLite connection and register it for centralized cleanup."""
    conn = sqlite3.connect(db_path, timeout=timeout)
    with _lock:
        _connections.append(conn)
    return conn


def release_connection(conn: sqlite3.Connection) -> None:
    """Close a single tracked connection and remove it from the registry."""
    try:
        conn.close()
    except Exception:
        pass
    with _lock:
        try:
            _connections.remove(conn)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Background task registry
# ---------------------------------------------------------------------------

def track_task(task: "asyncio.Task[Any]") -> None:
    """Register an asyncio.Task for centralized cancellation."""
    with _lock:
        _background_tasks.append(task)


def untrack_task(task: "asyncio.Task[Any]") -> None:
    """Remove a task from the registry (e.g. after it completes)."""
    with _lock:
        try:
            _background_tasks.remove(task)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Centralized cleanup
# ---------------------------------------------------------------------------

def cleanup_all() -> None:
    """
    Close every tracked SQLite connection, cancel every tracked task, and
    release the TranscriptLogger singleton so its session file is freed.

    Call this from stop_bot(), stop_telegram_bot(), and on_closing() to
    guarantee no file handles remain open after the bot shuts down.
    """
    # 1. Cancel all background tasks
    with _lock:
        tasks_snapshot = list(_background_tasks)

    for task in tasks_snapshot:
        try:
            if not task.done():
                task.cancel()
        except Exception:
            pass

    with _lock:
        _background_tasks.clear()

    # 2. Close all SQLite connections
    with _lock:
        conns_snapshot = list(_connections)
        _connections.clear()

    for conn in conns_snapshot:
        try:
            conn.close()
        except Exception:
            pass

    # 3. Release TranscriptLogger so its session file handle is freed
    try:
        from transcript_logger import TranscriptLogger
        TranscriptLogger.close_instance()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Context manager convenience wrapper
# ---------------------------------------------------------------------------

class ManagedConnection:
    """
    Context manager that opens a tracked SQLite connection and guarantees
    it is closed (and de-registered) when the ``with`` block exits.

    Usage::

        with ManagedConnection(DB_PATH) as conn:
            conn.execute(...)
            conn.commit()
    """

    def __init__(self, db_path: str, timeout: float = 30) -> None:
        self._db_path = db_path
        self._timeout = timeout
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> sqlite3.Connection:
        self._conn = tracked_connect(self._db_path, self._timeout)
        return self._conn

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._conn is not None:
            release_connection(self._conn)
            self._conn = None
        return False  # do not suppress exceptions
