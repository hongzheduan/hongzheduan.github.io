#!/usr/bin/env python3
"""
Can scanner data flag stocks about to rise more than 10% within 7 trading days? (2026-10-23)

Event: close 7 sessions later / today's close - 1 > 10%. For every S&P 500 / Nasdaq-100 stock
and session, compute price/volume features (as daily cross-sectional percentiles), then:
  1. single-feature AUC (0.5 = no signal) for the >10% gain AND the >10% drop event,
  2. a logistic regression fitted on the first 60% of sessions, scored on the last 40%
     (7-session gap between them), so the test is out-of-sample in time,
  3. how often the model's top 10 per day actually rose >10% (and fell >10%) vs the base rate.
Current members only (survivorship), no costs. Prices: candles.json stitched to the
yfinance cache (about 2 years); Baiz scores from baiz_score_trend.json where available.
Run from the repo root: python backtests/big_gain_7d_study.py
"""
import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
FWD, THRESH, TOP_N = 7, 0.10, 10


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
    shape = (len(tickers), len(pre) + len(cdates))
    O, Hh, L, C, V = (np.full(shape, np.nan) for _ in range(5))
    for k, t in enumerate(tickers):
        bars, scale = cache[t], c["data"][t][0][3] / cache[t][seam]["c"]
        for i, d in enumerate(pre):
            if d in bars:
                b = bars[d]
                O[k, i], Hh[k, i], L[k, i], C[k, i], V[k, i] = b["o"] * scale, b["h"] * scale, b["l"] * scale, b["c"] * scale, b["v"]
        for i, b in enumerate(c["data"][t]):
            if b:
                O[k, len(pre) + i], Hh[k, len(pre) + i], L[k, len(pre) + i], C[k, len(pre) + i], V[k, len(pre) + i] = b
    return tickers, pre + cdates, len(pre), O, Hh, L, C, V


def rank_pct(x):
    out = np.full(len(x), np.nan)
    ok = ~np.isnan(x)
    if ok.sum() > 1:
        out[ok] = x[ok].argsort().argsort() / (ok.sum() - 1)
    return out


def auc(score, y):
    ok = ~np.isnan(score)
    s, y = score[ok], y[ok]
    r = s.argsort().argsort() + 1.0
    n1 = y.sum(); n0 = len(y) - n1
    return (r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def main():
    tickers, dates, off, O, Hh, L, C, V = load()
    trend = json.loads((ROOT / "data/baiz_score_trend.json").read_text(encoding="utf-8"))
    tdates = trend["__dates__"]
    def tcol(name):
        a = np.full(C.shape, np.nan)
        for k, t in enumerate(tickers):
            arr = (trend.get(t) or {}).get(name) or []
            for j, v in enumerate(arr):
                d = tdates[len(tdates) - len(arr) + j]
                if v is not None and d in dates:
                    a[k, dates.index(d)] = v
        return a
    conv, bscore = tcol("BaizConviction"), tcol("BaizScore")
    ret = np.full_like(C, np.nan); ret[:, 1:] = C[:, 1:] / C[:, :-1] - 1
    start = 253   # need a year of history for the features
    names = ["vol30", "vol1y", "ret5", "ret21", "ret63", "dist52wHigh", "distSMA200", "rsi14",
             "volume/21d", "volume5/63d", "maxJump21", "pastEvents1y", "atr14", "BaizConviction", "BaizScore"]
    X, Yup, Ydn, day, F7 = [], [], [], [], []
    for i in range(start, C.shape[1] - FWD):
        ok = ~np.isnan(C[:, i]) & ~np.isnan(C[:, i + FWD]) & ~np.isnan(C[:, i - 252])
        k = np.where(ok)[0]
        f7 = C[k, i + FWD] / C[k, i] - 1
        r = ret[k, i - 251:i + 1]
        gains, losses = np.clip(r[:, -14:], 0, None).mean(1), np.clip(-r[:, -14:], 0, None).mean(1)
        c7 = C[k, i - 252 + FWD:i + 1] / C[k, i - 252:i + 1 - FWD] - 1   # trailing 7-day returns over the year
        feats = [
            np.nanstd(r[:, -30:], 1), np.nanstd(r, 1),
            C[k, i] / C[k, i - 5] - 1, C[k, i] / C[k, i - 21] - 1, C[k, i] / C[k, i - 63] - 1,
            C[k, i] / np.nanmax(C[k, i - 251:i + 1], 1) - 1,
            C[k, i] / np.nanmean(C[k, i - 199:i + 1], 1) - 1,
            100 - 100 / (1 + gains / np.where(losses > 0, losses, np.nan)),
            V[k, i] / np.nanmean(V[k, i - 20:i + 1], 1),
            np.nanmean(V[k, i - 4:i + 1], 1) / np.nanmean(V[k, i - 62:i + 1], 1),
            np.nanmax(r[:, -21:], 1),
            np.nanmean(c7 > THRESH, 1),
            np.nanmean((Hh[k, i - 13:i + 1] - L[k, i - 13:i + 1]) / C[k, i - 13:i + 1], 1),
            conv[k, i], bscore[k, i],
        ]
        X.append(np.column_stack([rank_pct(f) for f in feats]))
        Yup.append(f7 > THRESH); Ydn.append(f7 < -THRESH); day.append(np.full(len(k), i)); F7.append(f7 * 100)
    X, Yup, Ydn, day = np.vstack(X), np.concatenate(Yup), np.concatenate(Ydn), np.concatenate(day)
    F7 = np.concatenate(F7)
    days = np.unique(day)
    cut = days[int(len(days) * 0.6)]
    train, test = day < cut - FWD, day >= cut
    print(f"{len(tickers)} stocks, sessions {dates[days[0]]}..{dates[days[-1]]} ({len(days)}); "
          f"train to {dates[cut - FWD - 1]}, test from {dates[cut]}")
    print(f"base rate: >10% gain in 7 days {Yup.mean()*100:.1f}% of stock-days (train {Yup[train].mean()*100:.1f}%, test {Yup[test].mean()*100:.1f}%); "
          f">10% drop {Ydn.mean()*100:.1f}%")
    print(f"\n{'feature':16}{'AUC gain':>9}{'AUC drop':>9}   (test period; BaizScore/Conviction only where available)")
    for j, n in enumerate(names):
        print(f"{n:16}{auc(X[test, j], Yup[test]):9.3f}{auc(X[test, j], Ydn[test]):9.3f}")

    # Logistic regression on train (features with full coverage; NaN -> 0.5), plain gradient descent.
    use = [j for j in range(len(names)) if names[j] not in ("BaizConviction", "BaizScore")]
    def design(rows):
        Z = np.nan_to_num(X[rows][:, use], nan=0.5) - 0.5
        return np.column_stack([np.ones(len(Z)), Z])
    Ztr, ytr = design(train), Yup[train].astype(float)
    w = np.zeros(Ztr.shape[1])
    for _ in range(3000):
        p = 1 / (1 + np.exp(-Ztr @ w))
        w -= 0.5 * (Ztr.T @ (p - ytr) / len(ytr) + 1e-3 * np.r_[0, w[1:]])
    print("\nlogistic weights (percentile features, centered):")
    for j, wj in sorted(zip(use, w[1:]), key=lambda t: -abs(t[1])):
        print(f"  {names[j]:16}{wj:+.2f}")
    s_test = design(test) @ w
    print(f"\nmodel AUC, test period: gain {auc(s_test, Yup[test]):.3f}, drop {auc(s_test, Ydn[test]):.3f}"
          f"  (train gain {auc(Ztr @ w, Yup[train]):.3f})")
    vol_only = X[test, names.index("vol30")]
    print(f"30-day volatility alone, test: gain {auc(vol_only, Yup[test]):.3f}, drop {auc(vol_only, Ydn[test]):.3f}")

    print(f"\ntop {TOP_N} per day, test period:   rose >10%   fell >10%   mean 7-day return")
    ytd, dtd = Yup[test], Ydn[test]
    tday = day[test]
    ft = F7[test]
    for label, sc in (("model", s_test), ("30-day vol", vol_only), ("random (base)", None)):
        up = dn = 0; n = 0; rs = []
        for d in np.unique(tday):
            m = np.where(tday == d)[0]
            pick = m if sc is None else m[np.argsort(-np.nan_to_num(sc[m], nan=-9))[:TOP_N]]
            up += ytd[pick].sum(); dn += dtd[pick].sum(); n += len(pick); rs.append(ft[pick].mean())
        print(f"  {label:16}{up / n * 100:10.1f}%{dn / n * 100:11.1f}%{np.mean(rs):+14.2f}%")

    # Direction: among the most volatile 20% (1-year), does anything separate big gains from big drops?
    hv = test & (X[:, names.index("vol1y")] >= 0.8)
    big = hv & (Yup | Ydn)
    print(f"\nmost volatile 20%, test period: {Yup[hv].mean()*100:.1f}% rose >10%, {Ydn[hv].mean()*100:.1f}% fell >10%")
    print(f"{'feature':16}{'AUC gain':>9}{'AUC drop':>9}{'up vs down':>11}   (within that group; up vs down = only stock-days that moved >10%)")
    for j, n in enumerate(names):
        print(f"{n:16}{auc(X[hv, j], Yup[hv]):9.3f}{auc(X[hv, j], Ydn[hv]):9.3f}{auc(X[big, j], Yup[big]):11.3f}")


if __name__ == "__main__":
    main()
