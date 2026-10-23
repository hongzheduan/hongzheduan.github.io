#!/usr/bin/env python3
"""
SPG Tracker rule (user, 2026-10-23): stocks whose close rose on each of the last 5 sessions,
then the 10 with the LOWEST 1-year volatility. Compared with the 30-day-volatility version,
the most volatile risers, all risers, the Baizora Tracker 25/75 rule and SPY.
13-session forward returns, current members only (survivorship), in-sample, no costs.
Run from the repo root: python backtests/spg_lowvol_streak_backtest.py
"""
import sys, json
sys.path.insert(0, "backtests")
import numpy as np
from gainer_pattern_backtest import load_prices, ROOT, TOP_N, HORIZON
tickers, dates, off, H, C, spy = load_prices()
trend = json.loads((ROOT / "data/baiz_score_trend.json").read_text(encoding="utf-8"))
n_c = len(trend["__dates__"])
conv = np.array([[np.nan] * (n_c - len(trend[t]["BaizConviction"]))
                 + [np.nan if v is None else v for v in trend[t]["BaizConviction"]] for t in tickers], float)
ret = np.full_like(C, np.nan); ret[:, 1:] = C[:, 1:] / C[:, :-1] - 1
pr = lambda x: np.nan_to_num(x, nan=-np.inf).argsort().argsort() / (len(x) - 1)
STREAK = 5
names = ["low1y", "low30", "high1y", "risers", "c2575"]
res = {k: [] for k in names + ["spy", "univ"]}
counts, used = [], []
for ci in range(len(spy) - HORIZON):
    i = off + ci
    ok = ~np.isnan(C[:, i]) & ~np.isnan(C[:, i + HORIZON]) & ~np.isnan(conv[:, ci])
    idx = np.where(ok)[0]
    fwd = (C[idx, i + HORIZON] / C[idx, i] - 1) * 100
    up = np.all(ret[idx, i - STREAK + 1:i + 1] > 0, 1)
    v1y = np.nanstd(ret[idx, i - 251:i + 1], 1, ddof=1)
    v30 = np.nanstd(ret[idx, i - 29:i + 1], 1, ddof=1)
    r = np.where(up)[0]
    counts.append(len(r))
    if len(r) == 0:
        continue   # no qualifying stock that day: no list
    used.append(ci)
    top = {
        "low1y": r[np.argsort(v1y[r], kind="stable")[:TOP_N]],
        "low30": r[np.argsort(v30[r], kind="stable")[:TOP_N]],
        "high1y": r[np.argsort(-v1y[r], kind="stable")[:TOP_N]],
        "risers": r,
        "c2575": np.argsort(-(0.25 * pr(conv[idx, ci]) + 0.75 * pr(C[idx, i] / C[idx, i - 62])), kind="stable")[:TOP_N],
    }
    for k in names: res[k].append(fwd[top[k]].mean())
    res["spy"].append((spy[ci + HORIZON] / spy[ci] - 1) * 100); res["univ"].append(fwd.mean())
a = {k: np.array(v) for k, v in res.items()}
cnt = np.array(counts)
lab = {"low1y": "5 up days, lowest 1Y vol", "low30": "5 up days, lowest 30d vol", "high1y": "5 up days, highest 1Y vol",
       "risers": "All 5-up-day stocks", "c2575": "Baizora 25/75 (current)", "univ": "All stocks eq-wt", "spy": "SPY"}
print(f"sessions={len(cnt)} ({dates[off]}..{dates[off + len(cnt) - 1]}), with >=1 qualifier: {len(used)}; "
      f"qualifiers per day median {np.median(cnt):.0f}, min {cnt.min()}, max {cnt.max()}, <10 on {(cnt < TOP_N).sum()} days")
print(f"{'':28}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'stdev':>7}{'mean/sd':>8}")
for k in names + ["univ", "spy"]:
    x = a[k]; print(f"{lab[k]:28}{x.mean():7.2f}{np.median(x):8.2f}{(x > a['spy']).mean()*100:5.0f}%{x.min():7.1f}{x.std():7.2f}{x.mean()/x.std():8.2f}")
for base in ("spy", "c2575"):
    d = a["low1y"] - a[base]
    ts = [d[o::HORIZON].mean() / (d[o::HORIZON].std(ddof=1) / np.sqrt(len(d[o::HORIZON]))) for o in range(HORIZON)]
    print(f"low1y minus {base}: {d.mean():+.2f}pp mean, {np.median(d):+.2f}pp median, non-overlapping t {min(ts):+.2f}..{max(ts):+.2f}")
for part, sl in zip(("first third", "middle third", "last third"), np.array_split(np.arange(len(a["spy"])), 3)):
    print(f"  {part:13}: " + "  ".join(f"{k} {a[k][sl].mean():+.2f}" for k in ["low1y", "risers", "c2575", "spy"]))
