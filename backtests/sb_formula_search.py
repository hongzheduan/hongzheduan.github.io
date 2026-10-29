#!/usr/bin/env python3
"""
SB Tracker formula search (2026-10-28): which product-news rule had the best 7-session forward return?
Every rule keeps SB's core idea (a launch headline from data/product_news.json in the last WINDOW
sessions) and varies the sector filter, the headline window and the ranking, top 10 each:
  sector  : all sectors / Technology only (live) / all except Technology
  window  : 1, 3 (live), 5, 10 sessions
  ranking : most outlets (live), volume vs 21d avg, 3M change high/low, 30d volatility high/low,
            1-day change high/low, 5-day change high/low, change since the first headline high/low
Same caveats as product_news_tech_backtest.py: headline history is sparse before September,
sectors are today's labels, current members only, no costs. With 7-day returns over ~56 sessions
there are only ~8 independent periods, so each rule is also scored on each half separately.
Run from the repo root: python backtests/sb_formula_search.py [horizon] [start date]
"""
import sys, json, bisect
sys.path.insert(0, "backtests")
import numpy as np
from big_gain_7d_study import load, ROOT

FWD = int(sys.argv[1]) if len(sys.argv) > 1 else 7
START = sys.argv[2] if len(sys.argv) > 2 else "2026-08-01"
TOP_N = 10
tickers, dates, off, O, Hh, L, C, V = load()
tix = {t: k for k, t in enumerate(tickers)}
c = json.loads((ROOT / "data/candles.json").read_text(encoding="utf-8"))
spy = np.r_[np.full(off, np.nan), [b[3] for b in c["data"]["SPY"]]]
news = json.loads((ROOT / "data/product_news.json").read_text(encoding="utf-8"))["items"]
sector = {r["Ticker"]: r.get("Sector") for r in json.loads((ROOT / "data/latest.json").read_text(encoding="utf-8"))["data"]}
tech = np.array([sector.get(t) == "Technology" for t in tickers])
ret = np.full_like(C, np.nan); ret[:, 1:] = C[:, 1:] / C[:, :-1] - 1

SECTORS = {"all": lambda k: True, "tech": lambda k: tech[k], "non-tech": lambda k: not tech[k]}
WINDOWS = [1, 3, 5, 10]
SORTS = ["outlets", "volx", "r63", "-r63", "vol30", "-vol30", "r1", "-r1", "r5", "-r5", "since", "-since"]
LIVE = ("tech", 3, "outlets")

res = {(s, w, k): [] for s in SECTORS for w in WINDOWS for k in SORTS}
sizes = {key: [] for key in res}
spy_r = []
for d in range(bisect.bisect_left(dates, START), len(dates) - FWD):
    fwd = (C[:, d + FWD] / C[:, d] - 1) * 100
    spy_r.append((spy[d + FWD] / spy[d] - 1) * 100)
    feat = {
        "volx": V[:, d] / np.nanmean(V[:, d - 21:d], 1),
        "r63": C[:, d] / C[:, d - 63] - 1,
        "vol30": np.nanstd(ret[:, d - 29:d + 1], 1, ddof=1),
        "r1": ret[:, d],
        "r5": C[:, d] / C[:, d - 5] - 1,
    }
    for w in WINDOWS:
        lo, hi = dates[d - w], dates[d]
        agg, first = {}, {}
        for it in news:
            if lo < it["date"] <= hi and it["ticker"] in tix:
                k = tix[it["ticker"]]
                agg.setdefault(k, set()).add(it["source"] or it["title"])
                first[k] = min(first.get(k, it["date"]), it["date"])
        cand = [k for k in agg if not np.isnan(fwd[k])]
        since = {k: C[k, d] / C[k, bisect.bisect_left(dates, first[k]) - 1] - 1 for k in cand}
        for s, keep in SECTORS.items():
            ks = [k for k in cand if keep(k)]
            for srt in SORTS:
                name, sign = srt.lstrip("-"), (1 if srt.startswith("-") else -1)   # default: highest first
                if name == "outlets":
                    key = lambda k: (-len(agg[k]), -np.nan_to_num(feat["volx"][k]))
                elif name == "since":
                    key = lambda k: sign * since[k]
                else:
                    key = lambda k, f=feat[name]: sign * np.nan_to_num(f[k], nan=np.inf * sign)   # missing values last
                pick = sorted(ks, key=key)[:TOP_N]
                sizes[(s, w, srt)].append(len(pick))
                res[(s, w, srt)].append(fwd[pick].mean() if pick else np.nan)
spy_r = np.array(spy_r); n = len(spy_r); half = n // 2


def stats(x, sl):
    x, sp = x[sl], spy_r[sl]; m = ~np.isnan(x); d = x[m] - sp[m]
    ts = [d[o::FWD].mean() / (d[o::FWD].std(ddof=1) / np.sqrt(len(d[o::FWD]))) for o in range(FWD) if len(d[o::FWD]) > 2]
    return x[m].mean(), np.median(x[m]), (d > 0).mean() * 100, x[m].min(), d.mean(), min(ts) if ts else np.nan, m.sum()


label = lambda key: f"{key[0]}, {key[1]}d news, " + (f"lowest {key[2][1:]}" if key[2].startswith("-") else
                                                     ("most outlets" if key[2] == "outlets" else f"highest {key[2]}"))
rows = [(key, stats(np.array(v), slice(None)), stats(np.array(v), slice(0, half)), stats(np.array(v), slice(half, None)),
         np.mean(sizes[key])) for key, v in res.items()]
print(f"horizon {FWD}, {n} sessions ({dates[bisect.bisect_left(dates, START)]}..), halves split at "
      f"{dates[bisect.bisect_left(dates, START) + half]}; {len(rows)} rules")
print(f"SPY: mean {spy_r.mean():.2f} median {np.median(spy_r):.2f}; 1st half {spy_r[:half].mean():.2f}, 2nd half {spy_r[half:].mean():.2f}")
hdr = f"{'rule':38}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'vsSPY':>7}{'t(min)':>7}{'days':>5}{'size':>5} | {'H1':>6}{'H2':>6}"
fmt = lambda key, a, b1, b2, sz: (f"{label(key):38}{a[0]:7.2f}{a[1]:8.2f}{a[2]:5.0f}%{a[3]:7.1f}{a[4]:+7.2f}{a[5]:+7.2f}{a[6]:5d}{sz:5.1f} | "
                                  f"{b1[4]:+6.2f}{b2[4]:+6.2f}")
print("\n== Top 15 by full-period mean ==\n" + hdr)
for r in sorted(rows, key=lambda r: -r[1][0])[:15]: print(fmt(*r))
print("\n== Top 10 by worse half (both halves must hold up) ==\n" + hdr)
for r in sorted(rows, key=lambda r: -min(r[2][4], r[3][4]))[:10]: print(fmt(*r))
print("\n== Current SB rule ==\n" + hdr)
print(fmt(*next(r for r in rows if r[0] == LIVE)))
h1 = np.array([r[2][4] for r in rows]); h2 = np.array([r[3][4] for r in rows])
print(f"\nrank correlation of rule's vsSPY, 1st half vs 2nd half: {np.corrcoef(h1.argsort().argsort(), h2.argsort().argsort())[0, 1]:+.2f}")
