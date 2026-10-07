"""Unit test D: perintah Telegram user-friendly (tanpa network)."""
import unittest

from src.bot_commands import (format_calendar, format_locks, format_perf,
                              format_signals, format_status, help_text,
                              main_menu_keyboard, normalize_symbol,
                              parse_user_input, start_text, unknown_text)


class TestParse(unittest.TestCase):
    def test_slash_opsional_dan_case_insensitive(self):
        for raw in ("/status", "status", "Status", "STATUS", "/STATUS"):
            self.assertEqual(parse_user_input(raw)["command"], "status", raw)

    def test_alias_id_en(self):
        self.assertEqual(parse_user_input("signal")["command"], "sinyal")
        self.assertEqual(parse_user_input("/perf")["command"], "perf")
        self.assertEqual(parse_user_input("audit")["command"], "perf")
        self.assertEqual(parse_user_input("bantuan")["command"], "help")
        self.assertEqual(parse_user_input("mulai")["command"], "start")

    def test_typo_dikoreksi(self):
        r = parse_user_input("stauts")
        self.assertEqual(r["command"], "status")
        self.assertTrue(r["corrected"])
        r = parse_user_input("/hepl")
        self.assertEqual(r["command"], "help")

    def test_at_bot_suffix(self):
        self.assertEqual(parse_user_input("/status@BotSaya")["command"], "status")

    def test_symbol_shorthand(self):
        r = parse_user_input("btc")
        self.assertEqual((r["command"], r["symbol"]), ("sinyal", "BTCUSDT"))
        r = parse_user_input("/sinyal eth 5")
        self.assertEqual((r["symbol"], r["limit"]), ("ETHUSDT", 5))

    def test_normalize_symbol_variants(self):
        for raw, exp in (("btc", "BTCUSDT"), ("BTC/USDT", "BTCUSDT"),
                         ("#eth", "ETHUSDT"), ("solusdt", "SOLUSDT")):
            self.assertEqual(normalize_symbol(raw), exp, raw)
        self.assertIsNone(normalize_symbol("???"))

    def test_perf_days_default_dan_variasi(self):
        self.assertEqual(parse_user_input("/perf")["days"], 7)
        self.assertEqual(parse_user_input("perf 30")["days"], 30)
        self.assertEqual(parse_user_input("perf 7d")["days"], 7)
        self.assertEqual(parse_user_input("/perf btc 30")["symbol"], "BTCUSDT")

    def test_sinyal_limit_default(self):
        self.assertEqual(parse_user_input("/sinyal")["limit"], 3)
        self.assertEqual(parse_user_input("sinyal btc 5")["limit"], 5)

    def test_unknown_kasih_saran(self):
        r = parse_user_input("stxyz")
        self.assertEqual(r["command"], "unknown")
        t = unknown_text(r, "stxyz")
        self.assertIn("/help", t)

    def test_greeting_tidak_error(self):
        self.assertEqual(parse_user_input("makasih")["command"], "greeting")
        self.assertEqual(parse_user_input("")["command"], "help")


class TestFormat(unittest.TestCase):
    def test_keyboard_ada_6_tombol(self):
        kb = main_menu_keyboard()
        n = sum(len(row) for row in kb["inline_keyboard"])
        self.assertEqual(n, 6)

    def test_start_help_singkat_jelas(self):
        self.assertIn("TAP", start_text())
        self.assertIn("/sinyal", help_text())

    def test_status_kosong_tetap_ramah(self):
        t = format_status({"uptime_s": 5, "dry_run": True, "symbols": ["BTCUSDT"],
                           "open_trades": 0, "last_candle_age_s": {}})
        self.assertIn("warming up", t)

    def test_signals_kosong_tetap_ramah(self):
        self.assertIn("Belum ada sinyal", format_signals([]))

    def test_perf_kosong_tetap_ramah(self):
        self.assertIn("Belum ada trade", format_perf({"closed": 0}, 7))

    def test_locks_dan_calendar_kosong(self):
        self.assertIn("Tidak ada", format_locks([], None, []))
        self.assertIn("Tidak ada event", format_calendar([]))


if __name__ == "__main__":
    unittest.main()
