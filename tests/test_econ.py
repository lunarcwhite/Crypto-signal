"""Unit test sumber kalender FMP (mock fetcher, tanpa jaringan)."""
import os
import tempfile
import unittest

from src.econ import is_high_impact_us, normalize, sync


class TestEcon(unittest.TestCase):
    def test_filter_us_high(self):
        self.assertTrue(is_high_impact_us(
            {"country": "US", "event": "CPI YoY", "date": "2026-10-08T12:30:00Z"}))
        self.assertTrue(is_high_impact_us(
            {"country": "US", "event": "FOMC Meeting Minutes", "impact": "low",
             "date": "2026-10-08T18:00:00Z"}))
        self.assertFalse(is_high_impact_us(
            {"country": "DE", "event": "CPI YoY", "date": "2026-10-08T12:30:00Z"}))
        self.assertFalse(is_high_impact_us(
            {"country": "US", "event": "Building Permits", "impact": "low",
             "date": "2026-10-08T12:30:00Z"}))

    def test_normalize(self):
        n = normalize({"event": "NFP", "date": "2026-10-08T12:30:00Z"})
        assert n is not None
        self.assertEqual(n["title"], "NFP")
        self.assertGreater(n["time_ms"], 0)
        self.assertIsNone(normalize({"event": "NFP"}))  # tanpa tanggal

    def test_sync_merge_manual(self):
        def fake_fetch(key, dfrom, dto):
            return [
                {"country": "US", "event": "CPI", "date": "2026-10-08T12:30:00Z"},
                {"country": "US", "event": "Housing Starts", "impact": "low",
                 "date": "2026-10-09T12:30:00Z"},
            ]

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            import json
            json.dump([{"time_ms": 1, "title": "Custom", "impact": "high", "manual": True}], f)
            path = f.name
        try:
            out = sync("DUMMY", path, 14, fetcher=fake_fetch)
            titles = [e["title"] for e in out]
            self.assertIn("CPI", titles)
            self.assertIn("Custom", titles)  # manual dipertahankan
            self.assertNotIn("Housing Starts", titles)  # low-impact terfilter
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
