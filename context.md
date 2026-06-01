# Baizora Scanner - Project Context

## Status: Massive API migration COMPLETE and stable

`scanner_massive.py` is live in production. `scanner_yfinance.py` kept as reference only.

---

## Current Data Quality (as of 2026-05-31)

| Metric | Status |
|---|---|
| Total tickers | 516 (503 S&P 500 + 101 Nasdaq-100, union) |
| Unknown sectors | 0 |
| EPS coverage | 505/516 (98%) |
| Missing name/mktcap | 0 |

---

## EPS Calculation (complex — key bugs fixed 2026-05-30/31; diluted-first since 2026-06-01)

**Fields tried in order (diluted first — matches Yahoo Finance TTM P/E methodology):**
1. `EarningsPerShareDiluted`
2. `EarningsPerShareBasic`
3. `IncomeLossFromContinuingOperationsPerDilutedShare` — REITs use this
4. `IncomeLossFromContinuingOperationsPerBasicShare`

**Algorithm:**
- Many companies file YTD cumulative EPS in 10-Qs (Q2=6mo, Q3=9mo). `_derive_quarterly_eps()` detects YTD by period length and derives quarterly values by differencing.
- **Q4 from annual 10-K:** Q4 is never in a 10-Q. Derived as Annual_10K − Q3_9month_YTD. This gives correct TTM for non-December fiscal year companies (AAPL, NVDA, COST, LITE, etc.)
- **Recency check:** Annual fallback only used if 10-K is within 2 years. Stale data → return None, not old numbers.
- **Annual across all fields:** Best annual is tracked across all 4 fields before falling back — no early return from stale data in first field.

**Special cases:**
- `BRK-B`: EDGAR EPS is at Class A level → divide by 1500 for Class B
- `BKNG`: 25-for-1 stock split April 2026 → divide by 25. Guard `eps > 25` auto-disables once Q2 2026 10-Q is filed (~Aug 2026) with post-split EPS.
- Foreign IFRS filers (CCEP, FER, TRI, ASML, PDD): no US-GAAP EPS in EDGAR → None
- Visa (V): no XBRL EPS data at all in EDGAR → None

**EPS=None tickers (11):** CCEP, FER, TRI, ASML, PDD, V, ERIE, ARES, KKR, STZ, ARM

---

## Sector Mapping

0 Unknown. 65 Massive ALL-CAPS SIC descriptions + `TICKER_SECTOR_OVERRIDE` for 26 tickers.

**SIC misclassification overrides added 2026-05-31:**
- Consumer Cyclical: ABNB, BKNG, CCL, DASH, EBAY, EXPE, MELI, NCLH, POOL, RCL, UBER
- Financial Services: CPAY, FIS, FISV, GPN, MA, MSCI, PYPL, V
- Technology: ACN, AKAM, FICO, GLW, GRMN, IT, KEYS, LRCX, TRMB, ZBRA
- Healthcare: DHR, TMO
- Real Estate: CSGP
- Basic Materials: AMCR

**Sector distribution (post-fix):**
Technology 96 / Financial Services 75 / Consumer Cyclical 61 / Healthcare 60 / Industrials 59 / Consumer Defensive 38 / Basic Materials 32 / Real Estate 31 / Utilities 31 / Energy 21 / Communication Services 12

---

## Sector Average PE

Uses **market-cap weighted harmonic mean**: `sum(MarketCap) / sum(MarketCap / PE)`

Equivalent to total sector market cap / total sector implied earnings — same method as S&P sector indices. Robust to high-PE outliers (DDOG 634x, MCHP 430x no longer distort averages).

Example Technology sector: simple mean was 62.9x → weighted harmonic mean is 34.5x.

---

## OHLCV Cache

- Per-day files: `data/ohlcv_cache/{date}.json`
- Files <5 bytes treated as missing and retried every run
- `check_data_quality()` runs after every scan — flags >25% 1D change, <200 candle bars, empty files
- Special closure detection: probes Massive before scanning; if 0 results on a weekday → skip (handles presidential funerals etc.)
- **2025-01-09:** Jimmy Carter state funeral — Massive returns 0 results, now auto-detected

**TICKER_ALIASES** (internal → Massive format):
- `"BNY": "BK"` — Massive returns "BK" for Bank of New York Mellon
- `"BF-B": "BF.B"` — Massive uses dots, symbol list uses hyphens
- `"BRK-B": "BRK.B"` — same

**BNY cache fix (2026-05-31):** 159 corrupted entries (~$10 close, old ticker) purged. 143 clean entries remain. 9M/1Y price changes unavailable until ~4 more months of history accumulates. Beta null until next scan.

**Dot-format fallback in `get_fundamentals`:** if Massive returns no name for a hyphen ticker, retries with dot format.

---

## GitHub Actions Schedule

- **Weekdays 8:30 PM UTC:** incremental scan
- **Saturday midnight UTC:** same incremental scan (wipe step removed — wipe risked broken dashboard all weekend if rebuild failed)

---

## Known Data Limitations

- **BNY:** 9M/1Y price changes null; Beta null (recomputed on next scan). Candle chart shows Jun 2025–present only (143 clean bars).
- **FISV, MRSH, Q:** short candle history (Massive data gap, not code bug)
- **BF-B, BRK-B:** ~108 candle bars — dot/hyphen mismatch meant old cache files missed them; history accumulates going forward

---

## Dashboard

- Ticker click → modal with 1Y candlestick chart + P/E, EPS, Beta, Vol30D, MarketCap, Sector
- Modal header: 1D price change badge (green/red) displayed next to price
- Modal stats grid: Volume (M), 1M/3M/1Y price change tiles with green/red coloring added (2026-06-01)
- Close button: fixed `type=module` scope bug — `onclick` attribute can't reach module functions; replaced with `addEventListener` inside module (both EN and CN files)
- Candle data: separate `data/candles.json`, loaded after table renders
- **Watchlist** (added 2026-06-01): ☆ star icon on every row; click to save/remove. Stored in `localStorage` under `"baizora_watchlist"`. Dedicated "★ Watchlist" tab (EN) / "★ 自选股" tab (CN) shows saved tickers with full table/sort/filter. Persists across page refreshes; shared between EN and CN versions.

---

## Methodology Document

- File: `assets/methodology_2026-05-31.html` — comprehensive internal documentation (updated 2026-06-01 for diluted EPS + Beta fix)
- Covers: data universe, sources (Polygon + EDGAR), daily pipeline, OHLCV cache, volume definition, all metric formulas, TTM EPS derivation, sector classification, market-cap weighted harmonic mean sector PE, all four scores, output format, known limitations
- Versioned by date; create a new file (e.g. `methodology_2026-12-31.html`) when methods change significantly

---

## SPY / Beta

- SPY fetched fresh each scan via `/v2/aggs/ticker/SPY/range/1/day/{from}/{to}` (not in OHLCV cache)
- **Retry count increased to 8** (was 3) on 2026-06-01 after SPY silently failed under rate limiting, leaving Beta null for all 516 tickers
- Failure now logs explicitly: "SPY fetch returned no data — beta will be None" (visible in GitHub Actions logs)
- If SPY fails after 8 retries, Beta is null for all tickers that run

---

## Next Time: What to Check

1. Check GitHub Actions run succeeded (no rate-limit failures overnight)
2. Run `data quality warnings` from latest scanner log — check for "SPY fetch returned no data"
3. BNY — 9M/1Y price changes will fill in over ~4 months
4. BKNG split guard — once Q2 2026 10-Q is filed (~Aug 2026), verify `eps > 25` guard auto-disables correctly
5. Remaining 11 EPS=None tickers — any solvable without a paid data source?
6. **EPS cache rebuild caution** — if fundamentals cache must be deleted, patch sector/marketcap from old cache before re-running (267 tickers lost data on 2026-06-01 due to rate limiting). Script: restore old cache from git, merge Sector/MarketCap/CompanyName for Unknown/null entries.
