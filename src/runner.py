"""Paper runner Fase 3/4: live WS -> engine -> risk -> breaker -> dispatcher + tracker.

  python -m src.runner --dry-run   # tanpa kirim Telegram, hanya print+SQLite

Tracker: tiap sinyal OPEN di-mark ke closed candle 15M berikutnya
(SL dicek dulu, lalu TP1/TP2 — PRD Modul 3). Hasil dicatat ke SQLite dan
di-note ke CircuitBreaker untuk loss-lock.
"""
from __future__ import annotations

import argparse
import asyncio
import bisect
import logging
import sys
import time
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

load_dotenv()

from src import config as cfg
from src.circuit_breaker import CircuitBreaker
from src.data_ingestion import CandleBuffer, run_forever
from src.dispatcher import Dispatcher, format_signal_message
from src.indicators import adx_series, atr_series, ema_series, rsi_series, sma_series
from src.risk_engine import compute_levels, position_qty
from src.signal_engine import SignalEngine
from src.store import close_signal, connect, get_lock, log_event, save_signal, set_lock

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("runner")


def build_runner(dry_run: bool = True, db_path: str = "signals.db"):
    conn = connect(db_path)
    eng = SignalEngine()
    brk = CircuitBreaker()
    restored = brk.restore(conn, int(time.time() * 1000))
    log.info("breaker restore: %s", restored)
    disp = Dispatcher(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_IDS,
                      cfg.DISCORD_WEBHOOK_URL) if not dry_run else Dispatcher()
    buf = CandleBuffer(maxlen=600)
    open_trades: dict[int, dict] = {}  # signal_id -> {lv, symbol, dir, qty}
    state = {"started_at": time.time(), "last_candle_at": {}, "open_trades": open_trades,
             "dry_run": dry_run, "db_path": db_path}
    return conn, eng, brk, disp, buf, open_trades, state


async def main_async(dry_run: bool, db_path: str, health_port: int = 0) -> None:
    conn, eng, brk, disp, buf, open_trades, state = build_runner(dry_run, db_path)
    log.info("paper runner start symbols=%s dry_run=%s", cfg.SYMBOLS, dry_run)
    if health_port:
        from src.health import start_health_server

        def _status():
            now = time.time()
            ages = {s: round(now - t, 1) for s, t in state["last_candle_at"].items()}
            return {"uptime_s": round(now - state["started_at"], 1),
                    "symbols": cfg.SYMBOLS, "open_trades": len(open_trades),
                    "last_candle_age_s": ages, "dry_run": dry_run}
        try:
            start_health_server(health_port, _status)
            log.info("health: http://127.0.0.1:%d/health", health_port)
        except OSError:
            log.error("port health %d terpakai — kemungkinan instance lain berjalan. STOP.", health_port)
            sys.exit(2)

    def track_closed(symbol: str, candle) -> None:
        # mark semua OPEN untuk simbol ini
        done = []
        for sid, t in open_trades.items():
            if t["symbol"] != symbol:
                continue
            lv, d = t["lv"], t["dir"]
            sl_now = t.get("bep") or lv["sl"]
            hit = None
            if d == "LONG":
                if candle.low <= sl_now:
                    hit = ("SL_BEP" if t.get("tp1_done") else "SL_HIT", sl_now)
                elif not t.get("tp1_done") and candle.high >= lv["tp1"]:
                    t["tp1_done"] = True
                    t["bep"] = lv["entry"]
                    log.info("TP1 %s -> BEP", sid)
                    continue
                elif t.get("tp1_done") and candle.high >= lv["tp2"]:
                    hit = ("TP2_HIT", lv["tp2"])
            else:
                if candle.high >= sl_now:
                    hit = ("SL_BEP" if t.get("tp1_done") else "SL_HIT", sl_now)
                elif not t.get("tp1_done") and candle.low <= lv["tp1"]:
                    t["tp1_done"] = True
                    t["bep"] = lv["entry"]
                    log.info("TP1 %s -> BEP", sid)
                    continue
                elif t.get("tp1_done") and candle.low <= lv["tp2"]:
                    hit = ("TP2_HIT", lv["tp2"])
            if hit:
                outcome, px = hit
                close_signal(conn, sid, outcome, px)
                brk.note_close(symbol, int(time.time() * 1000), outcome)
                if outcome == "SL_HIT":
                    # cek apakah memicu lock (breaker sudah update internal)
                    if brk.symbol_locked(symbol, int(time.time() * 1000)):
                        set_lock(conn, symbol, int(time.time() * 1000) + 12 * 3600 * 1000,
                                 "2xSL/24h")
                        log_event(conn, "SYMBOL_LOCKED", symbol)
                log.info("close #%d %s %s @%s", sid, symbol, outcome, px)
                done.append(sid)
        for sid in done:
            open_trades.pop(sid, None)

    STRUCT_LOOKBACK = 50  # candle 15M untuk resistance/support TP2

    async def on_candle(c):
        t_compute_start = time.perf_counter()
        buf.push(c)
        state["last_candle_at"][c.symbol] = time.time()
        if c.interval != "15m":
            return
        track_closed(c.symbol, c)
        sym = c.symbol
        now_ms = int(time.time() * 1000)
        ok, reason = brk.allow(sym, now_ms)
        if not ok:
            return
        if get_lock(conn, sym, now_ms):
            return
        # butuh deret cukup per TF
        c15 = [x for x in buf._data[(sym, "15m")]]
        c1h = [x for x in buf._data[(sym, "1h")]]
        c4h = [x for x in buf._data[(sym, "4h")]]
        if len(c15) < 60 or len(c1h) < 60 or len(c4h) < 210:
            return
        cl15 = [x.close for x in c15]
        e21, e55 = ema_series(cl15, 21)[-1], ema_series(cl15, 55)[-1]
        a15 = atr_series([x.high for x in c15], [x.low for x in c15], cl15, 14)[-1]
        r15 = rsi_series(cl15, 14)
        vs = sma_series([x.volume for x in c15], 20)[-1]
        cl1 = [x.close for x in c1h]
        r1 = rsi_series(cl1, 14)[-1]
        cl4 = [x.close for x in c4h]
        e200 = ema_series(cl4, 200)[-1]
        ax = adx_series([x.high for x in c4h], [x.low for x in c4h], cl4, 14)[0][-1]
        regime = eng.update_regime_4h(sym, cl4[-1], e200, ax)
        if None in (e21, e55, a15, vs) or r15[-1] is None or r15[-2] is None or r1 is None:
            return
        vr = c.volume / vs if vs else 0
        sig = eng.evaluate_15m(sym, len(c15), c.open_time, regime,
                               {"low": c.low, "high": c.high, "close": c.close},
                               r15[-2], r15[-1], r1, e21, e55, a15, vr)
        if sig is None:
            return
        lows15 = [x.low for x in c15[-21:-1]]
        highs15 = [x.high for x in c15[-21:-1]]
        struct_high = max(x.high for x in c15[-STRUCT_LOOKBACK - 1:-1])
        struct_low = min(x.low for x in c15[-STRUCT_LOOKBACK - 1:-1])
        if sig.direction == "LONG":
            lv = compute_levels("LONG", c.close * 1.001, min(lows15), 0.0, a15 or 0,
                                struct_resistance=struct_high)
        else:
            lv = compute_levels("SHORT", c.close * 0.999, 0.0, max(highs15), a15 or 0,
                                struct_support=struct_low)
        if lv is None:
            log.info("sinyal digugurkan: RRR_TP2<1:2 vs struktur")
            return
        qty = position_qty(cfg.EQUITY_USDT, cfg.RISK_PCT / 100.0, lv.risk)
        compute_ms = (time.perf_counter() - t_compute_start) * 1000.0
        sid = save_signal(conn, {"symbol": sym, "direction": sig.direction, "entry": lv.entry,
                                 "sl": lv.sl, "tp1": lv.tp1, "tp2": lv.tp2,
                                 "qty": qty, "risk": lv.risk})
        open_trades[sid] = {"symbol": sym, "dir": sig.direction, "lv": lv}
        msg = format_signal_message({"symbol": sym, "direction": sig.direction},
                                    {"entry": lv.entry, "sl": lv.sl, "tp1": lv.tp1, "tp2": lv.tp2},
                                    {"adx_4h": ax or 0, "regime": regime, "atr": a15 or 0, "qty": qty})
        t_send_start = time.perf_counter()
        r = disp.send(msg)
        delivery_ms = (time.perf_counter() - t_send_start) * 1000.0
        log.info("latensi compute=%.0fms delivery=%.0fms (target <800ms / <5000ms)",
                 compute_ms, delivery_ms)
        log_event(conn, "SIGNAL", f"{sym} {sig.direction} id={sid} {r} "
                                  f"compute_ms={compute_ms:.0f} delivery_ms={delivery_ms:.0f}")
        log.info("sinyal #%d %s %s entry=%s", sid, sym, sig.direction, lv.entry)

    await run_forever(cfg.BINANCE_WS_BASE, cfg.BINANCE_REST_BASE, cfg.SYMBOLS, on_candle)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--db", default="signals.db")
    ap.add_argument("--health-port", type=int, default=None)
    ap.add_argument("--log-file", default="")
    a = ap.parse_args()
    if a.log_file:
        h = RotatingFileHandler(a.log_file, maxBytes=5_000_000, backupCount=3)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger().addHandler(h)
    port = cfg.HEALTH_PORT if a.health_port is None else a.health_port
    asyncio.run(main_async(dry_run=not a.live, db_path=a.db, health_port=port))


if __name__ == "__main__":
    main()
