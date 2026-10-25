#!/usr/bin/env python3
"""
BaizConviction formula variants, Baizora Tracker top 10, 13-session returns (2026-10-24).

User asked whether a different combination for BaizConviction gives better results.
BaizScore's five components are rebuilt from daily prices exactly as scanner_tiingo.py
does (RS / Momentum percentiles ranked within this universe instead of the full scanned
universe incl. ETFs, so the rebuild is close but not identical; agreement is printed).
Two families are tested, each against the rebuilt current formula:
  A. how today's score and its history combine: Score^a x Persist_N^(1-a)
     (a = 0.5, N = 21 is today's BaizConviction; a = 1 is plain BaizScore)
  B. BaizScore component weights, with the current sqrt(Score x Persist21) on top.
Current S&P 500 + Nasdaq-100 members only (survivorship bias), no costs, in-sample:
every variant is scored on the same ~240 overlapping sessions (~18 independent
13-day periods), so the best of many variants is expected to look better by chance.

Result (239 sessions 2025-10-23..2026-10-06; rebuild corr 0.991 vs stored BaizScore):
current +4.05% mean per 13 sessions; 42-session average BaizScore alone +6.77% (t 1.93,
better in every third); RS+Momentum-only weights +6.37% (t 1.32); plain 3M change +5.42%;
SPY +0.79%. Shorter history (5-10 sessions) and Breakout/VolPressure/Trend weight hurt.
None significant after testing ~30 variants.

Run from the repo root: python backtests/conviction_variants_backtest.py
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TOP_N, HORIZON = 10, 13


def load():
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
    C = np.full((len(tickers), len(pre) + len(cdates)), np.nan)
    V = C.copy()
    for k, t in enumerate(tickers):
        bars, scale = cache[t], c["data"][t][0][3] / cache[t][seam]["c"]
        for i, d in enumerate(pre):
            if d in bars:
                C[k, i], V[k, i] = bars[d]["c"] * scale, bars[d]["v"]
        for i, b in enumerate(c["data"][t]):
            if b:
                C[k, len(pre) + i], V[k, len(pre) + i] = b[3], b[4]
    spy = np.array([np.nan] * len(pre) + [b[3] if b else np.nan for b in c["data"]["SPY"]], float)
    return tickers, pre + cdates, C, V, spy


def pct_rank(x):
    """pandas rank(pct=True): average rank / n, NaN stays NaN."""
    out = np.full(len(x), np.nan)
    ok = ~np.isnan(x)
    v = x[ok]
    s = np.sort(v)
    out[ok] = (np.searchsorted(s, v, "left") + np.searchsorted(s, v, "right") + 1) / 2 / len(v)
    return out


def components(C, V):
    """Per (ticker, day): rs_norm, MomentumScore, BreakoutScore, TrendScore, vp_norm (all 0..100)."""
    n_t, n_d = C.shape
    comp = np.full((5, n_t, n_d), np.nan)
    chg = lambda i, days: (C[:, i] / C[:, i - days + 1] - 1) * 100  # calculate_period_metrics: last N bars
    for i in range(252, n_d):
        pc = {k: np.nan_to_num(chg(i, d)) for k, d in (("2w", 10), ("1m", 21), ("3m", 63), ("6m", 126), ("9m", 189), ("1y", 252))}
        raw_rs = 0.40 * pc["3m"] + 0.20 * pc["6m"] + 0.20 * pc["9m"] + 0.20 * pc["1y"]
        raw_mom = 0.35 * pc["1m"] + 0.25 * pc["3m"] + 0.20 * pc["6m"] + 0.20 * pc["1y"]
        live = ~np.isnan(C[:, i]) & ~np.isnan(C[:, i - 1])
        raw_rs[~live] = np.nan
        raw_mom[~live] = np.nan
        rs = np.clip(np.round(pct_rank(raw_rs) * 98 + 1), 1, 99)
        mom = np.clip(np.round(pct_rank(raw_mom) * 100), 0, 100)
        pv = C[:, i] / np.nanmean(C[:, i - 20:i + 1], 1)
        vv = V[:, i] / np.nanmean(V[:, i - 20:i + 1], 1)
        pv, vv = np.nan_to_num(pv, nan=1.0), np.nan_to_num(vv, nan=1.0)
        d1 = np.nan_to_num((C[:, i] / C[:, i - 1] - 1) * 100)
        bs = np.clip((pv - 1) * 200, 0, 33) + np.clip(d1 * 3, 0, 33) + np.clip((vv - 1) * 25, 0, 34)
        brk = np.round(np.clip(bs, 0, 100))
        vp = np.round(np.clip((vv - 1) * np.sign(d1) * 100, -100, 100))
        trend = np.round(sum((pc[k] > 0).astype(float) for k in pc) / 6 * 100)
        comp[:, :, i] = [(rs - 1) / 98 * 100, mom, brk, trend, (vp + 100) / 2]
        comp[:, ~live, i] = np.nan
    return comp


def score(comp, w):
    return np.clip(np.round(np.tensordot(np.array(w), comp, 1)), 0, 100)


def persist(S, n):
    """Trailing n-session mean of S including today; NaN until n sessions exist."""
    out = np.full_like(S, np.nan)
    cs = np.nancumsum(np.nan_to_num(S), 1)
    cnt = np.cumsum(~np.isnan(S), 1)
    for i in range(n - 1, S.shape[1]):
        s = cs[:, i] - (cs[:, i - n] if i >= n else 0)
        k = cnt[:, i] - (cnt[:, i - n] if i >= n else 0)
        out[:, i] = np.where(k == n, s / n, np.nan)
    return out


def main():
    tickers, dates, C, V, spy = load()
    comp = components(C, V)
    CUR = (0.30, 0.25, 0.20, 0.15, 0.10)
    S = score(comp, CUR)

    trend = json.loads((ROOT / "data/baiz_score_trend.json").read_text(encoding="utf-8"))
    td = trend["__dates__"]
    di = {d: i for i, d in enumerate(dates)}
    a, b = [], []
    for k, t in enumerate(tickers):
        vals = trend.get(t, {}).get("BaizScore") or []
        for d, v in zip(td[len(td) - len(vals):], vals):
            if v is not None and d in di and not np.isnan(S[k, di[d]]):
                a.append(v); b.append(S[k, di[d]])
    a, b = np.array(a), np.array(b)
    print(f"Rebuild check vs stored BaizScore: corr {np.corrcoef(a, b)[0, 1]:.3f}, "
          f"median |diff| {np.median(np.abs(a - b)):.0f}, within 5 pts {np.mean(np.abs(a - b) <= 5) * 100:.0f}%  (n={len(a)})")

    # Evaluation sessions: every variant must have a value (63-session persist is the longest).
    first = 252 + 63
    sess = [i for i in range(first, len(dates) - HORIZON) if not np.isnan(spy[i]) and not np.isnan(spy[i + HORIZON])]
    print(f"sessions {len(sess)}: {dates[sess[0]]} .. {dates[sess[-1]]} (13-day returns end {dates[sess[-1] + HORIZON]})\n")

    def run(sig):
        out = []
        for i in sess:
            ok = ~np.isnan(sig[:, i]) & ~np.isnan(C[:, i]) & ~np.isnan(C[:, i + HORIZON])
            idx = np.where(ok)[0]
            fwd = (C[idx, i + HORIZON] / C[idx, i] - 1) * 100
            # ties broken by today's current-formula score, like the tracker (then ticker order)
            order = np.lexsort((-np.nan_to_num(S[idx, i]), -sig[idx, i]))
            out.append(fwd[order[:TOP_N]].mean())
        return np.array(out)

    spy_r = np.array([(spy[i + HORIZON] / spy[i] - 1) * 100 for i in sess])
    base = None
    rows = []

    def report(label, x):
        nonlocal base
        if base is None:
            base = x
        d = x - base
        ts = [d[o::HORIZON].mean() / (d[o::HORIZON].std(ddof=1) / np.sqrt(len(d[o::HORIZON]))) if d[o::HORIZON].std() > 0 else 0
              for o in range(HORIZON)]
        h1, h2 = np.array_split(x, 2)
        rows.append((label, x.mean(), np.median(x), (x > spy_r).mean() * 100, x.min(), x.mean() / x.std(),
                     h1.mean(), h2.mean(), d.mean(), np.median(ts)))

    P = {n: persist(S, n) for n in (5, 10, 21, 42, 63)}
    report("CURRENT  √(Score × Persist21)", run(np.round(np.sqrt(S * P[21]))))

    print("A. Combining today's score with its history:  Score^a × PersistN^(1-a)")
    for a_ in (1.0, 0.75, 0.5, 0.25, 0.0):
        for n in (5, 10, 21, 42, 63):
            if a_ == 1.0 and n != 21:
                continue
            if a_ == 0.5 and n == 21:
                continue
            lab = "BaizScore alone" if a_ == 1.0 else f"a={a_:.2f}  N={n}"
            report(lab, run(S ** a_ * P[n] ** (1 - a_)))

    print_table(rows, spy_r)
    rows.clear()
    report("CURRENT  √(Score × Persist21)", run(np.round(np.sqrt(S * P[21]))))
    print("\nB. BaizScore part weights (RS, Momentum, Breakout, Trend, VolPressure), conviction = √(Score × Persist21)")
    W = {
        "equal 20 each": (0.20, 0.20, 0.20, 0.20, 0.20),
        "RS+Mom only 50/50": (0.50, 0.50, 0, 0, 0),
        "momentum-heavy 40/35/15/5/5": (0.40, 0.35, 0.15, 0.05, 0.05),
        "technical 10/10/40/10/30": (0.10, 0.10, 0.40, 0.10, 0.30),
        "trend-heavy 20/15/10/45/10": (0.20, 0.15, 0.10, 0.45, 0.10),
        "no breakout/VP 35/35/0/30/0": (0.35, 0.35, 0, 0.30, 0),
        "no VolPressure 33/28/22/17/0": (0.33, 0.28, 0.22, 0.17, 0),
        "no Breakout 37/31/0/19/13": (0.37, 0.31, 0, 0.19, 0.13),
        "RS only": (1, 0, 0, 0, 0),
        "Momentum only": (0, 1, 0, 0, 0),
        "Trend only": (0, 0, 0, 1, 0),
    }
    for lab, w in W.items():
        s2 = score(comp, w)
        report(lab, run(np.round(np.sqrt(s2 * persist(s2, 21)))))
    print_table(rows, spy_r)

    univ = []
    for i in sess:
        ok = ~np.isnan(C[:, i]) & ~np.isnan(C[:, i + HORIZON])
        univ.append(((C[ok, i + HORIZON] / C[ok, i] - 1) * 100).mean())
    univ = np.array(univ)
    print(f"\nReference: SPY mean {spy_r.mean():+.2f}%, median {np.median(spy_r):+.2f}%; "
          f"all stocks equal-weight mean {univ.mean():+.2f}%")


def print_table(rows, spy_r):
    print(f"{'':32}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'mean/sd':>8}{'1st half':>9}{'2nd half':>9}{'vs cur':>8}{'t':>6}")
    for lab, m, md, gt, w, rs, h1, h2, d, t in rows:
        print(f"{lab:32}{m:7.2f}{md:8.2f}{gt:5.0f}%{w:7.1f}{rs:8.2f}{h1:9.2f}{h2:9.2f}{d:+8.2f}{t:6.2f}")


if __name__ == "__main__":
    main()
