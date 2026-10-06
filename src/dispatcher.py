"""Modul 5: Dispatcher — Telegram utama, Discord opsional (PRD §Modul 5).

- Retry 3x dengan backoff 1s/2s/4s; patuhi rate-limit (min interval 50ms).
- Template pesan mengikuti PRD §4 (RRR TP1 + TP2 dipisah).
- http_post di-inject agar bisa di-test tanpa jaringan.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)


def format_signal_message(sig: dict, lv: dict, meta: dict) -> str:
    arrow = "LONG 🟢" if sig["direction"] == "LONG" else "SHORT 🔴"
    r1 = abs(lv["tp1"] - lv["entry"]) / abs(lv["entry"] - lv["sl"]) if lv["entry"] != lv["sl"] else 0
    r2 = abs(lv["tp2"] - lv["entry"]) / abs(lv["entry"] - lv["sl"]) if lv["entry"] != lv["sl"] else 0
    pct = lambda px: (px / lv["entry"] - 1) * 100 * (1 if sig["direction"] == "LONG" else -1)
    return (
        f"🚨 SIGNAL DETECTED: #{sig['symbol']} ({arrow})\n"
        f"Timeframe: 15M entry / 1H konfirmasi / 4H bias\n"
        f"\n📥 Entry Area: {lv['entry']:,.0f} USDT\n"
        f"⛔ Toleransi Entry Maks: {lv['entry'] * 1.001:,.0f} USDT (slippage 0.1%)\n"
        f"\n🛑 Stop Loss: {lv['sl']:,.0f} USDT ({pct(lv['sl']):+.2f}%)\n"
        f"🎯 Take Profit 1: {lv['tp1']:,.0f} USDT ({pct(lv['tp1']):+.2f}% | Tutup 50% & Set BEP)\n"
        f"🎯 Take Profit 2: {lv['tp2']:,.0f} USDT ({pct(lv['tp2']):+.2f}% | Target Akhir)\n"
        f"\n📊 Metrik Risiko:\n"
        f"• Risk/Reward TP1: 1 : {r1:.2f}\n"
        f"• Risk/Reward TP2: 1 : {r2:.2f}\n"
        f"• Macro ADX (4H): {meta.get('adx_4h', 0):.1f} ({meta.get('regime', '?')})\n"
        f"• Volatilitas ATR (14): {meta.get('atr', 0):,.0f} USDT\n"
        f"• Qty saran (1% risiko): {meta.get('qty', 0):.4f} {sig['symbol'].replace('USDT', '')}\n"
        f"\n💡 Saran Manajemen: Alokasikan risiko maksimal 1-2% modal akun."
    )


def _post_json(url: str, payload: dict, timeout: int = 15) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "trend-pullback-engine/1.3"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode() or "{}")


class Dispatcher:
    def __init__(self, bot_token: str = "", chat_ids: list[str] | None = None,
                 discord_url: str = "", http_post=_post_json, min_interval_s: float = 0.05) -> None:
        self.bot_token = bot_token
        self.chat_ids = chat_ids or []
        self.discord_url = discord_url
        self._post = http_post
        self._min_interval = min_interval_s
        self._last_sent = 0.0

    def _throttle(self) -> None:
        dt = time.time() - self._last_sent
        if dt < self._min_interval:
            time.sleep(self._min_interval - dt)

    def _send_with_retry(self, url: str, payload: dict) -> bool:
        for attempt, delay in ((0, 0), (1, 1), (2, 2), (3, 4)):
            if attempt:
                time.sleep(delay)
            try:
                self._throttle()
                self._post(url, payload)
                self._last_sent = time.time()
                return True
            except Exception:
                log.exception("kirim gagal (attempt %d)", attempt)
        return False

    def send(self, text: str) -> dict:
        """Kirim ke Telegram (per chat) + Discord best-effort. Return ringkasan."""
        res: dict = {"telegram": [], "discord": None, "text": text}
        if self.bot_token and self.chat_ids:
            for cid in self.chat_ids:
                url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                ok = self._send_with_retry(url, {"chat_id": cid, "text": text, "parse_mode": "HTML"})
                res["telegram"].append({"chat_id": cid, "ok": ok})
        else:
            res["telegram"] = [{"chat_id": "DRY_RUN", "ok": True}]
            log.info("DRY_RUN telegram:\n%s", text)
        if self.discord_url:
            try:
                ok = self._send_with_retry(self.discord_url, {"content": text[:1900]})
                res["discord"] = ok
            except Exception:
                res["discord"] = False
        return res


def main() -> None:
    """CLI: python -m src.dispatcher --test [teks] — kirim pesan uji via .env."""
    import argparse

    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("text", nargs="?", default="✅ Tes dispatcher OK.")
    a = ap.parse_args()
    if not a.test:
        ap.print_help()
        return
    from src import config as cfg

    d = Dispatcher(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_IDS, cfg.DISCORD_WEBHOOK_URL)
    import json

    print(json.dumps(d.send(a.text), indent=2, default=str))


if __name__ == "__main__":
    main()
