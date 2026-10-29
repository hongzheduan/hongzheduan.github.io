#!/usr/bin/env python3
"""
SB Tracker: top 10 S&P 500 / Nasdaq-100 stocks by 3-month price change, returns after 7 sessions
(user, 2026-10-28). No news involved: the rule is spg_tracker.py's build_entry (close vs the close
63 sessions earlier, from candles.json); SB differs from SPG only in its 7-session horizon.
backtests/spg_formula_search.py 7 (105 rules, 245 sessions): +2.42% mean / +2.60% median per 7 sessions
vs SPY +0.39% / +0.24%, ahead of SPY in 62% of lists, worst list -15.5%, ahead in both halves.
The news rule tried first (backtests/sb_formula_search.py, 55 sessions) was set aside by the user.

Until 2026-10-28 SB used the product-news rule below, still defined here as build_news_entry because
custom_tracker.py runs it:

A stock qualifies when data/product_news.json (fetch_product_news.py: Google News headlines
that start with the company's name followed by a launch verb, e.g. "Apple unveils ...") has a
headline dated within the last WINDOW sessions and its scanner Sector is SECTOR ("Technology"
only, user 2026-10-25; backtests/product_news_tech_backtest.py, 52 sessions: +0.52% mean per
7 days vs all sectors -0.18%, SPY -0.00%, avg 6.7 stocks a list, ~8 independent periods,
noise-level; at 2 days, 57 sessions: -0.04% vs all sectors -0.11%, SPY +0.00%, no edge). Ranked by how many outlets carried the launch
news in that window, then today's volume vs its 21-day average, up to TOP_N. A day with no
qualifying stock is still logged, with an empty list. (Replaced the 8-K filing + volume
spike rule of fb612460 the same day.)

Each list's return is measured HORIZON = 2 trading sessions later (user, 2026-10-25; was 7, before that 6).
product_news_volatility_backtest.py 7: most outlets first -0.18% mean per 7 days vs SPY -0.00%
(most volatile first, 2026-10-24 to 10-25, was +0.22%; user went back to outlets first).
Storage and exits reuse baizora_tracker.py with this file's builder and output file.
backtests/product_news_backtest.py: only 53 sessions of headline history (Aug..Oct 2026,
sparse early on): -0.31% mean per 6 days vs SPY -0.00%, ahead in 47%; far too little data to
judge. Lists before 2026-10-23 were rebuilt from the headlines the feed still returned that day.

Usage:
    python sb_tracker.py                # append today's list if new
    python sb_tracker.py --rerank       # rebuild every logged session from git history
"""
import argparse
import bisect
import json
from pathlib import Path

import baizora_tracker as bt
from spg_tracker import build_entry   # top 10 by 3-month change (user, 2026-10-28)

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "sb_tracker.json"
NEWS = ROOT / "data" / "product_news.json"
TOP_N = 10
HORIZON = 7     # trading sessions after the list date (user, 2026-10-28; was 2, before that 7, then 6)
SECTOR = "Technology"  # only this scanner Sector qualifies (user, 2026-10-25)
WINDOW = 3      # headline dated within the last 3 sessions (weekend news counts toward Monday)
_cache = {}


def _load():
    if not _cache:
        _cache["candles"] = json.loads(bt.CANDLES.read_text(encoding="utf-8"))
        try:
            _cache["news"] = json.loads(NEWS.read_text(encoding="utf-8")).get("items", [])
        except (FileNotFoundError, json.JSONDecodeError):
            _cache["news"] = []
    return _cache["candles"], _cache["news"]


def build_news_entry(data):
    """The product-news rule SB used until 2026-10-28; custom_tracker.py still uses it."""
    candles, news = _load()
    dates = candles.get("dates") or []
    if data["date"] not in dates:
        return None   # candles.json not updated for this date yet; a later run retries
    d = dates.index(data["date"])
    lo, hi = dates[d - WINDOW], dates[d]
    by_t = {}
    for it in news:
        if lo < it["date"] <= hi:
            by_t.setdefault(it["ticker"], []).append(it)
    stale = set(data.get("staleTickers") or [])
    found = []
    for r in data.get("data", []):
        t = r.get("Ticker")
        if t not in by_t or r.get("Sector") != SECTOR or not (r.get("InSP500") or r.get("InNASDAQ100")) or t in stale or not r.get("Price"):
            continue
        items = sorted(by_t[t], key=lambda i: i["date"])
        outlets = len({i["source"] or i["title"] for i in items})
        bars = (candles.get("data") or {}).get(t) or []
        lo_i = len(dates) - len(bars)   # arrays are end-aligned to dates
        f = bisect.bisect_left(dates, items[0]["date"])   # first session on/after the first headline
        before = bars[f - 1 - lo_i] if 0 <= f - 1 - lo_i < len(bars) and bars[f - 1 - lo_i] else None
        found.append((outlets, items, before[3] if before else None, r))
    found.sort(key=lambda x: (-x[0], -(x[3].get("VolumeVsMA21_1D") or 0), -(x[3].get("MarketCap") or 0), x[3]["Ticker"]))
    spy = next((r for r in data["data"] if r.get("Ticker") == "SPY"), None)

    def rnd(v, n=2):
        return None if v is None else round(v, n)

    picks = []
    for i, (outlets, items, before, r) in enumerate(found[:TOP_N]):
        top = items[-1]   # latest headline
        picks.append({
            "rank": i + 1,
            "ticker": r["Ticker"],
            "name": r.get("CompanyName") or "",
            "sector": r.get("Sector") or "",
            "price": r["Price"],
            "chg1d": rnd(r.get("PriceChange1D")),
            "news": top["title"],
            "newsSource": top["source"],
            "newsUrl": top["link"],
            "newsDate": items[0]["date"],
            "outlets": outlets,
            "chgSince": rnd((r["Price"] / before - 1) * 100 if before else None),
            "chg1y": rnd(r.get("1YPriceChange")),
            "volVsMa21": rnd(r.get("VolumeVsMA21_1D"), 3),
        })
    return {"date": data["date"], "spy": spy.get("Price") if spy else None, "qualified": len(found), "picks": picks}


# Point the shared Baizora Tracker machinery at this tracker's file, rule and horizon.
# (Importing spg_tracker patches bt for SPG; the three lines below take it back.)
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
