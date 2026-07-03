"""Hourly refresh of data/market_news.json, data/market_news_cn.json, and the news section of
the downloadable daily_briefing.txt / daily_briefing_cn.txt.

Runs independently of the main scanner. The homepage used to fetch this feed live from the
/api/market-news Cloud Function, but Google started returning HTTP 503 bot-block pages to
the Cloud Function's GCP egress IP on 2026-07-02, so that live fetch has been stuck serving
stale cached data ever since. This job re-fetches from a GitHub Actions runner IP (unaffected
by that block, same as the main scanner) on its own cron cadence and writes the static JSON
files the homepage reads directly, so the "Market News" section stays fresh independent of
the Cloud Function's health.

The top-gainers/top-volume tables in the .txt briefing still only change once per scan (they
need real price data), but the news list is rebuilt here every run using the same
_build_briefing_txt(_cn) helpers the scanner uses, from the same data/daily_digest.json the
homepage card reads — so the download's news always matches what's currently shown on the page.
"""
import copy
import json

import scanner_tiingo as s


def main():
    fetched_en, items_en = s._fetch_market_news_items(30, "en")
    if not items_en:
        print("news_refresh: 0 items fetched, leaving existing files untouched")
        return

    with open(s.MARKET_NEWS_JSON, "w", encoding="utf-8") as f:
        json.dump({"fetched": fetched_en, "items": items_en}, f, ensure_ascii=False)
    print(f"market_news.json: {len(items_en)} items")

    items_cn_all = copy.deepcopy(items_en)
    s._translate_items_to_zh(items_cn_all)
    items_cn = [it for it in items_cn_all if it.get("title_cn")]
    with open(s.MARKET_NEWS_CN_JSON, "w", encoding="utf-8") as f:
        json.dump({"fetched": fetched_en, "items": items_cn}, f, ensure_ascii=False)
    n_dropped = len(items_en) - len(items_cn)
    print(f"market_news_cn.json: {len(items_cn)} items ({n_dropped} dropped, translation failed)")

    try:
        with open(s.DIGEST_JSON, encoding="utf-8") as f:
            digest = json.load(f)
    except FileNotFoundError:
        print("news_refresh: no daily_digest.json yet, skipping .txt briefing rebuild")
        return

    market_date, scan_time = digest["date"], digest["scan_time"]
    headlines = [f"  • {it['title']}" + (f" — {it['source']}" if it['source'] else "") for it in items_en]
    with open(s.BRIEFING_TXT, "w", encoding="utf-8") as f:
        f.write(s._build_briefing_txt(market_date, scan_time, digest, headlines))
    print("daily_briefing.txt refreshed")

    headlines_cn = [f"  • {it['title_cn']}" + (f" — {it['source']}" if it['source'] else "") for it in items_cn]
    with open(s.BRIEFING_TXT_CN, "w", encoding="utf-8") as f:
        f.write(s._build_briefing_txt_cn(market_date, scan_time, digest, headlines_cn))
    print("daily_briefing_cn.txt refreshed")


if __name__ == "__main__":
    main()
