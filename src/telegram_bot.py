"""Polling Telegram untuk perintah user (getUpdates, stdlib saja).

Dipakai dua cara:
  1. Otomatis di dalam runner live (lihat `src/runner.py`).
  2. Manual:  python -m src.telegram_bot --poll --db signals.db
              python -m src.telegram_bot --setup-commands

Logika parsing/format ada di `src/bot_commands.py` (murni, testable).
File ini hanya urus network Telegram + baca DB/audit.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _api(token: str, method: str, payload: dict | None = None,
         timeout: int = 30) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    if payload is None:
        req = urllib.request.Request(url, headers={"User-Agent": "trend-pullback-engine/1.3"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "trend-pullback-engine/1.3"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def setup_commands(token: str) -> dict:
    from src.bot_commands import BOT_COMMANDS
    return _api(token, "setMyCommands", {"commands": BOT_COMMANDS})


def send_message(token: str, chat_id: str | int, text: str,
                 keyboard: dict | None = None) -> dict:
    from src.bot_commands import main_menu_keyboard
    payload: dict = {"chat_id": chat_id, "text": text[:4000]}
    payload["reply_markup"] = keyboard or main_menu_keyboard()
    return _api(token, "sendMessage", payload)


# ---------------------------------------------------------------- data layer
def _db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def intent_reply(intent: dict, ctx: dict) -> tuple[str, dict | None]:
    """Bangun teks balasan dari intent. ctx: {"db_path", "state",
    "open_trades", "breaker"}. Return (text, keyboard|None)."""
    from src import bot_commands as bc

    kb = bc.main_menu_keyboard()
    cmd = intent["command"]
    prefix = bc._koreksi(intent)

    if cmd == "start":
        return prefix + bc.start_text(), kb
    if cmd == "help":
        return prefix + bc.help_text(), kb
    if cmd == "greeting":
        return bc.greeting_text(), kb
    if cmd == "unknown":
        return bc.unknown_text(intent, ctx.get("raw", "")), kb

    db_path = ctx.get("db_path", "signals.db")
    try:
        if cmd == "status":
            return prefix + bc.format_status(_status_data(ctx)), kb
        if cmd == "sinyal":
            rows = _query_signals(db_path, intent.get("symbol"), intent.get("limit") or 3)
            return prefix + bc.format_signals(rows, intent.get("symbol")), kb
        if cmd == "perf":
            from src.audit import audit
            days = intent.get("days") or 7
            since = int(time.time() * 1000) - days * 86400_000
            try:
                a = audit(db_path, since)
            except Exception:
                a = {"closed": 0}
            sym = intent.get("symbol")
            if sym and a.get("by_symbol"):
                by = a["by_symbol"].get(sym, {})
                closed_sym = sum(by.values())
                # ringkas khusus simbol bila diminta
                if closed_sym:
                    a = {**a, "closed": closed_sym,
                         "by_symbol": {sym: by},
                         "wr_tp1_pct": "?", "wr_tp2_pct": "?",
                         "expectancy_R": 0.0, "pass_kpi": False,
                         "note": "detail per-simbol: lihat audit CLI"}
            return prefix + bc.format_perf(a, days, sym), kb
        if cmd == "locks":
            locked, macro, upcoming = _locks_data(ctx)
            return prefix + bc.format_locks(locked, macro, upcoming), kb
        if cmd == "kalender":
            return prefix + bc.format_calendar(_calendar_data()), kb
    except Exception as e:  # noqa: BLE001 — user tetap dapat balasan ramah
        log.exception("gagal balas %s", cmd)
        return ("⚠️ Maaf, ada gangguan sesaat membaca data "
                f"({str(e)[:100]}). Coba lagi sebentar ya.", kb)
    return bc.unknown_text(intent, ctx.get("raw", "")), kb


def _status_data(ctx: dict) -> dict:
    state = ctx.get("state") or {}
    open_trades = ctx.get("open_trades") or {}
    now = time.time()
    ages = {s: round(now - t, 1) for s, t in (state.get("last_candle_at") or {}).items()}
    trades = [{"id": sid, "symbol": t.get("symbol"), "dir": t.get("dir"),
               "entry": (t.get("lv").entry if hasattr(t.get("lv"), "entry")
                         else (t.get("lv") or {}).get("entry", 0))}
              for sid, t in open_trades.items()]
    locked: list[str] = []
    macro: str | None = None
    brk = ctx.get("breaker")
    if brk is not None:
        now_ms = int(now * 1000)
        try:
            mz = brk.macro_frozen(now_ms)
            macro = mz["title"] if mz else None
        except Exception:
            macro = None
        for s in (ctx.get("symbols") or []):
            try:
                if brk.symbol_locked(s, now_ms):
                    locked.append(s)
            except Exception:
                pass
    closed_today = None
    try:
        conn = _db(ctx.get("db_path", "signals.db"))
        try:
            cur = conn.execute("SELECT COUNT(*) c FROM signals WHERE status='CLOSED'"
                               " AND closed_at>=?", (int(now * 1000) - 86400_000,))
            closed_today = cur.fetchone()["c"]
        finally:
            conn.close()
    except Exception:
        pass
    return {"uptime_s": now - state.get("started_at", now),
            "dry_run": state.get("dry_run", False),
            "symbols": ctx.get("symbols") or [],
            "open_trades": len(open_trades), "trades": trades,
            "last_candle_age_s": ages, "macro": macro, "locked": locked,
            "closed_today": closed_today}


def _query_signals(db_path: str, symbol: str | None, limit: int) -> list[dict]:
    conn = _db(db_path)
    try:
        if symbol:
            rows = conn.execute(
                "SELECT id,symbol,direction,entry,sl,tp1,tp2,status,outcome"
                " FROM signals WHERE symbol=? ORDER BY id DESC LIMIT ?",
                (symbol.upper(), limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id,symbol,direction,entry,sl,tp1,tp2,status,outcome"
                " FROM signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _locks_data(ctx: dict) -> tuple[list, str | None, list]:
    brk = ctx.get("breaker")
    now_ms = int(time.time() * 1000)
    locked: list[str] = []
    macro: str | None = None
    if brk is not None:
        try:
            mz = brk.macro_frozen(now_ms)
            macro = mz["title"] if mz else None
        except Exception:
            pass
        for s in (ctx.get("symbols") or []):
            try:
                if brk.symbol_locked(s, now_ms):
                    locked.append(s)
            except Exception:
                pass
    # DB locks (tahan restart)
    try:
        conn = _db(ctx.get("db_path", "signals.db"))
        try:
            rows = conn.execute("SELECT symbol FROM locks WHERE locked_until>?",
                                (now_ms,)).fetchall()
            for r in rows:
                if r["symbol"] not in locked:
                    locked.append(r["symbol"])
        finally:
            conn.close()
    except Exception:
        pass
    upcoming = [e.get("title", "?") for e in _calendar_data()[:3]]
    return locked, macro, upcoming


def _calendar_data() -> list[dict]:
    try:
        from src.circuit_breaker import load_events
        evs = load_events()
    except Exception:
        return []
    now_ms = int(time.time() * 1000)
    fut = sorted([e for e in evs if e.get("t", 0) >= now_ms - 3600_000],
                 key=lambda e: e["t"])
    out = []
    for e in fut[:5]:
        dt = datetime.fromtimestamp(e["t"] / 1000, tz=timezone.utc).strftime("%d %b %H:%M UTC")
        delta_h = (e["t"] - now_ms) / 3600_000
        when = f"{dt} ({delta_h:+.1f} jam)" if abs(delta_h) < 72 else dt
        out.append({"when": when, "title": e.get("title", "?")})
    return out


# ---------------------------------------------------------------- polling loop
class CommandBot:
    def __init__(self, token: str, allowed_ids: list[str] | None,
                 ctx: dict, sender=None) -> None:
        self.token = token
        self.allowed = {str(x).strip() for x in (allowed_ids or []) if str(x).strip()}
        self.ctx = ctx
        self._sender = sender or send_message
        self._offset = 0

    def _allowed(self, chat_id: str | int) -> bool:
        if not self.allowed:
            return True  # belum diset whitelist -> izinkan agar owner bisa baca ID-nya
        return str(chat_id) in self.allowed

    def handle_text(self, chat_id: str | int, raw: str) -> None:
        from src import bot_commands as bc
        if not self._allowed(chat_id):
            log.warning("chat %s di luar whitelist — ditolak", chat_id)
            try:
                self._sender(self.token, chat_id,
                             "⛔ Maaf, bot ini private (whitelist). "
                             "Minta admin menambahkan chat ID Anda ke TELEGRAM_CHAT_IDS.",
                             {"inline_keyboard": []})
            except Exception:
                pass
            return
        intent = bc.parse_user_input(raw)
        text, kb = intent_reply(intent, {**self.ctx, "raw": raw})
        try:
            self._sender(self.token, chat_id, text, kb)
        except Exception:
            log.exception("gagal kirim balasan ke %s", chat_id)

    def poll_once(self, timeout: int = 20) -> int:
        """Satu putaran getUpdates. Return jumlah update diproses."""
        try:
            res = _api(self.token, "getUpdates",
                       {"offset": self._offset, "timeout": timeout,
                        "allowed_updates": ["message", "callback_query"]},
                       timeout=timeout + 10)
        except Exception:
            log.warning("getUpdates gagal", exc_info=True)
            return 0
        n = 0
        for u in res.get("result", []):
            self._offset = max(self._offset, int(u.get("update_id", 0)) + 1)
            n += 1
            try:
                if "callback_query" in u:
                    cq = u["callback_query"]
                    cid = cq.get("id")
                    chat_id = (cq.get("message") or {}).get("chat", {}).get("id")
                    data = cq.get("data", "/help")
                    if cid:
                        try:
                            _api(self.token, "answerCallbackQuery", {"callback_query_id": cid})
                        except Exception:
                            pass
                    if chat_id is not None:
                        self.handle_text(chat_id, data)
                elif "message" in u:
                    m = u["message"]
                    chat_id = m.get("chat", {}).get("id")
                    raw = m.get("text", "") or ""
                    if not raw and "sticker" in m:
                        raw = "/help"
                    if chat_id is not None:
                        self.handle_text(chat_id, raw)
            except Exception:
                log.exception("gagal proses update")
        return n


async def run_polling(token: str, allowed_ids: list[str], ctx: dict) -> None:
    """Loop selamanya (dipanggil sebagai asyncio task dari runner)."""
    try:
        await asyncio.to_thread(setup_commands, token)
        log.info("menu perintah Telegram terdaftar (/start.. /kalender)")
    except Exception:
        log.warning("setMyCommands gagal (lanjut polling)", exc_info=True)
    bot = CommandBot(token, allowed_ids, ctx)
    log.info("command bot polling aktif (whitelist=%s)",
             len(bot.allowed) or "terbuka-sementara")
    while True:
        try:
            await asyncio.to_thread(bot.poll_once, 20)
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("polling error — jeda 5 dtk")
            await asyncio.sleep(5)


def main() -> None:
    ap = argparse.ArgumentParser(description="Telegram command bot (standalone).")
    ap.add_argument("--poll", action="store_true", help="jalan polling getUpdates")
    ap.add_argument("--setup-commands", action="store_true", help="daftarkan menu / ke Telegram")
    ap.add_argument("--db", default="signals.db")
    a = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv()
    from src import config as cfg

    if not cfg.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN kosong di .env")
    if a.setup_commands:
        print(json.dumps(setup_commands(cfg.TELEGRAM_BOT_TOKEN), indent=2)[:500])
    if a.poll:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        ctx = {"db_path": a.db, "symbols": cfg.SYMBOLS,
               "state": {"started_at": time.time(), "dry_run": False,
                         "last_candle_at": {}}, "open_trades": {}, "breaker": None}
        asyncio.run(run_polling(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_IDS, ctx))


if __name__ == "__main__":
    main()
