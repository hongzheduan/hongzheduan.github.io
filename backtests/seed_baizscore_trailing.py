"""
One-time seed of data/baizscore_trailing.json — the LIVE trailing-21-session
BaizScore window that scanner_tiingo.py's _compute_baiz_persist_and_conviction()
reads/writes to compute today's BaizPersist/BaizConviction.

This file was never seeded when backfill_score_trend.py backfilled
data/baiz_score_trend.json (the 1-year sparkline history). The two files are
independent: the trend file has plenty of historical BaizPersist/BaizConviction
values (correctly replayed), but the live trailing-window file was left empty,
so the daily scanner was starting its 21-session warmup from zero and would
have shown null BaizPersist/BaizConviction for another ~21 trading days despite
already having the data to compute it correctly right now.

Derives the seed directly from data/baiz_score_trend.json's BaizScore arrays
(last 21 entries per ticker) — this IS the correct trailing-21 state, since
backfill_score_trend.py already replayed BaizScore chronologically per ticker.

Writes real production state (data/baizscore_trailing.json), not a backtest
artifact — meant to be committed, per the same exception backfill_score_trend.py
follows (see backtests/README.md).
"""
import os
import json

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backtests/ -> repo root
TREND_FILE = os.path.join(REPO, "data", "baiz_score_trend.json")
OUT_FILE = os.path.join(REPO, "data", "baizscore_trailing.json")
PERSIST_WINDOW = 21


def main():
    with open(TREND_FILE) as f:
        trend = json.load(f)

    out = {}
    for ticker, scores in trend.items():
        baiz_vals = scores.get("BaizScore", [])
        out[ticker] = baiz_vals[-PERSIST_WINDOW:]

    with open(OUT_FILE, "w") as f:
        json.dump(out, f)

    n_ready = sum(1 for v in out.values() if len(v) >= PERSIST_WINDOW)
    print(f"Wrote {OUT_FILE} — {len(out)} tickers, {n_ready} with a full {PERSIST_WINDOW}-session window")
    sample = next(iter(out))
    print(f"Sample ({sample}): {out[sample]}")


if __name__ == "__main__":
    main()
