import pandas as pd
import numpy as np
import time
import json
import os
import glob
import requests
from bs4 import BeautifulSoup
import sys
from datetime import date, datetime, timedelta, timezone
import xml.etree.ElementTree as ET

# =========================
# CONFIG
# =========================

MASSIVE_API_KEY  = os.environ["MASSIVE_API_KEY"]
MASSIVE_BASE     = "https://api.massive.com"

DATE_STR         = datetime.now(timezone.utc).strftime("%Y-%m-%d")
DATA_DIR         = "data"
ARCHIVE_DIR      = "archive"
OHLCV_CACHE_DIR  = os.path.join(DATA_DIR, "ohlcv_cache")
FUND_CACHE_FILE  = os.path.join(DATA_DIR, "fundamentals_cache.json")
FUND_CACHE_TTL_DAYS = 8   # safety net — Saturday rebuild clears cache, this catches any missed weeks

os.makedirs(DATA_DIR,        exist_ok=True)
os.makedirs(ARCHIVE_DIR,     exist_ok=True)
os.makedirs(OHLCV_CACHE_DIR, exist_ok=True)

TIMEFRAMES = {
    "2W": 10,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "9M": 189,
    "1Y": 252,
}

OUTPUT_JSON = os.path.join(DATA_DIR,    "latest.json")
OUTPUT_CSV  = os.path.join(ARCHIVE_DIR, f"results_{DATE_STR}.csv")

SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# =========================
# MASSIVE API HELPERS
# =========================

_massive_session = requests.Session()
_massive_session.headers.update({
    "Authorization": f"Bearer {MASSIVE_API_KEY}",
    "Content-Type":  "application/json",
})


def _massive_get(path, params=None, retries=3):
    url = MASSIVE_BASE + path
    for attempt in range(retries):
        try:
            r = _massive_session.get(url, params=params, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt
                print(f"  [massive] rate-limited, waiting {wait}s …")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt < retries - 1:
                time.sleep(1)
            else:
                print(f"  [massive] GET {path} failed: {e}")
                return None
    return None


# =========================
# NYSE HOLIDAY DETECTION
# (placed early — needed by get_trading_days)
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


# Special one-off market closures (presidential funerals, national days of mourning)
_SPECIAL_CLOSURES = {
    date(2025, 1, 9),   # Jimmy Carter state funeral
}


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
    return d in nyse_holidays(d.year) or d in _SPECIAL_CLOSURES


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
    "OIL ROYALTY TRADERS":                                               "Energy",
    "COGENERATION SERVICES & SMALL POWER PRODUCERS":                     "Utilities",
    "Crude Petroleum & Natural Gas":                                    "Energy",
    "Oil & Gas Field Services":                                         "Energy",
    "Petroleum Refining":                                               "Energy",
    "Coal Mining":                                                      "Energy",
    "Pipelines (Except Natural Gas)":                                   "Energy",
    "Natural Gas Transmission":                                         "Energy",
    "Natural Gas Transmission & Distribution":                          "Energy",
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
    "COMMUNICATIONS SERVICES, NEC":                                      "Communication Services",
    "SERVICES-ADVERTISING AGENCIES":                                     "Communication Services",
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

    # ── Massive API returns SIC descriptions in ALL CAPS with abbreviations ──
    # Technology
    "COMMUNICATIONS EQUIPMENT, NEC":                                    "Technology",
    "ELECTRONIC CONNECTORS":                                             "Technology",
    "INSTRUMENTS FOR MEAS & TESTING OF ELECTRICITY & ELEC SIGNALS":    "Technology",
    "OPTICAL INSTRUMENTS & LENSES":                                     "Technology",
    "WHOLESALE-ELECTRONIC PARTS & EQUIPMENT, NEC":                      "Technology",

    # Healthcare
    "LABORATORY ANALYTICAL INSTRUMENTS":                                "Healthcare",
    "ORTHOPEDIC, PROSTHETIC & SURGICAL APPLIANCES & SUPPLIES":          "Healthcare",
    "SERVICES-COMMERCIAL PHYSICAL & BIOLOGICAL RESEARCH":               "Healthcare",
    "SERVICES-MISC HEALTH & ALLIED SERVICES, NEC":                      "Healthcare",
    "WHOLESALE-DRUGS, PROPRIETARIES & DRUGGISTS' SUNDRIES":             "Healthcare",
    "X-RAY APPARATUS & TUBES & RELATED IRRADIATION APPARATUS":          "Healthcare",

    # Financial Services
    "SECURITY & COMMODITY BROKERS, DEALERS, EXCHANGES & SERVICES":      "Financial Services",
    "SECURITY BROKERS, DEALERS & FLOTATION COMPANIES":                  "Financial Services",
    "SERVICES-CONSUMER CREDIT REPORTING, COLLECTION AGENCIES":          "Financial Services",

    # Consumer Cyclical
    "APPAREL & OTHER FINISHD PRODS OF FABRICS & SIMILAR MATL":          "Consumer Cyclical",
    "GENERAL BLDG CONTRACTORS - RESIDENTIAL BLDGS":                      "Consumer Cyclical",
    "LEATHER & LEATHER PRODUCTS":                                        "Consumer Cyclical",
    "MEN'S & BOYS' FURNISHGS, WORK CLOTHG, & ALLIED GARMENTS":           "Consumer Cyclical",
    "RETAIL-RETAIL STORES, NEC":                                         "Consumer Cyclical",
    "RETAIL-RADIO, TV & CONSUMER ELECTRONICS STORES":                    "Consumer Cyclical",
    "WHOLESALE-MOTOR VEHICLE SUPPLIES & NEW PARTS":                      "Consumer Cyclical",
    "GAMES, TOYS & CHILDREN'S VEHICLES (NO DOLLS & BICYCLES)":          "Consumer Cyclical",
    "OPERATIVE BUILDERS":                                                "Consumer Cyclical",
    "RETAIL-BUILDING MATERIALS, HARDWARE, GARDEN SUPPLY":               "Consumer Cyclical",
    "RUBBER & PLASTICS FOOTWEAR":                                        "Consumer Cyclical",

    # Consumer Defensive
    "BOTTLED & CANNED SOFT DRINKS & CARBONATED WATERS":                 "Consumer Defensive",
    "CANNED, FROZEN & PRESERVD FRUIT, VEG & FOOD SPECIALTIES":          "Consumer Defensive",
    "CANNED, FRUITS, VEG, PRESERVES, JAMS & JELLIES":                   "Consumer Defensive",
    "CIGARETTES":                                                        "Consumer Defensive",
    "FATS & OILS":                                                       "Consumer Defensive",
    "MISCELLANEOUS FOOD PREPARATIONS & KINDRED PRODUCTS":               "Consumer Defensive",
    "PERFUMES, COSMETICS & OTHER TOILET PREPARATIONS":                  "Consumer Defensive",
    "MEAT PACKING PLANTS":                                               "Consumer Defensive",
    "WHOLESALE-GROCERIES & RELATED PRODUCTS":                            "Consumer Defensive",
    "POULTRY SLAUGHTERING AND PROCESSING":                               "Consumer Defensive",
    "SPECIALTY CLEANING, POLISHING AND SANITATION PREPARATIONS":         "Consumer Defensive",

    # Industrials
    "AIR-COND & WARM AIR HEATG EQUIP & COMM & INDL REFRIG EQUIP":       "Industrials",
    "AUTO CONTROLS FOR REGULATING RESIDENTIAL & COMML ENVIRONMENTS":    "Industrials",
    "CUTLERY, HANDTOOLS & GENERAL HARDWARE":                             "Industrials",
    "ELECTRICAL WORK":                                                   "Industrials",
    "INDUSTRIAL INSTRUMENTS FOR MEASUREMENT, DISPLAY, AND CONTROL":     "Industrials",
    "MEASURING & CONTROLLING DEVICES, NEC":                              "Industrials",
    "MISCELLANEOUS MANUFACTURING INDUSTRIES":                            "Industrials",
    "ORDNANCE & ACCESSORIES, (NO VEHICLES/GUIDED MISSILES)":             "Industrials",
    "PUMPS & PUMPING EQUIPMENT":                                         "Industrials",
    "REFUSE SYSTEMS":                                                    "Industrials",
    "SEARCH, DETECTION, NAVIGATION, GUIDANCE, AERONAUTICAL SYS":        "Industrials",
    "SERVICES-BUSINESS SERVICES, NEC":                                   "Industrials",
    "SERVICES-DETECTIVE, GUARD & ARMORED CAR SERVICES":                  "Industrials",
    "SERVICES-ENGINEERING, ACCOUNTING, RESEARCH, MANAGEMENT":           "Industrials",
    "SERVICES-TO DWELLINGS & OTHER BUILDINGS":                           "Industrials",
    "WHOLESALE-DURABLE GOODS":                                           "Industrials",
    "DRAWING & INSULATING OF NONFERROUS WIRE":                           "Industrials",
    "MISCELLANEOUS FABRICATED METAL PRODUCTS":                           "Industrials",
    "MOTORS & GENERATORS":                                               "Industrials",
    "SERVICES-EQUIPMENT RENTAL & LEASING, NEC":                          "Industrials",
    "SERVICES-MANAGEMENT SERVICES":                                      "Industrials",
    "WHOLESALE-MISC DURABLE GOODS":                                      "Industrials",
    "HEATING EQUIP, EXCEPT ELEC & WARM AIR; & PLUMBING FIXTURES":       "Industrials",

    # Basic Materials
    "CEMENT, HYDRAULIC":                                                 "Basic Materials",
    "GOLD AND SILVER ORES":                                              "Basic Materials",
    "METAL CANS":                                                        "Basic Materials",
    "PAINTS, VARNISHES, LACQUERS, ENAMELS & ALLIED PRODS":               "Basic Materials",
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
    """Map a Massive SIC description to a standard GICS-style sector name.
    Case-insensitive — Massive returns SIC descriptions in ALL CAPS."""
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
    try:
        response = requests.get(url, headers=SCRAPE_HEADERS, timeout=30)
        if response.status_code != 200:
            print(f"Failed to fetch {url}: HTTP {response.status_code}")
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table")
        if not table:
            print(f"No table found at {url}")
            return []
        symbols = []
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) > 2:
                symbol = cols[2].text.strip()
                if symbol:
                    symbols.append(symbol)
        return symbols
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []


def update_and_detect_changes():
    sp500_path     = os.path.join(DATA_DIR, "sp500_symbols.txt")
    nasdaq100_path = os.path.join(DATA_DIR, "nasdaq100_symbols.txt")

    old_sp500     = set()
    old_nasdaq100 = set()
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
        "sp500": {
            "added":   sorted(new_sp500 - old_sp500),
            "removed": sorted(old_sp500 - new_sp500),
        },
        "nasdaq100": {
            "added":   sorted(new_nasdaq100 - old_nasdaq100),
            "removed": sorted(old_nasdaq100 - new_nasdaq100),
        },
    }

    has_changes = (
        changes["sp500"]["added"]     or changes["sp500"]["removed"] or
        changes["nasdaq100"]["added"] or changes["nasdaq100"]["removed"]
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
        if any(
            e[k].get("added") or e[k].get("removed")
            for k in ("sp500", "nasdaq100")
        )
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
            date_str  = fname.replace("results_", "").replace(".csv", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff:
                os.remove(filepath)
                print(f"Deleted old archive: {fname}")
        except Exception:
            pass


def cleanup_old_ohlcv_cache():
    """Delete per-day cache files older than 2 years — they are never needed again."""
    cutoff  = datetime.now() - timedelta(days=730)
    pattern = os.path.join(OHLCV_CACHE_DIR, "*.json")
    removed = 0
    for filepath in glob.glob(pattern):
        fname = os.path.basename(filepath)
        try:
            file_date = datetime.strptime(fname.replace(".json", ""), "%Y-%m-%d")
            if file_date < cutoff:
                os.remove(filepath)
                removed += 1
        except Exception:
            pass
    if removed:
        print(f"Deleted {removed} old OHLCV cache files.")


# =========================
# UNIVERSE
# =========================

def get_sp500():
    path = os.path.join(DATA_DIR, "sp500_symbols.txt")
    with open(path, "r") as f:
        tickers = f.read().splitlines()
    return [t.strip().replace(".", "-") for t in tickers if t.strip()]


def get_nasdaq100():
    path = os.path.join(DATA_DIR, "nasdaq100_symbols.txt")
    with open(path, "r") as f:
        tickers = f.read().splitlines()
    return [t.strip().replace(".", "-") for t in tickers if t.strip()]


def get_tickers():
    sp500     = get_sp500()
    nasdaq100 = get_nasdaq100()

    clean = [t.replace(".", "-") for t in sp500 + nasdaq100 if isinstance(t, str)]
    tickers = sorted(set(clean))

    sp_set = set(t.replace(".", "-") for t in sp500     if isinstance(t, str))
    nd_set = set(t.replace(".", "-") for t in nasdaq100 if isinstance(t, str))

    return tickers, sp_set, nd_set


# =========================
# TICKER ALIASES
# Handles renames: when a company changes its ticker, old data lives under
# the previous symbol. Add new entries here as renames happen.
# =========================

TICKER_ALIASES = {
    "BNY": "BK",    # Bank of New York Mellon: traded as BK, adopted BNY ticker later.
    # Add entries here when a company renames its ticker symbol.
    # Format: "NEW_TICKER": "OLD_TICKER"
    # Spinoffs (new companies) should NOT be added — their short history is correct.
}

# =========================
# TICKER SECTOR OVERRIDES
# For tickers where Massive returns no SIC description (mostly foreign-listed
# companies and hyphenated tickers). Checked before SIC mapping.
# =========================

TICKER_SECTOR_OVERRIDE = {
    "ARM":   "Technology",           # ARM Holdings (UK chip designer)
    "ASML":  "Technology",           # ASML (Netherlands, semiconductor equipment)
    "BF-B":  "Consumer Defensive",   # Brown-Forman (spirits)
    "BRK-B": "Financial Services",   # Berkshire Hathaway (conglomerate)
    "CCEP":  "Consumer Defensive",   # Coca-Cola Europacific Partners (beverages)
    "CTSH":  "Technology",           # Cognizant (IT services)
    "CTVA":  "Basic Materials",      # Corteva Agriscience (agricultural chemicals)
    "FER":   "Industrials",          # Ferrovial (Spanish infrastructure)
    "PDD":   "Consumer Cyclical",    # PDD Holdings / Pinduoduo (Chinese e-commerce)
    "PKG":   "Basic Materials",      # Packaging Corp of America
    "PM":    "Consumer Defensive",   # Philip Morris International (tobacco)
    "RL":    "Consumer Cyclical",    # Ralph Lauren (apparel)
    "TRI":   "Communication Services", # Thomson Reuters (media/data)
}

# =========================
# OHLCV GROUPED CACHE
# =========================

def get_trading_days(from_date, to_date):
    """Return list of YYYY-MM-DD strings for NYSE market-open days in range."""
    days    = []
    current = datetime.strptime(from_date, "%Y-%m-%d").date()
    end     = datetime.strptime(to_date,   "%Y-%m-%d").date()
    while current <= end:
        if current.weekday() < 5 and not is_market_holiday(current):
            days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


def fetch_grouped_bars(date_str, universe_set):
    """
    Fetch all US equity bars for one trading day via the grouped daily endpoint.
    One API call returns every US stock; we filter to our universe before saving.
    Returns {ticker: {"c": float, "v": float}}.
    """
    path = f"/v2/aggs/grouped/locale/us/market/stocks/{date_str}"
    data = _massive_get(path, params={"adjusted": "true"})
    if not data or not data.get("results"):
        return {}
    # Build reverse alias lookup: old ticker → current ticker
    alias_reverse = {v: k for k, v in TICKER_ALIASES.items()}

    out = {}
    for bar in data["results"]:
        ticker = bar.get("T")
        if not ticker:
            continue
        # Accept current ticker OR its old alias name
        target = ticker if ticker in universe_set else alias_reverse.get(ticker)
        if not target:
            continue
        c = bar.get("c")
        v = bar.get("v")
        if c is not None and v is not None:
            out[target] = {
                "o": bar.get("o"),
                "h": bar.get("h"),
                "l": bar.get("l"),
                "c": float(c),
                "v": float(v),
            }
    return out


def fetch_benchmark_bars(ticker, from_date, to_date):
    """Fetch daily close prices for a benchmark ticker (e.g. SPY) not in the universe cache."""
    path = f"/v2/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}"
    data = _massive_get(path, params={"adjusted": "true", "sort": "asc", "limit": 50000})
    if not data or not data.get("results"):
        return None
    rows = [
        {"Date": datetime.utcfromtimestamp(b["t"] / 1000).strftime("%Y-%m-%d"), "Close": b["c"]}
        for b in data["results"] if b.get("c")
    ]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").reset_index(drop=True)


def build_ohlcv_cache(universe_set, from_date, to_date, sleep_time=0.2):
    """
    Ensure every trading day in [from_date, to_date] has a per-day cache file.
    Already-cached days are skipped; only missing days trigger API calls.
    Returns the full list of trading days.
    """
    trading_days = get_trading_days(from_date, to_date)
    missing = []
    for d in trading_days:
        path = os.path.join(OHLCV_CACHE_DIR, f"{d}.json")
        if not os.path.exists(path):
            missing.append(d)
        else:
            try:
                if os.path.getsize(path) < 5:   # empty or "{}" file
                    missing.append(d)
            except OSError:
                missing.append(d)

    cached_count = len(trading_days) - len(missing)
    print(f"OHLCV cache: {cached_count} days cached, {len(missing)} to fetch …")

    for i, day in enumerate(missing, 1):
        bars = fetch_grouped_bars(day, universe_set)
        with open(os.path.join(OHLCV_CACHE_DIR, f"{day}.json"), "w") as f:
            json.dump(bars, f)
        time.sleep(sleep_time)
        if i % 50 == 0:
            print(f"  … fetched {i}/{len(missing)} days")

    if missing:
        print("OHLCV cache up to date.")
    return trading_days


def load_ohlcv_cache_into_memory(trading_days):
    """
    Load all per-day cache files into a single dict keyed by date.
    Called once before the scan loop so each ticker requires no disk I/O.
    Returns {date_str: {ticker: {"c": float, "v": float}}}.
    """
    daily_data = {}
    for day in trading_days:
        fpath = os.path.join(OHLCV_CACHE_DIR, f"{day}.json")
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath) as f:
                daily_data[day] = json.load(f)
        except Exception:
            continue
    return daily_data


def load_ticker_ohlcv(ticker, trading_days, daily_data):
    """
    Reconstruct a ticker's Close/Volume history from the in-memory daily_data dict.
    Returns pd.DataFrame[Date, Close, Volume] sorted ascending, or None.
    """
    old_name = TICKER_ALIASES.get(ticker)  # e.g. BNY -> BK (pre-rename cache files)
    rows = []
    for day in trading_days:
        day_data = daily_data.get(day, {})
        bar = day_data.get(ticker) or (day_data.get(old_name) if old_name else None)
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
# SEC EDGAR EPS FALLBACK
# Free, unlimited, no ToS restrictions. Used only when Massive has no data.
# =========================

_EDGAR_HEADERS = {"User-Agent": "Baizora support@baizora.com"}
_edgar_cik_map = {}
_edgar_cik_map_attempted = False


def _load_edgar_cik_map():
    """Fetch ticker→CIK mapping from EDGAR (one call, ~10k companies)."""
    global _edgar_cik_map, _edgar_cik_map_attempted
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
            _edgar_cik_map = {
                v["ticker"].upper(): str(v["cik_str"]).zfill(10)
                for v in resp.json().values()
            }
            print(f"EDGAR: {len(_edgar_cik_map)} ticker->CIK mappings loaded")
            return
        except Exception as e:
            print(f"EDGAR: failed ({url}): {e}")
    print("EDGAR: CIK map unavailable - EPS will be skipped")


def _get_eps_from_edgar(ticker):
    """
    Fetch TTM EPS from SEC EDGAR as a last-resort fallback.
    Tries: last 4 quarterly 10-Q filings (TTM sum) → most recent 10-K.
    Returns float EPS or None.
    """
    _load_edgar_cik_map()

    # Try ticker variants: BRK-B → BRK.B → BRKB
    cik = None
    for variant in [ticker, ticker.replace("-", "."), ticker.replace("-", "")]:
        cik = _edgar_cik_map.get(variant.upper())
        if cik:
            break
    if not cik:
        return None

    try:
        resp = requests.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            headers=_EDGAR_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        us_gaap = resp.json().get("facts", {}).get("us-gaap", {})

        for field in ("EarningsPerShareBasic", "EarningsPerShareDiluted"):
            units = (us_gaap.get(field, {})
                           .get("units", {})
                           .get("USD/shares", []))
            if not units:
                continue

            # Deduplicate by period end date (keep most recent filing per period)
            quarterly_raw = sorted(
                [x for x in units if x.get("form") == "10-Q"],
                key=lambda x: (x.get("end", ""), x.get("filed", "")),
                reverse=True,
            )
            seen, quarterly = set(), []
            for x in quarterly_raw:
                if x.get("end") not in seen:
                    seen.add(x.get("end"))
                    quarterly.append(x)

            # TTM = sum of last 4 quarters
            if len(quarterly) >= 4:
                return round(sum(x["val"] for x in quarterly[:4]), 4)

            # Annual fallback
            annual = sorted(
                [x for x in units if x.get("form") in ("10-K", "10-K405")],
                key=lambda x: x.get("end", ""),
                reverse=True,
            )
            if annual:
                return round(float(annual[0]["val"]), 4)

        return None
    except Exception:
        return None


# =========================
# FUNDAMENTALS via Massive
# (disk-cached; EPS: TTM quarterly → annual → SEC EDGAR fallback)
# =========================

_fund_cache = {}


def _load_fund_disk_cache():
    """Load fundamentals from disk if fresh. Returns True if loaded and valid."""
    global _fund_cache
    if not os.path.exists(FUND_CACHE_FILE):
        return False
    try:
        with open(FUND_CACHE_FILE) as f:
            data = json.load(f)
        fetched  = datetime.strptime(data.get("fetched", ""), "%Y-%m-%d").date()
        age_days = (date.today() - fetched).days
        if age_days <= FUND_CACHE_TTL_DAYS:
            _fund_cache = data.get("tickers", {})
            print(f"Fundamentals: {len(_fund_cache)} tickers loaded from disk cache ({age_days}d old)")
            return True
        print(f"Fundamentals cache stale ({age_days}d old) — refreshing from API")
        return False
    except Exception:
        return False


def _save_fund_disk_cache():
    with open(FUND_CACHE_FILE, "w") as f:
        json.dump({"fetched": DATE_STR, "tickers": _fund_cache}, f, indent=2)


def get_fundamentals(ticker):
    """
    Fetch fundamentals for one ticker from Massive API.
    - /v3/reference/tickers  → sector (via SIC mapping), market cap, company name
    - /vX/reference/financials → EPS (best-effort; may not be available on free plan)
    Results are stored in the in-memory _fund_cache.
    """
    if ticker in _fund_cache:
        return _fund_cache[ticker]

    overview = _massive_get(f"/v3/reference/tickers/{ticker}")
    results  = (overview or {}).get("results", {})

    market_cap   = results.get("market_cap")
    company_name = results.get("name")
    sic_desc     = results.get("sic_description") or ""
    sector       = TICKER_SECTOR_OVERRIDE.get(ticker) or sic_to_sector(sic_desc)

    # EPS via SEC EDGAR — free, 10 req/sec, no ToS issues, better coverage than Massive vX
    eps = _get_eps_from_edgar(ticker)

    result = {
        "MarketCap":     market_cap,
        "EPS":           eps,
        "Sector":        sector,
        "SicDescription": sic_desc,
        "Volatility30D": None,
        "CompanyName":   company_name,
    }

    _fund_cache[ticker] = result
    return result


def prefetch_fundamentals(tickers, sleep_time=1.2):
    """
    Populate _fund_cache for every ticker not already loaded.
    sleep_time paces the Massive reference call (market cap / sector).
    EPS comes from EDGAR which has no rate limit concern.
    """
    needed = [t for t in tickers if t not in _fund_cache]
    print(f"Fundamentals: fetching {len(needed)} tickers from API "
          f"({len(tickers) - len(needed)} already cached) …")

    for i, ticker in enumerate(needed, 1):
        get_fundamentals(ticker)
        time.sleep(sleep_time)
        if i % 50 == 0:
            print(f"  … fetched {i}/{len(needed)}")

    eps_count = sum(1 for v in _fund_cache.values() if v.get("EPS") is not None)
    print(f"Fundamentals complete: {eps_count}/{len(_fund_cache)} tickers have EPS "
          f"({'vX endpoint available' if eps_count > 0 else 'vX endpoint unavailable on this plan'})")
    if _unknown_sic_descriptions:
        print(f"\nWARNING: {len(_unknown_sic_descriptions)} SIC descriptions mapped to Unknown -- add to _SIC_TO_SECTOR:")
        for desc in sorted(_unknown_sic_descriptions):
            print(f'    "{desc}":  "",')
        print()

    _save_fund_disk_cache()
    print("Fundamentals cache saved to disk.")


def refetch_missing_eps(tickers, sleep_time=1.2):
    """
    Re-fetch fundamentals only for tickers that have EPS=None in cache.
    Useful after a rate-limited initial run where some vX calls failed.
    """
    missing = [t for t in tickers if _fund_cache.get(t, {}).get("EPS") is None]
    if not missing:
        print("No missing EPS — skipping refetch.")
        return
    print(f"Re-fetching EPS for {len(missing)} tickers with missing data …")
    for i, ticker in enumerate(missing, 1):
        if ticker in _fund_cache:
            del _fund_cache[ticker]   # force fresh API call
        get_fundamentals(ticker)
        time.sleep(sleep_time)
        if i % 50 == 0:
            print(f"  … refetched {i}/{len(missing)}")
    eps_count = sum(1 for v in _fund_cache.values() if v.get("EPS") is not None)
    print(f"After refetch: {eps_count}/{len(_fund_cache)} tickers have EPS")
    _save_fund_disk_cache()


# =========================
# MULTI-PERIOD METRICS
# =========================

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

    max_price_val = recent["price_change"].iloc[max_price_idx]
    max_vol_val   = recent["volume_change"].iloc[max_vol_idx]

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

def scan():
    tickers, sp_set, nd_set = get_tickers()
    universe_set  = set(tickers)
    results       = []
    candles_out   = {}
    sector_pe_map = {}
    sector_counts = {}

    print(f"Total tickers: {len(tickers)}")

    to_date   = DATE_STR
    from_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")

    # Build/update OHLCV cache (1 grouped API call per missing trading day)
    trading_days = build_ohlcv_cache(universe_set, from_date, to_date)

    # Load fundamentals from disk cache (7-day TTL), then fetch any missing tickers
    _load_fund_disk_cache()
    prefetch_fundamentals(tickers)  # skips already-cached tickers internally

    # Load all OHLCV cache files into memory once (avoids 500+ file reads per ticker)
    print("Loading OHLCV cache into memory …")
    daily_data = load_ohlcv_cache_into_memory(trading_days)
    print(f"Loaded {len(daily_data)} days. Processing {len(tickers)} tickers …")

    # Fetch SPY for beta calculation (1 API call, not in universe cache)
    spy_returns = None
    try:
        spy_df = fetch_benchmark_bars("SPY", from_date, to_date)
        if spy_df is not None and len(spy_df) >= 60:
            spy_returns = spy_df["Close"].pct_change().dropna()
            print(f"SPY loaded: {len(spy_returns)} daily returns for beta calculation")
    except Exception:
        print("SPY fetch failed — beta will be None")

    for i, ticker in enumerate(tickers, 1):
        try:
            df = load_ticker_ohlcv(ticker, trading_days, daily_data)

            if df is None or df.empty:
                continue

            df = df[(df["Volume"] >= 10000) & (df["Close"] > 0)]

            if len(df) < 30:
                continue

            # =========================
            # BASE FEATURES
            # =========================
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

            # =========================
            # 1D
            # =========================
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

            # =========================
            # MULTI-DAY WINDOWS
            # =========================
            metrics = {}
            for label, days in TIMEFRAMES.items():
                metrics.update(calculate_period_metrics(df, label, days))

            # =========================
            # FUNDAMENTALS
            # =========================
            fund   = get_fundamentals(ticker)
            sector = fund["Sector"]
            eps    = fund["EPS"]

            # PE calculated from today's live price and cached EPS
            pe = round(float(latest["Close"]) / eps, 2) if eps and eps > 0 else None

            if sector and pe:
                sector_pe_map.setdefault(sector, 0)
                sector_counts.setdefault(sector, 0)
                sector_pe_map[sector] += pe
                sector_counts[sector] += 1

            # =========================
            # FLAGS
            # =========================
            in_sp500     = ticker in sp_set
            in_nasdaq100 = ticker in nd_set

            # =========================
            # SPARKLINE PREP
            # =========================
            try:
                close_series = df["Close"].dropna()

                def normalize(series):
                    min_v = series.min()
                    max_v = series.max()
                    if max_v == min_v:
                        return [0.5] * len(series)
                    return ((series - min_v) / (max_v - min_v)).tolist()

                spark_6m = None
                spark_1y = normalize(close_series.tail(252))
            except Exception:
                spark_6m = None
                spark_1y = None

            # =========================
            # BETA & VOLATILITY (calculated from OHLCV cache)
            # =========================
            beta    = None
            vol_30d = None
            try:
                stock_ret = df["Close"].pct_change().dropna()

                # 30-day annualised volatility
                if len(stock_ret) >= 20:
                    vol_30d = round(float(stock_ret.iloc[-30:].std() * np.sqrt(252)), 4)

                # 1-year beta vs SPY
                if spy_returns is not None and len(stock_ret) >= 60:
                    n   = min(252, len(stock_ret), len(spy_returns))
                    s   = stock_ret.iloc[-n:].values
                    m   = spy_returns.iloc[-n:].values
                    cov = np.cov(s, m)
                    if cov[1, 1] != 0:
                        beta = round(cov[0, 1] / cov[1, 1], 3)
            except Exception:
                pass

            # =========================
            # CANDLE DATA (1Y, for candles.json)
            # =========================
            try:
                candle_rows = df.tail(252)
                candles = []
                for _, row in candle_rows.iterrows():
                    o, h, l, c = row.get("Open"), row.get("High"), row.get("Low"), row["Close"]
                    if all(v is not None and pd.notna(v) for v in [o, h, l, c]):
                        candles.append([round(float(o),2), round(float(h),2), round(float(l),2), round(float(c),2)])
                if candles:
                    candles_out[ticker] = candles
            except Exception:
                pass

            # =========================
            # SCORES (per-stock)
            # =========================
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

            # =========================
            # OUTPUT
            # =========================
            actual_date = df["Date"].iloc[-1].strftime("%Y-%m-%d")
            results.append({
                "Date":   actual_date,
                "Ticker": ticker,

                "InSP500":     in_sp500,
                "InNASDAQ100": in_nasdaq100,

                "Price":   round(float(latest["Close"]), 2),
                "VolumeM": latest_volume_m,

                "PriceChange1D":  round(price_change_1d  * 100, 2) if price_change_1d  is not None else None,
                "VolumeChange1D": round(volume_change_1d * 100, 2) if volume_change_1d is not None else None,

                "PriceVsMA21_1D":  round(price_vs_ma21_1d,  3) if pd.notna(price_vs_ma21_1d)  else None,
                "VolumeVsMA21_1D": round(volume_vs_ma21_1d, 3) if pd.notna(volume_vs_ma21_1d) else None,

                **metrics,

                "PE":            pe,
                "MarketCap":     fund["MarketCap"],
                "EPS":           eps,
                "Sector":        sector,
                "Beta":          beta,
                "Volatility30D": vol_30d,
                "CompanyName":   fund["CompanyName"],
                "Spark6M":       spark_6m,
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

    # =========================
    # POST-PROCESSING
    # =========================
    sector_avg_pe = {
        s: sector_pe_map[s] / sector_counts[s]
        for s in sector_pe_map
        if sector_counts[s] > 0
    }

    df = pd.DataFrame(results)
    if df.empty:
        print("No results generated — universe or data issue")
        return df

    df["MarketCap"] = df["MarketCap"].apply(
        lambda x: round(float(x) / 1_000_000_000, 2)
        if x is not None and pd.notna(x)
        else None
    )

    df["SectorAvgPE"] = df["Sector"].map(sector_avg_pe)
    df["SectorAvgPE"] = pd.to_numeric(df["SectorAvgPE"], errors="coerce").round(2)

    df["PE_vs_Sector"] = np.where(
        (df["PE"].notna()) &
        (df["SectorAvgPE"].notna()) &
        (df["SectorAvgPE"] != 0),
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

    if "VolumeChange1D" in df.columns:
        df = df.sort_values("VolumeChange1D", ascending=False)

    return df, candles_out


# =========================
# DATA QUALITY CHECK
# =========================

def check_data_quality(df, candles_out, trading_days):
    """
    Post-scan sanity checks. Prints warnings for anomalies that suggest
    missing cache days or bad API data rather than real market moves.
    """
    issues = []

    # 1. Tickers with large 1D price change (>25%) — likely a multi-day gap
    if "PriceChange1D" in df.columns:
        big_1d = df[df["PriceChange1D"].abs() > 25][["Ticker", "PriceChange1D", "Price"]].copy()
        for _, row in big_1d.iterrows():
            issues.append(f"  {row['Ticker']}: 1D price change {row['PriceChange1D']:.1f}% (price ${row['Price']}) -- possible gap in cache")

    # 2. Tickers whose candle series has fewer bars than expected (< 200 of 252)
    expected = min(252, len(trading_days))
    for ticker, candles in candles_out.items():
        if len(candles) < 200:
            issues.append(f"  {ticker}: only {len(candles)} candle bars (expected ~{expected}) -- missing OHLCV data")

    # 3. Check how many cache days are empty (0 tickers)
    empty_days = sum(
        1 for d in trading_days
        if os.path.getsize(os.path.join(OHLCV_CACHE_DIR, f"{d}.json")) < 5
    )
    if empty_days > 0:
        issues.append(f"  {empty_days} OHLCV cache files are empty -- will be re-fetched next run")

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

def export(df):
    df = df.replace({np.nan: None, np.inf: None, -np.inf: None})

    df.to_csv(OUTPUT_CSV, index=False)

    market_date = df["Date"].iloc[0] if len(df) and "Date" in df.columns else DATE_STR
    payload = {
        "date":   market_date,
        "status": "Updated",
        "count":  len(df),
        "data":   df.to_dict(orient="records"),
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    print("Export complete:", len(df))


# =========================
# CANDLES EXPORT
# =========================

def export_candles(candles_out, trading_days):
    """
    Write data/candles.json — loaded by the dashboard separately after the
    main table renders, so it does not slow down initial page load.
    Format: {"date": "...", "dates": [...252 YYYY-MM-DD...], "data": {ticker: [[o,h,l,c],...], ...}}
    """
    dates = list(trading_days[-252:])
    payload = {
        "date":  DATE_STR,
        "dates": dates,
        "data":  candles_out,
    }
    path = os.path.join(DATA_DIR, "candles.json")
    with open(path, "w") as f:
        json.dump(payload, f)
    print(f"Candles export: {len(candles_out)} tickers, {len(dates)} dates")


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
            headers=SCRAPE_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        return "".join(part[0] for part in data[0] if part[0])
    except Exception:
        return ""


def fetch_and_save_index_news(lookback_days=90):
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
            title   = (item.findtext("title")   or "").strip()
            pub_raw = (item.findtext("pubDate")  or "").strip()
            source  = (item.findtext("source")   or "").strip()
            link    = (item.findtext("link")     or "").strip()

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

    all_items.sort(key=lambda x: x["date"], reverse=True)

    print(f"  [news] translating {len(all_items)} titles to Chinese...")
    for item in all_items:
        suffix = " - " + item["source"]
        clean  = item["title"][:-len(suffix)] if item["title"].endswith(suffix) else item["title"]
        item["title_cn"] = _translate_to_zh(clean)
        time.sleep(0.2)

    out = {
        "fetched":       datetime.now().strftime("%Y-%m-%d"),
        "lookback_days": lookback_days,
        "items":         all_items,
    }

    path = os.path.join(DATA_DIR, "index_news.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"  [news] saved {len(all_items)} articles to {path}")


# =========================
# MAIN
# =========================

if __name__ == "__main__":

    today = date.today()
    if is_market_holiday(today):
        print(f"Market holiday ({today}) — skipping scan.")
        sys.exit(0)

    print("Running Baizora scanner (Massive API) …")

    # 1. Fetch fresh index lists and detect membership changes
    _, _, changes_entry = update_and_detect_changes()

    # 2. Update index_changes.json
    load_update_index_changes(changes_entry)

    # 3. Delete old archives and OHLCV cache files beyond 2-year window
    cleanup_old_archives()
    cleanup_old_ohlcv_cache()

    # 4. Run scan (builds/updates OHLCV cache, loads fundamentals cache)
    df, candles_out = scan()

    print(df.head(10))

    trading_days_full = get_trading_days(
        (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d"), DATE_STR
    )

    # 5. Data quality check — warns about gaps, bad 1D jumps, empty cache files
    check_data_quality(df, candles_out, trading_days_full)

    # 6. Export results
    export(df)

    # 7. Export candle data (separate file, does not affect latest.json size)
    export_candles(candles_out, trading_days_full)

    # 7. Fetch index membership news
    fetch_and_save_index_news()

    print("Done")
