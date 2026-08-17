"""
Backtest two proposed new scores derived from the persistence findings:

  BaizPersist    = 0.5*trailing21davg(BaizScore) + 0.3*trailing42davg(...) + 0.2*trailing63davg(...)
                   -- a smooth, recency-weighted blend of 1M/2M/3M average score
  BaizConviction = sqrt(BaizScore * BaizPersist)   -- geometric mean, needs BOTH high

Checks (a) whether thresholding on these beats thresholding on BaizScore alone
at matched sample size, and (b) whether "higher score -> better forward return"
holds smoothly across the WHOLE decile range, not just at a cutoff. No raw
per-row data persisted.
"""
import sys
import os
import pandas as pd
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backtests/ -> repo root
sys.path.insert(0, REPO)

from scanner_yfinance import fetch_yfinance_bulk  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from baizscore_backtest import load_universe, compute_ticker_frame, BURN_IN  # noqa: E402

FWD_HORIZONS = {"3M": 63, "6M": 126, "9M": 189, "1Y": 252}
PERSIST_WINDOWS = {"1M": 21, "2M": 42, "3M": 63}
PERSIST_WEIGHTS = {"1M": 0.5, "2M": 0.3, "3M": 0.2}   # recency-weighted blend
PERSIST_THRESH = 70


def summarize(sub, base_stats, label):
    n = len(sub)
    print(f"\n=== {label} (N obs = {n:,}) ===")
    if n == 0:
        return
    for h in FWD_HORIZONS:
        col = f"Fwd{h}"
        f_ = sub[col].dropna()
        if len(f_) == 0:
            print(f"  {h}: N=0")
            continue
        bmean, bmed = base_stats[h]
        print(f"  {h}: N={len(f_):6d}  mean={f_.mean():7.3f}% (base {bmean:6.3f}%, edge={f_.mean()-bmean:7.3f}pp)"
              f"   median={f_.median():7.3f}% (base {bmed:6.3f}%, edge={f_.median()-bmed:7.3f}pp)"
              f"  win={((f_ > 0).mean() * 100):5.2f}%")


def main():
    tickers, sp_set, nd_set = load_universe()
    print(f"Universe: {len(tickers)} tickers")

    print("Fetching 4y OHLCV via yfinance (chunked) …")
    bars_by_ticker = fetch_yfinance_bulk(tickers, period="4y")
    print(f"Fetched bars for {len(bars_by_ticker)}/{len(tickers)} tickers")

    frames = []
    for t in tickers:
        f = compute_ticker_frame(t, bars_by_ticker.get(t))
        if f is not None:
            frames.append(f)
    print(f"Built per-ticker frames for {len(frames)} tickers")

    all_df = pd.concat(frames, ignore_index=True)

    all_df["RSScore"] = all_df.groupby("Date")["_RawRS"].rank(pct=True)
    all_df["RSScore"] = (all_df["RSScore"] * 98 + 1).round().clip(1, 99).astype(int)
    all_df["MomentumScore"] = all_df.groupby("Date")["_RawMomentum"].rank(pct=True)
    all_df["MomentumScore"] = (all_df["MomentumScore"] * 100).round().clip(0, 100).astype(int)

    rs_norm = (all_df["RSScore"] - 1) / 98 * 100
    vp_norm = (all_df["VolPressureScore"] + 100) / 2
    all_df["BaizScore"] = (
        0.30 * rs_norm + 0.25 * all_df["MomentumScore"] + 0.20 * all_df["BreakoutScore"]
        + 0.15 * all_df["TrendScore"] + 0.10 * vp_norm
    ).round().clip(0, 100).astype(int)

    all_df = all_df.sort_values(["Ticker", "RowIdx"]).reset_index(drop=True)

    # smooth trailing average of the raw score itself (not a threshold-count) --
    # avoids the "many observations exactly 0" artifact a count-based measure gets
    # whenever a stock simply never touched the threshold in the window
    persist_parts = {}
    for wlabel, wdays in PERSIST_WINDOWS.items():
        roll_avg = (
            all_df["BaizScore"].groupby(all_df["Ticker"])
            .transform(lambda s, w=wdays: s.rolling(w, min_periods=w).mean())
        )
        persist_parts[wlabel] = roll_avg
        all_df[f"Persist_{wlabel}"] = persist_parts[wlabel]

    all_df["BaizPersist"] = sum(PERSIST_WEIGHTS[w] * persist_parts[w] for w in PERSIST_WINDOWS)
    all_df["BaizConviction"] = np.sqrt(all_df["BaizScore"].clip(lower=0) * all_df["BaizPersist"].clip(lower=0))

    # 1M-only versions, for a direct "does adding 2M/3M actually help" comparison
    all_df["BaizPersist_1Monly"] = persist_parts["1M"]
    all_df["BaizConviction_1Monly"] = np.sqrt(all_df["BaizScore"].clip(lower=0) * all_df["BaizPersist_1Monly"].clip(lower=0))

    max_window = max(PERSIST_WINDOWS.values())
    eligible = all_df["RowIdx"] >= (BURN_IN + max_window - 1)
    scoreable = all_df[eligible & all_df["BaizPersist"].notna()].copy()
    print(f"\nEligible observations (score + persistence both valid): {len(scoreable):,}")

    base_stats = {h: (scoreable[f"Fwd{h}"].dropna().mean(), scoreable[f"Fwd{h}"].dropna().median()) for h in FWD_HORIZONS}

    print("\n########## BASELINE: plain BaizScore thresholds (for comparison) ##########")
    for thresh in [70, 80]:
        sub = scoreable[scoreable["BaizScore"] >= thresh]
        summarize(sub, base_stats, f"BaizScore >= {thresh}")

    print("\n########## BaizPersist alone ##########")
    for thresh in [30, 50, 70, 90]:
        sub = scoreable[scoreable["BaizPersist"] >= thresh]
        summarize(sub, base_stats, f"BaizPersist >= {thresh}")

    print("\n########## BaizConviction (sqrt(BaizScore * BaizPersist)) ##########")
    for thresh in [40, 50, 60, 70, 80]:
        sub = scoreable[scoreable["BaizConviction"] >= thresh]
        summarize(sub, base_stats, f"BaizConviction >= {thresh}")

    print("\n########## HEAD-TO-HEAD at matched sample size ##########")
    # find BaizConviction threshold giving ~same N as BaizScore>=70, and >=80
    for target_thresh, target_label in [(70, "BaizScore>=70"), (80, "BaizScore>=80")]:
        target_n = len(scoreable[scoreable["BaizScore"] >= target_thresh])
        # binary search a BaizConviction cutoff giving ~matched N
        lo, hi = 0.0, 100.0
        for _ in range(30):
            mid = (lo + hi) / 2
            n = len(scoreable[scoreable["BaizConviction"] >= mid])
            if n > target_n:
                lo = mid
            else:
                hi = mid
        matched_cut = lo
        sub_conv = scoreable[scoreable["BaizConviction"] >= matched_cut]
        print(f"\n-- matched to {target_label} (N={target_n:,}): BaizConviction >= {matched_cut:.2f} (N={len(sub_conv):,}) --")
        summarize(sub_conv, base_stats, f"BaizConviction >= {matched_cut:.2f} (N-matched to {target_label})")

    print("\n########## MULTI-WINDOW (1M/2M/3M blend) vs 1M-ONLY, matched sample size ##########")
    for target_thresh, target_label in [(70, "BaizScore>=70"), (80, "BaizScore>=80")]:
        target_n = len(scoreable[scoreable["BaizScore"] >= target_thresh])

        def matched_cutoff(col):
            lo, hi = 0.0, 100.0
            for _ in range(30):
                mid = (lo + hi) / 2
                n = len(scoreable[scoreable[col] >= mid])
                if n > target_n:
                    lo = mid
                else:
                    hi = mid
            return lo

        cut_multi = matched_cutoff("BaizConviction")
        cut_1m = matched_cutoff("BaizConviction_1Monly")
        sub_multi = scoreable[scoreable["BaizConviction"] >= cut_multi]
        sub_1m = scoreable[scoreable["BaizConviction_1Monly"] >= cut_1m]
        print(f"\n-- both matched to {target_label} (N={target_n:,}) --")
        summarize(sub_multi, base_stats, f"BaizConviction (1M/2M/3M blend) >= {cut_multi:.2f}  [N-matched to {target_label}]")
        summarize(sub_1m, base_stats, f"BaizConviction (1M-only) >= {cut_1m:.2f}  [N-matched to {target_label}]")

    print("\n########## DECILE MONOTONICITY CHECK ##########")
    print("(is 'higher score -> better forward return' actually true across the WHOLE range, not just at a threshold?)")
    for score_col in ["BaizScore", "BaizPersist", "BaizConviction"]:
        print(f"\n--- {score_col} deciles ---")
        try:
            deciles = pd.qcut(scoreable[score_col], 10, labels=False, duplicates="drop")
        except ValueError as e:
            print(f"  could not decile ({e})")
            continue
        n_bins = deciles.max() + 1
        for h in FWD_HORIZONS:
            col = f"Fwd{h}"
            row_means, row_meds, row_ns, row_ranges = [], [], [], []
            for d in range(n_bins):
                mask = deciles == d
                f_ = scoreable.loc[mask, col].dropna()
                score_range = scoreable.loc[mask, score_col]
                row_means.append(f_.mean() if len(f_) else float("nan"))
                row_meds.append(f_.median() if len(f_) else float("nan"))
                row_ns.append(len(f_))
                row_ranges.append((score_range.min(), score_range.max()))
            # monotonicity: count of decile-to-decile increases in median return
            diffs = [row_meds[i + 1] - row_meds[i] for i in range(len(row_meds) - 1) if not (np.isnan(row_meds[i]) or np.isnan(row_meds[i + 1]))]
            n_up = sum(1 for d in diffs if d > 0)
            print(f"  {h}: median return by decile (low->high score) = " +
                  " | ".join(f"{m:6.2f}%" for m in row_meds) +
                  f"   [{n_up}/{len(diffs)} decile-steps increasing]")
        # print score ranges per decile once (score doesn't change per horizon)
        print("  decile score ranges: " + " | ".join(f"[{lo:.0f}-{hi:.0f}]" for lo, hi in row_ranges))
        print("  decile N: " + " | ".join(f"{n:,}" for n in row_ns))

    print("\nDone. (no raw data files written)")


if __name__ == "__main__":
    main()
