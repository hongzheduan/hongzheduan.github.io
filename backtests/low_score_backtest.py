"""
Symmetric check on the low end: does a LOW BaizScore (<=10/<=20/<=30) predict
future price DECLINE, the same way a high score predicted future gains?

Same methodology as baizscore_backtest.py (70/80/90 upside test), median as
the primary metric. No raw per-row data persisted.
"""
import sys
import os
import pandas as pd
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backtests/ -> repo root
sys.path.insert(0, REPO)

from scanner_yfinance import fetch_yfinance_bulk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from baizscore_backtest import load_universe, compute_ticker_frame, BURN_IN  # noqa: E402

FWD_HORIZONS = {"1M": 21, "3M": 63, "6M": 126, "9M": 189, "1Y": 252}
THRESHOLDS = [10, 20, 30]


def main():
    tickers, sp_set, nd_set = load_universe()
    print(f"Universe: {len(tickers)} tickers")

    print("Fetching 4y OHLCV via yfinance (chunked) …")
    bars_by_ticker = fetch_yfinance_bulk(tickers, period="4y")
    print(f"Fetched bars for {len(bars_by_ticker)}/{len(tickers)} tickers")

    frames = []
    for t in tickers:
        f = compute_ticker_frame(t, bars_by_ticker.get(t))
        if f is not None:
            frames.append(f)
    print(f"Built per-ticker frames for {len(frames)} tickers")

    all_df = pd.concat(frames, ignore_index=True)

    all_df["RSScore"] = all_df.groupby("Date")["_RawRS"].rank(pct=True)
    all_df["RSScore"] = (all_df["RSScore"] * 98 + 1).round().clip(1, 99).astype(int)
    all_df["MomentumScore"] = all_df.groupby("Date")["_RawMomentum"].rank(pct=True)
    all_df["MomentumScore"] = (all_df["MomentumScore"] * 100).round().clip(0, 100).astype(int)

    rs_norm = (all_df["RSScore"] - 1) / 98 * 100
    vp_norm = (all_df["VolPressureScore"] + 100) / 2
    all_df["BaizScore"] = (
        0.30 * rs_norm + 0.25 * all_df["MomentumScore"] + 0.20 * all_df["BreakoutScore"]
        + 0.15 * all_df["TrendScore"] + 0.10 * vp_norm
    ).round().clip(0, 100).astype(int)

    scoreable = all_df[all_df["RowIdx"] >= BURN_IN].copy()
    print(f"\nScoreable observations: {len(scoreable):,}")
    print(f"Date range: {scoreable['Date'].min()} .. {scoreable['Date'].max()}")

    base_stats = {}
    for h in FWD_HORIZONS:
        b = scoreable[f"Fwd{h}"].dropna()
        base_stats[h] = (b.mean(), b.median())

    for thresh in THRESHOLDS:
        low = scoreable[scoreable["BaizScore"] <= thresh]
        print(f"\n=== BaizScore <= {thresh}: {len(low):,} obs "
              f"({len(low) / len(scoreable) * 100:.2f}% of scoreable obs) ===")
        for h in FWD_HORIZONS:
            col = f"Fwd{h}"
            base_mean, base_med = base_stats[h]
            f_ = low[col].dropna()
            if len(f_) == 0:
                print(f"  {h}: N=0")
                continue
            edge_mean = f_.mean() - base_mean
            edge_median = f_.median() - base_med
            print(f"  {h}: N={len(f_):6d}  mean={f_.mean():7.3f}% (base {base_mean:7.3f}%, "
                  f"edge={edge_mean:7.3f}pp)   median={f_.median():7.3f}% (base {base_med:7.3f}%, "
                  f"edge={edge_median:7.3f}pp)  win={((f_ > 0).mean() * 100):5.2f}%  "
                  f"lossrate={((f_ < 0).mean() * 100):5.2f}%")

    print("\nDone. (no raw data files written)")


if __name__ == "__main__":
    main()
