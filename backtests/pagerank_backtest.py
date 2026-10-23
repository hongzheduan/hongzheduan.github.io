#!/usr/bin/env python3
"""
Personalized-PageRank variant of the Baizora Tracker list, backtested (2026-10-23).

Asked: "use the pagerank formula" for the tracker's top-10 list. Chosen design
(user picked it over pure-correlation and lead-lag networks):

  graph     stocks = nodes; each stock links to its K most positively correlated
            peers, by daily close-to-close returns over the trailing CORR_WINDOW
            sessions, edge weight = correlation
  restart   personalization vector v proportional to BaizConviction that day
  rank      r = (1 - D) * v + D * P^T r   (P = row-normalized edge weights)
  list      top 10 by r

Compared, at every session with a full 13-session forward window, against the
live rule (top 10 by BaizConviction), SPY, and the equal-weight universe. Same
13-trading-day horizon as the tracker page. Universe = current S&P 500 +
Nasdaq-100 members (survivorship bias: today's members only). In-sample, one
year, no costs. Report medians and hit rates, not just means.

Data: data/candles.json (252 daily bars) + data/baiz_score_trend.json (rebuilt
per-session BaizConviction, same 252 dates).

Usage: python backtests/pagerank_backtest.py [--d 0.85] [--k 10] [--window 63]
"""
import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TOP_N = 10
HORIZON = 13


def load():
    candles = json.loads((ROOT / "data" / "candles.json").read_text(encoding="utf-8"))
    trend = json.loads((ROOT / "data" / "baiz_score_trend.json").read_text(encoding="utf-8"))
    latest = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    dates = candles["dates"]
    assert trend["__dates__"] == dates, "score history and candles are on different dates"
    members = [r["Ticker"] for r in latest["data"] if r.get("InSP500") or r.get("InNASDAQ100")]
    tickers = [t for t in members
               if len(candles["data"].get(t, [])) == len(dates) and isinstance(trend.get(t), dict)]
    close = np.array([[b[3] if b else np.nan for b in candles["data"][t]] for t in tickers], float)
    # Shorter score arrays are end-aligned to dates (newer tickers): pad the front.
    conv = np.array([[np.nan] * (len(dates) - len(trend[t]["BaizConviction"]))
                     + [np.nan if v is None else v for v in trend[t]["BaizConviction"]] for t in tickers], float)
    spy = np.array([b[3] for b in candles["data"]["SPY"]], float)
    return dates, tickers, close, conv, spy


def personalized_pagerank(rets, v, d, k, iters=100):
    """rets: (n, window) daily returns; v: (n,) restart weights summing to 1."""
    c = np.corrcoef(rets)
    c = np.nan_to_num(c, nan=0.0)
    np.fill_diagonal(c, -np.inf)
    w = np.zeros_like(c)
    nbr = np.argpartition(-c, k, axis=1)[:, :k]
    rows = np.arange(len(c))[:, None]
    w[rows, nbr] = np.clip(c[rows, nbr], 0, None)
    s = w.sum(1, keepdims=True)
    p = np.divide(w, s, out=np.zeros_like(w), where=s > 0)
    dangling = (s[:, 0] == 0)
    r = v.copy()
    for _ in range(iters):
        r_new = (1 - d) * v + d * (p.T @ r + v * r[dangling].sum())
        if np.abs(r_new - r).sum() < 1e-10:
            return r_new
        r = r_new
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--d", type=float, default=0.85)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--window", type=int, default=63)
    ap.add_argument("--restart", type=int, default=0,
                    help="0 = restart weight proportional to BaizConviction (flat-ish: most scores sit"
                         " mid-range); N = restart only on the top N by conviction, weighted by it")
    args = ap.parse_args()

    dates, tickers, close, conv, spy = load()
    rets = close[:, 1:] / close[:, :-1] - 1          # rets[:, j] = return into day j+1
    res = {"pr": [], "conv": [], "spy": [], "univ": [], "overlap": [], "date": []}
    for i in range(args.window, len(dates) - HORIZON):
        cv = conv[:, i]
        ok = ~np.isnan(cv) & ~np.isnan(close[:, i]) & ~np.isnan(close[:, i + HORIZON])
        win = rets[:, i - args.window:i]
        ok &= ~np.isnan(win).any(1)
        if ok.sum() < 100:
            continue
        idx = np.where(ok)[0]
        v = np.clip(cv[idx], 0, None)
        if args.restart:
            v[np.argsort(-cv[idx])[args.restart:]] = 0
        if v.sum() == 0:
            continue
        r = personalized_pagerank(win[idx], v / v.sum(), args.d, args.k)
        fwd = (close[idx, i + HORIZON] / close[idx, i] - 1) * 100
        top_pr = np.argsort(-r)[:TOP_N]
        top_cv = np.lexsort((np.arange(len(idx)), -cv[idx]))[:TOP_N]
        res["pr"].append(fwd[top_pr].mean())
        res["conv"].append(fwd[top_cv].mean())
        res["spy"].append((spy[i + HORIZON] / spy[i] - 1) * 100)
        res["univ"].append(fwd.mean())
        res["overlap"].append(len(set(top_pr) & set(top_cv)))
        res["date"].append(dates[i])

    a = {k: np.array(v) for k, v in res.items() if k != "date"}
    n = len(a["pr"])
    print(f"d={args.d} k={args.k} window={args.window} restart={args.restart or 'all'}  sessions={n}  {res['date'][0]} .. {res['date'][-1]}")
    print(f"{'':22}{'mean':>8}{'median':>8}{'>SPY':>8}{'>0':>8}{'worst':>8}")
    for name, key in (("PageRank top 10", "pr"), ("Conviction top 10", "conv"),
                      ("Universe (equal wt)", "univ"), ("SPY", "spy")):
        x = a[key]
        print(f"{name:22}{x.mean():8.2f}{np.median(x):8.2f}{(x > a['spy']).mean() * 100:7.0f}%"
              f"{(x > 0).mean() * 100:7.0f}%{x.min():8.1f}")
    diff = a["pr"] - a["conv"]
    print(f"PageRank minus Conviction: mean {diff.mean():+.2f}pp, median {np.median(diff):+.2f}pp, "
          f"PageRank ahead on {(diff > 0).mean() * 100:.0f}% of sessions")
    # Non-overlapping 13-session blocks, every offset, so one lucky phase can't dominate
    t_stats = []
    for off in range(HORIZON):
        blk = diff[off::HORIZON]
        if len(blk) > 2:
            t_stats.append(blk.mean() / (blk.std(ddof=1) / np.sqrt(len(blk))))
    print(f"non-overlapping blocks: {len(diff[::HORIZON])} per offset, t-stat of difference "
          f"range {min(t_stats):+.2f} .. {max(t_stats):+.2f}")
    print(f"avg overlap with Conviction list: {a['overlap'].mean():.1f} of 10")
    # By quarter-ish thirds
    for part, sl in zip(("first third", "middle third", "last third"),
                        np.array_split(np.arange(n), 3)):
        print(f"  {part:13} {res['date'][sl[0]]}..{res['date'][sl[-1]]}: "
              f"PR {a['pr'][sl].mean():+.2f}  Conv {a['conv'][sl].mean():+.2f}  SPY {a['spy'][sl].mean():+.2f}")


if __name__ == "__main__":
    main()
