"""
Flag-breakout backtest (sharp run, short tight pause, break on volume), e.g. ALAB 2026-10-06.

Signal on day t:
  pole   : close[t-L-1] >= (1 + POLE) x min close of the 21 days ending t-L-1
  flag   : prior L closes (t-L .. t-1) within max/min - 1 <= RANGE
  break  : close[t] > flag high, volume[t] >= VOL x 21d avg
  trend  : close > SMA200, SMA50 > SMA200; fresh = no signal in prior 10 days
Excess = fwd return minus same-date universe median. "fail" = closed below flag
high within 10 days. Survivorship-biased universe (today's constituents).
Standalone, summary only.
"""
import os, sys, itertools
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pattern_breakout_backtest import fetch_yfinance_bulk, load_universe, FWD, FAIL_DAYS, FRESH_GAP  # noqa: E402

LENS, RANGES, POLES, VOLS = [8, 10, 15], [0.06, 0.08, 0.10], [0.15, 0.25], [1.3, 1.5]


def frame(t, bars):
    if not bars:
        return None
    d = sorted(bars)
    df = pd.DataFrame({"Date": d, "Close": [bars[x]["c"] for x in d], "Volume": [bars[x]["v"] for x in d]})
    df = df[(df.Close > 0) & (df.Volume > 0)].reset_index(drop=True)
    if len(df) < 300:
        return None
    df["Ticker"] = t
    df["SMA50"], df["SMA200"] = df.Close.rolling(50).mean(), df.Close.rolling(200).mean()
    df["VolRatio"] = df.Volume / df.Volume.rolling(21).mean()
    prev = df.Close.shift(1)
    for L in LENS:
        df[f"Hi{L}"], df[f"Lo{L}"] = prev.rolling(L).max(), prev.rolling(L).min()
        pe = df.Close.shift(L + 1)
        df[f"Pole{L}"] = pe / pe.rolling(21).min() - 1
    for k, h in FWD.items():
        df[f"F{k}"] = (df.Close.shift(-h) / df.Close - 1) * 100
    df["FutMin"] = pd.concat([df.Close.shift(-i) for i in range(1, FAIL_DAYS + 1)], axis=1).min(axis=1, skipna=False)
    return df.iloc[200:]


def main():
    tickers, _, _ = load_universe()
    bars = fetch_yfinance_bulk(tickers, period="5y")
    df = pd.concat([f for f in (frame(t, bars.get(t)) for t in tickers) if f is not None], ignore_index=True)
    for k in FWD:
        df[f"X{k}"] = df[f"F{k}"] - df.groupby("Date")[f"F{k}"].transform("median")
    trend = (df.Close > df.SMA200) & (df.SMA50 > df.SMA200)
    print(f"{len(df):,} ticker-days {df.Date.min()}..{df.Date.max()}")
    print(f"{'L':>3} {'rng':>4} {'pole':>4} {'vol':>3} {'n':>5} | " + " | ".join(f"{k} med  exc win%" for k in FWD) + " | fail%")
    for L, r, p, v in itertools.product(LENS, RANGES, POLES, VOLS):
        sig = trend & (df[f"Hi{L}"] / df[f"Lo{L}"] - 1 <= r) & (df.Close > df[f"Hi{L}"]) & (df[f"Pole{L}"] >= p) & (df.VolRatio >= v)
        prior = sig.astype(int).groupby(df.Ticker).transform(lambda x: x.shift(1).rolling(FRESH_GAP, min_periods=1).sum()).fillna(0)
        sub = df[sig & (prior == 0)]
        if len(sub) < 20:
            print(f"{L:>3} {r:>4.2f} {p:>4.2f} {v:>3} {len(sub):>5} | too few")
            continue
        parts = [f"{k} {sub[f'F{k}'].median():+5.1f} {sub[f'X{k}'].median():+5.1f} {(sub[f'F{k}'].dropna() > 0).mean()*100:3.0f}" for k in FWD]
        f_ = sub.dropna(subset=["FutMin"])
        print(f"{L:>3} {r:>4.2f} {p:>4.2f} {v:>3} {len(sub):>5} | " + " | ".join(parts) + f" | {(f_.FutMin < f_[f'Hi{L}']).mean()*100:4.0f}")


if __name__ == "__main__":
    main()
