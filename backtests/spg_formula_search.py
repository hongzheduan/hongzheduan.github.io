#!/usr/bin/env python3
"""
SPG Tracker formula search (2026-10-28): which "top 10 by <rule>" list had the best 2-session
forward return? Tries ~90 rules (single-factor sorts both ways, and filter + sort combos such as
the current 5-up-days-lowest-vol rule) on the same universe as the SPG backtests.

Overfitting guard: with this many rules and 2-day noise, the best full-period rule is mostly luck.
So every rule is also scored on the FIRST half only and the LAST half only; the honest number for a
rule picked on the first half is its last-half result (walk-forward).
Current members only (survivorship), in-sample, no costs, list mean of up to 10 stocks.
Run from the repo root: python backtests/spg_formula_search.py [horizon]
"""
import sys, json
sys.path.insert(0, "backtests")
import numpy as np
from gainer_pattern_backtest import ROOT, TOP_N

H_FWD = int(sys.argv[1]) if len(sys.argv) > 1 else 2


def load_ohlcv():
    """load_prices() from gainer_pattern_backtest, extended with open, low and volume."""
    c = json.loads((ROOT / "data/candles.json").read_text(encoding="utf-8"))
    latest = json.loads((ROOT / "data/latest.json").read_text(encoding="utf-8"))
    cdates, seam = c["dates"], c["dates"][0]
    cache = {}
    for r in latest["data"]:
        t = r["Ticker"]
        f = ROOT / "data/ohlcv_yfinance_cache" / f"{t}.json"
        if (r.get("InSP500") or r.get("InNASDAQ100")) and len(c["data"].get(t, [])) == len(cdates) and f.exists():
            bars = json.loads(f.read_text(encoding="utf-8"))["bars"]
            if seam in bars and c["data"][t][0]:
                cache[t] = bars
    pre = sorted({d for b in cache.values() for d in b if d < seam})
    pre = [d for d in pre if sum(d in b for b in cache.values()) > 0.9 * len(cache)]
    tickers = sorted(cache)
    n = len(pre) + len(cdates)
    O, H, L, C, V = (np.full((len(tickers), n), np.nan) for _ in range(5))
    for k, t in enumerate(tickers):
        bars, scale = cache[t], c["data"][t][0][3] / cache[t][seam]["c"]
        for i, d in enumerate(pre):
            b = bars.get(d)
            if b:
                O[k, i], H[k, i], L[k, i], C[k, i] = (b[x] * scale for x in "ohlc")
                V[k, i] = b["v"] / scale
        for i, b in enumerate(c["data"][t]):
            if b:
                O[k, len(pre) + i], H[k, len(pre) + i], L[k, len(pre) + i], C[k, len(pre) + i], V[k, len(pre) + i] = b[:5]
    spy = np.array([b[3] for b in c["data"]["SPY"]], float)
    return tickers, pre + cdates, len(pre), O, H, L, C, V, spy


tickers, dates, off, O, H, L, C, V, spy = load_ohlcv()
ret = np.full_like(C, np.nan); ret[:, 1:] = C[:, 1:] / C[:, :-1] - 1


def rsi(i, n):
    d = ret[:, i - n + 1:i + 1]
    g = np.nansum(np.clip(d, 0, None), 1); l = -np.nansum(np.clip(d, None, 0), 1)
    return np.where(g + l > 0, 100 * g / np.where(g + l > 0, g + l, 1), 50)


def features(i):
    f = {}
    for k in (1, 2, 5, 10, 21, 63, 126):
        f[f"r{k}"] = C[:, i] / C[:, i - k] - 1
    f["mom12_1"] = C[:, i - 21] / C[:, i - 252] - 1
    f["vol1y"] = np.nanstd(ret[:, i - 251:i + 1], 1, ddof=1)
    f["vol30"] = np.nanstd(ret[:, i - 29:i + 1], 1, ddof=1)
    f["z1"] = ret[:, i] / f["vol30"]                                   # today's move in 30d-vol units
    f["rsi2"], f["rsi5"], f["rsi14"] = rsi(i, 2), rsi(i, 5), rsi(i, 14)
    for k in (20, 50, 200):
        f[f"sma{k}"] = C[:, i] / np.nanmean(C[:, i - k + 1:i + 1], 1) - 1
    f["volx"] = V[:, i] / np.nanmean(V[:, i - 21:i], 1)                 # today's volume vs prior 21d avg
    rng = H[:, i] - L[:, i]
    f["clv"] = np.where(rng > 0, (C[:, i] - L[:, i]) / np.where(rng > 0, rng, 1), 0.5)   # close location in day's range
    f["body"] = C[:, i] / O[:, i] - 1
    f["hi52"] = C[:, i] / np.nanmax(H[:, i - 251:i + 1], 1) - 1         # distance below 52-week high
    up = np.zeros(len(C), int); dn = np.zeros(len(C), int); ua = np.ones(len(C), bool); da = ua.copy()
    for k in range(10):
        ua &= ret[:, i - k] > 0; da &= ret[:, i - k] < 0; up += ua; dn += da
    f["upstreak"], f["dnstreak"] = up, dn
    return f


SORTS = ["r1", "r2", "r5", "r10", "r21", "r63", "r126", "mom12_1", "vol1y", "vol30", "z1", "rsi2", "rsi5", "rsi14",
         "sma20", "sma50", "sma200", "volx", "clv", "body", "hi52"]
RULES = {}  # name -> (filter fn or None, sort key, ascending)
for s in SORTS:
    RULES[f"lowest {s}"] = (None, s, True)
    RULES[f"highest {s}"] = (None, s, False)
FILTERS = {
    "5 up days": lambda f: f["upstreak"] >= 5,
    "3 up days": lambda f: f["upstreak"] >= 3,
    "3 down days": lambda f: f["dnstreak"] >= 3,
    "above SMA200": lambda f: f["sma200"] > 0,
    "below SMA200": lambda f: f["sma200"] < 0,
    "volume 2x": lambda f: f["volx"] >= 2,
    "top 30% 6M momentum": lambda f: f["r126"] >= np.nanquantile(f["r126"], 0.7),
}
for fn in FILTERS:
    for s, asc in [("vol1y", True), ("vol1y", False), ("r1", True), ("r5", True), ("r5", False),
                   ("rsi2", True), ("z1", True), ("r63", False), ("volx", False)]:
        RULES[f"{fn}, {'lowest' if asc else 'highest'} {s}"] = (FILTERS[fn], s, asc)
CURRENT = "5 up days, lowest vol1y"

res = {k: [] for k in RULES}; spy_r = []
for ci in range(len(spy) - H_FWD):
    i = off + ci
    ok = ~np.isnan(C[:, i]) & ~np.isnan(C[:, i + H_FWD]) & ~np.isnan(C[:, i - 252])
    f = features(i)
    fwd = (C[:, i + H_FWD] / C[:, i] - 1) * 100
    spy_r.append((spy[ci + H_FWD] / spy[ci] - 1) * 100)
    for name, (filt, s, asc) in RULES.items():
        m = ok & ~np.isnan(f[s]) & (filt(f) if filt else True)
        r = np.where(m)[0]
        if not len(r):
            res[name].append(np.nan); continue
        key = f[s][r] if asc else -f[s][r]
        res[name].append(fwd[r[np.argsort(key, kind="stable")[:TOP_N]]].mean())
spy_r = np.array(spy_r)
n = len(spy_r); half = n // 2


def stats(x, sl):
    x, s = x[sl], spy_r[sl]; m = ~np.isnan(x); d = x[m] - s[m]
    ts = [d[o::H_FWD].mean() / (d[o::H_FWD].std(ddof=1) / np.sqrt(len(d[o::H_FWD]))) for o in range(H_FWD)]
    return x[m].mean(), np.median(x[m]), (d > 0).mean() * 100, x[m].min(), d.mean(), min(ts), m.sum()


rows = []
for k in RULES:
    x = np.array(res[k])
    a, b1, b2 = stats(x, slice(None)), stats(x, slice(0, half)), stats(x, slice(half, None))
    rows.append((k, a, b1, b2))
print(f"horizon {H_FWD} sessions, {n} sessions ({dates[off]}..{dates[off + n - 1]}), halves split at {dates[off + half]}; "
      f"{len(RULES)} rules, top {TOP_N} each")
print(f"SPY: full mean {spy_r.mean():.2f} median {np.median(spy_r):.2f}; 1st half {spy_r[:half].mean():.2f}, 2nd half {spy_r[half:].mean():.2f}")
hdr = f"{'rule':42}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'vsSPY':>7}{'t(min)':>7}{'days':>5} | {'H1 vsSPY':>9}{'H2 vsSPY':>9}"
print("\n== Top 15 by full-period mean ==\n" + hdr)
fmt = lambda k, a, b1, b2: (f"{k:42}{a[0]:7.2f}{a[1]:8.2f}{a[2]:5.0f}%{a[3]:7.1f}{a[4]:+7.2f}{a[5]:+7.2f}{a[6]:5d} | "
                            f"{b1[4]:+9.2f}{b2[4]:+9.2f}")
for row in sorted(rows, key=lambda r: -r[1][0])[:15]:
    print(fmt(*row))
print("\n== Walk-forward: top 10 picked on 1st half, scored on 2nd half ==\n" + hdr)
for row in sorted(rows, key=lambda r: -r[2][0])[:10]:
    print(fmt(*row))
print("\n== Current SPG rule ==\n" + hdr)
print(fmt(*next(r for r in rows if r[0] == CURRENT)))
h1 = np.array([r[2][4] for r in rows]); h2 = np.array([r[3][4] for r in rows])
print(f"\nrank correlation of rule's vsSPY, 1st half vs 2nd half: {np.corrcoef(h1.argsort().argsort(), h2.argsort().argsort())[0, 1]:+.2f}")
