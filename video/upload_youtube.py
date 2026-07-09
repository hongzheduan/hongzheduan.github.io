"""
Upload a video to YouTube using OAuth refresh token (no browser needed).

Usage:
    python video/upload_youtube.py \
        --file video/sp500_movers.mp4 \
        --title "S&P 500 Top Movers — 2026-05-22" \
        --description "..." \
        --privacy public

Credentials are read from environment variables:
    YOUTUBE_CLIENT_ID
    YOUTUBE_CLIENT_SECRET
    YOUTUBE_REFRESH_TOKEN
"""

import argparse
import datetime
import json
import os
import random
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
COVERING_DIR = SCRIPT_DIR / "covering"

# Same weekday mapping as generate_shorts.py's cover_path_for() — duplicated (not
# imported) since this script is meant to stay a standalone upload utility.
_WEEKDAY_BY_TYPE = {
    "volume_spikes": "Monday",
    "best_performer": "Tuesday",
    "6m_breakout": "Wednesday",
    "1y_vol_peak": "Thursday",
    "index_spotlight": "Friday",
}


def cover_path_for(video_type, date_obj):
    """Picks one of the 4 pre-made cover images for this video type's weekday,
    rotating by calendar day (not upload count) so re-running for the same date
    always picks the same cover. Returns None if no cover set exists for this type."""
    base_type = video_type[:-3] if video_type.endswith("_cn") else video_type
    weekday = _WEEKDAY_BY_TYPE.get(base_type)
    if not weekday:
        return None
    variant = date_obj.toordinal() % 4 + 1
    path = COVERING_DIR / f"{weekday}_{variant}.png"
    return path if path.exists() else None


_TUESDAY_TF_ROTATION = [
    {"label_en": "2-Week",   "label_short": "2W", "window_en": "two weeks",     "label_cn": "两周",   "window_cn": "两周"},
    {"label_en": "1-Month",  "label_short": "1M", "window_en": "one month",     "label_cn": "一个月", "window_cn": "一个月"},
    {"label_en": "3-Month",  "label_short": "3M", "window_en": "three months",  "label_cn": "三个月", "window_cn": "三个月"},
    {"label_en": "6-Month",  "label_short": "6M", "window_en": "six months",    "label_cn": "六个月", "window_cn": "六个月"},
    {"label_en": "9-Month",  "label_short": "9M", "window_en": "nine months",   "label_cn": "九个月", "window_cn": "九个月"},
    {"label_en": "1-Year",   "label_short": "1Y", "window_en": "twelve months", "label_cn": "一年",  "window_cn": "十二个月"},
]


def _tuesday_tf(date_str):
    d = datetime.date.fromisoformat(date_str)
    return _TUESDAY_TF_ROTATION[d.isocalendar()[1] % 6]


_WEDNESDAY_TF_ROTATION = [
    {"label_en": "1-Month", "label_cn": "一个月", "min_drawdown": 10},
    {"label_en": "3-Month", "label_cn": "三个月", "min_drawdown": 10},
    {"label_en": "6-Month", "label_cn": "六个月", "min_drawdown": 10},
    {"label_en": "9-Month", "label_cn": "九个月", "min_drawdown": 10},
    {"label_en": "1-Year",  "label_cn": "一年",   "min_drawdown": 10},
]


def _wednesday_tf(date_str):
    d = datetime.date.fromisoformat(date_str)
    return _WEDNESDAY_TF_ROTATION[d.isocalendar()[1] % 5]


_THURSDAY_TF_ROTATION = [
    {"label_en": "1-Month", "label_cn": "一个月", "window_en": "one month",     "window_cn": "一个月"},
    {"label_en": "3-Month", "label_cn": "三个月", "window_en": "three months",  "window_cn": "三个月"},
    {"label_en": "6-Month", "label_cn": "六个月", "window_en": "six months",    "window_cn": "六个月"},
    {"label_en": "9-Month", "label_cn": "九个月", "window_en": "nine months",   "window_cn": "九个月"},
    {"label_en": "1-Year",  "label_cn": "一年",   "window_en": "twelve months", "window_cn": "十二个月"},
]


def _thursday_tf(date_str):
    d = datetime.date.fromisoformat(date_str)
    return _THURSDAY_TF_ROTATION[d.isocalendar()[1] % 5]


def build_credentials():
    client_id     = os.environ["YOUTUBE_CLIENT_ID"]
    client_secret = os.environ["YOUTUBE_CLIENT_SECRET"]
    refresh_token = os.environ["YOUTUBE_REFRESH_TOKEN"]

    try:
        from google.oauth2.credentials import Credentials
    except ImportError:
        print("Missing dependency. Run:  pip install google-auth google-api-python-client")
        sys.exit(1)

    return Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )


def set_thumbnail(youtube, video_id, thumbnail_path):
    """Sets a custom thumbnail on an already-uploaded video. Non-fatal on failure —
    custom thumbnails require a phone-verified channel, so an unverified channel (or
    any other API hiccup) should log a warning and let the rest of the upload stand,
    not fail the whole run over a cosmetic image."""
    import googleapiclient.http
    try:
        media = googleapiclient.http.MediaFileUpload(str(thumbnail_path), mimetype="image/png")
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
        print(f"  Thumbnail set: {thumbnail_path.name}")
    except Exception as e:
        print(f"  WARNING: failed to set thumbnail ({e.__class__.__name__}: {e}) — "
              f"video uploaded fine, thumbnail left as YouTube's auto-picked frame. "
              f"(Custom thumbnails require a phone-verified channel.)")


def upload(file_path, title, description, privacy, category_id="22", thumbnail_path=None):
    try:
        import googleapiclient.discovery
        import googleapiclient.http
        from google.auth.transport.requests import Request
    except ImportError:
        print("Missing dependency. Run:  pip install google-auth google-api-python-client")
        sys.exit(1)

    creds = build_credentials()
    creds.refresh(Request())

    youtube = googleapiclient.discovery.build(
        "youtube", "v3", credentials=creds, cache_discovery=False
    )

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id,
            "tags": ["baizora", "stock market", "S&P 500", "Nasdaq-100",
                     "price volume", "large cap"],
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = googleapiclient.http.MediaFileUpload(
        file_path, mimetype="video/mp4", resumable=True, chunksize=4 * 1024 * 1024
    )

    request = youtube.videos().insert(
        part=",".join(body.keys()), body=body, media_body=media
    )

    print(f"Uploading: {file_path}")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.resumable_progress / status.total_size * 100)
            print(f"  {pct}%", end="\r")

    video_id = response["id"]
    print(f"  Done → https://youtu.be/{video_id}")

    if thumbnail_path:
        set_thumbnail(youtube, video_id, thumbnail_path)

    return video_id


# ── Per-type metadata ──────────────────────────────────────────────────────────

DISCLAIMER_EN = (
    "For informational purposes only. Not financial advice. "
    "Past performance does not guarantee future results.\n\n"
    "Data: baizora.com | Free 7-day trial available."
)
DISCLAIMER_CN = (
    "仅供参考，不构成投资建议。过往表现不代表未来结果。\n\n"
    "数据来源：baizora.com | 提供七天免费试用。"
)

PLATFORM_LINK_EN = (
    "For platform details, see: https://www.youtube.com/watch?v=eZlmxP_wV5g"
)
PLATFORM_LINK_CN = (
    "了解平台详情，请观看：https://www.youtube.com/watch?v=XwqEO9RJ0HE"
)

def make_meta(video_type, date):
    if video_type == "sp500_movers":
        title = random.choice([
            f"S&P 500 Top Movers — {date}",
            f"S&P 500 Biggest Movers Today — {date}",
            f"Top Price Moves in the S&P 500 — {date}",
            f"S&P 500 Daily Movers Report — {date}",
        ])
        return (
            title,
            f"Today's biggest price and volume movers in the S&P 500, as of {date}.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
        )
    if video_type == "nasdaq_movers":
        title = random.choice([
            f"Nasdaq-100 Top Movers — {date}",
            f"Nasdaq-100 Biggest Movers Today — {date}",
            f"Top Price Moves in the Nasdaq-100 — {date}",
            f"Nasdaq-100 Daily Movers Report — {date}",
        ])
        return (
            title,
            f"Today's biggest price and volume movers in the Nasdaq-100, as of {date}.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
        )
    if video_type == "volume_spikes":
        title = random.choice([
            f"Biggest Volume Spikes Today — {date}",
            f"Top Unusual Volume Stocks Today — {date}",
            f"Today's Biggest Volume Surges — {date}",
            f"Stocks With Unusual Volume Today — {date}",
            f"Top Volume Breakouts Today — {date}",
        ])
        return (
            title,
            f"Large-cap stocks with unusual trading volume today ({date}), across S&P 500 and Nasdaq-100.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
        )
    if video_type == "best_performer":
        tf    = _tuesday_tf(date)
        label = tf["label_en"]
        short = tf["label_short"]
        window = tf["window_en"]
        num, unit = label.split("-")
        numeral_window = f"{num} {unit}" if num == "1" else f"{num} {unit}s"
        title = random.choice([
            f"Top {label} Winners — {date}",
            f"Best Performing Stocks ({numeral_window}) — {date}",
            f"Top Stock Winners Over {numeral_window} — {date}",
            f"Top {label} Performers — {date}",
            f"Best Large-Cap Stocks ({label} Returns) — {date}",
        ])
        return (
            title,
            f"Top large-cap stocks by trailing {window} price appreciation, as of {date}.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
        )
    if video_type == "volume_spikes_cn":
        title = random.choice([
            f"今日成交量激增最多股票 — {date}",
            f"今日成交量最异常股票 — {date}",
            f"今日成交量暴涨股票 — {date}",
            f"今日成交量异常股票 — {date}",
            f"今日成交量突破股票 — {date}",
        ])
        return (
            title,
            f"S&P 500和纳斯达克100中今日出现异常交易量的大盘股（{date}）。\n\n{PLATFORM_LINK_CN}\n\n{DISCLAIMER_CN}",
        )
    if video_type == "best_performer_cn":
        tf       = _tuesday_tf(date)
        label_cn = tf["label_cn"]
        window_cn = tf["window_cn"]
        title = random.choice([
            f"{label_cn}涨幅冠军股票 — {date}",
            f"表现最佳股票（{window_cn}）— {date}",
            f"过去{window_cn}涨幅最大股票 — {date}",
            f"{label_cn}表现最佳股票 — {date}",
            f"最佳大盘股（{label_cn}收益）— {date}",
        ])
        return (
            title,
            f"截至{date}，S&P 500和纳斯达克100中过去{window_cn}涨幅最大的大盘股。\n\n{PLATFORM_LINK_CN}\n\n{DISCLAIMER_CN}",
        )
    if video_type == "6m_breakout":
        wtf   = _wednesday_tf(date)
        label = wtf["label_en"]
        title = random.choice([
            f"{label} High Breakouts — {date}",
            f"Large-Caps Reclaiming Their {label} High — {date}",
            f"New {label} High After {wtf['min_drawdown']}%+ Pullback — {date}",
            f"Breakout Alert: {label} Highs Crossed — {date}",
        ])
        return (
            title,
            f"Large-cap stocks from S&P 500 and Nasdaq-100 that crossed their {label.lower()} high for the first time in the past 2 weeks, after a {wtf['min_drawdown']}%+ real pullback, as of {date}.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
        )
    if video_type == "6m_breakout_cn":
        wtf      = _wednesday_tf(date)
        label_cn = wtf["label_cn"]
        title = random.choice([
            f"{label_cn}新高突破 — {date}",
            f"大盘股突破{label_cn}高点 — {date}",
            f"{wtf['min_drawdown']}%回调后创{label_cn}新高 — {date}",
            f"突破警报：{label_cn}高点首次被突破 — {date}",
        ])
        return (
            title,
            f"S&P 500和纳斯达克100中，在经历{wtf['min_drawdown']}%以上真实回调后，过去两周内首次突破{label_cn}高点的大盘股（{date}）。\n\n{PLATFORM_LINK_CN}\n\n{DISCLAIMER_CN}",
        )
    if video_type == "1y_vol_peak":
        ttf   = _thursday_tf(date)
        label = ttf["label_en"]
        window = ttf["window_en"]
        num, unit = label.split("-")
        numeral_window = f"{num} {unit}" if num == "1" else f"{num} {unit}s"
        title = random.choice([
            f"Stocks Hitting New {label} Volume Highs — {date}",
            f"New {label} Volume Leaders — {date}",
            f"Highest Trading Volume in {numeral_window} — {date}",
            f"{label} Volume Breakouts — {date}",
            f"Record {label} Trading Volume — {date}",
        ])
        return (
            title,
            f"Large-cap stocks from S&P 500 and Nasdaq-100 recording their biggest single-day volume in the past {window}, as of {date}.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
        )
    if video_type == "1y_vol_peak_cn":
        ttf      = _thursday_tf(date)
        label_cn = ttf["label_cn"]
        window_cn = ttf["window_cn"]
        title = random.choice([
            f"创下{label_cn}成交量新高的股票 — {date}",
            f"{label_cn}成交量新领跑股票 — {date}",
            f"过去{window_cn}最高交易量 — {date}",
            f"{label_cn}成交量突破股票 — {date}",
            f"创纪录{label_cn}交易量股票 — {date}",
        ])
        return (
            title,
            f"S&P 500和纳斯达克100中，今日创下过去{window_cn}最大单日成交量的大盘股（{date}）。\n\n{PLATFORM_LINK_CN}\n\n{DISCLAIMER_CN}",
        )
    if video_type == "index_spotlight":
        title = random.choice([
            f"New Index Members — {date}",
            f"Newest S&P 500 & Nasdaq-100 Members — {date}",
            f"New Index Additions — {date}",
            f"Recent Index Additions — {date}",
            f"Fresh Index Members — {date}",
        ])
        return (
            title,
            f"A look at how a recent S&P 500 or Nasdaq-100 addition has performed since joining the index, as of {date}.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
        )
    if video_type == "index_spotlight_cn":
        title = random.choice([
            f"新晋指数成员 — {date}",
            f"标普500/纳斯达克100最新成员 — {date}",
            f"新纳入指数成分股 — {date}",
            f"近期指数新增成分股 — {date}",
            f"最新指数成员 — {date}",
        ])
        return (
            title,
            f"追踪一只近期加入标普500或纳斯达克100的成分股，截至{date}的完整表现。\n\n{PLATFORM_LINK_CN}\n\n{DISCLAIMER_CN}",
        )
    if video_type == "news_report":
        title = random.choice([
            f"Daily Market News Recap — {date}",
            f"Today's Top Market Headlines — {date}",
            f"Baizora Report: Market News — {date}",
            f"Market News Roundup — {date}",
        ])
        return (
            title,
            f"Today's top market news headlines, summarized — {date}.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
        )
    if video_type == "news_report_cn":
        title = random.choice([
            f"每日市场新闻速览 — {date}",
            f"今日市场要闻 — {date}",
            f"贝佐拉报告：市场新闻 — {date}",
            f"市场新闻汇总 — {date}",
        ])
        return (
            title,
            f"今日市场重要新闻要点汇总 — {date}。\n\n{PLATFORM_LINK_CN}\n\n{DISCLAIMER_CN}",
        )
    raise ValueError(f"Unknown video type: {video_type}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file",    required=True, help="Path to .mp4 file")
    ap.add_argument("--type",    required=True, help="Video type key (e.g. sp500_movers)")
    ap.add_argument("--date",    required=True, help="Scan date (YYYY-MM-DD)")
    ap.add_argument("--privacy", default="public",
                    choices=["public", "unlisted", "private"])
    args = ap.parse_args()

    if not Path(args.file).exists():
        print(f"File not found: {args.file}")
        sys.exit(1)

    title, description = make_meta(args.type, args.date)
    # All 10 video types are Shorts now (vertical, <60s) — #Shorts reinforces the
    # Shorts-shelf placement signal YouTube already infers from aspect ratio/duration.
    description = f"{description}\n\n#Shorts"
    date_obj = datetime.date.fromisoformat(args.date)
    thumbnail_path = cover_path_for(args.type, date_obj)
    video_id = upload(args.file, title, description, args.privacy, thumbnail_path=thumbnail_path)
    if video_id:
        print(f"YOUTUBE_URL=https://youtu.be/{video_id}")


if __name__ == "__main__":
    main()
