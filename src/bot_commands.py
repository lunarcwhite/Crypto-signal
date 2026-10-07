"""Parser + formatter perintah Telegram yang user-friendly (Bahasa Indonesia).

Tujuan: user TIDAK perlu menghafal sintaks kaku. Semua perintah:
- opsional pakai `/`  (`status` == `/status`),
- case-insensitive (`Status`, `STATUS` sama),
- punya alias ID/EN (`sinyal` == `signal`, `perf` == `audit`),
- toleran typo (`stauts` -> `/status` dengan koreksi otomatis),
- mengerti nama simbol santai (`btc`, `BTC/USDT`, `#eth` -> `BTCUSDT`),
- selalu membalas dengan tombol menu inline sehingga user tinggal tap.

Modul ini MURNI (tanpa network/DB) agar gampang di-unit-test.
I/O Telegram (polling getUpdates) ada di `src/telegram_bot.py`.
"""
from __future__ import annotations

import difflib
import re

# ---------------------------------------------------------------- perintah
CANONICAL = ("start", "help", "status", "sinyal", "perf", "locks", "kalender")

ALIASES: dict[str, set[str]] = {
    "start": {"start", "mulai", "halo", "halo", "hai", "hello", "hi", "pagi",
              "siang", "sore", "malam", "tes", "test", "ping"},
    "help": {"help", "bantuan", "tolong", "cara", "panduan", "menu", "?"},
    "status": {"status", "stat", "info", "kondisi", "posisi", "open",
               "cek", "check", "state"},
    "sinyal": {"sinyal", "signal", "signals", "sinal", "synal"},
    "perf": {"perf", "performa", "performance", "audit", "statistik",
             "statistic", "winrate", "wr", "hasil", "report", "laporan",
             "ringkasan"},
    "locks": {"locks", "lock", "kunci", "blokir", "freeze", "beku", "hold"},
    "kalender": {"kalender", "kalendar", "calendar", "econ", "ekonomi",
                 "berita", "event", "events", "jadwal"},
}

ALIAS_TO_CANON: dict[str, str] = {}
for _canon, _aliases in ALIASES.items():
    for _a in _aliases:
        ALIAS_TO_CANON.setdefault(_a, _canon)

GREETINGS = {"makasih", "terima", "kasih", "thanks", "thank", "ok", "oke",
             "siap", "mantap", "sip"}

# Untuk setMyCommands (menu autocomplete saat user mengetik "/").
BOT_COMMANDS = [
    {"command": "start", "description": "Mulai & panduan singkat"},
    {"command": "help", "description": "Bantuan lengkap + contoh"},
    {"command": "status", "description": "Status bot & posisi open"},
    {"command": "sinyal", "description": "Sinyal terbaru (cth: /sinyal BTC)"},
    {"command": "perf", "description": "Performa paper (cth: /perf 7)"},
    {"command": "locks", "description": "Kunci simbol & freeze makro"},
    {"command": "kalender", "description": "Event ekonomi terdekat"},
]


# Basis populer untuk jalan pintas ketikan 1 kata ("btc" -> sinyal BTC).
# Token asing tanpa penanda eksplisit (cth: "stxyz") TIDAK dianggap simbol
# agar typo tetap dikoreksi / dilaporkan unknown, bukan dikira koin.
KNOWN_BASES = {"BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX",
               "LINK", "TON", "ARB", "OP", "MATIC", "DOT", "LTC", "ATOM",
               "NEAR", "APT", "SUI", "SEI", "TIA", "JUP", "WIF", "PEPE",
               "BONK", "SHIB", "INJ", "S", "HYPE"}


def _looks_like_symbol_shortcut(tok: str) -> str | None:
    sym = normalize_symbol(tok)
    if not sym:
        return None
    t = tok.strip().upper()
    # penanda eksplisit: user jelas maksud koin (ada USDT, /, atau #)
    if "USDT" in t or "/" in tok or "#" in tok:
        return sym
    # atau basis populer ("btc", "eth", "sol")
    if t in KNOWN_BASES:
        return sym
    return None
def normalize_symbol(tok: str) -> str | None:
    """'btc'/'BTC/USDT'/'#eth' -> 'BTCUSDT'. Return None bila tak plausible."""
    t = tok.strip().upper().replace("#", "").replace("/", "").replace(
        "-", "").replace("_", "").replace(":", "").replace(" ", "")
    if t.endswith("USDT"):
        core = t[:-4]
    elif t.isalpha() and 2 <= len(t) <= 10:
        core, t = t, t + "USDT"
    else:
        return None
    if re.fullmatch(r"[A-Z0-9]{2,10}", core or ""):
        return t
    return None


_DAY_RE = re.compile(r"^(\d{1,3})\s*(d|day|days|h|hari)?$", re.IGNORECASE)


def _parse_days(tok: str) -> int | None:
    t = tok.strip().lower()
    mapping = {"seminggu": 7, "sebulan": 30, "seminggu": 7, "minggu": 7,
               "bulan": 30, "mingguan": 7}
    if t in mapping:
        return mapping[t]
    m = _DAY_RE.match(t)
    if m:
        v = int(m.group(1))
        if 1 <= v <= 90:
            return v
    return None


def parse_user_input(raw: str | None) -> dict:
    """Ubah ketikan bebas user menjadi intent terstruktur.

    Return: {"command", "symbol", "days", "limit", "corrected",
             "suggestion", "greeting"}
    - command: salah satu CANONICAL | "greeting" | "unknown"
    - corrected: True bila typo dikoreksi otomatis (tampilkan ke user).
    """
    text = (raw or "").strip()
    if not text:
        return {"command": "help", "symbol": None, "days": None,
                "limit": None, "corrected": False, "suggestion": None,
                "greeting": False}
    # buang "/" depan dan "@namabot" (cth: /status@BotSaya)
    first_word = text.split()[0] if text.split() else ""
    if first_word.startswith("/"):
        text = "/" + text[1:].strip()
        # tulis ulang tanpa "/" agar split seragam, tapi ingat slash-nya
    body = text[1:] if text.startswith("/") else text
    body = body.strip()
    if not body:
        return {"command": "help", "symbol": None, "days": None,
                "limit": None, "corrected": False, "suggestion": None,
                "greeting": False}
    tokens = body.split()
    head = tokens[0].split("@")[0].lower().strip(".,!?#/:;")
    rest = tokens[1:]
    corrected = False

    canon = ALIAS_TO_CANON.get(head)
    if canon is None:
        # sapaan / terima kasih saja -> sambut, jangan error
        if head in GREETINGS:
            return {"command": "greeting", "symbol": None, "days": None,
                    "limit": None, "corrected": False, "suggestion": None,
                    "greeting": True}
        # toleransi typo DULU (agar "stauts"->status, bukan dikira koin)
        guess = difflib.get_close_matches(head, list(ALIAS_TO_CANON), n=1,
                                          cutoff=0.65)
        if guess:
            canon = ALIAS_TO_CANON[guess[0]]
            corrected = True
        else:
            # ketikan 1 kata berupa simbol (cth: "btc") -> jalan pintas sinyal
            if len(tokens) == 1:
                sym = _looks_like_symbol_shortcut(tokens[0])
                if sym:
                    return {"command": "sinyal", "symbol": sym, "days": None,
                            "limit": 3, "corrected": False, "suggestion": None,
                            "greeting": False}
            sug = difflib.get_close_matches(head, list(ALIAS_TO_CANON), n=3,
                                            cutoff=0.4)
            return {"command": "unknown", "symbol": None, "days": None,
                    "limit": None, "corrected": False,
                    "suggestion": ["/" + ALIAS_TO_CANON[s] for s in sug],
                    "greeting": False}

    # --- gali argumen dari sisa token ---
    symbol: str | None = None
    days: int | None = None
    limit: int | None = None
    # simbol bisa menempel di head untuk bentuk "sinyalbtc"? abaikan (terlalu magis).
    # cek juga head sendiri bila user ketik "status btc" dsb.
    for tok in rest:
        clean = tok.strip(".,!?#")
        s = normalize_symbol(clean)
        if s and symbol is None:
            # hindari angka murni dianggap simbol
            if not clean.strip().isdigit():
                symbol = s
                continue
        d = _parse_days(clean)
        if d is not None:
            if canon == "sinyal" and d <= 10 and days is None:
                limit = d  # "/sinyal 5" = 5 sinyal terakhir
            elif days is None:
                days = d
            continue
    # bentuk "perf btc 30": simbol + hari sudah tertangani di loop.
    # default ramah: /sinyal tampilkan 3, /perf 7 hari
    if canon == "sinyal" and limit is None:
        limit = 3
    if canon == "perf" and days is None:
        days = 7
    if limit is not None:
        limit = max(1, min(10, limit))
    if days is not None:
        days = max(1, min(90, days))
    return {"command": canon, "symbol": symbol, "days": days,
            "limit": limit, "corrected": corrected, "suggestion": None,
            "greeting": False}


# ---------------------------------------------------------------- keyboard
def main_menu_keyboard() -> dict:
    """Tombol inline di bawah setiap balasan — user tinggal tap."""
    return {"inline_keyboard": [
        [{"text": "📊 Status", "callback_data": "/status"},
         {"text": "📡 Sinyal", "callback_data": "/sinyal"}],
        [{"text": "📈 Performa", "callback_data": "/perf 7"},
         {"text": "🔒 Kunci", "callback_data": "/locks"}],
        [{"text": "🗓 Kalender", "callback_data": "/kalender"},
         {"text": "❓ Bantuan", "callback_data": "/help"}],
    ]}


# ---------------------------------------------------------------- formatter
def _koreksi(intent: dict) -> str:
    if intent.get("corrected"):
        return "🔎 (Saya anggap maksud Anda perintah terkait — ketik /help untuk daftar.)\n"
    return ""


def start_text() -> str:
    return (
        "👋 Halo! Saya bot sinyal *Trend-Pullback*.\n"
        "Saya pantau BTC/ETH/SOL (4H bias → 1H konfirmasi → 15M entry) "
        "dan kirim sinyal otomatis bila setup valid.\n"
        "\nAnda tidak perlu menghafal perintah — cukup TAP tombol di bawah, "
        "atau ketik santai misalnya:\n"
        "• `status` — kondisi bot & posisi open\n"
        "• `sinyal btc` — 3 sinyal BTC terakhir\n"
        "• `perf 7` — ringkasan 7 hari\n"
        "\nKetik /help untuk panduan lengkap."
    )


def help_text() -> str:
    return (
        "❓ *Bantuan* — semua perintah bebas huruf besar/kecil, "
        "boleh tanpa `/`, typo kecil saya koreksi otomatis.\n"
        "\n📊 `/status` — status bot, posisi open, umur data terakhir.\n"
        "📡 `/sinyal [SIMBOL] [N]` — sinyal terakhir.\n"
        "   cth: `/sinyal`, `/sinyal btc`, `/sinyal eth 5`, atau cukup `btc`.\n"
        "📈 `/perf [HARI] [SIMBOL]` — win-rate & expectancy paper.\n"
        "   cth: `/perf`, `/perf 30`, `/perf btc 7`.\n"
        "🔒 `/locks` — simbol terkunci (2x SL) & freeze berita makro.\n"
        "🗓 `/kalender` — 5 event ekonomi terdekat.\n"
        "\n💡 Tips: ketik `/` di Telegram untuk melihat menu perintah, "
        "atau langsung TAP tombol di bawah."
    )


def greeting_text() -> str:
    return ("👍 Sama-sama! Semoga cuannya konsisten.\n"
            "Ada yang bisa saya bantu? Ketik /help atau TAP tombol di bawah.")


def unknown_text(intent: dict, raw: str) -> str:
    sugs = intent.get("suggestion") or []
    s = (f"🤔 Maaf, saya kurang paham maksud \"{raw.strip()[:60]}\".\n")
    if sugs:
        s += "Mungkin maksud Anda: " + ", ".join(sugs) + "?\n"
    s += ("Coba ketik santai saja, misal: `status`, `sinyal btc`, `perf 7`.\n"
          "Atau TAP salah satu tombol di bawah / ketik /help.")
    return s


def format_status(d: dict) -> str:
    lines = ["📊 *Status Bot*"]
    lines.append(f"• Uptime: {d.get('uptime_s', 0):.0f} dtk")
    lines.append(f"• Mode: {'🧪 DRY-RUN (tidak kirim sinyal)' if d.get('dry_run') else '🟢 LIVE paper'}")
    lines.append(f"• Simbol: {', '.join(d.get('symbols', [])) or '-'}")
    lines.append(f"• Posisi open: {d.get('open_trades', 0)}")
    for t in (d.get("trades") or [])[:5]:
        lines.append(f"  - #{t.get('id')} {t.get('symbol')} {t.get('dir')} "
                     f"entry {t.get('entry'):,.0f}")
    ages = d.get("last_candle_age_s") or {}
    if ages:
        lines.append("• Umur data terakhir:")
        for s, a in ages.items():
            flag = "⚠️" if a > 180 else "✅"
            lines.append(f"  {flag} {s}: {a:.0f}s")
    else:
        lines.append("• Data: ⏳ warming up (belum ada candle masuk)")
    if d.get("macro"):
        lines.append(f"• Makro: 🛑 FREEZE ({d['macro']})")
    if d.get("locked"):
        lines.append(f"• Terkunci: {', '.join(d['locked'])}")
    if d.get("closed_today") is not None:
        lines.append(f"• Sinyal closed (24 jam): {d['closed_today']}")
    return "\n".join(lines)


def format_signals(rows: list[dict], symbol: str | None = None) -> str:
    if not rows:
        judul = f" {symbol}" if symbol else ""
        return (f"📡 Belum ada sinyal{judul}.\n"
                "Bot hanya kirim sinyal bila tren valid (ADX 4H kuat + pullback + RSI + volume). "
                "Coba lagi nanti atau cek /status.")
    lines = [f"📡 *{len(rows)} sinyal terakhir" + (f" ({symbol})" if symbol else "") + "*"]
    for r in rows:
        st = r.get("outcome") or r.get("status") or "OPEN"
        lines.append(f"\n#{r.get('id')} {r.get('symbol')} {r.get('direction')} — {st}")
        lines.append(f"  Entry {r.get('entry'):,.0f} | SL {r.get('sl'):,.0f} | "
                     f"TP1 {r.get('tp1'):,.0f} | TP2 {r.get('tp2'):,.0f}")
    lines.append("\n⚠️ Bukan saran finansial. Risiko maks 1–2% per trade.")
    return "\n".join(lines)


def format_perf(a: dict, days: int, symbol: str | None = None) -> str:
    judul = f" ({symbol} — {days} hari)" if symbol else f" ({days} hari)"
    if not a.get("closed"):
        return (f"📈 Belum ada trade closed{judul}.\n"
                "KPI butuh ≥30 closed & expectancy > +0.2R (lihat /help). "
                "Bot masih warming up / menunggu setup valid.")
    lines = [f"📈 *Performa{judul}*",
             f"• Closed: {a['closed']}",
             f"• Win-rate TP1: {a.get('wr_tp1_pct', 0)}%",
             f"• Win-rate TP2: {a.get('wr_tp2_pct', 0)}%",
             f"• Expectancy: {a.get('expectancy_R', 0):+.3f}R " +
             ("✅ lolos KPI" if a.get("pass_kpi") else "⏳ belum lolos KPI")]
    by = a.get("by_symbol") or {}
    if by:
        lines.append("• Per simbol:")
        for s, c in sorted(by.items()):
            lines.append(f"  - {s}: {c}")
    return "\n".join(lines)


def format_locks(locked: list, macro: str | None, upcoming: list | None = None) -> str:
    lines = ["🔒 *Kunci & Freeze*"]
    if locked:
        lines.append("Simbol terkunci (2x SL beruntun, lepas 12 jam):")
        for s in locked:
            lines.append(f"• 🛑 {s}")
    else:
        lines.append("• ✅ Tidak ada simbol terkunci.")
    if macro:
        lines.append(f"• 🛑 Freeze makro aktif: {macro}")
    else:
        lines.append("• ✅ Tidak ada freeze makro saat ini.")
    if upcoming:
        lines.append("• Berikutnya:")
        for e in upcoming[:3]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


def format_calendar(events: list[dict]) -> str:
    if not events:
        return ("🗓 Tidak ada event high-impact terjadwal.\n"
                "Kalender kosong = tanpa freeze. Tambah manual via econ_calendar.json.")
    lines = ["🗓 *Event terdekat* (freeze ±60 mnt):"]
    for e in events[:5]:
        lines.append(f"• {e.get('when', '?')} — {e.get('title', '?')}")
    return "\n".join(lines)
