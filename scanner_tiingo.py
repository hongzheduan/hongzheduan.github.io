"""Baizora Scanner — Tiingo commercial API edition."""
import pandas as pd
import numpy as np
import time
import json
import os
import glob
import re
import requests
from bs4 import BeautifulSoup
import sys
from datetime import date, datetime, timedelta, timezone
import math
import xml.etree.ElementTree as ET
from itertools import groupby
import pytz
import yfinance as yf

# =========================
# CONFIG
# =========================

TIINGO_API_KEY   = os.environ.get("TIINGO_API_KEY", "")
TIINGO_BASE      = "https://api.tiingo.com"
SKIP_EDGAR       = os.environ.get("SKIP_EDGAR",  "").lower() in ("1", "true", "yes")
EDGAR_ONLY       = os.environ.get("EDGAR_ONLY",  "").lower() in ("1", "true", "yes")

# Cost-cutting switch (no paying customers yet, 2026-08): sources daily OHLCV bars,
# the SPY benchmark, and BRK-A's price from free yfinance instead of Tiingo, and skips
# the Tiingo company-name/market-cap meta call entirely (falls back to SEC EDGAR's own
# name — see get_fundamentals()). Everything downstream (scan/export/candles/digest/
# score history/index news) is source-agnostic and unchanged either way. Flip back to
# "tiingo" (or unset) once there's revenue to justify the subscription again.
OHLCV_SOURCE     = os.environ.get("OHLCV_SOURCE", "tiingo").strip().lower()
USE_YFINANCE     = OHLCV_SOURCE == "yfinance"

DATE_STR         = datetime.now(pytz.timezone('America/New_York')).strftime("%Y-%m-%d")
_TIINGO_LAST_DATE = DATE_STR   # updated by __main__ to the last date Tiingo actually has data for
_STALE_TICKERS_EXCLUDED = []   # tickers dropped by __main__ because Tiingo hadn't published
                                # their bar for _TIINGO_LAST_DATE yet (partial-publish protection)
DATA_DIR         = "data"
ARCHIVE_DIR      = "archive"
OHLCV_CACHE_DIR  = os.path.join(DATA_DIR, "ohlcv_tiingo_cache")
YF_OHLCV_CACHE_DIR = os.path.join(DATA_DIR, "ohlcv_yfinance_cache")  # separate dir, never touches the Tiingo cache
FUND_CACHE_FILE  = os.path.join(DATA_DIR, "fundamentals_cache.json")
FUND_CACHE_TTL_DAYS = 0  # always re-fetch EDGAR every run; no stale data risk
SPLIT_GUARDS_FILE = os.path.join(DATA_DIR, "split_guards.csv")

os.makedirs(DATA_DIR,        exist_ok=True)
os.makedirs(ARCHIVE_DIR,     exist_ok=True)
os.makedirs(OHLCV_CACHE_DIR, exist_ok=True)
os.makedirs(YF_OHLCV_CACHE_DIR, exist_ok=True)

TIMEFRAMES = {
    "2W": 10,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "9M": 189,
    "1Y": 252,
    "2Y": 500,
    "5Y": 1260,
}

OUTPUT_JSON   = os.path.join(DATA_DIR,    "latest.json")
OUTPUT_CSV    = os.path.join(ARCHIVE_DIR, f"results_{DATE_STR}.csv")
DIGEST_JSON   = os.path.join(DATA_DIR,    "daily_digest.json")
BRIEFING_TXT     = os.path.join(DATA_DIR, "daily_briefing.txt")
BRIEFING_TXT_CN  = os.path.join(DATA_DIR, "daily_briefing_cn.txt")
MARKET_NEWS_JSON    = os.path.join(DATA_DIR, "market_news.json")
MARKET_NEWS_CN_JSON = os.path.join(DATA_DIR, "market_news_cn.json")
SCORE_HISTORY    = os.path.join(DATA_DIR, "score_history.json")
BAIZSCORE_TRAILING_FILE = os.path.join(DATA_DIR, "baizscore_trailing.json")  # per-ticker daily BaizScore, last 21 sessions — feeds BaizConviction
BAIZ_PERSIST_WINDOW = 21  # trading sessions (~1 month) — see assets/baizscore_backtest.html
BAIZSCORE_TREND_FILE = os.path.join(DATA_DIR, "baiz_score_trend.json")  # per-ticker rolling ~1Y history of all 4 Baizora scores — feeds dashboard sparklines
BAIZ_TREND_WINDOW = 252  # trading sessions (~1 year)

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# =========================
# TIINGO API HELPERS
# =========================

_tiingo_session = requests.Session()
_tiingo_session.headers.update({
    "Authorization": f"Token {TIINGO_API_KEY}",
    "Content-Type":  "application/json",
})


def _tiingo_get(path, params=None, retries=5):
    url = TIINGO_BASE + path
    for attempt in range(retries):
        try:
            r = _tiingo_session.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt
                print(f"  [tiingo] rate-limited, waiting {wait}s …")
                time.sleep(wait)
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                print(f"  [tiingo] GET {path} failed: {e}")
                return None
    return None


def _to_tiingo_ticker(ticker):
    """Internal format (BRK-B) → Tiingo format (brk-b). Hyphens are preserved."""
    return ticker.lower()


def _parse_tiingo_date(date_str):
    """Extract YYYY-MM-DD from Tiingo's ISO 8601 strings like 2024-06-06T00:00:00+00:00."""
    return (date_str or "")[:10]


# =========================
# NYSE HOLIDAY DETECTION
# =========================

def _easter(year):
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(114 + h + l - 7 * m, 31)
    return date(year, month, day + 1)


def _observed(d):
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nth_weekday(year, month, weekday, n):
    first = date(year, month, 1)
    first += timedelta(days=(weekday - first.weekday()) % 7)
    return first + timedelta(weeks=n - 1)


def _last_weekday(year, month, weekday):
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last = next_month - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def nyse_holidays(year):
    h = set()
    h.add(_observed(date(year, 1, 1)))
    h.add(_nth_weekday(year, 1, 0, 3))
    h.add(_nth_weekday(year, 2, 0, 3))
    h.add(_easter(year) - timedelta(days=2))
    h.add(_last_weekday(year, 5, 0))
    if year >= 2022:
        h.add(_observed(date(year, 6, 19)))
    h.add(_observed(date(year, 7, 4)))
    h.add(_nth_weekday(year, 9, 0, 1))
    h.add(_nth_weekday(year, 11, 3, 4))
    h.add(_observed(date(year, 12, 25)))
    return h


def is_market_holiday(d=None):
    if d is None:
        d = date.today()
    return d in nyse_holidays(d.year)


# =========================
# SIC → SECTOR MAPPING
# =========================

_SIC_TO_SECTOR = {
    # Technology
    "Electronic Computers":                                             "Technology",
    "Services-Prepackaged Software":                                    "Technology",
    "Semiconductors and Related Devices":                               "Technology",
    "Services-Computer Programming, Data Processing, Etc.":             "Technology",
    "Services-Computer Programming, Data Processing, Etc No":           "Technology",
    "Services-Computer Programming, Data Processing":                   "Technology",
    "Services-Computer Programming":                                    "Technology",
    "Services-Computer Integrated Systems Design":                      "Technology",
    "Computer Communications Equipment":                                "Technology",
    "Electronic Components & Accessories":                              "Technology",
    "Printed Circuit Boards":                                           "Technology",
    "Services-Computer Rental & Leasing":                               "Technology",
    "Services-Computer Maintenance & Repair":                           "Technology",
    "Services-Computer Processing & Data Preparation":                  "Technology",
    "Services-Information Retrieval Services":                          "Technology",
    "Telephone & Telegraph Apparatus":                                  "Technology",
    "Radio & TV Broadcasting & Communications Equipment":               "Technology",
    "Electronic & Other Electrical Equipment (No Computer Equipment)":  "Technology",
    "Office Machines, Not Elsewhere Classified":                        "Technology",
    "Calculating & Accounting Machines (No Electronic Computers)":      "Technology",
    "Instruments For Meas & Testing of  Electricity & Elec Signals":   "Technology",
    # Healthcare
    "Pharmaceutical Preparations":                                      "Healthcare",
    "Biological Products (No Diagnostic Substances)":                   "Healthcare",
    "Biological Products (ex Diagnostics)":                             "Healthcare",
    "Surgical & Medical Instruments & Apparatus":                       "Healthcare",
    "In Vitro & In Vivo Diagnostic Substances":                         "Healthcare",
    "Electromedical & Electrotherapeutic Apparatus":                    "Healthcare",
    "Ophthalmic Goods":                                                 "Healthcare",
    "Medicinal Chemicals & Botanical Products":                         "Healthcare",
    "Services-Health Services":                                         "Healthcare",
    "Services-Hospitals":                                               "Healthcare",
    "Services-Medical Laboratories":                                    "Healthcare",
    "Services-Misc Health & Allied Services":                           "Healthcare",
    "Services-Home Health Care Services":                               "Healthcare",
    "Services-Hospital & Medical Service Plans":                        "Healthcare",
    "Services-Specialty Outpatient Facilities":                         "Healthcare",
    "Services-Offices & Clinics of Doctors of Medicine":                "Healthcare",
    # Financial Services
    "National Commercial Banks":                                        "Financial Services",
    "National Commercial Banks & Trust Companies":                      "Financial Services",
    "State Commercial Banks":                                           "Financial Services",
    "State Commercial Banks-Federal Reserve Members":                   "Financial Services",
    "State Commercial Banks & Trust Companies":                         "Financial Services",
    "Savings Institutions, Federally Chartered":                        "Financial Services",
    "Savings Institutions, Not Federally Chartered":                    "Financial Services",
    "Personal Credit Institutions":                                     "Financial Services",
    "Federal-Sponsored Credit Agencies":                                "Financial Services",
    "Short-Term Business Credit Institutions":                          "Financial Services",
    "Miscellaneous Business Credit Institutions":                       "Financial Services",
    "Mortgage Bankers, Loan Correspondents":                            "Financial Services",
    "Security Brokers, Dealers, & Flotation Companies":                 "Financial Services",
    "Investment Advice":                                                "Financial Services",
    "Services-Investment Offices":                                      "Financial Services",
    "Open-End Management Investment Companies":                         "Financial Services",
    "Closed-End Management Investment Companies":                       "Financial Services",
    "Fire, Marine & Casualty Insurance":                                "Financial Services",
    "Life Insurance":                                                   "Financial Services",
    "Accident and Health Insurance":                                    "Financial Services",
    "Surety Insurance":                                                 "Financial Services",
    "Title Insurance":                                                  "Financial Services",
    "Insurance Agents, Brokers & Services":                             "Financial Services",
    "Finance Services":                                                 "Financial Services",
    "Services-Finance Services":                                        "Financial Services",
    # Real Estate
    "Real Estate Investment Trusts":                                    "Real Estate",
    "Real Estate Dealers (For Their Own Account)":                      "Real Estate",
    "Land Subdividers & Developers (No Cemeteries)":                    "Real Estate",
    "Operators of Apartment Buildings":                                 "Real Estate",
    "Operators of Dwellings Buildings, Except Apartment Buildings":     "Real Estate",
    "Real Estate":                                                      "Real Estate",
    # Consumer Cyclical
    "Apparel & Other Finishd Prods of  Fabrics & Similar Matl":        "Consumer Cyclical",
    "Motor Vehicles & Passenger Car Bodies":                            "Consumer Cyclical",
    "Motor Vehicle Parts & Accessories":                                "Consumer Cyclical",
    "Retail-Auto Dealers & Gas Stations":                               "Consumer Cyclical",
    "Retail-Apparel & Accessory Stores":                                "Consumer Cyclical",
    "Retail-Family Clothing Stores":                                    "Consumer Cyclical",
    "Retail-Shoe Stores":                                               "Consumer Cyclical",
    "Retail-Jewelry Stores":                                            "Consumer Cyclical",
    "Retail-Home Furniture, Furnishings & Equipment Stores":            "Consumer Cyclical",
    "Retail-Eating & Drinking Places":                                  "Consumer Cyclical",
    "Retail-Hobby, Toy & Game Shops":                                   "Consumer Cyclical",
    "Retail-Sporting Goods Stores & Bicycle Shops":                     "Consumer Cyclical",
    "Retail-Catalog & Mail-Order Houses":                               "Consumer Cyclical",
    "Retail-Stores, Not Elsewhere Classified":                          "Consumer Cyclical",
    "Retail-Lumber & Building Material Dealers":                        "Consumer Cyclical",
    "Retail-Radio, Television & Consumer Electronics Stores":           "Consumer Cyclical",
    "Retail-Department Stores":                                         "Consumer Cyclical",
    "Hotels & Motels":                                                  "Consumer Cyclical",
    "Air Transportation, Scheduled":                                    "Consumer Cyclical",
    "Air Transportation, Nonscheduled":                                 "Consumer Cyclical",
    "Services-Amusement & Recreation Services":                         "Consumer Cyclical",
    "Services-Automotive Repair, Services & Parking":                   "Consumer Cyclical",
    "Services-Video Tape Rental":                                       "Consumer Cyclical",
    "Games, Toys & Children's Vehicles":                                "Consumer Cyclical",
    "Household Furniture":                                              "Consumer Cyclical",
    "Travel Agencies":                                                  "Consumer Cyclical",
    "Construction Special Trade Contractors":                           "Consumer Cyclical",
    # Consumer Defensive
    "Retail-Grocery Stores":                                            "Consumer Defensive",
    "Retail-Drug Stores and Proprietary Stores":                        "Consumer Defensive",
    "Retail-Variety Stores":                                            "Consumer Defensive",
    "Retail-Food Stores":                                               "Consumer Defensive",
    "Food and Kindred Products":                                        "Consumer Defensive",
    "Beverages":                                                        "Consumer Defensive",
    "Tobacco Products":                                                 "Consumer Defensive",
    "Soap, Detergents, Cleaning Preparations, Perfumes, Cosmetics":     "Consumer Defensive",
    "Soap, Detergents, Cleaning Preparations, Perfumes":                "Consumer Defensive",
    "Grain Mill Products":                                              "Consumer Defensive",
    "Dairy Products":                                                   "Consumer Defensive",
    "Canned, Frozen & Preserved Fruit, Veg & Food Specialties":         "Consumer Defensive",
    "Bakery Products":                                                  "Consumer Defensive",
    "Sugar & Confectionery Products":                                   "Consumer Defensive",
    "Agricultural Production-Livestock & Animal Specialties":           "Consumer Defensive",
    # Industrials
    "Rolling Drawing & Extruding of  Nonferrous Metals":                "Industrials",
    "Aircraft & Parts":                                                 "Industrials",
    "Guided Missiles & Space Vehicles & Parts":                         "Industrials",
    "Ship & Boat Building & Repairing":                                 "Industrials",
    "Railroad Equipment":                                               "Industrials",
    "Railroads, Line-Haul Operating":                                   "Industrials",
    "Motor Freight Transportation & Warehousing":                       "Industrials",
    "Trucking & Warehousing":                                           "Industrials",
    "Air Courier Services":                                             "Industrials",
    "Services-Courier Services (No Air)":                               "Industrials",
    "Water Transportation":                                             "Industrials",
    "Transportation Services":                                          "Industrials",
    "Industrial & Commercial Machinery & Equipment":                    "Industrials",
    "Electrical Industrial Apparatus":                                  "Industrials",
    "Special Industry Machinery":                                       "Industrials",
    "General Industrial Machinery & Equipment":                         "Industrials",
    "Construction & Mining (No Oil Well) Machinery & Equipment":        "Industrials",
    "Farm Machinery & Equipment":                                       "Industrials",
    "Engines & Turbines":                                               "Industrials",
    "Fabricated Metal Products":                                        "Industrials",
    "Measuring & Controlling Instruments":                              "Industrials",
    "Household Appliances":                                             "Industrials",
    "Services-Engineering Services":                                    "Industrials",
    "Services-Management Consulting Services":                          "Industrials",
    "Services-Staffing Services":                                       "Industrials",
    "Services-Security Services":                                       "Industrials",
    "Services-Facilities Support Management Services":                  "Industrials",
    "Services-Waste Management":                                        "Industrials",
    "Services-Misc Business Services":                                  "Industrials",
    "Services-Equipment Rental & Leasing":                              "Industrials",
    "Services-Services to Buildings & Dwellings":                       "Industrials",
    "Construction-General Contractors & Operative Builders":            "Industrials",
    "Heavy Construction, Except Building Construction, Contractors":    "Industrials",
    # Energy
    "OIL ROYALTY TRADERS":                                              "Energy",
    "COGENERATION SERVICES & SMALL POWER PRODUCERS":                    "Utilities",
    "Crude Petroleum & Natural Gas":                                    "Energy",
    "Oil & Gas Field Services":                                         "Energy",
    "Petroleum Refining":                                               "Energy",
    "Coal Mining":                                                      "Energy",
    "Pipelines (Except Natural Gas)":                                   "Energy",
    "Natural Gas Transmission":                                         "Energy",
    "Natural Gas Transmission & Distribution":                          "Energy",
    "Natural Gas Transmisison & Distribution":                          "Energy",
    "Oil & Gas Field Machinery & Equipment":                            "Energy",
    "Petroleum & Petroleum Products Wholesalers (No Bulk Stations)":    "Energy",
    # Utilities
    "Electric Services":                                                "Utilities",
    "Electric & Other Services Combined":                               "Utilities",
    "Gas & Other Services Combined":                                    "Utilities",
    "Combination Electric & Gas & Other Utility Services":              "Utilities",
    "Natural Gas Distribution":                                         "Utilities",
    "Water Supply":                                                     "Utilities",
    "Sanitary Services":                                                "Utilities",
    # Basic Materials
    "Metal Mining":                                                     "Basic Materials",
    "Gold and Silver Ores Mining":                                      "Basic Materials",
    "Iron Ores":                                                        "Basic Materials",
    "Copper Ores":                                                      "Basic Materials",
    "Mining & Quarrying of Nonmetallic Minerals (No Fuels)":            "Basic Materials",
    "Chemicals & Allied Products":                                      "Basic Materials",
    "Plastics Materials, Synthetic Resins & Nonvulcanizable Elastomers": "Basic Materials",
    "Primary Metal Industries":                                         "Basic Materials",
    "Blast Furnaces & Steel Mills":                                     "Basic Materials",
    "Steel Works, Blast Furnaces (Including Coke Ovens)":               "Basic Materials",
    "Rolling Drawing & Extruding of Nonferrous Metals":                 "Basic Materials",
    "Primary Production of Aluminum":                                   "Basic Materials",
    "Paper & Allied Products":                                          "Basic Materials",
    "Lumber & Wood Products (Except Furniture)":                        "Basic Materials",
    "Agricultural Chemicals":                                           "Basic Materials",
    "Industrial Chemicals & Synthetics":                                "Basic Materials",
    "Miscellaneous Chemical Products":                                  "Basic Materials",
    # Communication Services
    "COMMUNICATIONS SERVICES, NEC":                                     "Communication Services",
    "SERVICES-ADVERTISING AGENCIES":                                    "Communication Services",
    "Telephone Communications (No Radio Telephone)":                    "Communication Services",
    "Telephone Communications":                                         "Communication Services",
    "Radiotelephone Communications":                                    "Communication Services",
    "Radio Broadcasting Stations":                                      "Communication Services",
    "Television Broadcasting Stations":                                 "Communication Services",
    "Services-Motion Picture Production":                               "Communication Services",
    "Services-Cable & Other Pay Television Services":                   "Communication Services",
    "Services-Misc Entertainment":                                      "Communication Services",
    "Newspapers: Publishing & Printing":                                "Communication Services",
    "Periodicals: Publishing & Printing":                               "Communication Services",
    "Books: Publishing & Printing":                                     "Communication Services",
    # ALL-CAPS SIC descriptions (EDGAR submissions API returns mixed/title case)
    "COMMUNICATIONS EQUIPMENT, NEC":                                    "Technology",
    "ELECTRONIC COMPONENTS, NEC":                                       "Technology",
    "ELECTRONIC CONNECTORS":                                            "Technology",
    "INSTRUMENTS FOR MEAS & TESTING OF ELECTRICITY & ELEC SIGNALS":    "Technology",
    "OPTICAL INSTRUMENTS & LENSES":                                     "Technology",
    "WHOLESALE-ELECTRONIC PARTS & EQUIPMENT, NEC":                      "Technology",
    "LABORATORY ANALYTICAL INSTRUMENTS":                                "Healthcare",
    "ORTHOPEDIC, PROSTHETIC & SURGICAL APPLIANCES & SUPPLIES":          "Healthcare",
    "SERVICES-COMMERCIAL PHYSICAL & BIOLOGICAL RESEARCH":               "Healthcare",
    "SERVICES-MISC HEALTH & ALLIED SERVICES, NEC":                      "Healthcare",
    "WHOLESALE-DRUGS, PROPRIETARIES & DRUGGISTS' SUNDRIES":             "Healthcare",
    "X-RAY APPARATUS & TUBES & RELATED IRRADIATION APPARATUS":          "Healthcare",
    "SECURITY & COMMODITY BROKERS, DEALERS, EXCHANGES & SERVICES":      "Financial Services",
    "SECURITY BROKERS, DEALERS & FLOTATION COMPANIES":                  "Financial Services",
    "SERVICES-CONSUMER CREDIT REPORTING, COLLECTION AGENCIES":          "Financial Services",
    "APPAREL & OTHER FINISHD PRODS OF FABRICS & SIMILAR MATL":          "Consumer Cyclical",
    "GENERAL BLDG CONTRACTORS - RESIDENTIAL BLDGS":                     "Consumer Cyclical",
    "LEATHER & LEATHER PRODUCTS":                                       "Consumer Cyclical",
    "MEN'S & BOYS' FURNISHGS, WORK CLOTHG, & ALLIED GARMENTS":          "Consumer Cyclical",
    "RETAIL-RETAIL STORES, NEC":                                        "Consumer Cyclical",
    "RETAIL-RADIO, TV & CONSUMER ELECTRONICS STORES":                   "Consumer Cyclical",
    "WHOLESALE-MOTOR VEHICLE SUPPLIES & NEW PARTS":                     "Consumer Cyclical",
    "GAMES, TOYS & CHILDREN'S VEHICLES (NO DOLLS & BICYCLES)":          "Consumer Cyclical",
    "OPERATIVE BUILDERS":                                               "Consumer Cyclical",
    "RETAIL-BUILDING MATERIALS, HARDWARE, GARDEN SUPPLY":               "Consumer Cyclical",
    "RUBBER & PLASTICS FOOTWEAR":                                       "Consumer Cyclical",
    "BOTTLED & CANNED SOFT DRINKS & CARBONATED WATERS":                 "Consumer Defensive",
    "CANNED, FROZEN & PRESERVD FRUIT, VEG & FOOD SPECIALTIES":          "Consumer Defensive",
    "CANNED, FRUITS, VEG, PRESERVES, JAMS & JELLIES":                   "Consumer Defensive",
    "CIGARETTES":                                                       "Consumer Defensive",
    "FATS & OILS":                                                      "Consumer Defensive",
    "MISCELLANEOUS FOOD PREPARATIONS & KINDRED PRODUCTS":               "Consumer Defensive",
    "PERFUMES, COSMETICS & OTHER TOILET PREPARATIONS":                  "Consumer Defensive",
    "MEAT PACKING PLANTS":                                              "Consumer Defensive",
    "WHOLESALE-GROCERIES & RELATED PRODUCTS":                           "Consumer Defensive",
    "POULTRY SLAUGHTERING AND PROCESSING":                              "Consumer Defensive",
    "SPECIALTY CLEANING, POLISHING AND SANITATION PREPARATIONS":        "Consumer Defensive",
    "AIR-COND & WARM AIR HEATG EQUIP & COMM & INDL REFRIG EQUIP":       "Industrials",
    "AUTO CONTROLS FOR REGULATING RESIDENTIAL & COMML ENVIRONMENTS":    "Industrials",
    "CUTLERY, HANDTOOLS & GENERAL HARDWARE":                            "Industrials",
    "ELECTRICAL WORK":                                                  "Industrials",
    "INDUSTRIAL INSTRUMENTS FOR MEASUREMENT, DISPLAY, AND CONTROL":     "Industrials",
    "MEASURING & CONTROLLING DEVICES, NEC":                             "Industrials",
    "MISCELLANEOUS MANUFACTURING INDUSTRIES":                           "Industrials",
    "ORDNANCE & ACCESSORIES, (NO VEHICLES/GUIDED MISSILES)":            "Industrials",
    "PUMPS & PUMPING EQUIPMENT":                                        "Industrials",
    "REFUSE SYSTEMS":                                                   "Industrials",
    "SEARCH, DETECTION, NAVIGATION, GUIDANCE, AERONAUTICAL SYS":        "Industrials",
    "SERVICES-BUSINESS SERVICES, NEC":                                  "Industrials",
    "SERVICES-DETECTIVE, GUARD & ARMORED CAR SERVICES":                 "Industrials",
    "SERVICES-ENGINEERING, ACCOUNTING, RESEARCH, MANAGEMENT":           "Industrials",
    "SERVICES-TO DWELLINGS & OTHER BUILDINGS":                          "Industrials",
    "WHOLESALE-DURABLE GOODS":                                          "Industrials",
    "DRAWING & INSULATING OF NONFERROUS WIRE":                          "Industrials",
    "MISCELLANEOUS FABRICATED METAL PRODUCTS":                          "Industrials",
    "MOTORS & GENERATORS":                                              "Industrials",
    "SERVICES-EQUIPMENT RENTAL & LEASING, NEC":                         "Industrials",
    "SERVICES-MANAGEMENT SERVICES":                                     "Industrials",
    "WHOLESALE-MISC DURABLE GOODS":                                     "Industrials",
    "HEATING EQUIP, EXCEPT ELEC & WARM AIR; & PLUMBING FIXTURES":       "Industrials",
    "CEMENT, HYDRAULIC":                                                "Basic Materials",
    "GOLD AND SILVER ORES":                                             "Basic Materials",
    "METAL CANS":                                                       "Basic Materials",
    "PAINTS, VARNISHES, LACQUERS, ENAMELS & ALLIED PRODS":              "Basic Materials",
}

_SIC_KEYWORDS = [
    ("Technology",             ["software", "semiconductor", "computer", "circuit board", "data processing", "electronic component"]),
    ("Healthcare",             ["pharmaceutical", "biotech", "medical", "hospital", "health service", "diagnostic", "therapeutic"]),
    ("Financial Services",     ["bank", "insurance", "financial service", "investment", "credit institution", "securities", "brokerage"]),
    ("Real Estate",            ["real estate", "reit", "property", "apartment", "realty"]),
    ("Energy",                 ["petroleum", "oil & gas", "coal mining", "pipeline", "oil field"]),
    ("Utilities",              ["electric service", "electric & other", "gas & other", "water supply", "utility"]),
    ("Basic Materials",        ["chemical", "metal mining", "steel", "aluminum", "paper", "lumber", "mining", "plastic material"]),
    ("Communication Services", ["telephone", "telecom", "broadcasting", "cable", "motion picture", "publishing"]),
    ("Consumer Cyclical",      ["retail-apparel", "retail-auto", "retail-eating", "retail-catalog", "hotel", "amusement", "automotive repair"]),
    ("Consumer Defensive",     ["retail-grocery", "retail-drug", "retail-food", "retail-variety", "food and kindred", "beverage", "tobacco", "soap"]),
    ("Industrials",            ["aircraft", "freight", "railroad", "trucking", "courier", "machinery", "construction", "engineering service", "waste"]),
]

_SIC_TO_SECTOR_LOWER = {k.lower(): v for k, v in _SIC_TO_SECTOR.items()}
_unknown_sic_descriptions = set()


def sic_to_sector(sic_description):
    if not sic_description:
        return "Unknown"
    lower = sic_description.lower()
    sector = _SIC_TO_SECTOR_LOWER.get(lower)
    if sector:
        return sector
    for sec, keywords in _SIC_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return sec
    _unknown_sic_descriptions.add(sic_description)
    return "Unknown"


# =========================
# INDEX LIST MANAGEMENT
# =========================

def fetch_index_tickers(url):
    # Slickcharts columns: #, Company, Symbol, Weight, Price, Chg, % Chg.
    # Delisted/renamed constituents (e.g. SATS→ECHO ticker change, Jun 2026) can linger
    # in the table at 0.00% weight for days after the actual index removal — skip them
    # rather than trusting the row's mere presence.
    try:
        response = requests.get(url, headers=SCRAPE_HEADERS, timeout=30)
        if response.status_code != 200:
            print(f"Failed to fetch {url}: HTTP {response.status_code}")
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table")
        if not table:
            return []
        symbols = []
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) > 3:
                symbol = cols[2].text.strip()
                weight_str = cols[3].text.strip().rstrip("%")
                try:
                    weight = float(weight_str)
                except ValueError:
                    weight = None
                if weight is not None and weight <= 0:
                    print(f"  Skipping {symbol}: 0% weight on {url} (stale/delisted listing)")
                    continue
                if symbol:
                    symbols.append(symbol)
        return symbols
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []


def update_and_detect_changes():
    sp500_path     = os.path.join(DATA_DIR, "sp500_symbols.txt")
    nasdaq100_path = os.path.join(DATA_DIR, "nasdaq100_symbols.txt")

    old_sp500, old_nasdaq100 = set(), set()
    if os.path.exists(sp500_path):
        with open(sp500_path) as f:
            old_sp500 = {line.strip() for line in f if line.strip()}
    if os.path.exists(nasdaq100_path):
        with open(nasdaq100_path) as f:
            old_nasdaq100 = {line.strip() for line in f if line.strip()}

    new_sp500_raw     = fetch_index_tickers("https://www.slickcharts.com/sp500")
    new_nasdaq100_raw = fetch_index_tickers("https://www.slickcharts.com/nasdaq100")

    if not new_sp500_raw:
        print("Warning: could not fetch S&P 500 from web, using cached list")
        new_sp500_raw = sorted(old_sp500)
    if not new_nasdaq100_raw:
        print("Warning: could not fetch Nasdaq-100 from web, using cached list")
        new_nasdaq100_raw = sorted(old_nasdaq100)

    # Apply known ticker renames before diffing — see TICKER_RENAMES above.
    new_sp500_raw     = [TICKER_RENAMES.get(t, t) for t in new_sp500_raw]
    new_nasdaq100_raw = [TICKER_RENAMES.get(t, t) for t in new_nasdaq100_raw]

    new_sp500     = set(new_sp500_raw)
    new_nasdaq100 = set(new_nasdaq100_raw)

    with open(sp500_path, "w") as f:
        for s in sorted(new_sp500_raw):
            f.write(s + "\n")
    with open(nasdaq100_path, "w") as f:
        for s in sorted(new_nasdaq100_raw):
            f.write(s + "\n")

    print(f"Index lists updated: {len(new_sp500)} S&P 500, {len(new_nasdaq100)} Nasdaq-100")

    if not old_sp500 and not old_nasdaq100:
        return new_sp500_raw, new_nasdaq100_raw, None

    changes = {
        "date": DATE_STR,
        "sp500":    {"added": sorted(new_sp500 - old_sp500),     "removed": sorted(old_sp500 - new_sp500)},
        "nasdaq100":{"added": sorted(new_nasdaq100 - old_nasdaq100), "removed": sorted(old_nasdaq100 - new_nasdaq100)},
    }
    has_changes = any(
        changes[k][d]
        for k in ("sp500", "nasdaq100")
        for d in ("added", "removed")
    )
    return new_sp500_raw, new_nasdaq100_raw, (changes if has_changes else None)


ROUNDTRIP_LOOKBACK_DAYS = 3


def _cancel_roundtrips(changes_entry, entries):
    cutoff = datetime.now() - timedelta(days=ROUNDTRIP_LOOKBACK_DAYS)
    for idx_name in ("sp500", "nasdaq100"):
        new_added   = set(changes_entry[idx_name].get("added",   []))
        new_removed = set(changes_entry[idx_name].get("removed", []))
        for entry in entries:
            try:
                entry_date = datetime.strptime(entry["date"], "%Y-%m-%d")
            except Exception:
                continue
            if entry_date < cutoff:
                continue
            prev_added   = set(entry[idx_name].get("added",   []))
            prev_removed = set(entry[idx_name].get("removed", []))
            flip_back_add    = new_added   & prev_removed
            flip_back_remove = new_removed & prev_added
            if flip_back_add or flip_back_remove:
                print(
                    f"Round-trip glitch detected in {idx_name} "
                    f"(original entry {entry['date']}): "
                    f"suppressing {sorted(flip_back_add | flip_back_remove)}"
                )
                new_added   -= flip_back_add
                new_removed -= flip_back_remove
                entry[idx_name]["added"]   = sorted(prev_added   - flip_back_remove)
                entry[idx_name]["removed"] = sorted(prev_removed - flip_back_add)
        changes_entry[idx_name]["added"]   = sorted(new_added)
        changes_entry[idx_name]["removed"] = sorted(new_removed)

    entries = [
        e for e in entries
        if any(e[k].get("added") or e[k].get("removed") for k in ("sp500", "nasdaq100"))
    ]
    has_content = any(
        changes_entry[k].get("added") or changes_entry[k].get("removed")
        for k in ("sp500", "nasdaq100")
    )
    return (changes_entry if has_content else None), entries


def load_update_index_changes(changes_entry):
    path = os.path.join(DATA_DIR, "index_changes.json")
    existing = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    entries       = existing.get("entries", [])
    tracked_since = existing.get("trackedSince", DATE_STR)

    if changes_entry is not None:
        changes_entry, entries = _cancel_roundtrips(changes_entry, entries)
    if changes_entry is not None:
        entries.insert(0, changes_entry)
        print(f"Index change recorded: {changes_entry}")

    data = {"trackedSince": tracked_since, "lastChecked": DATE_STR, "entries": entries}
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return data


def cleanup_old_archives():
    cutoff  = datetime.now() - timedelta(days=7)
    pattern = os.path.join(ARCHIVE_DIR, "results_*.csv")
    for filepath in glob.glob(pattern):
        fname = os.path.basename(filepath)
        try:
            file_date = datetime.strptime(fname.replace("results_", "").replace(".csv", ""), "%Y-%m-%d")
            if file_date < cutoff:
                os.remove(filepath)
                print(f"Deleted old archive: {fname}")
        except Exception:
            pass


_NEWS_DEDUP_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "to", "for", "on", "in", "of", "and", "or", "at", "by", "with", "from",
    "today", "here", "here's", "what", "why", "how", "as", "it", "its",
    "this", "that", "will", "you", "your", "s", "amp",
}


def _news_dedup_tokens(title):
    """Normalizes a headline into a set of significant words for near-duplicate detection —
    same idea as the exact-match dedup already used elsewhere, just fuzzy: strips punctuation
    and numbers (dates/years vary between otherwise-identical wire-style stories) and drops
    stopwords, so 'Is the stock market open today, July 3?' and 'Is stock market closed today?
    Why you can't trade July 4' collapse to the same core token set."""
    words = re.findall(r"[a-z]+", title.lower())
    return {w for w in words if w not in _NEWS_DEDUP_STOPWORDS and len(w) > 1}


# Recurring low-diversity story templates that many outlets all run near-simultaneously with
# heavily paraphrased titles (e.g. "market open?" vs "market closed?" for the same holiday) —
# word-overlap similarity alone misses these since the paraphrasing often swaps in literal
# antonyms. Matched title -> a fixed cluster key; any two headlines sharing a key are treated
# as the same story regardless of wording. Extend this list if new recurring templates show up.
_NEWS_TOPIC_PATTERNS = [
    ("market_hours_holiday", re.compile(r"stock market (?:open|close|closed)", re.IGNORECASE)),
]


def _news_topic_key(title):
    for key, pattern in _NEWS_TOPIC_PATTERNS:
        if pattern.search(title):
            return key
    return None


def _dedup_similar_headlines(items, threshold=0.5):
    """Drops near-duplicate headlines, keeping the first (freshest, since Google News RSS
    returns newest-first) occurrence of each story cluster. Two signals: word-overlap (Jaccard)
    similarity on significant terms, and known recurring low-diversity templates (see
    _NEWS_TOPIC_PATTERNS) matched by keyword pattern rather than lexical overlap."""
    kept = []
    kept_tokens = []
    kept_topic_keys = set()
    for it in items:
        topic_key = _news_topic_key(it["title"])
        if topic_key and topic_key in kept_topic_keys:
            continue
        tokens = _news_dedup_tokens(it["title"])
        if tokens and any(
            len(tokens & other) / len(tokens | other) >= threshold for other in kept_tokens
        ):
            continue
        kept.append(it)
        kept_tokens.append(tokens)
        if topic_key:
            kept_topic_keys.add(topic_key)
    return kept


def _fetch_market_news_items(n=6, lang="en"):
    """Fetch top financial headlines from Google News RSS (always the international/English
    feed — same query the /api/market-news CF uses). Returns (fetched_str, items).
    items: [{title, source, link, date}]; when lang="zh" each item also gets a "title_cn"
    translation so the CN briefing shows international coverage instead of Chinese-portal
    results from a Chinese-language RSS query.
    """
    try:
        import urllib.request
        from email.utils import parsedate_to_datetime
        query = "stock+market+OR+%22Federal+Reserve%22+OR+earnings+OR+war+OR+tariff+OR+inflation"
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Baizora/1.0)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
        items = []
        for el in root.iter("item"):
            title = (el.findtext("title") or "").strip()
            source_el = el.find("source")
            source = source_el.text.strip() if source_el is not None and source_el.text else ""
            link = (el.findtext("link") or "").strip()
            pub_date = (el.findtext("pubDate") or "").strip()
            try:
                dt = parsedate_to_datetime(pub_date)
                date_str = dt.strftime("%Y-%m-%d")
            except Exception:
                dt = None
                date_str = ""
            if title:
                items.append({"title": title, "source": source, "link": link, "date": date_str, "_dt": dt})
        # Google News RSS for a broad multi-topic OR query is relevance-ranked, not strictly
        # newest-first (confirmed 2026-07-10: a 07-09 headline showed up after a 07-08 one) —
        # sort explicitly instead of trusting feed order. Items with an unparsable pubDate sort
        # last rather than being placed arbitrarily. Sorted before dedup so "keep first
        # occurrence of a cluster" in _dedup_similar_headlines actually keeps the freshest one,
        # matching that function's own docstring assumption.
        items.sort(key=lambda it: it["_dt"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        for it in items:
            del it["_dt"]
        # Parse every item Google returned (not just the first n) before deduping — the
        # near-duplicate filter needs the full pool so truncating to n afterward doesn't
        # just cut off partway through a cluster of "same story, different outlet" headlines.
        items = _dedup_similar_headlines(items)[:n]
        if lang == "zh":
            _translate_items_to_zh(items)
        et_tz = pytz.timezone("America/New_York")
        fetched = datetime.now(et_tz).strftime("%m/%d/%Y, %I:%M %p ET")
        return fetched, items
    except Exception as e:
        print(f"[digest] news fetch failed: {e}")
        return "", []


def _translate_items_to_zh(items):
    """Adds a "title_cn" field to each item in place via _translate_to_zh (defined further down,
    under INDEX MEMBERSHIP NEWS — same helper used for that feature's headline translation).
    Retries once on failure so a transient network hiccup doesn't leave an English title in the
    CN output."""
    for it in items:
        suffix = f" - {it['source']}" if it["source"] else ""
        clean = it["title"][: -len(suffix)] if suffix and it["title"].endswith(suffix) else it["title"]
        title_cn = ""
        for attempt in range(2):
            try:
                title_cn = _translate_to_zh(clean)
                if title_cn:
                    break
            except Exception:
                pass
            time.sleep(0.3)
        it["title_cn"] = title_cn
        time.sleep(0.08)


def _fetch_market_headlines(n=5, lang="en"):
    """Return news as text lines for the daily briefing .txt file."""
    _, items = _fetch_market_news_items(n, lang)
    return [f"  • {it['title']}" + (f" — {it['source']}" if it['source'] else "") for it in items]


# =========================
# UNIVERSE
# =========================

# Major low-cost/high-volume ETFs tracking the S&P 500 and Nasdaq-100. Hardcoded
# (not scraped) since this list changes rarely, unlike the index constituent lists
# below. These aren't constituents of either index, so they're kept in their own
# set rather than merged into sp_set/nd_set — get_fundamentals() short-circuits
# EDGAR lookups for them (see ETF_TICKERS check there) since ETFs don't file the
# XBRL company-facts data those lookups expect.
ETF_TICKERS = ["VOO", "SPY", "IVV", "SPLG", "QQQ", "QQQM"]
ETF_NAMES = {
    "VOO":  "Vanguard S&P 500 ETF",
    "SPY":  "SPDR S&P 500 ETF Trust",
    "IVV":  "iShares Core S&P 500 ETF",
    "SPLG": "SPDR Portfolio S&P 500 ETF",
    "QQQ":  "Invesco QQQ Trust",
    "QQQM": "Invesco NASDAQ 100 ETF",
}


def get_sp500():
    path = os.path.join(DATA_DIR, "sp500_symbols.txt")
    with open(path) as f:
        return [t.strip().replace(".", "-") for t in f.read().splitlines() if t.strip()]


def get_nasdaq100():
    path = os.path.join(DATA_DIR, "nasdaq100_symbols.txt")
    with open(path) as f:
        return [t.strip().replace(".", "-") for t in f.read().splitlines() if t.strip()]


def get_tickers():
    sp500     = get_sp500()
    nasdaq100 = get_nasdaq100()
    clean   = [t.replace(".", "-") for t in sp500 + nasdaq100 + ETF_TICKERS if isinstance(t, str)]
    tickers = sorted(set(clean))
    sp_set  = {t.replace(".", "-") for t in sp500     if isinstance(t, str)}
    nd_set  = {t.replace(".", "-") for t in nasdaq100 if isinstance(t, str)}
    etf_set = {t.replace(".", "-") for t in ETF_TICKERS if isinstance(t, str)}
    return tickers, sp_set, nd_set, etf_set


# =========================
# TICKER ALIASES
# Tiingo uses lowercase with hyphens (brk-b, bf-b) matching our internal format.
# Only add entries here if Tiingo uses a symbol that differs from our internal one.
# =========================

TICKER_ALIASES = {
    # "BNY": "bny",  # uncomment only if Tiingo still returns BK for Bank of New York Mellon
}

# =========================
# TICKER RENAMES
# A constituent keeps its index membership but changes ticker symbol (company
# rebrand/rename, same legal entity/CIK). Applied to the freshly-scraped
# slickcharts list in update_and_detect_changes() *before* diffing against the
# previous day's list, so the rename never shows up as a misleading "removed
# EQR / added VMRK" index-membership-change item — regardless of whether
# slickcharts itself has already updated its own listing. Remove an entry once
# slickcharts reliably reports the new symbol on its own (no longer needed).
# =========================
TICKER_RENAMES = {
    "EQR": "VMRK",  # Equity Residential -> Vivmark Residential, effective 2026-08-12 (SEC EDGAR CIK 906107)
}

TICKER_SECTOR_OVERRIDE = {
    "ARM":   "Technology",
    "ASML":  "Technology",
    "BF-B":  "Consumer Defensive",
    "BRK-B": "Financial Services",
    "CCEP":  "Consumer Defensive",
    "CTSH":  "Technology",
    "CTVA":  "Basic Materials",
    "FER":   "Industrials",
    "PDD":   "Consumer Cyclical",
    "PKG":   "Basic Materials",
    "PM":    "Consumer Defensive",
    "RL":    "Consumer Cyclical",
    "TRI":   "Communication Services",
    "ABNB":  "Consumer Cyclical",
    "BKNG":  "Consumer Cyclical",
    "CCL":   "Consumer Cyclical",
    "DASH":  "Consumer Cyclical",
    "EBAY":  "Consumer Cyclical",
    "EXPE":  "Consumer Cyclical",
    "MELI":  "Consumer Cyclical",
    "NCLH":  "Consumer Cyclical",
    "POOL":  "Consumer Cyclical",
    "RCL":   "Consumer Cyclical",
    "UBER":  "Consumer Cyclical",
    "CPAY":  "Financial Services",
    "FIS":   "Financial Services",
    "FISV":  "Financial Services",
    "GPN":   "Financial Services",
    "MA":    "Financial Services",
    "MSCI":  "Financial Services",
    "PYPL":  "Financial Services",
    "V":     "Financial Services",
    "ACN":   "Technology",
    "AKAM":  "Technology",
    "CSGP":  "Real Estate",
    "FICO":  "Technology",
    "GLW":   "Technology",
    "GRMN":  "Technology",
    "IT":    "Technology",
    "KEYS":  "Technology",
    "LRCX":  "Technology",
    "TRMB":  "Technology",
    "ZBRA":  "Technology",
    "DHR":   "Healthcare",
    "TMO":   "Healthcare",
    "AMCR":  "Basic Materials",
}

def _load_split_guards():
    """Load split_guards.csv and return all rows as list of dicts. No pruning at load time."""
    import csv
    if not os.path.exists(SPLIT_GUARDS_FILE):
        return []
    with open(SPLIT_GUARDS_FILE, newline="") as f:
        return list(csv.DictReader(f))

def _prune_split_guards():
    """Remove guards that no longer fired this EDGAR run AND are past earliest_remove.
    Called after a full EDGAR fetch (not on SKIP_EDGAR runs). A guard that didn't fire
    means EDGAR now reports post-split values — safe to drop. If EDGAR stops filing,
    the guard keeps firing and is never removed."""
    import csv
    today = DATE_STR
    to_keep = []
    removed = []
    for r in _SPLIT_GUARDS:
        ticker = r["ticker"]
        if today >= r["earliest_remove"] and ticker not in _SPLIT_GUARDS_FIRED:
            removed.append(ticker)
        else:
            to_keep.append(r)
    if removed:
        print(f"[split_guards] Condition-healed, removing: {removed}")
        with open(SPLIT_GUARDS_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["ticker","direction","ratio","action_date","earliest_remove","shares_threshold","eps_threshold"])
            writer.writeheader()
            writer.writerows(to_keep)

_SPLIT_GUARDS = _load_split_guards()
_SPLIT_GUARDS_BY_TICKER = {r["ticker"]: r for r in _SPLIT_GUARDS}
_SPLIT_GUARDS_FIRED = set()   # populated during EDGAR fetch; used by _prune_split_guards()


# Shares outstanding overrides for tickers where EDGAR only reports one share class
# but total economic units are larger (LP/LLC units, multi-class structures).
# BRK-B excluded (own special case). GOOG/GOOGL excluded (EDGAR covers both classes).
def _make_shares_lambda(direction, ratio, threshold):
    ratio = int(ratio)
    threshold = int(threshold)
    if direction == "forward":
        return lambda s: (s or 0) * ratio if (s or 0) < threshold else s
    else:
        return lambda s: (s or 0) // ratio if (s or 0) > threshold else s

SHARES_OUTSTANDING_OVERRIDE = {
    "IBKR": 1_697_000_000,  # permanent: Class A 445M + IBG LLC membership units (~75% private stake)
    "BX":   1_222_000_000,  # permanent: Class A 742M + Blackstone Holdings LP units
    # Conditional (lambda): uses override only while EDGAR lags; auto-heals once 10-Q is filed
    "DVN":  lambda s: 1_153_000_000 if (s or 0) < 800_000_000 else s,  # Coterra merger May 2026; EDGAR pre-merger ~621M; heals after Q2 2026 10-Q
    **{
        r["ticker"]: _make_shares_lambda(r["direction"], r["ratio"], r["shares_threshold"])
        for r in _SPLIT_GUARDS
        if r.get("shares_threshold")
    },
}


# =========================
# TIINGO OHLCV CACHE (per-ticker)
# Each ticker gets its own JSON file: ohlcv_tiingo_cache/AAPL.json
# Format: {"ticker": "AAPL", "updated": "2026-06-06", "bars": {"2024-01-02": {o,h,l,c,v}, ...}}
# =========================

def _cache_path(ticker):
    cache_dir = YF_OHLCV_CACHE_DIR if USE_YFINANCE else OHLCV_CACHE_DIR
    return os.path.join(cache_dir, f"{ticker}.json")


def _load_ticker_bars(ticker):
    """Return {date_str: {o,h,l,c,v}} from disk cache, or {}."""
    path = _cache_path(ticker)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("bars", {})
    except Exception:
        return {}


def _save_ticker_bars(ticker, bars):
    path = _cache_path(ticker)
    with open(path, "w") as f:
        json.dump({"ticker": ticker, "updated": DATE_STR, "bars": bars}, f)


def _trim_old_bars(bars, cutoff_date_str):
    """Remove bars older than cutoff to keep file sizes bounded."""
    return {d: v for d, v in bars.items() if d >= cutoff_date_str}


def fetch_ticker_history(ticker, from_date):
    """
    Fetch full OHLCV history for one ticker from Tiingo.
    Returns list of (date_str, {o,h,l,c,v}).
    """
    tiingo_ticker = _to_tiingo_ticker(TICKER_ALIASES.get(ticker, ticker))
    data = _tiingo_get(
        f"/tiingo/daily/{tiingo_ticker}/prices",
        params={"startDate": from_date, "resampleFreq": "daily"},
    )
    if not data:
        return []
    result = []
    for bar in data:
        d = _parse_tiingo_date(bar.get("date", ""))
        if not d:
            continue
        o = bar.get("adjOpen")   if bar.get("adjOpen")   is not None else bar.get("open")
        h = bar.get("adjHigh")   if bar.get("adjHigh")   is not None else bar.get("high")
        l = bar.get("adjLow")    if bar.get("adjLow")    is not None else bar.get("low")
        c = bar.get("adjClose")  if bar.get("adjClose")  is not None else bar.get("close")
        v = bar.get("adjVolume") if bar.get("adjVolume") is not None else bar.get("volume")
        if c is not None and v is not None:
            result.append((d, {
                "o": round(float(o), 4) if o is not None else None,
                "h": round(float(h), 4) if h is not None else None,
                "l": round(float(l), 4) if l is not None else None,
                "c": round(float(c), 4),
                "v": float(v),
            }))
    return result


def fetch_bulk_latest(tickers):
    """
    Fetch latest EOD for all universe tickers via one bulk Tiingo call.
    Returns {internal_ticker: {date, o,h,l,c,v}}.
    """
    tiingo_tickers = [_to_tiingo_ticker(TICKER_ALIASES.get(t, t)) for t in tickers]
    # Build reverse map: tiingo_lower → internal
    tiingo_to_internal = {_to_tiingo_ticker(TICKER_ALIASES.get(t, t)): t for t in tickers}

    data = _tiingo_get("/tiingo/daily/prices", params={"tickers": ",".join(tiingo_tickers)})
    if not data:
        return {}

    out = {}
    for bar in data:
        tiingo_tk = (bar.get("ticker") or "").lower()
        internal  = tiingo_to_internal.get(tiingo_tk)
        if not internal:
            continue
        d = _parse_tiingo_date(bar.get("date", ""))
        o = bar.get("adjOpen")   if bar.get("adjOpen")   is not None else bar.get("open")
        h = bar.get("adjHigh")   if bar.get("adjHigh")   is not None else bar.get("high")
        l = bar.get("adjLow")    if bar.get("adjLow")    is not None else bar.get("low")
        c = bar.get("adjClose")  if bar.get("adjClose")  is not None else bar.get("close")
        v = bar.get("adjVolume") if bar.get("adjVolume") is not None else bar.get("volume")
        if c is not None and v is not None and d:
            out[internal] = {
                "date": d,
                "o": round(float(o), 4) if o is not None else None,
                "h": round(float(h), 4) if h is not None else None,
                "l": round(float(l), 4) if l is not None else None,
                "c": round(float(c), 4),
                "v": float(v),
            }
    return out




def get_trading_days(from_date, to_date):
    days    = []
    current = datetime.strptime(from_date, "%Y-%m-%d").date()
    end     = datetime.strptime(to_date,   "%Y-%m-%d").date()
    while current <= end:
        if current.weekday() < 5 and not is_market_holiday(current):
            days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


SPLITS_PATH = os.path.join(DATA_DIR, "splits.json")

def update_splits_file(tickers, lookback_days=180, sleep_time=0.1):
    """
    Detect forward splits by scanning Tiingo daily price history for splitFactor != 1.0.
    splitFactor is a field in /tiingo/daily/{ticker}/prices — no separate splits endpoint exists.
    """
    lookback_start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    splits = {}
    print(f"Scanning split history for {len(tickers)} tickers since {lookback_start} …")
    for i, ticker in enumerate(tickers, 1):
        tiingo_tk = _to_tiingo_ticker(TICKER_ALIASES.get(ticker, ticker))
        data = _tiingo_get(f"/tiingo/daily/{tiingo_tk}/prices",
                           params={"startDate": lookback_start})
        if isinstance(data, list):
            for bar in data:
                factor = bar.get("splitFactor")
                if factor is None or float(factor) == 1.0:
                    continue
                d = _parse_tiingo_date(bar.get("date", ""))
                if not d:
                    continue
                ratio = float(factor)
                if 0 < ratio < 1:
                    ratio = 1 / ratio
                ratio = round(ratio)
                if ratio >= 2:
                    if ticker not in splits or d > splits[ticker]["date"]:
                        splits[ticker] = {"ratio": ratio, "date": d}
        if i % 100 == 0:
            print(f"  … splits {i}/{len(tickers)}")
        time.sleep(sleep_time)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SPLITS_PATH, "w") as f:
        json.dump(splits, f, indent=2)
    print(f"splits.json written: {len(splits)} split(s) found in last {lookback_days} days.")
    return splits


# =========================
# yfinance OHLCV fetch (OHLCV_SOURCE=yfinance only) — ported from scanner_yfinance.py's
# fetch_yfinance_bulk rather than imported, so the two scanner scripts stay independent
# (matches the existing convention: neither file imports the other).
# =========================

YF_CHUNK_SIZE  = 60
YF_MAX_RETRIES = 3
YF_RETRY_WAITS = [5, 15, 45]
YF_CHUNK_DELAY = 2


def fetch_yfinance_bulk(tickers, period="2y"):
    """
    Fetch daily OHLCV for all tickers via yfinance, chunked with retry/backoff
    (Yahoo throttles high-volume scraping). auto_adjust=True means yfinance handles
    split/dividend adjustment itself — update_splits_file (Tiingo-specific) is
    skipped entirely in this mode, see scan(). Returns {ticker: {date_str: {o,h,l,c,v}}}.
    """
    all_bars = {}
    chunks = [tickers[i:i + YF_CHUNK_SIZE] for i in range(0, len(tickers), YF_CHUNK_SIZE)]

    for ci, chunk in enumerate(chunks, 1):
        data = None
        for attempt in range(YF_MAX_RETRIES):
            try:
                data = yf.download(
                    tickers=chunk, period=period, group_by="ticker",
                    auto_adjust=True, threads=False, progress=False,
                )
                break
            except Exception as e:
                wait = YF_RETRY_WAITS[min(attempt, len(YF_RETRY_WAITS) - 1)]
                print(f"  chunk {ci}/{len(chunks)} attempt {attempt+1} failed: {e}; retrying in {wait}s")
                time.sleep(wait)

        if data is None or data.empty:
            print(f"  chunk {ci}/{len(chunks)} failed after {YF_MAX_RETRIES} attempts — skipping {len(chunk)} tickers")
            time.sleep(YF_CHUNK_DELAY)
            continue

        is_multi = isinstance(data.columns, pd.MultiIndex)
        for ticker in chunk:
            try:
                if is_multi:
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    sub = data[ticker]
                else:
                    sub = data
                sub = sub.dropna(subset=["Close"])
                if sub.empty:
                    continue
                bars = {}
                idx = sub.index
                if getattr(idx, "tz", None) is not None:
                    idx = idx.tz_localize(None)
                for ts, row in zip(idx, sub.itertuples(index=False)):
                    d = ts.strftime("%Y-%m-%d")
                    close = getattr(row, "Close", None)
                    if close is None or pd.isna(close):
                        continue
                    bars[d] = {
                        "o": round(float(row.Open), 4) if pd.notna(getattr(row, "Open", None)) else None,
                        "h": round(float(row.High), 4) if pd.notna(getattr(row, "High", None)) else None,
                        "l": round(float(row.Low),  4) if pd.notna(getattr(row, "Low",  None)) else None,
                        "c": round(float(close), 4),
                        "v": float(row.Volume) if pd.notna(getattr(row, "Volume", None)) else 0.0,
                    }
                if bars:
                    all_bars[ticker] = bars
            except Exception as e:
                print(f"  {ticker}: parse error {e}")

        print(f"  chunk {ci}/{len(chunks)} done ({len(chunk)} tickers)")
        time.sleep(YF_CHUNK_DELAY)

    return all_bars


def fetch_yfinance_benchmark(from_date, to_date):
    """yfinance-mode replacement for the Tiingo SPY fetch used for beta calc."""
    try:
        hist = yf.Ticker("SPY").history(start=from_date, end=to_date, auto_adjust=True)
        if hist is None or hist.empty:
            return None
        hist = hist.reset_index()
        hist["Date"] = pd.to_datetime(hist["Date"])
        if hist["Date"].dt.tz is not None:
            hist["Date"] = hist["Date"].dt.tz_localize(None)
        return hist[["Date", "Close"]].sort_values("Date").reset_index(drop=True)
    except Exception as e:
        print(f"yfinance SPY fetch failed: {e}")
        return None


def build_ohlcv_cache_yfinance(tickers, from_date):
    """yfinance-mode equivalent of build_ohlcv_cache — full re-fetch each run (yfinance
    has no cheap 'just today's bar' bulk endpoint like Tiingo's /tiingo/daily/prices, so
    there's no separate initial-vs-bulk-latest split here)."""
    cutoff_str = from_date
    print(f"OHLCV cache (yfinance): fetching {len(tickers)} tickers …")
    fetched = fetch_yfinance_bulk(tickers, period="5y")
    updated = 0
    for ticker in tickers:
        bars = fetched.get(ticker)
        if not bars:
            continue
        bars = _trim_old_bars(bars, cutoff_str)
        _save_ticker_bars(ticker, bars)
        updated += 1
    print(f"OHLCV cache (yfinance) updated: {updated}/{len(tickers)} tickers.")
    missing_after = [t for t in tickers if not os.path.exists(_cache_path(t))]
    if missing_after:
        print(f"WARNING: {len(missing_after)} tickers still have no cache file after build.")


def build_ohlcv_cache(tickers, from_date, sleep_time=0.15):
    """
    Ensure every ticker has an up-to-date per-ticker cache file.
    1. Initial fetch for tickers with no cache file (full ~5Y history, one call each).
    2. Bulk latest call for all tickers to add today's EOD.
    """
    if USE_YFINANCE:
        build_ohlcv_cache_yfinance(tickers, from_date)
        return

    cutoff_str = from_date  # trim bars older than the ~5Y lookback

    missing = [t for t in tickers if not os.path.exists(_cache_path(t))]
    if missing:
        print(f"OHLCV cache: initial fetch for {len(missing)} new tickers …")
        for i, ticker in enumerate(missing, 1):
            bars_list = fetch_ticker_history(ticker, from_date)
            bars      = _trim_old_bars({d: b for d, b in bars_list}, cutoff_str)
            _save_ticker_bars(ticker, bars)
            time.sleep(sleep_time)
            if i % 50 == 0:
                print(f"  … initial fetch {i}/{len(missing)}")
        print("Initial OHLCV fetch complete.")

    print("Fetching latest EOD via bulk endpoint …")
    bulk    = fetch_bulk_latest(tickers)
    updated = 0
    for ticker in tickers:
        bar_data = bulk.get(ticker)
        if not bar_data:
            continue
        d    = bar_data.pop("date")
        bars = _load_ticker_bars(ticker)
        if d not in bars:
            bars[d] = bar_data
            bars = _trim_old_bars(bars, cutoff_str)
            _save_ticker_bars(ticker, bars)
            updated += 1
    print(f"OHLCV bulk update: {updated}/{len(tickers)} tickers received new EOD bar.")

    missing_after = [t for t in tickers if not os.path.exists(_cache_path(t))]
    if missing_after:
        print(f"WARNING: {len(missing_after)} tickers still have no cache file after build.")


def load_ohlcv_cache_into_memory(tickers, trading_days):
    """
    Reconstruct {date: {ticker: {o,h,l,c,v}}} from per-ticker cache files.
    Same structure as scanner_massive per-day cache for drop-in compatibility.
    """
    daily_data = {d: {} for d in trading_days}
    for ticker in tickers:
        bars = _load_ticker_bars(ticker)
        for d, bar in bars.items():
            if d in daily_data:
                daily_data[d][ticker] = bar
    return daily_data


def load_ticker_ohlcv(ticker, trading_days, daily_data):
    rows = []
    for day in trading_days:
        bar = daily_data.get(day, {}).get(ticker)
        if bar:
            rows.append({
                "Date":   day,
                "Open":   bar.get("o"),
                "High":   bar.get("h"),
                "Low":    bar.get("l"),
                "Close":  bar["c"],
                "Volume": bar["v"],
            })
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").reset_index(drop=True)


# =========================
# SPY BENCHMARK (via Tiingo)
# =========================

def fetch_benchmark_bars(from_date, to_date):
    data = _tiingo_get(
        "/tiingo/daily/spy/prices",
        params={"startDate": from_date, "endDate": to_date, "resampleFreq": "daily"},
        retries=8,
    )
    if not data:
        return None
    rows = []
    for bar in data:
        d = _parse_tiingo_date(bar.get("date", ""))
        c = bar.get("adjClose") if bar.get("adjClose") is not None else bar.get("close")
        if d and c:
            rows.append({"Date": d, "Close": float(c)})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").reset_index(drop=True)


# =========================
# TIINGO META — company names + market caps (one batch call)
# =========================

def prefetch_tiingo_meta(tickers):
    """
    Fetch company names and market caps for all tickers via Tiingo meta endpoint.
    Returns {internal_ticker: {"name": str, "marketCap": float|None}}.
    """
    tiingo_tickers    = [_to_tiingo_ticker(TICKER_ALIASES.get(t, t)) for t in tickers]
    tiingo_to_internal = {_to_tiingo_ticker(TICKER_ALIASES.get(t, t)): t for t in tickers}

    data = _tiingo_get("/tiingo/daily/meta", params={"tickers": ",".join(tiingo_tickers)})
    if not data:
        print("Warning: Tiingo meta call returned no data — company names will be empty")
        return {}

    # Prefer isActive=True when Tiingo returns multiple rows for the same ticker
    # (e.g. BNY: active=BofNY Mellon AND inactive=old BlackRock fund — keep the active one).
    meta_map = {}
    for row in data:
        t = row.get("ticker", "").lower()
        if t not in meta_map or row.get("isActive", False):
            meta_map[t] = {
                "name":      row.get("name", ""),
                "marketCap": row.get("marketCap"),  # raw dollars, may be None
            }
    result = {}
    for ticker in tickers:
        tiingo_tk      = _to_tiingo_ticker(TICKER_ALIASES.get(ticker, ticker))
        result[ticker] = meta_map.get(tiingo_tk, {"name": "", "marketCap": None})

    found_names = sum(1 for v in result.values() if v.get("name"))
    found_mc    = sum(1 for v in result.values() if v.get("marketCap"))
    print(f"Tiingo meta: {found_names}/{len(tickers)} names, {found_mc}/{len(tickers)} market caps loaded")
    return result


# =========================
# SEC EDGAR — EPS, shares outstanding, SIC description
# =========================

_EDGAR_HEADERS          = {"User-Agent": "Baizora support@baizora.com"}
_edgar_cik_map          = {}
_edgar_name_map         = {}   # ticker → company title from company_tickers.json
_edgar_cik_map_attempted = False

_fx_rates = {}   # ISO currency code → USD conversion factor (e.g. "EUR" → 1.099)


def _load_fx_rates():
    """
    Fetch today's FX rates once per process from the Frankfurter API (ECB daily rates).
    Populates _fx_rates with foreign→USD factors for EUR, CNY, GBP, CAD.
    Called once at the start of prefetch_fundamentals.
    """
    global _fx_rates
    if _fx_rates:
        return
    _fx_rates["USD"] = 1.0   # baseline; set early so partial failure still handles USD
    try:
        r = requests.get(
            "https://api.frankfurter.app/latest?from=USD&to=EUR,CNY,GBP,CAD",
            headers=_EDGAR_HEADERS, timeout=10,
        )
        r.raise_for_status()
        rates = r.json().get("rates", {})   # USD → foreign
        for ccy, usd_per_foreign in {k: 1.0 / v for k, v in rates.items() if v}.items():
            _fx_rates[ccy.upper()] = usd_per_foreign
        print(f"FX rates loaded: { {k: round(v,4) for k,v in _fx_rates.items()} }")
    except Exception as e:
        print(f"FX rates fetch failed: {e} — non-USD EPS will be null")


def _load_edgar_cik_map():
    global _edgar_cik_map, _edgar_name_map, _edgar_cik_map_attempted
    if _edgar_cik_map_attempted:
        return
    _edgar_cik_map_attempted = True
    for url in [
        "https://www.sec.gov/files/company_tickers.json",
        "https://data.sec.gov/files/company_tickers.json",
    ]:
        try:
            resp = requests.get(url, headers=_EDGAR_HEADERS, timeout=15)
            resp.raise_for_status()
            raw = resp.json()
            _edgar_cik_map  = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}
            _edgar_name_map = {v["ticker"].upper(): v.get("title", "") for v in raw.values()}
            print(f"EDGAR: {len(_edgar_cik_map)} ticker->CIK mappings loaded")
            return
        except Exception as e:
            print(f"EDGAR: failed ({url}): {e}")
    print("EDGAR: CIK map unavailable — EPS/shares will be skipped")


def _period_days(entry):
    try:
        return (datetime.strptime(entry["end"], "%Y-%m-%d") -
                datetime.strptime(entry["start"], "%Y-%m-%d")).days
    except Exception:
        return 999


def _derive_quarterly_eps(entries):
    """
    Convert 10-Q EPS entries to true quarterly values.
    Many filers report YTD cumulative EPS; this derives incremental quarters by differencing.
    Returns list of (end_date, quarterly_val) sorted newest-first.
    """
    seen, deduped = set(), []
    # Prefer individual quarterly entries (period≈90d) over YTD cumulative entries when
    # a company files both for the same end date (e.g. VRSN files H1=$4.31 AND Q2=$2.21
    # with end=2025-06-30). -abs(period-90) is 0 for true quarters and negative for YTD.
    for x in sorted(entries, key=lambda x: (x.get("end",""), x.get("filed",""), -abs(_period_days(x) - 90)), reverse=True):
        if x.get("end") not in seen:
            seen.add(x.get("end"))
            deduped.append(x)

    deduped.sort(key=lambda x: x.get("end",""))
    quarters = []
    for start_date, group in groupby(deduped, key=lambda x: x.get("start","")):
        year_entries = sorted(list(group), key=lambda x: x.get("end",""))
        prev_ytd = 0.0
        for entry in year_entries:
            days = _period_days(entry)
            if days < 100:
                quarters.append((entry["end"], entry["val"]))
                prev_ytd = entry["val"]
            else:
                quarterly_val = entry["val"] - prev_ytd
                quarters.append((entry["end"], quarterly_val))
                prev_ytd = entry["val"]

    quarters.sort(key=lambda x: x[0], reverse=True)
    return quarters


def _get_edgar_fundamentals(ticker):
    """
    Fetch EPS, shares outstanding, and SIC description from SEC EDGAR.
    Two EDGAR calls per new ticker (company_facts + submissions); results are disk-cached.
    Returns (eps, shares_outstanding, sic_description).
    """
    _load_edgar_cik_map()

    cik = None
    for variant in [ticker, ticker.replace("-", "."), ticker.replace("-", "")]:
        cik = _edgar_cik_map.get(variant.upper())
        if cik:
            break
    if not cik:
        return None, None, "", "", ""

    eps                = None
    shares_outstanding = None
    shares_filed_date  = ""
    sic_description    = ""

    # --- company_facts: EPS + shares outstanding ---
    try:
        resp = requests.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            headers=_EDGAR_HEADERS, timeout=15,
        )
        resp.raise_for_status()
        facts   = resp.json().get("facts", {})
        us_gaap = facts.get("us-gaap", {})
        dei     = facts.get("dei", {})

        # Shares outstanding — priority order:
        #   1. DEI EntityCommonStockSharesOutstanding (most precise, period-end)
        #   2. CommonStockSharesOutstanding (us-gaap, period-end)
        #   3. Inline XBRL from latest 10-Q/10-K cover page (period-end; better than
        #      weighted avg for market cap — handles CVNA 109M→219M, IBKR 435M→445M)
        #   4. WeightedAverageBasic (last resort; TTM average, ok but not ideal for mktcap)
        # Require filing within 2 years to reject stale entries (e.g. IBKR DEI from 2011).
        _two_yrs_ago = (date.today() - timedelta(days=2 * 365)).isoformat()
        _all_share_entries = (
            dei.get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
            + us_gaap.get("CommonStockSharesOutstanding", {}).get("units", {}).get("shares", [])
        )
        recent_shares = sorted(
            [
                x for x in _all_share_entries
                if x.get("val") and x.get("val") >= 1_000_000
                and x.get("filed") and x["filed"] >= _two_yrs_ago
            ],
            key=lambda x: x.get("filed", ""),
            reverse=True,
        )
        if recent_shares:
            shares_outstanding = int(recent_shares[0]["val"])
            shares_filed_date  = recent_shares[0].get("filed", "")

        # If DEI/CommonStock are stale or empty, try inline XBRL (period-end, more
        # accurate than weighted average for current market cap).
        if shares_outstanding is None:
            shares_outstanding, shares_filed_date = _parse_shares_from_latest_filing(cik)

        # Last resort: weighted average (TTM, not period-end, but better than nothing).
        if shares_outstanding is None:
            wtd_src = us_gaap.get("WeightedAverageNumberOfSharesOutstandingBasic", {}).get("units", {}).get("shares", [])
            if wtd_src:
                recent_shares = sorted(
                    [
                        x for x in wtd_src
                        if x.get("val") and x.get("val") >= 1_000_000
                        and x.get("filed") and x["filed"] >= _two_yrs_ago
                    ],
                    key=lambda x: x.get("filed", ""),
                    reverse=True,
                )
                if recent_shares:
                    shares_outstanding = int(recent_shares[0]["val"])
                    shares_filed_date  = recent_shares[0].get("filed", "")

        # EPS (diluted-first; same algorithm as scanner_massive.py)
        EPS_FIELDS = (
            "EarningsPerShareDiluted",
            "EarningsPerShareBasic",
            "EarningsPerShareBasicAndDiluted",   # used by PDD Holdings and some other filers
            "IncomeLossFromContinuingOperationsPerDilutedShare",
            "IncomeLossFromContinuingOperationsPerBasicShare",
        )
        min_annual_end = str(date.today().year - 2)
        best_annual    = None

        for field in EPS_FIELDS:
            units = us_gaap.get(field, {}).get("units", {}).get("USD/shares", [])
            if not units:
                continue

            q10_entries = [x for x in units if x.get("form") == "10-Q"
                           and x.get("start") and x.get("end")
                           and x.get("end", "") >= min_annual_end]
            q10_entries_all = [x for x in units if x.get("form") == "10-Q"
                               and x.get("start") and x.get("end")]
            annual_entries = sorted(
                [x for x in units if x.get("form") in ("10-K", "10-K405")
                 and x.get("end", "") >= min_annual_end],
                key=lambda x: x.get("end", ""), reverse=True,
            )

            if q10_entries:
                quarters = _derive_quarterly_eps(q10_entries)
                if annual_entries and len(quarters) >= 1:
                    annual_end = annual_entries[0]["end"]
                    annual_val = annual_entries[0]["val"]
                    recent_end, recent_val = quarters[0]
                    # Preferred path: TTM = annual + (recent_Q - year_ago_Q).
                    # Only use when exactly 1 quarter has been reported since the annual
                    # (~50–120 days), so the formula is mathematically correct.
                    # More robust than the q3_candidates path because it avoids the
                    # inconsistent 9M YTD value (e.g. TPL where Q1+Q2+Q3 ≠ 9M YTD).
                    if recent_end > annual_end:
                        days_since = (date.fromisoformat(recent_end) - date.fromisoformat(annual_end)).days
                        if 50 <= days_since <= 120:
                            year_ago_end = f"{int(recent_end[:4]) - 1}{recent_end[4:]}"
                            year_ago = next((q for q in quarters if q[0] == year_ago_end), None)
                            if year_ago:
                                eps = round(annual_val + recent_val - year_ago[1], 4)
                                break
                if annual_entries and len(quarters) >= 3:
                    annual_end = annual_entries[0]["end"]
                    annual_val = annual_entries[0]["val"]
                    q3_candidates = sorted(
                        [x for x in q10_entries_all
                         if 200 < _period_days(x) < 310 and x.get("end", "") < annual_end],
                        key=lambda x: x.get("end", ""), reverse=True,
                    )
                    if q3_candidates:
                        q4_val = annual_val - q3_candidates[0]["val"]
                        eps    = round(sum(v for _, v in quarters[:3]) + q4_val, 4)
                        break
                if len(quarters) >= 4:
                    eps = round(sum(v for _, v in quarters[:4]), 4)
                    break

            if annual_entries:
                if best_annual is None or annual_entries[0]["end"] > best_annual["end"]:
                    best_annual = annual_entries[0]

        if eps is None and best_annual:
            eps = round(float(best_annual["val"]), 4)

    except Exception:
        pass

    # Inline XBRL fallback: used when company_facts has no EPS data.
    # Handles US GAAP filers (e.g. Visa) via 10-Q/10-K TTM, and IFRS filers
    # (CCEP, ASML, FER, TRI, PDD) via annual 20-F/40-F (annual EPS, non-USD currency).
    if eps is None:
        eps = _parse_eps_from_latest_filing(cik)
        if eps is not None:
            print(f"  {ticker}: EPS from inline XBRL fallback = {eps}")

    # --- submissions: SIC description + company name ---
    edgar_company_name = ""
    try:
        resp = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=_EDGAR_HEADERS, timeout=15,
        )
        resp.raise_for_status()
        sub                = resp.json()
        sic_description    = sub.get("sicDescription", "") or ""
        edgar_company_name = sub.get("name", "") or ""
    except Exception:
        pass

    # Special-case adjustments
    if ticker == "BRK-B" and eps is not None:
        eps = round(eps / 1500, 4)

    # Split EPS + shares guards — driven by data/split_guards.csv; condition-based auto-removal
    if ticker in _SPLIT_GUARDS_BY_TICKER:
        g = _SPLIT_GUARDS_BY_TICKER[ticker]
        ratio = int(g["ratio"])
        direction = g["direction"]
        # EPS guard
        if eps is not None and g.get("eps_threshold"):
            eps_thr = float(g["eps_threshold"])
            if direction == "forward" and eps > eps_thr:
                eps = round(eps / ratio, 4)
                _SPLIT_GUARDS_FIRED.add(ticker)
            elif direction == "reverse" and abs(eps) < eps_thr:
                eps = round(eps * ratio, 4)
                _SPLIT_GUARDS_FIRED.add(ticker)
        # Shares condition check (guard applied via SHARES_OUTSTANDING_OVERRIDE lambda)
        if shares_outstanding is not None and g.get("shares_threshold"):
            s_thr = int(g["shares_threshold"])
            if direction == "forward" and shares_outstanding < s_thr:
                _SPLIT_GUARDS_FIRED.add(ticker)
            elif direction == "reverse" and shares_outstanding > s_thr:
                _SPLIT_GUARDS_FIRED.add(ticker)

    # ADS ratio corrections: EDGAR reports per ordinary share; Tiingo prices are per ADS.
    # Divide shares by ratio → market cap = (ordinary_shares / ratio) × ADS_price.
    # Multiply EPS by ratio → PE = ADS_price / (ordinary_EPS × ratio).
    _ADS_RATIOS = {"PDD": 4}   # 1 PDD ADS = 4 ordinary shares
    if ticker in _ADS_RATIOS:
        ratio = _ADS_RATIOS[ticker]
        if shares_outstanding is not None:
            shares_outstanding = shares_outstanding // ratio
        if eps is not None:
            eps = round(eps * ratio, 4)

    return eps, shares_outstanding, sic_description, shares_filed_date, edgar_company_name


def _get_post_filing_split_factor(ticker, filing_date_str):
    """
    Query Tiingo's corporate-actions splits endpoint and return the cumulative
    split factor (splitTo/splitFrom) for any forward splits with ex-date AFTER
    filing_date_str (ISO date, e.g. '2026-04-29').

    Tiingo adjusts OHLCV prices retroactively for splits, so if a split happened
    after our EDGAR filing date, our share count is pre-split and must be multiplied
    by this factor to match the price series.
    Returns 1.0 if no post-filing splits are found or the endpoint fails.
    """
    try:
        resp = _tiingo_get(f"/tiingo/corporate-actions/{ticker.lower()}/splits")
        if not resp:
            return 1.0
        factor = 1.0
        for event in resp:
            ex_date = (event.get("exDate") or "")[:10]   # trim to YYYY-MM-DD
            if ex_date > filing_date_str:
                # Skip spin-off / distribution events: Tiingo records them as splits to
                # adjust historical prices, but they don't change share count.
                # Real stock splits have small clean integers (2:1, 3:2); spin-offs use
                # large arbitrary ratios (e.g. FDX Freight spin-off: 1000:1241).
                sf_from = event.get("splitFrom")
                sf_to   = event.get("splitTo")
                if sf_from is not None and sf_to is not None:
                    if max(abs(sf_from), abs(sf_to)) > 20:
                        continue  # spin-off / distribution, not a stock split
                sf = float(event.get("splitFactor") or 1.0)
                factor *= sf
        return factor
    except Exception:
        return 1.0


def _parse_shares_from_latest_filing(cik):
    """
    Fallback: fetch the most recent 10-Q or 10-K inline XBRL document and parse
    dei:EntityCommonStockSharesOutstanding from the cover page.
    Returns (shares, filed_date). Used when company_facts has no recent share data.
    For multi-class structures (e.g. Visa A/B/C), takes the largest value (Class A = market cap basis).
    """
    try:
        import re as _re
        sub = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=_EDGAR_HEADERS, timeout=15,
        )
        sub.raise_for_status()
        recent = sub.json()["filings"]["recent"]
        forms = recent["form"]
        accns  = recent["accessionNumber"]
        dates  = recent.get("filingDate", [""] * len(forms))
        docs   = recent.get("primaryDocument", [""] * len(forms))

        accn = primary_doc = filing_date = None
        for i, form in enumerate(forms):
            if form in ("10-Q", "10-K"):
                accn         = accns[i]
                primary_doc  = docs[i]
                filing_date  = dates[i]
                break

        if not accn or not primary_doc:
            return None, ""

        accn_path = accn.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn_path}/{primary_doc}"
        doc_r = requests.get(url, headers=_EDGAR_HEADERS, timeout=30)
        doc_r.raise_for_status()

        raw = _re.findall(
            r'<ix:nonFraction[^>]*name="dei:EntityCommonStockSharesOutstanding"[^>]*>([^<]+)<',
            doc_r.text,
        )
        # Filter to plausible share counts (≥1M); zero/tiny values (e.g. WDAY) are
        # excluded so the caller falls through to WeightedAverage.
        vals = [int(v.replace(",", "")) for v in raw
                if v.replace(",", "").isdigit() and int(v.replace(",", "")) >= 1_000_000]
        if not vals:
            return None, ""

        # If all values cluster within 2% of each other they are the same share class
        # reported in multiple XBRL contexts (e.g. CME lists Class A twice with
        # slightly different context dates) — take the largest to avoid double-counting.
        # Otherwise they are distinct share classes (e.g. FOXA Class A + Class B) —
        # sum them for total economic shares outstanding.
        if max(vals) / min(vals) < 1.02:
            return max(vals), filing_date or ""
        return sum(vals), filing_date or ""

    except Exception:
        return None, ""


def _parse_eps_from_latest_filing(cik):
    """
    Fallback: extract EPS from inline XBRL in the primary filing documents.
    Called only when company_facts returns no EPS data (e.g. Visa, CCEP).

    US GAAP path  (10-Q / 10-K): builds full TTM from up to 4 quarterly filings
                                  + annual 10-K for Q4 derivation.
    IFRS path     (20-F / 40-F): annual EPS only (no quarterly 20-F filings exist).

    Reporting currency is detected automatically from the XBRL unitRef attribute
    in each filing and converted to USD using _fx_rates (loaded once per scan).
    Returns eps in USD (float) or None.
    """
    try:
        import re as _re

        sub = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=_EDGAR_HEADERS, timeout=15,
        )
        sub.raise_for_status()
        recent  = sub.json()["filings"]["recent"]
        forms   = recent["form"]
        accns   = recent["accessionNumber"]
        docs    = recent.get("primaryDocument", [""] * len(forms))
        periods = recent.get("reportDate",      [""] * len(forms))

        q_filings  = []
        ann_filing = None
        for i, form in enumerate(forms):
            if form == "10-Q" and len(q_filings) < 4:
                q_filings.append((accns[i], docs[i], periods[i]))
            elif form in ("10-K", "10-K405", "20-F", "40-F") and ann_filing is None:
                ann_filing = (accns[i], docs[i], periods[i], form)
            if len(q_filings) >= 4 and ann_filing:
                break

        US_GAAP_TAGS = (
            "us-gaap:EarningsPerShareDiluted",
            "us-gaap:EarningsPerShareBasic",
        )
        IFRS_TAGS = (
            "ifrs-full:DilutedEarningsLossPerShare",
            "ifrs-full:BasicEarningsLossPerShare",
            "ifrs-full:EarningsLossPerShare",
        )

        def _fetch_eps_entries(accn, primary_doc, prefer_ifrs=False):
            """
            Return list of (end_date_str, period_days, value, currency_code).
            Currency is detected from XBRL unit definitions in the filing.
            """
            if not primary_doc:
                return []
            accn_path = accn.replace("-", "")
            url = (f"https://www.sec.gov/Archives/edgar/data/"
                   f"{int(cik)}/{accn_path}/{primary_doc}")
            r = requests.get(url, headers=_EDGAR_HEADERS, timeout=30)
            r.raise_for_status()
            html = r.text

            # Duration contexts: id → (end_date_str, period_days)
            contexts = {}
            for ctx_id, body in _re.findall(
                r'<[^:>]*:context[^>]+id="([^"]+)"[^>]*>(.*?)</[^:>]*:context>',
                html, _re.DOTALL | _re.IGNORECASE,
            ):
                sm = _re.search(r'<[^:>]*:startDate[^>]*>(\d{4}-\d{2}-\d{2})<',
                                body, _re.IGNORECASE)
                em = _re.search(r'<[^:>]*:endDate[^>]*>(\d{4}-\d{2}-\d{2})<',
                                body, _re.IGNORECASE)
                if sm and em:
                    days = (date.fromisoformat(em.group(1))
                            - date.fromisoformat(sm.group(1))).days
                    contexts[ctx_id] = (em.group(1), days)

            # Unit definitions: unit_id → ISO currency code (e.g. "iso4217:EUR" → "EUR")
            unit_map = {}
            for uid, body in _re.findall(
                r'<[^:>]*:unit[^>]+id="([^"]+)"[^>]*>(.*?)</[^:>]*:unit>',
                html, _re.DOTALL | _re.IGNORECASE,
            ):
                m = _re.search(r'iso4217:([A-Z]{3})', body, _re.IGNORECASE)
                if m:
                    unit_map[uid] = m.group(1).upper()

            tag_order = IFRS_TAGS + US_GAAP_TAGS if prefer_ifrs else US_GAAP_TAGS + IFRS_TAGS
            results = []
            for tag in tag_order:
                hits = _re.findall(
                    r'<ix:nonFraction([^>]*\bname="' + _re.escape(tag)
                    + r'"[^>]*)>([\d.,\-\(\)]+)<',
                    html, _re.IGNORECASE,
                )
                for attrs, raw in hits:
                    cm = _re.search(r'\bcontextRef="([^"]+)"', attrs)
                    sm = _re.search(r'\bsign="([^"]+)"',       attrs)
                    um = _re.search(r'\bunitRef="([^"]+)"',    attrs)
                    if not cm or cm.group(1) not in contexts:
                        continue
                    v        = raw.replace(",", "").strip()
                    negative = (sm and sm.group(1) == "-") or (
                        v.startswith("(") and v.endswith(")"))
                    try:
                        val = float(v.strip("()")) * (-1 if negative else 1)
                    except ValueError:
                        continue
                    end_date, days = contexts[cm.group(1)]
                    # Resolve currency: unitRef → unit definition → ISO code
                    currency = "USD"
                    if um:
                        ref = um.group(1)
                        currency = unit_map.get(ref) or (
                            ref.upper() if _re.match(r'^[A-Z]{3}$', ref) else "USD")
                    results.append((end_date, days, val, currency))
                if results:
                    break
            return results

        def _to_usd(val, currency):
            """Convert val to USD using cached FX rates. Returns None if rate missing."""
            rate = _fx_rates.get(currency.upper())
            if rate is None:
                return None
            return val * rate

        # Collect quarterly (~90d) and 9M-YTD (~270d) entries from 10-Qs
        quarterly = {}   # end_date → (val, currency)
        ytd_9m    = {}   # end_date → (val, currency)
        for accn, doc, _ in q_filings:
            for end_date, days, val, ccy in _fetch_eps_entries(accn, doc):
                if 60 < days < 120 and end_date not in quarterly:
                    quarterly[end_date] = (val, ccy)
                elif 200 < days < 310 and end_date not in ytd_9m:
                    ytd_9m[end_date] = (val, ccy)

        quarters = sorted(quarterly.items(), reverse=True)  # newest first

        ann_entries = None

        def _get_ann_entries():
            nonlocal ann_entries
            if ann_entries is None and ann_filing:
                prefer = ann_filing[3] in ("20-F", "40-F")
                ann_entries = _fetch_eps_entries(ann_filing[0], ann_filing[1],
                                                 prefer_ifrs=prefer)
            return ann_entries or []

        def _best_ann_hit():
            # Sort by end_date desc, then prefer USD over CNY (avoids FX conversion noise).
            # 20-F comparative tables list oldest year first; without sorting we'd pick FY-2.
            entries = sorted(_get_ann_entries(),
                             key=lambda x: (x[0], x[3] == 'USD'),
                             reverse=True)
            return next(((v, c) for _, d, v, c in entries if 300 < d < 400), None)

        # Path 1: quarters since the last annual + Q4 derived from annual − 9M YTD.
        # Must run before the naive 4-quarter sum below: Q4 is never filed as its own
        # 10-Q (it's folded into the 10-K), so quarters[:4] would silently swap in a
        # stale year-ago quarter instead of the real Q4, corrupting TTM (e.g. KKR
        # summed Q1'26+Q3'25+Q2'25+Q1'25 = 1.56, skipping Q4'25 entirely; correct
        # TTM with Q4'25 derived from annual−9M is 2.93).
        if ann_filing and len(quarters) >= 3:
            ann_end = ann_filing[2]
            ann_hit = _best_ann_hit()
            if ann_hit:
                ann_val, ann_ccy = ann_hit
                q3_hit = next(
                    ((v, c) for end, (v, c) in sorted(ytd_9m.items(), reverse=True)
                     if end < ann_end), None)
                if q3_hit:
                    q4_usd = _to_usd(ann_val - q3_hit[0], ann_ccy)
                    partial_vals = [_to_usd(v, c) for _, (v, c) in quarters[:3]]
                    if q4_usd is not None and all(x is not None for x in partial_vals):
                        return round(sum(partial_vals) + q4_usd, 4)

        # Path 2: four full quarters — last resort when no usable annual figure exists.
        if len(quarters) >= 4:
            vals = [_to_usd(v, c) for _, (v, c) in quarters[:4]]
            if all(x is not None for x in vals):
                return round(sum(vals), 4)

        # Path 3: annual only (20-F / 40-F land here)
        ann_hit = _best_ann_hit()
        if ann_hit:
            result = _to_usd(ann_hit[0], ann_hit[1])
            if result is not None:
                return round(result, 4)

        return None

    except Exception:
        return None


def _get_brk_b_market_cap(brkb_close):
    """
    BRK-B market cap = BRK-A shares × BRK-A price + BRK-B shares × BRK-B price.
    Berkshire's company_facts EDGAR entry has no current share data, so we parse
    the inline XBRL from their most recent 10-Q cover page instead.
    """
    try:
        import re as _re

        # Fetch BRK-A price — Tiingo normally, yfinance in cost-saving mode.
        if USE_YFINANCE:
            brka_hist = yf.Ticker("BRK-A").history(period="5d", auto_adjust=True)
            if brka_hist is None or brka_hist.empty:
                return None
            brka_close = float(brka_hist["Close"].iloc[-1])
        else:
            brka_data = _tiingo_get("/tiingo/daily/brk-a/prices", params={"resampleFreq": "daily"})
            if not brka_data:
                return None
            brka_close = float(brka_data[-1]["close"])

        # Find most recent 10-Q/10-K accession number and primary document
        cik = "0001067983"
        sub = requests.get(
            f"https://data.sec.gov/submissions/CIK{cik}.json",
            headers=_EDGAR_HEADERS, timeout=15,
        )
        sub.raise_for_status()
        recent = sub.json()["filings"]["recent"]
        forms  = recent["form"]
        accns  = recent["accessionNumber"]
        docs   = recent.get("primaryDocument", [""] * len(forms))

        accn = primary_doc = None
        for i, form in enumerate(forms):
            if form in ("10-Q", "10-K"):
                accn = accns[i]
                primary_doc = docs[i]
                break

        if not accn or not primary_doc:
            return None

        accn_path = accn.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn_path}/{primary_doc}"
        doc_r = requests.get(url, headers=_EDGAR_HEADERS, timeout=30)
        doc_r.raise_for_status()

        # Parse inline XBRL EntityCommonStockSharesOutstanding values
        raw_shares = _re.findall(
            r'<ix:nonFraction[^>]*name="dei:EntityCommonStockSharesOutstanding"[^>]*>([^<]+)<',
            doc_r.text,
        )
        # Values are ordered: Class A first, Class B second (by size)
        share_vals = sorted(
            [int(v.replace(",", "")) for v in raw_shares if v.replace(",", "").isdigit()],
        )
        if len(share_vals) < 2:
            return None

        brka_shares = share_vals[0]   # smaller = Class A (~500K)
        brkb_shares = share_vals[-1]  # larger  = Class B (~1.4B)

        return brka_shares * brka_close + brkb_shares * brkb_close

    except Exception:
        return None


# =========================
# FUNDAMENTALS (disk-cached)
# Combines Tiingo meta (name) + EDGAR (EPS, shares, SIC/sector).
# Market cap is NOT stored — computed fresh each scan as shares × price.
# =========================

_fund_cache = {}
_fund_cache_fetched_date = ""


def _load_fund_disk_cache(ignore_ttl=False):
    global _fund_cache, _fund_cache_fetched_date
    if not os.path.exists(FUND_CACHE_FILE):
        return False
    try:
        with open(FUND_CACHE_FILE) as f:
            data = json.load(f)
        fetched  = datetime.strptime(data.get("fetched", ""), "%Y-%m-%d").date()
        age_days = (date.today() - fetched).days
        if ignore_ttl or age_days < FUND_CACHE_TTL_DAYS:
            _fund_cache             = data.get("tickers", {})
            _fund_cache_fetched_date = data.get("fetched", "")
            print(f"Fundamentals: {len(_fund_cache)} tickers from disk cache ({age_days}d old)")
            return True
        print(f"Fundamentals cache stale ({age_days}d old) — refreshing from EDGAR")
        return False
    except Exception:
        return False


def _save_fund_disk_cache():
    with open(FUND_CACHE_FILE, "w") as f:
        json.dump({"fetched": DATE_STR, "tickers": _fund_cache}, f, indent=2)


def get_fundamentals(ticker, tiingo_names=None):
    if ticker in _fund_cache:
        cached = _fund_cache[ticker]
        meta_entry = (tiingo_names or {}).get(ticker, {})
        if not cached.get("CompanyName"):
            # Backfill: prefer Tiingo name, fall back to EDGAR CIK map title
            name = meta_entry.get("name", "") or _edgar_name_map.get(ticker.upper(), "")
            if name:
                cached["CompanyName"] = name
        # Always update TiingoMarketCap from the fresh meta call (not persisted in disk cache)
        mc = meta_entry.get("marketCap")
        if mc:
            cached["TiingoMarketCap"] = mc
        return cached

    if ticker in ETF_TICKERS:
        # ETFs don't file the XBRL company-facts data EDGAR lookups below expect
        # (no EPS, no operating-company sector) — skip straight to a blank record.
        result = {"SharesOutstanding": None, "SharesFiledDate": None, "EPS": None,
                   "Sector": "", "SicDescription": "", "CompanyName": ETF_NAMES.get(ticker, ticker),
                   "TiingoMarketCap": None}
        _fund_cache[ticker] = result
        return result

    if SKIP_EDGAR:
        return {"SharesOutstanding": None, "SharesFiledDate": None, "EPS": None,
                "Sector": "", "SicDescription": "", "CompanyName": "", "TiingoMarketCap": None}

    eps, shares, sic_desc, shares_filed, edgar_name = _get_edgar_fundamentals(ticker)
    sector       = TICKER_SECTOR_OVERRIDE.get(ticker) or sic_to_sector(sic_desc)
    meta_entry   = (tiingo_names or {}).get(ticker, {})
    tiingo_name  = meta_entry.get("name", "")
    tiingo_mc    = meta_entry.get("marketCap")
    company_name = tiingo_name or edgar_name or _edgar_name_map.get(ticker.upper(), "")

    result = {
        "SharesOutstanding": shares,
        "SharesFiledDate":   shares_filed,
        "EPS":               eps,
        "Sector":            sector,
        "SicDescription":    sic_desc,
        "CompanyName":       company_name,
        "TiingoMarketCap":   tiingo_mc,
    }
    _fund_cache[ticker] = result
    return result


def _apply_post_cache_splits(ticker_set):
    """
    Check for splits since the last fundamentals cache build and update cached
    share counts in _fund_cache. Uses the batch endpoint (one call per trading
    day between cache-fetch date and today — at most ~6 calls for an 8-day TTL).

    Only affects tickers already in _fund_cache. New tickers (cache miss) are
    handled by _get_post_filing_split_factor inside _get_edgar_fundamentals.
    """
    if not _fund_cache_fetched_date or not _fund_cache:
        return
    try:
        start = datetime.strptime(_fund_cache_fetched_date, "%Y-%m-%d").date() + timedelta(days=1)
    except Exception:
        return
    today = date.today()
    if start > today:
        return

    tiingo_to_internal = {_to_tiingo_ticker(TICKER_ALIASES.get(t, t)): t for t in ticker_set}

    post_cache_splits = {}  # tiingo_lower → cumulative factor
    current = start
    call_count = 0
    while current <= today:
        if current.weekday() < 5 and not is_market_holiday(current):
            date_str = current.strftime("%Y-%m-%d")
            resp = _tiingo_get("/tiingo/corporate-actions/splits", params={"exDate": date_str})
            if resp:
                for event in resp:
                    tiingo_tk = (event.get("ticker") or "").lower()
                    if tiingo_tk in tiingo_to_internal:
                        sf = float(event.get("splitFactor") or 1.0)
                        if sf and sf != 1.0:
                            post_cache_splits[tiingo_tk] = post_cache_splits.get(tiingo_tk, 1.0) * sf
            call_count += 1
            time.sleep(0.05)
        current += timedelta(days=1)

    if not post_cache_splits:
        print(f"Post-cache split check: {call_count} date(s) — no splits in universe")
        return

    print(f"Post-cache split check: {call_count} date(s), {len(post_cache_splits)} universe ticker(s) with splits:")
    for tiingo_tk, factor in post_cache_splits.items():
        internal = tiingo_to_internal[tiingo_tk]
        shares = (_fund_cache.get(internal) or {}).get("SharesOutstanding")
        if shares:
            new_shares = int(shares * factor)
            _fund_cache[internal]["SharesOutstanding"] = new_shares
            print(f"  {internal}: {shares:,} → {new_shares:,} (×{factor})")
        if internal in SHARES_OUTSTANDING_OVERRIDE:
            old_ov = SHARES_OUTSTANDING_OVERRIDE[internal]
            SHARES_OUTSTANDING_OVERRIDE[internal] = int(old_ov * factor)
            print(f"  {internal} override: {old_ov:,} → {SHARES_OUTSTANDING_OVERRIDE[internal]:,} (×{factor}) — UPDATE HARDCODED VALUE")


def prefetch_fundamentals(tickers, tiingo_names, sleep_edgar=0.15):
    """
    Populate _fund_cache for all tickers not already loaded.
    sleep_edgar paces EDGAR calls (rate limit: ~10 req/sec; we use ~6 req/sec).
    Each new ticker requires 2 EDGAR calls (company_facts + submissions).
    """
    _load_fx_rates()   # fetch once; needed for foreign-filer EPS currency conversion
    needed = [t for t in tickers if t not in _fund_cache]
    print(f"Fundamentals: fetching {len(needed)} tickers from EDGAR "
          f"({len(tickers) - len(needed)} already cached) …")

    for i, ticker in enumerate(needed, 1):
        try:
            get_fundamentals(ticker, tiingo_names)
        except Exception as e:
            print(f"  {ticker}: EDGAR fetch error — {e}")
        time.sleep(sleep_edgar)
        if i % 50 == 0:
            print(f"  … fetched {i}/{len(needed)}")

    eps_count    = sum(1 for v in _fund_cache.values() if v.get("EPS") is not None)
    shares_count = sum(1 for v in _fund_cache.values() if v.get("SharesOutstanding") is not None)
    print(f"Fundamentals: {eps_count}/{len(_fund_cache)} have EPS, {shares_count} have shares")

    if _unknown_sic_descriptions:
        print(f"\nWARNING: {len(_unknown_sic_descriptions)} SIC descriptions unmapped — add to _SIC_TO_SECTOR:")
        for desc in sorted(_unknown_sic_descriptions):
            print(f'    "{desc}":  "",')

    _save_fund_disk_cache()
    print("Fundamentals cache saved.")


# =========================
# MULTI-PERIOD METRICS
# =========================

def _compute_baiz_persist_and_conviction(df):
    """
    BaizPersist / BaizConviction — validated 2026-08, see assets/baizscore_backtest.html.
    BaizPersist = trailing BAIZ_PERSIST_WINDOW-session average of BaizScore per ticker
    (today's score included), tracked in BAIZSCORE_TRAILING_FILE across daily runs.
    BaizConviction = sqrt(BaizScore * BaizPersist) — rewards stocks that are both
    strong today AND have been consistently strong recently, rather than a single
    spike. At matched sample size this beat plain BaizScore on forward returns.
    Both are null until a ticker has BAIZ_PERSIST_WINDOW sessions of accumulated
    history — ~1 month after this feature's first deploy, or after a new ticker's
    first appearance in the universe.
    """
    history = {}
    if os.path.exists(BAIZSCORE_TRAILING_FILE):
        try:
            with open(BAIZSCORE_TRAILING_FILE) as f:
                history = json.load(f)
        except Exception:
            history = {}

    persist_vals, conviction_vals, updated_history = [], [], {}
    for score, ticker in zip(df["BaizScore"], df["Ticker"]):
        prior = history.get(ticker, [])
        combined = prior + [float(score)] if score is not None and pd.notna(score) else prior
        combined = combined[-BAIZ_PERSIST_WINDOW:]
        updated_history[ticker] = combined

        if len(combined) >= BAIZ_PERSIST_WINDOW and score is not None and pd.notna(score):
            persist = sum(combined) / len(combined)
            persist_vals.append(round(persist))
            conviction_vals.append(round((persist * float(score)) ** 0.5))
        else:
            persist_vals.append(None)
            conviction_vals.append(None)

    try:
        with open(BAIZSCORE_TRAILING_FILE, "w") as f:
            json.dump(updated_history, f)
    except Exception as e:
        print(f"[baiz_persist] failed to save trailing history: {e}")

    return persist_vals, conviction_vals


SCORE_TREND_COLS = ["BaizScore", "BaizMomentum", "BaizPersist", "BaizConviction"]


def _update_score_trends(df):
    """
    Rolling ~1-year (BAIZ_TREND_WINDOW-session) history of all four Baizora scores
    per ticker, feeding the score-trend sparklines on the dashboard. Backfilled once
    (2026-08) via a one-off historical replay so sparklines are populated immediately
    rather than growing empty for a year; maintained incrementally here afterward —
    append today's already-computed values, drop anything past the window.
    Returns {score_col: [list_per_row, ...]} aligned to df's current row order.
    """
    history = {}
    if os.path.exists(BAIZSCORE_TREND_FILE):
        try:
            with open(BAIZSCORE_TREND_FILE) as f:
                history = json.load(f)
        except Exception:
            history = {}

    spark_cols = {c: [] for c in SCORE_TREND_COLS}
    updated_history = {}

    for _, row in df.iterrows():
        ticker = row["Ticker"]
        entry = history.get(ticker, {})
        new_entry = {}
        for c in SCORE_TREND_COLS:
            val = row.get(c)
            val_clean = int(val) if val is not None and pd.notna(val) else None
            combined = (entry.get(c, []) + [val_clean])[-BAIZ_TREND_WINDOW:]
            new_entry[c] = combined
            spark_cols[c].append(combined)
        updated_history[ticker] = new_entry

    try:
        with open(BAIZSCORE_TREND_FILE, "w") as f:
            json.dump(updated_history, f)
    except Exception as e:
        print(f"[baiz_trend] failed to save trend history: {e}")

    return spark_cols


def calculate_period_metrics(df, label, days):
    recent = df.iloc[-days:].copy().reset_index(drop=True)
    start_price = recent["Close"].iloc[0]
    end_price   = recent["Close"].iloc[-1]

    period_price_change = (
        (end_price - start_price) / start_price
        if start_price not in [0, None] and not pd.isna(start_price)
        else None
    )

    recent["price_change"]  = recent["Close"].pct_change()
    recent["volume_change"] = recent["Volume"].pct_change()
    recent["price_change"]  = recent["price_change"].replace([np.inf, -np.inf], np.nan)
    recent["volume_change"] = recent["volume_change"].replace([np.inf, -np.inf], np.nan)

    if recent["price_change"].dropna().empty or recent["volume_change"].dropna().empty:
        return {}

    max_price_idx = recent["price_change"].idxmax()
    max_vol_idx   = recent["volume_change"].idxmax()

    max_price_val    = recent["price_change"].iloc[max_price_idx]
    max_vol_val      = recent["volume_change"].iloc[max_vol_idx]
    price_at_max_vol = recent["price_change"].iloc[max_vol_idx]
    vol_at_max_price = recent["volume_change"].iloc[max_price_idx]

    n          = len(recent)
    price_day  = n - 1 - max_price_idx
    volume_day = n - 1 - max_vol_idx

    return {
        f"{label}PriceChange":            round(period_price_change * 100, 2) if period_price_change is not None else None,
        f"{label}MaxPriceChange":         round(max_price_val * 100, 2),
        f"{label}MaxVolumeChange":        round(max_vol_val * 100, 2),
        f"{label}MaxPriceChangeDay":      price_day,
        f"{label}MaxVolumeChangeDay":     volume_day,
        f"{label}PriceChangeAtMaxVolume": round(price_at_max_vol * 100, 2),
        f"{label}VolumeChangeAtMaxPrice": round(vol_at_max_price * 100, 2),
    }


# =========================
# SCAN
# =========================

def _build_weekly_series(df, max_weeks=265):
    """Resample one ticker's daily OHLCV df (cols Date/Open/High/Low/Close/Volume,
    ascending) to weekly bars — one per calendar week (Mon–Fri), labelled by the
    last actual trading day in that week. Returns (dates[list[str]],
    candles[list[[o,h,l,c,v]]], sma{sma20,sma50,sma200}) or None.

    Weekly SMA200 needs ~3.8y of weeks, so on a ~5y series it is non-null only for
    the most recent stretch — the chart draws it as an intentional partial line."""
    if df is None or df.empty:
        return None
    d = df[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"]).copy()
    if d.empty:
        return None
    d["EndDate"] = d["Date"]                       # preserved through resample for the real week-end label
    g = d.resample("W-FRI", on="Date")
    w = pd.DataFrame({
        "Open":    g["Open"].first(),
        "High":    g["High"].max(),
        "Low":     g["Low"].min(),
        "Close":   g["Close"].last(),
        "Volume":  g["Volume"].sum(),
        "EndDate": g["EndDate"].max(),
    }).dropna(subset=["Close"])
    if w.empty:
        return None
    w = w.tail(max_weeks).reset_index(drop=True)
    s20  = w["Close"].rolling(20).mean()
    s50  = w["Close"].rolling(50).mean()
    s200 = w["Close"].rolling(200).mean()
    dates, candles, a20, a50, a200 = [], [], [], [], []
    for i, row in w.iterrows():
        o, h, l, c, v = row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]
        if not all(pd.notna(x) for x in (o, h, l, c)) or pd.isna(row["EndDate"]):
            continue
        dates.append(pd.Timestamp(row["EndDate"]).strftime("%Y-%m-%d"))
        candles.append([
            round(float(o), 2), round(float(h), 2), round(float(l), 2), round(float(c), 2),
            int(v) if pd.notna(v) and v > 0 else 0,
        ])
        a20.append(round(float(s20.iloc[i]), 2)  if pd.notna(s20.iloc[i])  else None)
        a50.append(round(float(s50.iloc[i]), 2)  if pd.notna(s50.iloc[i])  else None)
        a200.append(round(float(s200.iloc[i]), 2) if pd.notna(s200.iloc[i]) else None)
    if not candles:
        return None
    return dates, candles, {"sma20": a20, "sma50": a50, "sma200": a200}


def scan():
    tickers, sp_set, nd_set, etf_set = get_tickers()
    universe_set        = set(tickers)
    results             = []
    candles_out         = {}
    smas_out            = {}
    weekly_raw          = {}   # ticker -> (dates, candles, sma) for candles_weekly.json
    sector_mktcap_sum   = {}
    sector_earnings_sum = {}

    print(f"Total tickers: {len(tickers)}")

    to_date   = _TIINGO_LAST_DATE
    # ~5Y lookback (1830 calendar days ≈ 1260 trading days) for the 5Y window metrics.
    # Matches the yfinance period="5y" fetch in build_ohlcv_cache_yfinance.
    from_date = (datetime.now(pytz.timezone('America/New_York')) - timedelta(days=1830)).strftime("%Y-%m-%d")

    # Build / update per-ticker OHLCV cache
    build_ohlcv_cache(tickers, from_date)

    # Fetch Tiingo split history and write data/splits.json — skipped in yfinance mode,
    # where auto_adjust=True already handles splits at fetch time (see fetch_yfinance_bulk).
    # Runs on full scan AND weekend EDGAR-only runs (splits announced well before effective date)
    if not USE_YFINANCE and (not SKIP_EDGAR or EDGAR_ONLY):
        update_splits_file(tickers)

    # Load fundamentals (disk cache → EDGAR for missing)
    _load_fund_disk_cache(ignore_ttl=SKIP_EDGAR)
    if not SKIP_EDGAR:
        pass  # post-cache split adjustment removed — EDGAR shares used as-is
    # Tiingo's meta call (company names/market cap) is skipped entirely in yfinance mode —
    # get_fundamentals() already falls back to SEC EDGAR's own name when tiingo_meta is empty.
    tiingo_meta = {} if USE_YFINANCE else prefetch_tiingo_meta(tickers)
    if not SKIP_EDGAR:
        prefetch_fundamentals(tickers, tiingo_meta)
        _prune_split_guards()
    else:
        print("SKIP_EDGAR=1 — using cached fundamentals, skipping EDGAR fetch")

    # Build trading-day list and load all OHLCV into memory
    trading_days = get_trading_days(from_date, to_date)
    print("Loading OHLCV cache into memory …")
    daily_data = load_ohlcv_cache_into_memory(tickers, trading_days)

    print(f"Loaded {len(daily_data)} days. Processing {len(tickers)} tickers …")

    # SPY for beta
    spy_returns = None
    try:
        spy_df = fetch_yfinance_benchmark(from_date, to_date) if USE_YFINANCE else fetch_benchmark_bars(from_date, to_date)
        if spy_df is not None and len(spy_df) >= 60:
            spy_returns = spy_df["Close"].pct_change().dropna()
            print(f"SPY loaded: {len(spy_returns)} returns for beta")
        else:
            print("SPY fetch returned no data — beta will be None")
    except Exception as e:
        print(f"SPY fetch failed ({e}) — beta will be None")

    for i, ticker in enumerate(tickers, 1):
        try:
            df = load_ticker_ohlcv(ticker, trading_days, daily_data)
            if df is None or df.empty:
                continue

            df = df[(df["Volume"] >= 10000) & (df["Close"] > 0)]
            if len(df) < 2:
                continue

            df["MA21_PRICE"] = df["Close"].rolling(21).mean()
            df["MA21_VOL"]   = df["Volume"].rolling(21).mean()

            latest = df.iloc[-1]
            prev   = df.iloc[-2]

            latest_volume_m = round(latest["Volume"] / 1_000_000, 2)

            has_ma = (
                len(df) >= 21 and
                pd.notna(latest["MA21_PRICE"]) and
                pd.notna(latest["MA21_VOL"])
            )

            price_change_1d = (
                (latest["Close"] - prev["Close"]) / prev["Close"]
                if prev["Close"] not in [0, None] and not pd.isna(prev["Close"]) else None
            )
            volume_change_1d = (
                (latest["Volume"] - prev["Volume"]) / prev["Volume"]
                if prev["Volume"] not in [0, None] and not pd.isna(prev["Volume"]) else None
            )

            if has_ma:
                price_vs_ma21_1d  = latest["Close"]  / latest["MA21_PRICE"]
                volume_vs_ma21_1d = latest["Volume"] / latest["MA21_VOL"]
            else:
                price_vs_ma21_1d  = np.nan
                volume_vs_ma21_1d = np.nan

            metrics = {}
            for label, days in TIMEFRAMES.items():
                metrics.update(calculate_period_metrics(df, label, days))

            fund   = get_fundamentals(ticker, tiingo_meta)
            sector = fund["Sector"]
            eps    = fund["EPS"]

            # Market cap: BRK-B special case; otherwise SHARES_OUTSTANDING_OVERRIDE if set
            # (covers multi-class/LP structures where EDGAR under-reports), else EDGAR shares × price.
            shares = fund.get("SharesOutstanding")
            _ov = SHARES_OUTSTANDING_OVERRIDE.get(ticker)
            shares_for_cap = _ov(shares) if callable(_ov) else (_ov if _ov is not None else shares)
            if ticker == "BRK-B":
                market_cap = _get_brk_b_market_cap(float(latest["Close"]))
            else:
                market_cap = shares_for_cap * float(latest["Close"]) if shares_for_cap else None

            pe = round(float(latest["Close"]) / eps, 2) if eps and eps > 0 else None

            if sector and pe and market_cap and market_cap > 0:
                sector_mktcap_sum.setdefault(sector, 0.0)
                sector_earnings_sum.setdefault(sector, 0.0)
                sector_mktcap_sum[sector]   += market_cap
                sector_earnings_sum[sector] += market_cap / pe

            in_sp500     = ticker in sp_set
            in_nasdaq100 = ticker in nd_set
            in_etf       = ticker in etf_set

            try:
                close_series = df["Close"].dropna()

                def normalize(series):
                    min_v, max_v = series.min(), series.max()
                    if max_v == min_v:
                        return [0.5] * len(series)
                    return ((series - min_v) / (max_v - min_v)).tolist()

                spark_1y = normalize(close_series.tail(252))
            except Exception:
                spark_1y = None

            beta    = None
            vol_30d = None
            try:
                stock_ret = df["Close"].pct_change().dropna()
                if len(stock_ret) >= 20:
                    vol_30d = round(float(stock_ret.iloc[-30:].std() * np.sqrt(252)), 4)
                if spy_returns is not None and len(stock_ret) >= 60:
                    n   = min(252, len(stock_ret), len(spy_returns))
                    s   = stock_ret.iloc[-n:].values
                    m   = spy_returns.iloc[-n:].values
                    cov = np.cov(s, m)
                    if cov[1, 1] != 0:
                        beta = round(cov[0, 1] / cov[1, 1], 3)
            except Exception:
                pass

            try:
                candle_rows = df.tail(252)
                # Rolling means computed over the FULL df (up to ~5Y of history,
                # see build_ohlcv_cache's from_date above) so SMA200 has real lookback
                # for every bar in the exported 252-day window, not just the tail end —
                # only genuinely new listings (<200 trading days of total history) will
                # show nulls, which is a real data limit, not a truncation artifact.
                sma20_full  = df["Close"].rolling(20).mean()
                sma50_full  = df["Close"].rolling(50).mean()
                sma200_full = df["Close"].rolling(200).mean()
                candles, sma20_l, sma50_l, sma200_l = [], [], [], []
                for idx, row in candle_rows.iterrows():
                    o, h, l, c, v = row.get("Open"), row.get("High"), row.get("Low"), row["Close"], row.get("Volume")
                    if all(x is not None and pd.notna(x) for x in [o, h, l, c]):
                        vol = int(v) if v is not None and pd.notna(v) and v > 0 else 0
                        candles.append([round(float(o),2), round(float(h),2), round(float(l),2), round(float(c),2), vol])
                        s20, s50, s200 = sma20_full.get(idx), sma50_full.get(idx), sma200_full.get(idx)
                        sma20_l.append(round(float(s20), 2)   if pd.notna(s20)  else None)
                        sma50_l.append(round(float(s50), 2)   if pd.notna(s50)  else None)
                        sma200_l.append(round(float(s200), 2) if pd.notna(s200) else None)
                if candles:
                    candles_out[ticker] = candles
                    smas_out[ticker] = {"sma20": sma20_l, "sma50": sma50_l, "sma200": sma200_l}
            except Exception:
                pass

            try:
                wk = _build_weekly_series(df)
                if wk:
                    weekly_raw[ticker] = wk
            except Exception:
                pass

            # Scores
            pc_2w = metrics.get("2WPriceChange")  or 0.0
            pc_1m = metrics.get("1MPriceChange")  or 0.0
            pc_3m = metrics.get("3MPriceChange")  or 0.0
            pc_6m = metrics.get("6MPriceChange")  or 0.0
            pc_9m = metrics.get("9MPriceChange")  or 0.0
            pc_1y = metrics.get("1YPriceChange")  or 0.0

            pv_ma     = float(price_vs_ma21_1d)  if pd.notna(price_vs_ma21_1d)  else 1.0
            vv_ma     = float(volume_vs_ma21_1d) if pd.notna(volume_vs_ma21_1d) else 1.0
            pc_1d_pct = float(price_change_1d * 100) if price_change_1d is not None else 0.0

            bs  = min(33, max(0, (pv_ma - 1) * 200))
            bs += min(33, max(0, pc_1d_pct * 3))
            bs += min(34, max(0, (vv_ma - 1) * 25))
            breakout_score = round(min(100, max(0, bs)))

            p_dir = 1 if pc_1d_pct > 0 else (-1 if pc_1d_pct < 0 else 0)
            vol_pressure_score = round(max(-100, min(100, (vv_ma - 1) * p_dir * 100)))

            trend_score = round(
                sum(1 for v in [pc_2w, pc_1m, pc_3m, pc_6m, pc_9m, pc_1y] if v > 0) / 6 * 100
            )

            raw_rs       = 0.40*pc_3m + 0.20*pc_6m + 0.20*pc_9m + 0.20*pc_1y
            raw_momentum = 0.35*pc_1m + 0.25*pc_3m + 0.20*pc_6m + 0.20*pc_1y

            actual_date = df["Date"].iloc[-1].strftime("%Y-%m-%d")
            results.append({
                "Date":   actual_date,
                "Ticker": ticker,

                "InSP500":     in_sp500,
                "InNASDAQ100": in_nasdaq100,
                "InETF":       in_etf,

                "Price":   round(float(latest["Close"]), 2),
                "VolumeM": latest_volume_m,

                "PriceChange1D":  round(price_change_1d  * 100, 2) if price_change_1d  is not None else None,
                "VolumeChange1D": round(volume_change_1d * 100, 2) if volume_change_1d is not None else None,

                "PriceVsMA21_1D":  round(price_vs_ma21_1d,  3) if pd.notna(price_vs_ma21_1d)  else None,
                "VolumeVsMA21_1D": round(volume_vs_ma21_1d, 3) if pd.notna(volume_vs_ma21_1d) else None,

                **metrics,

                "PE":            pe,
                "MarketCap":     market_cap,
                "EPS":           eps,
                "Sector":        sector,
                "Beta":          beta,
                "Volatility30D": vol_30d,
                "CompanyName":   fund["CompanyName"],
                "Spark6M":       None,
                "Spark1Y":       spark_1y,

                "BreakoutScore":    breakout_score,
                "VolPressureScore": vol_pressure_score,
                "TrendScore":       trend_score,
                "_RawRS":           raw_rs,
                "_RawMomentum":     raw_momentum,
            })

        except Exception as e:
            print(f"{ticker} error: {e}")
            continue

        if i % 50 == 0:
            print(f"  … processed {i}/{len(tickers)}")

    # Post-processing
    sector_avg_pe = {
        s: sector_mktcap_sum[s] / sector_earnings_sum[s]
        for s in sector_mktcap_sum
        if sector_earnings_sum.get(s, 0) > 0
    }

    df = pd.DataFrame(results)
    if df.empty:
        print("No results generated — universe or data issue")
        return df, {}, trading_days

    df["MarketCap"] = df["MarketCap"].apply(
        lambda x: round(float(x) / 1_000_000_000, 2)
        if x is not None and pd.notna(x) else None
    )

    df["SectorAvgPE"] = df["Sector"].map(sector_avg_pe)
    df["SectorAvgPE"] = pd.to_numeric(df["SectorAvgPE"], errors="coerce").round(2)

    df["PE_vs_Sector"] = np.where(
        df["PE"].notna() & df["SectorAvgPE"].notna() & (df["SectorAvgPE"] != 0),
        (df["PE"] - df["SectorAvgPE"]) / df["SectorAvgPE"] * 100,
        np.nan,
    )
    df["PE_vs_Sector"] = df["PE_vs_Sector"].round(1)

    if "_RawRS" in df.columns:
        df["RSScore"] = (df["_RawRS"].rank(pct=True) * 98 + 1).round().clip(1, 99).astype(int)
        df.drop(columns=["_RawRS"], inplace=True)

    if "_RawMomentum" in df.columns:
        df["MomentumScore"] = (df["_RawMomentum"].rank(pct=True) * 100).round().clip(0, 100).astype(int)
        df.drop(columns=["_RawMomentum"], inplace=True)

    score_cols = ["RSScore", "MomentumScore", "BreakoutScore", "TrendScore", "VolPressureScore"]
    if all(c in df.columns for c in score_cols):
        rs_norm = (df["RSScore"] - 1) / 98 * 100
        vp_norm = (df["VolPressureScore"] + 100) / 2
        df["BaizScore"] = (
            0.30 * rs_norm +
            0.25 * df["MomentumScore"] +
            0.20 * df["BreakoutScore"] +
            0.15 * df["TrendScore"] +
            0.10 * vp_norm
        ).round().clip(0, 100).astype(int)

        # BaizMomentum — alternate composite weighted toward RS/Momentum (backtested
        # 2026-08 as the "momentum_amplified" scenario; edge over BaizScore was only
        # clear at the 90+ tier on a thin sample — see assets/baizscore_backtest.html)
        df["BaizMomentum"] = (
            0.40 * rs_norm +
            0.35 * df["MomentumScore"] +
            0.15 * df["BreakoutScore"] +
            0.05 * df["TrendScore"] +
            0.05 * vp_norm
        ).round().clip(0, 100).astype(int)

        persist_vals, conviction_vals = _compute_baiz_persist_and_conviction(df)
        df["BaizPersist"] = persist_vals
        df["BaizConviction"] = conviction_vals

        trend_spark = _update_score_trends(df)
        for c in SCORE_TREND_COLS:
            df[f"{c}Spark1Y"] = trend_spark[c]

    if "VolumeChange1D" in df.columns:
        df = df.sort_values("VolumeChange1D", ascending=False)

    return df, candles_out, smas_out, weekly_raw, trading_days


# =========================
# DATA QUALITY CHECK
# =========================

def check_data_quality(df, candles_out, trading_days):
    issues = []

    if "PriceChange1D" in df.columns:
        big_1d = df[df["PriceChange1D"].abs() > 25][["Ticker", "PriceChange1D", "Price"]].copy()
        for _, row in big_1d.iterrows():
            issues.append(
                f"  {row['Ticker']}: 1D price change {row['PriceChange1D']:.1f}% "
                f"(${row['Price']}) — possible cache gap"
            )

    expected = min(252, len(trading_days))
    for ticker, candles in candles_out.items():
        if len(candles) < 200:
            issues.append(f"  {ticker}: only {len(candles)} candle bars (expected ~{expected})")

    all_tickers = df["Ticker"].tolist() if not df.empty else []
    no_cache = [t for t in all_tickers if not os.path.exists(_cache_path(t))]
    if no_cache:
        issues.append(f"  {len(no_cache)} tickers have no OHLCV cache file")

    if issues:
        print(f"\nDATA QUALITY WARNINGS ({len(issues)} issues):")
        for msg in issues:
            print(msg)
        print()
    else:
        print("Data quality check passed.")


# =========================
# EXPORT
# =========================

def _rotate_prior_session(new_market_date):
    """Rotates latest.json → latest_d1.json (used by score_history for prior-session top movers)."""
    import shutil
    d1_path = os.path.join(DATA_DIR, "latest_d1.json")

    if not os.path.exists(OUTPUT_JSON):
        return
    try:
        with open(OUTPUT_JSON) as f:
            existing_date = json.load(f).get("date", "")
        if existing_date == new_market_date:
            return  # Same-day rescan — don't rotate
    except Exception:
        return

    shutil.copy2(OUTPUT_JSON, d1_path)
    print(f"[rotate] d1←{existing_date}, new latest←{new_market_date}")


def export(df):
    df = df.replace({np.nan: None, np.inf: None, -np.inf: None})

    market_date = df["Date"].iloc[0] if len(df) and "Date" in df.columns else DATE_STR
    output_csv  = os.path.join(ARCHIVE_DIR, f"results_{market_date}.csv")

    df.to_csv(output_csv, index=False)
    _rotate_prior_session(market_date)

    payload = {
        "date":   market_date,
        "status": "Updated",
        "count":  len(df),
        "partialUpdate": bool(_STALE_TICKERS_EXCLUDED),
        "staleTickers":  _STALE_TICKERS_EXCLUDED,
        "data":   df.to_dict(orient="records"),
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    print("Export complete:", len(df))


# =========================
# CANDLES EXPORT
# =========================

def export_candles(candles_out, smas_out, trading_days):
    dates = list(trading_days[-252:])
    payload = {"date": DATE_STR, "dates": dates, "data": candles_out, "sma": smas_out}
    path = os.path.join(DATA_DIR, "candles.json")
    with open(path, "w") as f:
        json.dump(payload, f)
    print(f"Candles export: {len(candles_out)} tickers, {len(dates)} dates, {len(smas_out)} with SMA data")


def export_candles_weekly(weekly_raw):
    """Write data/candles_weekly.json — ~5Y of weekly bars, same shape as
    candles.json (shared `dates` axis, per-ticker candle/SMA arrays aligned to it
    with null gaps). Loaded lazily by the paid dashboard chart's 2Y / 5Y views."""
    if not weekly_raw:
        print("Weekly candles export: nothing to write (weekly_raw empty)")
        return

    all_dates = sorted({d for dates, _c, _s in weekly_raw.values() for d in dates})
    idx_of = {d: i for i, d in enumerate(all_dates)}
    n = len(all_dates)

    data, sma = {}, {}
    for ticker, (dates, candles, smad) in weekly_raw.items():
        row_c = [None] * n
        row20, row50, row200 = [None] * n, [None] * n, [None] * n
        for k, d in enumerate(dates):
            i = idx_of.get(d)
            if i is None:
                continue
            row_c[i]   = candles[k]
            row20[i]   = smad["sma20"][k]
            row50[i]   = smad["sma50"][k]
            row200[i]  = smad["sma200"][k]
        data[ticker] = row_c
        sma[ticker]  = {"sma20": row20, "sma50": row50, "sma200": row200}

    payload = {"date": DATE_STR, "dates": all_dates, "data": data, "sma": sma}
    path = os.path.join(DATA_DIR, "candles_weekly.json")
    with open(path, "w") as f:
        json.dump(payload, f)
    print(f"Weekly candles export: {len(data)} tickers, {n} weeks")


def _build_briefing_txt(market_date, scan_time, digest, headlines):
    line = "─" * 54
    txt  = f"BAIZORA DAILY MARKET BRIEFING — {market_date}\n{line}\n"
    txt += f"S&P 500 & Nasdaq-100  ·  516 stocks tracked\n"
    txt += f"Scan time: {scan_time}\n\n"
    txt += "TOP GAINERS (1-Day)\n"
    for r in digest["top_gainers"]:
        sign = "+" if r["chg1d"] >= 0 else ""
        name = (r["name"] or "")[:22]
        txt += f"  {r['ticker']:<6} {name:<22}  ${r['price']:.2f}   {sign}{r['chg1d']:.2f}%\n"
    txt += "\nTOP VOLUME SPIKES (1-Day)\n"
    for r in digest["top_volume"]:
        name  = (r["name"] or "")[:22]
        vol_s = f"{r['vol']:.1f}M" if r["vol"] else "—"
        txt += f"  {r['ticker']:<6} {name:<22}  +{r['volchg']:.0f}%   Vol: {vol_s}\n"
    if headlines:
        txt += "\nMARKET NEWS\n"
        for h in headlines:
            txt += h + "\n"
    txt += f"\n{line}\nBaizora — S&P 500 & Nasdaq-100 Daily Analytics\nhttps://baizora.com\nNot financial advice.\n"
    return txt


def _build_briefing_txt_cn(market_date, scan_time, digest, headlines_cn):
    line = "─" * 54
    txt_cn  = f"贝佐拉每日市场简报 — {market_date}\n{line}\n"
    txt_cn += f"标普500 & 纳斯达克100  ·  追踪516支股票\n"
    txt_cn += f"行情时间：{scan_time}\n\n"
    txt_cn += "涨幅榜（日内）\n"
    for r in digest["top_gainers"]:
        sign = "+" if r["chg1d"] >= 0 else ""
        name = (r["name"] or "")[:22]
        txt_cn += f"  {r['ticker']:<6} {name:<22}  ${r['price']:.2f}   {sign}{r['chg1d']:.2f}%\n"
    txt_cn += "\n成交量飙升（日内）\n"
    for r in digest["top_volume"]:
        name  = (r["name"] or "")[:22]
        vol_s = f"{r['vol']:.1f}M" if r["vol"] else "—"
        txt_cn += f"  {r['ticker']:<6} {name:<22}  +{r['volchg']:.0f}%   成交量: {vol_s}\n"
    if headlines_cn:
        txt_cn += "\n市场资讯\n"
        for h in headlines_cn:
            txt_cn += h + "\n"
    else:
        txt_cn += "\n市场资讯\n  （每日更新于 baizora.com）\n"
    txt_cn += f"\n{line}\n贝佐拉 — 标普500 & 纳斯达克100 每日行情分析\nhttps://baizora.com\n本内容不构成投资建议。\n"
    return txt_cn


def export_daily_digest(df):
    """Write daily_digest.json (for card display) and daily_briefing.txt (for download)."""
    try:
        et_tz = pytz.timezone("America/New_York")
        scan_time = datetime.now(et_tz).strftime("%Y-%m-%d %I:%M %p ET")

        df_clean = df.dropna(subset=["PriceChange1D", "VolumeChange1D"]).copy()
        top_g = df_clean.nlargest(5, "PriceChange1D")
        top_v = df_clean.nlargest(5, "VolumeChange1D")

        def _row_g(r):
            return {"ticker": r["Ticker"], "name": r.get("CompanyName", ""),
                    "price": round(float(r["Price"]), 2) if r.get("Price") else None,
                    "chg1d": round(float(r["PriceChange1D"]), 2)}
        def _row_v(r):
            return {"ticker": r["Ticker"], "name": r.get("CompanyName", ""),
                    "price": round(float(r["Price"]), 2) if r.get("Price") else None,
                    "volchg": round(float(r["VolumeChange1D"]), 1),
                    "vol": round(float(r["VolumeM"]), 1) if r.get("VolumeM") else None}

        market_date = df["Date"].iloc[0] if len(df) and "Date" in df.columns else DATE_STR
        digest = {
            "date":        market_date,
            "scan_time":   scan_time,
            "top_gainers": [_row_g(r) for _, r in top_g.iterrows()],
            "top_volume":  [_row_v(r) for _, r in top_v.iterrows()],
        }
        with open(DIGEST_JSON, "w") as f:
            json.dump(digest, f)
        print(f"Digest JSON: {len(digest['top_gainers'])} gainers, {len(digest['top_volume'])} volume spikes")

        # Build downloadable text briefing — Google News RSS (international sources), up to 30 headlines
        fetched_en, items_en = _fetch_market_news_items(30, "en")
        with open(MARKET_NEWS_JSON, "w", encoding="utf-8") as f:
            json.dump({"fetched": fetched_en, "items": items_en}, f, ensure_ascii=False)
        print(f"Market news JSON: {len(items_en)} items")
        headlines = [f"  • {it['title']}" + (f" — {it['source']}" if it['source'] else "") for it in items_en]

        with open(BRIEFING_TXT, "w", encoding="utf-8") as f:
            f.write(_build_briefing_txt(market_date, scan_time, digest, headlines))
        print("Briefing text written.")

        # CN version — same international headlines as EN, translated (not a Chinese-language RSS query).
        # Items that fail translation even after retry are dropped rather than shown in English,
        # so the CN download/card never mixes in an untranslated headline.
        import copy
        items_cn_all = copy.deepcopy(items_en)
        _translate_items_to_zh(items_cn_all)
        items_cn = [it for it in items_cn_all if it.get("title_cn")]
        n_dropped = len(items_cn_all) - len(items_cn)
        if n_dropped:
            print(f"[digest] dropped {n_dropped} CN headline(s) that failed translation")
        fetched_cn = fetched_en
        if items_en and not items_cn:
            # Wholesale translation failure (items_en had content, none of it survived translation) —
            # don't overwrite a previously-good market_news_cn.json with an empty list.
            print(f"[digest] CN translation failed for all {len(items_en)} headlines — leaving existing {MARKET_NEWS_CN_JSON} untouched")
            try:
                with open(MARKET_NEWS_CN_JSON, encoding="utf-8") as f:
                    items_cn = json.load(f).get("items", [])
            except (OSError, json.JSONDecodeError):
                items_cn = []
        else:
            with open(MARKET_NEWS_CN_JSON, "w", encoding="utf-8") as f:
                json.dump({"fetched": fetched_cn, "items": items_cn}, f, ensure_ascii=False)
            print(f"Market news CN JSON: {len(items_cn)} items")
        headlines_cn = [f"  • {it['title_cn']}" + (f" — {it['source']}" if it['source'] else "") for it in items_cn]

        with open(BRIEFING_TXT_CN, "w", encoding="utf-8") as f:
            f.write(_build_briefing_txt_cn(market_date, scan_time, digest, headlines_cn))
        print("CN briefing text written.")
    except Exception as e:
        import traceback
        print(f"[digest] export failed: {e}")
        traceback.print_exc()


# =========================
# SCORE HISTORY
# =========================

def export_score_history(df):
    """Last session's top-10 price movers (from latest_d1.json) + 5-session BaizScore rank history."""
    try:
        market_date = df["Date"].iloc[0] if len(df) and "Date" in df.columns else DATE_STR

        # BaizScore ranks for all tickers — used for dots and score display
        df_s = df[df["BaizScore"].notna()].copy()
        df_s = df_s.sort_values("BaizScore", ascending=False).reset_index(drop=True)
        df_s["_rank"] = range(1, len(df_s) + 1)
        all_ranks = {row["Ticker"]: int(row["_rank"]) for _, row in df_s.iterrows()}
        score_map = {row["Ticker"]: (round(float(row["BaizScore"]), 1), int(row["_rank"]))
                     for _, row in df_s.iterrows()}

        # Load existing history and update with today's ranks
        history = {"sessions": [], "session_ranks": []}
        if os.path.exists(SCORE_HISTORY):
            try:
                with open(SCORE_HISTORY) as f:
                    history = json.load(f)
            except Exception:
                pass

        if history["sessions"] and history["sessions"][0] == market_date:
            history["session_ranks"][0] = {"session": market_date, "ranks": all_ranks}
        else:
            history["sessions"].insert(0, market_date)
            history["session_ranks"].insert(0, {"session": market_date, "ranks": all_ranks})

        history["sessions"]      = history["sessions"][:5]
        history["session_ranks"] = history["session_ranks"][:5]

        # Top-10 by PriceChange1D from TODAY's scan (latest.json).
        # By the time users view the homepage next day this is already "last session's" data.
        top10 = []
        if os.path.exists(OUTPUT_JSON):
            with open(OUTPUT_JSON) as f:
                d1 = json.load(f)
            d1_rows = [r for r in d1.get("data", []) if r.get("PriceChange1D") is not None]
            d1_rows.sort(key=lambda r: r.get("PriceChange1D") or 0, reverse=True)
            for r in d1_rows[:10]:
                spark = r.get("Spark1Y")
                if isinstance(spark, list):
                    spark = [round(float(x), 4) for x in spark if x is not None]
                sc, rk = score_map.get(r["Ticker"], (None, None))
                n_spark = max(len(spark) - 1, 1) if spark else 1
                # Triangle = highest-volume day; dot = largest price-change day
                tri_idx = min(int(r.get("1YMaxVolumeChangeDay") or 0), n_spark)
                dot_idx = min(int(r.get("1YMaxPriceChangeDay") or 0), n_spark)
                tri_col = "#22c55e" if (r.get("1YPriceChangeAtMaxVolume") or 0) >= 0 else "#ef4444"
                dot_col = "#22c55e" if (r.get("1YVolumeChangeAtMaxPrice") or 0) >= 0 else "#ef4444"
                sc, rk = score_map.get(r["Ticker"], (None, None))
                top10.append({
                    "ticker":      r["Ticker"],
                    "company":     r.get("CompanyName", ""),
                    "session":     d1.get("date", ""),
                    "price":       round(float(r["Price"]), 2) if r.get("Price") else None,
                    "change1d":    round(float(r["PriceChange1D"]), 2) if r.get("PriceChange1D") else None,
                    "spark1y":     spark,
                    "triIdx":      tri_idx,
                    "triCol":      tri_col,
                    "dotIdx":      dot_idx,
                    "dotCol":      dot_col,
                    "inSP500":     bool(r.get("InSP500")),
                    "inNASDAQ100": bool(r.get("InNASDAQ100")),
                    "score":       sc,
                    "scoreRank":   rk,
                })

        with open(SCORE_HISTORY, "w") as f:
            json.dump({"sessions": history["sessions"], "top10": top10,
                       "session_ranks": history["session_ranks"]}, f)

        print(f"[score_history] {len(history['sessions'])} sessions, top movers from d1: {[t['ticker'] for t in top10[:5]]}")
    except Exception as e:
        print(f"[score_history] failed: {e}")


# =========================
# INDEX MEMBERSHIP NEWS
# =========================

_NEWS_QUERIES = [
    ("S&P 500 addition",
     '"added to S&P 500" OR "will join S&P 500" OR "joins S&P 500" OR "joining S&P 500"'
     ' OR "entering S&P 500" OR "S&P 500 index addition" OR "S&P 500 inclusion"'),
    ("S&P 500 removal",
     '"removed from S&P 500" OR "dropped from S&P 500" OR "leaving S&P 500"'
     ' OR "exits S&P 500" OR "S&P 500 index removal" OR "S&P 500 exclusion"'),
    ("Nasdaq-100 addition",
     '"added to Nasdaq-100" OR "will join Nasdaq-100" OR "joins Nasdaq-100" OR "joining Nasdaq-100"'
     ' OR "entering Nasdaq-100" OR "Nasdaq-100 index addition" OR "Nasdaq-100 inclusion"'),
    ("Nasdaq-100 removal",
     '"removed from Nasdaq-100" OR "dropped from Nasdaq-100" OR "leaving Nasdaq-100"'
     ' OR "exits Nasdaq-100" OR "Nasdaq-100 index removal" OR "Nasdaq-100 exclusion"'),
]

_NEWS_SKIP_PHRASES = [
    "within a year", "within a month", "within months",
    "since joining", "since being added", "since addition",
    "year after joining", "months after joining", "a year of joining",
    "years after", "year later", "months later", "one year", "look back",
]


def _is_retrospective(title):
    t = title.lower()
    return any(p in t for p in _NEWS_SKIP_PHRASES)


def _translate_to_zh(text):
    try:
        resp = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text},
            headers=SCRAPE_HEADERS, timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return "".join(part[0] for part in data[0] if part[0])
    except Exception:
        return ""


_GNEWS_ARTICLE_RE = re.compile(r"news\.google\.com/rss/articles/")
_URL_DATE_RE      = re.compile(r"[/_-](20\d{2})[/_-](\d{2})[/_-](\d{2})(?:[/_.-]|$)")
_PAGE_DATE_PATS   = [
    re.compile(r'"datePublished"\s*:\s*"(20\d{2}-\d{2}-\d{2})'),
    re.compile(r'"datePublished":"(20\d{2}-\d{2}-\d{2})'),
    re.compile(r'article:published_time"\s+content="(20\d{2}-\d{2}-\d{2})'),
    re.compile(r'itemprop="datePublished"[^>]+content="(20\d{2}-\d{2}-\d{2})'),
    re.compile(r'name="(?:pubdate|publishdate|publish-date|date|article:published_time)"\s+content="(20\d{2}-\d{2}-\d{2})'),
    re.compile(r'<time[^>]+datetime="(20\d{2}-\d{2}-\d{2})'),
]


def _resolve_gnews_url(rss_link, session):
    """Resolve a news.google.com/rss/articles/<blob> link to the real publisher URL.

    Google stopped 302-redirecting these to the publisher; the blob is now an opaque
    signed token that only the DotsSplashUi/batchexecute endpoint can expand. Returns
    the publisher URL, or None on any failure. Links that are already direct publisher
    URLs are returned unchanged.
    """
    if not _GNEWS_ARTICLE_RE.search(rss_link):
        return rss_link
    try:
        html = session.get(rss_link, headers=SCRAPE_HEADERS, timeout=15).text
        art = re.search(r'data-n-a-id="([^"]+)"', html).group(1)
        sig = re.search(r'data-n-a-sg="([^"]+)"', html).group(1)
        ts  = re.search(r'data-n-a-ts="([^"]+)"', html).group(1)
        inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,'
                 'null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
                 '"%s",%s,"%s"]' % (art, ts, sig))
        body = "f.req=" + requests.utils.quote(json.dumps([[["Fbv4je", inner, None, "generic"]]]))
        resp = session.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={**SCRAPE_HEADERS,
                     "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data=body, timeout=20,
        ).text
        m = re.search(r'https?://(?!news\.google\.com|www\.google\.com)[^\\"\]]+', resp)
        return m.group(0) if m else None
    except Exception:
        return None


def _article_pub_date(url, session):
    """Best-effort true publication date ('YYYY-MM-DD') for a publisher URL: a date in
    the URL path first, then common date meta tags on the page. None if undeterminable
    (paywall / bot-block / no machine-readable date)."""
    m = _URL_DATE_RE.search(url)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    try:
        r = session.get(url, headers=SCRAPE_HEADERS, timeout=12)
        if r.status_code != 200:
            return None
        for pat in _PAGE_DATE_PATS:
            m = pat.search(r.text)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def fetch_and_save_index_news(lookback_days=7, max_age_days=2):
    """Homepage "Index Membership News" feed.

    Google News RSS is queried with narrow membership-change phrases ("added to S&P 500",
    etc.). Those queries return few real hits, so Google pads them with months-old
    articles carrying a *re-surfaced* pubDate that looks fresh. We therefore resolve every
    candidate to its publisher page, read the real publish date, and only ADD it if that
    date is within `max_age_days`; anything older or unconfirmable is skipped. Items that
    are already in the file stay (see the merge below) — this is a gate on what gets
    published, not a filter on what the homepage shows.

    max_age_days is 2, not 1, on purpose: this job runs ~daily, so a story published
    yesterday but indexed by Google *after* yesterday's run would be missed entirely if
    we only accepted same-day items. Two days gives that late-arriving news one more
    chance to be picked up.

    `lookback_days` is only a cheap pubDate pre-filter to bound how many links we resolve
    (re-surfacing makes articles look newer, never older, so a pubDate already older than
    a few days is safe to skip without a network round-trip).
    """
    print("Fetching index membership news...")
    cutoff    = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    all_items = []

    for label, query in _NEWS_QUERIES:
        url = (
            "https://news.google.com/rss/search"
            f"?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        )
        try:
            resp = requests.get(url, headers=SCRAPE_HEADERS, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  [news] {label}: {e}")
            continue

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            print(f"  [news] XML parse error for {label}: {e}")
            continue

        for item in root.findall(".//item"):
            title   = (item.findtext("title")  or "").strip()
            pub_raw = (item.findtext("pubDate") or "").strip()
            source  = (item.findtext("source")  or "").strip()
            link    = (item.findtext("link")    or "").strip()
            try:
                pub_dt = datetime.strptime(pub_raw, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if pub_dt < cutoff or _is_retrospective(title):
                continue
            all_items.append({
                "category": label,
                "date":     pub_dt.strftime("%Y-%m-%d"),
                "title":    title,
                "source":   source,
                "link":     link,
            })

    if not all_items:
        print("  [news] 0 items fetched (likely a transient RSS/network failure) — leaving existing index_news.json untouched")
        return

    path = os.path.join(DATA_DIR, "index_news.json")
    try:
        with open(path, encoding="utf-8") as f:
            existing = json.load(f).get("items", [])
    except (FileNotFoundError, ValueError):
        existing = []

    def _key(title, source=""):
        # Google returns the same story from many outlets with the source appended to the
        # title ("... - Yahoo Finance" / "... - TradingView"); strip that and non-alnum so
        # near-identical headlines collapse to one.
        t = title or ""
        if source and t.endswith(" - " + source):
            t = t[: -(len(source) + 3)]
        return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()

    known = ({it.get("link", "") for it in existing}
             | {_key(it.get("title", ""), it.get("source", "")) for it in existing})

    # A published item stays put once it's in the file ("once published, keep it there").
    # New items are only ADDED if their *real* publish date is within max_age_days — Google
    # News RSS pads these narrow phrase queries with months-old articles carrying a
    # re-surfaced pubDate, so verify against the publisher page before publishing.
    today   = datetime.now(timezone.utc).date()
    session = requests.Session()
    added   = []
    for it in all_items:
        k = _key(it["title"], it["source"])
        if it["link"] in known or k in known:
            continue
        known.add(it["link"]); known.add(k)
        resolved = _resolve_gnews_url(it["link"], session)
        if resolved and resolved in known:
            time.sleep(0.2)
            continue
        real = _article_pub_date(resolved, session) if resolved else None
        if not real:
            print(f"  [news] skip (real date unverifiable): {it['title'][:70]}")
            time.sleep(0.25)
            continue
        try:
            age = (today - datetime.strptime(real, "%Y-%m-%d").date()).days
        except ValueError:
            time.sleep(0.25)
            continue
        if age < 0 or age > max_age_days:
            print(f"  [news] skip (real date {real}, {age}d old): {it['title'][:70]}")
            time.sleep(0.25)
            continue
        it["date"] = real
        it["link"] = resolved
        known.add(resolved)
        suffix = " - " + it["source"]
        clean  = it["title"][:-len(suffix)] if it["title"].endswith(suffix) else it["title"]
        it["title_cn"] = _translate_to_zh(clean)
        added.append(it)
        time.sleep(0.25)

    # Merge new items on top of everything already published; drop only the genuinely
    # ancient (kept RETENTION_DAYS so a story stays on the page for months), newest first.
    RETENTION_DAYS = 120
    cutoff_date = today - timedelta(days=RETENTION_DAYS)
    merged, seen = [], set()
    for it in added + existing:
        k = _key(it.get("title", ""), it.get("source", ""))
        if it.get("link", "") in seen or k in seen:
            continue
        seen.add(it.get("link", "")); seen.add(k)
        try:
            if datetime.strptime(it["date"], "%Y-%m-%d").date() < cutoff_date:
                continue
        except (KeyError, ValueError):
            pass
        merged.append(it)
    merged.sort(key=lambda x: x.get("date", ""), reverse=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "fetched":        datetime.now().strftime("%Y-%m-%d"),
            "max_age_days":   max_age_days,
            "retention_days": RETENTION_DAYS,
            "items":          merged,
        }, f, ensure_ascii=False, indent=2)
    print(f"  [news] {len(added)} new item(s); {len(merged)} total after merge -> {path}")




# =========================
# DIAGNOSTIC: compare our fundamentals vs Yahoo Finance (internal validation only)
# yfinance accesses Yahoo's unofficial endpoints — never expose this data to users.
# =========================

def compare_with_yfinance(df):
    """
    Compare our Price, Volume, MktCap, PE, EPS against Yahoo Finance via yfinance.
    Writes a human-readable log to archive/compare_<date>.log.
    Flags diffs > 10% and always shows top-10 per metric regardless of threshold.
    """
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    log_path = os.path.join(ARCHIVE_DIR, f"compare_{DATE_STR}.log")

    def _write_error(msg):
        with open(log_path, "w", encoding="utf-8") as _f:
            _f.write(f"[compare] {msg}\n")
        print(f"[compare] {msg}")

    try:
        import yfinance as yf
    except ImportError:
        _write_error("yfinance not installed — run: pip install yfinance")
        return

    tickers = sorted(df["Ticker"].unique().tolist())

    # Fetch from yfinance in bulk
    print(f"[compare] fetching {len(tickers)} tickers from Yahoo Finance …")
    try:
        raw = yf.Tickers(" ".join(tickers))
    except Exception as e:
        _write_error(f"yfinance bulk fetch failed: {e}")
        return

    # Build our lookup: ticker → row
    our = {r["Ticker"]: r for r in df.to_dict("records")}

    THRESHOLD = 0.10  # 10 %

    # (our_col, yf_extractor, scale_factor)
    # scale_factor converts our value to the same units as yfinance before comparing.
    # VolumeM is in millions; yfinance returns raw shares.
    metrics = {
        "PRICE":  ("Price",     lambda info: info.get("currentPrice") or info.get("regularMarketPrice"), 1),
        "VOLUME": ("VolumeM",   lambda info: info.get("volume") or info.get("regularMarketVolume"),      1e6),
        "MKTCAP": ("MarketCap", lambda info: info.get("marketCap"),                                      1e9),
        "PE":     ("PE",        lambda info: info.get("trailingPE"),                                     1),
        "EPS":    ("EPS",       lambda info: info.get("trailingEps"),                                    1),
    }

    results = {m: [] for m in metrics}

    for ticker in tickers:
        try:
            full_info = raw.tickers[ticker].info
        except Exception:
            continue

        row = our.get(ticker, {})

        for metric, (our_key, yf_fn, scale) in metrics.items():
            our_val = row.get(our_key)
            try:
                yf_val = yf_fn(full_info)
            except Exception:
                yf_val = None

            if our_val is None or yf_val is None:
                continue

            try:
                our_f  = float(our_val) * scale   # convert to yfinance units
                yf_f   = float(yf_val)
                if yf_f == 0 or math.isnan(our_f) or math.isnan(yf_f):
                    continue
                diff = abs(our_f - yf_f) / abs(yf_f)
                if math.isnan(diff):
                    continue
                results[metric].append((ticker, our_f / scale, yf_f / scale, diff))
            except (TypeError, ValueError):
                continue

    # Upcoming splits — announced/detected in data/splits.json but not yet effective.
    # Surfaced here so a split_guards.csv row can be added proactively, before EDGAR
    # lag causes a real market-cap/EPS discrepancy on the effective date.
    upcoming_splits = []
    try:
        with open(SPLITS_PATH, encoding="utf-8") as f:
            for tk, info in json.load(f).items():
                d = info.get("date", "")
                if d > DATE_STR:
                    upcoming_splits.append((tk, info.get("ratio"), d))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    upcoming_splits.sort(key=lambda x: x[2])

    # Write log
    lines = [
        f"Tiingo vs yfinance comparison — {DATE_STR}",
        f"Threshold: >{int(THRESHOLD*100)}% for all metrics",
    ]
    total_flagged = sum(1 for m in results for _, _, _, d in results[m] if d > THRESHOLD)
    lines.append(f"{total_flagged} flagged diffs above threshold")

    if upcoming_splits:
        lines += [
            "",
            "=" * 60,
            "UPCOMING SPLITS (effective date not yet reached)",
            "=" * 60,
            "Add a data/split_guards.csv row before the effective date to avoid a",
            "market-cap/EPS discrepancy once Tiingo adjusts prices but EDGAR still lags.",
            "",
        ]
        for tk, ratio, d in upcoming_splits:
            lines.append(f"  {tk:<8} ratio={ratio}  effective={d}")

    lines += [
        "",
        "=" * 60,
        "KNOWN EXPECTED DIFFERENCES (not bugs)",
        "=" * 60,
        "",
        "EPS / PE — hardcoded adjustments (our side intentional):",
        "  BRK-B   EDGAR EPS ÷ 1500  (Class A→B conversion)",
        "  BKNG    EDGAR EPS ÷ 25    (25-for-1 split Apr 2026; auto-disables after Q2 2026 10-Q)",
        "  CVNA    EDGAR EPS ÷ 5     (5-for-1 split May 2026; auto-disables after Q2 2026 10-Q)",
        "  KLAC    EDGAR EPS ÷ 10    (10-for-1 split Jun 2026; auto-disables after Q2 2026 10-Q)",
        "  DD      EDGAR EPS × 3     (1-for-3 reverse split Jun 2026; pre-split EPS ~-0.07; auto-disables when EDGAR EPS abs > 0.20 after Q2 2026 10-Q)",
        "  HON     EDGAR EPS × 2     (1-for-2 reverse split Jun 29 2026; pre-split EPS ~$3.21; auto-disables when EDGAR EPS abs > 4.0 after Q2/Q3 2026 10-Q)",
        "",
        "EPS / PE — inline XBRL fallback (company_facts has no data; we parse filing HTML):",
        "  V ERIE KKR STZ HSY BRK-B   US 10-Q/10-K  USD   TTM = quarters since last 10-K",
        "                                                  + Q4 derived (annual − 9M YTD).",
        "                                                  Fixed 2026-06-30 (commit 973b985):",
        "                                                  naive 4-quarter sum used to run",
        "                                                  before the Q4-derivation path and",
        "                                                  silently skipped the real Q4 (never",
        "                                                  filed as its own 10-Q), substituting",
        "                                                  a stale year-ago quarter instead.",
        "                                                  KKR 1.56→2.93, BRK-B 26.83→33.59,",
        "                                                  V 11.18→11.47, ERIE 12.37→10.93,",
        "                                                  STZ 11.82→9.61, HSY 4.90→5.37 — all",
        "                                                  now match yfinance.",
        "  ARM ASML CCEP FER PDD      20-F          —      annual only (no 10-Q filed; not",
        "                                                  affected by the bug above). ASML/",
        "                                                  CCEP/FER convert EUR→USD via daily",
        "                                                  ECB rate; PDD uses",
        "                                                  EarningsPerShareBasicAndDiluted.",
        "  NBIS                       6-K           USD    annual only (foreign private issuer,",
        "                                                  furnishes 6-K instead of 10-Q).",
        "  Diffs vs YF expected: foreign EPS is annual-only (no TTM); FX rate differs by fetch time.",
        "",
        "EPS / PE — null (still unavailable):",
        "  ARES TRI    Filed Form 25-NSE May 2026 — being removed from exchange listing.",
        "              Will drop out of S&P 500 / Nasdaq-100 universe on next rebalance.",
        "  FDXF        FedEx Freight spinoff (2026-06); only 8-K/Form 4 filed so far, no",
        "              10-Q/10-K yet — EPS unavailable until first quarterly filing.",
        "",
        "EPS / PE — TTM window vs YF annual anchor:",
        "  Large diffs (e.g. CI 23.61 vs YF 113.71) often mean YF is anchored to an older",
        "  annual 10-K that included a one-time gain/charge now outside our rolling TTM.",
        "  Our TTM = sum of 4 most recent quarters from EDGAR 10-Q/10-K filings.",
        "  YF trailingEps sources from data vendors and may reflect a different period.",
        "",
        "MKTCAP — shares outstanding overrides (SHARES_OUTSTANDING_OVERRIDE, our side intentional):",
        "  IBKR   1,697,000,000  (Class A 445M + IBG LLC membership units; EDGAR under-reports)",
        "  BX     1,222,000,000  (Class A 742M + Blackstone Holdings LP units)",
        "  DVN    1,153,000,000  (Coterra merger May 2026 doubled shares; EDGAR XBRL lags until Q2 2026 10-Q ~Aug 2026)",
        "  CVNA   shares × 5    (5-for-1 split May 2026; EDGAR pre-split ~219M Class A; heals after Q2 2026 10-Q ~Aug 2026)",
        "  KLAC   shares × 10   (10-for-1 split Jun 2026; EDGAR pre-split ~130.6M; heals after Q2 2026 10-Q ~Aug 2026)",
        "  DD     shares ÷ 3    (1-for-3 reverse split Jun 2026; EDGAR pre-split ~410M; heals after Q2 2026 10-Q ~Aug 2026)",
        "",
        "VOLUME — systematic offset:",
        "  Tiingo EOD volume includes extended-hours (pre/after market).",
        "  YF typically reports regular-session only. Expect ours ~1.5-2x YF across the board.",
        "=" * 60,
    ]

    for metric in metrics:
        rows_sorted = sorted(results[metric], key=lambda x: x[3], reverse=True)
        flagged = [r for r in rows_sorted if r[3] > THRESHOLD]
        top10   = rows_sorted[:10]

        lines.append("")
        lines.append("-" * 60)
        lines.append(f"{metric}  -- {len(flagged)} flagged (>{int(THRESHOLD*100)}%)")

        def _fmt(t, o, y, d):
            flag = " ***" if d > THRESHOLD else ""
            if metric == "MKTCAP":
                return f"    {t:<8} ours=${o:.2f}B  yf=${y:.2f}B  diff={d*100:.1f}%{flag}"
            elif metric in ("PE", "EPS"):
                return f"    {t:<8} ours={o:.3f}  yf={y:.3f}  diff={d*100:.1f}%{flag}"
            else:
                return f"    {t:<8} ours={o:.2f}  yf={y:.2f}  diff={d*100:.1f}%{flag}"

        MAX_FLAGGED = 20
        if flagged:
            lines.append(f"  FLAGGED (top {min(len(flagged), MAX_FLAGGED)} of {len(flagged)}):")
            for row in flagged[:MAX_FLAGGED]:
                lines.append(_fmt(*row))
        lines.append("  TOP 10 LARGEST DIFF:")
        for row in top10:
            lines.append(_fmt(*row))

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[compare] log written to {log_path}")


# =========================
# MAIN
# =========================

if __name__ == "__main__":

    if not USE_YFINANCE and not TIINGO_API_KEY:
        sys.exit("ERROR: TIINGO_API_KEY environment variable is not set.")

    # EDGAR-only midnight run: refresh fundamentals cache, skip market scan entirely.
    # Tiingo-free (and key-optional) in yfinance mode — company names fall back to EDGAR.
    if EDGAR_ONLY:
        print("EDGAR_ONLY — refreshing fundamentals cache from SEC EDGAR …")
        tickers, _, _, _ = get_tickers()
        _fund_cache.clear()  # force full re-fetch so new filings are picked up
        tiingo_meta = {} if (USE_YFINANCE or not TIINGO_API_KEY) else prefetch_tiingo_meta(tickers)
        prefetch_fundamentals(tickers, tiingo_meta)
        print("EDGAR refresh complete.")
        sys.exit(0)

    # FORCE_RUN=1 bypasses the holiday and probe checks (use for local testing).
    FORCE_RUN = os.environ.get("FORCE_RUN", "").lower() in ("1", "true", "yes")

    today = datetime.now(pytz.timezone('America/New_York')).date()
    if not FORCE_RUN and is_market_holiday(today):
        print(f"Market holiday ({today}) — skipping scan.")
        sys.exit(0)

    if today.weekday() >= 5 and not FORCE_RUN:
        print(f"Weekend ({today}) — cron should not fire; skipping.")
        sys.exit(0)

    if USE_YFINANCE:
        # yfinance's EOD data is available promptly after close (no incremental per-ticker
        # publish delay the way Tiingo has), so there's nothing to probe/wait for here.
        # _TIINGO_LAST_DATE is provisional — refined below from the actual scan results
        # (majority vote across df["Date"]) before the stale-ticker exclusion runs, same
        # mechanism the Tiingo path uses, just confirmed after the fetch instead of before.
        print("OHLCV_SOURCE=yfinance — skipping Tiingo publish-delay probe.")
        data_confirmed = True

        # SKIP_IF_COMPLETE=1 is set by the 4:30 PM ET primary cron and the ~midnight ET
        # safety-net cron (0 4 * * 2-6 — see scanner.yml). If latest.json already carries
        # a complete, non-partial update for the most recent *completed* trading session,
        # there's nothing to do — exit before a redundant scan (and, for the primary cron,
        # before the workflow's video steps would build a duplicate). "Completed" = today's
        # session only counts once its close has passed (~4 PM ET); before that, or after
        # midnight, the most recent completed session is the prior trading day. On a normal
        # untouched day latest.json still holds yesterday's date here, so the scan proceeds.
        # (In Tiingo mode the equivalent check lives further down, in the probe path.)
        if os.environ.get("SKIP_IF_COMPLETE", "").lower() in ("1", "true", "yes"):
            try:
                _now_et = datetime.now(pytz.timezone("America/New_York"))
                _end = _now_et.date()
                if (_now_et.hour, _now_et.minute) < (16, 5):
                    _end = _end - timedelta(days=1)
                _recent = get_trading_days((_end - timedelta(days=10)).strftime("%Y-%m-%d"),
                                           _end.strftime("%Y-%m-%d"))
                _expected = _recent[-1] if _recent else None
                with open(OUTPUT_JSON) as f:
                    _existing = json.load(f)
                if _expected and _existing.get("date") == _expected and not _existing.get("partialUpdate", False):
                    print(f"{_expected} already fully updated — skipping redundant scan.")
                    sys.exit(0)
                print(f"Data stale (have {_existing.get('date')}, expected {_expected}) — scanning.")
            except Exception as e:
                print(f"SKIP_IF_COMPLETE check failed ({e}) — proceeding with scan.")
    elif FORCE_RUN:
        print("FORCE_RUN=1 — skipping market probe, using latest available Tiingo data.")
        data_confirmed = True
        _discover = _tiingo_get(
            "/tiingo/daily/spy/prices",
            params={
                "startDate": (datetime.now(pytz.timezone('America/New_York')) - timedelta(days=7)).strftime("%Y-%m-%d"),
                "endDate": DATE_STR,
            },
        )
        if _discover:
            _TIINGO_LAST_DATE = _parse_tiingo_date(_discover[-1].get("date", "")) or DATE_STR
            print(f"FORCE_RUN: Tiingo latest date confirmed = {_TIINGO_LAST_DATE}")
    else:
        # Probe Tiingo for today's SPY data. Retry every 30 min for up to 90 min
        # to handle data publication delays (especially the 6 PM scan).
        PROBE_RETRIES   = int(os.environ.get("PROBE_RETRIES", "3"))
        PROBE_WAIT_SECS = 30 * 60
        data_confirmed  = False

        for attempt in range(1, PROBE_RETRIES + 1):
            probe = _tiingo_get(
                "/tiingo/daily/spy/prices",
                params={"startDate": DATE_STR, "endDate": DATE_STR},
            )
            if probe:
                latest_bar_date = _parse_tiingo_date(probe[-1].get("date", ""))
                if latest_bar_date >= DATE_STR:
                    _TIINGO_LAST_DATE = latest_bar_date
                    print(f"Tiingo data confirmed for {latest_bar_date} — proceeding.")
                    data_confirmed = True
                    break
                else:
                    print(f"Attempt {attempt}/{PROBE_RETRIES}: latest bar is {latest_bar_date}, not {DATE_STR}. "
                          f"Waiting {PROBE_WAIT_SECS // 60} min …")
            else:
                print(f"Attempt {attempt}/{PROBE_RETRIES}: SPY probe returned no data. "
                      f"Waiting {PROBE_WAIT_SECS // 60} min …")
            if attempt < PROBE_RETRIES:
                time.sleep(PROBE_WAIT_SECS)

        if not data_confirmed:
            print(f"Today's data not available after {PROBE_RETRIES} attempts — special closure or delay, skipping.")
            sys.exit(0)

        # SKIP_IF_COMPLETE (Tiingo path): skip if latest.json already holds a complete,
        # non-partial update for the confirmed latest session — nothing left to do.
        # Set by the 4:30 PM primary, the 5:00 PM retry, and the ~midnight safety-net
        # crons (see scanner.yml); 5:30/6:30 PM stay unconditional safety nets. The
        # probe above already resolved _TIINGO_LAST_DATE to the real latest session,
        # so no separate wall-clock date math is needed on this path.
        if os.environ.get("SKIP_IF_COMPLETE", "").lower() in ("1", "true", "yes"):
            try:
                with open(OUTPUT_JSON) as f:
                    _existing = json.load(f)
                if _existing.get("date") == _TIINGO_LAST_DATE and not _existing.get("partialUpdate", False):
                    print(f"{_TIINGO_LAST_DATE} already fully updated (0 stale tickers) — skipping redundant rescan.")
                    sys.exit(0)
            except Exception:
                pass

    print("Running Baizora scanner (Tiingo) …")

    # 1. Update index lists, detect membership changes
    _, _, changes_entry = update_and_detect_changes()

    # 2. Write index_changes.json
    load_update_index_changes(changes_entry)

    # 3. (archive cleanup disabled — all daily CSVs kept in git permanently)

    # 4. Run scan
    df, candles_out, smas_out, weekly_raw, trading_days = scan()

    # 4a. yfinance mode: confirm the scan date from the actual results (majority vote
    # across df["Date"]) rather than probing beforehand — see the USE_YFINANCE branch
    # above. Feeds the same stale-ticker exclusion logic below unchanged.
    if USE_YFINANCE and not df.empty and "Date" in df.columns:
        _TIINGO_LAST_DATE = df["Date"].value_counts().idxmax()
        print(f"yfinance: confirmed scan date = {_TIINGO_LAST_DATE} ({(df['Date'] == _TIINGO_LAST_DATE).sum()}/{len(df)} tickers)")

    # 4b. Exclude tickers Tiingo hasn't published for _TIINGO_LAST_DATE yet.
    # Tiingo sometimes publishes EOD data incrementally across tickers rather than all at
    # once — without this, a stale ticker's old bar silently rides along in an otherwise
    # "Updated" payload (e.g. SATS sat 8 days stale on 2026-07-01 while 516/517 other
    # tickers were current, with nothing flagging it). Any mismatch, even one day, is
    # excluded — a later scheduled/manual run will pick it back up once Tiingo catches up.
    if not df.empty and "Date" in df.columns:
        stale_mask = df["Date"] != _TIINGO_LAST_DATE
        _STALE_TICKERS_EXCLUDED = sorted(df.loc[stale_mask, "Ticker"].tolist())
        if _STALE_TICKERS_EXCLUDED:
            print(f"STALE DATA: excluding {len(_STALE_TICKERS_EXCLUDED)} ticker(s) not yet "
                  f"updated to {_TIINGO_LAST_DATE}: {_STALE_TICKERS_EXCLUDED}")
            df = df[~stale_mask].reset_index(drop=True)
            candles_out = {t: c for t, c in candles_out.items() if t not in _STALE_TICKERS_EXCLUDED}
            smas_out    = {t: s for t, s in smas_out.items()    if t not in _STALE_TICKERS_EXCLUDED}
            weekly_raw  = {t: w for t, w in weekly_raw.items()  if t not in _STALE_TICKERS_EXCLUDED}

    print(df.head(10))

    # 5. Data quality check
    check_data_quality(df, candles_out, trading_days)

    # 6. Export results to latest.json + archive CSV + free-tier rotation
    export(df)

    # 6b. Export candle data
    export_candles(candles_out, smas_out, trading_days)
    export_candles_weekly(weekly_raw)

    # 6c. Export daily digest + downloadable briefing for homepage card
    export_daily_digest(df)

    # 6d. Export rolling 5-session BaizScore history for homepage top-10 card
    export_score_history(df)

    # 6e. Index membership news
    fetch_and_save_index_news()

    # 9. Diagnostic comparison vs Yahoo Finance (internal only — never served to users)
    try:
        compare_with_yfinance(df)
    except Exception as _e:
        print(f"[compare] skipped: {_e}")

    print("Done")
