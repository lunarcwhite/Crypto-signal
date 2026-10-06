"""Persistensi MVP: SQLite signals.db (PRD §5). Tabel signals + events."""
from __future__ import annotations

import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL, direction TEXT NOT NULL,
  entry REAL NOT NULL, sl REAL NOT NULL, tp1 REAL NOT NULL, tp2 REAL NOT NULL,
  qty REAL DEFAULT 0, risk REAL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'OPEN',
  opened_at INTEGER NOT NULL, closed_at INTEGER,
  outcome TEXT, exit_px REAL
);
CREATE INDEX IF NOT EXISTS ix_signals_sym_status ON signals(symbol, status);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL, kind TEXT NOT NULL, detail TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS locks(
  symbol TEXT PRIMARY KEY, locked_until INTEGER NOT NULL, reason TEXT DEFAULT ''
);
"""


def connect(path: str = "signals.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_signal(conn: sqlite3.Connection, s: dict) -> int:
    cur = conn.execute(
        "INSERT INTO signals(symbol,direction,entry,sl,tp1,tp2,qty,risk,status,opened_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (s["symbol"], s["direction"], s["entry"], s["sl"], s["tp1"], s["tp2"],
         s.get("qty", 0), s.get("risk", 0), "OPEN", s.get("opened_at", int(time.time() * 1000))),
    )
    conn.commit()
    return int(cur.lastrowid)


def close_signal(conn: sqlite3.Connection, sid: int, outcome: str, exit_px: float) -> None:
    conn.execute(
        "UPDATE signals SET status='CLOSED', outcome=?, exit_px=?, closed_at=? WHERE id=?",
        (outcome, exit_px, int(time.time() * 1000), sid),
    )
    conn.commit()


def recent_outcomes(conn: sqlite3.Connection, symbol: str, limit: int = 5) -> list[str]:
    cur = conn.execute(
        "SELECT outcome FROM signals WHERE symbol=? AND status='CLOSED' AND outcome IS NOT NULL"
        " ORDER BY closed_at DESC LIMIT ?",
        (symbol.upper(), limit),
    )
    return [r[0] for r in cur.fetchall()]


def log_event(conn: sqlite3.Connection, kind: str, detail: str = "") -> None:
    conn.execute("INSERT INTO events(ts,kind,detail) VALUES(?,?,?)",
                 (int(time.time() * 1000), kind, detail))
    conn.commit()


def set_lock(conn: sqlite3.Connection, symbol: str, locked_until_ms: int, reason: str) -> None:
    conn.execute("INSERT OR REPLACE INTO locks(symbol,locked_until,reason) VALUES(?,?,?)",
                 (symbol.upper(), locked_until_ms, reason))
    conn.commit()


def get_lock(conn: sqlite3.Connection, symbol: str, now_ms: int) -> str | None:
    cur = conn.execute("SELECT locked_until, reason FROM locks WHERE symbol=?", (symbol.upper(),))
    row = cur.fetchone()
    if row and row["locked_until"] > now_ms:
        return str(row["reason"])
    return None


def recent_closes(conn: sqlite3.Connection, window_ms: int, now_ms: int) -> list[tuple[str, int, str]]:
    """Riwayat close terbaru (untuk restore breaker): [(symbol, closed_at, outcome)]."""
    cur = conn.execute(
        "SELECT symbol, closed_at, outcome FROM signals WHERE status='CLOSED'"
        " AND closed_at IS NOT NULL AND closed_at>=? ORDER BY closed_at ASC",
        (now_ms - window_ms,),
    )
    return [(r[0], r[1], r[2]) for r in cur.fetchall() if r[2]]


def active_locks(conn: sqlite3.Connection, now_ms: int) -> list[tuple[str, int]]:
    cur = conn.execute("SELECT symbol, locked_until FROM locks WHERE locked_until>?", (now_ms,))
    return [(r[0], r[1]) for r in cur.fetchall()]
