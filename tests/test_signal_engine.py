"""Unit test Fase 2: SignalEngine + risk_engine."""
import unittest

from src.risk_engine import compute_levels, position_qty
from src.signal_engine import SignalEngine, pullback_long, pullback_short


class TestPullback(unittest.TestCase):
    def test_long_touch_ema(self):
        self.assertTrue(pullback_long(100.0, 100.1, 100.0, 99.0, 1.0))
        self.assertFalse(pullback_long(105.0, 105.0, 100.0, 99.0, 1.0))  # jauh

    def test_long_breakdown_guard(self):
        # sentuh EMA55 tapi close jebol >1 ATR di bawah keduanya -> bukan pullback
        self.assertFalse(pullback_long(99.0, 97.0, 100.0, 99.2, 1.0))

    def test_short_mirror(self):
        self.assertTrue(pullback_short(100.0, 99.9, 100.0, 101.0, 1.0))
        self.assertFalse(pullback_short(95.0, 95.0, 100.0, 101.0, 1.0))


class TestRegime(unittest.TestCase):
    def test_hysteresis(self):
        eng = SignalEngine()  # default freeze 30 / unfreeze 32 (PRD v1.3)
        self.assertEqual(eng.update_regime_4h("BTCUSDT", 100, 90, 35), "BULLISH")
        self.assertEqual(eng.update_regime_4h("BTCUSDT", 100, 90, 29), "CHOPPY")
        # tetap beku di 31 (butuh >=32 untuk buka)
        self.assertEqual(eng.update_regime_4h("BTCUSDT", 100, 90, 31), "CHOPPY")
        self.assertEqual(eng.update_regime_4h("BTCUSDT", 100, 90, 32.5), "BULLISH")
        self.assertEqual(eng.update_regime_4h("BTCUSDT", 80, 90, 35), "BEARISH")

    def test_hysteresis_custom(self):
        eng = SignalEngine(adx_freeze=20.0, adx_unfreeze=22.0)
        self.assertEqual(eng.update_regime_4h("BTCUSDT", 100, 90, 25), "BULLISH")
        self.assertEqual(eng.update_regime_4h("BTCUSDT", 100, 90, 19), "CHOPPY")

    def test_warming_up(self):
        eng = SignalEngine()
        self.assertEqual(eng.update_regime_4h("ETHUSDT", 100, None, 25), "WARMING_UP")


class TestEvaluate(unittest.TestCase):
    def _engine_long_setup(self):
        eng = SignalEngine()
        eng.update_regime_4h("BTCUSDT", 100, 90, 25)
        return eng

    def test_long_signal_ok(self):
        eng = self._engine_long_setup()
        sig = eng.evaluate_15m(
            "BTCUSDT", 100, 1, "BULLISH",
            {"low": 100.0, "high": 101.0, "close": 100.1},
            30.0, 42.0, 50.0, 100.0, 99.0, 1.0, 1.5,
        )
        assert sig is not None
        self.assertEqual(sig.direction, "LONG")

    def test_long_signal_path_b(self):
        eng = self._engine_long_setup()
        sig = eng.evaluate_15m(
            "BTCUSDT", 100, 1, "BULLISH",
            {"low": 100.0, "high": 101.0, "close": 100.1},
            50.0, 55.0, 55.0, 100.0, 99.0, 1.0, 1.2,  # hold, tanpa cross
        )
        assert sig is not None
        self.assertEqual(sig.direction, "LONG")

    def test_dedup_block(self):
        eng = self._engine_long_setup()
        kw = dict(symbol="BTCUSDT", regime_4h="BULLISH",
                  ohlc_15m={"low": 100.0, "high": 101.0, "close": 100.1},
                  rsi_prev_15m=30.0, rsi_curr_15m=42.0, rsi_1h=50.0,
                  ema21_15m=100.0, ema55_15m=99.0, atr_15m=1.0, vol_ratio=1.5)
        s1 = eng.evaluate_15m(open_time=1, idx=100, **kw)  # type: ignore[arg-type]
        s2 = eng.evaluate_15m(open_time=2, idx=102, **kw)  # type: ignore[arg-type]
        assert s1 is not None
        self.assertIsNone(s2)  # <6 candle -> blokir
        s3 = eng.evaluate_15m(open_time=3, idx=106, **kw)  # type: ignore[arg-type]
        assert s3 is not None

    def test_rsi_filter_gagal(self):
        eng = self._engine_long_setup()
        sig = eng.evaluate_15m(
            "BTCUSDT", 100, 1, "BULLISH",
            {"low": 100.0, "high": 101.0, "close": 100.1},
            40.0, 42.0, 38.0, 100.0, 99.0, 1.0, 1.5,  # cross gagal (prev tidak <40), hold gagal (curr<45, 1H<40)
        )
        self.assertIsNone(sig)

    def test_choppy_no_signal(self):
        eng = SignalEngine()
        sig = eng.evaluate_15m(
            "BTCUSDT", 100, 1, "CHOPPY",
            {"low": 100.0, "high": 101.0, "close": 100.1},
            30.0, 40.0, 50.0, 100.0, 99.0, 1.0, 1.5,
        )
        self.assertIsNone(sig)


class TestRisk(unittest.TestCase):
    def test_levels_long(self):
        lv = compute_levels("LONG", 100.0, 98.0, 0.0, 1.0)  # sl=96.5, risk=3.5
        assert lv is not None
        self.assertAlmostEqual(lv.sl, 96.5)
        self.assertAlmostEqual(lv.tp1, 105.25)
        self.assertAlmostEqual(lv.tp2, 107.0)

    def test_struct_cap_ok(self):
        # resistance 106.5 < tp2 107 tapi masih >=2R (6.5/3.5=1.857 <2!) -> None
        self.assertIsNone(compute_levels("LONG", 100.0, 98.0, 0.0, 1.0,
                                          struct_resistance=106.5))
        # resistance jauh di atas tp2 -> tidak berpengaruh
        lv = compute_levels("LONG", 100.0, 98.0, 0.0, 1.0, struct_resistance=110.0)
        assert lv is not None
        self.assertAlmostEqual(lv.tp2, 107.0)

    def test_struct_short_cancel(self):
        # risk=3.5, tp2=-2R=93.0; support 94.0 -> RRR=(100-94)/3.5=1.71 <2 -> None
        self.assertIsNone(compute_levels("SHORT", 100.0, 0.0, 102.0, 1.0,
                                          struct_support=94.0))
        lv = compute_levels("SHORT", 100.0, 0.0, 102.0, 1.0, struct_support=90.0)
        assert lv is not None
        self.assertAlmostEqual(lv.tp2, 93.0)

    def test_qty(self):
        self.assertAlmostEqual(position_qty(1000.0, 0.01, 1150.0), 10.0 / 1150.0)


if __name__ == "__main__":
    unittest.main()
