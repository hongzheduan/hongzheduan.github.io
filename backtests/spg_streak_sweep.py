#!/usr/bin/env python3
"""
SPG Tracker streak-length sweep (2026-10-23): which N in "closed higher N sessions in a row,
then lowest 1-year volatility first, up to 10" did best? N = 0 means no streak filter.
Forward horizon 2 sessions by default (the SPG Tracker's), or pass one, e.g. 13.
Current members only (survivorship), in-sample, no costs.
Run from the repo root: python backtests/spg_streak_sweep.py [horizon]
"""
import sys
sys.path.insert(0, "backtests")
import numpy as np
from gainer_pattern_backtest import load_prices, TOP_N
H_FWD = int(sys.argv[1]) if len(sys.argv) > 1 else 2
tickers, dates, off, H, C, spy = load_prices()
ret = np.full_like(C, np.nan); ret[:, 1:] = C[:, 1:] / C[:, :-1] - 1
NS = list(range(0, 9))
res = {n: [] for n in NS}; sizes = {n: [] for n in NS}; spy_r = []
for ci in range(len(spy) - H_FWD):
    i = off + ci
    ok = ~np.isnan(C[:, i]) & ~np.isnan(C[:, i + H_FWD]) & ~np.isnan(C[:, i - 252])
    idx = np.where(ok)[0]
    fwd = (C[idx, i + H_FWD] / C[idx, i] - 1) * 100
    v1y = np.nanstd(ret[idx, i - 251:i + 1], 1, ddof=1)
    streak = np.zeros(len(idx), int); alive = np.ones(len(idx), bool)
    for k in range(max(NS)):
        alive &= ret[idx, i - k] > 0; streak += alive
    spy_r.append((spy[ci + H_FWD] / spy[ci] - 1) * 100)
    for n in NS:
        r = np.where(streak >= n)[0]
        sizes[n].append(min(len(r), TOP_N))
        res[n].append(fwd[r[np.argsort(v1y[r], kind="stable")[:TOP_N]]].mean() if len(r) else np.nan)
spy_r = np.array(spy_r)
print(f"horizon {H_FWD} sessions, {len(spy_r)} sessions ({dates[off]}..{dates[off + len(spy_r) - 1]})")
print(f"{'N up days':10}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'avg size':>9}{'no list':>8}{'vs SPY':>8}{'t':>12}")
for n in NS:
    x = np.array(res[n]); m = ~np.isnan(x); d = x[m] - spy_r[m]
    ts = [d[o::H_FWD].mean() / (d[o::H_FWD].std(ddof=1) / np.sqrt(len(d[o::H_FWD]))) for o in range(H_FWD)]
    print(f"{n:<10}{x[m].mean():7.2f}{np.median(x[m]):8.2f}{(d > 0).mean()*100:5.0f}%{x[m].min():7.1f}"
          f"{np.mean(sizes[n]):9.1f}{(~m).sum():8d}{d.mean():+8.2f}{min(ts):+6.2f}..{max(ts):+.2f}")
print(f"{'SPY':10}{spy_r.mean():7.2f}{np.median(spy_r):8.2f}")
for part, sl in zip(("first third", "middle third", "last third"), np.array_split(np.arange(len(spy_r)), 3)):
    print(f"  {part:13}: " + "  ".join(f"N{n} {np.nanmean(np.array(res[n])[sl]):+.2f}" for n in NS) + f"  SPY {spy_r[sl].mean():+.2f}")
