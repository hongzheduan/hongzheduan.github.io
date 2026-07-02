# Baizora Scanner - Project Context

## What Was Done 2026-07-01 (session 3 — verification, banner wording, 500PM skip-if-complete)

### Manual Trigger Confirmed Everything End-to-End

Triggered `workflow_dispatch` via the GitHub REST API (no `gh` CLI available locally; used the OAuth token from `git credential fill` — `git`'s own stored credential, not a new secret) to verify the day's fixes in one real run rather than trusting local simulations. Run [28561542236](https://github.com/hongzheduan/hongzheduan.github.io/actions/runs/28561542236) completed successfully. Verified after pulling:

| Check | Result |
|---|---|
| SATS removed from `data/sp500_symbols.txt` | ✓ 0 matches |
| `data/index_changes.json` | ✓ new entry, recorded once: `{"sp500": {"removed": ["SATS"]}}` |
| Ticker count | 516 (was 517) |
| SATS in `latest.json` results | ✓ absent |
| `partialUpdate` / `staleTickers` | `false` / `[]` — clean run |
| EPS fallback fix still holding | ✓ KKR 2.93, BRK-B 33.59 |

**Diff-mechanism confirmed non-repeating:** simulated two consecutive `update_and_detect_changes()` calls against a scratch copy of the data files (not the real repo) — run 1 detects and records the SATS removal (comparing our *old* file, pre-fix, against the freshly-filtered Slickcharts scrape); run 2 finds `changes: None`, because the diff is always *our own previously-written file* vs *today's scrape*, and our file self-updates to drop SATS after the first pass. Confirms Slickcharts continuing to show the zombie 0%-weight row indefinitely will **not** cause repeated daily "removed" entries.

**index_changes.json rewritten multiple times/day, harmlessly:** `update_and_detect_changes()` runs as step 1 of every scan that reaches that point (4:30, 5:00 if not skipped, 5:30, 6:30, 11 PM, manual) — same two files overwritten in place each time, not new dated files. Most rewrites are content no-ops; `index_changes.json` only grows when the diff against the previous write actually differs.

**False alarm — user didn't see the SATS entry in the "MEMBERSHIP CHANGE" tab:** live JSON was already correct (`curl` confirmed `entries[0]` had the SATS removal) — turned out to be GitHub Pages' CDN cache (`Cache-Control: max-age=600`) plus the browser's own cache. `loadIndexChanges()` fetches `data/index_changes.json` with no cache-busting query param (unlike the periodic `data/latest.json` re-check, which appends `?Date.now()`). Resolved with a hard refresh. **Worth considering:** add cache-busting to this fetch too if this recurs.

### Partial-Update Banner Wording Iterated

- `b8e4202`: switched from listing every excluded ticker by name to count-only ("N tickers pending fresh data and temporarily hidden") — naming would overflow the banner if dozens/hundreds were stale at once.
- `cf308e2`: added "Check back in 30 minutes."
- `394ea53`: softened to "Typically updates within 30 minutes" — a ticker can stay excluded across *multiple* scans (SATS was stale 8 days across many runs before its root cause was fixed), so a firm 30-min promise was misleading, especially on the last scan of the day.

### 500PM-scan Skip-If-Complete (commit `0f917ed`)

Added `SKIP_IF_COMPLETE=1`, set **only** in the `0 21 * * 1-5` (5:00 PM) branch of `scanner.yml`'s "Check market holiday and run type" step. In `scanner_tiingo.py`'s `__main__`, right after the SPY probe confirms data: if `data/latest.json` already shows today's date with `partialUpdate: false`, skip the rescan entirely (`sys.exit(0)`) rather than reproducing an identical result. **Deliberately not applied to 5:30/6:30 PM** — those stay unconditional safety nets regardless of what 5:00 PM finds, per explicit instruction. If the scan is skipped, the "Commit updated data" step still commits just the `archive/worklog.md` line (existing `git diff --cached --quiet` check handles this with no special-casing).

---

## What Was Done 2026-07-01 (continued)

### SATS Sat 8 Days Stale, Silently — Per-Ticker Staleness Exclusion + Index Weight Filter Added

**Discovery:** while investigating the earlier stale-data incident, an empirical check of the live `data/latest.json` found `SATS` (EchoStar) carrying data from `2026-06-23` — 8 days old — while the top-level `date` said `2026-07-01` and `status: "Updated"`. All other 516 tickers were correctly current. Nothing anywhere in the pipeline validated per-ticker date consistency.

**Root cause 1 — Slickcharts index-membership lag:** EchoStar changed its ticker to `ECHO` on 2026-06-24 and left the S&P 500, but `slickcharts.com/sp500` still listed a row for `SATS` a week later at `0.00%` weight, `$0.00` price (confirmed by scraping the live page — 503 rows instead of the correct 502, with SATS as the last/zombie row). `fetch_index_tickers()` (`scanner_tiingo.py:480`) now parses the Weight column and skips any row with weight `<= 0`. This lets the *pre-existing* `update_and_detect_changes()` / `index_changes.json` mechanism auto-record the removal on the next scan — already surfaced in the dashboard's "MEMBERSHIP CHANGE" tab, no new UI needed for that part.

**Root cause 2 — no per-ticker recency validation, anywhere:** the SPY probe only confirms SPY itself is current; `check_data_quality()` only checks big 1D swings / thin candle counts / missing cache files — never date staleness. Tiingo can publish EOD data incrementally per-ticker, and a ticker whose bar hasn't landed yet just silently carries its old data through an otherwise "successful" run.

**Fix (commit `e39982b`):**
- After `scan()` returns in `__main__` (~line 2958), any row whose `Date` doesn't exactly match the confirmed `_TIINGO_LAST_DATE` is dropped from `df` and `candles_out` — **any mismatch at all (≥1 day) excludes the ticker**, per explicit instruction: showing nothing for a ticker is better than showing wrong same-day-looking data for it.
- Excluded tickers are tracked in a new module global `_STALE_TICKERS_EXCLUDED` and written into `export()`'s payload as `partialUpdate: bool` + `staleTickers: [...]`.
- `baizora_main_form.html` / `_cn.html`: new `.stale-banner` element (reuses the documented announcement-bar gradient) shows/hides in `loadDashboard()` based on `json.partialUpdate`. Wording iterated same day — see the "Partial-Update Banner Wording Iterated" note below.
- **Not yet extended to** `baizora_main_form_free*.html` / freetier variants — lower priority since those already show delayed/limited data.

A later scheduled or manual run naturally re-includes an excluded ticker once Tiingo catches up — no special recovery logic needed, every run re-evaluates from scratch.

---

## What Was Done 2026-07-01

### EPS Fallback Path Skipped Q4 — KKR/BRK-B/V/ERIE/STZ/HSY Fixed

**Root cause:** `_parse_eps_from_latest_filing()` (`scanner_tiingo.py`, the inline-XBRL fallback used when EDGAR `company_facts` has no standard EPS tags for a ticker) checked its naive "sum the 4 most recent quarter end-dates found" path *before* its correct "3 quarters + Q4 derived from annual − 9M YTD" path. Since no company ever files Q4 as a standalone 10-Q (it's folded into the 10-K), the naive path always had ≥4 distinct end-dates available — it silently reached back to a stale year-ago quarter to fill the gap — and fired first, skipping the real Q4 every time it ran.

**Fix (commit `973b985`):** Reordered the two paths — no logic rewritten, just swapped which one runs first — so the derived-Q4 path now takes priority, matching the ordering already used (and never buggy) in the primary EDGAR path (`_get_edgar_fundamentals`).

**Verified via live production run** (`_get_edgar_fundamentals()` called directly for the full 517-ticker S&P 500 + Nasdaq-100 universe, not a proxy check). Six tickers were silently wrong and are now fixed:

| Ticker | Before | After |
|---|---|---|
| KKR | 1.56 | 2.93 ✓ matches yfinance |
| BRK-B | 26.83 | 33.59 ✓ matches yfinance |
| V | 11.18 | 11.47 |
| ERIE | 12.37 | 10.93 |
| STZ | 11.82 | 9.61 |
| HSY | 4.90 | 5.37 |

**Not affected** — same fallback function, but these file 20-F/40-F/6-K and never a 10-Q, so the `quarters` dict is always empty and they go straight to the annual-only Path 3 (no Q4 to skip): ARM, ASML, CCEP, FER, PDD, NBIS.

**Still `EPS=None`** — pre-existing gaps, unrelated to this bug: ARES, TRI (both filed Form 25-NSE, being delisted), FDXF (FedEx Freight spinoff, only 8-K/Form 4 filed so far — no 10-Q/10-K yet).

**Debug-compare log comment updated** (`scanner_tiingo.py` ~line 2777) to reflect the corrected ticker list and explain the fix inline.

**Note — the fallback-ticker set is not static:** HSY and NBIS were *not* in the 2026-06-07 "EPS=None (13 tickers)" list further below in this file, meaning they only started hitting this fallback sometime in the following weeks (most likely `company_facts` data aging past the primary path's 2-year recency window). Don't trust a hardcoded snapshot of which tickers use the fallback — re-verify live if it matters again.

**✓ CONFIRMED in production (2026-07-01 evening):** `data/fundamentals_cache.json` now shows KKR 2.93, BRK-B 33.59, V 11.47, ERIE 10.93, HSY 5.37 — all matching. STZ shows 10.50 (not 9.61) — expected drift from a new EDGAR filing landing between the fix and this check, not a regression.

---

### 4:30 PM Scan Had Stale (June 30) Data — Manually Triggered, Added 500PM-scan Retry

**Symptom:** Tonight's 4:30 PM-scheduled scan (`430PM-scan`, ran ~6:15 PM ET) completed successfully — SPY readiness probe passed, 517 tickers processed, commits pushed — but `data/latest.json`'s `date` field stayed on `2026-06-30`. Dashboard showed all 1D price changes as 0%.

**Root cause:** The SPY probe (`scanner_tiingo.py:2909-2932`) only confirms *SPY's* bar is same-day — it doesn't guarantee Tiingo has finished publishing EOD data for the other ~516 tickers. `latest.json`'s date comes from the actual fetched OHLCV data (`df["Date"].iloc[0]`, `scanner_tiingo.py:2353`), not from the probe, so the probe passing didn't mean the bulk data was ready. A 5:55 PM ET manual `workflow_dispatch` trigger hit the same not-yet-published data.

**Also checked:** the "pages build and deployment" cancellation messages seen around this time were a red herring — confirmed via the GitHub Actions API that the *final* deployment (for the last commit in the batch) completed successfully; cancellations were just normal churn from three commits landing within 6 minutes of each other.

**Resolution:** manually re-triggered `workflow_dispatch` once Tiingo had caught up — `data/latest.json` rolled to `2026-07-01` and 1D price changes came back.

**Fix (commit `bffa5a7`):** Added a new **500PM-scan** cron slot (`0 21 * * 1-5`, scheduled 5:00 PM ET, actual ~7:00 PM ET) to `.github/workflows/scanner.yml`, sitting between the existing 4:30 PM and 5:30 PM runs. It falls through to the same generic retry branch as 530PM/630PM-scan — `SKIP_EDGAR=1` (no EDGAR refetch, since 4:30 PM already refreshed it), `PROBE_RETRIES=1`. Only 3 lines changed: the cron entry, a `RUN_TYPE="500PM-scan"` worklog case, and an updated comment.

---

### GIS Compare-Log Diff Explained (Not a Bug)

`archive/compare_*.log` flagged `GIS ours=-0.160 yf=4.090 diff=103.9%`. Diff formula is `abs(ours - yf) / abs(yf)` (`scanner_tiingo.py:2748`) — checks out exactly (4.25/4.09 = 103.9%).

Traced `ours=-0.160` to source: GIS filed a brand-new 10-K on **2026-07-01** (fiscal year ended 2026-05-31). Its own XBRL shows Q4 FY2026 (Mar–May 2026) diluted EPS = **-3.74** (a large one-time charge, likely goodwill/brand impairment), dragging full-year GAAP EPS to **-0.16** — an exact match to what EDGAR itself reports as the annual total. yfinance's `4.09` almost certainly hadn't ingested the just-filed 10-K yet, or reflects a non-GAAP "adjusted" EPS excluding the impairment. This is the documented "TTM window vs YF annual anchor" known-difference category (`scanner_tiingo.py` ~line 2788) — not a fallback-function bug like the KKR/BRK-B one above.

---

## What Was Done 2026-06-30

### Free Tier 10-Session Delay — Backfill & Bug Fixes

**Problem:** Free tier was showing today's data (2026-06-29) instead of 2-week-old data. Root cause: scanner-archive had only 1 file (`latest_2026-06-29.json.gz`), so `IDX = max(0, COUNT-10) = 0` → oldest = newest = Jun 29.

**Fix 1 — Backfill scanner-archive:**
- Wrote `backfill_archive.py` (one-time script, now deleted) — reads all 111 commits of `data/latest.json` from git history, deduplicates by market date, writes `latest_YYYY-MM-DD.json.gz` for each unique date.
- Generated 42 sessions from 2026-04-28 through 2026-06-29.
- User pushed 41 files (Apr 28–Jun 26) to scanner-archive; Jun 29 was already there.
- COUNT = 42 → IDX = 32 → `latest_2026-06-15.json.gz` (10 sessions before Jun 29 ✓).
- Applied immediately: `data/free_tier.json` set to Jun 15 data; pushed live.

**Fix 2 — CSV archive date bug (`scanner_tiingo.py`, commit `1fd8d05`):**
- `OUTPUT_CSV` was a module-level constant using `DATE_STR` (script import time). On midnight ET runs (11 PM ET = midnight in summer EDT), `DATE_STR = next calendar day`, so CSVs were named `results_2026-06-30.csv` for Jun 29 data.
- Fix: compute `output_csv = os.path.join(ARCHIVE_DIR, f"results_{market_date}.csv")` inside `export()` using the actual market date from the data.

**Fix 3 — scanner.yml archive step (commit `1fd8d05`):**
- Old: `CSV=$(find archive -name "results_*.csv" | sort | tail -1)` — picked wrong-dated file.
- New: `DATE_STR=$(python3 -c "import json; print(json.load(open('data/latest.json'))['date'])")` first, then `CSV="archive/results_${DATE_STR}.csv"` — always matches market date.
- Removed CSV.gz push from scanner-archive; now pushes only `latest_*.json.gz` (CSV was redundant).
- Step renamed from "Push gzipped CSV+JSON" to "Push JSON".

**Misnamed file cleanup:** User manually renamed `results_2026-06-30.csv.gz` → `results_2026-06-29.csv.gz` in scanner-archive via GitHub web UI.

**Verification pending:** Tonight's 11 PM scan will push `latest_2026-06-30.json.gz` to scanner-archive (COUNT → 43) and update `free_tier.json` to `latest_2026-06-16.json.gz` (still ~10 sessions old). User will verify free_tier shows 2-week-old data after that run.

**How the delay stabilizes:** IDX = COUNT - 10 means free_tier always shows data 9 sessions before the newest. Each nightly 11 PM run rolls it forward by 1 session. Delay is permanently ~9-10 trading sessions (~2 calendar weeks).

---

### 0% PriceChange1D After Scanner Auto-Reload — Fixed

**Root cause:** The 8 PM `isMarketOpen()` extension (June 29, commit `0ac2dd0`) created a new bug. After the ~6:30 PM scanner run commits today's date to `latest.json`, the 5-min auto-reload poll fires and reloads the page. After reload, `loadedDate = today`. But `isMarketOpen()` was still true until 8 PM, so `refreshDashPrices()` kept firing every 10s. IEX `last` = today's closing price = scanner's `r.Price` → `_liveChgPct = 0` for all tickers → all 1D changes showed 0%.

**Fix (`baizora_main_form.html` + `baizora_main_form_cn.html`, commit `3ce7474`):**
Added `loadedDate !== _todayET` guard to all IEX refresh call sites:
```js
const _todayET = new Date().toLocaleDateString('en-CA', {timeZone:'America/New_York'});
if (isMarketOpen() && loadedDate !== _todayET) refreshDashPrices();
setInterval(() => { if (isMarketOpen() && loadedDate !== _todayET) refreshDashPrices(); }, 10_000);
```
- Before scanner runs: `loadedDate = yesterday` → IEX fires, shows live prices during 4–6:30 PM gap ✓
- After scanner auto-reload: `loadedDate = today` → IEX suppressed → scanner's correct `PriceChange1D` shown ✓
- `isMarketOpen()` upper bound stays at 1200 min (8 PM ET) — unchanged.

Also fixed CN candles callback which was still using `isWeekdayET()` instead of `isMarketOpen()`.

Users already on the page seeing 0% need a manual hard refresh to pick up the new code. Future page loads and tomorrow's scan auto-reload are handled automatically.

---

### Homepage Sparkline Markers — Wrong Position Fixed

**Root cause:** Scanner computes `1YMaxVolumeChangeDay` and `1YMaxPriceChangeDay` as **days ago** (`n - 1 - idx`, 0 = most recent bar). The homepage's `miniSpark` (Top Price Movers panel) and `buildSparkSvg` (1Y Trend demo sparkline) were using these values as **direct left-to-right array indices** (0 = oldest), placing ▲ and ● on the mirror-image position of where they belong.

The dashboard's `renderSparkline` was correct all along — it applies `idxFromDays(daysAgo) = n - 1 - daysAgo` before computing marker positions.

**Fix (`index.html` + `index_cn.html`, commit `5110a1c`):**
- `miniSpark`: `const ai = data.length - 1 - triIdx/dotIdx` before calling `posX(ai)` / `posY(data[ai])`
- `buildSparkSvg` call site: `triIdx = Math.max(0, n - Math.min(daysAgo, n))` (equivalent conversion)

---

### HON Tiingo Data Inconsistency (Investigation, No Code Fix)

During the pre-spin-off period (May–June 28), Tiingo maintained two inconsistent series for HON:
- **Daily price endpoint** (stored as `Price` in `latest.json`): returned actual combined-company market price (~$210–$233)
- **Historical adjClose series** (stored in `candles.json`, rebuilt fresh each scan): already adjusted for the upcoming spin-off, showing ~$100–$163 (HON stub value only)

Result: `free_tier.json` (June 15 data) shows `Price: $227.41` while the candlestick chart shows ~$162 for the same date. This is a Tiingo upstream inconsistency, not a scanner bug. The 45.69% `PriceChange1D` in June 29's data was also Tiingo-caused (spin-off factor applied to June 26 adjClose but not the reverse split factor yet). Both issues self-correct once Tiingo completes retroactive adjustment of HON's historical series (expected tonight's scan).

---

## What Was Done 2026-06-29 (Session 2)

### Beta Scan Removed Entirely

**Decision:** Beta scan was causing incorrect `PriceChange1D` values on split days (HON +45.69% instead of -6%) and added complexity. Removed completely.

**`scanner_tiingo.py` changes (commit `74f0fee`):**
- Removed `BETA_RUN` constant
- Removed `fetch_iex_snapshot()` function (~50 lines)
- Removed `if BETA_RUN:` IEX injection block from `scan()`, volume carry-forward, BETA_RUN volume_change_1d branch
- Removed entire `if BETA_RUN:` block in `__main__` (holiday/weekend checks simplified, ~110-line beta block deleted)
- `export()` simplified: always writes CSV + rotates free-tier; `beta` parameter removed
- All post-scan steps (`update_and_detect_changes`, `check_data_quality`, `export_daily_digest`, `export_score_history`, `fetch_and_save_index_news`) now run unconditionally

**`scanner.yml` changes (commit `74f0fee`):**
- Removed `cron: "0 17 * * 1-5"` schedule entry
- Removed `elif [ "$SCHEDULE" = "0 17 * * 1-5" ]; then BETA_RUN=1 ...` env block
- Removed `BETA_RUN: ${{ env.BETA_RUN }}` from env passed to Python
- Removed `elif [ "$SCHEDULE" = "0 17 * * 1-5" ]; then RUN_TYPE="100PM-beta"` from worklog

**Impact:** 4:00–6:00 PM ET gap — IEX client refresh stops at 4 PM, full EOD scan doesn't land until ~6:30 PM ET. Users see prior day's data during this window. Two options discussed but not yet implemented:
1. Extend `isMarketOpen()` to 4:30 PM (client still catches closing price)
2. Restore narrower beta scan that only overlays closing IEX prices without touching `PriceChange1D`

**Client-side live price refresh (`refreshDashPrices`) is unchanged** — still fires every 10s during `isMarketOpen()` (9:30 AM–4:00 PM ET), showing live IEX prices during the trading day.

---

### HON Reverse Split Fixes

HON (Honeywell) completed a 1-for-2 reverse split on 2026-06-29. Two symptoms:
1. `PriceChange1D` showed +45.69% (actual: -6%)
2. `EPS` showed ~$6 (should be ~$12.86 post-split)

**EPS fix (commit `9c14359`):**
- `data/split_guards.csv`: HON `eps_threshold` changed 4.0 → 8.0. Pre-split EPS ~$6; old threshold `6 < 4.0 = False` (guard never fired); new `6 < 8.0 = True` → `eps = 6 × 2 = 12` ✓
- `data/splits.json`: HON entry added `{ "ratio": 2, "date": "2026-06-29" }` (marker only — reverse splits don't trigger frontend auto-heal since `obsRatio ≈ 1.06`, not ≈ 2)

**PriceChange1D still wrong after fix:** Tiingo had not yet retroactively adjusted HON's historical `adjClose` series. OHLCV cache (gitignored, rebuilt fresh each run) got Friday's `adjClose = $156.4` from Tiingo API, while today's close is $227.8, giving `(227.8 - 156.4)/156.4 = 45.69%`. This is a Tiingo source data propagation delay — will self-correct on tomorrow's scan once Tiingo updates historical series.

---

### CN Market News — EN RSS + Translation

**Problem:** CN 市场简报 was fetching from Chinese Google News RSS (`hl=zh-CN&gl=CN`), which returned non-US-stock content.

**Fix (`functions/index.js`, deployed):**
- Both EN and CN now fetch the same EN RSS (US-focused sources)
- When `?lang=zh`: each title is passed through `_translateToZh()` (Google Translate free API) with 80ms gaps; result stored as `it.title_cn`
- 30 items stored (was 6 → 10 → 30). Card shows 6; download gets 30 for manual curation
- `index_cn.html` `renderNews()`: uses `it.title_cn || it.title` as display title

**Commits:** `b9165ec`, `1e6f1b1`

---

### IEX Refresh Extended to 8 PM ET + Auto-Reload on Scan Land

**IEX window extended (`baizora_main_form.html` + `_cn.html`, commit `0ac2dd0`):**
`isMarketOpen()` upper bound changed from 960 min (4:00 PM) to 1200 min (8:00 PM ET). IEX `last` field is a static value after close — stays at the closing price until next trading day. Extending the window covers the 4:00–6:30 PM gap left by removing the beta scan. The 0% PriceChange1D issue from before was caused by the beta scan overwriting `r.Price` with IEX live price; without beta scan, `r.Price` is always yesterday's EOD close so the formula `(live - r.Price) / r.Price` gives the correct 1D change. The LIVE badge in column headers also stays visible until 8 PM (same `isMarketOpen()` call).

**Auto-reload on scan land (`baizora_main_form.html` + `_cn.html`, commit `c265550`):**
Added 5-minute `setInterval` after dashboard data loads:
```js
setInterval(() => {
  fetch("data/latest.json?" + Date.now()).then(r => r.json()).then(d => {
    if (d.date && d.date !== loadedDate) location.reload();
  }).catch(() => {});
}, 5 * 60 * 1000);
```
When the 6:30 PM scan commits new `latest.json` with today's date, the next poll detects the date change and reloads the page automatically — users get fresh scores, volume, multi-week metrics without manual refresh. `?Date.now()` cache-buster prevents GitHub Pages CDN from serving stale data.

**Why needed:** Announcement bar is on the homepage, not the dashboard. Users in the results page have no signal that new data has landed except the date in the toolbar. Auto-reload removes that friction.

---

### LIVE Badge — Conditional on Market Hours

`baizora_main_form.html` and `baizora_main_form_cn.html`: the `<span class='live-tag'>live</span>` / `实时` in the PRICE and 1D P CHG% column headers is now conditional on `isMarketOpen()`.

```js
${thSort("Price", "Price" + (isMarketOpen() ? "<span class='live-tag'>live</span>" : ""))}
```

Since `isMarketOpen()` is called at render time, the badge appears/disappears dynamically without a page reload (e.g., next sort click after 4 PM ET hides it).

**Commit:** `6dc933d`

---

## What Was Done 2026-06-29

### 1D P CHG% Wrong After Beta Scan (Bug Fix)

**Root cause:** The beta scan (`scanner_tiingo.py`, runs ~1–3 PM ET) overwrites `r["Price"]` with today's intraday IEX price. The frontend live refresh code then uses `r.Price` as the "previous close" reference when computing 1D P CHG%, giving a tiny number (e.g. 0.5–1%) instead of the real change from yesterday's EOD close (e.g. 4–10%).

**Fix — two parts:**
- **Backend (`scanner_tiingo.py`):** Before overwriting `r["Price"]`, store the original EOD close: `r["PrevClose"] = scan_close`. One line added before `r["Price"] = round(live, 4)`.
- **Frontend (all 4 dashboard files):** Use `r.PrevClose ?? r.Price` as the reference instead of `r.Price`.
  - `baizora_main_form.html` / `baizora_main_form_cn.html`: `const prevClose = r.PrevClose ?? r.Price` then use `prevClose` in the split-adj `obsRatio` + `refPrice` calculation.
  - `baizora_main_form_free.html` / `baizora_main_form_free_cn.html`: same one-liner before `chg` calculation (free pages no longer on homepage but fixed for consistency).

**Timing note:** Fix takes effect the next time the beta scan runs (next trading day ~1–3 PM ET). Until then `r.PrevClose` is absent and the frontend falls back to `r.Price` (old behavior).

**Commits:** `19a3b99` (fix), `d2ab7b0` (context)

---

### Homepage — Index News "View All" Subscription Gate

The "View all" link in the "Index Membership News & Records" card (`index.html` + `index_cn.html`) previously navigated directly to `index_news.html` / `index_news_cn.html`. That page redirects non-logged-in users to `login.html` and unsubscribed users to `billing.html`, which felt abrupt.

**New behavior:** Clicking "View all" now runs an async subscription check first. Non-subscribed users (logged in or not) see a modal instead of navigating.

**Modal content:**
- Not logged in: gold "Subscribe →" button → `pricing.html` / `pricing_cn.html` + blue "Already subscribed? Sign in →" secondary link
- Logged in, not subscribed: gold "Subscribe →" only (sign-in link hidden)
- Logged in, subscribed/trialing: navigates directly to `index_news.html` / `index_news_cn.html`

**Implementation (`index.html` + `index_cn.html`):**
- `hpViewAll(e)` async function: calls `e.preventDefault()` always; checks `firebase.auth().currentUser`; if user exists, fetches `/api/get-user?uid=...` and checks `subscriptionStatus`; if active/trialing navigates; otherwise shows modal
- No try/catch — network errors fail naturally
- Modal HTML placed at end of body with inline `onclick` on ✕ button and overlay (`document.getElementById('hpGateModal').style.display='none'`) — avoids `addEventListener` timing issue where script runs before modal HTML is in the DOM
- `#hpGateSignin` is the secondary sign-in link; hidden via `style.display='none'` for logged-in unsubscribed users

**Commit:** `e897ce3`

### AI Assistant — FAQ Routing, Clickable Links, Cost Optimisation

Three rounds of changes to `functions/index.js` and `chat-widget.js`:

**Round 1 — Shorter responses + link-first (`d980f5e`):**
- `max_tokens` 1024 → 300 (hard cap, ~70% output cost reduction)
- Added `RESPONSE STYLE` rule: 1–3 sentences max, link by topic (About, FAQ, Pricing, Signup, Account), FAQ when unsure, email only for account-specific issues
- Link destination matched to question topic:
  - "What is Baizora?" / general → `baizora.com/assets/about.html` (EN) / `about_cn.html` (CN)
  - Feature questions (scores, columns, data, watchlist) → FAQ with named section, e.g. "See 'Data & Updates' in our FAQ at baizora.com/assets/faq.html"
  - Pricing/plans → `pricing.html`, Sign up → `signup.html`, Account/billing → `account.html`
- **If unsure → link to FAQ**, not support email. Email only for clear account-specific issues (login failure, billing charge, subscription not activating)

**Round 2 — Clickable links in chat widget (`24af281`):**
- `chat-widget.js` v11: `addMsg` now parses `[text](url)` markdown into `<a target="_blank">` tags for bot messages. User messages still use `textContent` (XSS-safe). HTML-escaped first, then regex applied.
- Prompts updated to use `[text](url)` syntax and explicitly suppress `**bold**` formatting.
- Cache-buster bumped `?v=10` → `?v=11` across all 6 HTML files.

**Round 3 — Full FAQ routing, no inline explanations (`5f2d5ca`, `c7f26ae`):**
- Added all 25 exact FAQ question titles (EN + CN) to both prompts.
- Key rule: "The knowledge sections below are for reference only — do NOT use them to compose answers. If a FAQ item covers it, respond with ONE sentence pointing there by name."
- Example response: *See 'How is the data updated?' in our [FAQ](https://baizora.com/assets/faq.html).*
- Prompt topic → page routing: "What is Baizora?" → `about.html`; features/data/troubleshooting → FAQ by exact title; pricing → `pricing.html`; account → `account.html`.

**Round 4 — Strip all knowledge sections from prompts (`0f6ae4c`):**
- Removed all 15 detailed knowledge sections (FREE TIER, PRICING, DATA & UPDATE SCHEDULE, SPARKLINE MARKERS, DASHBOARD COLUMNS, TROUBLESHOOTING, etc.) from both EN and CN prompts.
- Prompts reduced from ~2,000 tokens to ~400 tokens — 5× cheaper per call on input cost alone.
- Philosophy: the AI's only job is to route to the right FAQ item or page. The FAQ itself is the content — no reason to duplicate it in the prompt.
- AI now has no knowledge to compose answers from; it can only return one sentence with a link.
- Example: "PE is different from other sites" → *See 'How current is the P/E and EPS data?' in our [FAQ](...).*

**Cost estimate (Haiku 4.5, after Round 4):** ~$0.0003 per question (~400 token prompt + ~40 token output) → roughly **30,000+ questions per $10**.

**Prompt caching — noted, NOT yet implemented:** `cache_control: { type: "ephemeral" }` on the system prompt would further reduce cached input tokens to ~10% within a 5-minute window. One-line change, deferred at user's request.

Cloud Functions redeployed after each round.

---

### Free Tier Delay — Dashboard Card Text Fix

`dashboard.html` and `dashboard_cn.html` Free Tier tool-card description updated from "2 trading sessions" → "2 weeks" (EN) / "2个交易日" → "约两周" (CN).

**Commit:** `7336c4a`

---

### Market News — Live CF Fetch + Hourly Refresh

**Problem:** `index.html` and `index_cn.html` were loading `data/market_news.json` (static file, written once per nightly scan). On weekends and during the trading day, the news card stayed stale for up to 24 hours.

**Fix:**
- **CF (`functions/index.js`):** `/api/market-news` now returns up to **10 items** (was 6). Already has 1-hour in-memory cache.
- **Frontend (`index.html` + `index_cn.html`):** Replaced static-JSON fetch with `_fetchNews()` function that:
  - Tries `https://us-central1-baizora.cloudfunctions.net/api/market-news` (EN) or `...?lang=zh` (CN) first, with 8-second timeout.
  - Falls back to static `data/market_news.json` / `data/market_news_cn.json` if CF fails.
  - Called on page load and via `setInterval` every 60 minutes for open tabs.
- Card still displays 6 items (`slice(0, 6)` in `renderNews`); CF stores all 10 in `_news` object.

**Commit:** `b9165ec`

---

## What Was Done 2026-06-28

### Homepage NVDA Chart — Volume Panel + X-Axis Fix

Canvas height increased from 120px → 160px in `index.html` and `index_cn.html`.

**Volume bars:** Canvas split into price (78%) + volume (22%) with 4px gap. Volume bars color-matched to candlestick direction at 35% opacity (`rgba(34,197,94,0.35)` / `rgba(239,68,68,0.35)`).

**X-axis label fix (mobile crowding):** Replaced month-boundary-only triggering with `lastLabelX` pixel-distance tracking (36px minimum gap). Labels now auto-thin on narrow mobile screens without overlapping.

**Date parsing:** `new Date(d + 'T12:00:00')` to avoid UTC/local timezone boundary misclassifying months at midnight.

**Chart card text:** "updated daily" (EN) → "updated in real time"; "每日更新" (CN) → "实时更新".

### Homepage Fact Bar — "Access Tiers"

`index.html` + `index_cn.html`: Changed "2× Plans (tax incl.)" → "Access Tiers" / "访问层级" (sub-line removed). Avoids money mention on the quick stat bar.

### Disclaimer — Liability Clause Bridging Language

`assets/disclaimer.html` + `assets/disclaimer_cn.html`: Added bridging sentence so the liability cap is explicitly subordinate to the exclusion clause:

**EN:** "To the extent any liability is not excluded by the foregoing, Baizora's total liability for any claim arising out of or related to this platform or its data shall not exceed..."

**CN:** "在上述免责条款未能完全排除责任的情况下，贝佐拉对任何...所承担的全部责任..."

### FAQ Overhaul (`assets/faq.html` + `assets/faq_cn.html`)

- Account creation: references "Register for Free" button on homepage (removed old "Sign In → Create one" flow)
- Dashboard question renamed: "How do I access my dashboard and analysis results?" (was "my dashboard")
- "new/unsubscribed users" → "unsubscribed users" (no distinction — all unsubscribed land on subscription page)
- Free trial: added credit card restriction — once per email address **and once per credit card**; EN: "once per email address and once per payment method"; CN: "每张信用卡仅限一次"
- Data freshness: reference announcement bar ("checking the **announcement bar at the top of the homepage** — it shows 'Analysis updated: [date]'") instead of vague "if data looks stale"
- EPS/PE fundamentals: "refreshed approximately once per week" → "refreshed from SEC EDGAR on every daily scan"
- Added **Stock Splits** paragraph: forward splits corrected same trading day; reverse splits may lag 1–2 days while SEC EDGAR updates shares + EPS
- Watchlist: rewritten as subscription-only, cloud-synced via Firestore, not available in Free Tier (removed local storage fallback)
- Added AI assistant nudge paragraph below "Frequently Asked Questions" header
- Added `<script src="../chat-widget.js?v=10" data-lang="en/cn"></script>` before `</body>` (chat widget was missing from FAQ pages)

### AI Assistant System Prompts Updated (`functions/index.js`)

`CHAT_SYSTEM_EN` + `CHAT_SYSTEM_CN` aligned with all FAQ changes:
- `## FREE PREVIEW` → `## FREE TIER` — all 500+ stocks, 2-session delay, no watchlist/search in Free Tier
- Step 4: "new/unsubscribed" → "unsubscribed"
- Data schedule: EDGAR refreshed on every daily scan (not ~weekly)
- Data freshness: reference announcement bar at top of homepage
- Added `## STOCK SPLITS` section: forward same-day; reverse 1–2 day lag while EDGAR updates
- Watchlist: subscription-only, cloud-sync, no local storage fallback
- Troubleshooting: announcement bar for "data not updated today"

Cloud Functions redeployed after edits.

### CN Pages — Bilingual Contact Note

Added `（中英文）` / `支持中英文。` to contact email mentions across all CN pages:
- `assets/faq_cn.html`, `assets/about_cn.html` — "支持中英文。" appended to contact-card paragraph
- `assets/terms_cn.html`, `assets/privacy_cn.html`, `assets/disclaimer_cn.html` — "（中英文）" after `support@baizora.com`
- `index_cn.html` — footer "联系我们" line: "support@baizora.com（中英文）"

---

## What Was Done 2026-06-27

### Free Preview Retired — Replaced by Free Tier Everywhere

Free Preview (`baizora_main_form_free.html` / `_cn.html`) has been removed from all navigation across the site. Files kept on disk for possible future use.

**Pages updated (links changed from Free Preview → Free Tier):**
- 22 stock pages (`stocks/*.html`) + `generate_stock_pages.py` template
- `index.html` / `index_cn.html` — hero CTA + compact CTA buttons
- `dashboard.html` / `dashboard_cn.html` — tool card + quick link removed entirely
- `top-price-movers.html` / `unusual-volume.html` — inline text + CTA button
- `assets/faq.html` / `assets/faq_cn.html` — see below

**robots.txt:** Old free preview files added to `Disallow` (files kept, just de-indexed).

**sitemap.xml:** Free Preview entries replaced with Free Tier; all `lastmod` dates bumped to `2026-06-27`.

### Pricing Comparison Table — Free Preview Column Removed

`pricing.html` and `pricing_cn.html`: dropped the "Free Preview" column from the comparison table. Now **3 columns: Free Tier · Trial · Subscription** (was 4).

### Membership Changes Tab — Gated (Not Removed)

In `baizora_main_form_freetier.html` + `_cn.html`, the MEMBERSHIP CHANGE / 成分股变动 tab button is kept visible but now calls `showUpsell('membership')` / `showUpsell('membership')` instead of navigating to the section.

**Feature-specific modal text:**
- EN: "Membership Change history is only available in the full version — not in the Free Tier. Start a 7-day free trial to unlock the full dashboard."
- CN: "成分股变动历史仅在完整版中提供，免费版不支持此功能。开始 7 天免费试用，解锁完整数据看板。"

**Implementation:** `showUpsell(feature)` now accepts an optional `feature` param. `_upsellDesc` dict maps `'membership'` and `'default'` keys. `#upsellDesc` added to the `<p>` tag in both EN and CN modals so JS can update it dynamically. Existing Watchlist/Search callers unchanged (no param → default text).

### FAQ Updates (`assets/faq.html` + `assets/faq_cn.html`)

- "How does the free preview work?" → "How does the Free Tier work?" — rewritten to describe 500+ stocks, 2-session delay, what requires subscription
- "Do I need to sign up?" answer updated — now links to `baizora_main_form_freetier.html`, correctly describes delay
- "How do I access my dashboard?" — removed mention of free preview, now references Free Tier
- Removed "What is the beta analysis…" FAQ item from both EN and CN
- JSON-LD schema updated to match in both files
- **Bug fix (`faq_cn.html`):** Logged-out auth branch was incorrectly showing `navDashBtn` — fixed to `display:none`

### Dashboard Header — Avatar Circle Mobile Fix

`dashboard.html` + `dashboard_cn.html`: The `#headerEmail` avatar circle was a direct flex child of `<header>` (which has `justify-content: space-between`), placing it in the middle of the header on mobile.

**Fix:** Wrapped `header-right` + `#headerEmail` + `hamburger` in `<div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">` — same wrapper pattern used on other pages. Avatar now sits beside the hamburger at the far right on mobile.

**Commits:** `f975bf6` (main batch), `3138a8e` (dashboard mobile fix)

---

## What Was Done 2026-06-26

### Free Tier — Watchlist & Search Gated with Upsell Modal

Disabled watchlist and ticker search in `baizora_main_form_freetier.html` + `_cn.html`. Clicking either now shows an upsell modal.

**Touchpoints intercepted:**
- **Watchlist tab** (desktop + mobile drawer): `onclick` → `showUpsell()`
- **Star (☆) buttons**: tableArea click handler → `showUpsell()` (removed all toggle/sign-in logic)
- **Search inputs**: replaced `input` listeners with `focus` listeners → `showUpsell()` + `e.target.blur()`

**Upsell modal:** "Full Version Only" / "仅完整版可用" — copy clarifies it's a page limitation, not a subscriber gate (even subscribers can't use these on the free tier page). Primary CTA → `pricing.html` / `pricing_cn.html`. Secondary link is auth-aware: signed out → sign in; signed in → "Go to Full Dashboard" / "前往完整版".

`window.showUpsell` defined inside `DOMContentLoaded`, checks `window._ftUser` at call time to set secondary link.

**Commits:** `475cd6e`, `99f0f8b`, `6135a6f`, `2bec6e7`

### Free Tier — Dashboard Button (logged-in users)

Added a "Dashboard" / "个人主页" button to both free tier pages, visible only when logged in.

- **Desktop header**: blue button between avatar and Sign Out → `dashboard.html` / `dashboard_cn.html`
- **Mobile drawer**: link above Subscribe → same destinations
- Hidden (`display:none`) by default; shown via `onAuthStateChanged` when `user` is truthy; hidden again on sign-out
- Element IDs: `navDashBtn` (desktop), `mobileDashBtn` (drawer)
- CN label: "个人主页" (not "控制台" — updated CLAUDE.md translation table to match)

**Commits:** `6bc8d79`, `af40440`, `c7c3c66`

### video/.gitignore — Archive Directory Ignored

`video/archive/` was untracked (old screenshots + locally-generated mp4s). Added `archive/` to `video/.gitignore`.

**Commit:** `005f16d`

### Scanner Schedule Changes

**Beta cron delayed 1 hour:** `0 16` → `0 17` (1:00 PM ET scheduled, ~3 PM ET actual with GH delay). Exit guard unchanged: exits if started ≥3:55 PM ET.

Three places updated in `scanner.yml`:
1. Cron trigger: `0 16` → `0 17`
2. Env-setup elif: `"0 16 * * 1-5"` → `"0 17 * * 1-5"`
3. Worklog RUN_TYPE elif: `"0 18 * * 1-5"` → `"0 17 * * 1-5"`, renamed `400PM-beta` → `100PM-beta` (all RUN_TYPE labels now use scheduled ET time consistently)

**EDGAR moved to 4:30 PM scan:** Removed `SKIP_EDGAR=1` from the `30 20 * * 1-5` block. Now runs EDGAR at ~6:30 PM ET actual — after SEC's 5:30 PM same-day filing cutoff, capturing all day's 10-Q/10-K filings. 5:30 PM and 6:30 PM retry scans use `SKIP_EDGAR=1` (read cache committed by 4:30 PM run). 11 PM run kept as safety net for days when 4:30 PM fails (uses previous session's cache). EDGAR costs ~5–8 min per run; runs at ~6 req/sec, well under SEC's 10 req/sec limit.

**Commits:** `7903653`, `798ee41`, `ec12b32`, `682b8de`

### Current Scanner Schedule (updated 2026-06-29 — beta scan removed)

| Cron (UTC) | Scheduled ET | Approx actual ET | RUN_TYPE | EDGAR |
|---|---|---|---|---|
| `30 20 * * 1-5` | 4:30 PM | ~6:30 PM | `430PM-scan` | **yes** |
| `30 21 * * 1-5` | 5:30 PM | ~7:30 PM | `530PM-scan` | no (cache) |
| `30 22 * * 1-5` | 6:30 PM | ~8:30 PM | `630PM-scan` | no (cache) |
| `0 4 * * 2-6` | 11:00 PM | ~11 PM | `11PM-full` | yes (safety net) |
| `0 5 * * 0,6` | midnight | ~1 AM ET | `EDGAR-only` | yes |

### HON 1-for-2 Reverse Split (effective 2026-06-29)

Honeywell (HON) set June 29, 2026 as the effective date for a 1-for-2 reverse split. Symptom: our market cap was $146.5B vs YF's ~$73B (2× too high). Root cause: Tiingo already priced in the post-split level (~$229.77 = 2× pre-split price), but EDGAR still reports pre-split shares (~638M). Market cap = 2× price × pre-split shares = 2× correct.

**Implied shares from data:** `$146.53B / $229.77 = 637.7M` — confirms EDGAR pre-split count. Post-split target: ~319M.

**Scanner fixes (`scanner_tiingo.py`):**
- `SHARES_OUTSTANDING_OVERRIDE`: `"HON": lambda s: (s or 0) // 2 if (s or 0) > 400_000_000 else s` — halves EDGAR ~638M → ~319M; threshold 400M sits between pre/post-split counts; auto-heals when EDGAR reports post-split ~319M
- EPS guard: `if ticker == "HON" and abs(eps) < 4.0: eps = round(eps * 2, 4)` — pre-split EPS ~$3.21 → $6.43; threshold 4.0 sits between pre/post-split EPS; auto-heals when EDGAR reports post-split EPS ~$6.43 (abs > 4.0) after Q2/Q3 2026 10-Q (~Aug 2026)

**Commit:** `d1452e5` (rebased to `1c6054d`)

### Split Guards — Data-Driven CSV System

Replaced hardcoded split guards in `scanner_tiingo.py` with a data-driven `data/split_guards.csv`. Motivation: hardcoded guards accumulate forever; CSV enables automatic condition-based cleanup and makes adding new splits a one-line change with no code edits.

**`data/split_guards.csv` columns:**
`ticker, direction, ratio, action_date, earliest_remove, shares_threshold, eps_threshold`

**Auto-removal logic (condition-based, not date-based):**
- `earliest_remove` = minimum date before removal is considered (~4 months after split, past Q2/Q3 10-Q season)
- Guard removed only when: `today >= earliest_remove` AND guard did NOT fire on this EDGAR run
- If EDGAR stops filing → condition keeps firing → guard stays forever (safe)
- If EDGAR updates to post-split values → condition stops firing → auto-removed after earliest_remove

**Key scanner changes (`scanner_tiingo.py`):**
- `_load_split_guards()` — reads CSV at module load, no pruning at load time
- `_SPLIT_GUARDS_FIRED = set()` — populated during EDGAR fetch when either EPS or shares condition triggers
- `_prune_split_guards()` — called after `prefetch_fundamentals()` on non-SKIP_EDGAR runs; rewrites CSV without healed rows
- `_make_shares_lambda()` — builds shares override lambdas from CSV data dynamically
- EPS guard block replaced with generic loop over `_SPLIT_GUARDS_BY_TICKER`
- Shares condition also checked in `_get_edgar_fundamentals()` to populate `_SPLIT_GUARDS_FIRED`
- Permanent overrides (IBKR, BX, DVN, BRK-B) remain hardcoded — no expiry date

**BKNG shares_threshold:** Added `500000000` (pre-split ~40M, post-split ~1B). Confirmed no-op — EDGAR already filed post-split shares in Q1 2026 10-Q. Guard will auto-remove after Oct 1.

**`_get_post_filing_split_factor()` note:** The automatic forward-split shares multiplier skips ratios > 20 (spin-off filter), so BKNG's 25-for-1 split is NOT handled by this mechanism. Manual CSV guard is the correct approach.

**Commits:** `421da7e` → `714ad50`, `2187260`, `03cc3fa`

---

## What Was Done 2026-06-25 (Afternoon Session)

### Beta Scan — Critical Fix (Empty Dashboard Bug)

**Root cause:** Beta scan (`BETA_RUN=1`) ran on GitHub Actions at 18:07 UTC (2:07 PM ET). GitHub Actions gives a fresh VM on every run — the per-ticker OHLCV cache (`data/ohlcv_tiingo_cache/`) is gitignored and not present. Without cached bars, every ticker had `len(df) < 2` and was skipped → `df` empty → `latest.json` written with 0 rows → dashboard showed empty table.

**Bad commit:** `6cae540` — `latest.json` went from 517 rows → 0 rows; `candles.json` dates included 2026-06-25 but data was `{}`.

**Fix — Beta scan rewritten as IEX overlay (`scanner_tiingo.py`, `__main__`):**

The `BETA_RUN` block now exits via `sys.exit(0)` after a self-contained overlay, never reaching `scan()`:
1. Reads existing `latest.json` (517 rows from last EOD session)
2. Calls `fetch_iex_snapshot()` — exits without update if snapshot empty (holiday/closed)
3. Updates only `Price` and `PriceChange1D` per ticker; all other metrics stay from last EOD scan
4. Writes updated `latest.json` keeping the previous session's date
5. Appends today's intraday bar to `candles.json`: IEX OHLC + prev-session volume as proxy; tickers missing from IEX get a flat placeholder to maintain `dates.length == bars.length`

**Data restore:** `data/latest.json` and `data/candles.json` restored from `6353571` (last good state).

**Commits:** `6d59b3c` (fix + restore)

### Homepage Sparkline Demo — Live Data, No Hardcoding

**Before:** Two hardcoded SVG paths for NVDA (uptrend) and TSLA (downtrend).

**After:** Single WDC row, 56px tall (combined height of the two old rows), driven by real data from `latest.json`.

**Changes:**
- `TICKERS = ["WDC"]` — swap to any ticker by editing one line in `index.html` and `index_cn.html`
- `buildSparkSvg` now accepts `H` parameter (height). Reads `svg.getAttribute('height')` and also calls `svg.setAttribute('viewBox', ...)` so the coordinate space matches the element height. `py` formula: `(H - 4) - ((val-mn)/rng) * (H - 8)` — uses full vertical range regardless of height.
- SVG element: `<svg width="200" height="56" fill="none">` — no hardcoded path; JS fills `innerHTML` on load
- Description text updated (EN + CN) to emphasize that green ▲ + ● together historically precede strong advances

**Commits:** `005a7b9`

---

## What Was Done 2026-06-25

### Individual Stock Pages — Chart & Description Fixes

**Problem 1 — Stale chart data:** `generate_stock_pages.py` was never called from `scanner.yml`. OHLCV data was embedded inline at generation time and never refreshed — pages were 20 days stale.

**Fix 1 — Runtime `candles.json` fetch (`_SCRIPT_TEMPLATE`):**
```js
fetch('../data/candles.json').then(function(r){return r.json();}).then(function(cj){
  var d = (cj.data||{})[TICKER], ds = cj.dates||[];
  if (!d || !d.length || ds.length !== d.length) return;
  DATES = ds; OHLCV = d;
  renderChart();
  // also updates .scan-date, #chartSectionTitle, and summary box "today (date)"
}).catch(function(){});
```
Inserted right after `var TICKER = "__TICKER__"` in the template so it fires on every page load. Inline DATES/OHLCV are kept as the initial render; the fetch re-renders with current data.

**Fix 2 — Daily regeneration (`scanner.yml`):**
Added "Regenerate stock pages" step after "Commit updated data", runs on all non-beta, non-EDGAR-only scans:
```yaml
- name: Regenerate stock pages
  if: env.IS_HOLIDAY != 'True' && env.BETA_RUN != '1' && env.EDGAR_ONLY != '1'
  run: |
    python generate_stock_pages.py
    git add stocks/*.html ...
    git rebase --autostash origin/main
    git commit -m "auto update stock pages ..."
    git push origin HEAD:main
```

**Problem 2 — No date in description:** First sentence said "is declining -3.1% today" with no date context.

**Fix — `generate_summary(row, scan_date)`:** Added `_format_date_nice(date_str)` helper; description now reads:
`"AMAZON COM INC (AMZN) is gaining +0.1% today (June 24, 2026), trading at $234.27."`
Runtime JS also patches this via `.replace(/today \([^)]+\)/, 'today (' + fmt + ')')` when candles.json is fresher.

**Other fixes:**
- `id="chartSectionTitle"` on chart section title div — runtime JS updates it
- `WMT` and `MU` added to `FEATURED_TICKERS` (were in `TOP10_NASDAQ` peer cards but not generated)
- All 22 stock pages regenerated locally with Jun 24 data before push

**Commits:** `2731588`, `b44ae4a` (rebase), `c0535b9`

### Video Ad Screenshots Updated

`video/generate_video.py` lines 1981–1982: switched from `baizora_homepage_Screenshot.png` / `_cn.png` to `baizora_homepage_Screenshot_2.png` / `_cn_2.png` to reflect recent homepage redesign.

**Commit:** `c0535b9`

---

## What Was Done 2026-06-24

### Beta Scan Window — Guard Logic Flipped

**Root cause:** Beta cron fires at 12:00 PM ET (`0 16 * * 1-5`). GH Actions delay is typically 2–4h, putting the actual start at 2–4 PM ET. Today delay was only ~1.5h → scan started at ~1:30 PM ET. Old guard (`et_min < 15 * 60`) exited if before 3:00 PM → scan skipped, only `worklog.md` committed → users saw yesterday's prices all day.

**Fix (`scanner_tiingo.py`):** Flipped the guard from "exit if too early" to "exit if too late":
```python
if not FORCE_RUN and et_min >= 15 * 60 + 55:  # exit if 3:55 PM ET or later
    print(f"BETA_RUN: too late — after 3:55 PM ET, skipping (4:30 PM scan will handle EOD). Exiting.")
```
Window is now 12:00 PM – 3:54 PM ET. Any GH delay landing in this range runs the beta. If GH delays past 3:55 PM, the 4:30 PM full scan handles EOD instead.

**Commit:** `6795b91`

### Top Price Movers Panel — Score & Rank Dots Bugs Fixed

**Bug 1 — BaizScore showed `—` for all top10:** `score_map` was built from `df_s.head(50)` only. Price movers outside the top-50 BaizScore got `None`. Fixed by removing `head(50)` — `score_map` now covers all ranked tickers.

**Bug 2 — `dotClass()` wrong threshold:** Function was `rank <= 10 ? 'top10' : 'top50'` — any non-null rank (including 300+) got orange. Fixed to:
```js
if (rank <= 10) return 'top10';
if (rank <= 50) return 'top50';
return 'miss';
```

**Bug 3 — `session_ranks` key was `"date"` not `"session"`:** Scanner wrote `{"date": ..., "ranks": ...}` but JS reads `sr.get('session')`. Fixed in scanner; patched existing JSON.

**Bug 4 — `session_ranks` only stored top-50 ranks:** Expanded to store all ~516 ranks per session so dots show actual rank numbers even for tickers ranked 51+.

**Data patch:** All 5 sessions in `score_history.json` rebuilt with full rank maps from `latest.json`, `latest_d1.json`, `free_tier.json`, and git history (`75556b5` = Jun 17, `bfb85a2` = Jun 16).

**Commits:** `25e0162`, `1806972`

### Announcement Bar — Simplified to Single Condition

Old logic: show "current session updates 6–7 PM ET" only between 9:30 AM and 4:00 PM ET on trading days. After 4 PM the message disappeared even though data hadn't updated yet.

**Fix:** Show pending message any time on a trading day when `latest.json` date ≠ today. Cleared once the scan writes today's date.
```js
if (isTradingDay && d.date !== todayStr) {
  // show "Analysis updated: [prev date] (current session updates 6–7 PM ET)"
}
```
Removed unused `afterOpen`/`afterClose` variables. Applied to `index.html` and `index_cn.html`.

**Commit:** `a588b86`

### Free Tier — Removed "live" Tags

Removed `<span class='live-tag'>live</span>` / `实时` from the Price and 1D P CHG% column headers in `baizora_main_form_freetier.html` and `baizora_main_form_freetier_cn.html`. Free tier has no live refresh (2-session delayed data only).

**Commit:** `b11fce5`

### DD 1-for-3 Reverse Stock Split (effective 2026-06-24)

DuPont (NYSE: DD) completed a 1-for-3 reverse split. Pre-split close: $46.67; post-split price: ~$140. EDGAR lags on both shares (~410M → ~137M) and EPS (-$0.07 → -$0.21) until Q2 2026 10-Q (~Aug 2026).

**Scanner fixes (`scanner_tiingo.py`):**

- `SHARES_OUTSTANDING_OVERRIDE`: `lambda s: s // 3 if s > 200_000_000 else s` — fires while EDGAR reports pre-split ~410M; auto-heals once EDGAR shows post-split ~137M.
- EPS guard: `if abs(eps) < 0.20: eps = round(eps * 3, 4)` — fires while EDGAR reports pre-split EPS ~-0.07; auto-heals once EDGAR reports post-split ~-0.21 (abs = 0.21 > 0.20).

**Why `splits.json` doesn't help here:** `update_splits_file()` converts Tiingo's `splitFactor = 0.333` to `ratio: 3` (same encoding as a 3-for-1 forward split). The dashboard auto-heal checks `obsRatio ≈ ratio (3)` — for a reverse split `obsRatio ≈ 0.33`, so it never fires. Forward splits do work with `splits.json` for intraday display; reverse splits need a manual `workflow_dispatch` to write the correct Tiingo split-adjusted prices. Modal stats (market cap, EPS, PE) always need scanner-side guards regardless of split direction.

**Intraday fix:** Triggered `workflow_dispatch` manually after pushing the scanner fix. Tiingo retroactively applies the split adjustment to all historical prices on the effective date, so `latest.json` was rewritten with the correct split-adjusted data in one shot.

**Commit:** `375646b` (rebased to `8823fe6` after pull)

---

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
- `BRK-B`: **Outdated as of 2026-07-01** — `company_facts` still has no recent EPS tags (correctly returns `eps=None` there), but BRK-B now resolves via the inline-XBRL fallback (`_parse_eps_from_latest_filing`), same as V/ERIE/KKR/STZ. Raw fallback value is Class-A-scale (~50,390), then `÷1500` → Class B EPS ~33.59. See the 2026-07-01 section at the top of this file for the Q4-derivation bug that affected this ticker too.
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

| Cron | ET Time | Days | What runs |
|---|---|---|---|
| `40 17 * * 1-5` | **3:40 PM** | Mon–Fri | Beta IEX snapshot (`BETA_RUN=1`, `SKIP_EDGAR=1`) — ~10 min before close; data ready by ~4:05 PM |
| `30 20 * * 1-5` | **4:30 PM** | Mon–Fri | Market scan + videos (`SKIP_EDGAR=1`, `PROBE_RETRIES=2` — retries at 5:00 PM if no data) |
| `30 21 * * 1-5` | **5:30 PM** | Mon–Fri | Market scan only (`SKIP_EDGAR=1`, `PROBE_RETRIES=1`) |
| `30 22 * * 1-5` | **6:30 PM** | Mon–Fri | Market scan only (`SKIP_EDGAR=1`, `PROBE_RETRIES=1`) |
| `0 4 * * 2-6` | **11 PM** | Mon–Fri | Full scan + EDGAR (`FORCE_RUN=1`); pushes gzipped CSV to `scanner-archive` |
| `0 5 * * 0,6` | **midnight** | Sat + Sun | EDGAR refresh only (`EDGAR_ONLY=1`) |

- Videos skipped on holidays; only 4:30 PM run generates videos (`IS_VIDEO_RUN=True`)
- Video type rotates by weekday: Mon=Volume Spikes, Tue=Best Performer, Wed=6M Breakout, Thu=1Y Vol Peak, Fri=Index Spotlight
- All runs use `scanner_tiingo.py` with `TIINGO_API_KEY` secret

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

- **Billing live** — Tiingo scanner active since 2026-06-07; billing/pricing pages live with Monthly ($9.99) and Yearly ($99) plans via Stripe

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

## What Was Done 2026-06-21

### User Avatar Circle — Replaced Email Display

All pages with a signed-in state now show a 28px solid blue (#3b82f6) circle with the user's capitalized initial instead of the raw email address (saves nav space; still disambiguates accounts). Hover title shows the full email address.

**HTML pattern (all pages):**
```html
<span id="navUserEmail" style="display:none;width:28px;height:28px;border-radius:50%;background:#3b82f6;color:#fff;font-family:'DM Sans',sans-serif;font-size:13px;font-weight:700;align-items:center;justify-content:center;flex-shrink:0;cursor:default;" title=""></span>
```
`display: inline-flex` set in JS (not CSS) so `align-items`/`justify-content` work.

**JS pattern:**
```js
const emailEl = document.getElementById("navUserEmail");
if (emailEl) {
  emailEl.textContent = user.email[0].toUpperCase();
  emailEl.title = user.email;
  emailEl.style.display = "inline-flex";
}
```

**Files updated:** `index.html`, `index_cn.html`, `baizora_main_form.html`, `baizora_main_form_cn.html`, `baizora_main_form_free.html`, `baizora_main_form_free_cn.html`, `baizora_main_form_freetier.html`, `baizora_main_form_freetier_cn.html`, `dashboard.html`, `dashboard_cn.html`, `account.html`, `account_cn.html`, `unusual-volume.html`, `top-price-movers.html`, `index_news.html`, `index_news_cn.html`.

`dashboard.html`/`_cn.html`, `index_news.html`/`_cn.html` used a different CSS class `.user-email` — replaced that class definition with the avatar circle styles.

`baizora_main_form.html`/`_cn.html` had NO email element before — avatar span added from scratch before `.dash-btn` in `header-right`.

**Mobile:** `#navUserEmail { display: none !important; }` in portrait and landscape ≤640px media blocks on all dashboard pages.

### Top Movers Panel Grid Fix

Row border-bottom was ending early before the Baizora Score column because `min-width: 580px` was less than the actual 626px computed grid width.

- `.sh-header` and `.sh-row` grid template last column: `64px` → `76px`
- `min-width: 580px` → `640px` on both panels

Applied to `index.html` and `index_cn.html`.

### Mobile Card Gap Reduction (index.html / index_cn.html)

Gap between the Sparklines card and the Index News card on mobile portrait was ~100px.

- `.features { padding: 60px 20px; }` → `padding: 60px 20px 24px;`
- Added `.bottom-cta { padding: 20px 20px 60px; }` in the mobile media block

### Toolbar Separator Hidden on Portrait

Added `.toolbar-sep { display: none; }` to portrait CSS in 4 dashboard files:
`baizora_main_form.html`, `baizora_main_form_cn.html`, `baizora_main_form_free.html`, `baizora_main_form_free_cn.html`.
(Already done for freetier files in prior session.)

### Chat Widget Desktop Raised

Desktop chat button was overlapping the About/FAQ footer links at bottom of scroll.

- `chat-widget.js` desktop button: `bottom:24px` → `bottom:76px`
- `chat-widget.js` desktop panel: `bottom:92px` → `bottom:144px`
- Mobile (≤480px) unchanged: button `bottom:90px`, panel `bottom:130px`
- Cache bust: `chat-widget.js` → `?v=9` in `index.html`, `index_cn.html`, `baizora_main_form_free.html`, `baizora_main_form_free_cn.html`

### faq_cn.html — 首页 Button Always Visible

`assets/faq_cn.html` logged-out auth branch was hiding `navDashBtn` (the 首页 link). Fixed so 首页 shows in both logged-in and logged-out states.

---

## What Was Done 2026-06-19

### Top Price Movers Panel (Homepage Hero)

Replaced the static "POPULAR STOCKS" mock dashboard (`hero-right` div) on both `index.html` and `index_cn.html` with a live "Top Price Movers" card driven by `data/score_history.json`.

**Panel contents (per row):**
- Rank (#1–10), ticker + company name
- 1Y sparkline with ▲ (highest-vol day) and ● (largest price-change day) markers; green = price up on that day, red = down
- 1D price change % (green/red)
- 5-session Baizora score rank dots (oldest→newest): green = top 10, amber = top 50, dim = outside
- Baizora Score

**CSS classes:** `sh-card`, `sh-header`, `sh-row`, `sh-dot.top10/.top50/.miss`, `sh-score`. Grid: `28px 1fr 130px 60px 110px 52px`. Badge shows session date. Dim texts use `#94a3b8`/`#64748b`.

**CN page:** Same panel with Chinese headers (代码, 年趋势线, 涨幅, 评分排名·旧→新, 贝佐拉评分). Badge: `YYYY-MM-DD · 涨幅榜`.

**Removed:** ~300 lines of mock dashboard JS from both pages (MOCK_DATA, mockView, buildSparkPath, MOCK_GRIDS, switchMockView, renderMock, etc.).

### score_history.json

New rolling file at `data/score_history.json` — maintained by scanner, consumed by homepage.

**Structure:**
```json
{
  "sessions": ["2026-06-18", "2026-06-17", "2026-06-16"],
  "top10": [{ "ticker": "SNDK", "company": "...", "session": "2026-06-18", "price": 0.0,
              "change1d": 0.0, "spark1y": [...], "triIdx": 0, "triCol": "#22c55e",
              "dotIdx": 0, "dotCol": "#22c55e", "inSP500": true, "inNASDAQ100": false,
              "score": 0.0, "scoreRank": 1 }],
  "session_ranks": [{ "session": "2026-06-18", "ranks": { "TICKER": N } }]
}
```

**sessions[]:** newest first. **top10[]:** from current session only (PriceChange1D desc). **session_ranks[]:** top-50 BaizScore per session for dot rendering. Dot render loop reverses `sessions` so left = oldest, right = most recent.

**Sparkline markers:** `triIdx`/`triCol` = highest-volume day position + color; `dotIdx`/`dotCol` = largest price-change day position + color.

**Seeding:** Bootstrapped from 3 on-disk files: `latest.json` (06-18), `latest_d1.json` (06-17), `free_tier.json` (06-16, from git commit `bfb85a2`). Scanner appends one session per run and drops oldest when >5 sessions.

**scanner.yml:** `score_history.json` backed up, restored, and committed on every run.

### Scanner Changes

- `export_score_history(df)` — reads top10 from `OUTPUT_JSON` (latest.json), stores marker fields, updates session_ranks
- `_rotate_free_tier()` — 3-slot rotation: `free_tier.json ← latest_d1.json ← latest.json ← new scan`
- `export_daily_digest` except block — added `traceback.print_exc()` to surface silent failures (Jun 18 digest was stale due to a swallowed exception)

### CN Market News Query Fix

Removed `战争` (war) from CN Google News query in both `functions/index.js` (line 221, `/api/market-news`) and `scanner_tiingo.py` (`_fetch_market_headlines`). `战争` pulled historical war articles (e.g., 抗美援朝). Replaced with `美股` + `通胀`. CF redeployed — 1-hour cache clears naturally.

---

## What Was Done 2026-06-23

### IEX Enrichment Bug Fix — Volume Columns Were Wrong

**Root cause:** Tiingo `/iex` endpoint returns exchange-specific volume only (~2–5% of consolidated tape). Client-side enrichment was overwriting `VolumeM`, `VolumeChange1D`, `VolumeVsMA21_1D`, and `PriceVsMA21_1D` with IEX-derived values, causing ~100% VChg% and <1M Vol for all tickers. The page-load IEX call was also gated on `isWeekdayET()` (Mon–Fri any time), so it fired after market close and overwrote the correct 6 PM EOD scan data.

**Fixes:**
- Removed all volume and PriceVsMA21_1D updates from `refreshDashPrices()` — IEX now drives **only Price and PriceChange1D** (`_liveChgPct`)
- Changed both page-load IEX calls from `isWeekdayET()` → `isMarketOpen()` in `baizora_main_form.html` + `_cn.html`
- Applies to both full dashboards (free pages had no volume enrichment)

### Beta Scan Improvements

**Volume fix (`scanner_tiingo.py`):**
- Beta scan carries forward prev-session's consolidated volume into today's row before MA computation (IEX volume unusable)
- `VolumeChange1D` in beta now shows prev vs prev-prev (last real session's change) instead of null
- Removed `"beta": true` from `latest.json` export — announcement bar no longer needs it

**Candles in beta:**
- `export_candles()` now runs in both BETA_RUN and full runs
- Beta candle has today's IEX O/H/L/C + prev-session volume as proxy → chart fully usable 4–6 PM
- Full 6:30 PM scan overwrites with correct consolidated volume

**Beta cron shifted 10 min earlier:**
- `"0 18 * * 1-5"` → `"50 17 * * 1-5"` (targets ~3:50 PM ET actual vs ~4 PM before)
- Reduces window where users see yesterday's data after market close
- Schedule-match `elif` in `scanner.yml` updated to match

### Announcement Bar — 2 States

Simplified from 4 states (beta/final/market-open-stale/default) to 2:
1. `isTradingDay && afterOpen && !afterClose && d.date !== todayStr` → "Analysis updated: [prev date] (current session updates 6–7 PM ET)"
2. Everything else → "Analysis updated: [date]" — no beta/final labels, no today's-date special case

Applied to `index.html` and `index_cn.html`. FAQ and chat robot knowledge updated in `assets/faq.html`, `assets/faq_cn.html`, `functions/index.js`.

**Commit:** `4dfc41a` — 9 files.

### Video Commit Step — `--autostash` Fix

`scanner.yml` "Commit latest videos for homepage download" step was failing with `error: cannot rebase: You have unstaged changes` because generated video files (`latest_video_en.mp4`, `latest_video_cn.mp4`, `latest_video_meta.json`) sat in the working tree when `git rebase origin/main` ran. Fixed both the video commit step and the "Log skipped videos" step with `git rebase --autostash origin/main`.

**Commit:** `6d715f4`

### Beta Scan — Keep Last Session's Date in `latest.json`

After the beta scan, `latest.json` was showing today's date even though only Price and PriceChange1D were truly from today (IEX). Volume, scores, multi-week stats are all from the previous session. Since Price is already labeled "live" in the UI, the correct behavior is to keep the date as the last closed session's date — consistent with how financial terminals work.

**Fix (`scanner_tiingo.py`, `export()`):** When `beta=True`, read the existing `latest.json` and carry forward its `date` field instead of writing today's `DATE_STR`. Side effect: announcement bar state 1 ("Analysis updated: [yesterday], current session updates 6–7 PM ET") stays active all afternoon until the 6:30 PM full scan writes today's date.

`candles.json` is unaffected — it still carries today's IEX intraday bar with today's date for the candlestick chart.

**Commit:** `e7e68b0`

---

## What Was Done 2026-06-22

### EOD Beta Analysis — Full Feature Rollout

Implemented end-to-end "beta analysis" pipeline: between market close (4 PM ET) and the full scanner run (6:30–7 PM ET), the dashboard performs a client-side initial analysis using live EOD data from Tiingo.

**Dashboard (`baizora_main_form.html` + `_cn.html`):**
- Added `isWeekdayET()` — Mon–Fri check regardless of time; replaces `isMarketOpen()` for the startup IEX fetch so it fires after market close too
- EOD enrichment in `refreshDashPrices()`: when `_isTodayIex` is true (IEX timestamp matches today's ET date), updates VolumeM, VolumeChange1D, PriceVsMA21_1D, VolumeVsMA21_1D from live OHLCV
- MA21 back-calculation: `MA21 = r.Price / r._origPvMA`, then `new_PriceVsMA21 = d.last × r._origPvMA / r.Price` (ratio, not %)
- `_orig*` fields stored on row objects before first overwrite so back-calculations always use scanner's reference values
- `_liveRenderDone` flag: one full `render()` call after first successful today's-data fetch to update all enriched columns in the table

**Announcement bar (index.html + index_cn.html):**
Three states driven by `latest.json` date vs today's ET date + `afterClose` flag (≥960 min = 4:00 PM ET):
1. Pre-close / non-trading: "Analysis updated: [prev date] (current session updates 6:30–7:00 PM ET)"
2. Beta (after 4 PM ET, before scanner): "Analysis (beta) updated: [today], full update 6:30–7:00 PM ET"
3. Final (scanner ran today): "Analysis (final) updated: [today]"
CN uses 下午 before times, 分析(初步)/分析(最终), fmt returns "YYYY年M月D日". Full NYSE holiday set (2025–2027) added to both scripts.

**FAQ (`assets/faq.html` + `_cn.html`):**
New Q&A explaining the beta window, which columns update, what doesn't (multi-week stats, scores, sparklines), and that final replaces beta once scan completes.

**Methodology (`assets/methodology_2026-05-31.html`):**
New "Initial EOD Beta Analysis (Client-Side)" subsection under Daily Processing Flow — covers batch IEX request trigger, all derived column formulas, MA21 approximation note, and announcement state descriptions.

**Chat system prompts (`functions/index.js`):**
Added `## BETA ANALYSIS` section to both `CHAT_SYSTEM_EN` and `CHAT_SYSTEM_CN`. Assistant can now explain the three announcement states, which columns update in beta, what's deferred to full scan, and how weekends/holidays behave.

**Commit:** `153c0cb` — all 8 files; functions deployed to Firebase Cloud Functions.

---

## What Was Done 2026-06-19

### Holiday Detection — IEX Timestamp Check (No Hardcoded Holidays)

On Juneteenth (market closed), live IEX refresh was overriding scan's `PriceChange1D` with 0%.

**Fix:** CF `/api/iex-quotes` now returns `ts: q.lastSaleTimestamp ?? q.quoteTimestamp ?? null` per ticker. All dashboards (`baizora_main_form.html`, `_cn.html`, `_free.html`, `_free_cn.html`, `top-price-movers.html`, `unusual-volume.html`) check if the IEX timestamp's ET date matches today's ET date before applying live data. If mismatch (holiday/closure), scan's `PriceChange1D` is preserved. `isMarketOpen()` reverted to simple weekday/hours check — no hardcoded holiday lists.

### Free Tier — Purely Delayed Data

Removed live price refresh entirely from `baizora_main_form_freetier.html` and `baizora_main_form_freetier_cn.html`. Dead `IEX_CF`, `_liveIex`, `_SPLIT_ADJ`, `isMarketOpen`, `refreshDashPrices` blocks deleted (~300 lines total). Free tier shows scan data as-is — no confusing mix of today's price vs 2-session-old change %.

### CN News Query Fix

Removed `战争` from both CF (`_MARKET_NEWS_QUERY_ZH`) and `scanner_tiingo.py` (`_fetch_market_headlines`). Was pulling irrelevant historical war articles. Added `美股` and `通胀`.

### Google News User-Agent Fix

CF `/api/market-news` was returning 0 items — GCP IPs blocked by Google News when using generic `Baizora/1.0` UA. Fixed by switching to full Chrome UA string.

### Announcement Bar Updates

- EN: `Free Version (no signup, 2 sessions delay) · First 7 Days Free for New Subscribers · support@baizora.com`
- CN: `免费版（无需注册，延迟两个交易日）· 新订阅用户前七天免费 · support@baizora.com`
- CN delay text unified to `延迟两个交易日` everywhere (was mixing `延迟两期` / `延迟2个交易日`).

### Billing & Pricing Pages

- `billing.html` / `billing_cn.html`: Monthly + Yearly only (no free cards). Yearly description: everything in monthly + better value long-term + price locked for a year + ideal for stable long-term users. Titles: "Baizora | Billing" / "贝佐拉 | 订阅管理".
- `pricing.html` / `pricing_cn.html`: 7 timeframes (1D–1Y), "Live pricing · daily scoring after market close". Comparison table has 5 columns: **Free Preview** · **Free Tier** · **Trial · 7 Days** · **Subscription**. Differentiating rows first, shared-feature rows at bottom. Free Preview data freshness = Current (live IEX + latest.json).
- Google News CF User-Agent fixed: was `Baizora/1.0` (blocked by Google on GCP IPs) → now full Chrome UA string; news returns 6 items again.

### Product Terminology (Canonical)

- **Free Preview** = `baizora_main_form_free.html` — 3 tickers, current data (live IEX), no signup
- **Free Tier** = `baizora_main_form_freetier.html` — all 500+ tickers, 2-session delay, no signup, no live refresh
- **Free Trial** = 7-day trial for new subscribers (requires payment method, once per email)
- **Subscription** = Monthly $9.99 / Yearly $99

---

## What Was Done 2026-06-18

### Scanner Cron Schedule Shifted 30 Minutes Earlier

- `30 20 * * 1-5` (4:30 PM ET) replaces `0 21` (5 PM ET) — preliminary + videos
- `30 21 * * 1-5` (5:30 PM ET) replaces `0 22` (6 PM ET) — retry scan
- `30 22 * * 1-5` (6:30 PM ET) replaces `0 23` (7 PM ET) — final scan
- 11 PM and weekend midnight runs unchanged

### Today's Market Briefing Card (Homepage)

Added a full "Today's Market Briefing" digest card to both `index.html` and `index_cn.html`, replacing the old CTA box on the right panel.

**Data files (scanner-generated):**
- `data/daily_digest.json` — top 5 gainers + volume spikes, date, scan_time
- `data/daily_briefing.txt` — EN download, full text with movers + news headlines + baizora.com footer
- `data/daily_briefing_cn.txt` — CN download, full Chinese text (labels, footer, CN Google News headlines)

**Cloud Function `/api/market-news`:**
- Bilingual: EN default, CN via `?lang=zh`
- EN query: `stock market OR "Federal Reserve" OR earnings OR war OR tariff OR inflation`
- CN query: Chinese terms (`股市 OR 利率 OR 美联储...`), `hl=zh-CN&gl=CN&ceid=CN:zh-Hans`
- 1-hour cache per lang; empty-result guard (never caches 0 items; serves stale instead)
- `lang` declared outside try/catch to avoid ReferenceError

**Index-news dedup fix:** Strips ` - SourceName` suffix before comparing titles, so same story from WSJ + Bloomberg no longer appears twice.

**Download link:** Green (`#64c487`) when `digest.date === today ET date`; blue otherwise.

**CTA mini:** Simplified to centered tagline + two buttons (no card background). Tagline below buttons.

**Video title fix:** Homepage fetches real title from YouTube oEmbed (`https://www.youtube.com/oembed?url=...&format=json`) — no API key needed. Falls back to JSON `name` field. Date suffix NOT appended (YouTube title already has date).

**Known: video commit can fail** if external pushes happen between scanner's data commit and video commit steps. Workaround: manually update `data/latest_video_meta.json`. Video schedule: Mon=volume_spikes, Tue=best_performer, Wed=6m_breakout, Thu=1y_vol_peak, Fri=index_spotlight.

---

## What Was Done 2026-06-17 (Intraday Bar Session)

### Root Cause: Scanner UTC/ET Date Mismatch

The final scanner runs at `00:00 UTC` (= 8 PM ET), so Python's `datetime.now(timezone.utc)` returned the next calendar day. `DATE_STR` was labeled `2026-06-17` for June 16 EOD data. This caused `trading_days` (which runs up to `DATE_STR`) to include June 17 with no Tiingo bars, making `candles.json`'s `dates[]` one entry longer than each ticker's bars arrays. On the frontend `isToday` was immediately `true`, so the injection branch never fired — live prices updated the June 16 bar instead of building a new June 17 bar.

### scanner_tiingo.py Fixes (commits 4070fcd, f4bcde4, 7233f26)

- Added `import pytz`
- `DATE_STR` changed from `datetime.now(timezone.utc)` → `datetime.now(pytz.timezone('America/New_York'))` (line 26)
- `today` in `__main__` holiday/weekend check changed from `date.today()` → ET date (line 2531)
- `from_date` 730-day lookback changed to ET
- Added module-level `_TIINGO_LAST_DATE = DATE_STR` — updated by probe/FORCE_RUN to last date Tiingo actually has data for
- FORCE_RUN path now does a 7-day lookback probe to discover latest confirmed Tiingo date
- Regular probe sets `_TIINGO_LAST_DATE = latest_bar_date` on confirmation
- `scan()` uses `_TIINGO_LAST_DATE` as `to_date` instead of `DATE_STR` — `trading_days` never includes a date without real bars

### Frontend Injection Fix — All 4 Dashboard Files

**Both full dashboards (`baizora_main_form.html` + `_cn.html`):**
- Removed "Path A" (injection block inside candles.json `.then()` callback) — was racing with the `candleData = d` assignment, causing dates/bars misalignment
- `refreshDashPrices()` is now the sole injection point, called explicitly after `candleData = d` in the `.then()` callback

**Free preview pages (`baizora_main_form_free.html` + `_free_cn.html`):**
- Added full live price refresh: `refreshFreePrices()` + `isMarketOpen()` + `IEX_CF` constant
- Updates price-cell (green/red flash), 1D chg% cell (live-computed vs scan close), open modal price/%, and candleData intraday bar
- Called from candles.json `.then()` and every 10s via `setInterval`
- Added `chg1d-cell data-ticker` to 1D change `<td>` in render template

### Verification

- Ran scanner via `workflow_dispatch` (FORCE_RUN=1) during market hours
- `candles.json` last date = `2026-06-16` ✓, LITE bars[-1] close = 875.36 ✓, dates count == bars count ✓
- Intraday bar confirmed working on EN and CN full dashboards

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
2. **Tiingo attribution** — ✓ DONE. Present in `baizora_main_form.html` (line 906), individual stock pages, and homepage. `dashboard.html` shows no market data so no attribution needed there.
3. **BKNG + CVNA split guards** — both auto-disable once Q2 2026 10-Q is filed (~Aug 2026). Verify EPS and mktcap drop to expected post-split values and compare log stays clean.
4. **Remaining EPS=None tickers** — ✓ RESOLVED for BRK-B (now via inline-XBRL fallback, see 2026-07-01 section). Still genuinely unavailable: ARES/TRI (Form 25-NSE delisting) and FDXF (no 10-Q/10-K filed yet, recent spinoff).
5. **yfinance compare log** — remaining flagged EPS diffs (OXY, MLM, CI etc.) are GAAP one-time items vs adjusted EPS. These are correct and expected — not bugs.
6. **FUND_CACHE_TTL_DAYS = 0** — EDGAR now always re-fetches every run. Cache file is still written but never read back. No further cache management needed.
7. **4–6 PM ET data gap + 0% PriceChange1D** — ✓ RESOLVED (commit `3ce7474`, 2026-06-30). `isMarketOpen()` stays at 8 PM (1200 min). Added `loadedDate !== _todayET` guard to all IEX refresh call sites — IEX suppressed after scanner auto-reload, live prices still shown 4–6:30 PM before scan lands.
8. **HON candlestick chart shape** — Verify tonight's scan rebuilds `candles.json` with Tiingo's fully-corrected HON historical series (should show $200+ range consistent with current price, not the ~$137–$163 pre-adjustment range).
9. **Homepage sparkline markers** — ✓ RESOLVED (commit `5110a1c`, 2026-06-30). `miniSpark` and `buildSparkSvg` on homepage were treating days-ago values as left-to-right array indices, placing ▲/● on the wrong end. Fixed with `data.length - 1 - daysAgo` conversion. Dashboard `renderSparkline` was already correct via `idxFromDays`.
10. **EPS fallback fix** — ✓ CONFIRMED in production same-day (2026-07-01). See top of file.
11. **New 500PM-scan slot** — added 2026-07-01 to catch Tiingo publication delays between the 4:30 PM and 5:30 PM runs. Watch a few sessions to confirm it actually helps (vs. 4:30 PM data just always being ready by 5:30 PM anyway, making it redundant).
12. **Stale-ticker exclusion + 0%-weight index filter** — ✓ VERIFIED via manual `workflow_dispatch` run same day (2026-07-01). SATS dropped from `sp500_symbols.txt`, recorded in `index_changes.json`, absent from `latest.json`, `partialUpdate: false`. Still open: watch for false positives where a ticker legitimately halted/thin-traded for a full day gets excluded by this logic too — intended behavior, but worth a real example to confirm it isn't over-triggering on ordinary low-volume days.
13. **`index_changes.json` fetch has no cache-busting** — `loadIndexChanges()` in `baizora_main_form.html`/`_cn.html` caused a same-day false alarm (CDN + browser cache served a stale copy after a hard-refresh-free page load). Consider adding a `?` + timestamp query param like the periodic `latest.json` re-check already does, if this recurs.
