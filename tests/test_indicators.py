"""Unit test Fase 1: EMA/RSI/ATR/ADX + parsing kline (unittest stdlib)."""
import unittest

from src.data_ingestion import CandleBuffer, parse_kline_message
from src.indicators import adx_series, atr_series, ema_series, rsi_series, sma_series


class TestEMA(unittest.TestCase):
    def test_seed_sma_dan_rekursi(self):
        closes = [10, 11, 12, 13, 14, 15]
        out = ema_series(closes, 3)  # seed=(10+11+12)/3=11, k=0.5
        self.assertIsNone(out[0])
        self.assertIsNone(out[1])
        self.assertAlmostEqual(out[2], 11.0)
        self.assertAlmostEqual(out[3], 12.0)  # 13*0.5+11*0.5
        self.assertAlmostEqual(out[4], 13.0)
        self.assertAlmostEqual(out[5], 14.0)

    def test_data_kurang_period(self):
        self.assertEqual(ema_series([1, 2], 5), [None, None])


class TestRSI(unittest.TestCase):
    def test_all_gain_mendekati_100(self):
        closes = list(range(1, 30))  # naik monoton
        out = rsi_series(closes, 14)
        self.assertIsNone(out[13])
        assert out[-1] is not None
        self.assertGreater(out[-1], 99.0)

    def test_all_loss_mendekati_0(self):
        closes = list(range(30, 0, -1))
        out = rsi_series(closes, 14)
        assert out[-1] is not None
        self.assertLess(out[-1], 1.0)

    def test_flat_50_atau_100(self):
        closes = [100.0] * 30
        out = rsi_series(closes, 14)
        assert out[-1] is not None
        self.assertAlmostEqual(out[-1], 100.0)  # avg_loss==0 -> 100 (definisi)


class TestATRADX(unittest.TestCase):
    def _trend(self, n=80, step=1.0):
        closes, highs, lows = [], [], []
        p = 100.0
        for _ in range(n):
            p += step
            closes.append(p)
            highs.append(p + 0.5)
            lows.append(p - 0.5)
        return highs, lows, closes

    def test_atr_positif_dan_none_awal(self):
        h, l, c = self._trend()
        atr = atr_series(h, l, c, 14)
        self.assertIsNone(atr[13])
        assert atr[-1] is not None
        self.assertGreater(atr[-1], 0)

    def test_adx_trend_kuat(self):
        h, l, c = self._trend(120, 1.0)
        adx, pdi, mdi = adx_series(h, l, c, 14)
        self.assertIsNone(adx[2 * 14 - 2])
        assert adx[-1] is not None and pdi[-1] is not None and mdi[-1] is not None
        self.assertGreater(adx[-1], 20.0)  # tren monoton harus trending
        self.assertGreater(pdi[-1], mdi[-1])

    def test_adx_butuh_data_cukup(self):
        h, l, c = self._trend(20, 1.0)
        adx, _, _ = adx_series(h, l, c, 14)
        self.assertTrue(all(v is None for v in adx))


class TestIngestion(unittest.TestCase):
    def test_parse_hanya_closed(self):
        open_msg = {"data": {"k": {"s": "BTCUSDT", "i": "15m", "t": 1, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "x": False}}}
        self.assertIsNone(parse_kline_message(open_msg))
        closed = {"data": {"k": {"s": "btcusdt", "i": "15m", "t": 1, "o": "1", "h": "2", "l": "0.5", "c": "1.5", "v": "10", "x": True}}}
        c = parse_kline_message(closed)
        assert c is not None
        self.assertEqual(c.symbol, "BTCUSDT")
        self.assertTrue(c.is_closed)

    def test_buffer_dedup_update(self):
        from src.data_ingestion import Candle

        buf = CandleBuffer(maxlen=3)
        for t in (1, 1, 2, 3, 4):
            buf.push(Candle("BTCUSDT", "15m", t, 1, 2, 0.5, 1.5, 10))
        self.assertEqual([c.open_time for c in buf._data[("BTCUSDT", "15m")]], [2, 3, 4])

    def test_sma_volume(self):
        vols = [10.0] * 19 + [30.0]
        s = sma_series(vols, 20)
        assert s[-1] is not None
        self.assertGreaterEqual(30.0, 1.3 * s[-1])  # 30 >= 1.3*avg -> sinyal volume valid
        self.assertLess(13.0, 1.3 * s[-1] if s[-1] else float("inf"))


if __name__ == "__main__":
    unittest.main()
