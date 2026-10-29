#!/usr/bin/env python3
"""
Custom Tracker: the SB Tracker's former rule (Technology stocks with a product-launch headline in the last
3 sessions, most outlets first, up to 10; see sb_tracker.py) with returns measured HORIZON = 21
trading sessions (about 1 month) later instead of 2 (user, 2026-10-25). Writes its own
data/custom_tracker.json so SB keeps its 2-day exits.
backtests/product_news_tech_backtest.py 21 (38 sessions): +2.04% mean per 21 days vs all sectors
-0.84%, SPY +0.22%, only ~2 independent periods.
Also stores each pick's peak (highest high) during the month for the page's Peak column (user, 2026-10-25;
sb_tracker.add_peaks since 2026-10-28).

Usage:
    python custom_tracker.py                # append today's list if new
    python custom_tracker.py --rerank       # rebuild every logged session from git history
"""
import json

import baizora_tracker as bt
import sb_tracker as sb

# The product-news rule (SB's rule until 2026-10-28, when SB switched to 2 up days + highest volatility).
bt.build_entry = sb.build_news_entry

OUT = sb.ROOT / "data" / "custom_tracker.json"
HORIZON = 21    # trading sessions after the list date, about 1 month (user, 2026-10-25)

bt.OUT = OUT
bt.HORIZON = HORIZON


def main():
    sb.main()   # also stores each pick's peak over bt.HORIZON (21) sessions, sb_tracker.add_peaks


if __name__ == "__main__":
    main()
