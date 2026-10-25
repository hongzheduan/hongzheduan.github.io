#!/usr/bin/env python3
"""
42-session average formulas vs the current Baizora Tracker rank, top 10, 13-session returns (2026-10-25).

User asked to compare "the 42 day BaizConviction average formula" with the tracker's current
rule. Current tracker (since 2026-10-24): RSMom = 50% RS + 50% Momentum, rank score =
sqrt(RSMom today x 21-session mean RSMom). Candidates, all on the same sessions:
  - 42-session mean of BaizScore (the a=0, N=42 row of conviction_variants_backtest.py)
  - 42-session mean of BaizConviction (sqrt(Score x Persist21), averaged over 42 sessions)
  - current tracker formula with a 42-session RSMom average instead of 21
  - 42-session mean of RSMom alone
Reuses conviction_variants_backtest.py's rebuild (corr ~0.99 vs stored BaizScore).
Current members only (survivorship bias), no costs, in-sample, ~18 independent 13-day periods.

Result (239 sessions 2025-10-23..2026-10-06, mean / median per 13 sessions, SPY +0.79%):
current tracker +6.16% / +6.62%; 42d mean BaizScore +6.77% / +7.44% (t 0.65 vs current);
42d mean BaizConviction +6.68% / +7.78% (t 0.50); sqrt(RSMom x RSMom42) +6.14%; 42d mean
RSMom +6.36%. Not significant. Lists from 2026-09-09 (20 sessions, very noisy): current -0.73%,
42d BaizScore +2.71%, 42d BaizConviction +3.87%, SPY +0.67%.

Run from the repo root: python backtests/conviction_42d_vs_tracker_backtest.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conviction_variants_backtest as cv  # noqa: E402

TOP_N, HORIZON = cv.TOP_N, cv.HORIZON


def main():
    tickers, dates, C, V, spy = cv.load()
    comp = cv.components(C, V)
    S = cv.score(comp, (0.30, 0.25, 0.20, 0.15, 0.10))  # BaizScore
    R = cv.score(comp, (0.50, 0.50, 0, 0, 0))           # RSMom
    conv = np.round(np.sqrt(S * cv.persist(S, 21)))     # BaizConviction

    # first session where a 42-session mean of BaizConviction exists (needs 21 + 41 sessions)
    first = 252 + 21 + 42
    sess = [i for i in range(first, len(dates) - HORIZON) if not np.isnan(spy[i]) and not np.isnan(spy[i + HORIZON])]
    print(f"sessions {len(sess)}: {dates[sess[0]]} .. {dates[sess[-1]]} (13-day returns end {dates[sess[-1] + HORIZON]})\n")

    def run(sig):
        out, picks = [], []
        for i in sess:
            ok = ~np.isnan(sig[:, i]) & ~np.isnan(C[:, i]) & ~np.isnan(C[:, i + HORIZON])
            idx = np.where(ok)[0]
            fwd = (C[idx, i + HORIZON] / C[idx, i] - 1) * 100
            order = np.lexsort((-np.nan_to_num(S[idx, i]), -sig[idx, i]))  # ties: BaizScore
            out.append(fwd[order[:TOP_N]].mean())
            picks.append(set(idx[order[:TOP_N]]))
        return np.array(out), picks

    spy_r = np.array([(spy[i + HORIZON] / spy[i] - 1) * 100 for i in sess])
    variants = [
        ("CURRENT tracker √(RSMom×RSMom21)", np.round(np.sqrt(R * cv.persist(R, 21)))),
        ("42d mean BaizScore", cv.persist(S, 42)),
        ("42d mean BaizConviction", cv.persist(conv, 42)),
        ("√(RSMom × RSMom42)", np.round(np.sqrt(R * cv.persist(R, 42)))),
        ("42d mean RSMom", cv.persist(R, 42)),
        ("BaizConviction (site-wide)", conv),
    ]
    res = [(lab, *run(sig)) for lab, sig in variants]
    base, base_picks = res[0][1], res[0][2]

    print(f"{'':34}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'mean/sd':>8}{'1st half':>9}{'2nd half':>9}"
          f"{'vs cur':>8}{'t':>6}{'overlap':>8}")
    for lab, x, picks in res:
        d = x - base
        ts = [d[o::HORIZON].mean() / (d[o::HORIZON].std(ddof=1) / np.sqrt(len(d[o::HORIZON])))
              if d[o::HORIZON].std() > 0 else 0 for o in range(HORIZON)]
        h1, h2 = np.array_split(x, 2)
        ov = np.mean([len(a & b) for a, b in zip(picks, base_picks)])
        print(f"{lab:34}{x.mean():7.2f}{np.median(x):8.2f}{(x > spy_r).mean() * 100:5.0f}%{x.min():7.1f}"
              f"{x.mean() / x.std():8.2f}{h1.mean():9.2f}{h2.mean():9.2f}{d.mean():+8.2f}{np.median(ts):6.2f}{ov:8.1f}")

    # recent stretch, the tracker's live period (lists from 2026-09-09 on)
    rec = [k for k, i in enumerate(sess) if dates[i] >= "2026-09-09"]
    if rec:
        print(f"\nLists from 2026-09-09 ({len(rec)} sessions): SPY {spy_r[rec].mean():+.2f}%")
        for lab, x, _ in res:
            print(f"  {lab:34}{x[rec].mean():+7.2f}%  ahead of SPY {np.mean(x[rec] > spy_r[rec]) * 100:.0f}%")
    print(f"\nSPY mean {spy_r.mean():+.2f}%, median {np.median(spy_r):+.2f}%")


if __name__ == "__main__":
    main()
