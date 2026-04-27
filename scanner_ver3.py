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

CSV_PATH = f"results_{DATE_STR}.csv"
JSON_PATH = "data/signals.json"

EMAIL_ENABLED = True  # turn off if not needed

# =========================
# LOAD UNIVERSE
# =========================
def get_tickers():
    return pd.read_csv("data/universe.csv").iloc[:, 0].dropna().tolist()

# =========================
# SCORING LABEL
# =========================
def score_label(score):
    if score < 0.5:
        return "Weak"
    elif score < 1.5:
        return "Moderate"
    elif score < 3:
        return "Strong"
    else:
        return "Very Strong"

# =========================
# SCAN ENGINE
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

                    latest = df.iloc[-1]
                    prev = df.iloc[-2]
                    last_week = df.tail(7)

                    # =====================
                    # FILTERS
                    # =====================
                    if latest["Close"] < 1:
                        continue

                    if latest["avg_vol"] < 500000:
                        continue

                    if pd.isna(last_week["rel_vol"].max()):
                        continue

                    max_rel_7d = last_week["rel_vol"].max()

                    if max_rel_7d < 2.5:
                        continue

                    rel_today = latest["Volume"] / latest["avg_vol"]

                    price_change_7d = (
                        last_week["Close"].iloc[-1] - last_week["Close"].iloc[0]
                    ) / last_week["Close"].iloc[0]

                    price_change_1d = (
                        latest["Close"] - prev["Close"]
                    ) / prev["Close"]

                    score = max_rel_7d * abs(price_change_7d)

                    results.append({
                        "Ticker": ticker,
                        "Price": round(latest["Close"], 2),
                        "RelVol": round(rel_today, 2),
                        "MaxRelVol_7D": round(max_rel_7d, 2),
                        "Change1D": round(price_change_1d * 100, 2),
                        "Change7D": round(price_change_7d * 100, 2),
                        "Score": round(score, 3),
                        "Signal": score_label(score)
                    })

                except Exception as e:
                    continue

        except Exception as e:
            print("Batch error:", e)

        time.sleep(0.2)

    df = pd.DataFrame(results)

    if not df.empty:
        df = df.sort_values("Score", ascending=False).reset_index(drop=True)

    return df

# =========================
# EXPORT JSON FOR WEBSITE
# =========================
def export_json(df):
    data = {
        "timestamp": datetime.now().strftime("%B %d, %Y %I:%M %p ET"),
        "tier": "premium",
        "data": df.to_dict(orient="records")
    }

    with open(JSON_PATH, "w") as f:
        json.dump(data, f, indent=2)

    print("✅ signals.json updated")

# =========================
# SPLIT FREE VERSION
# =========================
def export_free_version(df):
    free_df = df.head(3).copy()

    data = {
        "timestamp": datetime.now().strftime("%B %d, %Y %I:%M %p ET"),
        "tier": "free",
        "data": free_df.to_dict(orient="records")
    }

    with open("data/signals_free.json", "w") as f:
        json.dump(data, f, indent=2)

    print("✅ signals_free.json updated")

# =========================
# MAIN
# =========================
if __name__ == "__main__":

    print("Running Baizora scanner...")

    df = scan()

    print(df.head(20))

    # Save CSV backup
    df.to_csv(CSV_PATH, index=False)

    # Export for website
    export_json(df)
    export_free_version(df)

    print("✅ Done")