"""
"Fresh crossing" variant of the BaizScore backtest.

Instead of "every day score >= threshold" (baizscore_backtest.py), this isolates
days where a ticker crosses UP to >= threshold after NOT having been at or above
that threshold at all for the trailing ~3 months (63 trading days) — i.e. a stock
that's been quiet and just now hit the bar, vs. one that's been sitting there for
a while. Forward returns are then measured from that fresh-crossing day.

Standalone / one-off. No raw per-row data is persisted — summary only.
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
LOOKBACK = 63  # "3 months" of trading days, matching the site's own 3M window
THRESHOLDS = [70, 80, 90]


def main():
    tickers, sp_set, nd_set = load_universe()
    print(f"Universe: {len(tickers)} tickers (S&P500={len(sp_set)}, Nasdaq100={len(nd_set)})")

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

    # trailing max score over the PRIOR `LOOKBACK` rows (excludes today), per ticker,
    # only valid once a ticker has that many prior rows
    all_df = all_df.sort_values(["Ticker", "RowIdx"]).reset_index(drop=True)
    all_df["TrailingMaxScore"] = (
        all_df.groupby("Ticker")["BaizScore"]
        .transform(lambda s: s.shift(1).rolling(LOOKBACK, min_periods=LOOKBACK).max())
    )

    # both the current row AND the full trailing window must be genuinely scoreable
    scoreable = all_df[all_df["RowIdx"] >= BURN_IN].copy()
    eligible = all_df["RowIdx"] >= (BURN_IN + LOOKBACK)
    fresh_eligible = all_df[eligible & all_df["TrailingMaxScore"].notna()].copy()

    print(f"Baseline (all scoreable) observations: {len(scoreable):,}")
    print(f"Eligible-for-freshness observations (>= {LOOKBACK} prior scoreable days): {len(fresh_eligible):,}")

    for thresh in THRESHOLDS:
        fresh = fresh_eligible[
            (fresh_eligible["BaizScore"] >= thresh) & (fresh_eligible["TrailingMaxScore"] < thresh)
        ]
        print(f"\n=== FRESH CROSSING >= {thresh} "
              f"(no day >= {thresh} in the prior {LOOKBACK} trading days, ~3 months) ===")
        print(f"  N fresh-crossing observations: {len(fresh):,} "
              f"({len(fresh) / len(fresh_eligible) * 100:.3f}% of eligible obs)")
        for label in FWD_HORIZONS:
            col = f"Fwd{label}"
            base = scoreable[col].dropna()
            f_ = fresh[col].dropna()
            if len(f_) == 0:
                print(f"  {label}: N=0 (no observations)")
                continue
            edge_mean = f_.mean() - base.mean()
            edge_median = f_.median() - base.median()
            print(f"  {label}: N={len(f_):5d}  mean={f_.mean():7.3f}% (base {base.mean():7.3f}%, "
                  f"edge_mean={edge_mean:7.3f}pp)   median={f_.median():7.3f}% (base {base.median():7.3f}%, "
                  f"edge_median={edge_median:7.3f}pp)  win={((f_ > 0).mean() * 100):5.2f}%")

    print("\nDone. (no raw data files written)")


if __name__ == "__main__":
    main()
