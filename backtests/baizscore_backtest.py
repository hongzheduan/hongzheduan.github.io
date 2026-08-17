"""
Baizora Score predictive-power backtest.

Replays the exact BaizScore formula from scanner_tiingo.py (production) across
historical dates, using yfinance OHLCV, then measures forward returns
(1M/3M/6M/9M/1Y — matching the platform's own timeframe windows) conditioned
on BaizScore >= 70 vs the unconditional baseline.

Standalone / one-off — not part of the site, does not touch any production
files or caches.
"""
import sys
import os
import json
import pandas as pd
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backtests/ -> repo root
sys.path.insert(0, REPO)

from scanner_yfinance import fetch_yfinance_bulk  # noqa: E402

OUT_DIR = os.path.dirname(os.path.abspath(__file__))  # backtests/ - logs only, never raw per-row data

TIMEFRAMES = {"2W": 10, "1M": 21, "3M": 63, "6M": 126, "9M": 189, "1Y": 252}
FWD_HORIZONS = {"1M": 21, "3M": 63, "6M": 126, "9M": 189, "1Y": 252}
BURN_IN = 252          # require a genuine 252-day lookback before treating a row as "scoreable"
SCORE_THRESHOLD = 70


def load_universe():
    with open(os.path.join(REPO, "data", "sp500_symbols.txt")) as f:
        sp = [l.strip() for l in f if l.strip()]
    with open(os.path.join(REPO, "data", "nasdaq100_symbols.txt")) as f:
        nd = [l.strip() for l in f if l.strip()]
    tickers = sorted(set(sp) | set(nd))
    return tickers, set(sp), set(nd)


def compute_ticker_frame(ticker, bars):
    if not bars:
        return None
    dates = sorted(bars.keys())
    rows = [{"Date": d, "Close": bars[d]["c"], "Volume": bars[d]["v"]} for d in dates]
    df = pd.DataFrame(rows)
    df = df[(df["Volume"] >= 10000) & (df["Close"] > 0)].reset_index(drop=True)
    if len(df) < 30:
        return None

    df["MA21_PRICE"] = df["Close"].rolling(21).mean()
    df["MA21_VOL"] = df["Volume"].rolling(21).mean()
    df["PriceChange1D"] = df["Close"].pct_change() * 100
    df["VolumeChange1D"] = df["Volume"].pct_change() * 100
    df["PriceVsMA21"] = df["Close"] / df["MA21_PRICE"]
    df["VolumeVsMA21"] = df["Volume"] / df["MA21_VOL"]

    for label, days in TIMEFRAMES.items():
        start = df["Close"].shift(days - 1)
        start_filled = start.fillna(df["Close"].iloc[0])
        df[f"{label}PriceChange"] = (df["Close"] / start_filled - 1) * 100

    pv_ma = df["PriceVsMA21"].fillna(1.0)
    vv_ma = df["VolumeVsMA21"].fillna(1.0)
    pc_1d = df["PriceChange1D"].fillna(0.0)

    term1 = ((pv_ma - 1) * 200).clip(lower=0, upper=33)
    term2 = (pc_1d * 3).clip(lower=0, upper=33)
    term3 = ((vv_ma - 1) * 25).clip(lower=0, upper=34)
    df["BreakoutScore"] = (term1 + term2 + term3).clip(0, 100).round()

    p_dir = np.sign(pc_1d)
    df["VolPressureScore"] = ((vv_ma - 1) * p_dir * 100).clip(-100, 100).round()

    pc_cols = [f"{l}PriceChange" for l in ["2W", "1M", "3M", "6M", "9M", "1Y"]]
    pcf = df[pc_cols].fillna(0.0)
    df["TrendScore"] = ((pcf > 0).sum(axis=1) / 6 * 100).round()

    df["_RawRS"] = (
        0.40 * pcf["3MPriceChange"] + 0.20 * pcf["6MPriceChange"]
        + 0.20 * pcf["9MPriceChange"] + 0.20 * pcf["1YPriceChange"]
    )
    df["_RawMomentum"] = (
        0.35 * pcf["1MPriceChange"] + 0.25 * pcf["3MPriceChange"]
        + 0.20 * pcf["6MPriceChange"] + 0.20 * pcf["1YPriceChange"]
    )

    # forward returns (trading-day shifts on this ticker's own row sequence)
    for label, days in FWD_HORIZONS.items():
        df[f"Fwd{label}"] = (df["Close"].shift(-days) / df["Close"] - 1) * 100

    df["Ticker"] = ticker
    df["RowIdx"] = np.arange(len(df))
    return df


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
    all_df["InSP500"] = all_df["Ticker"].isin(sp_set)
    all_df["InNASDAQ100"] = all_df["Ticker"].isin(nd_set)

    # cross-sectional ranks, computed per calendar Date across ALL tickers with a row that day
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

    # only rows with a genuine full lookback (skip each ticker's first BURN_IN rows)
    scoreable = all_df[all_df["RowIdx"] >= BURN_IN].copy()
    print(f"Scoreable observations (post burn-in): {len(scoreable):,}")
    print(f"Date range: {scoreable['Date'].min()} .. {scoreable['Date'].max()}")

    fwd_cols = [f"Fwd{l}" for l in FWD_HORIZONS]
    keep_cols = ["Date", "Ticker", "InSP500", "InNASDAQ100", "Close",
                 "BaizScore", "RSScore", "MomentumScore", "BreakoutScore", "TrendScore", "VolPressureScore",
                 "TurnScore"] + fwd_cols
    keep_cols = [c for c in keep_cols if c in scoreable.columns]
    export_df = scoreable[keep_cols].rename(columns={"Close": "Price"})
    export_df.to_csv(os.path.join(OUT_DIR, "baiz_score_history.csv"), index=False)
    print(f"Wrote baiz_score_history.csv ({len(export_df):,} rows)")

    high = scoreable[scoreable["BaizScore"] >= SCORE_THRESHOLD]
    print(f"BaizScore >= {SCORE_THRESHOLD} observations: {len(high):,} "
          f"({len(high) / len(scoreable) * 100:.2f}% of all scoreable obs)")

    summary_rows = []
    for label in FWD_HORIZONS:
        col = f"Fwd{label}"
        base = scoreable[col].dropna()
        hi = high[col].dropna()
        summary_rows.append({
            "Horizon": label,
            "Baseline_N": len(base),
            "Baseline_MeanRet%": round(float(base.mean()), 3) if len(base) else None,
            "Baseline_MedianRet%": round(float(base.median()), 3) if len(base) else None,
            "Baseline_PctPositive": round(float((base > 0).mean() * 100), 2) if len(base) else None,
            "High_N": len(hi),
            "High_MeanRet%": round(float(hi.mean()), 3) if len(hi) else None,
            "High_MedianRet%": round(float(hi.median()), 3) if len(hi) else None,
            "High_PctPositive": round(float((hi > 0).mean() * 100), 2) if len(hi) else None,
        })
        if len(hi):
            summary_rows[-1]["Edge_pp"] = round(summary_rows[-1]["High_MeanRet%"] - summary_rows[-1]["Baseline_MeanRet%"], 3)
        else:
            summary_rows[-1]["Edge_pp"] = None

    summary_df = pd.DataFrame(summary_rows)
    summary_df.to_csv(os.path.join(OUT_DIR, "baiz_score_summary.csv"), index=False)
    print("\n=== SUMMARY (BaizScore >= 70 vs baseline) ===")
    print(summary_df.to_string(index=False))

    with open(os.path.join(OUT_DIR, "baiz_score_summary.json"), "w") as f:
        json.dump({
            "threshold": SCORE_THRESHOLD,
            "total_scoreable_obs": int(len(scoreable)),
            "high_obs": int(len(high)),
            "date_range": [str(scoreable["Date"].min()), str(scoreable["Date"].max())],
            "summary": summary_rows,
        }, f, indent=2)
    print("\nDone.")


if __name__ == "__main__":
    main()
