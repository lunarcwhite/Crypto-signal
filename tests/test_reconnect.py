"""Test reconnect Modul 1: mock WS lokal yang memutus koneksi tiap pesan.

Server mengirim 1 closed kline lalu menutup koneksi; klien harus reconnect
(backoff) dan tetap menerima candle berikutnya.
"""
import asyncio
import json
import unittest
from unittest.mock import patch


class TestReconnect(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_after_drop(self):
        import websockets

        from src import data_ingestion as di

        MSG = {"stream": "btcusdt@kline_15m",
               "data": {"k": {"s": "BTCUSDT", "i": "15m", "t": 1, "o": "1",
                               "h": "2", "l": "0.5", "c": "1.5", "v": "10", "x": True}}}

        async def handler(ws, *args):
            await ws.send(json.dumps(MSG))
            await ws.close()  # paksa putus -> klien harus reconnect

        server = await websockets.serve(handler, "127.0.0.1", 18765)
        received: list = []

        class _Done(BaseException):
            pass

        async def on_candle(c):
            received.append(c)
            if len(received) >= 2:
                raise _Done()

        async def runner():
            with patch.object(di, "fetch_klines_rest", return_value=[]):
                await di.run_forever("ws://127.0.0.1:18765", "http://127.0.0.1:9",
                                     ["BTCUSDT"], on_candle)

        task = asyncio.ensure_future(runner())
        try:
            await asyncio.wait_for(task, timeout=20)
        except _Done:
            pass
        except asyncio.TimeoutError:
            pass
        finally:
            task.cancel()
            server.close()
            await server.wait_closed()
        self.assertGreaterEqual(len(received), 2, "klien tidak reconnect setelah putus")


if __name__ == "__main__":
    unittest.main()
