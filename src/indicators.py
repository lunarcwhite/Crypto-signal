"""Indikator teknikal pure-stdlib (tanpa numpy/pandas).

Semua fungsi memakai data closed candle saja (tanpa repaint).
Konvensi Wilder (RSI/ATR/ADX) mengikuti definisi klasik Wilder's smoothing.
Referensi PRD Modul 2: EMA(21/55/200), RSI(14), ADX(14), ATR(14), SMA volume(20).
"""
from __future__ import annotations


def ema_series(closes: list[float], period: int) -> list[float | None]:
    """EMA dengan seed SMA(period) pada indeks period-1. Awal yang belum cukup = None."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if period <= 0 or n < period:
        return out
    k = 2.0 / (period + 1.0)
    seed = sum(closes[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = closes[i] * k + prev * (1.0 - k)
        out[i] = prev
    return out


def sma_series(values: list[float], period: int) -> list[float | None]:
    n = len(values)
    out: list[float | None] = [None] * n
    if period <= 0 or n < period:
        return out
    window = sum(values[:period])
    out[period - 1] = window / period
    for i in range(period, n):
        window += values[i] - values[i - period]
        out[i] = window / period
    return out


def _wilder_smooth(gains: list[float], period: int) -> list[float | None]:
    n = len(gains)
    out: list[float | None] = [None] * n
    if n < period or period <= 0:
        return out
    avg = sum(gains[:period]) / period
    out[period - 1] = avg
    for i in range(period, n):
        avg = (avg * (period - 1) + gains[i]) / period
        out[i] = avg
    return out


def rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period + 1 or period <= 0:
        return out
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        chg = closes[i] - closes[i - 1]
        gains[i] = chg if chg > 0 else 0.0
        losses[i] = -chg if chg < 0 else 0.0
    # Wilder dimulai dari indeks `period` (butuh `period` delta)
    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    out[period] = 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    ag, al = avg_gain, avg_loss
    for i in range(period + 1, n):
        ag = (ag * (period - 1) + gains[i]) / period
        al = (al * (period - 1) + losses[i]) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def atr_series(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]:
    n = len(closes)
    out: list[float | None] = [None] * n
    if n < period + 1 or not (len(highs) == n and len(lows) == n):
        return out
    trs = [0.0] * n
    for i in range(n):
        if i == 0:
            trs[i] = highs[i] - lows[i]
        else:
            trs[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    atr = _wilder_smooth(trs, period)
    # _wilder_smooth seed di period-1 padahal TR butuh offset 1; geser agar konsisten RSI:
    # TR[0] valid tapi ATR pertama yang sah ada di indeks `period`.
    for i in range(period):
        atr[i] = None
    return atr


def adx_series(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Return (adx, plus_di, minus_di). ADX pertama yang sah di indeks 2*period."""
    n = len(closes)
    none: list[float | None] = [None] * n
    if n < 2 * period + 1:
        return list(none), list(none), list(none)
    p_dm = [0.0] * n
    m_dm = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        p_dm[i] = up if up > dn and up > 0 else 0.0
        m_dm[i] = dn if dn > up and dn > 0 else 0.0
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
    tr[0] = highs[0] - lows[0]

    s_tr: list[float] = [0.0] * n
    s_p: list[float] = [0.0] * n
    s_m: list[float] = [0.0] * n
    s_tr[period] = sum(tr[1 : period + 1])
    s_p[period] = sum(p_dm[1 : period + 1])
    s_m[period] = sum(m_dm[1 : period + 1])
    for i in range(period + 1, n):
        s_tr[i] = s_tr[i - 1] - s_tr[i - 1] / period + tr[i]
        s_p[i] = s_p[i - 1] - s_p[i - 1] / period + p_dm[i]
        s_m[i] = s_m[i - 1] - s_m[i - 1] / period + m_dm[i]

    pdi: list[float | None] = [None] * n
    mdi: list[float | None] = [None] * n
    dx: list[float] = [0.0] * n
    for i in range(period, n):
        if s_tr[i] == 0:
            pdi[i], mdi[i] = 0.0, 0.0
        else:
            pdi[i] = 100.0 * s_p[i] / s_tr[i]
            mdi[i] = 100.0 * s_m[i] / s_tr[i]
        denom = (pdi[i] or 0) + (mdi[i] or 0)
        dx[i] = 0.0 if denom == 0 else 100.0 * abs((pdi[i] or 0) - (mdi[i] or 0)) / denom

    adx: list[float | None] = [None] * n
    adx[2 * period - 1] = sum(dx[period : 2 * period]) / period
    for i in range(2 * period, n):
        prev = adx[i - 1]
        assert prev is not None
        adx[i] = (prev * (period - 1) + dx[i]) / period
    return adx, pdi, mdi
