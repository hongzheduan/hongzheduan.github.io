#!/usr/bin/env python3
"""
Fetch a one-paragraph company description per ticker from Wikipedia's REST
summary API and cache it in data/company_descriptions.json.

Run manually / occasionally — descriptions rarely change, so this is not
part of the daily scanner.yml pipeline. Re-run to pick up new constituents;
already-cached tickers are skipped unless --refresh is passed.

Tickers Wikipedia's search can't resolve confidently (wrong article,
disambiguation, no hit) are left out and printed at the end so a manual
mapping can be added to data/company_description_overrides.json
(ticker -> exact Wikipedia page title), then the script re-run.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
LATEST_JSON = ROOT / "data" / "latest.json"
OUT_JSON = ROOT / "data" / "company_descriptions.json"
OVERRIDES_JSON = ROOT / "data" / "company_description_overrides.json"

HEADERS = {"User-Agent": "Baizora/1.0 (https://baizora.com; support@baizora.com) company-description-fetch"}
SEARCH_API = "https://en.wikipedia.org/w/api.php"
SUMMARY_API = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

SUFFIX_RE = re.compile(
    r"\s+(INCORPORATED|INC|CORPORATION|CORP|COMPANY|CO|LIMITED|LTD|LLC|PLC|GROUP|"
    r"HOLDINGS?|N\.?V\.?|S\.?A\.?|A\.?G\.?|CLASS\s*A|CLASS\s*B|CL\s*A|CL\s*B)\.?$",
    re.IGNORECASE,
)


def clean_name(name: str) -> str:
    name = name.strip()
    while True:
        new = SUFFIX_RE.sub("", name).strip().rstrip(".,")
        if new == name or not new:
            break
        name = new
    return name.title()


def wiki_search_title(query: str) -> str | None:
    params = {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 1}
    r = requests.get(SEARCH_API, params=params, headers=HEADERS, timeout=10)
    r.raise_for_status()
    hits = r.json().get("query", {}).get("search", [])
    return hits[0]["title"] if hits else None


def wiki_summary(title: str) -> dict | None:
    url = SUMMARY_API.format(title=requests.utils.quote(title, safe=""))
    r = requests.get(url, headers=HEADERS, timeout=10)
    if r.status_code != 200:
        return None
    return r.json()


def fetch_description(ticker: str, company_name: str, overrides: dict) -> dict:
    if ticker in overrides and not overrides[ticker]:
        # Explicit "no confident Wikipedia match exists" — don't fall through to the
        # fuzzy search, which would just re-match the wrong article every run.
        return {"ok": False, "reason": "no match (overrides: null)"}

    override_title = overrides.get(ticker)
    if override_title:
        title = override_title
    else:
        query = clean_name(company_name)
        title = wiki_search_title(f"{query} company")
        if not title:
            return {"ok": False, "reason": "no search hit"}

    summary = wiki_summary(title)
    if not summary or summary.get("type") == "disambiguation":
        return {"ok": False, "reason": "no summary / disambiguation", "title": title}

    extract = (summary.get("extract") or "").strip()
    if not extract:
        return {"ok": False, "reason": "empty extract", "title": title}

    return {
        "ok": True,
        "name": summary.get("title", title),
        "description": extract,
        "wiki_url": (summary.get("content_urls") or {}).get("desktop", {}).get("page"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="Re-fetch tickers already in the cache")
    ap.add_argument("--only", nargs="*", help="Only process these tickers (for testing)")
    args = ap.parse_args()

    latest = json.loads(LATEST_JSON.read_text(encoding="utf-8"))
    rows = latest.get("data", [])
    name_by_ticker = {r["Ticker"]: r.get("CompanyName", r["Ticker"]) for r in rows if r.get("Ticker")}

    overrides = {}
    if OVERRIDES_JSON.exists():
        overrides = json.loads(OVERRIDES_JSON.read_text(encoding="utf-8"))

    out = {}
    if OUT_JSON.exists():
        out = json.loads(OUT_JSON.read_text(encoding="utf-8"))

    tickers = sorted(args.only) if args.only else sorted(name_by_ticker)
    failures = []
    fetched = 0
    for i, ticker in enumerate(tickers, 1):
        if not args.refresh and ticker in out and out[ticker].get("description"):
            continue
        result = fetch_description(ticker, name_by_ticker.get(ticker, ticker), overrides)
        if result["ok"]:
            out[ticker] = {
                "name": result["name"],
                "description": result["description"],
                "source": "wikipedia",
                "wiki_url": result.get("wiki_url"),
            }
            fetched += 1
        else:
            failures.append((ticker, name_by_ticker.get(ticker, ticker), result.get("reason"), result.get("title")))
        time.sleep(0.15)
        if i % 25 == 0:
            print(f"...{i}/{len(tickers)}", file=sys.stderr)

    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"Wrote {len(out)} descriptions to {OUT_JSON} ({fetched} newly fetched)")
    if args.only:
        for t in tickers:
            print(f"{t}: {json.dumps(out.get(t), ensure_ascii=False)}")

    if failures:
        print(f"\n{len(failures)} ticker(s) need overrides in {OVERRIDES_JSON.name}:")
        for t, n, reason, title in failures:
            print(f"  {t:<6} ({n}): {reason}" + (f" [tried: {title}]" if title else ""))


if __name__ == "__main__":
    main()
