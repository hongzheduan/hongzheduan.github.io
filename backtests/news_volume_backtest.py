#!/usr/bin/env python3
"""
SB Tracker news rule (user, 2026-10-23): stocks with "big news" = an SEC 8-K filing
(data/corporate_events.json: earnings, leadership, agreements, acquisitions, ...) in the last
WINDOW sessions AND a volume spike since the filing (a session's volume >= SPIKE x its prior
21-session average). Ranked by the size of that spike, top 10. 6-session forward returns
(the SB Tracker's horizon) by default; pass another, e.g. 13.
Variants: only stocks up since the filing / only down; earnings only; no volume filter.
Current members only (survivorship), filings as the file holds them today, no costs.
Run from the repo root: python backtests/news_volume_backtest.py [horizon]
"""
import sys, json, bisect
sys.path.insert(0, "backtests")
import numpy as np
from big_gain_7d_study import load, ROOT

FWD = int(sys.argv[1]) if len(sys.argv) > 1 else 6
WINDOW, SPIKE, TOP_N = 3, 2.0, 10
tickers, dates, off, O, Hh, L, C, V = load()
tix = {t: k for k, t in enumerate(tickers)}
ev = json.loads((ROOT / "data/corporate_events.json").read_text(encoding="utf-8"))
filings = {}   # session index -> [(ticker row, types)]
for t, items in ev.items():
    if t not in tix:
        continue
    for e in items:
        j = bisect.bisect_left(dates, e["date"])   # first session on/after the filing date
        if j < len(dates):
            filings.setdefault(j, []).append((tix[t], set(e.get("type") or [])))
avg21 = np.full_like(V, np.nan)
for j in range(21, V.shape[1]):
    avg21[:, j] = np.nanmean(V[:, j - 21:j], 1)
vr = V / avg21
spy = C[tix["SPY"]] if "SPY" in tix else None
if spy is None:
    c = json.loads((ROOT / "data/candles.json").read_text(encoding="utf-8"))
    spy = np.r_[np.full(off, np.nan), [b[3] for b in c["data"]["SPY"]]]

first = bisect.bisect_left(dates, "2025-08-05")
variants = ["news+spike", "news+spike, up", "news+spike, down", "earnings+spike", "news, no spike filter"]
res = {k: [] for k in variants}; size = {k: [] for k in variants}; spy_r = []; univ = []
for d in range(max(first, 22), len(dates) - FWD):
    if np.isnan(spy[d]) or np.isnan(spy[d + FWD]):
        continue
    best = {}   # row -> (spike, types, filing session)
    for f in range(d - WINDOW + 1, d + 1):
        for k, ty in filings.get(f, []):
            s = np.nanmax(vr[k, f:d + 1]) if f <= d else np.nan
            if k not in best or (s > best[k][0]):
                best[k] = (s, ty, f)
    fwd_all = (C[:, d + FWD] / C[:, d] - 1) * 100
    spy_r.append((spy[d + FWD] / spy[d] - 1) * 100); univ.append(np.nanmean(fwd_all))
    for v in variants:
        cand = []
        for k, (s, ty, f) in best.items():
            if np.isnan(fwd_all[k]) or np.isnan(s):
                continue
            moved = C[k, d] / C[k, f - 1] - 1
            if v != "news, no spike filter" and s < SPIKE:
                continue
            if v.endswith(", up") and moved <= 0: continue
            if v.endswith(", down") and moved >= 0: continue
            if v.startswith("earnings") and "earnings" not in ty: continue
            cand.append((-s, k))
        cand.sort()
        pick = [k for _, k in cand[:TOP_N]]
        size[v].append(len(pick))
        res[v].append(fwd_all[pick].mean() if pick else np.nan)
spy_r, univ = np.array(spy_r), np.array(univ)
print(f"horizon {FWD} sessions, {len(spy_r)} sessions from {dates[max(first, 22)]}; window {WINDOW} sessions, spike >= {SPIKE}x 21-day avg volume")
print(f"{'rule':24}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'avg size':>9}{'no list':>8}{'vs SPY':>8}{'t':>14}")
for v in variants:
    x = np.array(res[v]); m = ~np.isnan(x); dd = x[m] - spy_r[m]
    ts = [dd[o::FWD].mean() / (dd[o::FWD].std(ddof=1) / np.sqrt(len(dd[o::FWD]))) for o in range(FWD)]
    print(f"{v:24}{x[m].mean():7.2f}{np.median(x[m]):8.2f}{(dd > 0).mean()*100:5.0f}%{x[m].min():7.1f}{np.mean(size[v]):9.1f}"
          f"{(~m).sum():8d}{dd.mean():+8.2f}{min(ts):+7.2f}..{max(ts):+.2f}")
print(f"{'All stocks eq-wt':24}{univ.mean():7.2f}{np.median(univ):8.2f}")
print(f"{'SPY':24}{spy_r.mean():7.2f}{np.median(spy_r):8.2f}")
for part, sl in zip(("first third", "middle third", "last third"), np.array_split(np.arange(len(spy_r)), 3)):
    print(f"  {part:13}: " + "  ".join(f"{v} {np.nanmean(np.array(res[v])[sl]):+.2f}" for v in variants[:3]) + f"  SPY {spy_r[sl].mean():+.2f}")
