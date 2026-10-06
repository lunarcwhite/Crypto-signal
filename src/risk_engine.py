"""Modul 3 (parsial, untuk backtest): kalkulasi Entry/SL/TP per PRD v1.1 §Modul 3."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Levels:
    entry: float
    sl: float
    tp1: float
    tp2: float
    risk: float
    rrr_tp1: float = 1.5
    rrr_tp2: float = 2.0


def compute_sl(
    direction: str, swing_low: float, swing_high: float, atr: float, atr_mult: float = 1.5
) -> float:
    if direction == "LONG":
        return swing_low - atr_mult * atr
    return swing_high + atr_mult * atr


def compute_levels(
    direction: str, entry: float, swing_low: float, swing_high: float, atr: float, atr_mult: float = 1.5,
    struct_resistance: float | None = None, struct_support: float | None = None,
) -> Levels | None:
    """Return None bila RRR_TP2 < 1:2 tidak bisa dipenuhi (sinyal digugurkan).

    TP2 struktur (PRD): bila resistance (LONG) / support (SHORT) lebih dekat
    dari TP2 2R, TP2 dipangkas ke struktur; bila hasil pangkasan < 1:2 -> None.
    """
    sl = compute_sl(direction, swing_low, swing_high, atr, atr_mult)
    risk = abs(entry - sl)
    if risk <= 0 or atr <= 0:
        return None
    if direction == "LONG":
        if sl >= entry:
            return None
        tp1 = entry + 1.5 * risk
        tp2 = entry + 2.0 * risk
        if struct_resistance and struct_resistance > entry and struct_resistance < tp2:
            tp2 = struct_resistance
        if (tp2 - entry) / risk < 2.0 - 1e-9:
            return None
    else:
        if sl <= entry:
            return None
        tp1 = entry - 1.5 * risk
        tp2 = entry - 2.0 * risk
        if struct_support and struct_support < entry and struct_support > tp2:
            tp2 = struct_support
        if (entry - tp2) / risk < 2.0 - 1e-9:
            return None
    return Levels(entry=entry, sl=sl, tp1=tp1, tp2=tp2, risk=risk)


def position_qty(equity: float, risk_pct: float, risk_dist: float) -> float:
    if risk_dist <= 0:
        return 0.0
    return (equity * risk_pct) / risk_dist
