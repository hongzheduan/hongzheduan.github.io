"""
Does TurnScore (weak-to-strong reversal signal) predict forward returns?

TurnScore = round(BreakoutScore * (1 - RSScore/100) * vp_turn), vp_turn = ((VolPressureScore+100)/200).clip(lower=0)
— rewards a currently-weak stock (low RS) showing a strong breakout backed by buying volume. Structurally
different from BaizScore: it explicitly wants LOW RS, not high. Dashboard tooltip documents 50+ = strong signal,
25-49 = emerging, <25 = no signal -- those are the thresholds tested here (plus 40 as an intermediate check).

Same methodology as baizscore_backtest.py, median as the primary metric. No raw per-row data persisted.
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
THRESHOLDS = [25, 40, 50]


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

    vp_turn = ((all_df["VolPressureScore"] + 100) / 200).clip(lower=0)
    all_df["TurnScore"] = (
        all_df["BreakoutScore"] * (1 - all_df["RSScore"] / 100) * vp_turn
    ).round().clip(0, 100).astype(int)

    scoreable = all_df[all_df["RowIdx"] >= BURN_IN].copy()
    print(f"\nScoreable observations: {len(scoreable):,}")
    print(f"Date range: {scoreable['Date'].min()} .. {scoreable['Date'].max()}")

    print("\nTurnScore distribution (scoreable rows):")
    print(scoreable["TurnScore"].describe(percentiles=[.5, .75, .9, .95, .99]).to_string())

    base_stats = {}
    for h in FWD_HORIZONS:
        b = scoreable[f"Fwd{h}"].dropna()
        base_stats[h] = (b.mean(), b.median())

    print("\n########## TurnScore thresholds (upside) ##########")
    for thresh in THRESHOLDS:
        high = scoreable[scoreable["TurnScore"] >= thresh]
        print(f"\n=== TurnScore >= {thresh}: {len(high):,} obs "
              f"({len(high) / len(scoreable) * 100:.3f}% of scoreable obs) ===")
        for h in FWD_HORIZONS:
            col = f"Fwd{h}"
            base_mean, base_med = base_stats[h]
            f_ = high[col].dropna()
            if len(f_) == 0:
                print(f"  {h}: N=0")
                continue
            edge_mean = f_.mean() - base_mean
            edge_median = f_.median() - base_med
            print(f"  {h}: N={len(f_):6d}  mean={f_.mean():7.3f}% (base {base_mean:7.3f}%, "
                  f"edge={edge_mean:7.3f}pp)   median={f_.median():7.3f}% (base {base_med:7.3f}%, "
                  f"edge={edge_median:7.3f}pp)  win={((f_ > 0).mean() * 100):5.2f}%")

    # comparison group: TurnScore == 0 (no signal at all) — is the signal doing anything vs literally nothing firing?
    print("\n########## TurnScore == 0 (no signal) vs baseline ##########")
    zero = scoreable[scoreable["TurnScore"] == 0]
    print(f"\n=== TurnScore == 0: {len(zero):,} obs ({len(zero) / len(scoreable) * 100:.2f}% of scoreable obs) ===")
    for h in FWD_HORIZONS:
        col = f"Fwd{h}"
        base_mean, base_med = base_stats[h]
        f_ = zero[col].dropna()
        edge_mean = f_.mean() - base_mean
        edge_median = f_.median() - base_med
        print(f"  {h}: N={len(f_):6d}  mean={f_.mean():7.3f}% (base {base_mean:7.3f}%, "
              f"edge={edge_mean:7.3f}pp)   median={f_.median():7.3f}% (base {base_med:7.3f}%, "
              f"edge={edge_median:7.3f}pp)  win={((f_ > 0).mean() * 100):5.2f}%")

    # decile monotonicity check (excluding the TurnScore==0 mass point which dominates the low end)
    print("\n########## DECILE CHECK (TurnScore > 0 only, to avoid the zero mass point) ##########")
    nonzero = scoreable[scoreable["TurnScore"] > 0].copy()
    for h in FWD_HORIZONS:
        col = f"Fwd{h}"
        d = nonzero[[col, "TurnScore"]].dropna()
        d["decile"] = pd.qcut(d["TurnScore"], 10, labels=False, duplicates="drop")
        med_by_decile = d.groupby("decile")[col].median()
        n_by_decile = d.groupby("decile")[col].count()
        steps_up = sum(med_by_decile.values[i+1] > med_by_decile.values[i] for i in range(len(med_by_decile) - 1))
        print(f"  {h}: median return by decile (low->high TurnScore) = " +
              " | ".join(f"{v:6.2f}%" for v in med_by_decile.values) +
              f"   [{steps_up}/{len(med_by_decile)-1} decile-steps increasing]")
    ranges = nonzero.groupby(pd.qcut(nonzero["TurnScore"], 10, duplicates="drop"))["TurnScore"].agg(["min", "max", "count"])
    print("  decile ranges:\n", ranges.to_string())

    print("\nDone. (no raw data files written)")


if __name__ == "__main__":
    main()
