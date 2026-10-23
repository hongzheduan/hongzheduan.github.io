#!/usr/bin/env python3
"""
Product-launch headlines for S&P 500 / Nasdaq-100 companies (2026-10-23, for the SB Tracker).

Searches Google News RSS in batches of company names combined with launch words, and keeps a
headline only when it STARTS with the company's name followed, within two words, by a launch
verb ("Apple unveils ...", "Nvidia's new chip launches ..." does not count). That keeps
precision reasonable: a loose "name anywhere + launch anywhere" match picked up headlines like
"AHF launches Quiet Comfort ..." for Comfort Systems. Recall is partial: launches reported with
other wording, or under a brand name only, are missed.

Merges into data/product_news.json {"fetched", "items": [{ticker, date, title, source, link}]},
keeping KEEP_DAYS of history, since the RSS feed only reaches back so far. Google News's
"when:" filter is not reliably applied to these OR queries, so dates are filtered here.

Usage: python fetch_product_news.py
"""
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
LATEST = ROOT / "data" / "latest.json"
OUT = ROOT / "data" / "product_news.json"
BATCH = 12          # company names per query (a query returns at most 100 items)
KEEP_DAYS = 120
SLEEP = 1.5
UA = {"User-Agent": "Mozilla/5.0 (compatible; Baizora/1.0)"}

SUFFIX = r"\b(inc|incorporated|corp|corporation|co|company|companies|ltd|limited|plc|holdings?|group|the|class [a-z]|n\.?v|s\.?a|lp|llc|se|ag)\b\.?"
# First words too generic to stand alone as a company name in a headline.
COMMON = {"american", "general", "first", "united", "international", "national", "energy", "global", "public",
          "digital", "western", "southern", "eastern", "northern", "federal", "capital", "financial", "health",
          "entertainment", "communications", "systems", "services", "technology", "technologies", "pacific",
          "texas", "consolidated", "royal", "electronic", "advanced", "applied", "analog", "host", "booking",
          "target", "match", "dollar", "best", "live", "news", "old", "home", "ross", "snap", "block", "arch",
          "core", "delta", "comfort", "johnson", "rocket", "thomson", "fidelity", "crown", "norwegian", "bloom", "realty", "universal", "regency", "public"}
# Brand names headlines actually use.
ALIASES = {"GOOGL": ["google", "alphabet"], "GOOG": ["google", "alphabet"], "META": ["meta", "facebook", "instagram"],
           "AMZN": ["amazon", "aws"], "MSFT": ["microsoft"], "NVDA": ["nvidia"], "TSLA": ["tesla"],
           "DAL": ["delta air lines", "delta"], "TGT": ["target"], "HD": ["home depot"], "BKNG": ["booking.com"],
           "XYZ": ["block", "square", "cash app"], "SNAP": ["snap", "snapchat"], "CRM": ["salesforce"],
           "SPCX": ["spacex"], "HON": ["honeywell"], "PEP": ["pepsico", "pepsi"], "KO": ["coca-cola"], "MCD": ["mcdonald's"],
           "SBUX": ["starbucks"], "DIS": ["disney"], "NFLX": ["netflix"], "CMCSA": ["comcast"], "ABNB": ["airbnb"],
           "UBER": ["uber"], "PYPL": ["paypal", "venmo"], "ADBE": ["adobe"], "AMD": ["amd"], "QCOM": ["qualcomm"],
           "AVGO": ["broadcom"], "CSCO": ["cisco"], "IBM": ["ibm"], "HPQ": ["hp"], "HPE": ["hpe", "hewlett packard enterprise"],
           "GM": ["gm", "general motors", "chevrolet", "cadillac"], "F": ["ford"], "LLY": ["lilly", "eli lilly"],
           "JNJ": ["johnson & johnson", "j&j"], "PG": ["procter & gamble", "p&g"], "WMT": ["walmart"], "COST": ["costco"]}
VERB = r"(launch(es|ed)?|unveil(s|ed)?|introduc(es|ed)|debut(s|ed)?|rolls out|rolled out|releases|released|announces new|reveals new|expands .* with new)"
# Headlines about launching something that is not a product (financing, programs, units, missions...).
NOT_PRODUCT = re.compile(r"\b(buyback|repurchase|offering|notes due|senior notes|dividend|tender offer|ipo|fund|competition|award|"
                         r"scholarship|foundation|lawsuit|investigation|probe|campaign|program helping|practice|unit|division|"
                         r"office|mission|satellites? to orbit|strike|layoffs?|restructuring|review)\b")
QUERY_VERBS = '(launches OR unveils OR introduces OR debuts OR "rolls out" OR releases OR "announces new")'


def aliases(data):
    out = {}
    for r in data["data"]:
        if not (r.get("InSP500") or r.get("InNASDAQ100")):
            continue
        t = r["Ticker"]
        n = (r.get("CompanyName") or "").lower().replace(",", " ")
        n = re.sub(r"/[a-z]*/?", " ", n)
        n = re.sub(SUFFIX, " ", n)
        n = re.sub(r"\s+", " ", n).strip(" .&-")
        a = set(ALIASES.get(t, []))
        if len(n) >= 3:
            a.add(n)
        w = n.split()
        if t not in ALIASES and w and len(w[0]) >= 5 and w[0] not in COMMON:
            a.add(w[0])
        out[t] = a
    # A short name shared by two companies (johnson: J&J / Johnson Controls; huntington:
    # Huntington Bancshares / Huntington Ingalls) is ambiguous: drop it for both.
    owners = {}
    for t, a in out.items():
        for n in a:
            owners.setdefault(n, set()).add(t)
    for t, a in out.items():
        keep = {n for n in a if len(owners[n]) == 1 or n in ALIASES.get(t, []) or len(n.split()) > 1}
        if not any(len(owners[n]) == 1 or n in ALIASES.get(t, []) for n in keep):
            keep = {n for n in a if len(n.split()) > 1} or a   # share-class pairs (GOOG/GOOGL) keep the full name
        out[t] = sorted(keep or a, key=len, reverse=True)
    return out


def headline_match(title, names):
    """True if the headline starts with one of names, then a launch verb within two words."""
    low = title.lower().replace("’", "'")
    if NOT_PRODUCT.search(low):
        return False
    for n in names:
        if re.match(r"^" + re.escape(n) + r"('s)?\s+(\S+\s+){0,2}?" + VERB + r"\b", low):
            return True
    return False


def search(q):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as resp:
                return list(ET.fromstring(resp.read()).iter("item"))
        except Exception as e:   # 429 / timeouts: back off and retry
            print("search failed:", e)
            time.sleep(10 * (attempt + 1))
    return []


def main():
    data = json.loads(LATEST.read_text(encoding="utf-8"))
    names = aliases(data)
    try:
        out = json.loads(OUT.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        out = {"items": []}
    seen = {(i["ticker"], i["title"]) for i in out["items"]}
    tickers = sorted(names)
    added = 0
    for b in range(0, len(tickers), BATCH):
        grp = tickers[b:b + BATCH]
        q = "(" + " OR ".join(f'"{n}"' for t in grp for n in names[t][-1:]) + ") " + QUERY_VERBS
        for el in search(q):
            title = (el.findtext("title") or "").strip()
            src_el = el.find("source")
            source = src_el.text.strip() if src_el is not None and src_el.text else ""
            if source and title.endswith(" - " + source):
                title = title[: -len(source) - 3]
            try:
                d = parsedate_to_datetime(el.findtext("pubDate")).astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
            except Exception:
                continue
            for t in grp:
                if headline_match(title, names[t]) and (t, title) not in seen:
                    out["items"].append({"ticker": t, "date": d, "title": title, "source": source,
                                         "link": (el.findtext("link") or "").strip()})
                    seen.add((t, title))
                    added += 1
        time.sleep(SLEEP)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    out["items"] = sorted((i for i in out["items"] if i["date"] >= cutoff), key=lambda i: (i["date"], i["ticker"]), reverse=True)
    out["fetched"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{added} new headlines, {len(out['items'])} kept")


if __name__ == "__main__":
    main()
