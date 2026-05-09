import pandas as pd
import requests
import json
from io import StringIO

# =========================
# S&P 500 (your working version)
# =========================
def get_sp500():

    url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"

    df = pd.read_csv(url)

    return df["Symbol"].tolist()


# =========================
# NASDAQ-100
# =========================
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

def get_nasdaq100():
    url = "https://raw.githubusercontent.com/boris-kuz/nasdaq-list/main/nasdaq100.csv"
    df = pd.read_csv(url)

    # column is usually "Symbol"
    return df["Symbol"].tolist()

# =========================
# MAIN
# =========================
if __name__ == "__main__":

    sp500 = get_sp500()
    nasdaq100 = get_nasdaq100()

    # merge + dedupe + Yahoo-compatible symbols
    tickers = sorted(list(set(
        t.replace(".", "-")
        for t in (sp500 + nasdaq100)
    )))

    with open("tickers.json", "w") as f:
        json.dump(tickers, f, indent=2)

    print(f"S&P 500: {len(sp500)}")
    print(f"Nasdaq-100: {len(nasdaq100)}")
    print(f"Final unique tickers: {len(tickers)}")