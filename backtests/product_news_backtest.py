#!/usr/bin/env python3
"""
SB Tracker product-news rule (user, 2026-10-23): stocks with a product-launch headline
(data/product_news.json, fetch_product_news.py) dated within the last WINDOW sessions, ranked
by how many outlets carried it, up to 10. 6-session forward returns by default.
Small, rough test: the headline history only reaches back as far as Google News RSS returned
on 2026-10-23 (sparse before September), so older sessions see fewer launches than the live
feed will. Current members only, no costs.
Run from the repo root: python backtests/product_news_backtest.py [horizon] [start date]
"""
import sys, json, bisect
sys.path.insert(0, "backtests")
import numpy as np
from big_gain_7d_study import load, ROOT

FWD = int(sys.argv[1]) if len(sys.argv) > 1 else 6
START = sys.argv[2] if len(sys.argv) > 2 else "2026-08-01"
WINDOW, TOP_N = 3, 10
tickers, dates, off, O, Hh, L, C, V = load()
tix = {t: k for k, t in enumerate(tickers)}
c = json.loads((ROOT / "data/candles.json").read_text(encoding="utf-8"))
spy = np.r_[np.full(off, np.nan), [b[3] for b in c["data"]["SPY"]]]
news = json.loads((ROOT / "data/product_news.json").read_text(encoding="utf-8"))["items"]
avg21 = np.full_like(V, np.nan)
for j in range(21, V.shape[1]):
    avg21[:, j] = np.nanmean(V[:, j - 21:j], 1)
variants = ["by outlets", "by volume today", "outlets, up since news", "outlets, down since news"]
res = {v: [] for v in variants}; size = {v: [] for v in variants}; spy_r, univ = [], []
for d in range(bisect.bisect_left(dates, START), len(dates) - FWD):
    lo, hi = dates[d - WINDOW], dates[d]
    agg = {}
    for it in news:
        if lo < it["date"] <= hi and it["ticker"] in tix:
            a = agg.setdefault(tix[it["ticker"]], {"src": set(), "first": it["date"]})
            a["src"].add(it["source"] or it["title"]); a["first"] = min(a["first"], it["date"])
    fwd = (C[:, d + FWD] / C[:, d] - 1) * 100
    spy_r.append((spy[d + FWD] / spy[d] - 1) * 100); univ.append(np.nanmean(fwd))
    rows = []
    for k, a in agg.items():
        if np.isnan(fwd[k]):
            continue
        f = bisect.bisect_left(dates, a["first"])
        moved = C[k, d] / C[k, f - 1] - 1
        rows.append((k, len(a["src"]), V[k, d] / avg21[k, d], moved))
    for v in variants:
        r = [x for x in rows if not (v.endswith("up since news") and x[3] <= 0) and not (v.endswith("down since news") and x[3] >= 0)]
        r.sort(key=lambda x: (-x[2],) if v == "by volume today" else (-x[1], -x[2]))
        pick = [x[0] for x in r[:TOP_N]]
        size[v].append(len(pick)); res[v].append(fwd[pick].mean() if pick else np.nan)
spy_r, univ = np.array(spy_r), np.array(univ)
print(f"horizon {FWD}, {len(spy_r)} sessions from {START}, {len(news)} headlines on file")
print(f"{'rule':26}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'avg size':>9}{'no list':>8}{'vs SPY':>8}")
for v in variants:
    x = np.array(res[v]); m = ~np.isnan(x); dd = x[m] - spy_r[m]
    print(f"{v:26}{x[m].mean():7.2f}{np.median(x[m]):8.2f}{(dd > 0).mean()*100:5.0f}%{x[m].min():7.1f}{np.mean(size[v]):9.1f}{(~m).sum():8d}{dd.mean():+8.2f}")
print(f"{'All stocks eq-wt':26}{univ.mean():7.2f}{np.median(univ):8.2f}")
print(f"{'SPY':26}{spy_r.mean():7.2f}{np.median(spy_r):8.2f}")
