#!/usr/bin/env python3
"""
Custom Tracker: the SB Tracker's former rule (Technology stocks with a product-launch headline in the last
3 sessions, most outlets first, up to 10; see sb_tracker.py) with returns measured HORIZON = 21
trading sessions (about 1 month) later instead of 2 (user, 2026-10-25). Writes its own
data/custom_tracker.json so SB keeps its 2-day exits.
backtests/product_news_tech_backtest.py 21 (38 sessions): +2.04% mean per 21 days vs all sectors
-0.84%, SPY +0.22%, only ~2 independent periods.
Also stores each pick's peak (highest high) during the month for the page's Peak column (user, 2026-10-25).

Usage:
    python custom_tracker.py                # append today's list if new
    python custom_tracker.py --rerank       # rebuild every logged session from git history
"""
import json

import baizora_tracker as bt
import sb_tracker as sb

# The product-news rule (SB's rule until 2026-10-28, when SB switched to 3-month change).
bt.build_entry = sb.build_news_entry

OUT = sb.ROOT / "data" / "custom_tracker.json"
HORIZON = 21    # trading sessions after the list date, about 1 month (user, 2026-10-25)

bt.OUT = OUT
bt.HORIZON = HORIZON


def add_peaks(out):
    """Each pick's highest intraday high over the HORIZON sessions after the list date (or so far),
    as % above the list-date close, from data/candles.json (split and dividend adjusted, so the
    ratio is unaffected by splits). Stored on the entry as peak = {ticker: [pct, date]}; once the
    full month is in, peakDone freezes it (candles.json only keeps ~252 sessions)."""
    candles = json.loads(bt.CANDLES.read_text(encoding="utf-8"))
    dates, data = candles.get("dates") or [], candles.get("data") or {}
    for e in out["entries"]:
        if e.get("peakDone") or e["date"] not in dates:
            continue
        d = dates.index(e["date"])
        end = min(d + HORIZON, len(dates) - 1)
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
        if end == d + HORIZON:
            e["peakDone"] = True


def main():
    sb.main()
    out = bt.load_out()
    add_peaks(out)
    bt.save_out(out)


if __name__ == "__main__":
    main()
