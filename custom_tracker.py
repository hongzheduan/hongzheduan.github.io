#!/usr/bin/env python3
"""
Custom Tracker: the SB Tracker's rule (Technology stocks with a product-launch headline in the last
3 sessions, most outlets first, up to 10; see sb_tracker.py) with returns measured HORIZON = 21
trading sessions (about 1 month) later instead of 2 (user, 2026-10-25). Writes its own
data/custom_tracker.json so SB keeps its 2-day exits.
backtests/product_news_tech_backtest.py 21 (38 sessions): +2.04% mean per 21 days vs all sectors
-0.84%, SPY +0.22%, only ~2 independent periods.

Usage:
    python custom_tracker.py                # append today's list if new
    python custom_tracker.py --rerank       # rebuild every logged session from git history
"""
import baizora_tracker as bt
import sb_tracker as sb   # sets bt.build_entry to the SB rule

OUT = sb.ROOT / "data" / "custom_tracker.json"
HORIZON = 21    # trading sessions after the list date, about 1 month (user, 2026-10-25)

bt.OUT = OUT
bt.HORIZON = HORIZON

if __name__ == "__main__":
    sb.main()
