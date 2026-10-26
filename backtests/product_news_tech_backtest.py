#!/usr/bin/env python3
"""
SB Tracker: product-news rule limited to the Technology sector (user, 2026-10-25).

User rule: same as the live SB Tracker (launch headline in the last WINDOW sessions, ranked by
distinct outlets, then volume vs 21-day average, top 10), but only stocks whose scanner Sector
is "Technology". Compared with the all-sector rule, 7-session forward returns like the live
tracker. Sectors are today's labels from latest.json. Same caveats as product_news_backtest.py:
headline history is sparse before September, current members only, no costs, very few sessions.

Result (52 sessions from 2026-08-01, 7-session returns): Technology only +0.52% mean / +0.90% median,
ahead of SPY 54%, worst -10.9%, avg 6.7 stocks; all sectors -0.18%; all except Technology +0.09%;
all Technology stocks equal-weight +0.06%; SPY -0.00%. Tech minus live +0.70pp, t -0.27..+1.69,
8 non-overlapping periods: noise-level.

2-session returns (user, 2026-10-25, `... 2`; 57 sessions): Technology only -0.04% mean / +0.24%
median, ahead of SPY 58%, worst -6.3%, avg 7.0 stocks; all sectors -0.11%; all except Technology +0.02%;
all Technology eq-wt +0.03%; SPY +0.00%. Tech minus live +0.07pp, t +0.12..+0.26, 29 periods: no edge.

21-session (1 month) returns for the Custom Tracker (user, 2026-10-25, `... 21`; 38 sessions):
Technology only +2.04% mean / +2.44% median, ahead of SPY 63%, worst -8.3%, avg 5.9 stocks; all sectors
-0.84%; all except Technology -1.69%; all Technology eq-wt +0.99%; SPY +0.22%. Only ~2 non-overlapping
periods (t -0.62..+3.28): far too little data to judge.

Run from the repo root: python backtests/product_news_tech_backtest.py [horizon] [start date]
"""
import sys, json, bisect
sys.path.insert(0, "backtests")
import numpy as np
from big_gain_7d_study import load, ROOT

FWD = int(sys.argv[1]) if len(sys.argv) > 1 else 7
START = sys.argv[2] if len(sys.argv) > 2 else "2026-08-01"
WINDOW, TOP_N = 3, 10
tickers, dates, off, O, Hh, L, C, V = load()
tix = {t: k for k, t in enumerate(tickers)}
c = json.loads((ROOT / "data/candles.json").read_text(encoding="utf-8"))
spy = np.r_[np.full(off, np.nan), [b[3] for b in c["data"]["SPY"]]]
news = json.loads((ROOT / "data/product_news.json").read_text(encoding="utf-8"))["items"]
sector = {r["Ticker"]: r.get("Sector") for r in json.loads((ROOT / "data/latest.json").read_text(encoding="utf-8"))["data"]}
tech = {tix[t] for t in tickers if sector.get(t) == "Technology"}
avg21 = np.full_like(V, np.nan)
for j in range(21, V.shape[1]):
    avg21[:, j] = np.nanmean(V[:, j - 21:j], 1)

variants = ["all sectors (live)", "Technology only", "all except Technology"]
res = {v: [] for v in variants}
size = {v: [] for v in variants}
spy_r, tech_all = [], []
for d in range(bisect.bisect_left(dates, START), len(dates) - FWD):
    lo, hi = dates[d - WINDOW], dates[d]
    agg = {}
    for it in news:
        if lo < it["date"] <= hi and it["ticker"] in tix:
            agg.setdefault(tix[it["ticker"]], set()).add(it["source"] or it["title"])
    fwd = (C[:, d + FWD] / C[:, d] - 1) * 100
    spy_r.append((spy[d + FWD] / spy[d] - 1) * 100)
    tech_all.append(np.nanmean(fwd[sorted(tech)]))
    rows = [(k, len(s), V[k, d] / avg21[k, d]) for k, s in agg.items() if not np.isnan(fwd[k])]
    rows.sort(key=lambda x: (-x[1], -np.nan_to_num(x[2])))
    for v in variants:
        keep = {"all sectors (live)": lambda k: True, "Technology only": lambda k: k in tech,
                "all except Technology": lambda k: k not in tech}[v]
        pick = [x[0] for x in rows if keep(x[0])][:TOP_N]
        size[v].append(len(pick))
        res[v].append(fwd[pick].mean() if pick else np.nan)
spy_r, tech_all = np.array(spy_r), np.array(tech_all)
print(f"horizon {FWD}, {len(spy_r)} sessions from {START}, {len(tech)} Technology stocks")
print(f"{'rule':24}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'best':>7}{'avg size':>9}{'empty days':>11}")
for v in variants:
    x = np.array(res[v])
    m = ~np.isnan(x)
    print(f"{v:24}{x[m].mean():7.2f}{np.median(x[m]):8.2f}{(x[m] > spy_r[m]).mean() * 100:5.0f}%{x[m].min():7.1f}"
          f"{x[m].max():7.1f}{np.mean(size[v]):9.1f}{(~m).sum():11d}")
print(f"{'All Technology eq-wt':24}{tech_all.mean():7.2f}{np.median(tech_all):8.2f}{(tech_all > spy_r).mean() * 100:5.0f}%")
print(f"{'SPY':24}{spy_r.mean():7.2f}{np.median(spy_r):8.2f}")
x1, x0 = np.array(res["Technology only"]), np.array(res["all sectors (live)"])
dd = x1 - x0
m = ~np.isnan(dd)
ts = [dd[m][o::FWD].mean() / (dd[m][o::FWD].std(ddof=1) / np.sqrt(len(dd[m][o::FWD]))) for o in range(FWD)]
print(f"Technology only minus live: {dd[m].mean():+.2f}pp mean, t {min(ts):+.2f}..{max(ts):+.2f} "
      f"({len(dd[m][::FWD])} non-overlapping periods)")
for part, sl in zip(("first half", "second half"), np.array_split(np.arange(len(spy_r)), 2)):
    print(f"  {part:11}: " + "  ".join(f"{v} {np.nanmean(np.array(res[v])[sl]):+.2f}" for v in variants)
          + f"  SPY {spy_r[sl].mean():+.2f}")
