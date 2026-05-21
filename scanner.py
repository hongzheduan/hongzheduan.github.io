import pandas as pd
import yfinance as yf
import numpy as np
import time
import json
import os
import glob
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# =========================
# CONFIG
# =========================

DATE_STR = datetime.now().strftime("%Y-%m-%d")

DATA_DIR = "data"
ARCHIVE_DIR = "archive"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

# 🔥 TIMEFRAME DEFINITIONS (CORE ENGINE PARAMETER)
TIMEFRAMES = {
    "2W": 10,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "9M": 189,
    "1Y": 252
}

OUTPUT_JSON = os.path.join(DATA_DIR, "latest.json")
OUTPUT_CSV = os.path.join(ARCHIVE_DIR, f"results_{DATE_STR}.csv")

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# =========================
# INDEX LIST MANAGEMENT
# =========================

def fetch_index_tickers(url):
    """Scrape ticker symbols from a slickcharts index page."""
    try:
        response = requests.get(url, headers=SCRAPE_HEADERS, timeout=30)
        if response.status_code != 200:
            print(f"Failed to fetch {url}: HTTP {response.status_code}")
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table")
        if not table:
            print(f"No table found at {url}")
            return []
        symbols = []
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) > 2:
                symbol = cols[2].text.strip()
                if symbol:
                    symbols.append(symbol)
        return symbols
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []


def update_and_detect_changes():
    """
    Fetch fresh S&P 500 + Nasdaq-100 lists, compare with previous,
    save updated lists to files, and return any membership changes.
    Returns: (new_sp500_list, new_nasdaq100_list, changes_entry_or_None)
    """
    sp500_path = os.path.join(DATA_DIR, "sp500_symbols.txt")
    nasdaq100_path = os.path.join(DATA_DIR, "nasdaq100_symbols.txt")

    # Read previous lists before overwriting
    old_sp500 = set()
    old_nasdaq100 = set()
    if os.path.exists(sp500_path):
        with open(sp500_path) as f:
            old_sp500 = {line.strip() for line in f if line.strip()}
    if os.path.exists(nasdaq100_path):
        with open(nasdaq100_path) as f:
            old_nasdaq100 = {line.strip() for line in f if line.strip()}

    # Fetch fresh lists from web
    new_sp500_raw = fetch_index_tickers("https://www.slickcharts.com/sp500")
    new_nasdaq100_raw = fetch_index_tickers("https://www.slickcharts.com/nasdaq100")

    if not new_sp500_raw:
        print("Warning: could not fetch S&P 500 from web, using cached list")
        new_sp500_raw = sorted(old_sp500)
    if not new_nasdaq100_raw:
        print("Warning: could not fetch Nasdaq-100 from web, using cached list")
        new_nasdaq100_raw = sorted(old_nasdaq100)

    new_sp500 = set(new_sp500_raw)
    new_nasdaq100 = set(new_nasdaq100_raw)

    # Save updated lists
    with open(sp500_path, "w") as f:
        for s in sorted(new_sp500_raw):
            f.write(s + "\n")
    with open(nasdaq100_path, "w") as f:
        for s in sorted(new_nasdaq100_raw):
            f.write(s + "\n")

    print(f"Index lists updated: {len(new_sp500)} S&P 500, {len(new_nasdaq100)} Nasdaq-100")

    # Skip change detection on first-ever run (no previous data)
    if not old_sp500 and not old_nasdaq100:
        return new_sp500_raw, new_nasdaq100_raw, None

    changes = {
        "date": DATE_STR,
        "sp500": {
            "added": sorted(new_sp500 - old_sp500),
            "removed": sorted(old_sp500 - new_sp500),
        },
        "nasdaq100": {
            "added": sorted(new_nasdaq100 - old_nasdaq100),
            "removed": sorted(old_nasdaq100 - new_nasdaq100),
        }
    }

    has_changes = (
        changes["sp500"]["added"] or changes["sp500"]["removed"] or
        changes["nasdaq100"]["added"] or changes["nasdaq100"]["removed"]
    )

    return new_sp500_raw, new_nasdaq100_raw, (changes if has_changes else None)


def load_update_index_changes(changes_entry):
    """
    Prepend changes_entry (if any) to index_changes.json.
    Keeps full history (no pruning). Stores trackedSince on first run.
    """
    path = os.path.join(DATA_DIR, "index_changes.json")

    existing = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    entries = existing.get("entries", [])
    tracked_since = existing.get("trackedSince", DATE_STR)

    if changes_entry is not None:
        entries.insert(0, changes_entry)
        print(f"Index change recorded: {changes_entry}")

    data = {"trackedSince": tracked_since, "lastChecked": DATE_STR, "entries": entries}

    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    return data


def cleanup_old_archives():
    """Delete archive CSVs older than 7 days."""
    cutoff = datetime.now() - timedelta(days=7)
    pattern = os.path.join(ARCHIVE_DIR, "results_*.csv")
    for filepath in glob.glob(pattern):
        fname = os.path.basename(filepath)
        try:
            date_str = fname.replace("results_", "").replace(".csv", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff:
                os.remove(filepath)
                print(f"Deleted old archive: {fname}")
        except Exception:
            pass

# =========================
# UNIVERSE
# =========================

def get_sp500():
    path = os.path.join(DATA_DIR, "sp500_symbols.txt")
    with open(path, "r") as f:
        tickers = f.read().splitlines()
    return [t.strip().replace(".", "-") for t in tickers if t.strip()]


def get_nasdaq100():
    path = os.path.join(DATA_DIR, "nasdaq100_symbols.txt")
    with open(path, "r") as f:
        tickers = f.read().splitlines()
    return [t.strip().replace(".", "-") for t in tickers if t.strip()]


def get_tickers():
    sp500 = get_sp500()
    nasdaq100 = get_nasdaq100()

    clean = []
    for t in sp500 + nasdaq100:
        if isinstance(t, str):
            clean.append(t.replace(".", "-"))

    tickers = sorted(set(clean))

    sp_set = set([t.replace(".", "-") for t in sp500 if isinstance(t, str)])
    nd_set = set([t.replace(".", "-") for t in nasdaq100 if isinstance(t, str)])

    return tickers, sp_set, nd_set


# =========================
# SAFE FUNDAMENTALS (KEY FIX)
# =========================
_fund_cache = {}

def get_fundamentals(ticker):
    """
    Safe + cached + fail-proof enrichment
    """
    if ticker in _fund_cache:
        return _fund_cache[ticker]

    try:
        info = yf.Ticker(ticker).get_info()

        result = {
            "PE": info.get("trailingPE"),
            "MarketCap": info.get("marketCap"),
            "EPS": info.get("trailingEps"),
            "Sector": info.get("sector"),
            "Volatility30D": info.get("beta"),
            "CompanyName": info.get("longName") or info.get("shortName"),
        }

    except Exception:
        result = {
            "PE": None,
            "MarketCap": None,
            "EPS": None,
            "Sector": None,
            "Volatility30D": None,
            "CompanyName": None,
        }

    _fund_cache[ticker] = result
    return result

# =========================
# MULTI-PERIOD METRICS
# =========================

def calculate_period_metrics(df, label, days):

    recent = df.iloc[-days:].copy().reset_index(drop=True)

    start_price = recent["Close"].iloc[0]
    end_price = recent["Close"].iloc[-1]

    period_price_change = (
        (end_price - start_price) / start_price
        if start_price not in [0, None] and not pd.isna(start_price)
        else None
)

    recent["price_change"] = recent["Close"].pct_change()
    recent["volume_change"] = recent["Volume"].pct_change()

    recent["price_change"] = recent["price_change"].replace([np.inf, -np.inf], np.nan)
    recent["volume_change"] = recent["volume_change"].replace([np.inf, -np.inf], np.nan)

    if recent["price_change"].dropna().empty or recent["volume_change"].dropna().empty:
        return {}

    max_price_idx = recent["price_change"].idxmax()
    max_vol_idx = recent["volume_change"].idxmax()

    max_price_val = recent["price_change"].iloc[max_price_idx]
    max_vol_val = recent["volume_change"].iloc[max_vol_idx]

    price_at_max_vol = recent["price_change"].iloc[max_vol_idx]
    vol_at_max_price = recent["volume_change"].iloc[max_price_idx]

    n = len(recent)
    price_day = (n - 1 - max_price_idx)
    volume_day = (n - 1 - max_vol_idx)

    return {
        f"{label}PriceChange": round(period_price_change * 100, 2) if period_price_change is not None else None,

        f"{label}MaxPriceChange": round(max_price_val * 100, 2),
        f"{label}MaxVolumeChange": round(max_vol_val * 100, 2),

        f"{label}MaxPriceChangeDay": price_day,
        f"{label}MaxVolumeChangeDay": volume_day,

        f"{label}PriceChangeAtMaxVolume": round(price_at_max_vol * 100, 2),
        f"{label}VolumeChangeAtMaxPrice": round(vol_at_max_price * 100, 2),
    }

# =========================
# SCAN
# =========================
def scan():

    tickers, sp_set, nd_set = get_tickers()
    results = []
    sector_pe_map = {}
    sector_counts = {}

    print(f"Total tickers: {len(tickers)}")

    batch_size = 50
    sleep_time = 0.15

    for i in range(0, len(tickers), batch_size):

        batch = tickers[i:i+batch_size]

        try:
            data = yf.download(
                batch,
                period="2y",
                group_by="ticker",
                progress=False,
                threads=True
            )

            for ticker in batch:

                try:
                    try:
                        df = data[ticker][["Close", "Volume"]].dropna()
                    except KeyError:
                        df = data[["Close", "Volume"]].dropna()

                    df = df[(df["Volume"] >= 10000) & (df["Close"] > 0)]

                    if len(df) < 30:
                        continue

                    # =========================
                    # BASE FEATURES
                    # =========================
                    df["MA21_PRICE"] = df["Close"].rolling(21).mean()
                    df["MA21_VOL"] = df["Volume"].rolling(21).mean()

                    latest = df.iloc[-1]
                    prev = df.iloc[-2]

                    latest_volume_m = round(latest["Volume"] / 1_000_000, 2)

                    has_ma = (
                        len(df) >= 21 and
                        pd.notna(latest["MA21_PRICE"]) and
                        pd.notna(latest["MA21_VOL"])
                    )

                    # =========================
                    # 1D
                    # =========================
                    price_change_1d = (
                        (latest["Close"] - prev["Close"]) / prev["Close"]
                        if prev["Close"] not in [0, None] and not pd.isna(prev["Close"]) else None
                    )

                    volume_change_1d = (
                        (latest["Volume"] - prev["Volume"]) / prev["Volume"]
                        if prev["Volume"] not in [0, None] and not pd.isna(prev["Volume"]) else None
                    )

                    if has_ma:
                        price_vs_ma21_1d = latest["Close"] / latest["MA21_PRICE"]
                        volume_vs_ma21_1d = latest["Volume"] / latest["MA21_VOL"]
                    else:
                        price_vs_ma21_1d = np.nan
                        volume_vs_ma21_1d = np.nan

                    # =========================
                    # MULTI-DAY WINDOWS
                    # =========================
                    metrics = {}
                    for label, days in TIMEFRAMES.items():
                        metrics.update(calculate_period_metrics(df, label, days))

                    # =========================
                    # FUNDAMENTALS (SAFE ADD)
                    # =========================
                    fund = get_fundamentals(ticker)

                    sector = fund["Sector"]
                    pe = fund["PE"]

                    if sector and pe:
                        sector_pe_map.setdefault(sector, 0)
                        sector_counts.setdefault(sector, 0)

                        sector_pe_map[sector] += pe
                        sector_counts[sector] += 1

                    # =========================
                    # FLAGS
                    # =========================
                    in_sp500 = ticker in sp_set
                    in_nasdaq100 = ticker in nd_set

                    # =========================
                    # SVG / FRONTEND PREP
                    # =========================
                    try:
                        close_series = df["Close"].dropna()

                        def normalize(series):
                            min_v = series.min()
                            max_v = series.max()
                            if max_v == min_v:
                                return [0.5] * len(series)
                            return ((series - min_v) / (max_v - min_v)).tolist()

                        spark_6m = None
                        spark_1y = normalize(close_series.tail(252))

                    except Exception:
                        spark_6m = None
                        spark_1y = None

                    # =========================
                    # OUTPUT
                    # =========================
                    results.append({
                        "Date": DATE_STR,
                        "Ticker": ticker,

                        "InSP500": in_sp500,
                        "InNASDAQ100": in_nasdaq100,

                        "Price": round(float(latest["Close"]), 2),
                        "VolumeM": latest_volume_m,

                        "PriceChange1D": round(price_change_1d * 100, 2) if price_change_1d is not None else None,
                        "VolumeChange1D": round(volume_change_1d * 100, 2) if volume_change_1d is not None else None,

                        "PriceVsMA21_1D": round(price_vs_ma21_1d, 3),
                        "VolumeVsMA21_1D": round(volume_vs_ma21_1d, 3),

                        **metrics,

                        "PE": fund["PE"],
                        "MarketCap": fund["MarketCap"],
                        "EPS": fund["EPS"],
                        "Sector": fund["Sector"],
                        "Volatility30D": fund["Volatility30D"],
                        "CompanyName": fund["CompanyName"],
                        "Spark6M": spark_6m,
                        "Spark1Y": spark_1y,
                    })

                except Exception as e:
                    print(f"{ticker} error:", e)
                    continue

        except Exception as e:
            print("Batch error:", e)

        time.sleep(sleep_time)

    sector_avg_pe = {
        s: sector_pe_map[s] / sector_counts[s]
        for s in sector_pe_map
        if sector_counts[s] > 0
    }

    df = pd.DataFrame(results)
    if df.empty:
        print("No results generated — universe or data issue")
        return df

    df["MarketCap"] = df["MarketCap"].apply(
        lambda x: round(float(x) / 1_000_000_000, 2)
        if x is not None and pd.notna(x)
        else None
    )

    df["SectorAvgPE"] = df["Sector"].map(sector_avg_pe)
    df["SectorAvgPE"] = pd.to_numeric(df["SectorAvgPE"], errors="coerce").round(2)

    df["PE_vs_Sector"] = np.where(
        (df["PE"].notna()) &
        (df["SectorAvgPE"].notna()) &
        (df["SectorAvgPE"] != 0),

        (df["PE"] - df["SectorAvgPE"]) / df["SectorAvgPE"] * 100,
        np.nan
    )
    df["PE_vs_Sector"] = df["PE_vs_Sector"].round(1)

    if "VolumeChange1D" in df.columns:
        df = df.sort_values("VolumeChange1D", ascending=False)

    return df


# =========================
# EXPORT
# =========================
def export(df):

    df = df.replace({np.nan: None, np.inf: None, -np.inf: None})

    df.to_csv(OUTPUT_CSV, index=False)

    payload = {
        "date": DATE_STR,
        "status": "Updated",
        "count": len(df),
        "data": df.to_dict(orient="records")
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    print("Export complete:", len(df))

# =========================
# MAIN
# =========================
if __name__ == "__main__":

    print("Running Baizora scanner...")

    # 1. Fetch fresh index lists and detect membership changes
    _, _, changes_entry = update_and_detect_changes()

    # 2. Update index_changes.json (append if changed, keep full history)
    load_update_index_changes(changes_entry)

    # 3. Delete archive CSVs older than 7 days
    cleanup_old_archives()

    # 4. Run scan (reads freshly-updated txt files)
    df = scan()

    print(df.head(10))

    # 5. Export results
    export(df)

    print("Done")
