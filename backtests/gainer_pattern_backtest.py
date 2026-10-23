#!/usr/bin/env python3
"""
"Top-gainer pattern" in the Baizora Tracker list, backtested (2026-10-22).

The pattern (from a study of the 10 biggest 1-day gainers per day, Apr 2025..Oct 2026):
top gainers were mostly high-volatility stocks trading above their 200-day average
but well off their 200-day high. Filter, fixed before testing:
  vol20     20-day daily-return std in the top fifth of the universe that day
  trend     close > 200-day simple average
  pullback  close 15%..50% below the 200-day high
Variants (top 10 each session):
  conv      live rule: BaizConviction
  pattern   stocks passing the filter, by vol20 (most volatile first)
  conv_pat  BaizConviction among filter passers (topped up from conviction if < 10 pass)
  blend     50% conviction percentile + 50% pattern score
            (pattern score = mean of vol20 percentile, trend 0/1, pullback-in-range 0/1)

13-trading-session forward return (the tracker horizon). Prices: yfinance cache
before candles.json's first date, scaled to match on the seam, then candles.json.
Current S&P 500 + Nasdaq-100 members only (survivorship bias), in-sample, no costs.

Usage: python backtests/gainer_pattern_backtest.py
"""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TOP_N, HORIZON = 10, 13


def load_prices():
    c = json.loads((ROOT / "data/candles.json").read_text(encoding="utf-8"))
    latest = json.loads((ROOT / "data/latest.json").read_text(encoding="utf-8"))
    cdates, seam = c["dates"], c["dates"][0]
    cache = {}
    for r in latest["data"]:
        t = r["Ticker"]
        f = ROOT / "data/ohlcv_yfinance_cache" / f"{t}.json"
        if (r.get("InSP500") or r.get("InNASDAQ100")) and len(c["data"].get(t, [])) == len(cdates) and f.exists():
            bars = json.loads(f.read_text(encoding="utf-8"))["bars"]
            if seam in bars and c["data"][t][0]:
                cache[t] = bars
    pre = sorted({d for b in cache.values() for d in b if d < seam})
    pre = [d for d in pre if sum(d in b for b in cache.values()) > 0.9 * len(cache)]
    tickers = sorted(cache)
    H = np.full((len(tickers), len(pre) + len(cdates)), np.nan)
    C = H.copy()
    for k, t in enumerate(tickers):
        bars, scale = cache[t], c["data"][t][0][3] / cache[t][seam]["c"]
        for i, d in enumerate(pre):
            if d in bars:
                H[k, i], C[k, i] = bars[d]["h"] * scale, bars[d]["c"] * scale
        for i, b in enumerate(c["data"][t]):
            if b:
                H[k, len(pre) + i], C[k, len(pre) + i] = b[1], b[3]
    spy = np.array([b[3] for b in c["data"]["SPY"]], float)
    return tickers, pre + cdates, len(pre), H, C, spy


def pct_rank(x):
    out = np.full(len(x), np.nan)
    ok = ~np.isnan(x)
    if ok.sum() > 1:
        out[ok] = x[ok].argsort().argsort() / (ok.sum() - 1)
    return out


def main():
    tickers, dates, off, H, C, spy = load_prices()
    trend = json.loads((ROOT / "data/baiz_score_trend.json").read_text(encoding="utf-8"))
    n_c = len(trend["__dates__"])
    conv = np.array([[np.nan] * (n_c - len(trend[t]["BaizConviction"]))
                     + [np.nan if v is None else v for v in trend[t]["BaizConviction"]] for t in tickers], float)
    ret = np.full_like(C, np.nan)
    ret[:, 1:] = C[:, 1:] / C[:, :-1] - 1
    names = ("conv", "pattern", "conv_pat", "blend")
    res = {k: [] for k in names + ("spy", "univ")}
    npass, sess = [], []
    for ci in range(n_c - HORIZON):
        i = off + ci                         # index into stitched prices
        cv = conv[:, ci]
        vol = np.nanstd(ret[:, i - 19:i + 1], 1)
        sma200 = np.nanmean(C[:, i - 199:i + 1], 1)
        hi200 = np.nanmax(H[:, i - 199:i + 1], 1)
        ok = ~np.isnan(cv) & ~np.isnan(C[:, i]) & ~np.isnan(C[:, i + HORIZON]) & ~np.isnan(vol)
        if ok.sum() < 300:
            continue
        idx = np.where(ok)[0]
        v, c = vol[idx], cv[idx]
        up = (C[idx, i] > sma200[idx]).astype(float)
        dd = C[idx, i] / hi200[idx] - 1
        pull = ((dd <= -0.15) & (dd >= -0.50)).astype(float)
        pv = pct_rank(v)
        passed = (pv >= 0.8) & (up == 1) & (pull == 1)
        tie = np.arange(len(idx))
        fwd = (C[idx, i + HORIZON] / C[idx, i] - 1) * 100
        top = {
            "conv": np.lexsort((tie, -c))[:TOP_N],
            "pattern": np.lexsort((tie, -np.where(passed, v, -np.inf)))[:TOP_N],
            # passers first by conviction, then everyone else by conviction
            "conv_pat": np.lexsort((tie, -c, ~passed))[:TOP_N],
            "blend": np.lexsort((tie, -(0.5 * pct_rank(c) + 0.5 * (pv + up + pull) / 3)))[:TOP_N],
        }
        for k in names:
            res[k].append(fwd[top[k]].mean())
        res["spy"].append((spy[ci + HORIZON] / spy[ci] - 1) * 100)
        res["univ"].append(fwd.mean())
        npass.append(passed.sum())
        sess.append(dates[i])

    a = {k: np.array(v) for k, v in res.items()}
    print(f"sessions={len(sess)}  {sess[0]} .. {sess[-1]}   pattern passers per day: median {np.median(npass):.0f}, "
          f"min {min(npass)}  (days with < 10: {sum(x < 10 for x in npass)})")
    print(f"{'':24}{'mean':>8}{'median':>8}{'>SPY':>8}{'>0':>8}{'worst':>8}{'stdev':>8}")
    lab = {"conv": "Conviction (live)", "pattern": "Pattern only", "conv_pat": "Conviction in pattern",
           "blend": "Blend 50/50", "univ": "Universe (equal wt)", "spy": "SPY"}
    for k in names + ("univ", "spy"):
        x = a[k]
        print(f"{lab[k]:24}{x.mean():8.2f}{np.median(x):8.2f}{(x > a['spy']).mean() * 100:7.0f}%"
              f"{(x > 0).mean() * 100:7.0f}%{x.min():8.1f}{x.std():8.2f}")
    for k in names[1:]:
        diff = a[k] - a["conv"]
        ts = [diff[o::HORIZON].mean() / (diff[o::HORIZON].std(ddof=1) / np.sqrt(len(diff[o::HORIZON])))
              for o in range(HORIZON)]
        print(f"{lab[k]} minus Conviction: mean {diff.mean():+.2f}pp, median {np.median(diff):+.2f}pp, "
              f"ahead {(diff > 0).mean() * 100:.0f}%, non-overlapping t {min(ts):+.2f}..{max(ts):+.2f}")
    for part, sl in zip(("first third", "middle third", "last third"), np.array_split(np.arange(len(sess)), 3)):
        print(f"  {part:13} {sess[sl[0]]}..{sess[sl[-1]]}: " + "  ".join(
            f"{k} {a[k][sl].mean():+.2f}" for k in names + ("spy",)))


if __name__ == "__main__":
    main()
