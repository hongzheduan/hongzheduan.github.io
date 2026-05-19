import pandas as pd
import yfinance as yf
import numpy as np
import time
import json
import os
import requests
from datetime import datetime

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

# =========================
# UNIVERSE (FIXED - NO FMP)
# =========================

# def get_sp500():
#     url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
#     df = pd.read_csv(url)
#     return df["Symbol"].tolist()


def get_sp500():
    path = os.path.join("data", "sp500_symbols.txt")

    with open(path, "r") as f:
        tickers = f.read().splitlines()

    # clean + remove empty lines
    tickers = [t.strip().replace(".", "-") for t in tickers if t.strip()]

    return tickers

def get_nasdaq100():
    path = os.path.join("data", "nasdaq100_symbols.txt")

    with open(path, "r") as f:
        tickers = f.read().splitlines()

    # clean + remove empty lines
    tickers = [t.strip().replace(".", "-") for t in tickers if t.strip()]

    return tickers

def get_tickers():
    sp500 = get_sp500()
    nasdaq100 = get_nasdaq100()

    # FIX: remove NaN / non-string values
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
            "Volatility30D": info.get("beta")
        }

    except Exception:
        result = {
            "PE": None,
            "MarketCap": None,
            "EPS": None,
            "Sector": None,
            "Volatility30D": None
        }

    _fund_cache[ticker] = result
    return result

# =========================
# MULTI-PERIOD METRICS
# =========================

def calculate_period_metrics(df, label, days):

    # recent = df.tail(days).copy().reset_index(drop=True)
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
                # period="6mo",
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

                    latest_volume_m = round(latest["Volume"] / 1_000_000,2)
                    # last_7d = df.tail(7).copy()

                    # if latest["Close"] < 1:
                    #     continue

                    # if pd.isna(latest["MA21_VOL"]) or latest["MA21_VOL"] < 500000:
                    #     continue

                    # if pd.isna(latest["MA21_PRICE"]) or latest["MA21_PRICE"] == 0:
                    #     continue

                    has_ma = (
                        len(df) >= 21 and
                        pd.notna(latest["MA21_PRICE"]) and
                        pd.notna(latest["MA21_VOL"])
                    )

                    # =========================
                    # 1D
                    # =========================
                    # price_change_1d = (latest["Close"] - prev["Close"]) / prev["Close"]
                    # volume_change_1d = (latest["Volume"] - prev["Volume"]) / prev["Volume"]

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
                    # 7D
                    # =========================
                    # last_7d["price_change"] = last_7d["Close"].pct_change()
                    # last_7d["volume_change"] = last_7d["Volume"].pct_change()

                    # max_7d_price_change = last_7d["price_change"].max()
                    # max_7d_volume_change = last_7d["volume_change"].max()

                    # last_7d["price_vs_ma21"] = last_7d["Close"] / last_7d["MA21_PRICE"]
                    # last_7d["vol_vs_ma21"] = last_7d["Volume"] / last_7d["MA21_VOL"]

                    # max_7d_price_vs_ma21 = last_7d["price_vs_ma21"].max()
                    # max_7d_vol_vs_ma21 = last_7d["vol_vs_ma21"].max()

                    # =========================
                    # MULTI-DAY WINDOWS
                    # =========================
                    # metrics_5d = calculate_period_metrics(df, 5)

                    # metrics_7d = calculate_period_metrics(df, 7)

                    # metrics_10d = calculate_period_metrics(df, 10)

                    # metrics_15d = calculate_period_metrics(df, 15)

                    # metrics_20d = calculate_period_metrics(df, 20)

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
                    # SVG / FRONTEND PREP (NO IMPACT ON LOGIC)
                    # =========================

                    try:
                        close_series = df["Close"].dropna()

                        # Normalize helper (0–1 scale for SVG)
                        def normalize(series):
                            min_v = series.min()
                            max_v = series.max()
                            if max_v == min_v:
                                return [0.5] * len(series)
                            return ((series - min_v) / (max_v - min_v)).tolist()

                        # 6M placeholder (future expansion, safe fallback if data missing)
                        spark_6m = None

                        # 1Y sparkline (main UI)
                        spark_1y = normalize(close_series.tail(252))

                    except Exception:
                        spark_6m = None
                        spark_1y = None



                    # =========================
                    # OUTPUT (NO BREAKING CHANGE)
                    # =========================
                    results.append({
                        "Date": DATE_STR,
                        "Ticker": ticker,

                        "InSP500": in_sp500,
                        "InNASDAQ100": in_nasdaq100,

                        "Price": round(float(latest["Close"]), 2),
                        "VolumeM": latest_volume_m,

                        # =========================
                        # 1D
                        # =========================

                        # "PriceChange1D": round(price_change_1d * 100, 2),
                        # "VolumeChange1D": round(volume_change_1d * 100, 2),

                        "PriceChange1D": round(price_change_1d * 100, 2) if price_change_1d is not None else None,
                        "VolumeChange1D": round(volume_change_1d * 100, 2) if volume_change_1d is not None else None,

                        "PriceVsMA21_1D": round(price_vs_ma21_1d, 3),
                        "VolumeVsMA21_1D": round(volume_vs_ma21_1d, 3),

                        **metrics,

                        # =========================
                        # FUNDAMENTALS FOR HOVER
                        # =========================
                        "PE": fund["PE"],
                        "MarketCap": fund["MarketCap"],
                        "EPS": fund["EPS"],
                        "Sector": fund["Sector"],
                        "Volatility30D": fund["Volatility30D"],
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

        df["PE"] / df["SectorAvgPE"],
        np.nan
    )
    df["PE_vs_Sector"] = df["PE_vs_Sector"].round(2)

    if "VolumeChange1D" in df.columns:
        df = df.sort_values("VolumeChange1D", ascending=False)

    return df


# =========================
# EXPORT
# =========================
def export(df):

    df = df.replace({np.nan: None, np.inf: None, -np.inf: None})  # IMPORTANT for JSON frontend

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

    df = scan()

    print(df.head(10))

    export(df)

    print("Done")