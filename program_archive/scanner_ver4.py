# scanner_ver5.py
# Baizora Quant Scanner (clean consistent scoring model)

import pandas as pd
import yfinance as yf
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

LATEST_JSON = f"{DATA_DIR}/latest.json"
CSV_PATH = f"{ARCHIVE_DIR}/results_{DATE_STR}.csv"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

# =========================
# LOAD UNIVERSE
# =========================
def get_tickers():
    return pd.read_csv("universe.csv").iloc[:, 0].dropna().tolist()

# =========================
# CLASSIFICATION
# =========================
def score_band(x):
    if x < 0:
        return "Negative"
    elif x < 0.5:
        return "Low"
    elif x < 1.5:
        return "Moderate"
    elif x < 3:
        return "High"
    else:
        return "Very High"

# =========================
# MAIN SCAN
# =========================
def scan():

    tickers = get_tickers()
    results = []

    for i in range(0, len(tickers), 50):

        batch = tickers[i:i+50]

        try:
            data = yf.download(
                batch,
                period="4mo",
                group_by="ticker",
                progress=False,
                auto_adjust=False
            )

            for ticker in batch:

                try:
                    df = data[ticker].dropna()

                    if len(df) < 30:
                        continue

                    # -----------------
                    # Rolling Baselines
                    # -----------------
                    df["avg_vol"] = df["Volume"].rolling(21).mean()
                    df["rel_vol"] = df["Volume"] / df["avg_vol"]

                    latest = df.iloc[-1]
                    prev = df.iloc[-2]
                    last_7d = df.tail(7).copy()

                    # -----------------
                    # Filters
                    # -----------------
                    if latest["Close"] < 1:
                        continue

                    if latest["avg_vol"] < 500000:
                        continue

                    if pd.isna(latest["avg_vol"]):
                        continue

                    # =========================
                    # 1 DAY METRICS
                    # =========================
                    price_change_1d = (
                        latest["Close"] - prev["Close"]
                    ) / prev["Close"]

                    vol_change_1d = latest["rel_vol"]

                    score_1d = vol_change_1d * price_change_1d

                    # =========================
                    # 7 DAY METRICS
                    # Consistent logic:
                    # score = rel volume * return
                    # same-day actual max score
                    # =========================
                    last_7d["ret_7d_anchor"] = (
                        latest["Close"] - last_7d["Close"]
                    ) / last_7d["Close"]

                    last_7d["score_combo"] = (
                        last_7d["rel_vol"] *
                        last_7d["ret_7d_anchor"]
                    )

                    best_row = last_7d.loc[
                        last_7d["score_combo"].idxmax()
                    ]

                    price_change_7d = best_row["ret_7d_anchor"]
                    vol_change_7d = best_row["rel_vol"]
                    score_7d = best_row["score_combo"]

                    # =========================
                    # OUTPUT
                    # =========================
                    results.append({
                        "Date": DATE_STR,
                        "Ticker": ticker,
                        "Price": round(latest["Close"], 2),

                        "PriceChange1D": round(price_change_1d * 100, 2),
                        "VolChange1D": round(vol_change_1d, 2),
                        "Score1D": round(score_1d, 3),
                        "Band1D": score_band(score_1d),

                        "PriceChange7D": round(price_change_7d * 100, 2),
                        "VolChange7D": round(vol_change_7d, 2),
                        "Score7D": round(score_7d, 3),
                        "Band7D": score_band(score_7d),
                    })

                except:
                    continue

        except Exception as e:
            print("Batch error:", e)

        time.sleep(0.25)

    df = pd.DataFrame(results)

    if not df.empty:
        df = df.sort_values(
            "Score7D",
            ascending=False
        ).reset_index(drop=True)

        # Percentile Rank
        df["Rank7D"] = (
            df["Score7D"].rank(pct=True) * 100
        ).round(1)

        df["Rank1D"] = (
            df["Score1D"].rank(pct=True) * 100
        ).round(1)

    return df

# =========================
# EXPORT
# =========================
def export(df):

    # CSV archive
    df.to_csv(CSV_PATH, index=False)

    # latest json for dashboard
    payload = {
        "date": DATE_STR,
        "status": "Updated",
        "count": len(df),
        "data": df.to_dict(orient="records")
    }

    with open(LATEST_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    print("✅ latest.json updated")
    print("✅ CSV archived")

# =========================
# MAIN
# =========================
if __name__ == "__main__":

    print("Running Baizora Scanner v5...")

    df = scan()

    print(df.head(20))

    export(df)

    print("✅ Done")