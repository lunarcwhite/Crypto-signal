"""Smoke manual Modul 1: print setiap closed candle. Jalankan: python -m src.data_ingestion"""
import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from src import config as cfg
from src.data_ingestion import run_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    async def on_candle(c):
        print(f"{c.symbol} {c.interval} close={c.close} vol={c.volume}", flush=True)

    asyncio.run(run_forever(cfg.BINANCE_WS_BASE, cfg.BINANCE_REST_BASE, cfg.SYMBOLS, on_candle, cfg.WARMUP_CANDLES))


if __name__ == "__main__":
    main()
