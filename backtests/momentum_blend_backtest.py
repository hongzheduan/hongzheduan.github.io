#!/usr/bin/env python3
"""
BaizConviction vs plain momentum vs 50/50 blends, Baizora Tracker top 10 (2026-10-22).

The user asked whether BaizConviction is the best ranking, then to add plain
momentum to it (tracker ranking only; the BaizConviction score is unchanged).
13-trading-session forward returns, 239 sessions 2025-10-22..2026-10-05, current
S&P 500 + Nasdaq-100 members only (survivorship bias), in-sample, no costs.
Result: conviction + 3M momentum 50/50 (shipped) +0.70pp mean / +0.60pp median vs
conviction alone, risk-adjusted 0.48 vs 0.37; not statistically significant.

Run from the repo root: python backtests/momentum_blend_backtest.py
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
rng = np.random.default_rng(0)
names = ["conv", "mom63", "mom12_1", "conv_m3", "conv_m12", "random"]
res = {k: [] for k in names + ["spy", "univ"]}
for ci in range(n_c - HORIZON):
    i = off + ci
    if i < 252: continue
    ok = ~np.isnan(conv[:, ci]) & ~np.isnan(C[:, i]) & ~np.isnan(C[:, i + HORIZON]) & ~np.isnan(C[:, i - 252])
    idx = np.where(ok)[0]
    fwd = (C[idx, i + HORIZON] / C[idx, i] - 1) * 100
    sig = {
        "conv": conv[idx, ci], "score": score[idx, ci],
        "mom63": C[idx, i] / C[idx, i - 63], "mom126": C[idx, i] / C[idx, i - 126],
        "mom12_1": C[idx, i - 21] / C[idx, i - 252],
        "lowvol": -np.nanstd(ret[idx, i - 62:i + 1], 1),
    }
    pr = lambda x: np.nan_to_num(x, nan=-np.inf).argsort().argsort() / (len(x) - 1)
    sig["conv_m3"] = 0.5 * pr(sig["conv"]) + 0.5 * pr(sig["mom63"])
    sig["conv_m12"] = 0.5 * pr(sig["conv"]) + 0.5 * pr(sig["mom12_1"])
    sig = {k: v for k, v in sig.items() if k in names}
    for k, s in sig.items():
        res[k].append(fwd[np.argsort(-np.nan_to_num(s, nan=-np.inf), kind="stable")[:TOP_N]].mean())
    res["random"].append(np.mean([fwd[rng.choice(len(idx), TOP_N, replace=False)].mean() for _ in range(200)]))
    res["spy"].append((spy[ci + HORIZON] / spy[ci] - 1) * 100); res["univ"].append(fwd.mean())
a = {k: np.array(v) for k, v in res.items()}
print(f"sessions={len(a['conv'])}")
print(f"{'':22}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'stdev':>7}{'mean/sd':>8}")
lab = {"conv": "BaizConviction", "score": "BaizScore", "mom63": "3M momentum", "mom126": "6M momentum",
       "mom12_1": "12-1M momentum", "conv_m3": "Conv + 3M mom 50/50", "conv_m12": "Conv + 12-1M 50/50", "lowvol": "Lowest volatility", "random": "Random 10 (avg)", "univ": "All stocks eq-wt", "spy": "SPY"}
for k in names + ["univ", "spy"]:
    x = a[k]; print(f"{lab[k]:22}{x.mean():7.2f}{np.median(x):8.2f}{(x > a['spy']).mean()*100:5.0f}%{x.min():7.1f}{x.std():7.2f}{x.mean()/x.std():8.2f}")
for k in ["conv_m3", "conv_m12"]:
    d = a[k] - a["conv"]
    ts = [d[o::HORIZON].mean() / (d[o::HORIZON].std(ddof=1) / np.sqrt(len(d[o::HORIZON]))) for o in range(HORIZON)]
    print(f"{lab[k]} minus Conviction: {d.mean():+.2f}pp mean, {np.median(d):+.2f}pp median, t {min(ts):+.2f}..{max(ts):+.2f}")

for part, sl in zip(("first third", "middle third", "last third"), np.array_split(np.arange(len(a["conv"])), 3)):
    print(f"  {part:13}: " + "  ".join(f"{k} {a[k][sl].mean():+.2f}" for k in ["conv", "mom63", "conv_m3", "conv_m12", "spy"]))
