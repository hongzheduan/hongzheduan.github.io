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
import json
import os
import random
import sys
import time
from pathlib import Path


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


def upload(file_path, title, description, privacy, category_id="22"):
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
            f"Volume Spikes — S&P 500 & Nasdaq-100 — {date}",
            f"Unusual Volume Today — S&P 500 & Nasdaq-100 — {date}",
            f"Big Volume Moves — Large-Cap Stocks — {date}",
            f"Today's Volume Alerts — S&P 500 & Nasdaq-100 — {date}",
        ])
        return (
            title,
            f"Large-cap stocks with unusual trading volume today ({date}), across S&P 500 and Nasdaq-100.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
        )
    if video_type == "extreme_1y":
        title = random.choice([
            f"1-Year Best Performers — S&P 500 & Nasdaq-100 — {date}",
            f"Top 12-Month Gainers — Large-Cap Stocks — {date}",
            f"Best Large-Cap Returns — Trailing 1 Year — {date}",
            f"1-Year Price Leaders — S&P 500 & Nasdaq-100 — {date}",
        ])
        return (
            title,
            f"Top large-cap stocks by trailing 12-month price appreciation, as of {date}.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
        )
    if video_type == "volume_spikes_cn":
        title = random.choice([
            f"今日成交量异动 — S&P 500 & 纳斯达克100 — {date}",
            f"大盘股异常成交量 — {date}",
            f"今日成交量异动股票 — 美股大盘 — {date}",
            f"S&P 500 & 纳斯达克100 成交量异动 — {date}",
        ])
        return (
            title,
            f"S&P 500和纳斯达克100中今日出现异常交易量的大盘股（{date}）。\n\n{PLATFORM_LINK_CN}\n\n{DISCLAIMER_CN}",
        )
    if video_type == "extreme_1y_cn":
        title = random.choice([
            f"过去一年最佳表现股票 — S&P 500 & 纳斯达克100 — {date}",
            f"大盘股年度领涨榜 — {date}",
            f"过去12个月涨幅最大的大盘股 — {date}",
            f"一年期价格领跑者 — S&P 500 & 纳斯达克100 — {date}",
        ])
        return (
            title,
            f"截至{date}，S&P 500和纳斯达克100中过去12个月涨幅最大的大盘股。\n\n{PLATFORM_LINK_CN}\n\n{DISCLAIMER_CN}",
        )
    if video_type == "6m_breakout":
        title = random.choice([
            f"1-Year High Breakouts — S&P 500 & Nasdaq-100 — {date}",
            f"Large-Caps Reclaiming Their 1-Year High — {date}",
            f"New 1-Year High After 20%+ Pullback — {date}",
            f"Breakout Alert: 1-Year Highs Crossed — {date}",
        ])
        return (
            title,
            f"Large-cap stocks from S&P 500 and Nasdaq-100 that crossed their 1-year high for the first time in the past 2 weeks, after a 20%+ real pullback, as of {date}.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
        )
    if video_type == "6m_breakout_cn":
        title = random.choice([
            f"一年新高突破 — S&P 500 & 纳斯达克100 — {date}",
            f"大盘股突破一年高点 — {date}",
            f"20%回调后创一年新高 — {date}",
            f"突破警报：一年高点首次被突破 — {date}",
        ])
        return (
            title,
            f"S&P 500和纳斯达克100中，在经历20%以上真实回调后，过去两周内首次突破一年高点的大盘股（{date}）。\n\n{PLATFORM_LINK_CN}\n\n{DISCLAIMER_CN}",
        )
    if video_type == "1y_vol_peak":
        title = random.choice([
            f"1-Year Volume Record Stocks — S&P 500 & Nasdaq-100 — {date}",
            f"Biggest Annual Trading Days — Large Caps — {date}",
            f"Today's Record Volume Movers — S&P 500 & Nasdaq-100 — {date}",
            f"Stocks Hitting Their 1-Year Volume Peak — {date}",
        ])
        return (
            title,
            f"Large-cap stocks from S&P 500 and Nasdaq-100 recording their biggest single-day volume in the past year, as of {date}.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
        )
    if video_type == "1y_vol_peak_cn":
        title = random.choice([
            f"年度成交量记录股票 — S&P 500 & 纳斯达克100 — {date}",
            f"大盘股年内最大单日成交量 — {date}",
            f"今日年度成交量记录 — S&P 500 & 纳斯达克100 — {date}",
            f"创下一年成交量峰值的大盘股 — {date}",
        ])
        return (
            title,
            f"S&P 500和纳斯达克100中，今日创下过去一年最大单日成交量的大盘股（{date}）。\n\n{PLATFORM_LINK_CN}\n\n{DISCLAIMER_CN}",
        )
    if video_type == "index_spotlight":
        title = random.choice([
            f"Index Spotlight — New S&P 500 & Nasdaq-100 Member — {date}",
            f"How Is This New Index Member Performing? — {date}",
            f"New to the S&P 500 or Nasdaq-100 — Performance Since Joining — {date}",
            f"Index Addition Watch — S&P 500 & Nasdaq-100 — {date}",
        ])
        return (
            title,
            f"A look at how a recent S&P 500 or Nasdaq-100 addition has performed since joining the index, as of {date}.\n\n{PLATFORM_LINK_EN}\n\n{DISCLAIMER_EN}",
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
    upload(args.file, title, description, args.privacy)


if __name__ == "__main__":
    main()
