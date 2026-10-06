# Product Requirement Document (PRD)
## Crypto Trend-Pullback Signal Engine

---

### 1. Ringkasan Eksekutif & Tujuan Produk

* **Nama Produk**: Crypto Trend-Pullback Signal Engine
* **Tipe Produk**: Layanan Pemantauan Pasar & Mesin Distribusi Sinyal (*Market Intelligence & Alerting Engine*)
* **Versi Dokumen**: v1.1.0
* **Status**: Siap untuk Pengembangan (*Ready for Development*)

#### 1.1 Latar Belakang
Pasar aset kripto memiliki volatilitas tinggi dan sering mengalami fase konsolidasi (*choppy market*). Trader manual sering mengalami kerugian beruntun akibat:
1. Terjebak pergerakan palsu (*false breakout*) pada fase konsolidasi.
2. Tidak mematuhi batasan rasio risiko terhadap keuntungan (*risk-to-reward ratio*).
3. Terlambat mengeksekusi analisis karena keterbatasan pemantauan grafik 24/7.

#### 1.2 Tujuan Utama
Membangun mesin pemantau pasar algoritmik yang menyaring peluang transaksi probabilitas tinggi berbasis momentum dan arah tren makro, memvalidasi rasio risiko secara otomatis, dan mendistribusikan notifikasi terstruktur tanpa intervensi emosional.

#### 1.3 Metrik Keberhasilan (KPI)
* **Tingkat Akurasi (Win Rate TP1)**: Target $45\text{--}55\%$ untuk pencapaian TP1 ($\text{RRR}=1:1.5$) setelah biaya & slippage, diukur via backtest 12 bulan + paper trading 14--30 hari. Bukan gerbang kelulusan tunggal.
* **Positive Expectancy (metrik utama)**: $\text{Expectancy} = (WR_{\text{TP1}} \times 1.5 - (1-WR_{\text{TP1}}) \times 1.0) - \text{biaya} > 0.2R$ per sinyal. Contoh: $WR=50\% \rightarrow 0.5\times1.5-0.5\times1.0=0.25R$ sebelum biaya (lolos).
* **Win Rate TP2 (tracking)**: Dilaporkan terpisah, tidak ditarget (ekspektasi alami $30\text{--}40\%$ untuk $\text{RRR}\ge1:2$).
* **Rasio Keuntungan terhadap Risiko Minimum**: $\text{RRR}_{\text{TP2}} \ge 1:2$ pada setiap sinyal terbit (diukur ke TP2; $\text{RRR}_{\text{TP1}} = 1:1.5$ tetap dilaporkan).
* **Latensi Pemrosesan**: Komputasi close $\rightarrow$ siap kirim $\le 800\text{ ms}$; delivery siap kirim $\rightarrow$ terkirim $< 5\text{ detik}$ (terpisah, karena API Telegram/Discord).
* **False Signal Reduction**: Target pengurangan $80\%$ jumlah sinyal saat $\text{ADX}_{4\text{H}} \le 20$ vs tanpa filter (diukur di backtest sebagai baseline).

---

### 2. Ruang Lingkup Sistem

| Kategori | Di Dalam Ruang Lingkup (In-Scope) | Di Luar Ruang Lingkup (Out-of-Scope) |
| :--- | :--- | :--- |
| **Aset Pantauan** | Pasangan likuiditas tinggi: `BTC/USDT`, `ETH/USDT`, `SOL/USDT` | Token mikro (*low-cap*), meme coins, pasangan koin berlikuiditas tipis |
| **Fitur Inti** | Konsumsi data real-time, evaluasi indikator teknikal multi-timeframe, kalkulasi stop loss dinamis, pengiriman sinyal | Eksekusi order otomatis ke bursa (*direct automated trade execution*) |
| **Antarmuka** | Notifikasi pesan teks terstruktur melalui bot Telegram / Discord Webhook | Dashboard antarmuka pengguna (UI/Web App) interaktif (fase lanjutan) |
| **Mekanisme Risiko** | Penghentian sinyal saat volatilitas abnormal (*circuit breaker*) dan filter rilis berita ekonomi | Manajemen saldo akun bursa secara langsung |

---

### 3. Arsitektur Sistem & Spesifikasi Fungsional

```
┌─────────────────────────┐
│     Bursa Kripto        │ (WebSocket / REST API)
└───────────┬─────────────┘
            │ Real-time Kline/Candle & Ticker
            ▼
┌─────────────────────────┐
│ Modul 1: Data Ingestion │ (Normalisasi & Buffer Data)
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Modul 2: Signal Engine  │ (Analisis Multi-Timeframe: 4H, 1H, 15M)
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Modul 3: Risk Engine    │ (ATR Stop Loss, RRR Check, Position Sizing)
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Modul 4: Circuit Breaker│ (Filter Berita Makro & Consecutive Loss Lock)
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ Modul 5: Dispatcher     │ (Kirim Notifikasi Telegram / Discord)
└─────────────────────────┘
```

#### Modul 1: Penerima Data Pasar (*Market Data Ingestion*)
* Menjaga koneksi persisten via WebSocket ke bursa (misalnya Binance / Bybit).
* Mengonsumsi data OHLCV (*Open, High, Low, Close, Volume*) untuk kerangka waktu:
  * 4 Jam ($4\text{H}$)
  * 1 Jam ($1\text{H}$)
  * 15 Menit ($15\text{M}$)
* Mendeteksi pemutusan koneksi jaringan dan menjalankan *auto-reconnect* dengan exponential backoff (detail di Modul 5) + snapshot REST untuk menutup gap.

#### Modul 2: Mesin Evaluasi Sinyal (*Signal Engine*)
Logika dievaluasi tepat pada penutupan *candle* $15\text{M}$ (trigger). $1\text{H}$ dan $4\text{H}$ memakai candle closed terakhir (tanpa repaint):

1. **Filter Tren Makro ($4\text{H}$)**:
   * **Kondisi Bullish**: $\text{Close}_{4\text{H}} > \text{EMA}(200)_{4\text{H}}$ dan $\text{ADX}(14)_{4\text{H}} > 20$.
   * **Kondisi Bearish**: $\text{Close}_{4\text{H}} < \text{EMA}(200)_{4\text{H}}$ dan $\text{ADX}(14)_{4\text{H}} > 20$.
   * **Filter Netral / Hysteresis**: Jika $\text{ADX}_{4\text{H}} \le 30$, bekukan sinyal (*Market Choppy*). Sinyal dibuka kembali hanya jika $\text{ADX}_{4\text{H}} \ge 32$ (mencegah flicker). Nilai 20/22 pada v1.1 terbukti expectancy negatif ($-0.16$s.d.$-0.01R$, WR 30--35%) pada validasi 3 simbol x 3 bulan; grid 24 kombinasi menunjukkan ADX 30 konsisten positif di BTC/ETH/SOL (tuning Fase 2b).
   * Warmup wajib sebelum live: $\ge 250$ candle closed per TF ($4\text{H}$/$1\text{H}$/$15\text{M}$); bila data kurang, mesin status `WARMING_UP`, tidak terbit sinyal.
2. **Hierarki Timeframe**:
   * $4\text{H}$ = bias arah (filter, tidak bisa di-override).
   * $1\text{H}$ = konfirmasi momentum searah.
   * $15\text{M}$ = trigger entry. Sinyal LONG hanya bila bias $4\text{H}$ Bullish; SHORT hanya bila bias Bearish.
3. **Pemicu Masuk LONG (semua harus terpenuhi pada candle $15\text{M}$ closed)**:
   * **Pullback terkuantifikasi**: $\min(\text{Low}, \text{Close})_{15\text{M}}$ menyentuh zona $\text{EMA}(21)$ atau $\text{EMA}(55)_{15\text{M}}$ dengan toleransi $\le 0.5 \times \text{ATR}(14)_{15\text{M}}$ (tunable 0.3--1.0), yaitu $|\text{Low} - \text{EMA}| \le 0.5\times\text{ATR}$ atau $|\text{Close} - \text{EMA}| \le 0.5\times\text{ATR}$. Candle tidak boleh close $> 1.0 \times \text{ATR}$ di bawah kedua EMA (breakdown, bukan pullback).
   * **Momentum (dual-path, salah satu cukup)**:
     * Path A (oversold bounce): $\text{RSI}(14)_{15\text{M}}$ cross-up: $\text{RSI}_{\text{prev}} < 40$ dan $\text{RSI}_{\text{curr}} > 40$ (tunable 35--45); DAN $\text{RSI}(14)_{1\text{H}} > 40$.
     * Path B (shallow pullback): $\text{RSI}(14)_{15\text{M}} > 45$ (hold, tanpa perlu oversold); DAN $\text{RSI}(14)_{1\text{H}} > 45$ (mencegah counter-trend).
   * **Volume Konfirmasi**: $\text{Volume}_{\text{sinyal}} \ge 1.0 \times \text{SMA}(\text{Volume}, 20)_{15\text{M}}$ (default 1.0; rentang tuning 1.0--1.5 via backtest. Nilai 1.5 terbukti menghasilkan ~0 sinyal/bulan di BTC pada validasi 1 bulan).
4. **Pemicu Masuk SHORT (cermin LONG)**:
   * Pullback: $\max(\text{High}, \text{Close})_{15\text{M}}$ dalam $0.5\times\text{ATR}$ dari $\text{EMA}(21)$/$\text{EMA}(55)_{15\text{M}}$; tidak close $>1.0\times\text{ATR}$ di atas kedua EMA.
   * Momentum: Path A: $\text{RSI}_{\text{prev},15\text{M}} > 60$ dan $\text{RSI}_{\text{curr},15\text{M}} < 60$; DAN $\text{RSI}_{1\text{H}} < 60$. Path B: $\text{RSI}_{15\text{M}} < 55$ DAN $\text{RSI}_{1\text{H}} < 55$.
   * Volume: sama seperti LONG.
5. **Deduplikasi**: Maks 1 sinyal per simbol per arah tiap 6 candle $15\text{M}$ (90 menit), kecuali sinyal sebelumnya sudah TP/SL. Sinyal berlawanan arah membatalkan antrean yang belum entry.

#### Modul 3: Manajemen Risiko Dinamis (*Risk Engine*)
* **Acuan Entry**: $\text{Entry} = \text{Close}_{15\text{M}}$ candle sinyal. $\text{Toleransi Entry Maks} = \text{Entry} \times (1 \pm 0.001)$ (+ untuk Long, $-$ untuk Short, batas slippage 0.1%). Sinyal kedaluwarsa bila tidak terisi dalam 3 candle $15\text{M}$ atau muncul sinyal berlawanan arah.
* **Stop Loss (SL)** — swing terdefinisi, $\text{ATR} = \text{ATR}(14)_{15\text{M}}$:
  $$\text{SL}_{\text{Long}} = \min(\text{Low}_{-20..-1}) - (1.5 \times \text{ATR})$$
  $$\text{SL}_{\text{Short}} = \max(\text{High}_{-20..-1}) + (1.5 \times \text{ATR})$$
  Lookback $N=20$ candle $15\text{M}$ (tunable via backtest). Risiko per trade $R = |\text{Entry} - \text{SL}|$.
* **Position Sizing (saran, tanpa eksekusi otomatis)**:
  $$\text{Qty} = (\text{Ekuitas} \times \text{Risiko}\%) / R,\quad \text{Risiko}\% \text{ default } 1\%, \text{ maks } 2\%$$
  Contoh: ekuitas 1.000 USDT, $R=1.150$ USDT (BTC) $\rightarrow$ qty $\approx 0.0087$ BTC pada risiko 1%. Sinyal SHORT berasumsi akun futures/perp; trader spot hanya ambil sinyal LONG.
* **Signal Tracker (wajib untuk audit & Circuit Breaker)**: Setiap sinyal OPEN di-mark ke candle $15\text{M}$ berikutnya dengan prioritas konservatif: cek SL dulu (wick), lalu TP1/TP2. Status akhir: `TP1_HIT`, `TP2_HIT`, `SL_HIT`, `EXPIRED`, `INVALIDATED`. TP1 terisi $\rightarrow$ status tetap OPEN dengan SL dipindah ke BEP hingga TP2/SL.
* **Target Keuntungan (Take Profit)**:
  * **TP 1**: Ditetapkan pada $\text{RRR}_{\text{TP1}} = 1:1.5$ dari risiko (Entry $-$ SL). Aksi: tutup $50\%$ porsi posisi dan ubah SL ke *Break Even*.
  * **TP 2**: Ditetapkan pada $\text{RRR}_{\text{TP2}} \ge 1:2$ dari risiko, atau dipangkas ke level struktur teknikal utama berikutnya bila struktur lebih dekat (dengan syarat tetap $\ge 1:2$).
* **Aturan Pembatalan Sinyal**: Hitung $\text{RRR}_{\text{TP2}} = |\text{TP2}_{\text{rencana}} - \text{Entry}| / |\text{Entry} - \text{SL}|$. Jika $\text{RRR}_{\text{TP2}} < 1:2$ (misal resistensi/support terdekat memaksa TP2 lebih dekat), sinyal digugurkan. $\text{RRR}_{\text{TP1}}$ tidak dipakai untuk pembatalan.

#### Modul 4: Protokol Pengaman Sistem (*Circuit Breaker*)
* **Filter Berita Makroekonomi**: Sumber kalender terkonfigurasi (`ECON_CAL_PROVIDER`: `manual_json` default; opsional `FMP`/`Finnhub`). Daftar high-impact: FOMC, Fed Rate, CPI, PPI, NFP, GDP AS. Pembekuan sinyal aktif $60\text{ menit}$ sebelum s.d. sesudah rilis (waktu UTC). File `econ_calendar.json` dapat diisi manual bila API down; bila sumber tidak tersedia dan ada event dalam $\pm 2$ jam yang belum pasti, fail-closed (bekukan) + log `WARN`.
* **Batas Toleransi Kerugian Beruntun**: Dihitung dari Signal Tracker (Modul 3): jika ada $2$ sinyal dengan status `SL_HIT` berturut-turut (tanpa `TP1_HIT`/`TP2_HIT` di antaranya) pada simbol yang sama dalam 24 jam rolling, simbol tersebut dikunci 12 jam (`SYMBOL_LOCKED`). Lock otomatis lepas + tercatat di log/DB.

#### Modul 5: Modul Pengiriman Notifikasi (*Dispatcher*)
* Kanal utama: Telegram Bot API (Markdown/HTML). Discord Webhook opsional via `DISCORD_WEBHOOK_URL` (format sama, best-effort).
* Retry 3x dengan backoff untuk kegagalan jaringan; patuhi rate-limit Telegram (~30 msg/detik); tiap kirim tercatat `sent/failed` di DB.
* Reconnect WebSocket: exponential backoff (1s, 2s, 4s, maks 30s) + snapshot REST untuk menutup gap candle; status koneksi di-log.

---

### 4. Format Notifikasi Sinyal

```text
🚨 SIGNAL DETECTED: #BTC/USDT (LONG)
Timeframe: 15M entry / 1H konfirmasi / 4H bias

📥 Entry Area: 64,250 USDT
⛔ Toleransi Entry Maks: 64,320 USDT (Batas slippage 0.1%)

🛑 Stop Loss: 63,100 USDT (-1.79%)
🎯 Take Profit 1: 65,975 USDT (+2.68% | Tutup 50% & Set BEP)
🎯 Take Profit 2: 67,200 USDT (+4.59% | Target Akhir)

📊 Metrik Risiko:
• Risk/Reward TP1: 1 : 1.50
• Risk/Reward TP2: 1 : 2.57
• Macro ADX (4H): 28.4 (Bullish Kuat)
• Volatilitas ATR (14): 450 USDT

💡 Saran Manajemen: Alokasikan risiko maksimal 1-2% modal akun.
```

---

### 5. Kebutuhan Non-Fungsional

* **Performa & Latensi**:
  * Latensi komputasi (candle close $\rightarrow$ sinyal siap kirim): $< 800\text{ ms}$.
  * Latensi delivery (siap kirim $\rightarrow$ terkirim Telegram/Discord): target $< 5\text{ detik}$ (di luar kendali penuh karena API pihak ketiga; diukur & di-log terpisah).
  * Penggunaan memori server efisien dengan batas konsumsi memori $< 512\text{ MB}$ per instans.
* **Ketersediaan Layanan (Reliability)**:
  * *Uptime* target: $99.5\%$ selama jam operasional pasar non-pemeliharaan bursa.
  * Persistensi MVP: SQLite (`signals.db`, tabel `signals`, `events`). Redis opsional fase lanjutan.
  * Observabilitas minimal: log terstruktur (level INFO/WARN/ERROR), healthcheck `/health`, metrik hitung sinyal/TP/SL/latensi.
* **Keamanan Kredensial**:
  * Variabel rahasia (*Telegram Bot Token*, *API Key*) disimpan di `.env` dan tidak boleh di-*hardcode* ke repositori kode.
  * Akses bot Telegram dibatasi hanya pada daftar ID obrolan (*whitelist chat IDs*) yang terdaftar.

---

### 6. Rencana Implementasi & Roadmap

```
Fase 1: Infrastruktur Data ──► Fase 2: Mesin Sinyal ──► Fase 3: Modul Risiko ──► Fase 4: Paper Trading
   (Pekan 1)                      (Pekan 2)                   (Pekan 3)               (Pekan 4 - 6)
```

1. **Fase 1: Infrastruktur Data (Pekan 1)**
   * Pembuatan skrip integrasi WebSocket bursa (`ccxt` atau native WebSocket).
   * Perhitungan formula teknikal (EMA, RSI, ADX, ATR).
2. **Fase 2: Mesin Sinyal & Backtesting (Pekan 2)**
   * Implementasi logika penyaring tren multi-timeframe.
   * *Backtesting* 12 bulan terakhir (asumsi: fee $0.05\%$/sisi, slippage $0.1\%$, spread diabaikan) untuk memvalidasi expectancy $> 0.2R$.
   * Hasil validasi 12 bln (baseline ADX30 + TP2 struktur): BTC 58 sinyal WR 31% exp $-0.04R$ (gagal), ETH 45 sinyal WR 40% exp $+0.26R$ (lolos), SOL 50 sinyal WR 38% exp $+0.11R$ (belum lolos). Keputusan: paper trading per-simbol; BTC perlu tuning lanjutan / nonaktif sementara.
3. **Fase 3: Modul Risiko & Dispatcher (Pekan 3)**
   * Integrasi formula SL berbasis ATR dan target profit bertahap.
   * Integrasi bot Telegram dan penyusunan template pesan.
   * Penerapan logika *circuit breaker*.
4. **Fase 4: Uji Coba Pasar Riil / Paper Trading (Pekan 4-6)**
   * Menjalankan bot di pasar riil tanpa eksekusi modal riil selama 14-30 hari.
   * Audit rasio keberhasilan, evaluasi *slippage*, dan penyesuaian parameter indikator.