#!/usr/bin/env python3
"""
Fetch important corporate events per ticker — stock splits, mergers/
acquisitions, bankruptcy, delisting notices, leadership changes, and
material agreements — into data/corporate_events.json.

Sources:
  - SEC EDGAR's per-company submissions feed (data.sec.gov/submissions/),
    the same endpoint already used for EPS data. Every 8-K filing carries
    structured "item" codes — no scraping/summarization needed, just
    filter to the codes that map to real events (see ITEM_LABELS below).
  - data/splits.json (already maintained by scanner_tiingo.py) for splits.

Only shows events within the last 6 months / next 3 months of today (see
WINDOW_PAST_DAYS / WINDOW_FUTURE_DAYS below) — except earnings events, which
get a longer ~13-month past window (EARNINGS_WINDOW_PAST_DAYS) so all 4
trailing quarters stay visible for cross-checking the site's own TTM EPS
math. Unlike the descriptions script this needs re-running periodically to
both pick up new filings and drop events that have aged out of the window —
every ticker is refreshed each run since new filings can appear for any of
them at any time.
"""
import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
LATEST_JSON = ROOT / "data" / "latest.json"
SPLITS_JSON = ROOT / "data" / "splits.json"
OUT_JSON = ROOT / "data" / "corporate_events.json"

HEADERS = {"User-Agent": "Baizora support@baizora.com"}
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# 8-K item code -> (type slug, human label)
ITEM_LABELS = {
    "1.01": ("agreement", "Material Agreement"),
    "1.03": ("bankruptcy", "Bankruptcy / Receivership"),
    "2.01": ("acquisition", "Acquisition / Disposition Completed"),
    "2.02": ("earnings", "Earnings Report"),
    "3.01": ("delisting", "Delisting Notice"),
    "5.01": ("control", "Change in Control"),
    "5.02": ("leadership", "Leadership Change"),
}

# Reported (not analyst-consensus — no such data source here) EPS + revenue for
# the quarter an earnings 8-K announces, pulled from SEC's structured XBRL
# company facts (same free source already used for the site's EPS/PE ratio —
# no scraping/AI summarization of the press-release text).
EARNINGS_EPS_FIELDS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")
EARNINGS_REVENUE_FIELDS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
# Quarter-end must fall in this window before the 8-K filing date to count as
# "the quarter this filing is announcing" (quarters are ~91 days apart).
EARNINGS_LOOKBACK_DAYS = 100

# Bumped from 12 (2026-08-15) alongside EARNINGS_WINDOW_PAST_DAYS below — a
# ticker can now show up to 4 trailing quarters of earnings on top of its
# normal 6-month window of leadership/agreement noise, so the old cap risked
# pushing an older earnings quarter out before a busier ticker's other events.
MAX_EVENTS_PER_TICKER = 16
# Past half is 6 months (2026-08-15, was 3 months, originally 2) — comfortable
# margin so a full earnings quarter (~91 days apart) never gets missed right
# before it ages back into view, even for filers whose reporting cadence
# slips a few weeks late. 8-K filings are always retrospective (SEC requires
# filing within ~4 business days of the event) so in practice this only means
# "last 6 months" for the EDGAR-sourced events. Future half stays at 3
# months — it only matters for data/splits.json, which can carry an
# announced-but-not-yet-effective split date (see scanner_tiingo.py's
# "Upcoming splits" handling); 8-K filings never have a future date.
WINDOW_PAST_DAYS = 180
WINDOW_FUTURE_DAYS = 90
# Earnings events get their own, longer past window (2026-08-15) — used for
# cross-checking the site's own TTM EPS/PE-ratio math against the individual
# reported quarters. 4 trailing quarters span ~365 days; a bit of slack on
# top covers filers whose cadence runs a few weeks late. Kept separate from
# WINDOW_PAST_DAYS so this doesn't also widen the noisier leadership-change/
# material-agreement event types shown to every visitor.
EARNINGS_WINDOW_PAST_DAYS = 400


def load_cik_map() -> dict:
    for url in [
        "https://www.sec.gov/files/company_tickers.json",
        "https://data.sec.gov/files/company_tickers.json",
    ]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            m = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in r.json().values()}
            print(f"EDGAR: {len(m)} ticker->CIK mappings loaded")
            return m
        except Exception as e:
            print(f"EDGAR: CIK map failed ({url}): {e}", file=sys.stderr)
    return {}


def _period_days(entry):
    try:
        return (datetime.strptime(entry["end"], "%Y-%m-%d") -
                datetime.strptime(entry["start"], "%Y-%m-%d")).days
    except Exception:
        return 999


def _find_quarter_value(units, cutoff_before: str, filing_date: str):
    """
    Find the reported value for the single fiscal quarter an earnings 8-K
    (filed on filing_date) is most likely announcing, from one field's raw
    XBRL fact entries (e.g. all EarningsPerShareDiluted entries).

    Q4 never gets its own 10-Q (10-Qs only cover Q1-Q3), so there are two
    cases:
      - Q1/Q2/Q3: filers report a standalone ~91-day entry directly in a
        10-Q — no math needed, just pick the freshest one in the window.
      - Q4: derived as (10-K full-year total) minus (10-Q 9-month YTD total)
        for the same fiscal year, matched by the two entries sharing a start
        date. This is a targeted two-entry lookup, not a generic multi-
        quarter differencing pass — mixing 10-K/10-Q entries into one
        general "walk and subtract the previous entry" pool (an earlier,
        buggier version of this function) silently picks up the wrong
        "previous" entry whenever a filer reports both a standalone quarter
        AND a redundant YTD figure for the same end date.
    """
    in_window = [x for x in units if x.get("end") and x.get("start") and x.get("val") is not None
                 and cutoff_before <= x["end"] <= filing_date]
    if not in_window:
        return None

    standalone = [x for x in in_window if x.get("form") == "10-Q" and 80 <= _period_days(x) <= 100]
    if standalone:
        best = max(standalone, key=lambda x: x["end"])
        return best["end"], best["val"]

    annual = [x for x in in_window if x.get("form") in ("10-K", "10-K405") and _period_days(x) >= 340]
    if annual:
        fy = max(annual, key=lambda x: x["end"])
        nine_mo = [x for x in units if x.get("form") == "10-Q" and x.get("start") == fy.get("start")
                   and x.get("val") is not None and 250 <= _period_days(x) <= 300]
        if nine_mo:
            ytd9 = max(nine_mo, key=lambda x: x.get("filed", ""))
            return fy["end"], round(fy["val"] - ytd9["val"], 4)
    return None


def _get_earnings_detail(cik: str, filing_date: str):
    """
    Best-effort reported EPS + revenue for the quarter an earnings (8-K Item
    2.02) filing announces, from SEC's structured XBRL data.

    Timing caveat: the earnings 8-K usually precedes the 10-Q that actually
    carries the XBRL-tagged numbers by 1-4 weeks, so this can return all-None
    right after the announcement. That's fine — this script re-fetches every
    ticker every run, so the detail fills in on its own once the 10-Q posts.
    Returns (eps, revenue, period_end) — any/all may be None.
    """
    try:
        resp = requests.get(COMPANYFACTS_URL.format(cik=cik), headers=HEADERS, timeout=15)
        resp.raise_for_status()
        us_gaap = resp.json().get("facts", {}).get("us-gaap", {})
    except Exception:
        return None, None, None

    cutoff_before = (date.fromisoformat(filing_date) - timedelta(days=EARNINGS_LOOKBACK_DAYS)).isoformat()

    def best_quarter(fields, unit_key):
        for field in fields:
            units = us_gaap.get(field, {}).get("units", {}).get(unit_key, [])
            if not units:
                continue
            found = _find_quarter_value(units, cutoff_before, filing_date)
            if found:
                return found
        return None

    eps_q = best_quarter(EARNINGS_EPS_FIELDS, "USD/shares")
    rev_q = best_quarter(EARNINGS_REVENUE_FIELDS, "USD")

    period_end = (eps_q or rev_q)[0] if (eps_q or rev_q) else None
    eps = round(eps_q[1], 2) if eps_q else None
    revenue = rev_q[1] if rev_q else None
    return eps, revenue, period_end


def fetch_events_for_cik(cik: str) -> list:
    try:
        r = requests.get(SUBMISSIONS_URL.format(cik=cik), headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        recent = r.json().get("filings", {}).get("recent", {})
    except Exception:
        return []

    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    items = recent.get("items", [])
    accns = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    cutoff_past = (date.today() - timedelta(days=WINDOW_PAST_DAYS)).isoformat()
    cutoff_past_earnings = (date.today() - timedelta(days=EARNINGS_WINDOW_PAST_DAYS)).isoformat()
    cutoff_future = (date.today() + timedelta(days=WINDOW_FUTURE_DAYS)).isoformat()

    events = []
    for i, form in enumerate(forms):
        if form != "8-K":
            continue
        item_str = items[i] if i < len(items) else ""
        if not item_str:
            continue
        matched = [it.strip() for it in item_str.split(",") if it.strip() in ITEM_LABELS]
        if not matched:
            continue
        fdate = dates[i] if i < len(dates) else ""
        # A combined filing (e.g. "2.02,9.01") gets the longer earnings window
        # if it includes item 2.02 at all, even alongside another code.
        past_bound = cutoff_past_earnings if "2.02" in matched else cutoff_past
        if not fdate or not (past_bound <= fdate <= cutoff_future):
            continue
        labels = sorted({ITEM_LABELS[it][1] for it in matched})
        types = sorted({ITEM_LABELS[it][0] for it in matched})
        accn = (accns[i] if i < len(accns) else "").replace("-", "")
        doc = docs[i] if i < len(docs) else ""
        url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/{doc}"
               if accn and doc else
               f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K")
        event = {
            "date": fdate,
            "type": types,
            "label": " + ".join(labels),
            "items": item_str,
            "url": url,
        }
        if "earnings" in types:
            eps, revenue, period_end = _get_earnings_detail(cik, fdate)
            event["eps"] = eps
            event["revenue"] = revenue
            event["period_end"] = period_end
        events.append(event)
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="Only process these tickers (for testing)")
    args = ap.parse_args()

    latest = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    all_tickers = sorted({r["Ticker"] for r in latest.get("data", []) if r.get("Ticker")})
    tickers = sorted(args.only) if args.only else all_tickers

    cik_map = load_cik_map()
    splits = {}
    if SPLITS_JSON.exists():
        splits = json.loads(SPLITS_JSON.read_text(encoding="utf-8"))

    out = {}
    if not args.only and OUT_JSON.exists():
        out = json.loads(OUT_JSON.read_text(encoding="utf-8"))

    no_cik = []
    for i, ticker in enumerate(tickers, 1):
        cik = cik_map.get(ticker)
        events = fetch_events_for_cik(cik) if cik else []
        if not cik:
            no_cik.append(ticker)

        split = splits.get(ticker)
        split_date = split.get("date", "") if split else ""
        window_past = (date.today() - timedelta(days=WINDOW_PAST_DAYS)).isoformat()
        window_future = (date.today() + timedelta(days=WINDOW_FUTURE_DAYS)).isoformat()
        if split and window_past <= split_date <= window_future:
            events.append({
                "date": split["date"],
                "type": ["split"],
                "label": f"Stock Split ({split['ratio']}-for-1)",
                "items": "",
                "url": "",
            })

        events.sort(key=lambda e: e["date"], reverse=True)
        events = events[:MAX_EVENTS_PER_TICKER]
        if events:
            out[ticker] = events
        elif ticker in out:
            del out[ticker]  # no longer has qualifying events in the lookback window

        time.sleep(0.12)
        if i % 50 == 0:
            print(f"...{i}/{len(tickers)}", file=sys.stderr)

    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"Wrote events for {len(out)}/{len(tickers)} tickers to {OUT_JSON}")
    if no_cik:
        print(f"{len(no_cik)} ticker(s) had no EDGAR CIK match: {', '.join(no_cik)}")


if __name__ == "__main__":
    main()
