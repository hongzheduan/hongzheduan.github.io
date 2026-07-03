"""Baizora Scanner — yfinance emergency backup edition.

Standalone script: if Tiingo ever becomes unavailable, this generates
data/latest_yfinance.json in the same schema as data/latest.json, sourced
from yfinance instead. Meant to buy time, not replace Tiingo permanently.

Does NOT touch scanner_tiingo.py, scanner.yml, or any of their output files.

v1 known limitations (acceptable for a "buy time" stopgap, not a full parity
replacement):
  - Fundamentals (EPS/Sector/CompanyName/SharesOutstanding) are read read-only
    from data/fundamentals_cache.json (EDGAR-sourced, written by the normal
    scanner_tiingo.py pipeline) rather than re-fetched from EDGAR here. If
    Tiingo disappears for good, this cache stops refreshing too, even though
    EDGAR itself would still be reachable — a real gap if this ever needs to
    run standalone for an extended period.
  - No per-ticker staleness exclusion (partialUpdate/staleTickers always
    False/[]) — scanner_tiingo.py's same-day-publish detection isn't
    replicated here.
  - BRK-B market cap falls back to the cached TiingoMarketCap figure (if
    present) instead of a live dual-class-share calculation.
"""
import pandas as pd
import numpy as np
import time
import json
import os
import csv
from datetime import date, datetime, timedelta
import pytz
import yfinance as yf

# =========================
# CONFIG
# =========================

DATE_STR        = datetime.now(pytz.timezone('America/New_York')).strftime("%Y-%m-%d")
DATA_DIR        = "data"
OHLCV_CACHE_DIR = os.path.join(DATA_DIR, "ohlcv_yfinance_cache")
FUND_CACHE_FILE = os.path.join(DATA_DIR, "fundamentals_cache.json")   # read-only
SPLIT_GUARDS_FILE = os.path.join(DATA_DIR, "split_guards.csv")        # read-only
OUTPUT_JSON     = os.path.join(DATA_DIR, "latest_yfinance.json")

os.makedirs(DATA_DIR,        exist_ok=True)
os.makedirs(OHLCV_CACHE_DIR, exist_ok=True)

TIMEFRAMES = {
    "2W": 10,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "9M": 189,
    "1Y": 252,
}

YF_CHUNK_SIZE  = 60
YF_MAX_RETRIES = 3
YF_RETRY_WAITS = [5, 15, 45]
YF_CHUNK_DELAY = 2


# =========================
# NYSE HOLIDAY DETECTION (copied verbatim from scanner_tiingo.py — pure, no Tiingo dependency)
# =========================

def _easter(year):
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(114 + h + l - 7 * m, 31)
    return date(year, month, day + 1)


def _observed(d):
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nth_weekday(year, month, weekday, n):
    first = date(year, month, 1)
    first += timedelta(days=(weekday - first.weekday()) % 7)
    return first + timedelta(weeks=n - 1)


def _last_weekday(year, month, weekday):
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last = next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def nyse_holidays(year):
    h = set()
    h.add(_observed(date(year, 1, 1)))
    h.add(_nth_weekday(year, 1, 0, 3))
    h.add(_nth_weekday(year, 2, 0, 3))
    h.add(_easter(year) - timedelta(days=2))
    h.add(_last_weekday(year, 5, 0))
    if year >= 2022:
        h.add(_observed(date(year, 6, 19)))
    h.add(_observed(date(year, 7, 4)))
    h.add(_nth_weekday(year, 9, 0, 1))
    h.add(_nth_weekday(year, 11, 3, 4))
    h.add(_observed(date(year, 12, 25)))
    return h


def is_market_holiday(d=None):
    if d is None:
        d = date.today()
    return d in nyse_holidays(d.year)


def get_trading_days(from_date, to_date):
    days    = []
    current = datetime.strptime(from_date, "%Y-%m-%d").date()
    end     = datetime.strptime(to_date,   "%Y-%m-%d").date()
    while current <= end:
        if current.weekday() < 5 and not is_market_holiday(current):
            days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


# =========================
# UNIVERSE (read-only — same files scanner_tiingo.py maintains)
# =========================

def get_sp500():
    path = os.path.join(DATA_DIR, "sp500_symbols.txt")
    with open(path) as f:
        return [t.strip().replace(".", "-") for t in f.read().splitlines() if t.strip()]


def get_nasdaq100():
    path = os.path.join(DATA_DIR, "nasdaq100_symbols.txt")
    with open(path) as f:
        return [t.strip().replace(".", "-") for t in f.read().splitlines() if t.strip()]


def get_tickers():
    sp500     = get_sp500()
    nasdaq100 = get_nasdaq100()
    clean   = [t.replace(".", "-") for t in sp500 + nasdaq100 if isinstance(t, str)]
    tickers = sorted(set(clean))
    sp_set  = {t.replace(".", "-") for t in sp500     if isinstance(t, str)}
    nd_set  = {t.replace(".", "-") for t in nasdaq100 if isinstance(t, str)}
    return tickers, sp_set, nd_set


# =========================
# SHARES-OUTSTANDING OVERRIDES (read-only reuse of split_guards.csv + the
# permanent overrides already documented in scanner_tiingo.py; EPS itself
# doesn't need re-adjusting here since fundamentals_cache.json already
# stores the post-split-guard EPS value written by scanner_tiingo.py)
# =========================

def _load_split_guards():
    if not os.path.exists(SPLIT_GUARDS_FILE):
        return []
    with open(SPLIT_GUARDS_FILE, newline="") as f:
        return list(csv.DictReader(f))


def _make_shares_lambda(direction, ratio, threshold):
    ratio = int(ratio)
    threshold = int(threshold)
    if direction == "forward":
        return lambda s: (s or 0) * ratio if (s or 0) < threshold else s
    else:
        return lambda s: (s or 0) // ratio if (s or 0) > threshold else s


_SPLIT_GUARDS = _load_split_guards()

SHARES_OUTSTANDING_OVERRIDE = {
    "IBKR": 1_697_000_000,
    "BX":   1_222_000_000,
    "DVN":  lambda s: 1_153_000_000 if (s or 0) < 800_000_000 else s,
    **{
        r["ticker"]: _make_shares_lambda(r["direction"], r["ratio"], r["shares_threshold"])
        for r in _SPLIT_GUARDS
        if r.get("shares_threshold")
    },
}


# =========================
# OHLCV CACHE (mirrors scanner_tiingo.py's data/ohlcv_tiingo_cache/ shape,
# separate directory — never touches the Tiingo cache)
# =========================

def _cache_path(ticker):
    return os.path.join(OHLCV_CACHE_DIR, f"{ticker}.json")


def _load_ticker_bars(ticker):
    path = _cache_path(ticker)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("bars", {})
    except Exception:
        return {}


def _save_ticker_bars(ticker, bars):
    path = _cache_path(ticker)
    with open(path, "w") as f:
        json.dump({"ticker": ticker, "updated": DATE_STR, "bars": bars}, f)


def _trim_old_bars(bars, cutoff_date_str):
    return {d: v for d, v in bars.items() if d >= cutoff_date_str}


def fetch_yfinance_bulk(tickers, period="2y"):
    """
    Fetch daily OHLCV for all tickers via yfinance, chunked with retry/backoff
    (Yahoo throttles high-volume scraping). auto_adjust=True means yfinance
    handles split/dividend adjustment itself — no split-detection needed here.
    Returns {ticker: {date_str: {o,h,l,c,v}}}.
    """
    all_bars = {}
    chunks = [tickers[i:i + YF_CHUNK_SIZE] for i in range(0, len(tickers), YF_CHUNK_SIZE)]

    for ci, chunk in enumerate(chunks, 1):
        data = None
        for attempt in range(YF_MAX_RETRIES):
            try:
                data = yf.download(
                    tickers=chunk, period=period, group_by="ticker",
                    auto_adjust=True, threads=False, progress=False,
                )
                break
            except Exception as e:
                wait = YF_RETRY_WAITS[min(attempt, len(YF_RETRY_WAITS) - 1)]
                print(f"  chunk {ci}/{len(chunks)} attempt {attempt+1} failed: {e}; retrying in {wait}s")
                time.sleep(wait)

        if data is None or data.empty:
            print(f"  chunk {ci}/{len(chunks)} failed after {YF_MAX_RETRIES} attempts — skipping {len(chunk)} tickers")
            time.sleep(YF_CHUNK_DELAY)
            continue

        is_multi = isinstance(data.columns, pd.MultiIndex)
        for ticker in chunk:
            try:
                if is_multi:
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    sub = data[ticker]
                else:
                    sub = data
                sub = sub.dropna(subset=["Close"])
                if sub.empty:
                    continue
                bars = {}
                idx = sub.index
                if getattr(idx, "tz", None) is not None:
                    idx = idx.tz_localize(None)
                for ts, row in zip(idx, sub.itertuples(index=False)):
                    d = ts.strftime("%Y-%m-%d")
                    close = getattr(row, "Close", None)
                    if close is None or pd.isna(close):
                        continue
                    bars[d] = {
                        "o": round(float(row.Open), 4) if pd.notna(getattr(row, "Open", None)) else None,
                        "h": round(float(row.High), 4) if pd.notna(getattr(row, "High", None)) else None,
                        "l": round(float(row.Low),  4) if pd.notna(getattr(row, "Low",  None)) else None,
                        "c": round(float(close), 4),
                        "v": int(row.Volume) if pd.notna(getattr(row, "Volume", None)) else 0,
                    }
                if bars:
                    all_bars[ticker] = bars
            except Exception as e:
                print(f"  {ticker}: parse error {e}")

        print(f"  chunk {ci}/{len(chunks)} done ({len(chunk)} tickers)")
        time.sleep(YF_CHUNK_DELAY)

    return all_bars


def build_ohlcv_cache(tickers, from_date, period="2y"):
    """Fetch fresh history for all tickers via yfinance, save to disk cache.
    Tickers whose fetch failed keep whatever was already on disk (if anything)."""
    cutoff_str = from_date
    print(f"Fetching {len(tickers)} tickers via yfinance (period={period}) …")
    fetched = fetch_yfinance_bulk(tickers, period=period)
    updated = 0
    for ticker in tickers:
        bars = fetched.get(ticker)
        if not bars:
            continue
        bars = _trim_old_bars(bars, cutoff_str)
        _save_ticker_bars(ticker, bars)
        updated += 1
    print(f"OHLCV cache updated: {updated}/{len(tickers)} tickers.")


def load_ohlcv_cache_into_memory(tickers, trading_days):
    daily_data = {d: {} for d in trading_days}
    for ticker in tickers:
        bars = _load_ticker_bars(ticker)
        for d, bar in bars.items():
            if d in daily_data:
                daily_data[d][ticker] = bar
    return daily_data


def load_ticker_ohlcv(ticker, trading_days, daily_data):
    rows = []
    for day in trading_days:
        bar = daily_data.get(day, {}).get(ticker)
        if bar:
            rows.append({
                "Date":   day,
                "Open":   bar.get("o"),
                "High":   bar.get("h"),
                "Low":    bar.get("l"),
                "Close":  bar["c"],
                "Volume": bar["v"],
            })
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").reset_index(drop=True)


# =========================
# SPY BENCHMARK (via yfinance)
# =========================

def fetch_benchmark_bars(from_date, to_date):
    try:
        hist = yf.Ticker("SPY").history(start=from_date, end=to_date, auto_adjust=True)
        if hist is None or hist.empty:
            return None
        hist = hist.reset_index()
        hist["Date"] = pd.to_datetime(hist["Date"])
        if hist["Date"].dt.tz is not None:
            hist["Date"] = hist["Date"].dt.tz_localize(None)
        return hist[["Date", "Close"]].sort_values("Date").reset_index(drop=True)
    except Exception as e:
        print(f"SPY fetch failed: {e}")
        return None


# =========================
# FUNDAMENTALS — read-only from data/fundamentals_cache.json
# (EDGAR-sourced, written daily by the normal scanner_tiingo.py pipeline;
# not re-fetched here — see module docstring for the known limitation)
# =========================

_fund_cache = {}
_fund_cache_fetched_date = ""

_EMPTY_FUND = {
    "SharesOutstanding": None, "EPS": None, "Sector": "",
    "CompanyName": "", "TiingoMarketCap": None,
}


def load_fundamentals_cache():
    global _fund_cache, _fund_cache_fetched_date
    if not os.path.exists(FUND_CACHE_FILE):
        print("WARNING: data/fundamentals_cache.json not found — fundamentals will be empty for all tickers")
        return
    with open(FUND_CACHE_FILE) as f:
        data = json.load(f)
    _fund_cache = data.get("tickers", {})
    _fund_cache_fetched_date = data.get("fetched", "")
    age_days = "?"
    try:
        age_days = (date.today() - datetime.strptime(_fund_cache_fetched_date, "%Y-%m-%d").date()).days
    except Exception:
        pass
    print(f"Fundamentals: {len(_fund_cache)} tickers from cache (fetched {_fund_cache_fetched_date}, {age_days}d old)")


def get_fundamentals(ticker):
    return _fund_cache.get(ticker, _EMPTY_FUND)


# =========================
# MULTI-PERIOD METRICS (copied verbatim — pure pandas math, source-agnostic)
# =========================

def calculate_period_metrics(df, label, days):
    recent = df.iloc[-days:].copy().reset_index(drop=True)
    start_price = recent["Close"].iloc[0]
    end_price   = recent["Close"].iloc[-1]

    period_price_change = (
        (end_price - start_price) / start_price
        if start_price not in [0, None] and not pd.isna(start_price)
        else None
    )

    recent["price_change"]  = recent["Close"].pct_change()
    recent["volume_change"] = recent["Volume"].pct_change()
    recent["price_change"]  = recent["price_change"].replace([np.inf, -np.inf], np.nan)
    recent["volume_change"] = recent["volume_change"].replace([np.inf, -np.inf], np.nan)

    if recent["price_change"].dropna().empty or recent["volume_change"].dropna().empty:
        return {}

    max_price_idx = recent["price_change"].idxmax()
    max_vol_idx   = recent["volume_change"].idxmax()

    max_price_val    = recent["price_change"].iloc[max_price_idx]
    max_vol_val      = recent["volume_change"].iloc[max_vol_idx]
    price_at_max_vol = recent["price_change"].iloc[max_vol_idx]
    vol_at_max_price = recent["volume_change"].iloc[max_price_idx]

    n          = len(recent)
    price_day  = n - 1 - max_price_idx
    volume_day = n - 1 - max_vol_idx

    return {
        f"{label}PriceChange":            round(period_price_change * 100, 2) if period_price_change is not None else None,
        f"{label}MaxPriceChange":         round(max_price_val * 100, 2),
        f"{label}MaxVolumeChange":        round(max_vol_val * 100, 2),
        f"{label}MaxPriceChangeDay":      price_day,
        f"{label}MaxVolumeChangeDay":     volume_day,
        f"{label}PriceChangeAtMaxVolume": round(price_at_max_vol * 100, 2),
        f"{label}VolumeChangeAtMaxPrice": round(vol_at_max_price * 100, 2),
    }


# =========================
# SCAN
# =========================

def scan():
    tickers, sp_set, nd_set = get_tickers()
    results             = []
    sector_mktcap_sum   = {}
    sector_earnings_sum = {}

    print(f"Total tickers: {len(tickers)}")

    to_date   = DATE_STR
    from_date = (datetime.now(pytz.timezone('America/New_York')) - timedelta(days=730)).strftime("%Y-%m-%d")

    build_ohlcv_cache(tickers, from_date)
    load_fundamentals_cache()

    trading_days = get_trading_days(from_date, to_date)
    print("Loading OHLCV cache into memory …")
    daily_data = load_ohlcv_cache_into_memory(tickers, trading_days)
    print(f"Loaded {len(daily_data)} days. Processing {len(tickers)} tickers …")

    spy_returns = None
    try:
        spy_df = fetch_benchmark_bars(from_date, to_date)
        if spy_df is not None and len(spy_df) >= 60:
            spy_returns = spy_df["Close"].pct_change().dropna()
            print(f"SPY loaded: {len(spy_returns)} returns for beta")
        else:
            print("SPY fetch returned no data — beta will be None")
    except Exception as e:
        print(f"SPY fetch failed ({e}) — beta will be None")

    for i, ticker in enumerate(tickers, 1):
        try:
            df = load_ticker_ohlcv(ticker, trading_days, daily_data)
            if df is None or df.empty:
                continue

            df = df[(df["Volume"] >= 10000) & (df["Close"] > 0)]
            if len(df) < 2:
                continue

            df["MA21_PRICE"] = df["Close"].rolling(21).mean()
            df["MA21_VOL"]   = df["Volume"].rolling(21).mean()

            latest = df.iloc[-1]
            prev   = df.iloc[-2]

            latest_volume_m = round(latest["Volume"] / 1_000_000, 2)

            has_ma = (
                len(df) >= 21 and
                pd.notna(latest["MA21_PRICE"]) and
                pd.notna(latest["MA21_VOL"])
            )

            price_change_1d = (
                (latest["Close"] - prev["Close"]) / prev["Close"]
                if prev["Close"] not in [0, None] and not pd.isna(prev["Close"]) else None
            )
            volume_change_1d = (
                (latest["Volume"] - prev["Volume"]) / prev["Volume"]
                if prev["Volume"] not in [0, None] and not pd.isna(prev["Volume"]) else None
            )

            if has_ma:
                price_vs_ma21_1d  = latest["Close"]  / latest["MA21_PRICE"]
                volume_vs_ma21_1d = latest["Volume"] / latest["MA21_VOL"]
            else:
                price_vs_ma21_1d  = np.nan
                volume_vs_ma21_1d = np.nan

            metrics = {}
            for label, days in TIMEFRAMES.items():
                metrics.update(calculate_period_metrics(df, label, days))

            fund   = get_fundamentals(ticker)
            sector = fund.get("Sector") or ""
            eps    = fund.get("EPS")

            shares = fund.get("SharesOutstanding")
            _ov = SHARES_OUTSTANDING_OVERRIDE.get(ticker)
            shares_for_cap = _ov(shares) if callable(_ov) else (_ov if _ov is not None else shares)

            if ticker == "BRK-B" and fund.get("TiingoMarketCap"):
                market_cap = float(fund["TiingoMarketCap"])
            else:
                market_cap = shares_for_cap * float(latest["Close"]) if shares_for_cap else None

            pe = round(float(latest["Close"]) / eps, 2) if eps and eps > 0 else None

            if sector and pe and market_cap and market_cap > 0:
                sector_mktcap_sum.setdefault(sector, 0.0)
                sector_earnings_sum.setdefault(sector, 0.0)
                sector_mktcap_sum[sector]   += market_cap
                sector_earnings_sum[sector] += market_cap / pe

            in_sp500     = ticker in sp_set
            in_nasdaq100 = ticker in nd_set

            try:
                close_series = df["Close"].dropna()

                def normalize(series):
                    min_v, max_v = series.min(), series.max()
                    if max_v == min_v:
                        return [0.5] * len(series)
                    return ((series - min_v) / (max_v - min_v)).tolist()

                spark_1y = normalize(close_series.tail(252))
            except Exception:
                spark_1y = None

            beta    = None
            vol_30d = None
            try:
                stock_ret = df["Close"].pct_change().dropna()
                if len(stock_ret) >= 20:
                    vol_30d = round(float(stock_ret.iloc[-30:].std() * np.sqrt(252)), 4)
                if spy_returns is not None and len(stock_ret) >= 60:
                    n   = min(252, len(stock_ret), len(spy_returns))
                    s   = stock_ret.iloc[-n:].values
                    m   = spy_returns.iloc[-n:].values
                    cov = np.cov(s, m)
                    if cov[1, 1] != 0:
                        beta = round(cov[0, 1] / cov[1, 1], 3)
            except Exception:
                pass

            pc_2w = metrics.get("2WPriceChange")  or 0.0
            pc_1m = metrics.get("1MPriceChange")  or 0.0
            pc_3m = metrics.get("3MPriceChange")  or 0.0
            pc_6m = metrics.get("6MPriceChange")  or 0.0
            pc_9m = metrics.get("9MPriceChange")  or 0.0
            pc_1y = metrics.get("1YPriceChange")  or 0.0

            pv_ma     = float(price_vs_ma21_1d)  if pd.notna(price_vs_ma21_1d)  else 1.0
            vv_ma     = float(volume_vs_ma21_1d) if pd.notna(volume_vs_ma21_1d) else 1.0
            pc_1d_pct = float(price_change_1d * 100) if price_change_1d is not None else 0.0

            bs  = min(33, max(0, (pv_ma - 1) * 200))
            bs += min(33, max(0, pc_1d_pct * 3))
            bs += min(34, max(0, (vv_ma - 1) * 25))
            breakout_score = round(min(100, max(0, bs)))

            p_dir = 1 if pc_1d_pct > 0 else (-1 if pc_1d_pct < 0 else 0)
            vol_pressure_score = round(max(-100, min(100, (vv_ma - 1) * p_dir * 100)))

            trend_score = round(
                sum(1 for v in [pc_2w, pc_1m, pc_3m, pc_6m, pc_9m, pc_1y] if v > 0) / 6 * 100
            )

            raw_rs       = 0.40*pc_3m + 0.20*pc_6m + 0.20*pc_9m + 0.20*pc_1y
            raw_momentum = 0.35*pc_1m + 0.25*pc_3m + 0.20*pc_6m + 0.20*pc_1y

            actual_date = df["Date"].iloc[-1].strftime("%Y-%m-%d")
            results.append({
                "Date":   actual_date,
                "Ticker": ticker,

                "InSP500":     in_sp500,
                "InNASDAQ100": in_nasdaq100,

                "Price":   round(float(latest["Close"]), 2),
                "VolumeM": latest_volume_m,

                "PriceChange1D":  round(price_change_1d  * 100, 2) if price_change_1d  is not None else None,
                "VolumeChange1D": round(volume_change_1d * 100, 2) if volume_change_1d is not None else None,

                "PriceVsMA21_1D":  round(price_vs_ma21_1d,  3) if pd.notna(price_vs_ma21_1d)  else None,
                "VolumeVsMA21_1D": round(volume_vs_ma21_1d, 3) if pd.notna(volume_vs_ma21_1d) else None,

                **metrics,

                "PE":            pe,
                "MarketCap":     market_cap,
                "EPS":           eps,
                "Sector":        sector,
                "Beta":          beta,
                "Volatility30D": vol_30d,
                "CompanyName":   fund.get("CompanyName") or "",
                "Spark6M":       None,
                "Spark1Y":       spark_1y,

                "BreakoutScore":    breakout_score,
                "VolPressureScore": vol_pressure_score,
                "TrendScore":       trend_score,
                "_RawRS":           raw_rs,
                "_RawMomentum":     raw_momentum,
            })

        except Exception as e:
            print(f"{ticker} error: {e}")
            continue

        if i % 50 == 0:
            print(f"  … processed {i}/{len(tickers)}")

    sector_avg_pe = {
        s: sector_mktcap_sum[s] / sector_earnings_sum[s]
        for s in sector_mktcap_sum
        if sector_earnings_sum.get(s, 0) > 0
    }

    df = pd.DataFrame(results)
    if df.empty:
        print("No results generated — universe or data issue")
        return df

    df["MarketCap"] = df["MarketCap"].apply(
        lambda x: round(float(x) / 1_000_000_000, 2)
        if x is not None and pd.notna(x) else None
    )

    df["SectorAvgPE"] = df["Sector"].map(sector_avg_pe)
    df["SectorAvgPE"] = pd.to_numeric(df["SectorAvgPE"], errors="coerce").round(2)

    df["PE_vs_Sector"] = np.where(
        df["PE"].notna() & df["SectorAvgPE"].notna() & (df["SectorAvgPE"] != 0),
        (df["PE"] - df["SectorAvgPE"]) / df["SectorAvgPE"] * 100,
        np.nan,
    )
    df["PE_vs_Sector"] = df["PE_vs_Sector"].round(1)

    if "_RawRS" in df.columns:
        df["RSScore"] = (df["_RawRS"].rank(pct=True) * 98 + 1).round().clip(1, 99).astype(int)
        df.drop(columns=["_RawRS"], inplace=True)

    if "_RawMomentum" in df.columns:
        df["MomentumScore"] = (df["_RawMomentum"].rank(pct=True) * 100).round().clip(0, 100).astype(int)
        df.drop(columns=["_RawMomentum"], inplace=True)

    score_cols = ["RSScore", "MomentumScore", "BreakoutScore", "TrendScore", "VolPressureScore"]
    if all(c in df.columns for c in score_cols):
        rs_norm = (df["RSScore"] - 1) / 98 * 100
        vp_norm = (df["VolPressureScore"] + 100) / 2
        df["BaizScore"] = (
            0.30 * rs_norm +
            0.25 * df["MomentumScore"] +
            0.20 * df["BreakoutScore"] +
            0.15 * df["TrendScore"] +
            0.10 * vp_norm
        ).round().clip(0, 100).astype(int)

        vp_turn = ((df["VolPressureScore"] + 100) / 200).clip(lower=0)
        df["TurnScore"] = (
            df["BreakoutScore"] * (1 - df["RSScore"] / 100) * vp_turn
        ).round().clip(0, 100).astype(int)

    if "VolumeChange1D" in df.columns:
        df = df.sort_values("VolumeChange1D", ascending=False)

    return df


# =========================
# EXPORT
# =========================

def export(df):
    df = df.replace({np.nan: None, np.inf: None, -np.inf: None})
    market_date = df["Date"].iloc[0] if len(df) and "Date" in df.columns else DATE_STR

    payload = {
        "date":   market_date,
        "status": "Updated",
        "count":  len(df),
        "partialUpdate": False,   # v1: no per-ticker staleness detection — see module docstring
        "staleTickers":  [],
        "data":   df.to_dict(orient="records"),
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    print(f"Export complete: {len(df)} tickers -> {OUTPUT_JSON}")


if __name__ == "__main__":
    print(f"=== scanner_yfinance.py — emergency backup scan, {DATE_STR} ===")
    result_df = scan()
    if result_df.empty:
        print("Scan produced no data — not writing output.")
    else:
        export(result_df)
    print("Done")
