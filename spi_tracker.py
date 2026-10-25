#!/usr/bin/env python3
"""
SPI Tracker: daily top 10 by 25% BaizConviction + 75% 3-month price change (user, 2026-10-24).

Until 2026-10-24 spi_tracker.html showed the Baizora Tracker's own lists. When the Baizora
Tracker moved to RS + Momentum conviction, the user put the earlier 25/75 rule on SPI:
    rank score = 0.25 x pct(BaizConviction) + 0.75 x pct(3MPriceChange)
percentiles taken within that day's eligible S&P 500 / Nasdaq-100 stocks (average rank for
ties, missing 3M change = 0.5); ties broken by BaizScore, then market cap.
backtests/momentum_blend_backtest.py (239 sessions, in-sample): +4.83% mean per 13 sessions
vs BaizConviction alone +3.70%, SPY +0.79%; not significant.

Storage, track record and exits work exactly like the Baizora Tracker: this script reuses
baizora_tracker.py (add / backfill / fill_exits) with its own output file and entry builder.
Backfilled lists use the corrected BaizConviction values (bt.backfill applies them).

Usage:
    python spi_tracker.py                # append today's list if new
    python spi_tracker.py --rerank       # rebuild every logged session from git history
"""
import argparse
import json
from bisect import bisect_left, bisect_right
from pathlib import Path

import baizora_tracker as bt

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "spi_tracker.json"
TOP_N = 10
CONV_WEIGHT, MOM_WEIGHT = 0.25, 0.75  # rank score weights (user, 2026-10-24)
HORIZON = 13  # trading sessions after the list date, same as the Baizora Tracker


def build_entry(data):
    stale = set(data.get("staleTickers") or [])
    rows = [r for r in data.get("data", [])
            if (r.get("InSP500") or r.get("InNASDAQ100"))
            and r.get("Ticker") not in stale
            and r.get("BaizConviction") is not None
            and r.get("Price")]
    if len(rows) < TOP_N:
        return None

    def pct(col):
        vals = sorted(r[col] for r in rows if r.get(col) is not None)
        n = len(vals)
        # average rank for ties; missing momentum = neutral 0.5
        return {r["Ticker"]: (0.5 if r.get(col) is None or n < 2 else
                              (bisect_left(vals, r[col]) + bisect_right(vals, r[col]) - 1) / 2 / (n - 1))
                for r in rows}
    pc, pm = pct("BaizConviction"), pct("3MPriceChange")
    for r in rows:
        r["_rank"] = CONV_WEIGHT * pc[r["Ticker"]] + MOM_WEIGHT * pm[r["Ticker"]]
    rows.sort(key=lambda r: (-r["_rank"], -(r.get("BaizScore") or 0),
                             -(r.get("MarketCap") or 0), r["Ticker"]))
    spy = next((r for r in data["data"] if r.get("Ticker") == "SPY"), None)

    def rnd(v, n=2):
        return None if v is None else round(v, n)

    return {"date": data["date"], "spy": spy.get("Price") if spy else None, "picks": [{
        "rank": i + 1,
        "ticker": r["Ticker"],
        "name": r.get("CompanyName") or "",
        "sector": r.get("Sector") or "",
        "price": r["Price"],
        "conviction": r["BaizConviction"],
        "score": r.get("BaizScore"),
        "persist": r.get("BaizPersist"),
        "chg1d": rnd(r.get("PriceChange1D")),
        "chg1y": rnd(r.get("1YPriceChange")),
        "chg3m": rnd(r.get("3MPriceChange")),
        "rankScore": rnd(r["_rank"] * 100, 1),
        "pxVsMa21": rnd(r.get("PriceVsMA21_1D"), 3),
        "volVsMa21": rnd(r.get("VolumeVsMA21_1D"), 3),
    } for i, r in enumerate(rows[:TOP_N])]}


# Point the shared Baizora Tracker machinery at this tracker's file and rule.
bt.OUT = OUT
bt.build_entry = build_entry
bt.HORIZON = HORIZON


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0, help="rebuild this many past sessions from git history")
    ap.add_argument("--rerank", action="store_true",
                    help="discard all lists and rebuild every logged session with the current rule")
    args = ap.parse_args()

    out = bt.load_out()
    if args.rerank:
        args.backfill = max(args.backfill, len(out["entries"]))
        out = {"entries": []}
    if args.backfill:
        bt.backfill(out, args.backfill)
    data = json.loads(bt.LATEST.read_text(encoding="utf-8"))
    if bt.add(out, data):
        print("added", data["date"])
    else:
        print(f"no new list (latest.json {data.get('date')}, midday={data.get('midday')})")
    bt.fill_exits(out, data)
    bt.save_out(out)


if __name__ == "__main__":
    main()
