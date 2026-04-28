import pandas as pd
import json
import subprocess

# 1. read your CSV
df = pd.read_csv("C:/Users/hongz/Desktop/Matt/stock_scanner/results/results.csv")

# 2. rename columns
df = df.rename(columns={
    "Ticker": "ticker",
    "RelVol": "relVol",
    "MaxRelVol_7D": "maxRelVol",
    "AvgVol(m)": "avgVol",
    "LatestPrice": "price",
    "PriceChange1D%": "change1d",
    "PriceChange7D%": "change7d",
    "Score_Significance": "signal"
})

# 3. convert to JSON
data = df.to_dict(orient="records")

# 4. save to GitHub data folder
with open("data/latest.json", "w") as f:
    json.dump(data, f, indent=2)

print("✅ JSON updated")

# 5. push to GitHub
subprocess.run(["git", "add", "."])
subprocess.run(["git", "commit", "-m", "auto update signals"])
subprocess.run(["git", "push"])

print("🚀 Pushed to GitHub")