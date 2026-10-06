"""Fase 2b tuning harness: cache klines sekali, grid-search tanpa refetch.

  python -m src.tune --symbols BTCUSDT --months 3          # grid cepat 1 simbol
  python -m src.tune --symbols BTCUSDT,ETHUSDT,SOLUSDT --months 3 --validate  # validasi top-2 di semua simbol

Grid: adx_freeze x atr_mult x vol_mult x require_1h_ema.
Metrik: expectancy_net_R (utama), WR_TP1, n sinyal.
"""
from __future__ import annotations

import argparse
import bisect
import itertools
import json
import os
import time

from src import config as cfg
from src.backtest import FEE_PCT, SLIPPAGE_PCT, SWING_N, fetch_range, to_series
from src.indicators import adx_series, atr_series, ema_series, rsi_series, sma_series
from src.risk_engine import compute_levels
from src.signal_engine import SignalEngine

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def cached_series(symbol: str, interval: str, start_ms: int, end_ms: int, rest_base: str) -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"klines_{symbol.upper()}_{interval}.json")
    rows: list = []
    if os.path.exists(path):
        with open(path) as f:
            rows = json.load(f)
    have_start = rows[0][0] if rows else None
    have_end = rows[-1][0] if rows else None
    if rows and have_start is not None and have_start <= start_ms and have_end is not None and have_end >= end_ms - 15 * 60 * 1000:
        rows = [r for r in rows if start_ms - 1 <= r[0] <= end_ms]
    else:
        rows = fetch_range(symbol, interval, start_ms, end_ms, rest_base)
        with open(path, "w") as f:
            json.dump(rows, f)
    return to_series(rows)


def evaluate(symbol: str, months: int, rest_base: str, p: dict) -> dict:
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int(months * 30.44 * 24 * 3600 * 1000)
    fstart = start_ms - 60 * 24 * 3600 * 1000
    i15 = cached_series(symbol, "15m", fstart, now_ms, rest_base)
    i1h = cached_series(symbol, "1h", fstart, now_ms, rest_base)
    i4h = cached_series(symbol, "4h", fstart, now_ms, rest_base)
    n15 = len(i15["c"])

    e21 = ema_series(i15["c"], 21)
    e55 = ema_series(i15["c"], 55)
    a15 = atr_series(i15["h"], i15["l"], i15["c"], 14)
    r15 = rsi_series(i15["c"], 14)
    vs = sma_series(i15["v"], 20)
    r1 = rsi_series(i1h["c"], 14)
    e55_1h = ema_series(i1h["c"], 55)
    e200_4 = ema_series(i4h["c"], 200)
    ax, _, _ = adx_series(i4h["h"], i4h["l"], i4h["c"], 14)

    eng = SignalEngine(vol_mult=p["vol_mult"], adx_freeze=p["adx_freeze"],
                       adx_unfreeze=p["adx_freeze"] + 2.0)
    trades: list[dict] = []
    for i in range(n15):
        t = i15["t"][i]
        if t < start_ms:
            continue
        j1 = bisect.bisect_right(i1h["t"], t) - 1
        j4 = bisect.bisect_right(i4h["t"], t) - 1
        if j1 < 1 or j4 < 0:
            continue
        regime = eng.update_regime_4h(symbol, i4h["c"][j4], e200_4[j4], ax[j4])
        if e21[i] is None or e55[i] is None or a15[i] is None or r15[i] is None or vs[i] is None:
            continue
        if i == 0 or r1[j1] is None:
            continue
        # filter 1H EMA alignment (eksperimen)
        if p["require_1h_ema"] and e55_1h[j1] is not None:
            if regime == "BULLISH" and not (i1h["c"][j1] > e55_1h[j1]):
                continue
            if regime == "BEARISH" and not (i1h["c"][j1] < e55_1h[j1]):
                continue
        vr = i15["v"][i] / vs[i] if vs[i] else 0
        sig = eng.evaluate_15m(
            symbol, i, t, regime,
            {"low": i15["l"][i], "high": i15["h"][i], "close": i15["c"][i]},
            r15[i - 1], r15[i], r1[j1], e21[i], e55[i], a15[i], vr,
        )
        if sig is None:
            continue
        lo = max(0, i - SWING_N)
        s0 = max(0, i - 50)
        if sig.direction == "LONG":
            entry = i15["c"][i] * (1 + SLIPPAGE_PCT)
            swing_lo = min(i15["l"][lo:i]) if i > lo else i15["l"][i]
            lv = compute_levels("LONG", entry, swing_lo, 0.0, a15[i] or 0, p["atr_mult"],
                                struct_resistance=max(i15["h"][s0:i]) if i > s0 else None)
        else:
            entry = i15["c"][i] * (1 - SLIPPAGE_PCT)
            swing_hi = max(i15["h"][lo:i]) if i > lo else i15["h"][i]
            lv = compute_levels("SHORT", entry, 0.0, swing_hi, a15[i] or 0, p["atr_mult"],
                                struct_support=min(i15["l"][s0:i]) if i > s0 else None)
        if lv is None:
            continue
        outcome = "EXPIRED"
        bep, t1 = lv.entry, False
        for k in range(i + 1, min(n15, i + 201)):
            h, l = i15["h"][k], i15["l"][k]
            sln = bep if t1 else lv.sl
            if sig.direction == "LONG":
                if l <= sln:
                    outcome = "SL_BEP" if t1 else "SL_HIT"
                    break
                if not t1 and h >= lv.tp1:
                    t1, bep = True, lv.entry
                    continue
                if t1 and h >= lv.tp2:
                    outcome = "TP2_HIT"
                    break
            else:
                if h >= sln:
                    outcome = "SL_BEP" if t1 else "SL_HIT"
                    break
                if not t1 and l <= lv.tp1:
                    t1, bep = True, lv.entry
                    continue
                if t1 and l <= lv.tp2:
                    outcome = "TP2_HIT"
                    break
        else:
            if t1:
                outcome = "TP1_ONLY"
        trades.append({"outcome": outcome, "entry": lv.entry, "risk": lv.risk})

    n = len(trades)
    wins = sum(1 for x in trades if x["outcome"] in ("TP1_ONLY", "TP2_HIT"))
    r_tot, fee_r = 0.0, 0.0
    for x in trades:
        if x["outcome"] == "TP2_HIT":
            r_tot += 1.75
        elif x["outcome"] == "TP1_ONLY":
            r_tot += 0.75
        elif x["outcome"] == "SL_HIT":
            r_tot -= 1.0
        fee_r += (x["entry"] * FEE_PCT * 2) / x["risk"] if x["risk"] else 0
    return {"n": n, "wr": round(100 * wins / n, 1) if n else 0.0,
            "exp_net": round((r_tot - fee_r) / n, 3) if n else 0.0,
            "exp_gross": round(r_tot / n, 3) if n else 0.0}


GRID = {
    "adx_freeze": [20.0, 25.0, 30.0],
    "atr_mult": [1.0, 1.5],
    "vol_mult": [1.0, 1.3],
    "require_1h_ema": [False, True],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTCUSDT")
    ap.add_argument("--months", type=int, default=3)
    ap.add_argument("--rest", default=cfg.BINANCE_REST_BASE)
    ap.add_argument("--validate", action="store_true")
    a = ap.parse_args()
    syms = [x.strip().upper() for x in a.symbols.split(",") if x.strip()]

    keys = list(GRID.keys())
    combos = [dict(zip(keys, v)) for v in itertools.product(*[GRID[k] for k in keys])]
    base_sym = syms[0]
    rows = []
    print(f"grid {len(combos)} kombinasi @ {base_sym} {a.months}bln...", flush=True)
    for p in combos:
        m = evaluate(base_sym, a.months, a.rest, p)
        rows.append((m["exp_net"], m["wr"], m["n"], p))
        print(f'exp_net={m["exp_net"]:+.3f} wr={m["wr"]}% n={m["n"]} {p}', flush=True)
    rows.sort(reverse=True)
    print("\nTOP-3:")
    for exp_net, wr, n, p in rows[:3]:
        print(f"  {exp_net:+.3f}R wr={wr}% n={n} {p}")
    if a.validate and len(syms) > 1:
        print("\nVALIDASI top-2 di semua simbol:")
        for _, _, _, p in rows[:2]:
            print(f"  params={p}")
            for s in syms:
                m = evaluate(s, a.months, a.rest, p)
                print(f'    {s}: exp_net={m["exp_net"]:+.3f} wr={m["wr"]}% n={m["n"]}')


if __name__ == "__main__":
    main()
