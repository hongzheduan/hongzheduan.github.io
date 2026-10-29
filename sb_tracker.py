#!/usr/bin/env python3
"""
SB Tracker: the most volatile recent risers (user, 2026-10-28). Each finished session: every
S&P 500 / Nasdaq-100 stock whose close rose on each of the last STREAK = 2 sessions, then up to TOP_N
with the HIGHEST 1-year volatility (annualized std of daily returns, from candles.json). No news.
backtests/sb_up2_highvol_backtest.py, 250 sessions, 2-session returns: +0.29% mean / +0.54% median vs
SPY +0.11% / +0.18%, ahead of SPY in 55% of lists, worst -12.6%, t +0.60: noise-level edge.
Shipped as the user's rule. Returns measured after 7 sessions since 2026-10-28 (user): +0.89% mean /
+0.58% median vs SPY +0.39% / +0.24%, ahead of SPY in 51%, worst -20.3%, behind SPY in the 2nd half.

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

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "sb_tracker.json"
NEWS = ROOT / "data" / "product_news.json"
TOP_N = 10
HORIZON = 7     # trading sessions after the list date (user, 2026-10-28; was 2, before that 7, then 6; Baizora Tracker uses 13)
STREAK = 2      # consecutive sessions with a higher close (user, 2026-10-28)
VOL_WINDOW = 252  # daily returns in the 1-year volatility
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


def build_entry(data):
    """2 straight higher closes, highest 1-year volatility first, up to TOP_N (user, 2026-10-28)."""
    candles, _ = _load()
    dates = candles.get("dates") or []
    if data["date"] not in dates:
        return None   # candles.json not updated for this date yet; a later run retries
    back = len(dates) - dates.index(data["date"]) - 1   # bars after the date; arrays are end-aligned
    stale = set(data.get("staleTickers") or [])
    picks = []
    for r in data.get("data", []):
        t = r.get("Ticker")
        if not (r.get("InSP500") or r.get("InNASDAQ100")) or t in stale or not r.get("Price"):
            continue
        bars = (candles.get("data") or {}).get(t) or []
        c = [b[3] if b else None for b in (bars[:len(bars) - back] if back else bars)]
        last = c[-(STREAK + 1):]
        if len(last) < STREAK + 1 or None in last or not all(last[k] > last[k - 1] for k in range(1, len(last))):
            continue
        hist = [x for x in c[-(VOL_WINDOW + 1):] if x]
        rets = [hist[k] / hist[k - 1] - 1 for k in range(1, len(hist))]
        if len(rets) < 200:
            continue
        m = sum(rets) / len(rets)
        vol = (sum((x - m) ** 2 for x in rets) / (len(rets) - 1)) ** 0.5 * 252 ** 0.5 * 100
        picks.append((vol, r, (last[-1] / last[0] - 1) * 100))
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
                "chg2d": rnd(gain),
                "vol1y": rnd(vol, 1),
                "chg1y": rnd(r.get("1YPriceChange")),
                "pxVsMa21": rnd(r.get("PriceVsMA21_1D"), 3),
                "volVsMa21": rnd(r.get("VolumeVsMA21_1D"), 3),
            } for i, (vol, r, gain) in enumerate(picks[:TOP_N])]}


# Peak column (SB: 7 sessions, user 2026-10-28; Custom: 21, user 2026-10-25). Moved here from custom_tracker.py.
def add_peaks(out, horizon):
    """Each pick's highest intraday high over the `horizon` sessions after the list date (or so far),
    as % above the list-date close, from data/candles.json (split and dividend adjusted, so the
    ratio is unaffected by splits). Stored on the entry as peak = {ticker: [pct, date]}; once the
    full horizon is in, peakDone freezes it (candles.json only keeps ~252 sessions)."""
    candles = json.loads(bt.CANDLES.read_text(encoding="utf-8"))
    dates, data = candles.get("dates") or [], candles.get("data") or {}
    for e in out["entries"]:
        if e.get("peakDone") or e["date"] not in dates:
            continue
        d = dates.index(e["date"])
        end = min(d + horizon, len(dates) - 1)
        peak = {}
        for p in e["picks"]:
            bars = data.get(p["ticker"]) or []
            lo = len(dates) - len(bars)   # arrays are end-aligned to dates
            base = bars[d - lo] if 0 <= d - lo < len(bars) else None
            span = [(dates[k], bars[k - lo]) for k in range(d + 1, end + 1) if 0 <= k - lo < len(bars) and bars[k - lo]]
            if base and span:
                day, bar = max(span, key=lambda x: x[1][1])
                peak[p["ticker"]] = [round((bar[1] / base[3] - 1) * 100, 2), day]
        e["peak"] = peak
        if end == d + horizon:
            e["peakDone"] = True


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
    add_peaks(out, bt.HORIZON)   # bt.HORIZON: 7 for SB, 21 when run by custom_tracker.py
    bt.save_out(out)


if __name__ == "__main__":
    main()
