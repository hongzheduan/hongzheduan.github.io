"""
One-time backfill of data/baiz_score_trend.json — seeds a trailing ~252-session
(1-year) history of all four Baizora scores (BaizScore/BaizMomentum/BaizPersist/
BaizConviction) per ticker, so the dashboard's score-trend sparklines are populated
immediately instead of growing empty for a year.

Reuses the same cross-sectional-ranking methodology as the backtest scripts
(RSScore/MomentumScore ranked per calendar date across the full universe), then
replays the BaizPersist (trailing 21-session average of BaizScore) / BaizConviction
(sqrt(BaizScore * BaizPersist)) logic chronologically per ticker — identical formulas
to scanner_tiingo.py's _compute_baiz_persist_and_conviction, just run once over history
instead of incrementally day-by-day.

Writes directly to the production data/ directory (this IS the seed data for a real
live feature, not a scratchpad backtest artifact — unlike the other scripts in this
directory, its output is meant to be committed).
"""
import sys
import os
import json
import pandas as pd
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backtests/ -> repo root
sys.path.insert(0, REPO)

from scanner_yfinance import fetch_yfinance_bulk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from baizscore_backtest import load_universe, compute_ticker_frame, BURN_IN  # noqa: E402

TREND_WINDOW = 252
PERSIST_WINDOW = 21
OUT_FILE = os.path.join(REPO, "data", "baiz_score_trend.json")


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
    all_df["BaizMomentum"] = (
        0.40 * rs_norm + 0.35 * all_df["MomentumScore"] + 0.15 * all_df["BreakoutScore"]
        + 0.05 * all_df["TrendScore"] + 0.05 * vp_norm
    ).round().clip(0, 100).astype(int)

    scoreable = all_df[all_df["RowIdx"] >= BURN_IN].copy()
    scoreable = scoreable.sort_values(["Ticker", "Date"])
    print(f"Scoreable observations: {len(scoreable):,}")
    print(f"Date range: {scoreable['Date'].min()} .. {scoreable['Date'].max()}")

    out = {}
    n_tickers = 0
    for ticker, g in scoreable.groupby("Ticker"):
        g = g.sort_values("Date")
        baiz_vals = g["BaizScore"].tolist()
        mom_vals = g["BaizMomentum"].tolist()

        # replay the trailing-PERSIST_WINDOW-session average chronologically, exactly
        # matching _compute_baiz_persist_and_conviction's incremental logic
        persist_vals, conviction_vals = [], []
        window = []
        for score in baiz_vals:
            window.append(float(score))
            window = window[-PERSIST_WINDOW:]
            if len(window) >= PERSIST_WINDOW:
                persist = sum(window) / len(window)
                persist_vals.append(round(persist))
                conviction_vals.append(round((persist * float(score)) ** 0.5))
            else:
                persist_vals.append(None)
                conviction_vals.append(None)

        # keep only the trailing TREND_WINDOW sessions — matches what the live
        # scanner's rolling window will converge to going forward
        out[ticker] = {
            "BaizScore": baiz_vals[-TREND_WINDOW:],
            "BaizMomentum": mom_vals[-TREND_WINDOW:],
            "BaizPersist": persist_vals[-TREND_WINDOW:],
            "BaizConviction": conviction_vals[-TREND_WINDOW:],
        }
        n_tickers += 1

    with open(OUT_FILE, "w") as f:
        json.dump(out, f)

    print(f"\nWrote {OUT_FILE} — {n_tickers} tickers")
    sample = next(iter(out))
    print(f"Sample ({sample}): BaizScore len={len(out[sample]['BaizScore'])}, "
          f"BaizPersist non-null={sum(1 for v in out[sample]['BaizPersist'] if v is not None)}, "
          f"last values: BaizScore={out[sample]['BaizScore'][-1]} "
          f"BaizMomentum={out[sample]['BaizMomentum'][-1]} "
          f"BaizPersist={out[sample]['BaizPersist'][-1]} "
          f"BaizConviction={out[sample]['BaizConviction'][-1]}")
    print("Done.")


if __name__ == "__main__":
    main()
