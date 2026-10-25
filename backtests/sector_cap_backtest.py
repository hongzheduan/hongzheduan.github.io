#!/usr/bin/env python3
"""
Sector cap on the Baizora Tracker top 10 (2026-10-24).

The Oct 5 list was 9 tech hardware / semiconductor names and fell 19% in 13 sessions when
that group reversed. User asked to backtest a cap on stocks per sector. Ranking is the
live rule (RS + Momentum conviction = sqrt(RSMom x 21-session mean), RSMom = 0.5 RS +
0.5 Momentum), rebuilt from prices with conviction_variants_backtest.py; ties by the
rebuilt BaizScore. With a cap of K, walk down the ranking and skip a stock once its
sector already has K picks. Sectors are today's scanner sectors (Yahoo-style, so all
"Technology" is one bucket: chips, hardware and software together).
Same caveats as the variants backtest: current members only, in-sample, no costs,
~18 independent 13-day periods.

Result (239 sessions to 2026-10-06): no cap +6.16% mean / worst -26.6% / 9.0 tech picks
on average; cap 5 +4.92% / -23.5%; cap 4 +4.37% / -22.8%; cap 3 +3.48% / -16.4% (Oct 5
list -3.9% vs -19.1%); cap 2 +1.60%; cap 1 +0.16%. SPY +0.79%. Caps cut both the
return and the swings; risk-adjusted (mean/sd) about equal at caps 4-5, lower from 3.

Run from the repo root: python backtests/sector_cap_backtest.py
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import conviction_variants_backtest as cv  # noqa: E402

TOP_N, HORIZON = cv.TOP_N, cv.HORIZON


def main():
    tickers, dates, C, V, spy = cv.load()
    comp = cv.components(C, V)
    S = cv.score(comp, (0.30, 0.25, 0.20, 0.15, 0.10))
    R = cv.score(comp, (0.5, 0.5, 0, 0, 0))
    sig = np.round(np.sqrt(R * cv.persist(R, 21)))

    latest = json.loads((cv.ROOT / "data/latest.json").read_text(encoding="utf-8"))
    sec_of = {r["Ticker"]: r.get("Sector") or "Unknown" for r in latest["data"]}
    sector = np.array([sec_of.get(t, "Unknown") for t in tickers])

    sess = [i for i in range(252 + 63, len(dates) - HORIZON)
            if not np.isnan(spy[i]) and not np.isnan(spy[i + HORIZON])]
    spy_r = np.array([(spy[i + HORIZON] / spy[i] - 1) * 100 for i in sess])
    print(f"sessions {len(sess)}: {dates[sess[0]]} .. {dates[sess[-1]]}\n")

    def run(cap):
        means, tech = [], []
        for i in sess:
            ok = ~np.isnan(sig[:, i]) & ~np.isnan(C[:, i]) & ~np.isnan(C[:, i + HORIZON])
            idx = np.where(ok)[0]
            order = idx[np.lexsort((-np.nan_to_num(S[idx, i]), -sig[idx, i]))]
            picks, used = [], {}
            for k in order:
                if cap and used.get(sector[k], 0) >= cap:
                    continue
                picks.append(k)
                used[sector[k]] = used.get(sector[k], 0) + 1
                if len(picks) == TOP_N:
                    break
            means.append(((C[picks, i + HORIZON] / C[picks, i] - 1) * 100).mean())
            tech.append(used.get("Technology", 0))
        return np.array(means), np.array(tech)

    base, base_tech = run(None)
    print(f"{'':16}{'mean':>7}{'median':>8}{'>SPY':>6}{'worst':>7}{'stdev':>7}{'mean/sd':>8}"
          f"{'thirds':>20}{'vs none':>9}{'t':>6}{'avg tech':>9}")
    for cap in (None, 5, 4, 3, 2, 1):
        x, tech = (base, base_tech) if cap is None else run(cap)
        d = x - base
        ts = [d[o::HORIZON].mean() / (d[o::HORIZON].std(ddof=1) / np.sqrt(len(d[o::HORIZON])))
              if d[o::HORIZON].std() > 0 else 0 for o in range(HORIZON)]
        th = "/".join(f"{s.mean():+.1f}" for s in np.array_split(x, 3))
        lab = "no cap (live)" if cap is None else f"max {cap} / sector"
        print(f"{lab:16}{x.mean():7.2f}{np.median(x):8.2f}{(x > spy_r).mean() * 100:5.0f}%{x.min():7.1f}{x.std():7.2f}"
              f"{x.mean() / x.std():8.2f}{th:>20}{d.mean():+9.2f}{np.median(ts):6.2f}{tech.mean():9.1f}")
        if cap in (None, 3):
            k = dates.index("2026-10-05") if "2026-10-05" in dates else None
            if k in sess:
                print(f"{'':16}Oct 5 list: {x[sess.index(k)]:+.1f}%")
    print(f"\nSPY mean {spy_r.mean():+.2f}%, thirds " + "/".join(f"{s.mean():+.1f}" for s in np.array_split(spy_r, 3)))


if __name__ == "__main__":
    main()
