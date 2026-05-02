import pandas as pd
import yfinance as yf
import numpy as np
import time
import json
import os
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

# =========================
# UNIVERSE
# =========================
def get_tickers():
    return pd.read_csv("universe.csv").iloc[:, 0].dropna().tolist()

# =========================
# SCAN
# =========================
def scan():

    tickers = get_tickers()
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
                    # BASE FEATURES
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

                    # =========================================================
                    # 1D METRICS
                    # =========================================================

                    price_change_1d = (
                        latest["Close"] - prev["Close"]
                    ) / prev["Close"]

                    volume_change_1d = (
                        latest["Volume"] - prev["Volume"]
                    ) / prev["Volume"]

                    price_vs_ma21_1d = (
                        latest["Close"] / latest["MA21_PRICE"]
                    )

                    volume_vs_ma21_1d = (
                        latest["Volume"] / latest["MA21_VOL"]
                    )

                    # =========================================================
                    # 7D METRICS (EVENT BASED)
                    # =========================================================

                    last_7d["price_change"] = last_7d["Close"].pct_change()
                    max_7d_price_change = last_7d["price_change"].max()

                    last_7d["volume_change"] = last_7d["Volume"].pct_change()
                    max_7d_volume_change = last_7d["volume_change"].max()

                    last_7d["price_vs_ma21"] = (
                        last_7d["Close"] / last_7d["MA21_PRICE"]
                    )
                    max_7d_price_vs_ma21 = last_7d["price_vs_ma21"].max()

                    last_7d["vol_vs_ma21"] = (
                        last_7d["Volume"] / last_7d["MA21_VOL"]
                    )
                    max_7d_vol_vs_ma21 = last_7d["vol_vs_ma21"].max()

                    # =========================
                    # OUTPUT
                    # =========================
                    results.append({
                        "Date": DATE_STR,
                        "Ticker": ticker,
                        "Price": round(latest["Close"], 2),

                        # 1D
                        "PriceChange1D": round(price_change_1d * 100, 2),
                        "VolumeChange1D": round(volume_change_1d * 100, 2),
                        "PriceVsMA21_1D": round(price_vs_ma21_1d, 3),
                        "VolumeVsMA21_1D": round(volume_vs_ma21_1d, 3),

                        # 7D max
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

    sp500_df = df[df["Universe"] == "SP500"]
    nasdaq_df = df[df["Universe"] == "NASDAQ100"]

    sp500_df.to_csv(f"{DATA_DIR}/sp500.csv", index=False)
    nasdaq_df.to_csv(f"{DATA_DIR}/nasdaq100.csv", index=False)

    print("✅ Done")