# Runbook Fase 4 — Paper Trading 14–30 hari

Target: ukur WR_TP1, expectancy net, slippage riil sebelum modal riil (PRD §6 Fase 4).
KPI lolos: `closed >= 30` dan `expectancy_R > +0.2` via `python -m src.audit`.

## 0. Prasyarat (sekali)

```powershell
Copy-Item .env.example .env   # lalu isi TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_IDS
pip install -r requirements.txt
python -m unittest discover -s tests   # harus OK (30 test)
```

## 1. Kalender makro (`econ_calendar.json`)

Format entri (UTC, hanya high-impact yang di-freeze ±60 mnt):

```json
[
  {"time": "2026-10-08T18:00:00Z", "title": "FOMC", "impact": "high"},
  {"time_ms": 1761234567890, "title": "CPI", "impact": "high"}
]
```

Kosong `[]` = tanpa freeze. Opsi ketat: set `ECON_FREEZE_ON_ERROR=1` agar file rusak membuat freeze (fail-closed).

## 2. Smoke dry-run (tanpa kirim Telegram, 2–5 menit)

```powershell
$env:PYTHONPATH='.'
python -m src.runner --dry-run --db paper.db   # Ctrl+C setelah 5 mnt
python -m src.audit --db paper.db              # closed=0 wajar (belum ada close)
sqlite3 paper.db "SELECT COUNT(*) FROM signals;"  # Windows: gunakan DB Browser bila tanpa sqlite3 CLI
```

Lolos bila: WS connect tanpa error, sinyal (bila ada) tercatat di `paper.db`, tidak ada traceback.

## 3. Live paper 14–30 hari

```powershell
python -m src.runner --live --db signals.db --log-file bot.log --health-port 8080
```

Alternatif deploy 24/7:
```powershell
# Docker (auto-restart, secret via env-file):
docker build -t crypto-bot .
docker run -d --restart unless-stopped --env-file .env -v ${PWD}:/data crypto-bot
# Windows Task Scheduler (saat logon, restart bila gagal): jalankan
python -m src.preflight   # pastikan 9/9 PASS dulu
schtasks /create /tn CryptoBot /tr "pythonw D:\aplikasi\bot\crypto\src\runner.py --live" /sc onlogon
# Linux systemd: ExecStart=/usr/bin/python3 -m src.runner --live, Restart=always
```

- Berjalan 24/7 (VPS/TMUX/Task Scheduler). Telegram terkirim ke whitelist saja.
- Jangan jalankan dua instance dengan DB sama (deduplikasi jebol).
- Pantau log: `SIGNAL`, `TP1 ... -> BEP`, `close #id ...`, `SYMBOL_LOCKED`.

## 4. Audit berkala (harian/mingguan)

```powershell
python -m src.audit --db signals.db
python -m src.audit --db signals.db --since-days 7
```

Keputusan:
- `expectancy_R > +0.2` dan `closed >= 30` → pertimbangkan modal kecil riil (risiko 0.5%).
- `expectancy_R 0..0.2` → lanjut tuning (lihat §5).
- `expectancy_R < 0` 7 hari berturut-turut → hentikan, kembali ke Fase 2b.

## 5. Evaluasi slippage & parameter

- Bandingkan `entry` tercatat vs harga eksekusi manual di bursa pada menit yang sama.
  Selisih konsisten > 0.15% → naikkan `SLIPPAGE_PCT` di `src/backtest.py` + `src/runner.py` (0.001 → 0.0015) lalu re-backtest.
- Tuning hanya via `python -m src.tune --symbols BTCUSDT,ETHUSDT,SOLUSDT --months 3 --validate`
  lalu terapkan default baru + catat di PRD (seperti ADX 20→30 pada Fase 2b).

## 6. Stop darurat

- Ctrl+C runner (posisi paper otomatis berhenti di-track; status OPEN tetap di DB).
- Hapus lock manual bila perlu: `DELETE FROM locks WHERE symbol='BTCUSDT';`
- Blacklist event dadakan: tambah ke `econ_calendar.json` lalu restart runner.
