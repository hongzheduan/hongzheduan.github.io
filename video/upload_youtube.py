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

def make_meta(video_type, date):
    if video_type == "sp500_movers":
        return (
            f"S&P 500 Top Movers — {date}",
            f"Today's biggest price and volume movers in the S&P 500, as of {date}.\n\n{DISCLAIMER_EN}",
        )
    if video_type == "nasdaq_movers":
        return (
            f"Nasdaq-100 Top Movers — {date}",
            f"Today's biggest price and volume movers in the Nasdaq-100, as of {date}.\n\n{DISCLAIMER_EN}",
        )
    if video_type == "volume_spikes":
        return (
            f"Volume Spikes — S&P 500 & Nasdaq-100 — {date}",
            f"Large-cap stocks with unusual trading volume today ({date}), across S&P 500 and Nasdaq-100.\n\n{DISCLAIMER_EN}",
        )
    if video_type == "extreme_1y":
        return (
            f"1-Year Best Performers — S&P 500 & Nasdaq-100 — {date}",
            f"Top large-cap stocks by trailing 12-month price appreciation, as of {date}.\n\n{DISCLAIMER_EN}",
        )
    if video_type == "volume_spikes_cn":
        return (
            f"今日成交量异动 — S&P 500 & 纳斯达克100 — {date}",
            f"S&P 500和纳斯达克100中今日出现异常交易量的大盘股（{date}）。\n\n{DISCLAIMER_CN}",
        )
    if video_type == "platform_intro":
        return (
            "Introducing Baizora — US Large-Cap Price & Volume Analytics",
            f"A walkthrough of Baizora's five core features for tracking S&P 500 and Nasdaq-100 price and volume data.\n\n{DISCLAIMER_EN}",
        )
    if video_type == "platform_intro_cn":
        return (
            "贝佐拉简介 — 美股大盘价量分析平台",
            f"贝佐拉五大核心功能介绍：追踪S&P 500和纳斯达克100的价格与成交量数据。\n\n{DISCLAIMER_CN}",
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
