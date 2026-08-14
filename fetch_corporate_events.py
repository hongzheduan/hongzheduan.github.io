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

Only shows events within +/- 2 months of today (see WINDOW_PAST_DAYS /
WINDOW_FUTURE_DAYS below), so unlike the descriptions script this needs
re-running periodically to both pick up new filings and drop events that
have aged out of the window — every ticker is refreshed each run since
new filings can appear for any of them at any time.
"""
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
LATEST_JSON = ROOT / "data" / "latest.json"
SPLITS_JSON = ROOT / "data" / "splits.json"
OUT_JSON = ROOT / "data" / "corporate_events.json"

HEADERS = {"User-Agent": "Baizora support@baizora.com"}
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

# 8-K item code -> (type slug, human label)
ITEM_LABELS = {
    "1.01": ("agreement", "Material Agreement"),
    "1.03": ("bankruptcy", "Bankruptcy / Receivership"),
    "2.01": ("acquisition", "Acquisition / Disposition Completed"),
    "3.01": ("delisting", "Delisting Notice"),
    "5.01": ("control", "Change in Control"),
    "5.02": ("leadership", "Leadership Change"),
}

MAX_EVENTS_PER_TICKER = 12
# Window is ±2 months around today. 8-K filings are always retrospective (SEC
# requires filing within ~4 business days of the event) so in practice this
# only means "last 2 months" for the EDGAR-sourced events; the "next 2 months"
# half of the window exists for data/splits.json, which can carry an
# announced-but-not-yet-effective split date (see scanner_tiingo.py's
# "Upcoming splits" handling).
WINDOW_PAST_DAYS = 60
WINDOW_FUTURE_DAYS = 60


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
        if not fdate or not (cutoff_past <= fdate <= cutoff_future):
            continue
        labels = sorted({ITEM_LABELS[it][1] for it in matched})
        types = sorted({ITEM_LABELS[it][0] for it in matched})
        accn = (accns[i] if i < len(accns) else "").replace("-", "")
        doc = docs[i] if i < len(docs) else ""
        url = (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/{doc}"
               if accn and doc else
               f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=8-K")
        events.append({
            "date": fdate,
            "type": types,
            "label": " + ".join(labels),
            "items": item_str,
            "url": url,
        })
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
