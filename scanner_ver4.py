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
TIME_STR = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

os.makedirs("data", exist_ok=True)
os.makedirs("archive", exist_ok=True)

LATEST_PATH = "data/latest.json"
FREE_PATH = "data/free.json"
ARCHIVE_PATH = f"archive/{DATE_STR}.json"
CSV_PATH = f"results_{DATE_STR}.csv"

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
            data = yf.download(batch, period="3mo", group_by="ticker", progress=False)

            for ticker in batch:
                try:
                    df = data[ticker].dropna()

                    if len(df) < 30:
                        continue

                    df["avg_vol"] = df["Volume"].rolling(21).mean()
                    df["rel_vol"] = df["Volume"] / df["avg_vol"]

                    df["avg_close"] = df["Close"].rolling(21).mean()
                    df["price_rel"] = df["Close"] / df["avg_close"]

                    latest = df.iloc[-1]
                    prev = df.iloc[-2]
                    last_7d = df.tail(7)

                    # basic filters only
                    if latest["Close"] < 1:
                        continue
                    if latest["avg_vol"] < 500000:
                        continue

                    # =========================
                    # 1D
                    # =========================
                    price_change_1d = (latest["Close"] - prev["Close"]) / prev["Close"]
                    vol_change_1d = latest["Volume"] / latest["avg_vol"]
                    score_1d = vol_change_1d * price_change_1d

                    # =========================
                    # 7D
                    # =========================
                    max_rel_vol_7d = last_7d["rel_vol"].max()
                    price_rel_7d = last_7d["price_rel"].max()

                    score_7d = max_rel_vol_7d * price_rel_7d

                    results.append({
                        "Ticker": ticker,
                        "Price": round(latest["Close"], 2),

                        "PriceChange1D": round(price_change_1d * 100, 2),
                        "VolChange1D": round(vol_change_1d, 2),
                        "Score1D": round(score_1d, 3),

                        "PriceChange7D": round((price_rel_7d - 1) * 100, 2),
                        "VolChange7D": round(max_rel_vol_7d, 2),
                        "Score7D": round(score_7d, 3),
                    })

                except:
                    continue

        except Exception as e:
            print("Batch error:", e)

        time.sleep(0.2)

    df = pd.DataFrame(results)

    if df.empty:
        return None

    df = df.sort_values("Score7D", ascending=False)

    return df

# =========================
# EXPORT
# =========================
def export(df):

    status = "LIVE" if df is not None else "EMPTY"

    payload = {
        "date": DATE_STR,
        "timestamp": TIME_STR,
        "status": status,
        "data": [] if df is None else df.to_dict(orient="records")
    }

    # latest
    with open(LATEST_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    # archive
    with open(ARCHIVE_PATH, "w") as f:
        json.dump(payload, f, indent=2)

    # free version
    free_payload = {
        "date": DATE_STR,
        "data": [] if df is None else df.head(3).to_dict(orient="records")
    }

    with open(FREE_PATH, "w") as f:
        json.dump(free_payload, f, indent=2)

    print(f"✅ saved ({status})")

# =========================
# MAIN
# =========================
if __name__ == "__main__":

    print("Running scanner v4...")

    df = scan()

    if df is not None:
        df.to_csv(CSV_PATH, index=False)

    export(df)

    print("Done")