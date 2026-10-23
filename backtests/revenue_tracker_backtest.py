#!/usr/bin/env python3
"""
Revenue growth in the Baizora Tracker list, backtested (2026-10-22).

Asked: take into account "quarter revenue vs previous quarter revenue" (QoQ, sequential)
and "yearly revenue vs previous year revenue" (latest fiscal year vs the one before).
Both read point-in-time from backtests/revenue_history.json (run revenue_history.py
first): on each session only numbers already filed count, and a quarter older than
STALE_DAYS counts as no data.

Variants, fixed before looking at results:
  conv     live rule: top 10 by BaizConviction
  filter   top 10 by BaizConviction among stocks with QoQ > 0 AND FY growth > 0
  blend    50% conviction percentile + 25% QoQ percentile + 25% FY-growth percentile
           (missing revenue = 0.5, neutral)
  revenue  revenue only: mean of the QoQ and FY-growth percentiles (no conviction)

13-trading-session forward return (the tracker page's horizon), every session with
a full forward window, current S&P 500 + Nasdaq-100 members only (survivorship
bias), in-sample one year, no costs.

Usage: python backtests/revenue_tracker_backtest.py
"""
import bisect
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TOP_N = 10
HORIZON = 13
STALE_DAYS = 200


def pct_rank(x):
    """Percentile 0..1 of each finite value; NaN stays NaN."""
    out = np.full(len(x), np.nan)
    ok = ~np.isnan(x)
    if ok.sum() > 1:
        order = x[ok].argsort().argsort()
        out[ok] = order / (ok.sum() - 1)
    return out


def growth_at(rows, date):
    """Latest value filed on/before date vs the period before it. rows = [[end, val, filed], ...]."""
    known = sorted((r for r in rows if r[2] <= date), key=lambda r: r[0])
    if len(known) < 2:
        return np.nan, None
    (e0, v0, _), (e1, v1, _) = known[-2], known[-1]
    if v0 is None or v0 <= 0 or v1 is None:
        return np.nan, e1
    return v1 / v0 - 1, e1


def main():
    candles = json.loads((ROOT / "data" / "candles.json").read_text(encoding="utf-8"))
    trend = json.loads((ROOT / "data" / "baiz_score_trend.json").read_text(encoding="utf-8"))
    latest = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    rev = json.loads((Path(__file__).parent / "revenue_history.json").read_text(encoding="utf-8"))["tickers"]
    dates = candles["dates"]
    assert trend["__dates__"] == dates
    members = [r["Ticker"] for r in latest["data"] if r.get("InSP500") or r.get("InNASDAQ100")]
    tickers = [t for t in members if len(candles["data"].get(t, [])) == len(dates) and isinstance(trend.get(t), dict)]
    close = np.array([[b[3] if b else np.nan for b in candles["data"][t]] for t in tickers], float)
    conv = np.array([[np.nan] * (len(dates) - len(trend[t]["BaizConviction"]))
                     + [np.nan if v is None else v for v in trend[t]["BaizConviction"]] for t in tickers], float)
    spy = np.array([b[3] for b in candles["data"]["SPY"]], float)

    import datetime as dt
    names = ("conv", "filter", "blend", "revenue")
    res = {k: [] for k in names + ("spy", "univ")}
    used, cover, sess = [], [], []
    for i in range(len(dates) - HORIZON):
        d = dates[i]
        stale_before = (dt.date.fromisoformat(d) - dt.timedelta(days=STALE_DAYS)).isoformat()
        cv = conv[:, i]
        ok = ~np.isnan(cv) & ~np.isnan(close[:, i]) & ~np.isnan(close[:, i + HORIZON])
        if ok.sum() < 300:
            continue
        idx = np.where(ok)[0]
        qoq = np.full(len(idx), np.nan)
        fy = np.full(len(idx), np.nan)
        for j, k in enumerate(idx):
            r = rev.get(tickers[k])
            if not r:
                continue
            g, end = growth_at(r["quarters"], d)
            if end and end >= stale_before:
                qoq[j] = g
            g, end = growth_at(r["years"], d)
            if end and end >= (dt.date.fromisoformat(d) - dt.timedelta(days=550)).isoformat():
                fy[j] = g
        fwd = (close[idx, i + HORIZON] / close[idx, i] - 1) * 100
        c = cv[idx]
        tie = np.arange(len(idx))
        top_conv = np.lexsort((tie, -c))[:TOP_N]
        good = (qoq > 0) & (fy > 0)
        cf = np.where(good, c, -np.inf)
        top_filter = np.lexsort((tie, -cf))[:TOP_N]
        pq, pf, pc = pct_rank(qoq), pct_rank(fy), pct_rank(c)
        blend = 0.5 * pc + 0.25 * np.nan_to_num(pq, nan=0.5) + 0.25 * np.nan_to_num(pf, nan=0.5)
        top_blend = np.lexsort((tie, -blend))[:TOP_N]
        ronly = np.where(np.isnan(pq) | np.isnan(pf), -np.inf, (pq + pf) / 2)
        top_rev = np.lexsort((tie, -ronly))[:TOP_N]
        for k, top in zip(names, (top_conv, top_filter, top_blend, top_rev)):
            res[k].append(fwd[top].mean())
        res["spy"].append((spy[i + HORIZON] / spy[i] - 1) * 100)
        res["univ"].append(fwd.mean())
        cover.append((~np.isnan(qoq) & ~np.isnan(fy)).mean())
        used.append(len(set(top_filter) & set(top_conv)))
        sess.append(d)

    a = {k: np.array(v) for k, v in res.items()}
    n = len(sess)
    print(f"sessions={n}  {sess[0]} .. {sess[-1]}   revenue coverage {np.mean(cover) * 100:.0f}%   "
          f"filter keeps {np.mean(used):.1f} of the conviction 10")
    print(f"{'':24}{'mean':>8}{'median':>8}{'>SPY':>8}{'>0':>8}{'worst':>8}")
    labels = {"conv": "Conviction (live)", "filter": "Conv + growth filter", "blend": "Blend 50/25/25",
              "revenue": "Revenue growth only", "univ": "Universe (equal wt)", "spy": "SPY"}
    for k in names + ("univ", "spy"):
        x = a[k]
        print(f"{labels[k]:24}{x.mean():8.2f}{np.median(x):8.2f}{(x > a['spy']).mean() * 100:7.0f}%"
              f"{(x > 0).mean() * 100:7.0f}%{x.min():8.1f}")
    for k in ("filter", "blend", "revenue"):
        diff = a[k] - a["conv"]
        ts = []
        for off in range(HORIZON):
            blk = diff[off::HORIZON]
            ts.append(blk.mean() / (blk.std(ddof=1) / np.sqrt(len(blk))) if blk.std() > 0 else 0)
        print(f"{labels[k]} minus Conviction: mean {diff.mean():+.2f}pp, median {np.median(diff):+.2f}pp, "
              f"ahead {(diff > 0).mean() * 100:.0f}% of sessions, non-overlapping t {min(ts):+.2f}..{max(ts):+.2f}")
    for part, sl in zip(("first third", "middle third", "last third"), np.array_split(np.arange(n), 3)):
        print(f"  {part:13} {sess[sl[0]]}..{sess[sl[-1]]}: " + "  ".join(
            f"{k} {a[k][sl].mean():+.2f}" for k in names + ("spy",)))


if __name__ == "__main__":
    main()
