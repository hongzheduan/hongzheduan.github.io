#!/usr/bin/env python3
"""
SB Tracker: stocks with a new product on the news (user rule, 2026-10-23).

A stock qualifies when data/product_news.json (fetch_product_news.py: Google News headlines
that start with the company's name followed by a launch verb, e.g. "Apple unveils ...") has a
headline dated within the last WINDOW sessions. Those are ranked by how many outlets carried
the launch news in that window, then today's volume vs its 21-day average, and the top
SHORTLIST kept; the shortlist is then re-ranked by 1-year volatility (annualized stdev of
daily returns from candles.json, VOL_WINDOW sessions), MOST volatile first, up to TOP_N
(user, 2026-10-24; 20-68 stocks qualified per day so far, so the shortlist rarely binds).
A day with no qualifying stock is still logged, with an empty list. (Replaced the 8-K
filing + volume spike rule of fb612460 on 2026-10-23.)
backtests/product_news_volatility_backtest.py, 53 sessions: most volatile first +0.12% mean
per 6 days vs most outlets first -0.29%, SPY -0.01%; ~9 independent periods, noise-level.

Each list's return is measured HORIZON = 7 trading sessions later (user, 2026-10-24; was 6).
product_news_volatility_backtest.py 7: most volatile first +0.22% mean per 7 days vs SPY -0.00%.
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

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "sb_tracker.json"
NEWS = ROOT / "data" / "product_news.json"
TOP_N = 10
HORIZON = 7     # trading sessions after the list date (user, 2026-10-24; was 6; Baizora Tracker uses 13)
WINDOW = 3      # headline dated within the last 3 sessions (weekend news counts toward Monday)
SHORTLIST = 100  # top stocks by outlets / volume kept before the volatility ranking (user, 2026-10-24)
VOL_WINDOW = 252  # daily returns in the 1-year volatility (same as the SPG Tracker)
MIN_RETURNS = 60  # newer listings need about 3 months of history to get a volatility
_cache = {}


def _load():
    if not _cache:
        _cache["candles"] = json.loads(bt.CANDLES.read_text(encoding="utf-8"))
        try:
            _cache["news"] = json.loads(NEWS.read_text(encoding="utf-8")).get("items", [])
        except (FileNotFoundError, json.JSONDecodeError):
            _cache["news"] = []
    return _cache["candles"], _cache["news"]


def build_entry(data):
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
        if t not in by_t or not (r.get("InSP500") or r.get("InNASDAQ100")) or t in stale or not r.get("Price"):
            continue
        items = sorted(by_t[t], key=lambda i: i["date"])
        outlets = len({i["source"] or i["title"] for i in items})
        bars = (candles.get("data") or {}).get(t) or []
        lo_i = len(dates) - len(bars)   # arrays are end-aligned to dates
        f = bisect.bisect_left(dates, items[0]["date"])   # first session on/after the first headline
        before = bars[f - 1 - lo_i] if 0 <= f - 1 - lo_i < len(bars) and bars[f - 1 - lo_i] else None
        # 1-year volatility from closes up to the list date (backfilled early lists have a bit
        # less than a year, since candles.json holds about 252 sessions)
        closes = [b[3] for b in bars[:d - lo_i + 1] if b][-(VOL_WINDOW + 1):]
        rets = [closes[k] / closes[k - 1] - 1 for k in range(1, len(closes))]
        if len(rets) < MIN_RETURNS:
            continue
        m = sum(rets) / len(rets)
        vol = (sum((x - m) ** 2 for x in rets) / (len(rets) - 1)) ** 0.5 * 252 ** 0.5 * 100
        found.append((outlets, items, before[3] if before else None, r, vol))
    found.sort(key=lambda x: (-x[0], -(x[3].get("VolumeVsMA21_1D") or 0), -(x[3].get("MarketCap") or 0), x[3]["Ticker"]))
    found = found[:SHORTLIST]
    found.sort(key=lambda x: (-x[4], -x[0], x[3]["Ticker"]))
    spy = next((r for r in data["data"] if r.get("Ticker") == "SPY"), None)

    def rnd(v, n=2):
        return None if v is None else round(v, n)

    picks = []
    for i, (outlets, items, before, r, vol) in enumerate(found[:TOP_N]):
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
            "vol1y": rnd(vol, 1),
            "chgSince": rnd((r["Price"] / before - 1) * 100 if before else None),
            "chg1y": rnd(r.get("1YPriceChange")),
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
