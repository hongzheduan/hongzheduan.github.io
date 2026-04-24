from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import time

app = FastAPI()

# allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# GLOBAL CACHE
# -------------------------
DATA_CACHE = []
LAST_LOAD_TIME = 0
CACHE_DURATION = 60  # seconds (adjust later)


# -------------------------
# LOAD + PROCESS DATA
# -------------------------
def load_data():
    df = pd.read_csv(r"C:/Users/hongz/Desktop/Matt/stock_scanner/results/results.csv")

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

    return df.to_dict(orient="records")


# -------------------------
# GET DATA WITH CACHE
# -------------------------
def get_cached_data():
    global DATA_CACHE, LAST_LOAD_TIME

    current_time = time.time()

    # reload if cache expired
    if current_time - LAST_LOAD_TIME > CACHE_DURATION:
        print("🔄 Reloading data...")
        DATA_CACHE = load_data()
        LAST_LOAD_TIME = current_time

    return DATA_CACHE


# -------------------------
# API ENDPOINT
# -------------------------
# @app.get("/signals")
# def get_signals():
#     return get_cached_data()

@app.get("/signals")
def get_signals():

    data = get_cached_data()

    # move logic FROM signalEngine.js TO HERE
    filtered = [
        x for x in data
        if x["relVol"] > 1.2 and x["change1d"] > 0
    ]

    # sort strongest first
    filtered.sort(key=lambda x: x["relVol"], reverse=True)

    return filtered

@app.get("/refresh")
def refresh():
    global DATA_CACHE, LAST_LOAD_TIME
    DATA_CACHE = load_data()
    LAST_LOAD_TIME = time.time()
    return {"status": "refreshed"}