"""Backtest Fase 2: fetch 12 bulan (default) lalu evaluasi expectancy.

Asumsi PRD: fee 0.05%/sisi, slippage 0.1% (di entry).
Tracker konservatif: cek SL dulu (wick), lalu TP1/TP2 per candle 15M.
Keluar: WR_TP1, WR_TP2, expectancy (R), jumlah sinyal, contoh break.

Cara pakai:
  python -m src.backtest --symbols BTCUSDT --months 1   # smoke cepat
  python -m src.backtest --symbols BTCUSDT,ETHUSDT,SOLUSDT --months 12
"""
from __future__ import annotations

import argparse
import bisect
import json
import time
import urllib.parse
import urllib.request

from src import config as cfg
from src.indicators import adx_series, atr_series, ema_series, rsi_series, sma_series
from src.risk_engine import compute_levels
from src.signal_engine import SignalEngine

FEE_PCT = 0.0005
SLIPPAGE_PCT = 0.001
SWING_N = 20


def fetch_range(symbol: str, interval: str, start_ms: int, end_ms: int, rest_base: str) -> list:
    out, cursor = [], start_ms
    while True:
        qs = urllib.parse.urlencode(
            {"symbol": symbol.upper(), "interval": interval, "limit": 1000,
             "startTime": cursor, "endTime": end_ms}
        )
        url = f"{rest_base.rstrip('/')}/api/v3/klines?{qs}"
        req = urllib.request.Request(url, headers={"User-Agent": "trend-pullback-backtest/1.1"})
        rows = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        if not rows:
            break
        out.extend(rows)
        cursor = int(rows[-1][0]) + 1
        if len(rows) < 1000 or cursor >= end_ms:
            break
        time.sleep(0.2)  # hormati rate-limit
    # dedup + sort
    seen, clean = set(), []
    for r in sorted(out, key=lambda x: x[0]):
        if r[0] not in seen:
            seen.add(r[0])
            clean.append(r)
    return clean


def to_series(rows: list) -> dict:
    return {
        "t": [int(r[0]) for r in rows],
        "o": [float(r[1]) for r in rows],
        "h": [float(r[2]) for r in rows],
        "l": [float(r[3]) for r in rows],
        "c": [float(r[4]) for r in rows],
        "v": [float(r[5]) for r in rows],
    }


def run_symbol(symbol: str, months: int, rest_base: str) -> dict:
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int(months * 30.44 * 24 * 3600 * 1000)
    buf_ms = 60 * 24 * 3600 * 1000  # 60 hari buffer agar EMA200-4H/ADX valid
    fstart = start_ms - buf_ms
    i15 = to_series(fetch_range(symbol, "15m", fstart, now_ms, rest_base))
    i1h = to_series(fetch_range(symbol, "1h", fstart, now_ms, rest_base))
    i4h = to_series(fetch_range(symbol, "4h", fstart, now_ms, rest_base))
    n15 = len(i15["c"])
    if n15 < 300:
        return {"symbol": symbol, "error": f"data kurang ({n15})"}

    e21 = ema_series(i15["c"], 21)
    e55 = ema_series(i15["c"], 55)
    atr15 = atr_series(i15["h"], i15["l"], i15["c"], 14)
    rsi15 = rsi_series(i15["c"], 14)
    vol_sma = sma_series(i15["v"], 20)
    rsi1 = rsi_series(i1h["c"], 14)
    e200_4 = ema_series(i4h["c"], 200)
    adx4, _, _ = adx_series(i4h["h"], i4h["l"], i4h["c"], 14)

    eng = SignalEngine()
    trades: list[dict] = []

    for i in range(n15):
        t = i15["t"][i]
        if t < start_ms:
            continue  # buffer warmup, tidak dievaluasi
        # petakan 1H/4H terakhir yang sudah close saat candle 15M ini tutup (t+15min)
        j1 = bisect.bisect_right(i1h["t"], t - 2_700_000) - 1   # 1H terakhir yg SUDAH close
        j4 = bisect.bisect_right(i4h["t"], t - 13_500_000) - 1  # 4H terakhir yg SUDAH close
        if j1 < 1 or j4 < 0:
            continue
        c4, e200, ax = i4h["c"][j4], e200_4[j4], adx4[j4]
        regime = eng.update_regime_4h(symbol, c4, e200, ax)
        if e21[i] is None or e55[i] is None or atr15[i] is None or rsi15[i] is None or vol_sma[i] is None:
            continue
        if i == 0:
            continue
        rsi_prev = rsi15[i - 1]
        vol_ratio = (i15["v"][i] / vol_sma[i]) if vol_sma[i] else None
        sig = eng.evaluate_15m(
            symbol, i, t, regime,
            {"low": i15["l"][i], "high": i15["h"][i], "close": i15["c"][i]},
            rsi_prev, rsi15[i], rsi1[j1] if rsi1[j1] is not None else None,
            e21[i], e55[i], atr15[i], vol_ratio,
        )
        if sig is None:
            continue
        # swing N=20 + level (slippage di entry) + cap struktur 50 candle
        lo = max(0, i - SWING_N)
        entry_raw = i15["c"][i]
        entry = entry_raw * (1 + SLIPPAGE_PCT if True else 1)  # disesuaikan per arah di bawah
        s0 = max(0, i - 50)
        if sig.direction == "LONG":
            entry = entry_raw * (1 + SLIPPAGE_PCT)
            swing_lo = min(i15["l"][lo:i]) if i > lo else i15["l"][i]
            lv = compute_levels("LONG", entry, swing_lo, 0.0, atr15[i] or 0,
                                struct_resistance=max(i15["h"][s0:i]) if i > s0 else None)
        else:
            entry = entry_raw * (1 - SLIPPAGE_PCT)
            swing_hi = max(i15["h"][lo:i]) if i > lo else i15["h"][i]
            lv = compute_levels("SHORT", entry, 0.0, swing_hi, atr15[i] or 0,
                                struct_support=min(i15["l"][s0:i]) if i > s0 else None)
        if lv is None:
            continue
        # tracker ke depan (maks 200 candle 15M ~ 2 hari)
        outcome, exit_px, exit_i = "EXPIRED", entry, -1
        bep = lv.entry
        tp1_done = False
        for k in range(i + 1, min(n15, i + 201)):
            h, l = i15["h"][k], i15["l"][k]
            sl_now = bep if tp1_done else lv.sl
            if sig.direction == "LONG":
                if l <= sl_now:
                    outcome, exit_px, exit_i = ("SL_BEP" if tp1_done else "SL_HIT"), sl_now, k
                    break
                if not tp1_done and h >= lv.tp1:
                    tp1_done = True
                    bep = lv.entry
                    continue
                if tp1_done and h >= lv.tp2:
                    outcome, exit_px, exit_i = "TP2_HIT", lv.tp2, k
                    break
            else:
                if h >= sl_now:
                    outcome, exit_px, exit_i = ("SL_BEP" if tp1_done else "SL_HIT"), sl_now, k
                    break
                if not tp1_done and l <= lv.tp1:
                    tp1_done = True
                    bep = lv.entry
                    continue
                if tp1_done and l <= lv.tp2:
                    outcome, exit_px, exit_i = "TP2_HIT", lv.tp2, k
                    break
        else:
            if tp1_done:
                outcome, exit_px = "TP1_ONLY", lv.tp1
        trades.append({"dir": sig.direction, "entry": lv.entry, "sl": lv.sl,
                       "tp1": lv.tp1, "tp2": lv.tp2, "risk": lv.risk,
                       "outcome": outcome, "exit": exit_px, "i": i, "t": t})

    # metrik: TP1 WR (TP1_ONLY+TP2 sebagai menang TP1), expectancy dalam R
    wins_tp1 = sum(1 for x in trades if x["outcome"] in ("TP1_ONLY", "TP2_HIT"))
    wins_tp2 = sum(1 for x in trades if x["outcome"] == "TP2_HIT")
    n = len(trades)
    wr1 = wins_tp1 / n if n else 0.0
    # R per trade: TP2=+2, TP1_ONLY=+1.5*0.5+0*0.5=+0.75 (50% closed, sisa BEP),
    # SL=-1, SL_BEP=+0.75*0.5? sederhanakan: TP1_ONLY=+0.75R, SL_BEP=0R (BEP), EXPIRED=0R
    r_total = 0.0
    for x in trades:
        o = x["outcome"]
        if o == "TP2_HIT":
            r_total += 0.5 * 1.5 + 0.5 * 2.0  # 1.75R (50% TP1 + 50% TP2)
        elif o == "TP1_ONLY":
            r_total += 0.5 * 1.5  # 0.75R
        elif o == "SL_HIT":
            r_total -= 1.0
        # SL_BEP / EXPIRED = 0
    # biaya: 2 sisi * 0.05% dikonversi ke R (pendekatan: fee/entry-risk ratio per trade)
    fees_r = 0.0
    for x in trades:
        notional = x["entry"]
        fee_abs = notional * FEE_PCT * 2
        fees_r += fee_abs / x["risk"] if x["risk"] else 0
    exp_gross = r_total / n if n else 0.0
    exp_net = (r_total - fees_r) / n if n else 0.0
    return {"symbol": symbol, "n15": n15, "signals": n,
            "wr_tp1": round(wr1 * 100, 1), "wr_tp2": round(wins_tp2 / n * 100, 1) if n else 0.0,
            "expectancy_gross_R": round(exp_gross, 3), "expectancy_net_R": round(exp_net, 3),
            "pass": bool(n > 0 and exp_net > 0.2),
            "tail": [(x["dir"], x["outcome"]) for x in trades[-5:]]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=",".join(cfg.SYMBOLS))
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--rest", default=cfg.BINANCE_REST_BASE)
    a = ap.parse_args()
    for s in [x.strip().upper() for x in a.symbols.split(",") if x.strip()]:
        print(f"== {s} ({a.months} bln) fetching...", flush=True)
        print(json.dumps(run_symbol(s, a.months, a.rest), indent=2))


if __name__ == "__main__":
    main()
