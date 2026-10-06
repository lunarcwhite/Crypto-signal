"""Modul 1: Market Data Ingestion — Binance WS kline + snapshot REST.

- Langganan combined stream: <sym>@kline_<interval> untuk 15m/1h/4h.
- Hanya candle closed (x.isBarClosed) yang diteruskan.
- Snapshot REST untuk warmup >=250 candle (PRD Modul 2) dan menutup gap reconnect.
- Reconnect: exponential backoff 1s,2s,4s,... maks 30s (PRD Modul 5).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

INTERVALS = ("15m", "1h", "4h")
BACKOFF_STEPS = (1, 2, 4, 8, 16, 30)


@dataclass
class Candle:
    symbol: str
    interval: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True


@dataclass
class CandleBuffer:
    maxlen: int = 500
    _data: dict[tuple[str, str], list[Candle]] = field(default_factory=lambda: defaultdict(list))

    def push(self, c: Candle) -> None:
        key = (c.symbol, c.interval)
        buf = self._data[key]
        if buf and buf[-1].open_time == c.open_time:
            buf[-1] = c
        else:
            buf.append(c)
        while len(buf) > self.maxlen:
            buf.pop(0)

    def closes(self, symbol: str, interval: str) -> list[float]:
        return [c.close for c in self._data[(symbol.upper(), interval)] if c.is_closed]

    def ready(self, symbol: str, interval: str, warmup: int = 250) -> bool:
        return len(self._data[(symbol.upper(), interval)]) >= warmup


def stream_name(symbol: str, interval: str) -> str:
    return f"{symbol.lower()}@kline_{interval}"


def combined_url(ws_base: str, symbols: list[str], intervals: tuple[str, ...] = INTERVALS) -> str:
    streams = "/".join(stream_name(s, i) for s in symbols for i in intervals)
    return f"{ws_base}/stream?streams={streams}"


def parse_kline_message(msg: dict) -> Candle | None:
    """Parse pesan Binance combined stream. Return None bila bukan kline closed."""
    try:
        k = msg["data"]["k"]
    except (KeyError, TypeError):
        return None
    if not k.get("x", False):
        return None  # abaikan candle yang belum close (anti-repaint)
    return Candle(
        symbol=str(k["s"]).upper(),
        interval=str(k["i"]),
        open_time=int(k["t"]),
        open=float(k["o"]),
        high=float(k["h"]),
        low=float(k["l"]),
        close=float(k["c"]),
        volume=float(k["v"]),
        is_closed=True,
    )


def fetch_klines_rest(rest_base: str, symbol: str, interval: str, limit: int = 500) -> list[Candle]:
    """Snapshot REST GET /api/v3/klines. Tanpa API key (public)."""
    qs = urllib.parse.urlencode({"symbol": symbol.upper(), "interval": interval, "limit": min(limit, 1000)})
    url = f"{rest_base.rstrip('/')}/api/v3/klines?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "trend-pullback-engine/1.1"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        rows = json.loads(resp.read().decode())
    out = []
    for r in rows:
        out.append(
            Candle(
                symbol=symbol.upper(),
                interval=interval,
                open_time=int(r[0]),
                open=float(r[1]),
                high=float(r[2]),
                low=float(r[3]),
                close=float(r[4]),
                volume=float(r[5]),
            )
        )
    return out


async def run_forever(
    ws_base: str,
    rest_base: str,
    symbols: list[str],
    on_candle,
    warmup: int = 250,
) -> None:
    """Loop koneksi persisten. `on_candle(candle)` dipanggil tiap closed candle."""
    try:
        import websockets
    except ImportError as e:
        raise RuntimeError("pip install -r requirements.txt (websockets)") from e

    # Warmup awal via REST agar EMA200/ADX langsung valid
    buf = CandleBuffer()
    for s in symbols:
        for iv in INTERVALS:
            try:
                for c in fetch_klines_rest(rest_base, s, iv, limit=max(warmup, 250)):
                    buf.push(c)
            except Exception:
                log.exception("warmup gagal %s %s", s, iv)
    log.info("warmup selesai")

    url = combined_url(ws_base, symbols)
    attempt = 0
    while True:
        try:
            log.info("connect %s", url)
            async with websockets.connect(url, ping_interval=30, ping_timeout=15) as ws:
                attempt = 0
                async for raw in ws:
                    candle = parse_kline_message(json.loads(raw))
                    if candle is None:
                        continue
                    buf.push(candle)
                    if asyncio.iscoroutinefunction(on_candle):
                        await on_candle(candle)
                    else:
                        on_candle(candle)
            log.warning("ws tertutup normal, reconnect 1s")
            await asyncio.sleep(1)
        except Exception:
            delay = BACKOFF_STEPS[min(attempt, len(BACKOFF_STEPS) - 1)]
            attempt += 1
            log.exception("ws putus, retry dalam %ss (attempt %d)", delay, attempt)
            # Tutup gap via REST sebelum reconnect
            try:
                for s in symbols:
                    for iv in INTERVALS:
                        for c in fetch_klines_rest(rest_base, s, iv, limit=5):
                            buf.push(c)
            except Exception:
                log.exception("gap-fill REST gagal")
            await asyncio.sleep(delay)
