#!/usr/bin/env python3
"""
SB Tracker: the Baizora Tracker's daily list (same rule, baizora_tracker.py), with each
list's return measured HORIZON = 6 trading sessions later instead of 13 (user, 2026-10-23).
Writes its own data/sb_tracker.json so the exit dates differ from the Baizora Tracker's.

backtests/momentum_blend_backtest.py at a 6-session horizon, 246 sessions, 25/75:
+2.13% mean / +2.46% median vs SPY +0.33% / +0.23%, ahead of SPY in 62% (in-sample).

Usage:
    python sb_tracker.py                # append today's list if new
    python sb_tracker.py --rerank       # rebuild every logged session from git history
"""
import argparse
import json
from pathlib import Path

import baizora_tracker as bt

ROOT = Path(__file__).parent
OUT = ROOT / "data" / "sb_tracker.json"
HORIZON = 6   # trading sessions after the list date (user, 2026-10-23; Baizora Tracker uses 13)

# Point the shared Baizora Tracker machinery at this tracker's file and horizon.
bt.OUT = OUT
bt.HORIZON = HORIZON


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", type=int, default=0, help="rebuild this many past sessions from git history")
    ap.add_argument("--rerank", action="store_true",
                    help="discard all lists and rebuild every logged session with the current rule")
    args = ap.parse_args()

    out = bt.load_out()
    if args.rerank:
        # first build: match the Baizora Tracker's logged sessions
        n = len(out["entries"]) or len(json.loads((ROOT / "data" / "baizora_tracker.json").read_text(encoding="utf-8"))["entries"])
        args.backfill = max(args.backfill, n)
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
