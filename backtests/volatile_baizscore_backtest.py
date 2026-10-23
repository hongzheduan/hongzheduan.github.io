#!/usr/bin/env python3
"""
Volatility filter + BaizScore ranking for the Baizora Tracker (2026-10-23, shipped).
Keep the most volatile 20% by 1-year volatility, take the top 10 by BaizScore. Compared
with the previous mix, other filter sizes and BaizConviction, 13-session forward
returns, 239 sessions; also the share of volatile stocks that rose, by BaizScore band.
Run from the repo root: python backtests/volatile_baizscore_backtest.py
"""
import sys, json
sys.path.insert(0, "backtests")
import numpy as np
from gainer_pattern_backtest import load_prices, ROOT, TOP_N, HORIZON
tickers, dates, off, H, C, spy = load_prices()
trend = json.loads((ROOT / "data/baiz_score_trend.json").read_text(encoding="utf-8"))
n_c = len(trend["__dates__"])
def col(name):
    return np.array([[np.nan] * (n_c - len(trend[t][name])) + [np.nan if v is None else v for v in trend[t][name]] for t in tickers], float)
conv, score = col("BaizConviction"), col("BaizScore")
ret = np.full_like(C, np.nan); ret[:, 1:] = C[:, 1:] / C[:, :-1] - 1
pr = lambda x: np.nan_to_num(x, nan=-np.inf).argsort().argsort() / (len(x) - 1)
names = ["cur", "v20", "v33", "v20_conv", "allscore"]
res = {k: [] for k in names + ["spy", "univ"]}
pool = []   # (score, fwd) for every high-vol stock-day, for the hit-rate table
for ci in range(n_c - HORIZON):
    i = off + ci
    ok = ~np.isnan(conv[:, ci]) & ~np.isnan(score[:, ci]) & ~np.isnan(C[:, i]) & ~np.isnan(C[:, i + HORIZON])
    idx = np.where(ok)[0]
    fwd = (C[idx, i + HORIZON] / C[idx, i] - 1) * 100
    v1y = np.nanstd(ret[idx, i - 250:i + 1], 1)
    sc, cv, m3 = score[idx, ci], conv[idx, ci], C[idx, i] / C[idx, i - 62]
    pv = pr(v1y)
    tie = np.arange(len(idx))
    def top_by(mask):  # BaizScore, then conviction, among mask
        return np.lexsort((tie, -cv, -sc, ~mask))[:TOP_N]
    top = {
        "cur": np.argsort(-(0.125 * pr(cv) + 0.375 * pr(m3) + 0.5 * pv), kind="stable")[:TOP_N],
        "v20": top_by(pv >= 0.8), "v33": top_by(pv >= 2 / 3),
        "v20_conv": np.lexsort((tie, -cv, ~(pv >= 0.8)))[:TOP_N],
        "allscore": top_by(np.ones(len(idx), bool)),
    }
    for k in names: res[k].append(fwd[top[k]].mean())
    res["spy"].append((spy[ci + HORIZON] / spy[ci] - 1) * 100); res["univ"].append(fwd.mean())
    hv = pv >= 0.8
    pool += list(zip(sc[hv], fwd[hv]))
a = {k: np.array(v) for k, v in res.items()}
lab = {"cur": "Current (50% 1Y vol mix)", "v20": "Top-20% vol, by BaizScore", "v33": "Top-33% vol, by BaizScore",
       "v20_conv": "Top-20% vol, by Conviction", "allscore": "All stocks, by BaizScore", "univ": "All stocks eq-wt", "spy": "SPY"}
print(f"sessions={len(a['cur'])}")
print(f"{'':28}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'stdev':>7}{'mean/sd':>8}")
for k in names + ["univ", "spy"]:
    x = a[k]; print(f"{lab[k]:28}{x.mean():7.2f}{np.median(x):8.2f}{(x > a['spy']).mean()*100:5.0f}%{x.min():7.1f}{x.std():7.2f}{x.mean()/x.std():8.2f}")
d = a["v20"] - a["cur"]
ts = [d[o::HORIZON].mean() / (d[o::HORIZON].std(ddof=1) / np.sqrt(len(d[o::HORIZON]))) for o in range(HORIZON)]
print(f"Top-20% vol by BaizScore minus current: {d.mean():+.2f}pp mean, {np.median(d):+.2f}pp median, t {min(ts):+.2f}..{max(ts):+.2f}")
for part, sl in zip(("first third", "middle third", "last third"), np.array_split(np.arange(len(a["cur"])), 3)):
    print(f"  {part:13}: " + "  ".join(f"{k} {a[k][sl].mean():+.2f}" for k in ["cur", "v20", "allscore", "spy"]))
p = np.array(pool)
print("\nHigh-volatility stocks (top 20% by 1Y vol): share up after 13 sessions, by BaizScore")
for lo, hi in ((0, 40), (40, 55), (55, 70), (70, 80), (80, 90), (90, 101)):
    m = (p[:, 0] >= lo) & (p[:, 0] < hi)
    if m.sum(): print(f"  BaizScore {lo:>3}-{min(hi,100):>3}: up {np.mean(p[m,1] > 0)*100:4.0f}%   median {np.median(p[m,1]):+5.1f}%   n={m.sum()}")
