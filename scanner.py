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

# 0 = local
# 1 = cloud
RUN_IN_CLOUD = 1

DATE_STR = datetime.now().strftime("%Y-%m-%d")


# =========================
# ENV SWITCHING
# =========================
if RUN_IN_CLOUD:

    # CLOUD VERSION
    DATA_DIR = "data"
    ARCHIVE_DIR = "archive"

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    OUTPUT_JSON = os.path.join(DATA_DIR, "latest.json")
    OUTPUT_CSV = os.path.join(ARCHIVE_DIR, f"results_{DATE_STR}.csv")

    API_KEY = os.getenv("API_KEY")

    # SAFETY CHECK
    if not API_KEY:
        raise ValueError("API_KEY environment variable not found")

else:

    # LOCAL VERSION
    DATA_DIR = "data"
    ARCHIVE_DIR = "archive"

    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    OUTPUT_JSON = os.path.join(DATA_DIR, "latest.json")
    OUTPUT_CSV = os.path.join(ARCHIVE_DIR, f"results_{DATE_STR}.csv")

    # local hardcoded key
    API_KEY = "YOUR_LOCAL_FMP_API_KEY_HERE"

# =========================
# UNIVERSE
# =========================
def get_universes():
    sp_url = f"https://financialmodelingprep.com/stable/sp500-constituent?apikey={API_KEY}"
    nd_url = f"https://financialmodelingprep.com/stable/nasdaq-constituent?apikey={API_KEY}"

    try:
        sp = requests.get(sp_url, timeout=10).json()
        nd = requests.get(nd_url, timeout=10).json()

        sp_set = set(x["symbol"] for x in sp if "symbol" in x)
        nd_set = set(x["symbol"] for x in nd if "symbol" in x)

        return sp_set, nd_set

    except Exception as e:
        print("Universe fetch error:", e)
        return set(), set()


def get_tickers():
    sp_set, nd_set = get_universes()
    return list(sp_set.union(nd_set)), sp_set, nd_set


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

def calculate_period_metrics(df, days):

    recent = df.tail(days).copy().reset_index(drop=True)

    # =========================
    # DAILY SIGNALS
    # =========================
    recent["price_change"] = recent["Close"].pct_change()
    recent["volume_change"] = recent["Volume"].pct_change()

    # =========================
    # HANDLE EDGE CASES
    # =========================
    if recent["price_change"].dropna().empty or recent["volume_change"].dropna().empty:
        return {}

    # =========================
    # MAX INDICES
    # =========================
    max_price_idx = recent["price_change"].idxmax()
    max_vol_idx = recent["volume_change"].idxmax()

    max_price_val = recent["price_change"].iloc[max_price_idx]
    max_vol_val = recent["volume_change"].iloc[max_vol_idx]

    # =========================
    # CROSS VALUES
    # =========================
    price_at_max_vol = recent["price_change"].iloc[max_vol_idx]
    vol_at_max_price = recent["volume_change"].iloc[max_price_idx]

    # =========================
    # CONVERT INDEX → "DAYS AGO"
    # =========================
    price_day = (days - 1 - max_price_idx)
    volume_day = (days - 1 - max_vol_idx)

    return {

        # =========================
        # CORE METRICS
        # =========================
        f"Max{days}DPriceChange": round(max_price_val * 100, 2),
        f"Max{days}DVolumeChange": round(max_vol_val * 100, 2),

        # =========================
        # WHEN THEY HAPPENED
        # =========================
        f"Max{days}DPriceChangeDay": price_day,
        f"Max{days}DVolumeChangeDay": volume_day,

        # =========================
        # CROSS BEHAVIOR
        # =========================
        f"Max{days}DPriceChangeAtMaxVolume": round(price_at_max_vol * 100, 2),
        f"Max{days}DVolumeChangeAtMaxPrice": round(vol_at_max_price * 100, 2),
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

    # Different batch size for cloud/local
    if RUN_IN_CLOUD:
        batch_size = 50
        sleep_time = 0.15
    else:
        batch_size = 100
        sleep_time = 0.05


    for i in range(0, len(tickers), batch_size):

        batch = tickers[i:i+batch_size]

        try:
            data = yf.download(
                batch,
                period="6mo",
                group_by="ticker",
                progress=False,
                threads=True
            )

            for ticker in batch:

                try:
                    if ticker not in data:
                        continue

                    df = data[ticker][["Close", "Volume"]].dropna()

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
                        pd.notna(latest["MA21_VOL"]) and latest["MA21_VOL"] > 0 and
                        pd.notna(latest["MA21_PRICE"]) and latest["MA21_PRICE"] > 0
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
                    metrics_5d = calculate_period_metrics(df, 5)

                    metrics_7d = calculate_period_metrics(df, 7)

                    metrics_10d = calculate_period_metrics(df, 10)

                    metrics_15d = calculate_period_metrics(df, 15)

                    metrics_20d = calculate_period_metrics(df, 20)

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

                        "PriceChange1D": round(price_change_1d * 100, 2),
                        "VolumeChange1D": round(volume_change_1d * 100, 2),

                        "PriceVsMA21_1D": round(price_vs_ma21_1d, 3),
                        "VolumeVsMA21_1D": round(volume_vs_ma21_1d, 3),

                        # "Max7DPriceChange": round(max_7d_price_change * 100, 2),
                        # "Max7DVolumeChange": round(max_7d_volume_change * 100, 2),

                        # "Max7DPriceVsMA21": round(max_7d_price_vs_ma21, 3),
                        # "Max7DVolumeVsMA21": round(max_7d_vol_vs_ma21, 3),

                        # =========================
                        # 5D
                        # =========================
                        **metrics_5d,

                        # =========================
                        # 7D
                        # =========================
                        **metrics_7d,

                        # =========================
                        # 10D
                        # =========================
                        **metrics_10d,

                        # =========================
                        # 15D
                        # =========================
                        **metrics_15d,

                        # =========================
                        # 20D
                        # =========================
                        **metrics_20d,

                        # =========================
                        # FUNDAMENTALS FOR HOVER
                        # =========================
                        "PE": fund["PE"],
                        "MarketCap": fund["MarketCap"],
                        "EPS": fund["EPS"],
                        "Sector": fund["Sector"],
                        "Volatility30D": fund["Volatility30D"],
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
    df["MarketCap"] = df["MarketCap"].apply(
        lambda x: round(x / 1_000_000_000, 2) if pd.notna(x) else None
    )

    df["SectorAvgPE"] = df["Sector"].map(sector_avg_pe)
    df["SectorAvgPE"] = df["SectorAvgPE"].round(2)

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

    df = df.replace({np.nan: None})  # IMPORTANT for JSON frontend

    df.to_csv(OUTPUT_CSV, index=False)

    payload = {
        "date": DATE_STR,
        "status": "Updated",
        "count": len(df),
        "data": df.to_dict(orient="records")
    }
    
    with open(OUTPUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    print("✅ Export complete:", len(df))

# =========================
# MAIN
# =========================
if __name__ == "__main__":

    if RUN_IN_CLOUD:
        print("☁️ Running CLOUD scanner...")
    else:
        print("💻 Running LOCAL scanner...")

    df = scan()

    print(df.head(10))

    export(df)

    print("✅ Done")