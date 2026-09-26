#!/usr/bin/env python3
"""
Fetch the next-7-days US IPO calendar into data/ipo_calendar.json for the
homepage "IPO Calendar" section.

Source: Nasdaq's public IPO calendar feed (api.nasdaq.com/api/ipo/calendar),
which covers every major US exchange (Nasdaq, NYSE, NYSE American), not just
Nasdaq listings. Unofficial / undocumented: needs a browser-like User-Agent.
If it ever breaks or gets blocked, Finnhub's /calendar/ipo (free API key) is
the fallback.

Filters (homepage is large-cap focused):
  - SPACs hidden (blank-check "... Acquisition Corp" shells, $10 unit deals)
  - Deal size >= MIN_DEAL_USD; deals with no disclosed size are dropped too

Sector / industry: the calendar feed has none, so each kept deal is looked
up via Nasdaq's deal overview (for its SEC CIK), then SEC EDGAR's
submissions feed (SIC code + description). SIC codes are mapped to the 11
familiar GICS-style sectors by sic_to_sector(); the SIC description is shown
as the finer "industry" line. Lookup failures just leave both blank.

Empty-overwrite guard: a quiet week legitimately has zero IPOs, so an empty
list is written as-is. But if the feed itself fails (HTTP error, bad JSON,
missing "data"), the script exits without touching the existing file.
"""
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "ipo_calendar.json"

FEED_URL = "https://api.nasdaq.com/api/ipo/calendar?date={ym}"
OVERVIEW_URL = "https://api.nasdaq.com/api/ipo/overview/?dealId={deal}"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_HEADERS = {"User-Agent": "Baizora support@baizora.com"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}
WINDOW_DAYS = 7
MIN_DEAL_USD = 100_000_000

ET = ZoneInfo("America/New_York")
SPAC_NAME_RE = re.compile(r"\b(acquisition|blank check|spac)\b", re.I)


def fetch_month(ym):
    r = requests.get(FEED_URL.format(ym=ym), headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json().get("data")
    if not isinstance(data, dict):
        raise ValueError(f"no 'data' object in feed for {ym}")
    upcoming = (data.get("upcoming") or {}).get("upcomingTable") or {}
    return upcoming.get("rows") or []


def parse_usd(s):
    s = re.sub(r"[^0-9.]", "", s or "")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def is_spac(row):
    name = row.get("companyName") or ""
    if SPAC_NAME_RE.search(name):
        return True
    # $10.00 units with a U-suffixed ticker are the SPAC signature even when
    # the name doesn't say "Acquisition"
    sym = row.get("proposedTickerSymbol") or ""
    return sym.endswith("U") and (row.get("proposedSharePrice") or "").strip() == "10.00"


def sic_to_sector(sic):
    """Map a 4-digit SIC code to a GICS-style sector name (approximate)."""
    try:
        c = int(sic)
    except (TypeError, ValueError):
        return None
    ranges = [
        (100, 999, "Consumer Staples"),
        (1000, 1099, "Materials"), (1200, 1399, "Energy"), (1400, 1499, "Materials"),
        (1500, 1799, "Industrials"),
        (2000, 2199, "Consumer Staples"), (2200, 2399, "Consumer Discretionary"),
        (2400, 2499, "Materials"), (2500, 2599, "Consumer Discretionary"), (2600, 2699, "Materials"),
        (2700, 2799, "Communication Services"),
        (2830, 2836, "Healthcare"), (2840, 2844, "Consumer Staples"), (2800, 2899, "Materials"),
        (2900, 2999, "Energy"),
        (3100, 3199, "Consumer Discretionary"), (3000, 3399, "Materials"),
        (3400, 3499, "Industrials"),
        (3570, 3579, "Technology"), (3500, 3599, "Industrials"),
        (3630, 3659, "Consumer Discretionary"), (3660, 3679, "Technology"), (3600, 3699, "Industrials"),
        (3710, 3716, "Consumer Discretionary"), (3750, 3751, "Consumer Discretionary"),
        (3700, 3799, "Industrials"),
        (3812, 3812, "Industrials"), (3840, 3851, "Healthcare"), (3800, 3899, "Technology"),
        (3900, 3999, "Consumer Discretionary"),
        (4800, 4899, "Communication Services"),
        (4955, 4955, "Industrials"), (4900, 4999, "Utilities"),
        (4000, 4799, "Industrials"),
        (5122, 5122, "Healthcare"), (5000, 5199, "Industrials"),
        (5400, 5499, "Consumer Staples"), (5912, 5912, "Consumer Staples"),
        (5200, 5999, "Consumer Discretionary"),
        (6500, 6553, "Real Estate"), (6798, 6798, "Real Estate"), (6000, 6799, "Financials"),
        (7370, 7379, "Technology"), (7300, 7399, "Industrials"),
        (7800, 7899, "Communication Services"),
        (7000, 7999, "Consumer Discretionary"),
        (8000, 8099, "Healthcare"), (8731, 8731, "Healthcare"),
        (8200, 8299, "Consumer Discretionary"),
        (8000, 8999, "Industrials"),
    ]
    for lo, hi, name in ranges:   # first match wins, so narrow ranges come first
        if lo <= c <= hi:
            return name
    return None


def clean_industry(desc):
    # EDGAR uses prefixes like "Services-Prepackaged Software", "Retail-Eating Places"
    desc = (desc or "").strip()
    head, sep, tail = desc.partition("-")
    if sep and head.lower() in ("services", "retail", "wholesale"):
        desc = tail
    desc = re.sub(r"\s*\([^)]*\)", "", desc)        # "(No Diagnostic Substances)"
    desc = re.sub(r",?\s*Etc\.?$", "", desc, flags=re.I)
    desc = re.sub(r"\s+", " ", desc).strip(" ,")
    return desc


def lookup_sector(deal_id):
    """deal id -> (sector, industry) via Nasdaq overview (CIK) + EDGAR. Never raises."""
    try:
        r = requests.get(OVERVIEW_URL.format(deal=deal_id), headers=HEADERS, timeout=20)
        r.raise_for_status()
        cik = (((r.json().get("data") or {}).get("poOverview") or {}).get("SECCIK") or {}).get("value")
        if not cik or not str(cik).strip().isdigit():
            return None, None
        r = requests.get(SEC_SUBMISSIONS_URL.format(cik=str(cik).strip().zfill(10)),
                         headers=SEC_HEADERS, timeout=20)
        r.raise_for_status()
        sub = r.json()
        return sic_to_sector(sub.get("sic")), clean_industry(sub.get("sicDescription")) or None
    except Exception as e:
        print(f"  sector lookup failed for {deal_id}: {e}")
        return None, None


def short_exchange(ex):
    ex = (ex or "").upper()
    if "NYSE MKT" in ex or "AMERICAN" in ex:
        return "NYSE American"
    if "NYSE" in ex:
        return "NYSE"
    if "NASDAQ" in ex:
        return "Nasdaq"
    return ex.title() or "—"


def main():
    today = datetime.now(ET).date()
    end = today + timedelta(days=WINDOW_DAYS)
    months = sorted({today.strftime("%Y-%m"), end.strftime("%Y-%m")})

    rows = []
    try:
        for ym in months:
            rows.extend(fetch_month(ym))
    except Exception as e:
        print(f"IPO feed fetch failed, keeping existing {OUT_JSON.name}: {e}")
        return 0

    seen, out = set(), []
    for row in rows:
        try:
            d = datetime.strptime(row.get("expectedPriceDate") or "", "%m/%d/%Y").date()
        except ValueError:
            continue
        if not (today <= d <= end):
            continue
        if is_spac(row):
            continue
        deal = parse_usd(row.get("dollarValueOfSharesOffered"))
        if deal is None or deal < MIN_DEAL_USD:
            continue
        key = row.get("dealID") or row.get("proposedTickerSymbol")
        if key in seen:
            continue
        seen.add(key)
        sector, industry = lookup_sector(row.get("dealID")) if row.get("dealID") else (None, None)
        time.sleep(0.3)   # stay well under SEC's 10 req/s fair-access limit
        out.append({
            "deal_id": row.get("dealID") or "",   # -> nasdaq.com IPO profile link on the homepage
            "ticker": row.get("proposedTickerSymbol") or "",
            "company": (row.get("companyName") or "").strip(),
            "exchange": short_exchange(row.get("proposedExchange")),
            "sector": sector,
            "industry": industry,
            "date": d.isoformat(),
            "price_range": (row.get("proposedSharePrice") or "").strip(),
            "shares": parse_usd(row.get("sharesOffered")),
            "deal_usd": deal,
        })

    out.sort(key=lambda x: (x["date"], -x["deal_usd"]))
    payload = {
        "updated": datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        "window_start": today.isoformat(),
        "window_end": end.isoformat(),
        "min_deal_usd": MIN_DEAL_USD,
        "ipos": out,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {len(out)} IPOs ({today} .. {end}) from {len(rows)} upcoming rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
