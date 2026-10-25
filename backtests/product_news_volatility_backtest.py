#!/usr/bin/env python3
"""
SB Tracker: news shortlist, then most volatile first (user, 2026-10-24).

User rule: use the product-news rule (launch headline in the last WINDOW sessions, ranked by
outlets, then volume vs 21-day average) to narrow to the top SHORTLIST, then rank that
shortlist by volatility, most volatile first, and list the top 10. The shortlist never binds
in practice (20-68 stocks qualified per day, Sep 9..Oct 23). Volatility = annualized stdev of
daily close-to-close returns over 252 sessions (same as the SPG Tracker), and a 21-session
(30-day) version for comparison. 6-session forward returns, like the live SB Tracker.
Same caveats as product_news_backtest.py: headline history is sparse before September,
current members only, no costs, very few sessions.

Run from the repo root: python backtests/product_news_volatility_backtest.py [horizon] [start date]
"""
import sys, json, bisect
sys.path.insert(0, "backtests")
import numpy as np
from big_gain_7d_study import load, ROOT

FWD = int(sys.argv[1]) if len(sys.argv) > 1 else 6
START = sys.argv[2] if len(sys.argv) > 2 else "2026-08-01"
WINDOW, TOP_N, SHORTLIST = 3, 10, 100
tickers, dates, off, O, Hh, L, C, V = load()
tix = {t: k for k, t in enumerate(tickers)}
c = json.loads((ROOT / "data/candles.json").read_text(encoding="utf-8"))
spy = np.r_[np.full(off, np.nan), [b[3] for b in c["data"]["SPY"]]]
news = json.loads((ROOT / "data/product_news.json").read_text(encoding="utf-8"))["items"]
avg21 = np.full_like(V, np.nan)
for j in range(21, V.shape[1]):
    avg21[:, j] = np.nanmean(V[:, j - 21:j], 1)
R = np.full_like(C, np.nan)
R[:, 1:] = C[:, 1:] / C[:, :-1] - 1


def vol(k, d, n):
    x = R[k, d - n + 1:d + 1]
    x = x[~np.isnan(x)]
    return x.std(ddof=1) * np.sqrt(252) * 100 if len(x) > 0.8 * n else np.nan


variants = ["current: by outlets", "most volatile, 1Y", "most volatile, 30D", "least volatile, 1Y"]
res = {v: [] for v in variants}
size = {v: [] for v in variants}
picks_vol = {v: [] for v in variants}
spy_r, univ, qual = [], [], []
for d in range(bisect.bisect_left(dates, START), len(dates) - FWD):
    lo, hi = dates[d - WINDOW], dates[d]
    agg = {}
    for it in news:
        if lo < it["date"] <= hi and it["ticker"] in tix:
            agg.setdefault(tix[it["ticker"]], set()).add(it["source"] or it["title"])
    fwd = (C[:, d + FWD] / C[:, d] - 1) * 100
    spy_r.append((spy[d + FWD] / spy[d] - 1) * 100)
    univ.append(np.nanmean(fwd))
    rows = [(k, len(s), V[k, d] / avg21[k, d], vol(k, d, 252), vol(k, d, 21))
            for k, s in agg.items() if not np.isnan(fwd[k])]
    rows.sort(key=lambda x: (-x[1], -np.nan_to_num(x[2])))
    short = rows[:SHORTLIST]
    qual.append(len(short))
    for v in variants:
        if v.startswith("current"):
            r = short
        else:
            col = 3 if "1Y" in v else 4
            sign = 1 if v.startswith("least") else -1
            r = sorted([x for x in short if not np.isnan(x[col])], key=lambda x: sign * x[col])
        pick = [x[0] for x in r[:TOP_N]]
        size[v].append(len(pick))
        res[v].append(fwd[pick].mean() if pick else np.nan)
        picks_vol[v] += [x[3] for x in r[:TOP_N] if not np.isnan(x[3])]
spy_r, univ = np.array(spy_r), np.array(univ)
print(f"horizon {FWD}, {len(spy_r)} sessions from {START}, {len(news)} headlines on file, "
      f"shortlist size avg {np.mean(qual):.0f} (max {max(qual)})")
print(f"{'rule':22}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'best':>7}{'stdev':>7}{'avg 1Y vol':>11}{'vs SPY':>8}")
for v in variants:
    x = np.array(res[v])
    m = ~np.isnan(x)
    dd = x[m] - spy_r[m]
    print(f"{v:22}{x[m].mean():7.2f}{np.median(x[m]):8.2f}{(dd > 0).mean() * 100:5.0f}%{x[m].min():7.1f}{x[m].max():7.1f}"
          f"{x[m].std():7.2f}{np.mean(picks_vol[v]):10.0f}%{dd.mean():+8.2f}")
print(f"{'All stocks eq-wt':22}{univ.mean():7.2f}{np.median(univ):8.2f}")
print(f"{'SPY':22}{spy_r.mean():7.2f}{np.median(spy_r):8.2f}")
x1, x0 = np.array(res["most volatile, 1Y"]), np.array(res["current: by outlets"])
dd = x1 - x0
m = ~np.isnan(dd)
ts = [dd[m][o::FWD].mean() / (dd[m][o::FWD].std(ddof=1) / np.sqrt(len(dd[m][o::FWD]))) for o in range(FWD)]
print(f"most volatile 1Y minus current: {dd[m].mean():+.2f}pp mean, t {min(ts):+.2f}..{max(ts):+.2f} "
      f"({len(dd[m][::FWD])} non-overlapping periods)")
for part, sl in zip(("first half", "second half"), np.array_split(np.arange(len(spy_r)), 2)):
    print(f"  {part:11}: " + "  ".join(f"{v.split(':')[0]} {np.nanmean(np.array(res[v])[sl]):+.2f}" for v in variants)
          + f"  SPY {spy_r[sl].mean():+.2f}")
