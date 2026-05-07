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

OUTPUT_JSON = os.path.join(DATA_DIR, "latest.json")
OUTPUT_CSV = os.path.join(ARCHIVE_DIR, f"results_{DATE_STR}.csv")

API_KEY = os.getenv("API_KEY")

# SAFETY CHECK
if not API_KEY:
    raise ValueError("API_KEY environment variable not found")

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
# SCAN
# =========================
def scan():

    tickers, sp_set, nd_set = get_tickers()
    results = []

    print(f"Total tickers: {len(tickers)}")

    for i in range(0, len(tickers), 50):

        batch = tickers[i:i+50]

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

                    df = data[ticker].dropna()

                    if len(df) < 30:
                        continue

                    # =========================
                    # BASE FEATURES
                    # =========================
                    df["MA21_PRICE"] = df["Close"].rolling(21).mean()
                    df["MA21_VOL"] = df["Volume"].rolling(21).mean()

                    latest = df.iloc[-1]
                    prev = df.iloc[-2]
                    last_7d = df.tail(7).copy()

                    if latest["Close"] < 1:
                        continue

                    if pd.isna(latest["MA21_VOL"]) or latest["MA21_VOL"] < 500000:
                        continue

                    # =========================
                    # 1D
                    # =========================
                    price_change_1d = (latest["Close"] - prev["Close"]) / prev["Close"]
                    volume_change_1d = (latest["Volume"] - prev["Volume"]) / prev["Volume"]

                    price_vs_ma21_1d = latest["Close"] / latest["MA21_PRICE"]
                    volume_vs_ma21_1d = latest["Volume"] / latest["MA21_VOL"]

                    # =========================
                    # 7D
                    # =========================
                    last_7d["price_change"] = last_7d["Close"].pct_change()
                    last_7d["volume_change"] = last_7d["Volume"].pct_change()

                    max_7d_price_change = last_7d["price_change"].max()
                    max_7d_volume_change = last_7d["volume_change"].max()

                    last_7d["price_vs_ma21"] = last_7d["Close"] / last_7d["MA21_PRICE"]
                    last_7d["vol_vs_ma21"] = last_7d["Volume"] / last_7d["MA21_VOL"]

                    max_7d_price_vs_ma21 = last_7d["price_vs_ma21"].max()
                    max_7d_vol_vs_ma21 = last_7d["vol_vs_ma21"].max()

                    # =========================
                    # FUNDAMENTALS (SAFE ADD)
                    # =========================
                    fund = get_fundamentals(ticker)

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

                        "PriceChange1D": round(price_change_1d * 100, 2),
                        "VolumeChange1D": round(volume_change_1d * 100, 2),

                        "PriceVsMA21_1D": round(price_vs_ma21_1d, 3),
                        "VolumeVsMA21_1D": round(volume_vs_ma21_1d, 3),

                        "Max7DPriceChange": round(max_7d_price_change * 100, 2),
                        "Max7DVolumeChange": round(max_7d_volume_change * 100, 2),

                        "Max7DPriceVsMA21": round(max_7d_price_vs_ma21, 3),
                        "Max7DVolumeVsMA21": round(max_7d_vol_vs_ma21, 3),

                        # NEW FIELDS (SAFE FOR HOVER ONLY)
                        "PE": fund["PE"],
                        "MarketCap": fund["MarketCap"],
                        "EPS": fund["EPS"],
                        "Sector": fund["Sector"],
                        "Volatility30D": fund["Volatility30D"],
                    })

                except Exception:
                    continue

        except Exception as e:
            print("Batch error:", e)

        time.sleep(0.15)

    df = pd.DataFrame(results)

    if not df.empty:
        df = df.sort_values("Max7DPriceChange", ascending=False)

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

    print("Running Baizora v10 scanner...")

    df = scan()

    print(df.head(10))

    export(df)

    print("✅ Done")