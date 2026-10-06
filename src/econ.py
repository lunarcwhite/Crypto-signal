"""Sumber kalender makro otomatis via FMP (PRD Modul 4, ECON_CAL_PROVIDER=fmp).

  python -m src.econ --sync --days-ahead 14   # fetch -> filter -> econ_calendar.json
  python -m src.econ --sync --dry-run         # lihat hasil tanpa tulis file

Alur: fetch 1x/hari (cron/Task Scheduler) -> tulis file -> CircuitBreaker baca
file seperti biasa. Bila fetch gagal, file lama dipertahankan (log ERROR,
exit 1 agar scheduler bisa alerting). Entri manual ({"manual": true}) tidak
tertimpa.
"""
from __future__ import annotations

import argparse
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

DEFAULT_URL = "https://financialmodelingprep.com/stable/economic-calendar"
# PRD Modul 4: daftar high-impact AS
KEYWORDS = ("FOMC", "FED", "CPI", "PPI", "NFP", "NONFARM", "PAYROLL",
            "GDP", "UNEMPLOYMENT", "PCE", "RETAIL SALES", "ISM")


def _get(d: dict, *keys: str):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def _to_ms(v) -> int | None:
    try:
        if isinstance(v, (int, float)):
            return int(v) if v > 10_000_000_000 else int(v) * 1000
        s = str(v).strip()
        if s.isdigit():
            iv = int(s)
            return iv if iv > 10_000_000_000 else iv * 1000
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def fetch_fmp(api_key: str, date_from: str, date_to: str,
              base_url: str = DEFAULT_URL, timeout: int = 30) -> list[dict]:
    qs = urllib.parse.urlencode({"from": date_from, "to": date_to, "apikey": api_key})
    url = f"{base_url}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "trend-pullback-engine/1.3"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode() or "[]")
    return data if isinstance(data, list) else data.get("events", data.get("data", []))


def is_high_impact_us(ev: dict) -> bool:
    country = str(_get(ev, "country", "countryCode", "region", "currency") or "").upper()
    if country not in ("US", "USA", "USD", "UNITED STATES"):
        # FMP kadang memakai currency USD sebagai penanda negara
        if country not in ("", "USD"):
            return False
    title = str(_get(ev, "event", "title", "name", "indicator", "eventName") or "").upper()
    impact = str(_get(ev, "impact", "importance", "volatility") or "").lower()
    if impact in ("high", "3", "***"):
        return True
    return any(k in title for k in KEYWORDS)


def normalize(ev: dict) -> dict | None:
    t = _to_ms(_get(ev, "date", "datetime", "time", "timestamp"))
    title = _get(ev, "event", "title", "name", "indicator", "eventName")
    if not t or not title:
        return None
    return {"time_ms": t, "title": str(title), "impact": "high"}


def sync(api_key: str, path: str = "econ_calendar.json", days_ahead: int = 14,
         fetcher=fetch_fmp) -> list[dict]:
    today = datetime.now(timezone.utc).date()
    rows = fetcher(api_key, today.isoformat(), (today + timedelta(days=days_ahead)).isoformat())
    auto = [n for n in (normalize(e) for e in rows if is_high_impact_us(e)) if n]
    try:
        with open(path) as f:
            existing = json.load(f)
    except FileNotFoundError:
        existing = []
    manual = [e for e in existing if isinstance(e, dict) and e.get("manual")]
    merged = {e["time_ms"]: e for e in manual}
    merged.update({e["time_ms"]: e for e in auto})  # auto menimpa judul sama waktu
    out = sorted(merged.values(), key=lambda e: e["time_ms"])
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    log.info("kalender tersinkron: %d auto + %d manual", len(auto), len(manual))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync", action="store_true")
    ap.add_argument("--days-ahead", type=int, default=14)
    ap.add_argument("--path", default="econ_calendar.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--key", default="")
    a = ap.parse_args()
    import os

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    key = a.key or os.getenv("FMP_API_KEY", "")
    if not key:
        raise SystemExit("FMP_API_KEY kosong (isi .env atau --key). Daftar gratis di financialmodelingprep.com.")
    if a.dry_run:
        today = datetime.now(timezone.utc).date()
        rows = fetch_fmp(key, today.isoformat(),
                         (today + timedelta(days=a.days_ahead)).isoformat())
        auto = [n for n in (normalize(e) for e in rows if is_high_impact_us(e)) if n]
        print(json.dumps(auto[:20], indent=2))
        print(f"... total {len(auto)} event high-impact")
        return
    if a.sync:
        try:
            sync(key, a.path, a.days_ahead)
        except Exception:
            log.exception("sinkronisasi kalender GAGAL, file lama dipertahankan")
            raise SystemExit(1)


if __name__ == "__main__":
    main()
