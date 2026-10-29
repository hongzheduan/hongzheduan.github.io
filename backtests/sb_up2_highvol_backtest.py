#!/usr/bin/env python3
"""
SB Tracker rule (user, 2026-10-28): stocks whose close rose on each of the last 2 sessions, then the 10
with the HIGHEST 1-year volatility. Compared with the 30-day-volatility version, the lowest-volatility
version, all 2-up-day stocks, the SPG rule (top 10 by 3-month change) and SPY, at 2- and 7-session
forward returns. Current members only (survivorship), in-sample, no costs.
Run from the repo root: python backtests/sb_up2_highvol_backtest.py
"""
import sys
sys.path.insert(0, "backtests")
import numpy as np
from gainer_pattern_backtest import load_prices, TOP_N

tickers, dates, off, H, C, spy = load_prices()
ret = np.full_like(C, np.nan); ret[:, 1:] = C[:, 1:] / C[:, :-1] - 1
STREAK = 2
lab = {"hi1y": "2 up days, highest 1Y vol (user)", "hi30": "2 up days, highest 30d vol", "lo1y": "2 up days, lowest 1Y vol",
       "all": "All 2-up-day stocks", "mom": "Top 10 by 3M change (SPG)", "spy": "SPY"}
for FWD in (2, 7):
    res = {k: [] for k in lab}
    for ci in range(len(spy) - FWD):
        i = off + ci
        ok = ~np.isnan(C[:, i]) & ~np.isnan(C[:, i + FWD]) & ~np.isnan(C[:, i - 252])
        idx = np.where(ok)[0]
        fwd = (C[idx, i + FWD] / C[idx, i] - 1) * 100
        up = np.all(ret[idx, i - STREAK + 1:i + 1] > 0, 1)
        v1y = np.nanstd(ret[idx, i - 251:i + 1], 1, ddof=1)
        v30 = np.nanstd(ret[idx, i - 29:i + 1], 1, ddof=1)
        r = np.where(up)[0]
        res["hi1y"].append(fwd[r[np.argsort(-v1y[r], kind="stable")[:TOP_N]]].mean())
        res["hi30"].append(fwd[r[np.argsort(-v30[r], kind="stable")[:TOP_N]]].mean())
        res["lo1y"].append(fwd[r[np.argsort(v1y[r], kind="stable")[:TOP_N]]].mean())
        res["all"].append(fwd[r].mean())
        res["mom"].append(fwd[np.argsort(-(C[idx, i] / C[idx, i - 63]), kind="stable")[:TOP_N]].mean())
        res["spy"].append((spy[ci + FWD] / spy[ci] - 1) * 100)
    a = {k: np.array(v) for k, v in res.items()}; s = a["spy"]; h = len(s) // 2
    print(f"\nhorizon {FWD} sessions, {len(s)} sessions ({dates[off]}..{dates[off + len(s) - 1]})")
    print(f"{'rule':34}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'H1 vsSPY':>9}{'H2 vsSPY':>9}{'t(min)':>8}")
    for k in lab:
        x = a[k]; d = x - s
        ts = [d[o::FWD].mean() / (d[o::FWD].std(ddof=1) / np.sqrt(len(d[o::FWD]))) for o in range(FWD)] if k != "spy" else [np.nan]
        print(f"{lab[k]:34}{x.mean():7.2f}{np.median(x):8.2f}{(x > s).mean()*100:5.0f}%{x.min():7.1f}"
              f"{d[:h].mean():+9.2f}{d[h:].mean():+9.2f}{min(ts):+8.2f}")
