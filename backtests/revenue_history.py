#!/usr/bin/env python3
"""
Point-in-time revenue history from SEC EDGAR companyfacts (2026-10-23).

For the Baizora Tracker revenue test ("quarter revenue vs previous quarter" and
"yearly revenue vs previous year"). For every current S&P 500 / Nasdaq-100 stock:

  quarters   [end, value, available]   3-month revenue; Q4 = fiscal year minus Q1..Q3
  years      [end, value, available]   fiscal-year revenue (10-K / 20-F / 40-F)

"available" is the FIRST filing date of that number, and the value is the one
first filed (later restatements ignored), so a backtest on date t only sees what
was public on t. Revenue tags are merged in priority order because companies
switch tags over time; banks/insurers that report no revenue line are left out.

Writes backtests/revenue_history.json. Fetch takes ~2 min (SEC limit 10 req/s).

Usage: python backtests/revenue_history.py
"""
import datetime
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "revenue_history.json"
HEADERS = {"User-Agent": "Baizora support@baizora.com"}

TAGS = (
    ("us-gaap", "Revenues"),
    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
    ("us-gaap", "SalesRevenueNet"),
    ("us-gaap", "SalesRevenueGoodsNet"),
    ("us-gaap", "SalesRevenueServicesNet"),
    ("us-gaap", "RevenuesNetOfInterestExpense"),
    ("ifrs-full", "Revenue"),
    ("ifrs-full", "RevenueFromContractsWithCustomers"),
)
FORMS = {"10-Q", "10-K", "10-K405", "10-KT", "20-F", "40-F", "6-K"}


def _days(e):
    return (datetime.date.fromisoformat(e["end"]) - datetime.date.fromisoformat(e["start"])).days


def extract(facts):
    """{(start, end): (value, first_filed)} for durations ~1Q / ~9M / ~1Y, tags merged by priority."""
    periods = {}
    for ns, tag in TAGS:
        units = facts.get(ns, {}).get(tag, {}).get("units", {})
        if not units:
            continue
        unit = "USD" if "USD" in units else next(iter(units))  # growth is unit-free
        for e in units[unit]:
            if e.get("form") not in FORMS or not e.get("start") or not e.get("filed") or e.get("val") is None:
                continue
            key = (e["start"], e["end"])
            cur = periods.get(key)
            # first filing wins; an earlier tag in TAGS wins a tie on the same filing date
            if cur is None or e["filed"] < cur[1]:
                periods[key] = (e["val"], e["filed"])
    return periods


def series(periods):
    quarters, years, ytd9 = {}, {}, {}
    for (start, end), (val, filed) in periods.items():
        d = _days({"start": start, "end": end})
        if 80 <= d <= 100:
            quarters[end] = (val, filed, start)
        elif 260 <= d <= 285:
            ytd9[(start, end)] = (val, filed)
        elif 350 <= d <= 380:
            years[end] = (val, filed, start)
    # Q4 = fiscal year minus the three quarters inside it (or minus 9-month YTD)
    for end, (fy, filed, fy_start) in years.items():
        if end in quarters:
            continue
        inside = [q for e, q in quarters.items() if q[2] and q[2] >= fy_start and e < end]
        nine = next((v for (s, e), v in ytd9.items() if s == fy_start), None)
        if len(inside) == 3:
            q4 = fy - sum(q[0] for q in inside)
        elif nine:
            q4 = fy - nine[0]
        else:
            continue
        quarters[end] = (q4, filed, None)
    q = sorted([e, v[0], v[1]] for e, v in quarters.items())
    y = sorted([e, v[0], v[1]] for e, v in years.items())
    return q, y


def main():
    latest = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    tickers = [r["Ticker"] for r in latest["data"] if r.get("InSP500") or r.get("InNASDAQ100")]
    cik_map = {v["ticker"].upper(): str(v["cik_str"]).zfill(10)
               for v in requests.get("https://www.sec.gov/files/company_tickers.json",
                                     headers=HEADERS, timeout=20).json().values()}
    out, missing = {}, []
    for i, t in enumerate(tickers):
        cik = next((cik_map.get(v) for v in (t, t.replace("-", "."), t.replace("-", "")) if cik_map.get(v)), None)
        if not cik:
            missing.append(t)
            continue
        try:
            facts = requests.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                                 headers=HEADERS, timeout=30).json().get("facts", {})
        except Exception as e:
            print(t, "fetch failed:", e)
            missing.append(t)
            continue
        q, y = series(extract(facts))
        if q or y:
            out[t] = {"quarters": q, "years": y}
        else:
            missing.append(t)
        if i % 50 == 0:
            print(f"{i}/{len(tickers)}")
        time.sleep(0.12)
    OUT.write_text(json.dumps({"fetched": datetime.date.today().isoformat(), "tickers": out},
                              separators=(",", ":")), encoding="utf-8")
    print(f"{len(out)} tickers with revenue, {len(missing)} without: {' '.join(missing)}")


if __name__ == "__main__":
    main()
