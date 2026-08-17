# Baizora Score Family — Backtest Scripts

These scripts reproduce the numbers published in `assets/baizscore_backtest.html` /
`_cn.html`. The report itself says it should be re-run roughly **annually** as more
data accumulates — this directory is what to run when that's due.

## Rules these scripts follow (keep following them)

- **Never persist raw per-row output.** Every script here prints summary stats to
  stdout only. The one exception is `backfill_score_trend.py`, which writes real
  production data (`data/baiz_score_trend.json`) — that's a shipping feature's seed
  data, not a backtest artifact, so it's meant to be committed.
- **yfinance is the data source** (`scanner_yfinance.fetch_yfinance_bulk`), 4 years
  of daily bars, chunked fetch. `BRK.B`/`BF.B` reliably fail (yfinance ticker-format
  mismatch) — expected, not a bug, ~516/518 tickers succeed.
- **`BURN_IN = 252`** (in `baizscore_backtest.py`) — a ticker-day only counts once it
  has a full trailing year of history, so early listings/thin-history tickers are
  excluded rather than scored on partial data.
- **Median is the primary metric, not mean** — stock return distributions are
  right-skewed; mean edges run 2–3× larger than median throughout. Report median,
  keep mean as a secondary reference.
- **`RSScore`/`MomentumScore` are cross-sectional percentile ranks per calendar
  date across the full universe** (`groupby("Date")...rank(pct=True)`), not
  per-ticker. Every script here replicates this — don't compute a ticker's score
  from its own history in isolation.

## `baizscore_backtest.py` — base module + BaizScore upside

Every other script imports `load_universe()` / `compute_ticker_frame()` /
`BURN_IN` from this file — it has to exist alongside the others. Run standalone,
it also reproduces BaizScore's own upside numbers (Section 03 of the report) at
whatever `SCORE_THRESHOLD` is set to (default `70` — edit and re-run for `80`
and `90`, the report's three published tiers). Writes `baiz_score_history.csv`
and `baiz_score_summary.csv`/`.json` as a byproduct — **delete these after
reading the numbers off, per the no-raw-data rule above.**

## `low_score_backtest.py` — BaizScore downside (Section 03b)

Tests `BaizScore <= 10/20/30` for decline prediction. Self-contained, no CSV
dependency.

## `weight_scenarios.py` — weighting comparison (Section 04)

Tests 6 weighting schemes (current/equal/pure-momentum/momentum-amplified/
technical-tilted/trend-consistency) at all three thresholds. **Depends on
`baiz_score_history.csv`** — run `baizscore_backtest.py` first to generate it,
then this script, then delete the CSV.

## `conviction_backtest.py` — BaizPersist + BaizConviction + decile checks (Sections 03d/03e)

The big one. Computes: BaizScore baseline (on the persistence-eligible sample,
which is slightly smaller than the full 380k — footnote this in the report same
as before), BaizPersist alone at ≥30/≥50/≥70, BaizConviction at several
thresholds plus **head-to-head at matched sample size vs BaizScore** (the
report's headline BaizConviction finding), and a **decile monotonicity check**
for BaizScore/BaizPersist/BaizConviction (does "higher score → better return"
actually hold across the whole range, not just at a threshold — there's a real,
consistent dip in the lowest deciles at the 12-month horizon, a likely deep-value/
mean-reversion effect; expect it to still be there, it's not a fluke to "fix").

## `low_conviction_backtest.py` — downside check for the derived scores

Tests whether BaizPersist/BaizConviction's low ends are *better* decline
predictors than raw BaizScore's low end. Found no — slightly worse, not better.
Re-run this if BaizConviction's formula ever changes; it's what backs the
"asymmetry isn't fixed by recombining the same ingredients" claim in Section 03b.

## `fresh_crossing_backtest.py` / `persistence_backtest.py` — design-exploration, not directly published

`fresh_crossing_backtest.py` tested whether a score *crossing* a threshold after
being below it for 3 months predicts differently than just being above it —
found no, the edge is in sustained strength, not the crossing event. Not in the
report; keep for reference if this question comes up again.

`persistence_backtest.py` is the count-based persistence grid (1/2/3-month
windows × 2+/5+/10+ count × 70/80/90 threshold) that originally motivated
BaizPersist's design, before it was redefined as a smooth trailing average
(count-based buckets collapsed `pd.qcut` deciles badly — ~38% of observations
sat at exactly 0). Superseded by `conviction_backtest.py`'s cleaner BaizPersist
test; keep for the historical "why a smooth average, not a count" reasoning.

## `turn_score_backtest.py` — TurnScore, removed 2026-08-17

TurnScore was retroactively backtested for the first time here and **failed** —
its own claimed "25–49 = emerging signal" tier had a negative median edge at 3
of 5 horizons, and the "50+ = strong signal" tier that did show a real edge was
only 308–434 observations, thinner than BaizScore's own thin 90+ tier. The score
was removed from the product entirely (see git log `81d0aec`). Kept here only in
case a redesigned reversal-style score is ever attempted again — there's nothing
in the current report to regenerate from it.

## `backfill_score_trend.py` — one-time seed for the dashboard sparklines

Not a "report" script — this seeds `data/baiz_score_trend.json` (the rolling
252-session score history feeding the BAIZORA tab's sparklines) by replaying the
real scoring methodology across the full trailing year. Already run once
(2026-08-17, 512 tickers). Only re-run this if the trend file is ever lost/
corrupted — the live scanner maintains it incrementally on its own otherwise
(see `_update_score_trends()` in `scanner_tiingo.py`).

## Suggested order for a full annual re-run

1. `baizscore_backtest.py` with `SCORE_THRESHOLD = 70`, then `80`, then `90` — Section 03 upside.
2. `low_score_backtest.py` — Section 03b downside.
3. `weight_scenarios.py` (needs step 1's CSV) — Section 04.
4. `conviction_backtest.py` — Sections 03d/03e, plus the decile checks.
5. `low_conviction_backtest.py` — the downside-asymmetry footnote in Section 03e.
6. Update the report's numbers, chart widths (unified `scale_max` — pick the new largest value on the page, recompute every bar), N-counts, and the "Published"/date line in both `assets/baizscore_backtest.html` and `_cn.html`.
7. Delete any CSV byproducts before committing.
