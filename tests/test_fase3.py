"""Unit test Fase 3: dispatcher format, circuit breaker, store."""
import os
import tempfile
import unittest

from src.circuit_breaker import CircuitBreaker
from src.dispatcher import Dispatcher, format_signal_message
from src.store import close_signal, connect, get_lock, recent_outcomes, save_signal, set_lock


class TestFormat(unittest.TestCase):
    def test_template_prd(self):
        msg = format_signal_message(
            {"symbol": "BTCUSDT", "direction": "LONG"},
            {"entry": 64250.0, "sl": 63100.0, "tp1": 65975.0, "tp2": 67200.0},
            {"adx_4h": 31.5, "regime": "BULLISH", "atr": 450.0, "qty": 0.0087},
        )
        self.assertIn("#BTCUSDT", msg)
        self.assertIn("64,250", msg)
        self.assertIn("63,100", msg)
        self.assertIn("65,975", msg)
        self.assertIn("67,200", msg)
        self.assertIn("1 : 1.50", msg)  # RRR TP1
        self.assertIn("1 : 2.57", msg)  # RRR TP2 = 2950/1150
        self.assertIn("31.5", msg)

    def test_dispatcher_dry_run(self):
        d = Dispatcher()  # tanpa token -> DRY_RUN ok
        r = d.send("halo")
        self.assertEqual(r["telegram"][0]["chat_id"], "DRY_RUN")

    def test_dispatcher_retry_ok(self):
        calls = []
        d = Dispatcher(bot_token="T", chat_ids=["1"], http_post=lambda u, p: calls.append((u, p)) or {})
        r = d.send("x")
        self.assertTrue(r["telegram"][0]["ok"])
        self.assertEqual(len(calls), 1)


class TestBreaker(unittest.TestCase):
    def test_loss_lock_2xsl(self):
        brk = CircuitBreaker.__new__(CircuitBreaker)
        brk.events, brk.lock_ms, brk.window_ms = [], 12 * 3600 * 1000, 24 * 3600 * 1000
        brk._locks, brk._closes = {}, {}
        t0 = 1_700_000_000_000
        brk.note_close("BTCUSDT", t0, "SL_HIT")
        self.assertFalse(brk.symbol_locked("BTCUSDT", t0 + 1000))
        brk.note_close("BTCUSDT", t0 + 3600_000, "SL_HIT")
        self.assertTrue(brk.symbol_locked("BTCUSDT", t0 + 7200_000))
        ok, reason = brk.allow("BTCUSDT", t0 + 7200_000)
        self.assertFalse(ok)
        self.assertIn("SYMBOL_LOCKED", reason)
        # TP di antara mereset rangkaian
        brk2 = CircuitBreaker.__new__(CircuitBreaker)
        brk2.events, brk2.lock_ms, brk2.window_ms = [], 12 * 3600 * 1000, 24 * 3600 * 1000
        brk2._locks, brk2._closes = {}, {}
        brk2.note_close("ETHUSDT", t0, "SL_HIT")
        brk2.note_close("ETHUSDT", t0 + 1000, "TP2_HIT")
        brk2.note_close("ETHUSDT", t0 + 2000, "SL_HIT")
        self.assertFalse(brk2.symbol_locked("ETHUSDT", t0 + 3000))

    def test_macro_freeze(self):
        import json
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump([{"time_ms": 1_700_000_000_000, "title": "CPI", "impact": "high"}], f)
            path = f.name
        try:
            brk = CircuitBreaker(calendar_path=path)
            self.assertIsNotNone(brk.macro_frozen(1_700_000_000_000 + 30 * 60 * 1000))
            self.assertIsNone(brk.macro_frozen(1_700_000_000_000 + 61 * 60 * 1000))
            ok, reason = brk.allow("BTCUSDT", 1_700_000_000_000)
            self.assertFalse(ok)
            self.assertIn("MACRO_FREEZE", reason)
        finally:
            os.unlink(path)


class TestStore(unittest.TestCase):
    def test_save_close_query(self):
        conn = connect(":memory:")
        sid = save_signal(conn, {"symbol": "BTCUSDT", "direction": "LONG", "entry": 100,
                                 "sl": 90, "tp1": 115, "tp2": 120, "qty": 1, "risk": 10})
        close_signal(conn, sid, "SL_HIT", 90)
        self.assertEqual(recent_outcomes(conn, "BTCUSDT"), ["SL_HIT"])
        set_lock(conn, "BTCUSDT", 9_999_999_999_999, "test")
        self.assertEqual(get_lock(conn, "BTCUSDT", 1_000), "test")
        self.assertIsNone(get_lock(conn, "BTCUSDT", 99_999_999_999_999))


if __name__ == "__main__":
    unittest.main()
