"""
Fetch Google News RSS for S&P 500 / Nasdaq-100 addition and removal
announcements. Saves results to data/index_news.json (90-day window).

Run: python data/test_index_news.py
"""

import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

QUERIES = [
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

LOOKBACK_DAYS = 90

# Phrases that indicate a retrospective performance article, not an announcement
SKIP_PHRASES = [
    "within a year",
    "within a month",
    "within months",
    "since joining",
    "since being added",
    "since addition",
    "year after joining",
    "months after joining",
    "a year of joining",
    "years after",
    "year later",
    "months later",
    "one year",
    "look back",
]

def is_retrospective(title: str) -> bool:
    t = title.lower()
    return any(phrase in t for phrase in SKIP_PHRASES)

def fetch_rss(label: str, query: str, lookback_days: int = LOOKBACK_DAYS) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [ERROR] {label}: {e}")
        return []

    root = ET.fromstring(resp.content)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    results = []
    for item in root.findall(".//item"):
        title   = (item.findtext("title") or "").strip()
        pub_raw = (item.findtext("pubDate") or "").strip()
        source  = (item.findtext("source") or "").strip()
        link    = (item.findtext("link") or "").strip()

        # Parse RFC-2822 date
        try:
            pub_dt = datetime.strptime(pub_raw, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        if pub_dt < cutoff:
            continue

        if is_retrospective(title):
            continue

        results.append({
            "date":   pub_dt.strftime("%Y-%m-%d"),
            "title":  title,
            "source": source,
            "link":   link,
        })

    return results


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*70}")
    print(f"  Index Addition/Removal News  —  last {LOOKBACK_DAYS} days")
    print(f"  Run date: {today}")
    print(f"{'='*70}\n")

    all_items = []

    for label, query in QUERIES:
        print(f"--- {label} ---")
        items = fetch_rss(label, query)

        if not items:
            print("  No results found.\n")
            continue

        for it in items:
            safe = lambda s: s.encode('ascii', 'replace').decode()
            print(f"  {it['date']}  {safe(it['source'])}")
            print("  " + safe(it['title']))
            print()
            all_items.append({"category": label, **it})

        print(f"  Total: {len(items)} article(s)\n")

    # Sort all items newest first
    all_items.sort(key=lambda x: x["date"], reverse=True)

    # Translate titles to Chinese
    print(f"\nTranslating {len(all_items)} titles to Chinese...")
    for item in all_items:
        suffix = " - " + item["source"]
        clean  = item["title"][:-len(suffix)] if item["title"].endswith(suffix) else item["title"]
        try:
            resp = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": clean},
                headers=HEADERS, timeout=10,
            )
            data = resp.json()
            item["title_cn"] = "".join(part[0] for part in data[0] if part[0])
        except Exception:
            item["title_cn"] = ""
        time.sleep(0.2)

    out = {
        "fetched": today,
        "lookback_days": LOOKBACK_DAYS,
        "items": all_items,
    }

    out_path = Path(__file__).parent / "index_news.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(all_items)} total article(s) to {out_path}")


if __name__ == "__main__":
    main()
