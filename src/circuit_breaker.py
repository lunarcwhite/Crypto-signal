"""Modul 4: Circuit Breaker per PRD v1.1 (kalender makro + loss-lock).

- Kalender: econ_calendar.json (list {time_ms|time_iso, title, impact}).
  Freeze ±60 menit di sekitar event high-impact. Waktu UTC.
  Bila file hilang/rusak -> fail-closed hanya bila ada ENV ECON_FREEZE_ON_ERROR=1,
  default fail-open + log WARN (agar bot tidak mati diam-diam).
- Loss-lock: 2x SL_HIT berturut-turut (tanpa TP di antara) per simbol dalam
  24 jam rolling -> kunci 12 jam. Dihitung dari SQLite (store.recent_outcomes
  + timestamps). Di sini disederhanakan: panggil note_outcome() tiap close.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)
FREEZE_MS = 60 * 60 * 1000
LOCK_MS = 12 * 3600 * 1000
WINDOW_MS = 24 * 3600 * 1000


def _parse_time(v) -> int | None:
    try:
        if isinstance(v, (int, float)):
            return int(v)  # ms epoch
        s = str(v).strip()
        if s.isdigit():
            iv = int(s)
            return iv if iv > 10_000_000_000 else iv * 1000
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def load_events(path: str = "econ_calendar.json") -> list[dict]:
    try:
        with open(path) as f:
            raw = json.load(f)
    except FileNotFoundError:
        log.warning("econ_calendar.json tidak ada -> tanpa freeze makro")
        return []
    except Exception:
        log.exception("econ_calendar.json rusak")
        if os.getenv("ECON_FREEZE_ON_ERROR") == "1":
            raise
        return []
    out = []
    for e in raw if isinstance(raw, list) else []:
        t = _parse_time(e.get("time_ms", e.get("time", e.get("datetime"))))
        impact = str(e.get("impact", "high")).lower()
        if t and impact in ("high", "medium"):
            if impact == "high" or str(e.get("title", "")).upper() in (
                "FOMC", "CPI", "NFP", "PPI", "FED", "GDP", "ADP"):
                out.append({"t": t, "title": str(e.get("title", "?"))})
    return out


class CircuitBreaker:
    def __init__(self, calendar_path: str = "econ_calendar.json",
                 lock_ms: int = LOCK_MS, window_ms: int = WINDOW_MS) -> None:
        self.events = load_events(calendar_path)
        self.lock_ms = lock_ms
        self.window_ms = window_ms
        self._locks: dict[str, int] = {}  # symbol -> locked_until_ms
        self._closes: dict[str, list[tuple[int, str]]] = {}  # symbol -> [(ts, outcome)]

    def macro_frozen(self, now_ms: int) -> dict | None:
        for e in self.events:
            if abs(now_ms - e["t"]) <= FREEZE_MS:
                return e
        return None

    def note_close(self, symbol: str, ts_ms: int, outcome: str) -> None:
        s = symbol.upper()
        lst = self._closes.setdefault(s, [])
        lst.append((ts_ms, outcome))
        lst[:] = [(t, o) for t, o in lst if ts_ms - t <= self.window_ms]
        # 2x SL_HIT berturut-turut (tanpa TP1/TP2 di antara) -> lock
        seq = [o for _, o in sorted(lst)]
        if len(seq) >= 2 and seq[-1] == "SL_HIT" and seq[-2] == "SL_HIT":
            self._locks[s] = ts_ms + self.lock_ms

    def symbol_locked(self, symbol: str, now_ms: int) -> bool:
        return self._locks.get(symbol.upper(), 0) > now_ms

    def restore(self, conn, now_ms: int) -> dict:
        """Pulihkan state dari SQLite setelah restart. Return ringkasan."""
        from src.store import active_locks, recent_closes

        n_close, n_lock = 0, 0
        for sym, until in active_locks(conn, now_ms):
            self._locks[sym.upper()] = until
            n_lock += 1
        for sym, ts, outcome in recent_closes(conn, self.window_ms, now_ms):
            lst = self._closes.setdefault(sym.upper(), [])
            lst.append((ts, outcome))
            n_close += 1
        # terapkan ulang aturan lock dari histori yang dipulihkan
        for sym, lst in self._closes.items():
            seq = [o for _, o in sorted(lst)]
            if len(seq) >= 2 and seq[-1] == "SL_HIT" and seq[-2] == "SL_HIT":
                last_ts = sorted(lst)[-1][0]
                if last_ts + self.lock_ms > now_ms:
                    self._locks[sym] = last_ts + self.lock_ms
        return {"restored_closes": n_close, "restored_locks": n_lock}

    def allow(self, symbol: str, now_ms: int) -> tuple[bool, str]:
        mz = self.macro_frozen(now_ms)
        if mz:
            return False, f"MACRO_FREEZE:{mz['title']}"
        if self.symbol_locked(symbol, now_ms):
            return False, "SYMBOL_LOCKED:2xSL/24h"
        return True, "OK"
