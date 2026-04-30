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

OUTPUT_JSON = f"{DATA_DIR}/latest.json"
OUTPUT_CSV = f"{ARCHIVE_DIR}/results_{DATE_STR}.csv"

API_KEY = "brx09r7m8gaEMaIg51ZBBVC1gkcRJ71h"


# =========================
# UNIVERSE FETCH
# =========================
def get_universes():

    sp_url = f"https://financialmodelingprep.com/stable/sp500-constituent?apikey={API_KEY}"
    nd_url = f"https://financialmodelingprep.com/stable/nasdaq-constituent?apikey={API_KEY}"

    try:
        sp = requests.get(sp_url).json()
        nd = requests.get(nd_url).json()

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
# SCAN
# =========================
def scan():

    tickers, sp_set, nd_set = get_tickers()
    results = []

    for i in range(0, len(tickers), 50):

        batch = tickers[i:i+50]

        try:
            data = yf.download(
                batch,
                period="6mo",
                group_by="ticker",
                progress=False
            )

            for ticker in batch:

                try:
                    df = data[ticker].dropna()

                    if len(df) < 30:
                        continue

                    # =========================
                    # FEATURES
                    # =========================
                    df["MA21_PRICE"] = df["Close"].rolling(21).mean()
                    df["MA21_VOL"] = df["Volume"].rolling(21).mean()

                    latest = df.iloc[-1]
                    prev = df.iloc[-2]
                    last_7d = df.tail(7).copy()

                    # =========================
                    # FILTERS
                    # =========================
                    if latest["Close"] < 1:
                        continue

                    if latest["MA21_VOL"] < 500000:
                        continue

                    # =========================
                    # 1D METRICS
                    # =========================
                    price_change_1d = (latest["Close"] - prev["Close"]) / prev["Close"]
                    volume_change_1d = (latest["Volume"] - prev["Volume"]) / prev["Volume"]

                    price_vs_ma21_1d = latest["Close"] / latest["MA21_PRICE"]
                    volume_vs_ma21_1d = latest["Volume"] / latest["MA21_VOL"]

                    # =========================
                    # 7D METRICS
                    # =========================
                    last_7d["price_change"] = last_7d["Close"].pct_change()
                    max_7d_price_change = last_7d["price_change"].max()

                    last_7d["volume_change"] = last_7d["Volume"].pct_change()
                    max_7d_volume_change = last_7d["volume_change"].max()

                    last_7d["price_vs_ma21"] = last_7d["Close"] / last_7d["MA21_PRICE"]
                    max_7d_price_vs_ma21 = last_7d["price_vs_ma21"].max()

                    last_7d["vol_vs_ma21"] = last_7d["Volume"] / last_7d["MA21_VOL"]
                    max_7d_vol_vs_ma21 = last_7d["vol_vs_ma21"].max()

                    # =========================
                    # MULTI-MEMBERSHIP FLAGS
                    # =========================
                    in_sp500 = ticker in sp_set
                    in_nasdaq100 = ticker in nd_set

                    # =========================
                    # OUTPUT
                    # =========================
                    results.append({
                        "Date": DATE_STR,
                        "Ticker": ticker,

                        # 🔥 IMPORTANT FIX
                        "InSP500": in_sp500,
                        "InNASDAQ100": in_nasdaq100,

                        "Price": round(latest["Close"], 2),

                        # 1D
                        "PriceChange1D": round(price_change_1d * 100, 2),
                        "VolumeChange1D": round(volume_change_1d * 100, 2),
                        "PriceVsMA21_1D": round(price_vs_ma21_1d, 3),
                        "VolumeVsMA21_1D": round(volume_vs_ma21_1d, 3),

                        # 7D
                        "Max7DPriceChange": round(max_7d_price_change * 100, 2),
                        "Max7DVolumeChange": round(max_7d_volume_change * 100, 2),
                        "Max7DPriceVsMA21": round(max_7d_price_vs_ma21, 3),
                        "Max7DVolumeVsMA21": round(max_7d_vol_vs_ma21, 3),
                    })

                except Exception:
                    continue

        except Exception as e:
            print("Batch error:", e)

        time.sleep(0.2)

    df = pd.DataFrame(results)

    if not df.empty:
        df = df.sort_values("Max7DPriceChange", ascending=False)

    return df


# =========================
# EXPORT
# =========================
def export(df):

    df.to_csv(OUTPUT_CSV, index=False)

    payload = {
        "date": DATE_STR,
        "status": "Updated",
        "count": len(df),
        "data": df.to_dict(orient="records")
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    print("✅ Export complete")


# =========================
# MAIN
# =========================
if __name__ == "__main__":

    print("Running Baizora v8 scanner...")

    df = scan()

    print(df.head(20))

    export(df)

    print("✅ Done")