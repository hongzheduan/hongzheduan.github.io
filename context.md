# Baizora Scanner - Project Context

## Status: Temporarily on yfinance (2026-06-02) — dashboard free to logged-in users

`scanner_yfinance.py` is live in production (free, bridge while shopping data providers).
`scanner_massive.py` kept as backup — restore by changing `scanner.yml` run command + adding `MASSIVE_API_KEY` secret.
Scanner cron paused. Dashboard free for any logged-in user (no subscription check).

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

- **Weekdays 9:30 PM UTC (5:30 PM ET):** scanner + daily videos (re-enabled after switching to yfinance)
- Videos skipped on weekends and holidays

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

## Billing / Subscriptions (as of 2026-06-02)

- **Subscriptions temporarily paused** — `billing.html` and `billing_cn.html` redirect to pricing page with maintenance banner
- Do NOT re-enable billing until a data provider is confirmed and the paid gate is restored

---

## ⚠️ WHEN WE START CHARGING — Full Revert Checklist

All 6 files below were changed for free mode. Revert ALL of them together.

### 1. `login.html` and `login_cn.html`
Comment out the direct redirect and uncomment the `isActive` ternary:
```js
// Remove this line:
window.location.href = "dashboard.html";  // or dashboard_cn.html

// Uncomment this line:
// window.location.href = isActive ? "dashboard.html" : "billing.html";
```

### 2. `baizora_main_form.html` and `baizora_main_form_cn.html`
Inside `onAuthStateChanged`, uncomment the subscription fetch block and remove the free `loadDashboard()` call:
```js
// Uncomment this block:
// user.getIdToken().then(token =>
//   fetch("https://us-central1-baizora.cloudfunctions.net/api/subscription", ...)
//   .then(d => { if (d.status !== "active") window.location.href = "billing.html"; else loadDashboard(); })
// );

// Remove this line:
loadDashboard();
```

### 3. `dashboard.html` and `dashboard_cn.html`
Inside the `else` block (non-subscriber), restore the card-locking code:
```js
// Remove: text.textContent = "Free Access";  (or "免费开放中")
// Uncomment the full locking block below it (scannerCard.classList.add("locked") etc.)
```

### 4. `billing.html` and `billing_cn.html`
Remove the `<script>window.location.replace(...)` redirect at the top of each file.

### 5. `index.html` and `index_cn.html`
Restore the announcement bar text:
- EN: `First 7 Days Free · Contact: support@baizora.com`
- CN: `完全免费试用七天 · 联系我们：support@baizora.com`

### 6. Scanner
Confirm a paid data provider is active before re-enabling billing. Do NOT charge users while on yfinance data.

## Data Provider Status (as of 2026-06-02)

- **Massive:** $2000/mo commercial license (50% discount still = $1000/mo) — too expensive with no paying customers yet; **ruled out**
- **AlphaVantage:** $500/mo with 50% startup discount (~$250/mo) — potential candidate, inquiry in progress
- **EODHD:** inquiry sent 2026-06-02; Egor confirmed client-facing display = redistribution license (awaiting pricing)
- **Tiingo:** inquiry sent 2026-06-02 (awaiting reply)
- **FMP:** inquiry sent 2026-06-02 (awaiting reply)
- **Intrinio:** inquiry sent 2026-06-02 (awaiting reply)
- **yfinance:** currently active — free, ToS-gray, viable bridge. Do NOT re-enable billing while on yfinance.
- **Scanner paused** until a cost-appropriate provider is confirmed; do NOT re-enable billing until then

---

## OHLCV Data Timing Issue (fixed 2026-06-02)

- **Root cause:** Polygon free tier EOD grouped data is only available 9–10 PM ET; scanner was running at 4:30 PM ET → empty `{}` cache files written for current day → fallback to prior day's data
- **Fix:** Cron shifted to 9:30 PM UTC (5:30 PM ET). Requires paid Polygon tier to reliably get same-day data.
- `data/ohlcv_cache/2026-06-01.json` is `{}` — will be auto-retried next scan (files <5 bytes treated as missing)
- `scanner_massive.py` line 17: changed `os.environ["MASSIVE_API_KEY"]` → `os.environ.get("MASSIVE_API_KEY", "")` so module can be imported without the key (holiday check); fast-fail added in `__main__`
- `scanner.yml`: `MASSIVE_API_KEY` moved to workflow-level `env` block so all steps can import the module

---

## Scanner History Policy

- **Keep all archive CSVs** — `cleanup_old_archives()` is disabled in both scanners; every daily `archive/results_YYYY-MM-DD.csv` is committed to git permanently
- Do NOT re-enable the cleanup calls

---

## What Was Done 2026-06-04

- **BaizScore** (composite score) added to scanner and dashboard — weighted formula: RS 30% + Momentum 25% + Breakout 20% + Trend 15% + Vol Pressure 10%; gold column header in SCORES tab
- **TurnScore** (weak-to-strong reversal) added — formula: `Breakout × (1 − RS/100) × VP_norm`; blue column header; 3-tier indicator: ▲ 50+ green, → 25–49 amber, <25 red
- `data/ohlcv_cache/` deleted (retired `scanner_massive.py` artifact, ~20 MB of JSON files)
- Row limit raised from 200 → 600 across all SCORES/window sort slices
- Column hover tooltips fixed — dead `tickerTip`/`tickerHideTimer` references were silently killing all column mouseover handlers with a ReferenceError
- Price column removed from SCORES tab view (not relevant there)
- Announcement bar: added live date display (JS `toLocaleDateString`) to signal freshness
- Homepage "Ways to Explore" section: 4-card 2×2 grid — (1) Baizora Score merged with Use-Scores-as-Filter, (2) Volume Spike merged with Quiet Accumulation, (3) Multi-Week Momentum, (4) Index Rebalancing Tracker
- Homepage: new Candlestick Chart card replacing the merged scores card — shows real 1Y NVDA OHLC chart lazy-loaded from `data/candles.json` via IntersectionObserver
- Fact bar updated: 4× → 7× Daily Scores; hero bullet lists all 7 scores (Baizora · Turn · RS · Breakout · Momentum · Vol Pressure · Trend)
- Readme (INFO tab in dashboard) updated to document all 7 scores with formulas
- Nav: removed "Price Movers" and "Volume Movers" buttons from homepage

---

## What Was Done 2026-06-02 / 2026-06-03

- Switched active scanner to `scanner_yfinance.py`; fixed to produce same output as massive scanner (Beta, Vol30D, candles, market-cap weighted sector PE)
- Fixed candlestick chart: batch download now includes OHLCV (was Close+Volume only → all bars were flat dots)
- Candlestick modal: added 3M/6M/1Y timeframe toggle, defaults to 3M (63 bars = readable candles)
- Dashboard auth: login required, subscription check commented out (free mode); revert = uncomment fetch block in `onAuthStateChanged`
- Login redirects to `dashboard.html` (not billing); scanner card unlocked for all logged-in users
- Announcement bar updated to "Temporarily Free"
- Archive cleanup disabled permanently — all daily CSVs kept in git
- Data provider inquiries sent: EODHD, Tiingo, FMP, Intrinio
- Scanner cron + video pipeline re-enabled (weekdays 9:30 PM UTC)
- Added special market closure detection: SPY probe before scan, retries 3× every 30 min (90 min budget) before skipping

---

## What Was Done 2026-06-06

- `scanner_tiingo.py` created — Tiingo commercial API scanner
  - Per-ticker OHLCV cache (`ohlcv_tiingo_cache/{TICKER}.json`) replaces per-day cache
  - Initial run: full 2Y history fetched per ticker; daily update via one bulk call (`/tiingo/daily/prices`)
  - Market cap = EDGAR `EntityCommonStockSharesOutstanding` × current price (no stale API value)
  - EPS: EDGAR (same diluted-first TTM algorithm as scanner_massive.py)
  - SIC/sector: EDGAR submissions API (`/submissions/CIK{cik}.json`)
  - Company names: Tiingo meta batch call (`/tiingo/daily/meta`)
  - SPY: Tiingo `/tiingo/daily/spy/prices`
  - BaizScore + TurnScore included (same formulas as scanner_yfinance.py)
  - yfinance comparison step: flags price/volume diffs >5%, logs to `archive/compare_YYYY-MM-DD.log`
- `scanner.yml` updated: two cron triggers (22:00 UTC = 6 PM ET preliminary; 00:00 UTC = 8 PM ET final + videos); uses `TIINGO_API_KEY` secret; commits `archive/compare_*.log`
- **Next steps before activating:**
  1. Add `TIINGO_API_KEY` secret to GitHub repo settings
  2. Test locally: `TIINGO_API_KEY=xxx python scanner_tiingo.py` (verify bulk endpoint format, ticker casing)
  3. Add Tiingo attribution to dashboard pages (see item 7 below)
  4. Switch `scanner.yml` active scanner: already done (uses scanner_tiingo.py)
  5. Re-enable billing once first clean Tiingo run completes

---

## Next Time: What to Check

1. **scanner_tiingo.py first run** — watch for: bulk endpoint field names (adjClose vs close), BRK-B/BF-B lowercase format, BNY ticker (verify Tiingo returns `bny` not `bk`)
2. **Re-enable billing + paid gate:** remove redirect from `billing.html`/`billing_cn.html`; uncomment subscription fetch block in both dashboard files (checklist in context.md above)
3. BKNG split guard — once Q2 2026 10-Q is filed (~Aug 2026), verify `eps > 25` guard auto-disables correctly
4. Remaining 11 EPS=None tickers — any solvable without a paid data source?
5. **EPS cache rebuild caution** — if fundamentals cache must be deleted, patch sector from old cache before re-running
6. **Tiingo attribution** — add `"Market Data Sourced by Tiingo.com"` to dashboard pages (`baizora_main_form.html`, `baizora_main_form_cn.html`) and any data-facing product pages, per the license agreement requirement
