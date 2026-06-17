# Baizora Scanner - Project Context

## Status: Tiingo scanner LIVE (2026-06-07) — dashboard free to logged-in users

`scanner_tiingo.py` is live in production. Two daily cron runs (6 PM ET preliminary; 8 PM ET final + videos).
`scanner_yfinance.py` kept as backup. Billing still paused pending one clean week of Tiingo data.
Dashboard free for any logged-in user (no subscription check).

---

## Current Data Quality (as of 2026-06-07)

| Metric | Status |
|---|---|
| Total tickers | 516 (503 S&P 500 + 101 Nasdaq-100, union) |
| Unknown sectors | 0 |
| EPS coverage | 503/516 (97%) — 13 tickers have EPS=None |
| Company names | 516/516 (EDGAR CIK map fallback works even on Tiingo 502) |
| Missing mktcap | 0 |

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
- `BRK-B`: Berkshire stopped tagging EPS in EDGAR XBRL after 2013. Quarterly date filter (`end >= today-2yr`) correctly returns `eps=None` — no stale Class A data. BRK-B does not appear in PE/EPS display.
- `BKNG`: 25-for-1 stock split April 2026 → divide by 25. Guard `eps > 25` auto-disables once Q2 2026 10-Q is filed (~Aug 2026) with post-split EPS.
- `CVNA`: 5-for-1 stock split May 2026 (2026-05-08). Q1 2026 10-Q filed 2026-04-29 (pre-split). Guard: `eps > 4 → eps / 5`. Auto-disables once Q2 2026 10-Q (post-split) is filed (~Aug 2026).
- `KLAC`: 10-for-1 stock split 2026-06-12. Guard: `eps > 10 → eps / 10`. EDGAR already shows post-split shares (~1.3B). Auto-disables once Q4 FY2026 10-K or next 10-Q is filed with post-split EPS.
- Foreign IFRS filers (CCEP, FER, TRI, ASML, PDD): no US-GAAP EPS in EDGAR → None
- Visa (V): no XBRL EPS data at all in EDGAR → None

**`_derive_quarterly_eps` dedup (fixed 2026-06-07):** Some companies file BOTH an individual quarterly EPS AND a YTD cumulative EPS with the same `end` and `filed` date. Tiebreaker: prefer entry with `period ≈ 90 days` (individual quarter) over longer periods (H1=~180d, 9M=~270d). Without this, VRSN's 9M YTD entry was treated as a single quarter, inflating TTM.

**Quarterly date filter (fixed 2026-06-07):** `10-Q` entries now require `end >= (today-2yr)`, matching the annual filter. Without this, BRK-B's 12 stale 2013 quarterly EPS entries (~$7,219/share Class A) passed through and produced wrong EPS.

**EPS=None tickers (13):** CCEP, FER, TRI, ASML, PDD, V, ERIE, ARES, KKR, STZ, ARM, BRK-B, and possibly others with no recent EDGAR data

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

- **Weekdays 22:00 UTC (6 PM ET):** preliminary scan only (`IS_VIDEO_RUN=False`); commits data
- **Weekdays 00:00 UTC next day (8 PM ET):** final scan + daily videos (`IS_VIDEO_RUN=True`)
- Videos skipped on weekends and holidays
- Both runs use `scanner_tiingo.py` with `TIINGO_API_KEY` secret

---

## Known Data Limitations

- **BNY:** 9M/1Y price changes null; Beta null (recomputed on next scan). Candle chart shows Jun 2025–present only (143 clean bars).
- **FISV, MRSH, Q:** short candle history (Massive data gap, not code bug)
- **BF-B, BRK-B:** ~108 candle bars — dot/hyphen mismatch meant old cache files missed them; history accumulates going forward

---

## Dashboard

- Ticker click → modal with candlestick chart + P/E, EPS, Beta, Vol30D, MarketCap, Sector
- Modal header: ticker symbol, **company name** (`#modalName`, color `#94a3b8`), price, 1D price change (green/red)
- Timeframe toggle: 3M / 6M / 1Y (defaults to 3M = 63 bars); driven by `data/candles.json`
- Modal stats grid: Volume (M), 1M/3M/1Y price change tiles with green/red coloring
- Close button: fixed `type=module` scope bug — wired via `addEventListener` inside module (both EN and CN)
- **Watchlist** (2026-06-01): ☆ star icon; localStorage `"baizora_watchlist"`; "★ Watchlist" / "★ 自选股" tab

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

**Quick find:** Search `// TEMP:` and `<!-- TEMP:` across all HTML files — every item below is marked with one of these comments. Also search `// FREE MODE:` for the subscription check block in `baizora_main_form.html` / `_cn.html`.

All files below were changed for free mode. Revert ALL of them together.

### 1. `login.html` and `login_cn.html`
Comment out the direct redirect and uncomment the `isActive` ternary:
```js
// Remove this line:
window.location.href = "dashboard.html";  // or dashboard_cn.html

// Uncomment this line:
// window.location.href = isActive ? "dashboard.html" : "billing.html";
```

### 2. `baizora_main_form.html` and `baizora_main_form_cn.html`
Inside `onAuthStateChanged`:
- Restore the login gate (currently commented out):
```js
// Uncomment this line:
// if (!user) { window.location.href = "login.html"; return; }  // or login_cn.html
```
- Uncomment the subscription fetch block and remove the free `loadDashboard()` call:
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
Three changes:

**a) Restore login gate** (currently commented out):
```js
// Uncomment this:
// if (!user) { window.location.href = "login.html"; return; }  // or login_cn.html
```

**b) Restore "Free Preview" tool card** (currently commented out between `<!-- TEMP -->` markers):
```html
<a href="baizora_main_form_free.html" class="tool-card">
  <div class="tool-icon">⬡</div>
  <div class="tool-name">Free Preview</div>
  <div class="tool-desc">Top 3 movers from today's data — no login required. Share with anyone.</div>
  <div class="tool-tag tag-free">Free</div>
</a>
```
(CN: `baizora_main_form_free_cn.html`)

**c) Restore "Free Preview" quick link** (currently commented out between `<!-- TEMP -->` markers):
```html
<a href="baizora_main_form_free.html" class="quick-link">
  <span class="quick-link-icon">👁</span> Free Preview
</a>
```
(CN: `baizora_main_form_free_cn.html`)

**d) Restore card-locking for non-subscribers** (inside the `else` block):
```js
// Remove: text.textContent = "Free Access";  (or "免费开放中")
// Uncomment the full locking block below it (scannerCard.classList.add("locked") etc.)
```

### 4. `billing.html` and `billing_cn.html`
Remove the `<script>window.location.replace(...)` redirect at the top of each file.

### 5. `index.html` and `index_cn.html`
Four changes:

**a) Restore announcement bar text:**
- EN: `First 7 Days Free · Contact: support@baizora.com`
- CN: `完全免费试用七天 · 联系我们：support@baizora.com`

**b) Restore nav "Plans" link; remove "Full Dashboard" nav link:**
- EN: uncomment `<a href="pricing.html" class="nav-btn">Plans</a>`, remove the `Full Dashboard` nav `<a>` tag
- CN: uncomment `<a href="pricing_cn.html" class="nav-btn">价格方案</a>`, remove `完整数据` nav `<a>` tag

**c) Restore hero primary CTA button:**
- EN: change `View Full Dashboard — No Sign-up` → `Free Preview (No Sign-up)`, `href="baizora_main_form_free.html"`
- CN: change `查看完整数据 — 无需注册` → `免费预览（无需注册）`, `href="baizora_main_form_free_cn.html"`

**d) Restore hero secondary CTA button:**
- EN: change `View Full Dashboard` → `Free Preview`, `href="baizora_main_form_free.html"`
- CN: change `查看完整数据` → `免费预览`, `href="baizora_main_form_free_cn.html"`

### 6. `index_news.html` and `index_news_cn.html`
Restore login gate (currently commented out):
```js
// Uncomment this:
// if (!user) { window.location.href = "login.html"; return; }  // or login_cn.html
```

### 7. Scanner
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

## What Was Done 2026-06-07 (Evening Session)

### Individual Stock Pages (stocks/*.html)

- `generate_stock_pages.py` rewrote all 10 pages (NVDA, GOOGL, AAPL, MSFT, AMZN, AVGO, TSLA, META, WMT, MU)
- **SVG sparkline replaced with canvas candlestick + volume chart** — OHLCV data from `data/candles.json` embedded inline at generation time (no runtime API call); section title shows "Scan date: YYYY-MM-DD"
- **Live IEX price refresh** — same `/api/iex-quotes` Cloud Function as homepage; polls every 60s during market hours; updates price + 1D change on the page
- **Tiingo attribution** added to footer of each stock page: "Market Data Sourced by Tiingo.com"
- Canvas renderer: adapted from dashboard `renderCandleChart()`; OHLCV arrays embedded via `_SCRIPT_TEMPLATE` raw string with `__DATES__`/`__OHLCV__`/`__TICKER__` placeholders (avoids f-string curly-brace escaping)

### Dashboard Color Refinement (all 4 dashboard files)

Applied to `baizora_main_form.html`, `baizora_main_form_cn.html`, `baizora_main_form_free.html`, `baizora_main_form_free_cn.html`:

- **Column headers** (`th`): dimmed `var(--white)` → brighter `#e2e8f0` (headers now brighter than data)
- **Data cells** (`td`): `var(--muted)` → `#94a3b8` (dimmed)
- **Ticker + Price cells**: `var(--white)` → `#94a3b8`
- **Positive/negative CSS vars**: `--positive: #64c487; --negative: #c46464;` (muted green/red — HSL ~45% saturation, ~58% lightness)
- **`.neutral`**: `var(--muted)` → `#94a3b8`

### Homepage Color Refinement (index.html + index_cn.html)

- **Popular stocks section** — `.dr-tk`, `.tk-val`, `.dr-pr`: `#ffffff` → `#94a3b8`; `.dr-pos`: → `#64c487`; `.dr-neg`: → `#c46464`; `.spark-ticker`, `.up-c`, `.dn-c`, `.tk-pos`, `.tk-neg`, `.up`, `.dn` also updated
- **Hero bullets** (`.hero-bullet`): `#e2e8f0` → `#94a3b8`; removed bold weight + gold color from promo box and "Simple by design…" bullet

### Dashboard Welcome Page

- `dashboard.html` + `dashboard_cn.html`: `.page-title` color `var(--white)` → `#94a3b8` ("Welcome back" / "欢迎回家")

---

## What Was Done 2026-06-08

### Video Schedule: Moved to 6 PM ET

- `IS_VIDEO_RUN` detection in `scanner.yml` changed from `HOUR=00||01` to `HOUR=22||23`
- Two crons now clearly separated: `0 22 * * 1-5` = 6 PM ET preliminary scan (no videos); `0 0 * * 2-6` = 8 PM ET final scan + videos
- Updated cron comments in `scanner.yml` to match

### FAQ Updates

- `assets/faq.html`: Updated "When is data updated?" to describe dual-run schedule (6 PM preliminary + 8 PM final); added new FAQ item "How current is the P/E and EPS data?" explaining TTM diluted GAAP EPS from SEC EDGAR XBRL
- `assets/faq_cn.html`: Synced with EN — translated both FAQ updates into Chinese
- `assets/methodology_2026-05-31.html`: Replaced all Polygon.io references with Tiingo; updated cache structure, volume definition, schedule section, added Q3 YTD search note; version date updated to 2026-06-07

### Candlestick Chart Date Improvements

Applied to all 4 dashboard files (`baizora_main_form.html`, `baizora_main_form_cn.html`, `baizora_main_form_free.html`, `baizora_main_form_free_cn.html`):

1. **Adaptive x-axis date labels:** 3M (n<100) → bi-weekly with "Apr 7"; 6M (n<200) → monthly with year suffix on year changes ("Jun '25"); 1Y (n≥200) → every other month (~6 labels). Timezone fix: `new Date(d + 'T12:00:00')`.
2. **Top-right "as of [date]" label:** 10px DM Mono `#475569` at `(W - pad.right, pad.top - 4)`, shows the latest data date so users know data is current.

### Live IEX Prices on Homepage

- **Cloud Function `GET /api/iex-quotes`** added to `functions/index.js`: proxies Tiingo IEX endpoint for 10 homepage tickers (NVDA,GOOGL,AAPL,MSFT,AMZN,AVGO,TSLA,META,WMT,MU); 60s in-memory cache caps Tiingo calls to ~1,440/day
- **`TIINGO_API_KEY`** set as Firebase secret via `echo "KEY" | firebase functions:secrets:set TIINGO_API_KEY` (piped stdin — interactive prompt not supported in Claude Code terminal)
- **`index.html` and `index_cn.html`**: added `refreshPrices()` IIFE — loads on page, then polls every 60s during market hours (Mon–Fri 9:30–16:00 ET via `America/New_York` timezone). Updates rolling ticker bar HTML + demo table `MOCK_DATA` prices.
- Functions deployed via `firebase deploy --only functions`
- **Pending verification:** live IEX polling must be checked during market hours (next opportunity 2026-06-09 Monday)

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

## What Was Done 2026-06-07

### scanner_tiingo.py — Three EPS Fixes

**Fix 1: VRSN EPS dedup tiebreaker (`_derive_quarterly_eps`)**
- Root cause: VRSN files BOTH an individual quarterly EPS and a YTD cumulative EPS with the same `end` + `filed` date. Python's stable sort picked arbitrarily; sometimes 9M YTD ($6.58) won over Q3 ($2.27). The 9M entry had no prior YTD to subtract from, so it was treated as a single quarter, producing wrong TTM.
- Fix: sort tiebreaker by `-abs(period_days - 90)` — prefers entries closest to 90-day individual quarters. Period ≈ 90 for individual quarters, ≈ 180 for H1 YTD, ≈ 270 for 9M YTD.
- Result: VRSN EPS 2.07 → 9.05 (matches yfinance; diff gone from compare log)

**Fix 2: BRK-B stale quarterly entries (quarterly date filter)**
- Root cause: 10-Q entries had NO date filter. BRK-B's 12 stale 2013 quarterly EPS entries (~$7,219/share Class A) passed through, summed 4 quarters of 2013 → ÷1500 = $4.81 Class B EPS (wrong).
- Fix: `q10_entries` now filtered by `end >= min_annual_end` (same `today-2yr` cutoff as annual entries).
- Result: BRK-B → EPS=None (Berkshire has no EDGAR XBRL EPS data after 2013). No longer appears in compare log.

**Fix 3: CVNA 5:1 split EPS guard**
- Root cause: CVNA's 5-for-1 split was 2026-05-08. Q1 2026 10-Q was filed 2026-04-29 (pre-split). Shares were correctly multiplied by 5 via `_get_post_filing_split_factor`, but EPS was not divided by 5.
- Fix: explicit guard `if ticker == "CVNA" and eps is not None and eps > 4: eps = round(eps / 5, 4)`. Matches BKNG ÷25 pattern. Auto-disables once Q2 2026 10-Q (post-split) is filed (~Aug 2026).
- Result: CVNA EPS 10.20 → 2.04

### Company Name Fallback

- Root cause: Tiingo meta endpoint returned HTTP 502 in both recent scans → `tiingo_names={}` → all 516 `CompanyName` fields empty in cache and `latest.json`.
- Fix 1 (immediate): one-time script fetched all names from SEC EDGAR CIK map (`company_tickers.json`) — single HTTP call covers all 516 tickers. Patched `fundamentals_cache.json` and `latest.json`.
- Fix 2 (permanent): `_load_edgar_cik_map()` now also builds `_edgar_name_map` (ticker → title from CIK JSON). `get_fundamentals` uses it as fallback when both Tiingo and cache CompanyName are empty. Covers both cached and newly-fetched tickers.

### Compare Log Status (2026-06-07)
- VRSN: fixed ✓ (not in log)
- BRK-B: fixed ✓ (not in log)
- CVNA: fixed ✓
- Remaining flagged EPS diffs are expected GAAP vs adjusted differences (OXY, MLM, CI, HSY, GD, TXT, BDX, etc.) — our GAAP TTM is correct; yfinance uses analyst "adjusted" EPS

### Tiingo Scanner Activated
- `scanner_tiingo.py` committed and now the active scanner in `scanner.yml`
- First complete scan with all fixes ran 2026-06-07; compare log clean of structural EPS bugs
- Modal company name confirmed working (was already wired up as `#modalName` in prior session)

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

## What Was Done 2026-06-16/17

### Auth State on Free Preview Pages

- **Problem:** After navigating from dashboard → free preview, user appeared signed out.
- **Fix:** Added Firebase compat SDK (`firebase-app-compat.js`, `firebase-auth-compat.js`) + `onAuthStateChanged` to both `baizora_main_form_free.html` and `baizora_main_form_free_cn.html`. Now shows Sign Out + user email when logged in (same pattern as homepage nav).

### Free Preview Mobile Header — Tab Row

- **Problem:** Mobile header too crowded; S&P 500 / Nasdaq 100 / README / MEMBERSHIP CHANGE buttons in the header caused "Upgrade" button to be cut off.
- **Fix:** Moved the 4 section-tab buttons to a new sticky `<div class="tab-row">` between the `</header>` and toolbar. `.tab-row { position:sticky; top:56px; z-index:60; height:40px }`. Updated `.toolbar { top:96px }` (was 56px). JS selectors updated from `.tab-nav .tab-btn` → `.tab-row .tab-btn` across `drawerSection()` and `showMobileTab()`.
- Applied to `baizora_main_form_free.html` (EN version — CN version has no tab row issue).

### Chat Widget Mobile iOS Fixes (chat-widget.js, v3 → v8)

Multiple layered iOS Safari bugs addressed:

**v4 — bottom:72px:** Initial attempt to clear iOS Safari navigation toolbar (~49px). Not sufficient for newer iPhones (toolbar + home indicator = ~83px).

**v5 — positionBtn() with visualViewport:** Attempted JS positioning using `window.visualViewport.width` to avoid layout viewport inflation. Caused wrong positioning because `visualViewport` still returns layout viewport width in some scenarios.

**v6 — append to `<html>`, restore CSS right:14px:** Appended widget to `document.documentElement` instead of `document.body` to escape iOS body overflow context. Removed `positionBtn()` left-calc (CSS `right:14px` used instead). Also moved `overflow-x:hidden` from `body` to `html` in `index.html`/`index_cn.html` to fix fixed-element scrolling bug.

**v7 — positionBtn() using screen.width, revert overflow-x to body:** Moving `overflow-x:hidden` to `html` broke `position:sticky` on the header. Reverted to `body`. Reimplemented `positionBtn()` using `Math.min(window.screen.width, window.screen.height)` (actual portrait device width — immune to layout viewport inflation) to compute `left` position. Widget stays on `<html>`.

**v8 — transform:translateZ(0), bottom:90px:**
- **Root cause of "robot not visible on page open":** iOS Safari doesn't activate `position:fixed` compositing until the first scroll event unless the element has a GPU-composited property. Added `-webkit-transform:translateZ(0); transform:translateZ(0); -webkit-backface-visibility:hidden` to `#bzw-btn` CSS to force immediate compositing layer.
- **Root cause of "toolbar hiding button":** iOS Safari toolbar (~49px) + home indicator (~34px) = ~83px of bottom chrome. `bottom:72px` put button behind the chrome. Raised to `bottom:90px` (button), `bottom:130px` (panel).

**Final state (v8):**
- Widget appended to `<html>` (not body) — escapes iOS body overflow-x:hidden fixed-position bug
- `body { overflow-x: hidden }` — prevents horizontal scroll AND keeps header sticky working
- `transform:translateZ(0)` — forces immediate GPU compositing on iOS so button is fixed from page load
- `bottom:90px` mobile — clears iOS Safari toolbar + home indicator on newer iPhones
- `positionBtn()` uses `Math.min(screen.width, screen.height)` for `left` in portrait — immune to wide table inflating layout viewport
- Chat-widget.js loaded with `?v=8` across all 4 pages

---

## What Was Done 2026-06-15

### Mobile Homepage — Dashboard Button in Header

- **Problem:** Mobile users had no obvious path to the dashboard from the homepage. The drawer only showed "About", auth links, and language toggle — no data access without digging.
- **Fix:** Added a blue "Dashboard" / "控制台" button directly in the mobile header, beside the hamburger icon. Always visible without opening the drawer.
  - `index.html`: `<a href="dashboard.html" class="mobile-dash-btn">Dashboard</a>` before the hamburger
  - `index_cn.html`: `<a href="dashboard_cn.html" class="mobile-dash-btn">控制台</a>` before the hamburger
  - CSS class `.mobile-dash-btn`: `display:none` on desktop, `display:inline-flex` at ≤768px; electric blue pill style
- **Also added** "Full Dashboard" / "完整数据" inside the mobile drawer (after the About link) as a secondary entry with `mobile-primary` styling linking to `baizora_main_form.html` / `baizora_main_form_cn.html`.
- **Temporary:** Both changes are for the free-access period only. Removal instructions documented in `assets/revert_billing_checklist.html` sections e/f/g. Search `mobile-dash-btn` to find all instances.

---

## What Was Done 2026-06-11

### PDD EPS Fix (ADS ratio)

- **Root cause:** PDD files a 20-F (foreign annual). EDGAR reports EPS per ordinary share. Tiingo price is per ADS (1 ADS = 4 ordinary shares). Old code was picking FY2023 EPS (10.29 CNY → $1.52 USD) from the 20-F comparative table instead of FY2025 (2.36 USD), AND was not applying the ADS ratio.
- **Fix 1 — fiscal year ordering:** `_best_ann_hit()` helper added inside `_parse_eps_from_latest_filing`. Sorts annual entries by `end_date` desc, prefers USD over CNY. 20-F comparative tables list oldest year first in HTML; without sorting the code picked FY2023 instead of FY2025.
- **Fix 2 — ADS ratio:** `_ADS_RATIOS = {"PDD": 4}` added. Divides `shares_outstanding // 4` for correct market cap. Multiplies `eps × 4` so PE = ADS_price / (ordinary_EPS × 4) is correct.
- **Result:** PDD EPS 1.518 → 9.44 (matches yf 9.54). PE 53.89 → ~8.7 (matches yf 8.426). No longer flagged in compare log.

### CVNA Shares Lambda Threshold Fix

- **Root cause:** CVNA had a 5-for-1 forward split on 2026-05-08. EDGAR inline XBRL (10-K filed 2026-02-18) shows pre-split Class A shares = **219M** (not ~32M as originally assumed). The lambda condition `< 50_000_000` never fired since 219M > 50M.
- **Fix:** Lambda threshold raised from `50_000_000` → `250_000_000`. Now 219M < 250M → fires → 219M × 5 = 1.095B shares → mktcap ≈ $73B (matches yf $72B).
- **Auto-heals:** After Q2 2026 10-Q is filed (~Aug 2026), EDGAR will show post-split ~1.095B shares. 1.095B > 250M → lambda returns unchanged. ✓

### Cache Management — TTL set to 0 permanently

- **`FUND_CACHE_TTL_DAYS = 0`** (changed 2026-06-11) with strict `<` comparison → cache is NEVER reused between runs. Every scan always re-fetches all EDGAR data fresh.
- **Rule:** Any fix to EPS/shares/fundamentals code → wipe `data/fundamentals_cache.json` immediately (write `{}`), commit together with the fix. Never debug "why isn't my fix working" — the answer is always the stale cache.
- **Users unaffected** — they see `latest.json` which only updates after scan finishes.
- **Cache stores raw EDGAR values.** SHARES_OUTSTANDING_OVERRIDE lambda is applied at scan time, not stored in cache.

---

## What Was Done 2026-06-14

### Bug Fix: 1D P CHG% Showing 0% on Weekends

- **Root cause:** `refreshDashPrices()` / `refreshLivePrices()` was called unconditionally on page load. On weekends, Tiingo IEX returns last traded price (= scanner close) → `chg = 0` → `r._liveChgPct = 0` → `0 ?? r.PriceChange1D` evaluates to `0` (because `??` only replaces null/undefined, not 0).
- **Fix:** Wrapped initial refresh call in `isMarketOpen()` guard in all 6 affected files: `baizora_main_form.html`, `baizora_main_form_cn.html`, `top-price-movers.html`, `unusual-volume.html`, `index.html`, `index_cn.html`.

### Bug Fix: Watchlist Not Syncing Across Devices

Two-part fix:
1. **Firestore security rules** were `allow read, write: if false` — blocking all client writes. Updated in Firebase Console to allow per-user access: `match /users/{userId} { allow read, write: if request.auth != null && request.auth.uid == userId; }`
2. **`loadCloudWatchlist()` seeding:** Previously, if Firestore had no watchlist doc, it silently kept localStorage data and never wrote to Firestore. Fixed to seed Firestore from localStorage on first login so other devices can then sync. The Firestore document is keyed by `uid`; email is not needed since uid is the document ID.

### Feature: `/api/index-news` Cloud Function

- Fetches Google News RSS for 4 queries (S&P 500 addition/removal, Nasdaq-100 addition/removal)
- 1-hour in-memory cache; filters retrospective articles; deduplicates; translates titles to Chinese
- Returns `{ fetched: "YYYY-MM-DD HH:MM ET", lookback_days: 90, items: [...] }`
- `index_news.html` + `_cn.html`: fetch CF first, fall back to static `data/index_news.json`; hourly `setInterval`
- `index.html` + `index_cn.html` homepage: also try CF first for the news card
- All pages show "Last checked: YYYY-MM-DD HH:MM ET" (browser fetch time)
- **firebase-tools** installed globally: `npm install -g firebase-tools`; deploy with `firebase deploy --only functions --non-interactive`

### Feature: Chat Widget Robot Icon

- `chat-widget.js`: replaced plain chat bubble with a cute robot face SVG (antenna, rounded head, eyes with shine, smile)
- Button changed from circular (56×56px) to pill shape with robot icon + **"Ask"** label (or **"问"** in CN)
- Entire pill floats up/down with CSS animation (pauses on hover)
- Cache-busting: all 4 pages loading `chat-widget.js` now use `?v=3` query string — bump this number on every future change to `chat-widget.js`

---

## What Was Done 2026-06-12

### Stock Split Handling — Automated Split Detection & Live Price Correction

**Problem:** KLAC had a 10-for-1 forward split on 2026-06-12. Tiingo IEX live quotes immediately returned the post-split price (~$247), but `latest.json` still held the pre-split close ($2411.64) from the previous night's scan. The dashboard's 1D P CHG% computation (`(livePrice - scanClose) / scanClose`) showed -89.88% instead of the correct ~+2.6%.

**Root cause of `chgPct` computation:** The code was using Tiingo IEX's `prevClose` field (unreliable on split day) to calculate the daily change. Fixed to always use the authoritative scan close `r.Price` from `latest.json`.

**Fix — `data/splits.json` (automated):**
- New file `data/splits.json` created by `update_splits_file()` in `scanner_tiingo.py`. Format: `{"TICKER": {"ratio": N, "date": "YYYY-MM-DD"}, ...}`.
- Tiingo endpoint: `GET /tiingo/daily/{ticker}/splits?startDate=...` (6-month lookback). Field: `splitFactor`. Normalized: if `< 1` (price adjustment factor), takes reciprocal to get forward ratio. Rounds to nearest integer; only ratio ≥ 2 recorded.
- Runs on: every full nightly scan (11 PM weekdays) AND every weekend midnight EDGAR-only run (splits are announced well before effective date → advance notice in `splits.json` before market open).
- `data/splits.json` is backed up, restored, committed, and git-added in `scanner.yml` alongside `latest.json`.

**Fix — Dashboard live price correction (`baizora_main_form.html` + `_cn.html`):**
- `_SPLIT_ADJ` is now populated dynamically from `data/splits.json` on page load (async fetch at startup).
- **Auto-heal logic:** for each ticker in `_SPLIT_ADJ`, compute `obsRatio = r.Price / d.last` (scan close ÷ live price). If `obsRatio ≈ split ratio (±20%)`, the scan close is pre-split → use `r.Price / ratio` as reference price for `chgPct`. If `obsRatio ≈ 1` (i.e., after tonight's scanner runs and updates `latest.json` to post-split price), the adjustment self-disables automatically — no manual intervention needed.
- The corrected `chgPct` is applied to both the table's 1D P CHG% column and the modal's `pc1` field.

**KLAC EPS guard (pre-existing, unchanged):** `if ticker == "KLAC" and eps > 10: eps = round(eps / 10, 4)`. EDGAR already had post-split shares (~1.3B). Market cap and PE auto-correct after tonight's scan when Tiingo returns post-split price ~$247.

**Design principle:** No generic percentage-based sanity check (e.g., block changes > 40%). That would hide real crashes. Instead: explicit per-ticker split ratio from verified Tiingo data, with two-sided `obsRatio` check that self-disables once the scanner catches up.

---

## Services & Infrastructure

### Service Stack

| Service | Role | Plan / Cost |
|---|---|---|
| **GitHub Pages** | Static site hosting + global CDN for all HTML/JS/CSS and `data/latest.json` | Free |
| **GitHub Actions** | Nightly scanner cron (5PM/6PM/7PM/11PM ET weekdays), video generation, archive push | Free (2,000 min/month) |
| **GitHub `scanner-archive` repo** | Permanent gzipped CSV archive (1 file/day, from 11PM run only) for data quality audit | Free (private repo) |
| **Google Cloud Functions (Firebase)** | `/api/iex-quotes` live price endpoint; `/api/subscription` auth check; other API routes | Blaze pay-as-you-go (~$0.10/month at current scale) |
| **Firebase Auth** | User authentication (email/password) | Free up to 50,000 MAU |
| **Stripe** | Subscription billing ($9.99/month or $99/year); 7-day free trial | 2.9% + $0.30 per transaction |
| **Tiingo** | EOD OHLCV data + company metadata for 516 tickers; IEX live quotes for homepage | Commercial license |
| **SEC EDGAR** | EPS (TTM diluted GAAP), shares outstanding, SIC sector, company name | Free (public API) |

---

### Scalability & Cost Analysis

**GitHub Pages (CDN)**
- Served via Fastly CDN — no concurrent user limit for static files
- Soft bandwidth limit: 100GB/month. At ~5MB per `latest.json` load, that's ~20,000 full page loads/month
- Repeat visitors don't re-download HTML/CSS/JS (browser-cached); only `latest.json` is fetched fresh each visit
- Cost: $0. GitHub does not charge for Pages bandwidth — soft limit triggers an email, not a bill
- If bandwidth becomes a concern at scale: gzip `latest.json` server-side (~10x reduction to ~500KB)

**Google Cloud Functions**
- Free tier (always free on Blaze): 2,000,000 invocations/month, 400,000 GB-seconds, 5GB outbound
- `/api/iex-quotes` has a **60-second in-memory cache** — regardless of concurrent homepage users, the function is called at most once per minute (~1,440 calls/day, ~31,680/month — well within 2M free)
- Paid rate beyond free tier: $0.40 per million invocations — 10M calls/month = ~$3.20
- Outbound data: $0.12/GB beyond 5GB free
- Current bill: ~$0.10/month (minor outbound networking from calling Tiingo/IEX)

**Firebase Auth**
- Free up to 50,000 monthly active users on Blaze plan
- Cost: $0 at any realistic near-term scale

**Key architectural advantage: user traffic does not multiply infrastructure cost**
- GitHub Pages CDN absorbs all static asset requests at no charge
- Cloud Functions 60s cache means 10,000 simultaneous homepage users = same cost as 1 user
- EDGAR and Tiingo are only called by GitHub Actions (nightly batch) — completely decoupled from user traffic
- No WebSocket server, no real-time database polling, no per-user server sessions

**Cost at 1,000 daily active users**
- GitHub Pages: $0
- Cloud Functions: $0 (well within free tier)
- Firebase Auth: $0
- Total infrastructure: ~$1–2/month (unchanged from today)
- Stripe fees: ~$32/month if 10% convert to paid (~100 subscribers × $9.99)
- Revenue at 10% conversion: ~$967/month net

**When architecture would need to change**
- Real-time sub-second price streaming (WebSocket service required — current 60s polling is by design)
- Tens of thousands of daily active users consistently exceeding GitHub Pages 100GB/month soft limit
- Neither scenario is relevant at current scale

---

## Next Time: What to Check

1. **Chat widget mobile test result** — user was going to test `chat-widget.js?v=8` on another phone. Confirm whether bottom:90px + transform:translateZ(0) fixed both "not visible on page open" and "scrolls with page until middle". If button is still not fixed: next step is JS scroll listener fallback (position:absolute updated on every scroll event as last resort).
2. **Re-enable billing + paid gate** — Tiingo scanner has been live since 2026-06-07 with clean compare log. After confirming clean runs for ~1 week, re-enable billing per the revert checklist above. Also remove the mobile `mobile-dash-btn` button and drawer link from `index.html` / `index_cn.html` (see `assets/revert_billing_checklist.html` sections e/f/g).
2. **Tiingo attribution** — ✓ DONE. Present in `baizora_main_form.html` (line 906), individual stock pages, and homepage. `dashboard.html` shows no market data so no attribution needed there.
3. **BKNG + CVNA split guards** — both auto-disable once Q2 2026 10-Q is filed (~Aug 2026). Verify EPS and mktcap drop to expected post-split values and compare log stays clean.
4. **Remaining EPS=None tickers** — BRK-B is structural (no EDGAR data after 2013); others may be IFRS filers. Investigate if any are solvable from EDGAR without a paid source.
5. **yfinance compare log** — remaining flagged EPS diffs (OXY, MLM, CI etc.) are GAAP one-time items vs adjusted EPS. These are correct and expected — not bugs.
6. **FUND_CACHE_TTL_DAYS = 0** — EDGAR now always re-fetches every run. Cache file is still written but never read back. No further cache management needed.
7. **FAQ watchlist section** — user asked to update FAQ to reflect that watchlist now syncs across devices via Firestore (was previously described as local-only). Check `assets/faq.html` and `assets/faq_cn.html`.
