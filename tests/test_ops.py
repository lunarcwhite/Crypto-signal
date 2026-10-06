"""Unit test C: restore breaker + health endpoint."""
import time
import unittest
import urllib.request
import json

from src.circuit_breaker import CircuitBreaker
from src.store import close_signal, connect, save_signal, set_lock


class TestRestore(unittest.TestCase):
    def test_restore_lock_dari_db(self):
        conn = connect(":memory:")
        now = 1_700_000_000_000
        for _ in range(2):
            sid = save_signal(conn, {"symbol": "BTCUSDT", "direction": "LONG",
                                     "entry": 100, "sl": 90, "tp1": 115, "tp2": 120})
            conn.execute("UPDATE signals SET closed_at=? WHERE id=?", (now, sid))
            close_signal(conn, sid, "SL_HIT", 90)
            conn.execute("UPDATE signals SET closed_at=? WHERE id=?", (now, sid))
            conn.commit()
        brk = CircuitBreaker.__new__(CircuitBreaker)
        brk.events, brk.lock_ms, brk.window_ms = [], 12 * 3600 * 1000, 24 * 3600 * 1000
        brk._locks, brk._closes = {}, {}
        # close_signal menimpa closed_at dgn waktu now() asli; geser ke window uji
        conn.execute("UPDATE signals SET closed_at=?", (now,))
        conn.commit()
        summary = brk.restore(conn, now + 1000)
        self.assertEqual(summary["restored_closes"], 2)
        self.assertTrue(brk.symbol_locked("BTCUSDT", now + 1000))
        ok, reason = brk.allow("BTCUSDT", now + 1000)
        self.assertFalse(ok)
        self.assertIn("SYMBOL_LOCKED", reason)

    def test_restore_lock_tabel(self):
        conn = connect(":memory:")
        now_ms = int(time.time() * 1000)
        set_lock(conn, "ETHUSDT", now_ms + 3600_000, "2xSL/24h")
        brk = CircuitBreaker.__new__(CircuitBreaker)
        brk.events, brk.lock_ms, brk.window_ms = [], 12 * 3600 * 1000, 24 * 3600 * 1000
        brk._locks, brk._closes = {}, {}
        brk.restore(conn, now_ms)
        self.assertTrue(brk.symbol_locked("ETHUSDT", now_ms + 1000))


class TestHealth(unittest.TestCase):
    def test_health_json(self):
        from src.health import start_health_server

        srv = start_health_server(0, lambda: {"open_trades": 3})
        port = srv.server_address[1]
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
                body = json.loads(r.read().decode())
            self.assertEqual(body["status"], "ok")
            self.assertEqual(body["open_trades"], 3)
        finally:
            srv.shutdown()

    def test_port_guard(self):
        from src.health import start_health_server

        srv = start_health_server(0, lambda: {})
        port = srv.server_address[1]
        try:
            with self.assertRaises(OSError):
                start_health_server(port, lambda: {})
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
