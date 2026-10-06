"""
Pattern-breakout backtest (base breakout on volume).

Signal on day t for a ticker:
  base     : the prior BASE_LEN closes (t-BASE_LEN .. t-1) stayed within a band,
             max/min - 1 <= MAX_RANGE
  break    : close[t] > max close of that base
  volume   : volume[t] >= VOL_MULT x 21-day average volume
  trend    : close[t] > SMA200 and SMA50 > SMA200
  fresh    : no other signal for this ticker in the prior 10 trading days

Forward returns from close[t] are compared with the median forward return of
the whole universe on the same date (excess), so market drift is netted out.
"failed" = closed back below the base high at any point in the next 10 days.

Caveats: universe is TODAY's S&P 500 + Nasdaq-100 (survivorship bias flatters
everything, signal and baseline alike). Median is the headline number.
Standalone. No raw per-row data is persisted, summary only.
"""
import sys
import os
import itertools
import pandas as pd
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from scanner_yfinance import fetch_yfinance_bulk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from baizscore_backtest import load_universe  # noqa: E402

FWD = {"1M": 21, "3M": 63, "6M": 126}
FAIL_DAYS = 10
FRESH_GAP = 10
BASE_LENS = [30, 60]
MAX_RANGES = [0.10, 0.15, 0.20]
VOL_MULTS = [1.5, 2.0]


def frame(ticker, bars):
    if not bars:
        return None
    d = sorted(bars)
    df = pd.DataFrame({"Date": d,
                       "Close": [bars[x]["c"] for x in d],
                       "Volume": [bars[x]["v"] for x in d]})
    df = df[(df.Close > 0) & (df.Volume > 0)].reset_index(drop=True)
    if len(df) < 300:
        return None
    df["Ticker"] = ticker
    df["SMA50"] = df.Close.rolling(50).mean()
    df["SMA200"] = df.Close.rolling(200).mean()
    df["VolRatio"] = df.Volume / df.Volume.rolling(21).mean()
    for n in BASE_LENS:
        prev = df.Close.shift(1)
        df[f"Hi{n}"] = prev.rolling(n).max()
        df[f"Lo{n}"] = prev.rolling(n).min()
    for k, h in FWD.items():
        df[f"F{k}"] = (df.Close.shift(-h) / df.Close - 1) * 100
    # min close over next FAIL_DAYS (for failure check)
    fut = pd.concat([df.Close.shift(-i) for i in range(1, FAIL_DAYS + 1)], axis=1)
    df["FutMin"] = fut.min(axis=1, skipna=False)
    return df.iloc[200:]  # need SMA200


def main():
    tickers, _, _ = load_universe()
    print(f"Universe: {len(tickers)} tickers")
    bars = fetch_yfinance_bulk(tickers, period="5y")
    frames = [f for f in (frame(t, bars.get(t)) for t in tickers) if f is not None]
    df = pd.concat(frames, ignore_index=True)
    print(f"Frames: {len(frames)} tickers, {len(df):,} ticker-days, "
          f"{df.Date.min()} .. {df.Date.max()}")

    for k in FWD:
        df[f"X{k}"] = df[f"F{k}"] - df.groupby("Date")[f"F{k}"].transform("median")

    print("\nBaseline (all ticker-days): median fwd return "
          + ", ".join(f"{k} {df[f'F{k}'].median():+.2f}%" for k in FWD))
    trend = (df.Close > df.SMA200) & (df.SMA50 > df.SMA200)
    print("Baseline (uptrend days only): median excess "
          + ", ".join(f"{k} {df.loc[trend, f'X{k}'].median():+.2f}" for k in FWD))

    print(f"\n{'base':>4} {'rng':>4} {'vol':>4} {'n':>5} | "
          + " | ".join(f"{k} med  exc  win%" for k in FWD) + " | fail%")
    for n, r, v in itertools.product(BASE_LENS, MAX_RANGES, VOL_MULTS):
        sig = (trend
               & (df[f"Hi{n}"] / df[f"Lo{n}"] - 1 <= r)
               & (df.Close > df[f"Hi{n}"])
               & (df.VolRatio >= v))
        # freshness: drop signals with another signal for same ticker in prior FRESH_GAP rows
        s = sig.astype(int)
        prior = s.groupby(df.Ticker).transform(
            lambda x: x.shift(1).rolling(FRESH_GAP, min_periods=1).sum()).fillna(0)
        sub = df[sig & (prior == 0)]
        if len(sub) < 20:
            print(f"{n:>4} {r:>4.2f} {v:>4.1f} {len(sub):>5} | too few")
            continue
        parts = []
        for k in FWD:
            s_ = sub[f"F{k}"].dropna()
            x_ = sub[f"X{k}"].dropna()
            parts.append(f"{k} {s_.median():+5.1f} {x_.median():+5.1f} {(s_ > 0).mean()*100:4.0f}")
        f_ = sub.dropna(subset=["FutMin"])
        fail = (f_.FutMin < f_[f"Hi{n}"]).mean() * 100
        print(f"{n:>4} {r:>4.2f} {v:>4.1f} {len(sub):>5} | " + " | ".join(parts) + f" | {fail:4.0f}")


if __name__ == "__main__":
    main()
