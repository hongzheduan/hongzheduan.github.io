#!/usr/bin/env python3
"""
SB Tracker: stocks with big company news (user rule, 2026-10-23).

"Big news" = an SEC 8-K filing in data/corporate_events.json (earnings, leadership change,
material agreement, acquisition, ...) on one of the last WINDOW sessions, AND a volume spike
since that filing: some session's volume >= SPIKE x its prior 21-session average (from
candles.json). Ranked by the size of that spike, biggest first, up to TOP_N. A day with no
qualifying stock is still logged, with an empty list.

Each list's return is measured HORIZON = 6 trading sessions later (user, 2026-10-23).
Storage and exits reuse baizora_tracker.py with this file's builder and output file.
backtests/news_volume_backtest.py, 246 sessions, 6-session returns: +0.07% mean / +0.02%
median vs SPY +0.33% / +0.23%, ahead of SPY in 47%, avg 6.1 stocks a day, 18 days with
none. Shipped as the user's rule.

Usage:
    python sb_tracker.py                # append today's list if new
    python sb_tracker.py --rerank       # rebuild every logged session from git history
"""
import argparse
import bisect
import json
from pathlib import Path

import baizora_tracker as bt

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "sb_tracker.json"
EVENTS = ROOT / "data" / "corporate_events.json"
TOP_N = 10
HORIZON = 6     # trading sessions after the list date (user, 2026-10-23; Baizora Tracker uses 13)
WINDOW = 3      # filing on one of the last 3 sessions (an after-close filing trades the next day)
SPIKE = 2.0     # volume >= 2x its prior 21-session average
_cache = {}


def _load():
    if not _cache:
        _cache["candles"] = json.loads(bt.CANDLES.read_text(encoding="utf-8"))
        _cache["events"] = json.loads(EVENTS.read_text(encoding="utf-8"))
    return _cache["candles"], _cache["events"]


def build_entry(data):
    candles, events = _load()
    dates = candles.get("dates") or []
    if data["date"] not in dates:
        return None   # candles.json not updated for this date yet; a later run retries
    d = dates.index(data["date"])
    stale = set(data.get("staleTickers") or [])
    found = []
    for r in data.get("data", []):
        t = r.get("Ticker")
        if not (r.get("InSP500") or r.get("InNASDAQ100")) or t in stale or not r.get("Price"):
            continue
        bars = (candles.get("data") or {}).get(t) or []
        lo = len(dates) - len(bars)   # arrays are end-aligned to dates
        def bar(j):
            return bars[j - lo] if 0 <= j - lo < len(bars) and bars[j - lo] else None
        best = None
        for e in events.get(t) or []:
            f = bisect.bisect_left(dates, e["date"])   # first session on/after the filing date
            if not d - WINDOW < f <= d:
                continue
            for j in range(f, d + 1):
                prev = [b[4] for b in (bar(k) for k in range(j - 21, j)) if b and b[4]]
                b = bar(j)
                if len(prev) < 15 or not b or not b[4]:
                    continue
                spike = b[4] / (sum(prev) / len(prev))
                if spike >= SPIKE and (best is None or spike > best[0]):
                    before = bar(f - 1)
                    best = (spike, e, before[3] if before else None)
        if best:
            found.append((best, r))
    found.sort(key=lambda x: (-x[0][0], -(x[1].get("MarketCap") or 0), x[1]["Ticker"]))
    spy = next((r for r in data["data"] if r.get("Ticker") == "SPY"), None)

    def rnd(v, n=2):
        return None if v is None else round(v, n)

    picks = []
    for i, ((spike, e, before), r) in enumerate(found[:TOP_N]):
        picks.append({
            "rank": i + 1,
            "ticker": r["Ticker"],
            "name": r.get("CompanyName") or "",
            "sector": r.get("Sector") or "",
            "price": r["Price"],
            "chg1d": rnd(r.get("PriceChange1D")),
            "news": e.get("label") or ", ".join(e.get("type") or []) or "8-K filing",
            "newsDate": e["date"],
            "newsUrl": e.get("url") or "",
            "spike": rnd(spike, 1),
            "chgSince": rnd((r["Price"] / before - 1) * 100 if before else None),
            "chg1y": rnd(r.get("1YPriceChange")),
            "pxVsMa21": rnd(r.get("PriceVsMA21_1D"), 3),
            "volVsMa21": rnd(r.get("VolumeVsMA21_1D"), 3),
        })
    return {"date": data["date"], "spy": spy.get("Price") if spy else None, "qualified": len(found), "picks": picks}


# Point the shared Baizora Tracker machinery at this tracker's file, rule and horizon.
bt.OUT = OUT
bt.HORIZON = HORIZON
bt.build_entry = build_entry


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
