#!/usr/bin/env python3
"""
Most volatile 20% (1-year) ranked by 25% BaizConviction + 75% 3-month momentum, the
Baizora Tracker rule since 2026-10-23, vs the same group by BaizScore and 25/75 on all
stocks. 13-session forward returns, 239 sessions, current members only, in-sample.
Run from the repo root: python backtests/volatile_2575_backtest.py
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
names = ["c2575", "v20", "v20_2575", "v20_2575u"]
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
        "c2575": np.argsort(-(0.25 * pr(cv) + 0.75 * pr(m3)), kind="stable")[:TOP_N],
        "v20": top_by(pv >= 0.8), "v33": top_by(pv >= 2 / 3),
        "v20_2575": (lambda m: np.where(m)[0][np.argsort(-(0.25 * pr(cv[m]) + 0.75 * pr(m3[m])), kind="stable")[:TOP_N]])(pv >= 0.8),
        "v20_2575u": (lambda m: np.where(m)[0][np.argsort(-(0.25 * pr(cv) + 0.75 * pr(m3))[m], kind="stable")[:TOP_N]])(pv >= 0.8),
    }
    for k in names: res[k].append(fwd[top[k]].mean())
    res["spy"].append((spy[ci + HORIZON] / spy[ci] - 1) * 100); res["univ"].append(fwd.mean())
    hv = pv >= 0.8
    pool += list(zip(sc[hv], fwd[hv]))
a = {k: np.array(v) for k, v in res.items()}
lab = {"c2575": "25/75, all stocks", "v20": "Top-20% vol, by BaizScore (now)",
       "v20_2575": "Top-20% vol, 25/75 (pct in group)", "v20_2575u": "Top-20% vol, 25/75 (pct all)", "univ": "All stocks eq-wt", "spy": "SPY"}
print(f"sessions={len(a['v20'])}")
print(f"{'':28}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'stdev':>7}{'mean/sd':>8}")
for k in names + ["univ", "spy"]:
    x = a[k]; print(f"{lab[k]:28}{x.mean():7.2f}{np.median(x):8.2f}{(x > a['spy']).mean()*100:5.0f}%{x.min():7.1f}{x.std():7.2f}{x.mean()/x.std():8.2f}")
d = a["v20_2575"] - a["v20"]
ts = [d[o::HORIZON].mean() / (d[o::HORIZON].std(ddof=1) / np.sqrt(len(d[o::HORIZON]))) for o in range(HORIZON)]
print(f"Top-20% vol 25/75 minus current (BaizScore): {d.mean():+.2f}pp mean, {np.median(d):+.2f}pp median, t {min(ts):+.2f}..{max(ts):+.2f}")
for part, sl in zip(("first third", "middle third", "last third"), np.array_split(np.arange(len(a["v20"])), 3)):
    print(f"  {part:13}: " + "  ".join(f"{k} {a[k][sl].mean():+.2f}" for k in ["c2575", "v20", "v20_2575", "spy"]))
