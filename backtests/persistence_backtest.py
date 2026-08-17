"""
"Persistence" variant of the BaizScore backtest.

For lookback windows of 1/2/3 months (21/42/63 trading days, inclusive of the
current day) and score thresholds 70/80/90, isolates days where a ticker has
scored at/above that threshold on at least 2/5/10 of the days in that window,
then measures forward returns (3M/6M/9M/1Y) from that day.

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

FWD_HORIZONS = {"3M": 63, "6M": 126, "9M": 189, "1Y": 252}
WINDOWS = {"1M": 21, "2M": 42, "3M": 63}
COUNTS = [2, 5, 10]
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

    all_df = all_df.sort_values(["Ticker", "RowIdx"]).reset_index(drop=True)

    scoreable = all_df[all_df["RowIdx"] >= BURN_IN].copy()
    print(f"Baseline (all scoreable) observations: {len(scoreable):,}")

    base_stats = {}
    for label in FWD_HORIZONS:
        col = f"Fwd{label}"
        b = scoreable[col].dropna()
        base_stats[label] = (b.mean(), b.median())

    # precompute, per threshold, the rolling count-in-window (inclusive of today) once per window
    for thresh in THRESHOLDS:
        meets = (all_df["BaizScore"] >= thresh).astype(int)
        counts_by_window = {}
        for wlabel, wdays in WINDOWS.items():
            counts_by_window[wlabel] = (
                meets.groupby(all_df["Ticker"])
                .transform(lambda s: s.rolling(wdays, min_periods=wdays).sum())
            )

        print(f"\n########## THRESHOLD >= {thresh} ##########")
        for wlabel, wdays in WINDOWS.items():
            eligible_mask = all_df["RowIdx"] >= (BURN_IN + wdays - 1)
            cnt = counts_by_window[wlabel]
            for c in COUNTS:
                sub = all_df[eligible_mask & cnt.notna() & (cnt >= c)]
                n_obs = len(sub)
                print(f"\n=== {wlabel} window, >= {thresh} on {c}+ of last {wdays} trading days "
                      f"(N obs = {n_obs:,}) ===")
                if n_obs == 0:
                    continue
                for label in FWD_HORIZONS:
                    col = f"Fwd{label}"
                    f_ = sub[col].dropna()
                    if len(f_) == 0:
                        print(f"  {label}: N=0")
                        continue
                    bmean, bmed = base_stats[label]
                    edge_mean = f_.mean() - bmean
                    edge_median = f_.median() - bmed
                    print(f"  {label}: N={len(f_):6d}  mean={f_.mean():7.3f}% (base {bmean:6.3f}%, "
                          f"edge={edge_mean:7.3f}pp)   median={f_.median():7.3f}% (base {bmed:6.3f}%, "
                          f"edge={edge_median:7.3f}pp)  win={((f_ > 0).mean() * 100):5.2f}%")

    print("\nDone. (no raw data files written)")


if __name__ == "__main__":
    main()
