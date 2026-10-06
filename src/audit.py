"""Audit paper trading: baca signals.db -> WR + expectancy (R).

  python -m src.audit --db signals.db
  python -m src.audit --db signals.db --since-days 7
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from collections import Counter

R_MAP = {"TP2_HIT": 1.75, "TP1_ONLY": 0.75, "SL_HIT": -1.0,
         "SL_BEP": 0.0, "EXPIRED": 0.0, "INVALIDATED": 0.0}


def audit(db: str, since_ms: int | None = None) -> dict:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    q = "SELECT symbol,direction,outcome,entry,sl,risk FROM signals WHERE status='CLOSED'"
    args: list = []
    if since_ms:
        q += " AND closed_at>=?"
        args.append(since_ms)
    rows = conn.execute(q, args).fetchall()
    n = len(rows)
    wins1 = sum(1 for r in rows if r["outcome"] in ("TP1_ONLY", "TP2_HIT"))
    wins2 = sum(1 for r in rows if r["outcome"] == "TP2_HIT")
    r_tot = sum(R_MAP.get(r["outcome"], 0.0) for r in rows)
    by_sym: dict[str, Counter] = {}
    for r in rows:
        by_sym.setdefault(r["symbol"], Counter())[r["outcome"] or "?"] += 1
    locks = conn.execute("SELECT symbol,reason FROM locks").fetchall() if _has(conn, "locks") else []
    return {"closed": n, "wr_tp1_pct": round(100 * wins1 / n, 1) if n else 0.0,
            "wr_tp2_pct": round(100 * wins2 / n, 1) if n else 0.0,
            "expectancy_R": round(r_tot / n, 3) if n else 0.0,
            "by_symbol": {k: dict(v) for k, v in by_sym.items()},
            "locks": [dict(x) for x in locks],
            "pass_kpi": bool(n >= 30 and (r_tot / n if n else 0) > 0.2)}


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="signals.db")
    ap.add_argument("--since-days", type=int, default=0)
    a = ap.parse_args()
    since = int(time.time() * 1000) - a.since_days * 86400_000 if a.since_days else None
    import json
    print(json.dumps(audit(a.db, since), indent=2))


if __name__ == "__main__":
    main()
