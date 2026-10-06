"""Modul 2: Signal Engine per PRD v1.1.

Hierarki: 4H bias (filter) -> 1H konfirmasi -> 15M trigger.
Semua input adalah candle CLOSED (anti-repaint). Fungsi murni + class stateful
untuk hysteresis ADX dan deduplikasi.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PULLBACK_TOL_ATR = 0.5
BREAKDOWN_GUARD_ATR = 1.0
VOL_MULT = 1.0
RSI_LONG_CROSS = 40.0
RSI_SHORT_CROSS = 60.0
RSI_LONG_HOLD = 45.0
RSI_SHORT_HOLD = 55.0
RSI_1H_LONG_A = 40.0
RSI_1H_SHORT_A = 60.0
RSI_1H_LONG_B = 45.0
RSI_1H_SHORT_B = 55.0
DEDUP_CANDLES_15M = 6  # 90 menit


@dataclass
class Signal:
    symbol: str
    direction: str  # LONG | SHORT
    entry: float
    open_time: int
    index_15m: int


def pullback_long(low: float, close: float, ema21: float, ema55: float, atr: float) -> bool:
    tol = PULLBACK_TOL_ATR * atr
    touch = abs(low - ema21) <= tol or abs(close - ema21) <= tol or abs(low - ema55) <= tol or abs(close - ema55) <= tol
    breakdown = close < min(ema21, ema55) - BREAKDOWN_GUARD_ATR * atr
    return bool(touch and not breakdown)


def pullback_short(high: float, close: float, ema21: float, ema55: float, atr: float) -> bool:
    tol = PULLBACK_TOL_ATR * atr
    touch = abs(high - ema21) <= tol or abs(close - ema21) <= tol or abs(high - ema55) <= tol or abs(close - ema55) <= tol
    breakdown = close > max(ema21, ema55) + BREAKDOWN_GUARD_ATR * atr
    return bool(touch and not breakdown)


@dataclass
class SymbolState:
    frozen_choppy: bool = False  # hysteresis ADX
    last_sig_idx: dict[str, int] = field(default_factory=dict)  # direction -> idx 15m
    last_open_time: dict[str, int] = field(default_factory=dict)


class SignalEngine:
    """Stateful per simbol untuk hysteresis + dedup. Indikator dihitung di luar."""

    def __init__(
        self,
        vol_mult: float = VOL_MULT,
        adx_freeze: float = 30.0,
        adx_unfreeze: float = 32.0,
    ) -> None:
        self._st: dict[str, SymbolState] = {}
        self.vol_mult = vol_mult
        self.adx_freeze = adx_freeze
        self.adx_unfreeze = adx_unfreeze

    def _state(self, symbol: str) -> SymbolState:
        return self._st.setdefault(symbol.upper(), SymbolState())

    def update_regime_4h(self, symbol: str, close_4h: float, ema200_4h: float | None, adx_4h: float | None) -> str:
        """Return 'BULLISH' | 'BEARISH' | 'CHOPPY' | 'WARMING_UP'. Kelola hysteresis."""
        st = self._state(symbol)
        if ema200_4h is None or adx_4h is None:
            return "WARMING_UP"
        if st.frozen_choppy:
            if adx_4h >= self.adx_unfreeze:
                st.frozen_choppy = False
            else:
                return "CHOPPY"
        elif adx_4h <= self.adx_freeze:
            st.frozen_choppy = True
            return "CHOPPY"
        if close_4h > ema200_4h:
            return "BULLISH"
        if close_4h < ema200_4h:
            return "BEARISH"
        return "CHOPPY"

    def evaluate_15m(
        self,
        symbol: str,
        idx: int,
        open_time: int,
        regime_4h: str,
        ohlc_15m: dict,
        rsi_prev_15m: float | None,
        rsi_curr_15m: float | None,
        rsi_1h: float | None,
        ema21_15m: float | None,
        ema55_15m: float | None,
        atr_15m: float | None,
        vol_ratio: float | None,
    ) -> Signal | None:
        st = self._state(symbol)
        if regime_4h in ("CHOPPY", "WARMING_UP"):
            return None
        if None in (rsi_prev_15m, rsi_curr_15m, rsi_1h, ema21_15m, ema55_15m, atr_15m, vol_ratio):
            return None
        assert atr_15m and ema21_15m is not None and ema55_15m is not None
        if atr_15m <= 0 or vol_ratio is None or vol_ratio < self.vol_mult:
            return None

        low, high, close = ohlc_15m["low"], ohlc_15m["high"], ohlc_15m["close"]
        assert rsi_prev_15m is not None and rsi_curr_15m is not None and rsi_1h is not None

        direction: str | None = None
        if regime_4h == "BULLISH":
            pb = pullback_long(low, close, ema21_15m, ema55_15m, atr_15m)
            path_a = rsi_prev_15m < RSI_LONG_CROSS and rsi_curr_15m > RSI_LONG_CROSS and rsi_1h > RSI_1H_LONG_A
            path_b = rsi_curr_15m > RSI_LONG_HOLD and rsi_1h > RSI_1H_LONG_B
            if pb and (path_a or path_b):
                direction = "LONG"
        elif regime_4h == "BEARISH":
            pb = pullback_short(high, close, ema21_15m, ema55_15m, atr_15m)
            path_a = rsi_prev_15m > RSI_SHORT_CROSS and rsi_curr_15m < RSI_SHORT_CROSS and rsi_1h < RSI_1H_SHORT_A
            path_b = rsi_curr_15m < RSI_SHORT_HOLD and rsi_1h < RSI_1H_SHORT_B
            if pb and (path_a or path_b):
                direction = "SHORT"
        if direction is None:
            return None

        # Deduplikasi: 1 sinyal per arah per 6 candle 15M
        last = st.last_sig_idx.get(direction)
        if last is not None and idx - last < DEDUP_CANDLES_15M:
            return None
        st.last_sig_idx[direction] = idx
        st.last_open_time[direction] = open_time
        return Signal(symbol=symbol.upper(), direction=direction, entry=close, open_time=open_time, index_15m=idx)
