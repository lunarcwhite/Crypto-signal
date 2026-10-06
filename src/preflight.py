"""Preflight deploy: validasi semua prasyarat sebelum paper/live.

  python -m src.preflight              # cek tanpa kirim pesan
  python -m src.preflight --send-test  # + kirim pesan uji Telegram (butuh token)

Exit 0 bila semua PASS, 1 bila ada FAIL.env yang dicek ada di .env.example.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import urllib.request

from dotenv import load_dotenv

load_dotenv()

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send-test", action="store_true")
    ap.add_argument("--db", default="signals.db")
    a = ap.parse_args()

    from src import config as cfg

    check("symbols", len(cfg.SYMBOLS) > 0, ",".join(cfg.SYMBOLS))
    check("EQUITY_USDT>0", cfg.EQUITY_USDT > 0, str(cfg.EQUITY_USDT))
    check("RISK_PCT 0-100", 0 < cfg.RISK_PCT <= 100, str(cfg.RISK_PCT))
    check("TELEGRAM_BOT_TOKEN", bool(cfg.TELEGRAM_BOT_TOKEN), "terisi" if cfg.TELEGRAM_BOT_TOKEN else "KOSONG — isi .env")
    check("TELEGRAM_CHAT_IDS", len(cfg.TELEGRAM_CHAT_IDS) > 0, str(len(cfg.TELEGRAM_CHAT_IDS)))

    # econ_calendar.json valid?
    try:
        with open("econ_calendar.json") as f:
            cal = json.load(f)
        check("econ_calendar.json", isinstance(cal, list), f"{len(cal)} event")
    except Exception as e:
        check("econ_calendar.json", False, str(e)[:100])

    # SQLite writable?
    try:
        from src.store import connect
        conn = connect(a.db)
        conn.execute("INSERT INTO events(ts,kind,detail) VALUES(1,'PREFLIGHT','ok')")
        conn.rollback()
        check("sqlite writable", True, a.db)
    except Exception as e:
        check("sqlite writable", False, str(e)[:100])

    # REST snapshot?
    try:
        from src.data_ingestion import fetch_klines_rest
        cs = fetch_klines_rest(cfg.BINANCE_REST_BASE, "BTCUSDT", "15m", limit=2)
        check("REST klines", len(cs) == 2, f"close={cs[-1].close}")
    except Exception as e:
        check("REST klines", False, str(e)[:120])

    # WS streaming?
    try:
        async def _ws():
            import websockets
            url = f"{cfg.BINANCE_WS_BASE}/stream?streams=btcusdt@kline_15m"
            async with websockets.connect(url, ping_timeout=15) as ws:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                return "k" in json.loads(raw).get("data", {})
        check("WS stream", bool(asyncio.run(_ws())), "1 pesan diterima")
    except Exception as e:
        check("WS stream", False, str(e)[:120])

    # Telegram kirim asli (opsional)?
    if a.send_test:
        try:
            from src.dispatcher import Dispatcher
            d = Dispatcher(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_IDS)
            r = d.send("✅ Preflight OK — bot terhubung.")
            ok = all(x.get("ok") for x in r["telegram"])
            check("Telegram send", ok, str(r["telegram"])[:120])
        except Exception as e:
            check("Telegram send", False, str(e)[:120])

    fails = [n for n, ok, _ in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(fails)}/{len(CHECKS)} PASS")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
