#!/usr/bin/env python3
"""
Fetch the US IPO calendar into data/ipo_calendar.json for ipo_calendar.html
(dashboard "IPO Calendar" card). Two lists:
  - ipos:  scheduled deals with an expected pricing date (today or later).
           Nasdaq only posts a date about a week ahead, so this list is short.
  - filed: public filings from the last FILED_LOOKBACK_DAYS with no date yet,
           minus anything since scheduled, priced or withdrawn.

Source: Nasdaq's public IPO calendar feed (api.nasdaq.com/api/ipo/calendar),
which covers every major US exchange (Nasdaq, NYSE, NYSE American), not just
Nasdaq listings. Unofficial / undocumented: needs a browser-like User-Agent.
If it ever breaks or gets blocked, Finnhub's /calendar/ipo (free API key) is
the fallback.

Filters (both lists; site is large-cap focused):
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
from datetime import datetime, timedelta
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
FILED_LOOKBACK_DAYS = 180
MIN_DEAL_USD = 100_000_000

ET = ZoneInfo("America/New_York")
SPAC_NAME_RE = re.compile(r"\b(acquisitions?|blank check|spac)\b", re.I)


def fetch_month(ym):
    r = requests.get(FEED_URL.format(ym=ym), headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json().get("data")
    if not isinstance(data, dict):
        raise ValueError(f"no 'data' object in feed for {ym}")
    up = (data.get("upcoming") or {}).get("upcomingTable") or {}
    return {
        "upcoming": up.get("rows") or [],
        "filed": (data.get("filed") or {}).get("rows") or [],
        "priced": (data.get("priced") or {}).get("rows") or [],
        "withdrawn": (data.get("withdrawn") or {}).get("rows") or [],
    }


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
    """deal id -> (sector, industry, sic) via Nasdaq overview (CIK) + EDGAR. Never raises."""
    try:
        r = requests.get(OVERVIEW_URL.format(deal=deal_id), headers=HEADERS, timeout=20)
        r.raise_for_status()
        cik = (((r.json().get("data") or {}).get("poOverview") or {}).get("SECCIK") or {}).get("value")
        if not cik or not str(cik).strip().isdigit():
            return None, None, ""
        r = requests.get(SEC_SUBMISSIONS_URL.format(cik=str(cik).strip().zfill(10)),
                         headers=SEC_HEADERS, timeout=20)
        r.raise_for_status()
        sub = r.json()
        sic = str(sub.get("sic") or "").strip()
        return sic_to_sector(sic), clean_industry(sub.get("sicDescription")) or None, sic
    except Exception as e:
        print(f"  sector lookup failed for {deal_id}: {e}")
        return None, None, None   # None sic = lookup failed (vs "" = EDGAR has no SIC)


def is_spac_by_sic(ticker, sic):
    # SIC 6770 = "Blank Checks". Brand-new SPAC shells often have no SIC yet;
    # a unit ticker (…U) with an empty SIC is the tell for those. Filed rows
    # carry no share price, so is_spac()'s $10-unit rule can't catch them.
    if sic == "6770":
        return True
    return sic == "" and (ticker or "").endswith("U") and len(ticker) >= 4


def short_exchange(ex):
    ex = (ex or "").upper()
    if "NYSE MKT" in ex or "AMERICAN" in ex:
        return "NYSE American"
    if "NYSE" in ex:
        return "NYSE"
    if "NASDAQ" in ex:
        return "Nasdaq"
    return ex.title() or "—"


def norm_name(n):
    return re.sub(r"[^a-z0-9]", "", (n or "").lower())


def main():
    today = datetime.now(ET).date()
    # Filed deals from the last FILED_LOOKBACK_DAYS, plus next month in case
    # a scheduled date lands there. Nasdaq only posts an expected date ~1 week
    # ahead, so "upcoming" never reaches far; the filed list is the pipeline.
    first = (today - timedelta(days=FILED_LOOKBACK_DAYS)).replace(day=1)
    months, m = [], first
    while m <= (today.replace(day=1) + timedelta(days=32)).replace(day=1):
        months.append(m.strftime("%Y-%m"))
        m = (m + timedelta(days=32)).replace(day=1)

    tables = {"upcoming": [], "filed": [], "priced": [], "withdrawn": []}
    try:
        for ym in months:
            for k, v in fetch_month(ym).items():
                tables[k].extend(v)
            time.sleep(0.3)
    except Exception as e:
        print(f"IPO feed fetch failed, keeping existing {OUT_JSON.name}: {e}")
        return 0

    # sector lookups are cached by deal id across runs (2 HTTP calls each otherwise)
    cache = {}
    try:
        old = json.loads(OUT_JSON.read_text(encoding="utf-8"))
        for x in (old.get("ipos") or []) + (old.get("filed") or []):
            if x.get("deal_id") and x.get("sic"):   # only cache successful lookups
                cache[x["deal_id"]] = (x.get("sector"), x.get("industry"), x["sic"])
    except Exception:
        pass

    def sector_for(deal_id):
        if not deal_id:
            return None, None, None
        if deal_id not in cache:
            cache[deal_id] = lookup_sector(deal_id)
            time.sleep(0.3)   # stay well under SEC's 10 req/s fair-access limit
        return cache[deal_id]

    def keep(row):
        if is_spac(row):
            return None
        deal = parse_usd(row.get("dollarValueOfSharesOffered"))
        return deal if deal is not None and deal >= MIN_DEAL_USD else None

    def base(row, deal):
        """Row dict with sector info, or None if EDGAR marks it as a SPAC."""
        ticker = row.get("proposedTickerSymbol") or ""
        sector, industry, sic = sector_for(row.get("dealID"))
        if is_spac_by_sic(ticker, sic):
            return None
        return {
            "deal_id": row.get("dealID") or "",   # -> nasdaq.com IPO profile link
            "ticker": ticker,
            "company": (row.get("companyName") or "").strip(),
            "sector": sector,
            "industry": industry,
            "sic": sic,
            "deal_usd": deal,
        }

    def pdate(s):
        try:
            return datetime.strptime(s or "", "%m/%d/%Y").date()
        except ValueError:
            return None

    # ---- scheduled: has an expected pricing date, today or later
    seen, sched = set(), []
    for row in tables["upcoming"]:
        d = pdate(row.get("expectedPriceDate"))
        deal = keep(row)
        key = row.get("dealID") or row.get("proposedTickerSymbol")
        if not d or d < today or deal is None or key in seen:
            continue
        seen.add(key)
        x = base(row, deal)
        if x is None:
            continue
        x.update({
            "exchange": short_exchange(row.get("proposedExchange")),
            "date": d.isoformat(),
            "price_range": (row.get("proposedSharePrice") or "").strip(),
            "shares": parse_usd(row.get("sharesOffered")),
        })
        sched.append(x)
    sched.sort(key=lambda x: (x["date"], -x["deal_usd"]))

    # ---- filed: public S-1/F-1 on file, no date yet; drop anything already
    # scheduled, priced or withdrawn (matched by deal id OR company name,
    # since a refiled deal can get a new id)
    done_ids = {r.get("dealID") for k in ("upcoming", "priced", "withdrawn") for r in tables[k]}
    done_names = {norm_name(r.get("companyName")) for k in ("upcoming", "priced", "withdrawn") for r in tables[k]}
    cutoff = today - timedelta(days=FILED_LOOKBACK_DAYS)
    filed, seen = [], set()
    for row in tables["filed"]:
        d = pdate(row.get("filedDate"))
        deal = keep(row)
        name = norm_name(row.get("companyName"))
        if not d or d < cutoff or deal is None:
            continue
        if row.get("dealID") in done_ids or name in done_names or name in seen:
            continue
        seen.add(name)
        x = base(row, deal)
        if x is None:
            continue
        x["filed_date"] = d.isoformat()
        filed.append(x)
    filed.sort(key=lambda x: x["filed_date"], reverse=True)

    payload = {
        "updated": datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        "min_deal_usd": MIN_DEAL_USD,
        "filed_lookback_days": FILED_LOOKBACK_DAYS,
        "ipos": sched,
        "filed": filed,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {len(sched)} scheduled + {len(filed)} filed IPOs "
          f"(months {months[0]}..{months[-1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
