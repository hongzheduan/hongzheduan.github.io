from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
import pandas as pd
import time


app = FastAPI()

# SIMPLE USER DATABASE (for now)
users = {
    "test@gmail.com": "free",
    "vip@gmail.com": "premium",
    "pro@gmail.com": "premium"
}

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
def get_signals(request: Request):

    email = request.query_params.get("email", "")

    # get cached data (IMPORTANT)
    data = get_cached_data()

    # determine tier
    tier = users.get(email, "free")

    # sort data
    data.sort(key=lambda x: x.get("relVol", 0), reverse=True)

    # apply restriction
    if tier == "free":
        filtered_data = data[:3]
    else:
        filtered_data = data

    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tier": tier,
        "data": filtered_data
    }

@app.get("/refresh")
def refresh():
    global DATA_CACHE, LAST_LOAD_TIME
    DATA_CACHE = load_data()
    LAST_LOAD_TIME = time.time()
    return {"status": "refreshed"}