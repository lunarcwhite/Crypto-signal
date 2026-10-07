# Crypto Trend-Pullback Signal Engine

Bot sinyal crypto multi-timeframe (4H bias → 1H konfirmasi → 15M entry), SL ATR,
TP bertahap, circuit breaker makro/loss-lock, notifikasi Telegram. **Tanpa
eksekusi order otomatis.** Detail spesifikasi: `PRD.md`.

## Instalasi

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env   # lalu isi (lihat tabel di bawah)
```

| Variabel `.env` | Wajib | Contoh |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_IDS` | ya (live) | `123:ABC`, `111,222` |
| `SYMBOLS` | tidak | `BTCUSDT,ETHUSDT,SOLUSDT` |
| `EQUITY_USDT` / `RISK_PCT` | tidak | `1000` / `1.0` |
| `ECON_CAL_PROVIDER` / `FMP_API_KEY` | tidak | `manual_json` / key FMP |
| `HEALTH_PORT` | tidak | `8080` (`0` = mati) |

## Perintah

```powershell
python -m unittest discover -s tests          # 40 test harus OK
python -m src.preflight                        # cek deploy (9 cek)
python -m src.preflight --send-test            # + kirim pesan Telegram asli
python -m src.runner --dry-run --db paper.db   # smoke tanpa kirim
python -m src.runner --live --db signals.db --log-file bot.log
python -m src.audit --db signals.db --since-days 7
python -m src.backtest --symbols BTCUSDT --months 3
python -m src.tune --symbols BTCUSDT --months 3 --validate
python -m src.econ --sync --days-ahead 14      # perlu FMP_API_KEY
python -m src.dispatcher --test "halo"         # tes kirim Telegram
```

Health: `http://127.0.0.1:8080/health` (port terpakai = ada instance lain → runner exit 2).

## Perintah Telegram (saat runner --live jalan)

Tidak perlu hafal sintaks: tanpa `/` boleh, huruf besar/kecil bebas,
typo kecil dikoreksi otomatis, dan setiap balasan ada tombol tap.

| Ketikan (bebas) | Artinya |
|---|---|
| `/start`, `halo` | Sapaan + panduan |
| `/help`, `bantuan` | Daftar lengkap + contoh |
| `/status`, `status` | Status bot & posisi open |
| `/sinyal`, `sinyal btc`, `btc` | Sinyal terakhir (opsional simbol + jumlah, cth: `/sinyal eth 5`) |
| `/perf`, `perf 30`, `/perf btc 7` | Win-rate & expectancy paper N hari |
| `/locks`, `kunci` | Simbol terkunci + freeze makro |
| `/kalender` | 5 event ekonomi terdekat |

```powershell
python -m src.telegram_bot --setup-commands  # daftarkan menu "/" autocomplete ke Telegram (sekali)
python -m src.telegram_bot --poll --db signals.db  # uji perintah standalone tanpa signal loop
```

Hanya `TELEGRAM_CHAT_IDS` (whitelist) yang dilayani; chat lain mendapat
penolakan sopan. Bila whitelist kosong, semua diizinkan sementara agar
owner bisa membaca chat ID-nya dari pesan masuk.

## Status validasi (12 bln, fee 0.05%+slippage 0.1%)

| Simbol | Sinyal | WR_TP1 | Exp net | KPI |
|---|---|---|---|---|
| ETHUSDT | 45 | 40% | +0.26R | lolos |
| SOLUSDT | 50 | 38% | +0.11R | belum |
| BTCUSDT | 58 | 31% | -0.04R | gagal |

Paper trading 14-30+ hari wajib sebelum modal riil — lihat `RUNBOOK_FASE4.md`.
