#!/usr/bin/env python3
"""
SPG Tracker: daily list of the strongest 3-month gainers (user, 2026-10-28).

Each finished trading session: rank the S&P 500 / Nasdaq-100 stocks by their 3-month price change
(close vs the close MOM_WINDOW = 63 sessions earlier, from candles.json) and list the TOP_N highest.
Picked by backtests/spg_formula_search.py (105 top-10 rules, 2-session returns, 250 sessions):
+0.76% mean / +0.67% median per 2 sessions vs SPY +0.11% / +0.18%, ahead of SPY in 60% of lists,
worst list -15.8%; ahead of SPY in both halves of the year. In-sample, survivorship-biased.
Until 2026-10-28 SPG used 5 straight higher closes + lowest 1-year volatility; that rule now
lives on as sg_tracker.py.

Storage, track record and exits work exactly like the Baizora Tracker: this script reuses
baizora_tracker.py (add / backfill / fill_exits) with its own output file and entry builder.
Each list's return is measured HORIZON = 2 trading sessions later (user, 2026-10-23).

Usage:
    python spg_tracker.py                # append today's list if new
    python spg_tracker.py --backfill 30  # rebuild the last 30 sessions from git history
"""
import argparse
import json
from pathlib import Path

import baizora_tracker as bt

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "spg_tracker.json"
TOP_N = 10
MOM_WINDOW = 63     # sessions in the 3-month price change (user, 2026-10-28)
VOL_WINDOW = 252    # daily returns in the 1-year volatility (shown, not ranked)
HORIZON = 2         # trading sessions after the list date (user, 2026-10-23; Baizora Tracker uses 13)
_candles = None


def _bars_to(date):
    """{ticker: closes up to and including date} from candles.json, or None if date is missing."""
    global _candles
    if _candles is None:
        _candles = json.loads(bt.CANDLES.read_text(encoding="utf-8"))
    dates = _candles.get("dates") or []
    if date not in dates:
        return None
    back = len(dates) - dates.index(date) - 1   # bars after date; arrays are end-aligned
    return {t: [b[3] if b else None for b in (bars[:len(bars) - back] if back else bars)]
            for t, bars in (_candles.get("data") or {}).items()}


def build_entry(data):
    closes = _bars_to(data["date"])
    if closes is None:
        return None   # candles.json not updated for this date yet; a later run retries
    stale = set(data.get("staleTickers") or [])
    picks = []
    for r in data.get("data", []):
        t = r.get("Ticker")
        if not (r.get("InSP500") or r.get("InNASDAQ100")) or t in stale or not r.get("Price"):
            continue
        c = closes.get(t) or []
        if len(c) < MOM_WINDOW + 1 or not c[-1] or not c[-(MOM_WINDOW + 1)]:
            continue
        mom = (c[-1] / c[-(MOM_WINDOW + 1)] - 1) * 100
        last = c[-6:]
        gain5 = (last[-1] / last[0] - 1) * 100 if None not in last else None
        hist = [x for x in c[-(VOL_WINDOW + 1):] if x]
        rets = [hist[k] / hist[k - 1] - 1 for k in range(1, len(hist))]
        vol = None
        if len(rets) >= 200:
            m = sum(rets) / len(rets)
            vol = (sum((x - m) ** 2 for x in rets) / (len(rets) - 1)) ** 0.5 * 252 ** 0.5 * 100
        picks.append((mom, r, gain5, vol))
    picks.sort(key=lambda p: (-p[0], -(p[1].get("MarketCap") or 0), p[1]["Ticker"]))
    spy = next((r for r in data["data"] if r.get("Ticker") == "SPY"), None)

    def rnd(v, n=2):
        return None if v is None else round(v, n)

    return {"date": data["date"], "spy": spy.get("Price") if spy else None, "qualified": len(picks),
            "picks": [{
                "rank": i + 1,
                "ticker": r["Ticker"],
                "name": r.get("CompanyName") or "",
                "sector": r.get("Sector") or "",
                "price": r["Price"],
                "chg1d": rnd(r.get("PriceChange1D")),
                "chg3m": rnd(mom, 1),
                "chg5d": rnd(gain5),
                "vol1y": rnd(vol, 1),
                "chg1y": rnd(r.get("1YPriceChange")),
                "pxVsMa21": rnd(r.get("PriceVsMA21_1D"), 3),
                "volVsMa21": rnd(r.get("VolumeVsMA21_1D"), 3),
            } for i, (mom, r, gain5, vol) in enumerate(picks[:TOP_N])]}


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
