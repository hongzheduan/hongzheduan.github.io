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

Empty-overwrite guard: a quiet week legitimately has zero IPOs, so an empty
list is written as-is. But if the feed itself fails (HTTP error, bad JSON,
missing "data"), the script exits without touching the existing file.
"""
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "data" / "ipo_calendar.json"

FEED_URL = "https://api.nasdaq.com/api/ipo/calendar?date={ym}"
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
        out.append({
            "ticker": row.get("proposedTickerSymbol") or "",
            "company": (row.get("companyName") or "").strip(),
            "exchange": short_exchange(row.get("proposedExchange")),
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
