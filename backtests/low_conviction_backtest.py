"""
Does LOW BaizPersist / BaizConviction predict decline better than low raw
BaizScore did? Same methodology as low_score_backtest.py, but using the
1M-only smooth-average definitions now shipped in scanner_tiingo.py:

  BaizPersist    = trailing 21-session average of BaizScore (this ticker only)
  BaizConviction = sqrt(BaizScore * BaizPersist)

No raw per-row data persisted.
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
PERSIST_WINDOW = 21
THRESHOLDS = [10, 20, 30]


def summarize(sub, base_stats, label):
    n = len(sub)
    print(f"\n=== {label} (N obs = {n:,}) ===")
    if n == 0:
        return
    for h in FWD_HORIZONS:
        col = f"Fwd{h}"
        f_ = sub[col].dropna()
        if len(f_) == 0:
            print(f"  {h}: N=0")
            continue
        bmean, bmed = base_stats[h]
        print(f"  {h}: N={len(f_):6d}  mean={f_.mean():7.3f}% (base {bmean:7.3f}%, edge={f_.mean()-bmean:7.3f}pp)"
              f"   median={f_.median():7.3f}% (base {bmed:7.3f}%, edge={f_.median()-bmed:7.3f}pp)"
              f"  win={((f_ > 0).mean() * 100):5.2f}%  lossrate={((f_ < 0).mean() * 100):5.2f}%")


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

    all_df = all_df.sort_values(["Ticker", "RowIdx"]).reset_index(drop=True)
    all_df["BaizPersist"] = (
        all_df["BaizScore"].groupby(all_df["Ticker"])
        .transform(lambda s: s.rolling(PERSIST_WINDOW, min_periods=PERSIST_WINDOW).mean())
    )
    all_df["BaizConviction"] = np.sqrt(all_df["BaizScore"].clip(lower=0) * all_df["BaizPersist"].clip(lower=0))

    eligible = all_df["RowIdx"] >= (BURN_IN + PERSIST_WINDOW - 1)
    scoreable = all_df[eligible & all_df["BaizPersist"].notna()].copy()
    print(f"\nScoreable observations: {len(scoreable):,}")

    base_stats = {h: (scoreable[f"Fwd{h}"].dropna().mean(), scoreable[f"Fwd{h}"].dropna().median()) for h in FWD_HORIZONS}

    print("\n########## LOW BaizScore (reference, same as before) ##########")
    for thresh in THRESHOLDS:
        sub = scoreable[scoreable["BaizScore"] <= thresh]
        summarize(sub, base_stats, f"BaizScore <= {thresh}")

    print("\n########## LOW BaizPersist ##########")
    for thresh in THRESHOLDS:
        sub = scoreable[scoreable["BaizPersist"] <= thresh]
        summarize(sub, base_stats, f"BaizPersist <= {thresh}")

    print("\n########## LOW BaizConviction ##########")
    for thresh in THRESHOLDS:
        sub = scoreable[scoreable["BaizConviction"] <= thresh]
        summarize(sub, base_stats, f"BaizConviction <= {thresh}")

    print("\nDone. (no raw data files written)")


if __name__ == "__main__":
    main()
