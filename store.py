"""Tiny entitlement datastore for strict one-report-per-payment.

Design: Stripe is the source of truth for *whether a session was paid* (we always
re-verify via the API, so a paid entitlement survives any redeploy). This store
only records which paid sessions have already been *consumed* (a report was
successfully delivered for them), so a single payment yields exactly one report.

Backed by SQLite. Default path is ./data/entitlements.db. On Railway, mount a
persistent volume and point ENTITLEMENT_DB at it (e.g. /data/entitlements.db) so
the consumed-record also survives redeploys. If it isn't persisted, the only
downside is that a customer could regenerate a report they already received after
a redeploy — never a loss of a paid entitlement.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.environ.get("ENTITLEMENT_DB", "data/entitlements.db")
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute(
        "CREATE TABLE IF NOT EXISTS consumed_sessions ("
        "  session_id TEXT PRIMARY KEY,"
        "  consumed_at TEXT NOT NULL,"
        "  note TEXT"
        ")"
    )
    return con


def is_consumed(session_id: str) -> bool:
    if not session_id:
        return False
    with _lock, _connect() as con:
        row = con.execute(
            "SELECT 1 FROM consumed_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row is not None


def mark_consumed(session_id: str, note: str = "") -> None:
    """Record a session as consumed. Idempotent (INSERT OR IGNORE)."""
    if not session_id:
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock, _connect() as con:
        con.execute(
            "INSERT OR IGNORE INTO consumed_sessions (session_id, consumed_at, note) "
            "VALUES (?, ?, ?)",
            (session_id, now, note),
        )
        con.commit()
