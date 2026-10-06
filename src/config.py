"""Config loader — secrets dari .env, tidak di-hardcode (PRD §5)."""
import os


def _csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


SYMBOLS: list[str] = _csv("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT")
TIMEFRAMES: list[str] = ["15m", "1h", "4h"]
WARMUP_CANDLES: int = int(os.getenv("WARMUP_CANDLES", "250"))

BINANCE_WS_BASE: str = os.getenv("BINANCE_WS_BASE", "wss://data-stream.binance.vision")
BINANCE_REST_BASE: str = os.getenv("BINANCE_REST_BASE", "https://data-api.binance.vision")

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS: list[str] = [s.strip() for s in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if s.strip()]
DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
ECON_CAL_PROVIDER: str = os.getenv("ECON_CAL_PROVIDER", "manual_json")
FMP_API_KEY: str = os.getenv("FMP_API_KEY", "")
EQUITY_USDT: float = float(os.getenv("EQUITY_USDT", "1000"))
RISK_PCT: float = float(os.getenv("RISK_PCT", "1.0"))  # persen, mis. 1.0 = 1%
HEALTH_PORT: int = int(os.getenv("HEALTH_PORT", "8080"))  # 0 = nonaktif (tanpa guard)
