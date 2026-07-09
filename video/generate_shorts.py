#!/usr/bin/env python3
"""
Baizora YouTube Shorts Generator
Vertical (1080x1920, 9:16), under 30 seconds — a condensed companion to the long-form
daily videos in generate_video.py, not a replacement. Built one weekday at a time;
Monday (Volume Spikes) first.

Structure (target ~27s total):
  1. Hook   (3s)  — bold headline, matches the thumbnail's Anton/impact style
  2. Data   (17s) — condensed top-5 table, one screen, no scrolling
  3. Ad     (5s)  — Baizora branding + CTA, reserved as the last 5 seconds per spec

Usage:
    py generate_shorts.py --type volume_spikes
"""

import argparse
import datetime
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from generate_video import (
    FPS, NAVY, NAVY_MID, NAVY_LIGHT, ELECTRIC, ELEC_BRIGHT, GOLD, GOLD_LIGHT,
    GREEN, RED, BRIGHT_GREEN, BRIGHT_RED, WHITE, MUTED, DIM, VERY_DIM, BORDER,
    load_font, load_font_cn, tw, th, pct_color, pct_str, encode, DATA_FILE,
    TUESDAY_TF_ROTATION, _tuesday_tf, WEDNESDAY_TF_ROTATION, _wednesday_tf,
    _compute_breakouts, THURSDAY_TF_ROTATION, _thursday_tf, _get_verified_members,
)
from generate_thumbnail import load_headline_font, _bg_volume_bars, _bg_candlesticks, _glow_line

SCRIPT_DIR = Path(__file__).parent
SW, SH = 1080, 1920  # YouTube Shorts: vertical 9:16

# ── Video cover ("封面") selection ──────────────────────────────────────────────────
# Pre-made portrait cover images live in video/covering/<Weekday>_<1-4>.png, one set of
# 4 per weekday video type, rotated by calendar day. Right now only Monday's 4 are real
# designs — Tuesday-Friday are duplicated from Monday's as placeholders until each
# weekday gets its own set (planned over the weekend); no code change needed when that
# happens, just replace the files.
COVERING_DIR = SCRIPT_DIR / "covering"

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


def new_frame_s():
    img = Image.new("RGB", (SW, SH), NAVY)
    return img, ImageDraw.Draw(img)


def centered_s(draw, y, text, font, fill=WHITE):
    w = tw(draw, text, font)
    draw.text(((SW - w) // 2, y), text, font=font, fill=fill)


def hline_s(draw, y, x0=50, x1=None, color=BORDER, width=2):
    draw.line([(x0, y), (x1 if x1 else SW - 50, y)], fill=color, width=width)


def dot_grid_s(draw, spacing=60, color=(20, 35, 65)):
    for gx in range(spacing, SW, spacing):
        for gy in range(spacing, SH, spacing):
            draw.ellipse([gx - 1, gy - 1, gx + 1, gy + 1], fill=color)


def _diamond(draw, cx, cy, r, color):
    """Small drawn diamond bullet — the '◈' glyph the landscape scenes use isn't
    present in the mono/CJK font fallbacks on some machines and renders as a tofu
    box, so this draws it as a shape instead of relying on font glyph coverage."""
    draw.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], outline=color, width=2)


# ── Scene 1: Hook ──────────────────────────────────────────────────────────────────

_BULL_IMG = SCRIPT_DIR / "bull.png"
_HIGHEST_IMG = SCRIPT_DIR / "highest.png"
_BOUNCEBACK_IMG = SCRIPT_DIR / "bounceback.png"
_MEMBERCHANGE_IMG = SCRIPT_DIR / "memberchange_slide1.png"
_IMG_BG_STYLES = {
    "bull": _BULL_IMG, "highest": _HIGHEST_IMG, "bounceback": _BOUNCEBACK_IMG,
    "memberchange": _MEMBERCHANGE_IMG,
}
_LOGO_IMG = SCRIPT_DIR.parent / "assets" / "baize_favicon_v2.png"


def _load_logo_cutout(path, black_thresh=12, ramp=30):
    """baize_favicon_v2.png is a flat black rectangle (opaque, not transparent) with
    the Baizora icon on it — this derives an alpha mask from brightness so it
    composites onto the navy background like a real cutout instead of pasting a
    visible black box."""
    im = Image.open(str(path)).convert("RGBA")
    arr = np.array(im).astype(np.float32)
    lum = arr[..., :3].max(axis=-1)
    alpha_mask = np.clip((lum - black_thresh) / ramp, 0, 1) * 255
    arr[..., 3] = np.minimum(arr[..., 3], alpha_mask)
    return Image.fromarray(arr.astype("uint8"), "RGBA")


def _paste_cover(img, source_path, region, valign="center"):
    """Scales+crops an image to fully cover a region (like CSS object-fit: cover),
    cropping evenly from whichever axis overflows rather than letterboxing.
    valign controls which part of the vertical overflow gets cropped away: "center"
    (default), "top" (keep the top, crop from the bottom — for images whose focal
    point, like an arrow tip, sits near the top), or "bottom" (keep the bottom)."""
    x0, y0, x1, y1 = region
    rw, rh = x1 - x0, y1 - y0
    src = Image.open(str(source_path)).convert("RGB")
    iw, ih = src.size
    scale = max(rw / iw, rh / ih)
    nw, nh = round(iw * scale), round(ih * scale)
    src = src.resize((nw, nh), Image.LANCZOS)
    cx = (nw - rw) // 2
    if valign == "top":
        cy = 0
    elif valign == "bottom":
        cy = nh - rh
    else:
        cy = (nh - rh) // 2
    src = src.crop((cx, cy, cx + rw, cy + rh))
    img.paste(src, (x0, y0))


def scene_hook_generic(scan_date, lang, lines_en, lines_cn, sub_en, sub_cn, bg_style="bars"):
    """Generic hook/title card — Monday uses a bar-chart texture (bg_style='bars'),
    Tuesday a bull-market illustration (bg_style='bull'), Wednesday a candlestick
    chart breaking through a new-high resistance line (bg_style='highest'), matching
    the same visual language already established per-category in generate_thumbnail.py."""
    img, draw = new_frame_s()

    # Bottom two-thirds: same chart texture language as the thumbnails, so the hook
    # doesn't read as a bare title card floating in empty space.
    img_path = _IMG_BG_STYLES.get(bg_style)
    if img_path and img_path.exists():
        # bounceback.png's arrow tip sits near the top of the source image, which a
        # center crop would slice off — keep the top intact and crop the bottom instead.
        valign = "top" if bg_style == "bounceback" else "center"
        _paste_cover(img, img_path, (0, 1380, SW, SH - 40), valign=valign)
        draw = ImageDraw.Draw(img)
    elif bg_style == "candles":
        _bg_candlesticks(img, draw, region=(0, 1380, SW, SH - 40), n=26, seed=17, recovery=True)
    else:
        _bg_volume_bars(img, draw, (20, 90, 55), region=(0, 1380, SW, SH - 40), n=28, seed=13)
    dot_grid_s(draw)

    eyebrow = "DAILY MARKET RECAP" if lang == "en" else "每日市场回顾"
    f_eyebrow = load_font(26, mono=True) if lang == "en" else load_font_cn(26)
    ew = tw(draw, eyebrow, f_eyebrow)
    badge_w = ew + 90
    ex = (SW - badge_w) // 2 + 46
    ey = 300
    draw.rectangle([ex - 66, ey - 16, ex + ew + 24, ey + 44], fill=NAVY_LIGHT, outline=ELECTRIC, width=2)
    _diamond(draw, ex - 38, ey + 14, 12, ELEC_BRIGHT)
    draw.text((ex, ey), eyebrow, font=f_eyebrow, fill=ELEC_BRIGHT)

    f_head = load_headline_font(104) if lang == "en" else load_font_cn(80, bold=True)
    lines = lines_en if lang == "en" else lines_cn
    y = 520
    for line in lines:
        centered_s(draw, y, line, f_head, GOLD_LIGHT)
        y += th(draw, line, f_head) + 20

    sub = sub_en if lang == "en" else sub_cn
    centered_s(draw, y + 40, sub, load_font(34) if lang == "en" else load_font_cn(32), MUTED)
    centered_s(draw, y + 96, scan_date, load_font(24, mono=True), DIM)
    return img


# ── Scene 2': one stock at a time — name, number, and its 1Y trend together ────────

_CANDLES_CACHE = None


def _load_candles():
    """data/candles.json: per-ticker daily OHLCV (~252 bars, matches the real
    dashboard's 1Y candlestick view) — loaded once and reused across all 3 cards."""
    global _CANDLES_CACHE
    if _CANDLES_CACHE is None:
        with open(SCRIPT_DIR.parent / "data" / "candles.json") as f:
            _CANDLES_CACHE = json.load(f)
    return _CANDLES_CACHE


def _blend_over_navy(fg, alpha=0.35):
    return tuple(round(bg * (1 - alpha) + c * alpha) for bg, c in zip(NAVY, fg))


_VOL_GREEN = _blend_over_navy(GREEN)
_VOL_RED = _blend_over_navy(RED)


def _draw_candles_with_volume(img, draw, ticker, region):
    """Real 1-year daily OHLCV candlesticks + a volume panel underneath (price ~78%
    / volume ~22%, volume bars color-matched to candle direction at reduced opacity)
    — same visual language as the real dashboard's candlestick chart, replacing the
    close-only sparkline so the card shows actual price action, not a smoothed line."""
    bars = _load_candles().get("data", {}).get(ticker) or []
    if len(bars) < 2:
        return
    x0, y0, x1, y1 = region
    gap = 4
    price_h = round((y1 - y0) * 0.78)
    price_y0, price_y1 = y0, y0 + price_h
    vol_y0, vol_y1 = price_y1 + gap, y1

    highs = [b[1] for b in bars]
    lows = [b[2] for b in bars]
    vols = [b[4] for b in bars]
    mn_v, mx_v = min(lows), max(highs)
    if mx_v <= mn_v:
        return
    max_vol = max(vols) or 1

    n = len(bars)
    slot_w = (x1 - x0) / n
    body_w = max(1.0, slot_w * 0.6)

    def py(v):
        return price_y1 - (v - mn_v) / (mx_v - mn_v) * (price_y1 - price_y0)

    for i, (o, h, l, c, v) in enumerate(bars):
        cx = x0 + (i + 0.5) * slot_w
        up = c >= o
        color = BRIGHT_GREEN if up else BRIGHT_RED
        draw.line([(cx, py(h)), (cx, py(l))], fill=color, width=1)
        top, bot = py(max(o, c)), py(min(o, c))
        if bot - top < 1:
            bot = top + 1
        draw.rectangle([cx - body_w / 2, top, cx + body_w / 2, bot], fill=color)

        vh = (v / max_vol) * (vol_y1 - vol_y0)
        vol_color = _VOL_GREEN if up else _VOL_RED
        draw.rectangle([cx - body_w / 2, vol_y1 - vh, cx + body_w / 2, vol_y1], fill=vol_color)


def scene_stock_card(row, rank, lang, value_key, sub_en, sub_cn, gold_leader=True):
    """Hero card for a single ticker — replaces the old shared 5-row table so the
    Short shows one stock at a time (name + the narrated metric + its 1-year
    candlestick trend, all together) instead of a static list everyone's narrated
    line points at identically. sub_en/sub_cn label whichever metric value_key is."""
    img, draw = new_frame_s()
    dot_grid_s(draw)

    rank_col = GOLD_LIGHT if (gold_leader and rank == 1) else MUTED
    centered_s(draw, 80, f"#{rank}", load_font(32, mono=True, bold=True), rank_col)

    ticker = row.get("Ticker", "")
    f_tkr = load_headline_font(90) if lang == "en" else load_font_cn(72, bold=True)
    centered_s(draw, 145, ticker, f_tkr, WHITE)

    name = (row.get("CompanyName") or "")
    if len(name) > 30:
        name = name[:27] + "..."
    centered_s(draw, 270, name, load_font(28) if lang == "en" else load_font_cn(26), MUTED)

    v = row.get(value_key)
    color = BRIGHT_GREEN if (v or 0) >= 0 else BRIGHT_RED
    # Trend region height cut to 3/4 of the original (350 -> SH-560) span, anchored
    # at the same top so the freed space collapses upward instead of leaving the
    # chart floating in the middle of a now-oversized box.
    full_h = (SH - 560) - 350
    region = (110, 350, SW - 110, 350 + round(full_h * 0.75))
    _draw_candles_with_volume(img, draw, ticker, region)

    f_pct = load_headline_font(130)
    pct_y = region[3] + 40
    pct_text = pct_str(v)
    centered_s(draw, pct_y, pct_text, f_pct, color)
    # Anton's glyph bbox top isn't flush with 0 (unlike most fonts) — use the actual
    # bbox bottom, not draw-y + th(), or the label below collides with the glyph tail.
    pct_bottom = pct_y + draw.textbbox((0, 0), pct_text, font=f_pct)[3]
    sub = sub_en if lang == "en" else sub_cn
    centered_s(draw, pct_bottom + 30, sub, load_font(24, mono=True) if lang == "en" else load_font_cn(22), DIM)
    return img


# ── Scene 2b': Friday — 1-year trend with a join-date marker ───────────────────────

def scene_member_spotlight_short(member, scan_date, lang="en"):
    """Portrait version of generate_video.py's scene_spotlight_sparkline — pre-join
    segment muted gray, post-join segment colored green/red, with a gold join marker,
    so the "index inclusion changed the trajectory" story reads in one glance."""
    img, draw = new_frame_s()
    dot_grid_s(draw)
    row = member["row"]
    ticker = member["ticker"]
    perf = member["perf_since_join"]
    spark_idx = member["spark_idx"]
    color = BRIGHT_GREEN if perf >= 0 else BRIGHT_RED

    title = f"{ticker} — NEW MEMBER" if lang == "en" else f"{ticker} — 新晋成分股"
    f_title = load_headline_font(56) if lang == "en" else load_font_cn(46, bold=True)
    centered_s(draw, 100, title, f_title, GOLD_LIGHT)

    name = (row.get("CompanyName") or "")
    idx_label = member["index_name"] if lang == "en" else ("纳斯达克100" if "Nasdaq" in member["index_name"] else "标普500")
    centered_s(draw, 210, f"{name}  ·  {idx_label}", load_font(24) if lang == "en" else load_font_cn(22), MUTED)

    spark = row.get("Spark1Y") or []
    region = (110, 320, SW - 110, SH - 480)
    if len(spark) >= 2:
        mn_v, mx_v = min(spark), max(spark)
        if mx_v > mn_v:
            n = len(spark)
            x0, y0, x1, y1 = region
            pad = 0.08
            def pt(i, v):
                px = x0 + i / (n - 1) * (x1 - x0)
                py = y1 - ((v - mn_v) / (mx_v - mn_v)) * (y1 - y0) * (1 - 2 * pad) - (y1 - y0) * pad
                return (px, py)
            pts = [pt(i, v) for i, v in enumerate(spark)]
            si = max(0, min(spark_idx, n - 1))
            pre_pts = pts[:si + 1]
            post_pts = pts[si:]
            if len(pre_pts) >= 2:
                draw.line(pre_pts, fill=VERY_DIM, width=4)
            if len(post_pts) >= 2:
                _glow_line(img, draw, post_pts, color, width=8, glow_radius=20)
            jx, jy = pts[si]
            draw.line([(jx, y0), (jx, y1)], fill=GOLD, width=2)
            r = 14
            draw.polygon([(jx, jy - r), (jx - r, jy + r), (jx + r, jy + r)], fill=GOLD)

    f_pct = load_headline_font(120)
    pct_y = SH - 440
    pct_text = pct_str(perf)
    centered_s(draw, pct_y, pct_text, f_pct, color)
    pct_bottom = pct_y + draw.textbbox((0, 0), pct_text, font=f_pct)[3]
    footer = "SINCE JOINING THE INDEX" if lang == "en" else "加入指数以来"
    centered_s(draw, pct_bottom + 30, footer, load_font(26, mono=True) if lang == "en" else load_font_cn(24), DIM)
    return img




# ── Scene 3: Baizora ad / outro (final 5 seconds) ─────────────────────────────────

def scene_ad_short(scan_date, lang="en"):
    img, draw = new_frame_s()
    dot_grid_s(draw)

    # Real Baizora icon (not a procedural chart texture) above the wordmark, so
    # every weekday's Short ends on the same recognizable brand mark. The favicon
    # is icon-only (no baked-in "BAIZORA" text), cut out from its flat black
    # background so it floats on the navy dot-grid like everything else.
    y = 180
    if _LOGO_IMG.exists():
        logo = _load_logo_cutout(_LOGO_IMG)
        lw, lh = logo.size
        target_w = 260
        scale = target_w / lw
        nw, nh = round(lw * scale), round(lh * scale)
        logo = logo.resize((nw, nh), Image.LANCZOS)
        img.paste(logo, ((SW - nw) // 2, y), logo)
        y += nh + 30

    f_big = load_font(120, serif=True)
    baiz_w = tw(draw, "Baiz", f_big)
    ora_w = tw(draw, "ora", f_big)
    lx = (SW - baiz_w - ora_w) // 2
    draw.text((lx, y), "Baiz", font=f_big, fill=WHITE)
    draw.text((lx + baiz_w, y), "ora", font=f_big, fill=ELECTRIC)
    y += 165

    tagline = "US Large-Cap Price & Volume Analytics" if lang == "en" else "美股大盘价格与成交量分析平台"
    centered_s(draw, y, tagline, load_font(30) if lang == "en" else load_font_cn(28), MUTED)
    y += 75
    hline_s(draw, y, x0=240, x1=SW - 240)

    cta = "Start your free 7-day trial" if lang == "en" else "开始七天免费试用"
    y += 50
    centered_s(draw, y, cta, load_font(38, bold=True) if lang == "en" else load_font_cn(36, bold=True), GOLD_LIGHT)
    y += 70
    centered_s(draw, y, "baizora.com", load_font(42), ELECTRIC)

    follow_y = y + 110
    hline_s(draw, follow_y - 40, x0=240, x1=SW - 240)
    follow = "New video every day — follow along" if lang == "en" else "每日更新 · 欢迎关注"
    centered_s(draw, follow_y, follow, load_font(28, bold=True) if lang == "en" else load_font_cn(26, bold=True), WHITE)

    disclaimer = ("For informational purposes only. Not financial advice."
                   if lang == "en" else "仅供参考，不构成投资建议。")
    centered_s(draw, SH - 260, disclaimer, load_font(18) if lang == "en" else load_font_cn(18), VERY_DIM)
    centered_s(draw, SH - 220, f"Daily Scan: {scan_date}" if lang == "en" else f"每日扫描：{scan_date}",
               load_font(18, mono=True) if lang == "en" else load_font_cn(18), DIM)
    return img


# ── Ad reel (replaces the old static ad card as the main CTA scene) ────────────────
# Shared across every weekday's Short (same reel, not per-weekday): a real still of
# the ranked dashboard, a real screen recording, then a real still of a ticker's
# detail modal — one continuous pitch narrated across all three. scene_ad_short
# still runs immediately after, unchanged, as a brief silent brand card — "end on
# the previous slide" per explicit instruction, rather than cutting straight from
# real footage to black.
#
# CN has its own dashboard still and screen recording (advertise_cn_0.png,
# advertise_1_cn.mp4); no CN-specific ticker-detail still exists yet, so CN
# reuses the EN advertise_2.png for that third slot until one is made.

_AD_ASSETS_EN = [
    ("image", SCRIPT_DIR / "advertise_0.png", 1.3),
    ("video", SCRIPT_DIR / "advertise_1.mp4", None),
    ("image", SCRIPT_DIR / "advertise_2.png", 1.3),
]
_AD_ASSETS_CN = [
    ("image", SCRIPT_DIR / "advertise_cn_0.png", 1.3),
    ("video", SCRIPT_DIR / "advertise_1_cn.mp4", None),
    ("image", SCRIPT_DIR / "advertise_2.png", 1.3),
]

# "Contain" box every ad asset is scaled into (aspect preserved, no cropping) so the
# image stills and the video clip all read as one consistent inset frame despite
# having different native aspect ratios.
_AD_BOX_W, _AD_BOX_H = 940, 1320
_AD_BOX_Y0 = 230

# Leads with "Baizora" so viewers know who's advertising from the first word.
# One flowing sentence (not disconnected fragments) — measured at the Shorts TTS
# rate (+40%) to land safely inside the ad footage (~11.9s EN reel / ~11.1s CN
# fallback clip; narration starts ~0.55s in — see generate_narration()'s
# pref_start convention), with room to spare rather than cutting it close. Covers
# the full pitch: every S&P 500 and Nasdaq-100 stock in one table, one day to one
# year, volume spikes, top performers, daily membership-change flags, and key
# events marked on the trend line. No "baizora dot com" here on purpose — the CTA
# is said once, at the very end (_AD_PITCH2_EN/_CN), not repeated mid-reel.
_AD_PITCH_EN = ("Baizora brings every S&P 500 and Nasdaq-100 stock into one table, "
                "one day to one year — volume spikes, top performers, membership "
                "changes, key events marked on the trend.")
_AD_PITCH_CN = ("贝佐拉一张表整合标普500和纳斯达克100全部股票，单日到一年——"
                 "成交量异动、领涨股、成分股变动，关键事件标注趋势线。")

# Second, shorter beat for the last ~3-4s of the ad reel (the advertise_2.png still),
# once the main pitch above has already finished — pitches the per-stock detail page
# instead of the platform-wide table, and is where the baizora.com CTA is actually
# said (only once, at the end). Kept terse: only ~4s of runway is left before the
# reel hands off to the silent outro card.
_AD_PITCH2_EN = "Full stock detail in thirty seconds — baizora dot com."
_AD_PITCH2_CN = "半分钟看懂个股全部信息。baizora点com。"


def _contain_dims(sw, sh, box_w, box_h):
    scale = min(box_w / sw, box_h / sh)
    nw, nh = round(sw * scale), round(sh * scale)
    return nw - nw % 2, nh - nh % 2


def _frame_ad_asset(asset_img, lang, heading):
    """Composites one ad-reel visual (already-scaled RGB image, still or extracted
    video frame) onto the shared navy portrait template — heading, bordered inset,
    'baizora.com' caption below — so all three parts of the reel read as one
    continuous sequence despite differing source aspect ratios."""
    img, draw = new_frame_s()
    dot_grid_s(draw)
    f_head = load_headline_font(50) if lang == "en" else load_font_cn(40, bold=True)
    centered_s(draw, 110, heading, f_head, GOLD_LIGHT)
    vw, vh = asset_img.size
    x = (SW - vw) // 2
    draw.rectangle([x - 8, _AD_BOX_Y0 - 8, x + vw + 8, _AD_BOX_Y0 + vh + 8], outline=ELECTRIC, width=4)
    img.paste(asset_img, (x, _AD_BOX_Y0))
    centered_s(draw, _AD_BOX_Y0 + vh + 60, "baizora.com", load_font(40), ELECTRIC)
    return img


def build_ad_reel(lang="en"):
    """Returns a list of frames-list entries (image entries: composed Image + fixed
    hold_sec; the video entry: list of composed frames + its exact decoded duration)
    for the shared ad reel. Meant to be the same three-part sequence for every
    weekday video, spliced in right before the final scene_ad_short outro card."""
    from generate_video import load_video_clip_frames

    heading = "SEE BAIZORA LIVE" if lang == "en" else "看看贝佐拉的实时看板"
    assets = _AD_ASSETS_CN if lang == "cn" else _AD_ASSETS_EN

    entries = []
    for kind, path, still_hold in assets:
        if kind == "image":
            src = Image.open(str(path)).convert("RGB")
            nw, nh = _contain_dims(*src.size, _AD_BOX_W, _AD_BOX_H)
            src = src.resize((nw, nh), Image.LANCZOS)
            entries.append((_frame_ad_asset(src, lang, heading), still_hold, None, None))
        else:
            raw_frames, vw, vh, dur = load_video_clip_frames(
                path, fit_w=_AD_BOX_W, max_h=_AD_BOX_H)
            composed = [_frame_ad_asset(rf, lang, heading) for rf in raw_frames]
            entries.append((composed, dur, None, None))
    return entries


_HOOK_NARRATION_EN = [
    "Today's stock market is showing some major volume spikes.",
    "The stock market just saw some serious volume spikes today.",
    "Big volume can mean big news — here's what's moving today.",
]

_HOOK_NARRATION_CN = [
    "今天美股市场出现了几只成交量异动股票。",
    "美股今天出现了几只成交量大幅异动的股票。",
]


def _narrate_ticker_lines(rows, n=5):
    """One short narration line per ticker (not one line for the whole scene) — so
    the table's on-screen time is covered by speech throughout, not just its first
    couple of seconds. Phrasing (leads the pack / follows / rounding out) is meant
    to read as one connected sentence-by-sentence script, not disconnected fragments."""
    lines = []
    for i, row in enumerate(rows[:n]):
        ticker = row.get("Ticker", "")
        v = abs(row.get("VolumeChange1D") or 0)
        if i == 0:
            lines.append(f"{ticker} leads the pack, up {v:.0f} percent.")
        elif i == 1:
            lines.append(f"{ticker} follows, up {v:.0f} percent.")
        elif i == n - 1:
            lines.append(f"And rounding things out, {ticker}, also up {v:.0f} percent.")
        else:
            lines.append(f"{ticker} is up {v:.0f} percent.")
    return lines


def _narrate_ticker_lines_cn(rows, n=5):
    lines = []
    for i, row in enumerate(rows[:n]):
        ticker = row.get("Ticker", "")
        v = abs(row.get("VolumeChange1D") or 0)
        if i == 0:
            lines.append(f"{ticker}领涨，上涨{v:.0f}%。")
        elif i == 1:
            lines.append(f"{ticker}紧随其后，上涨{v:.0f}%。")
        elif i == n - 1:
            lines.append(f"最后是{ticker}，同样上涨{v:.0f}%。")
        else:
            lines.append(f"{ticker}上涨{v:.0f}%。")
    return lines


_HOOK_NARRATION_BEST_EN = [
    "Best performers over the past {window}.",
    "These stocks led the market over the past {window}.",
]

_HOOK_NARRATION_BEST_CN = [
    "过去{window}表现最佳的股票。",
]


def _narrate_ticker_lines_best(rows, key, n=5):
    """Shorter phrasing than Monday's volume-spike lines on purpose — the best-
    performer % figures can run into the hundreds (a 6-month rotation window can show
    600%+ moves), and repeating a longer template per ticker overran the 30s budget."""
    lines = []
    for i, row in enumerate(rows[:n]):
        ticker = row.get("Ticker", "")
        v = abs(row.get(key) or 0)
        if i == 0:
            lines.append(f"{ticker} leads, up {v:.0f} percent.")
        elif i == 1:
            lines.append(f"{ticker} follows, up {v:.0f} percent.")
        elif i == n - 1:
            lines.append(f"And finally {ticker}, up {v:.0f} percent.")
        else:
            lines.append(f"{ticker} is up {v:.0f} percent.")
    return lines


def _narrate_ticker_lines_best_cn(rows, key, n=5):
    lines = []
    for i, row in enumerate(rows[:n]):
        ticker = row.get("Ticker", "")
        v = abs(row.get(key) or 0)
        if i == 0:
            lines.append(f"{ticker}领涨，上涨{v:.0f}%。")
        elif i == 1:
            lines.append(f"{ticker}紧随其后，上涨{v:.0f}%。")
        elif i == n - 1:
            lines.append(f"最后是{ticker}，上涨{v:.0f}%。")
        else:
            lines.append(f"{ticker}上涨{v:.0f}%。")
    return lines


_HOOK_NARRATION_PULLBACK_EN = [
    "These stocks pulled back at least {min_drawdown} percent, then broke out to a new {window} high.",
    "A real pullback, then a new {window} high — here's today's setup.",
]

_HOOK_NARRATION_PULLBACK_CN = [
    "这些股票回调至少{min_drawdown}%，随后突破{window}新高。",
    "先经历真实回调，再创下{window}新高，这就是今天的主角。",
]


def _narrate_ticker_lines_pullback(rows, label, n=3):
    """Leads with the pullback percentage (not today's move) — that's the actual
    headline stat for this category (a real 20%+ decline before reclaiming a new
    high), which earlier versions of this Short never stated out loud. Also names
    the timeframe explicitly (e.g. "six-month high") since it rotates weekly and
    was previously left implicit. Narrating only 3 (not 5) tickers, since stating
    both the pullback % and the timeframe per line makes each one longer than
    Monday/Tuesday's plain "up N percent" cadence."""
    n = min(n, len(rows))
    lines = []
    for i, row in enumerate(rows[:n]):
        ticker = row.get("Ticker", "")
        dd = abs(row.get("_drawdown") or 0)
        if n == 1:
            lines.append(f"There's only one today — {ticker}, down {dd:.0f} percent at its low, now at a new {label} high.")
        elif i == 0:
            lines.append(f"{ticker} pulled back {dd:.0f} percent, then broke out to a new {label} high.")
        elif i == n - 1:
            lines.append(f"And {ticker}, down {dd:.0f} percent at its low, is also back at a new {label} high.")
        else:
            lines.append(f"{ticker} fell {dd:.0f} percent, then recovered to a new {label} high.")
    return lines


def _narrate_ticker_lines_pullback_cn(rows, label_cn, n=3):
    n = min(n, len(rows))
    lines = []
    for i, row in enumerate(rows[:n]):
        ticker = row.get("Ticker", "")
        dd = abs(row.get("_drawdown") or 0)
        if n == 1:
            lines.append(f"今天只有一只——{ticker}，曾回调{dd:.0f}%，如今突破{label_cn}新高。")
        elif i == 0:
            lines.append(f"{ticker}曾回调{dd:.0f}%，如今突破{label_cn}新高。")
        elif i == n - 1:
            lines.append(f"最后是{ticker}，曾回调{dd:.0f}%，同样创下{label_cn}新高。")
        else:
            lines.append(f"{ticker}曾下跌{dd:.0f}%，如今创下{label_cn}新高。")
    return lines


_HOOK_NARRATION_VOL_PEAK_EN = [
    "Here's today's {window} volume record.",
    "A record volume day often means something big is happening — today's {window} record.",
]

_HOOK_NARRATION_VOL_PEAK_CN = [
    "这些是创{window}成交量记录的股票。",
    "这些股票创下了{window}成交量记录，值得关注。",
]


def _narrate_ticker_lines_vol_peak(rows, key, n=5):
    """Ranked by the volume-record day's % volume change. Unlike Monday/Tuesday/
    Wednesday's always-full pools, this category (today IS a stock's biggest volume
    day in the window) is genuinely rare — most days turn up only 1-3 qualifying
    stocks, sometimes just 1. The "last" index must be based on the actual row count
    (not a fixed n=5), or the closing flourish line never triggers on sparse days."""
    n = min(n, len(rows))
    rows = rows[:n]
    lines = []
    for i, row in enumerate(rows):
        ticker = row.get("Ticker", "")
        v = abs(row.get(key) or 0)
        if n == 1:
            lines.append(f"There's only one today — {ticker}, volume up {v:.0f} percent.")
        elif i == 0:
            lines.append(f"{ticker} leads, volume up {v:.0f} percent.")
        elif i == n - 1:
            lines.append(f"And finally {ticker}, up {v:.0f} percent.")
        else:
            lines.append(f"{ticker} is up {v:.0f} percent.")
    return lines


def _narrate_ticker_lines_vol_peak_cn(rows, key, n=5):
    n = min(n, len(rows))
    rows = rows[:n]
    lines = []
    for i, row in enumerate(rows):
        ticker = row.get("Ticker", "")
        v = abs(row.get(key) or 0)
        if n == 1:
            lines.append(f"今天只有一只——{ticker}，成交量放大{v:.0f}%。")
        elif i == 0:
            lines.append(f"{ticker}领涨，成交量放大{v:.0f}%。")
        elif i == n - 1:
            lines.append(f"最后是{ticker}，放大{v:.0f}%。")
        else:
            lines.append(f"{ticker}放大{v:.0f}%。")
    return lines


SHORTS_TTS_RATE = "+40%"  # fast-talking pace, matches how Shorts are typically cut
SHORTS_TTS_VOICE_CN = "zh-CN-YunxiNeural"  # same CN voice used throughout generate_video.py


def _embed_cover(output, cover_path, ffmpeg_path=None):
    """Muxes the selected cover image in as an attached picture (same trick as MP3
    album art) so file browsers / players show it as the video's poster frame —
    the actual YouTube-thumbnail upload is a separate step in upload_youtube.py,
    this just makes the chosen cover visible on the file itself."""
    import subprocess
    from generate_video import get_ffmpeg
    ffmpeg = ffmpeg_path or get_ffmpeg()
    tmp_output = str(output) + ".cover_tmp.mp4"
    cmd = [
        ffmpeg, "-y", "-i", str(output), "-i", str(cover_path),
        "-map", "0", "-map", "1",
        "-c", "copy", "-c:v:1", "mjpeg", "-disposition:v:1", "attached_pic",
        tmp_output,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"  [cover] WARNING: failed to embed cover art: {res.stderr[-500:]}")
        return
    Path(tmp_output).replace(output)
    print(f"  [cover] embedded {Path(cover_path).name} as poster frame")


def build_volume_spikes_short(data, output, lang="en"):
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    rows = sorted(data["data"], key=lambda r: r.get("VolumeChange1D") or -9999, reverse=True)[:3]

    # Durations below = actually-measured edge-tts speech time at SHORTS_TTS_RATE (EN)
    # or SHORTS_TTS_VOICE_CN (CN) for this exact wording pattern, +~0.15s buffer each —
    # not estimates. Guessed budgets consistently ran short (e.g. the EN leader line
    # "TICKER leads, up N percent" alone measured 3.02s against a guessed 2.05s slot),
    # which is what caused dropped/cut-off narration. If the narration templates in
    # _narrate_ticker_lines(_cn) change, re-measure rather than re-guess.
    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_cn(rows, n=3)
        ticker_durs = [2.8, 3.1, 3.5]
        hook_dur, hook_text = 3.15, random.choice(_HOOK_NARRATION_CN)
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines(rows, n=3)
        ticker_durs = [3.2, 2.7, 3.8]
        hook_dur, hook_text = 3.1, random.choice(_HOOK_NARRATION_EN)
        tts_voice = "en-US-ChristopherNeural"

    frames = [
        (scene_hook_generic(date, lang, ["BIGGEST VOLUME", "SPIKES TODAY"], ["今日成交量", "暴涨股票"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="bars"),
         hook_dur, None, hook_text),
    ]
    # One stock at a time (name + volume-change number + 1Y trend together) — replaces
    # the old shared 5-row table so each narrated ticker gets its own hero card instead
    # of all narration pointing at one static list.
    for i, (row, dur, line) in enumerate(zip(rows, ticker_durs, ticker_lines)):
        card = scene_stock_card(row, i + 1, lang, "VolumeChange1D",
                                 "VS 21-DAY AVERAGE VOLUME", "对比21日平均成交量")
        frames.append((card, dur, None, line))

    # Ad reel replaces the old dashboard-screenshot + static-card CTA: real footage
    # (advertise_0.png -> advertise_1.mp4 -> advertise_2.png) with the condensed pitch
    # narrated entirely across it (see _AD_PITCH_EN/_CN — measured to finish well
    # before the reel ends). Ends on scene_ad_short (the previous static brand card)
    # unchanged, silent, as the final slide — "end on the previous slide" per explicit
    # instruction.
    ad_entries = build_ad_reel(lang=lang)
    ad_pitch = _AD_PITCH_CN if lang == "cn" else _AD_PITCH_EN
    ad_pitch2 = _AD_PITCH2_CN if lang == "cn" else _AD_PITCH2_EN
    first = ad_entries[0]
    if len(ad_entries) > 1:
        # 3-part reel (both languages): main pitch on the first still, the short
        # second beat on the last still (advertise_2.png) — it only has ~3-4s of
        # runway once the main pitch finishes, so it has to be terse.
        ad_entries[0] = (first[0], first[1], first[2], ad_pitch)
        last = ad_entries[-1]
        ad_entries[-1] = (last[0], last[1], last[2], ad_pitch2)
    else:
        # Fallback if a language's reel is ever a single clip with nowhere else to
        # attach a second narration slot — both beats spoken back-to-back as one clip.
        ad_entries[0] = (first[0], first[1], first[2], ad_pitch + " " + ad_pitch2)
    frames += ad_entries
    frames.append((scene_ad_short(date, lang=lang), 2.5, None, None))
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("volume_spikes" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


def build_best_performer_short(data, output, lang="en"):
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    tf = _tuesday_tf(date)
    key = tf["key"]
    rows = sorted(data["data"], key=lambda r: r.get(key) or -9999, reverse=True)[:3]

    window_en, window_cn = tf["window_en"], tf["window_cn"]
    sub_en, sub_cn = f"OVER THE PAST {window_en.upper()}", f"过去{window_cn}表现"

    # Durations = actually-measured edge-tts speech time (same measure-don't-guess
    # approach as Monday). Ticker phrasing here is intentionally shorter than Monday's
    # ("leads" not "leads the pack") because best-performer % figures for longer
    # rotation windows (6-Month, 1-Year) can run into the hundreds of percent, and the
    # longer template overran the 30s budget when tested against real data.
    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_best_cn(rows, key, n=3)
        ticker_durs = [3.05, 2.60, 3.40]
        hook_dur = 2.55
        hook_text = random.choice(_HOOK_NARRATION_BEST_CN).format(window=window_cn)
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines_best(rows, key, n=3)
        ticker_durs = [3.40, 2.65, 3.45]
        hook_dur = 2.60
        hook_text = random.choice(_HOOK_NARRATION_BEST_EN).format(window=window_en)
        tts_voice = "en-US-ChristopherNeural"

    frames = [
        (scene_hook_generic(date, lang, [f"TOP {tf['label_en'].upper()}", "WINNERS"],
                            [tf["label_cn"], "最佳表现股票"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="bull"),
         hook_dur, None, hook_text),
    ]
    # One stock at a time (name + the narrated % + its 1Y candlestick trend), same
    # as Monday — replaces the old shared 5-row table.
    for i, (row, dur, line) in enumerate(zip(rows, ticker_durs, ticker_lines)):
        card = scene_stock_card(row, i + 1, lang, key, sub_en, sub_cn)
        frames.append((card, dur, None, line))

    # Ad reel, same as Monday: real footage (advertise_0/1/2) with the platform pitch,
    # then a short second beat with the CTA, then the unchanged silent outro card.
    ad_entries = build_ad_reel(lang=lang)
    ad_pitch = _AD_PITCH_CN if lang == "cn" else _AD_PITCH_EN
    ad_pitch2 = _AD_PITCH2_CN if lang == "cn" else _AD_PITCH2_EN
    first = ad_entries[0]
    ad_entries[0] = (first[0], first[1], first[2], ad_pitch)
    last = ad_entries[-1]
    ad_entries[-1] = (last[0], last[1], last[2], ad_pitch2)
    frames += ad_entries
    frames.append((scene_ad_short(date, lang=lang), 2.5, None, None))
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("best_performer" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


def build_6m_breakout_short(data, output, lang="en"):
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    tf = _wednesday_tf(date)
    breakouts = _compute_breakouts(data["data"], tf)
    # Ranked by pullback depth (not today's move) — the story is "how far did it fall
    # before reclaiming a new high", which is the stat that was missing from narration.
    breakouts.sort(key=lambda x: x.get("_drawdown") or 0, reverse=True)
    rows = breakouts[:3]

    if not rows:
        print(f"No {tf['label_en']} breakout stocks today, skipping Short.")
        return

    # Cards display the pullback magnitude (as a negative %, in red) rather than
    # today's price move — that's the headline stat for this category.
    for r in rows:
        r["_drawdown_display"] = -abs(r.get("_drawdown") or 0)

    window_en, window_cn = tf["window_en"], tf["window_cn"]
    label_en, label_cn = tf["label_en"], tf["label_cn"]
    sub_en = f"{tf['min_drawdown']}%+ DECLINE, NOW AT A NEW HIGH"
    sub_cn = f"跌超{tf['min_drawdown']}%，如今创新高"

    # Narrating only up to 3 tickers — mentioning the pullback % AND the rotating
    # timeframe (it cycles 1M/3M/6M/9M/1Y weekly, so it must be stated, not implied)
    # makes each line longer, so the full 5-ticker cadence used on Monday/Tuesday
    # doesn't fit the 30s budget here. Durations are per-position, not a flat
    # per-day array — row count varies 1-3 (some weeks/windows turn up only 1-2
    # real pullback-then-breakout stocks), same row-count-awareness as Thursday's
    # volume-record category. Budgets are actually-measured edge-tts speech time
    # at SHORTS_TTS_RATE (see measure_wed4.py in scratch for the n=3 case; the n=1
    # "There's only one today" line was measured directly: EN 4.97s, CN 4.44s), +buffer.
    n = len(rows)
    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_pullback_cn(rows, label_cn)
        def _dur(i):
            if n == 1:
                return 4.7
            if i == 0:
                return 3.83
            if i == n - 1:
                return 4.16
            return 3.97
        hook_dur = 4.2
        hook_text = random.choice(_HOOK_NARRATION_PULLBACK_CN).format(
            min_drawdown=tf["min_drawdown"], window=window_cn)
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines_pullback(rows, label_en.lower())
        def _dur(i):
            if n == 1:
                return 5.2
            if i == 0:
                return 3.94
            if i == n - 1:
                return 4.81
            return 3.99
        hook_dur = 4.3
        hook_text = random.choice(_HOOK_NARRATION_PULLBACK_EN).format(
            min_drawdown=tf["min_drawdown"], window=window_en)
        tts_voice = "en-US-ChristopherNeural"
    ticker_durs = [_dur(i) for i in range(n)]

    frames = [
        (scene_hook_generic(date, lang, [f"{label_en.upper()} HIGH", f"AFTER {tf['min_drawdown']}%+ PULLBACK"],
                            [f"{label_cn}新高", f"回调{tf['min_drawdown']}%以上"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="bounceback"),
         hook_dur, None, hook_text),
    ]
    # One stock at a time (name + pullback % + its 1Y candlestick trend), same as
    # Monday/Tuesday — replaces the old shared table.
    for i, (row, dur, line) in enumerate(zip(rows, ticker_durs, ticker_lines)):
        card = scene_stock_card(row, i + 1, lang, "_drawdown_display", sub_en, sub_cn, gold_leader=False)
        frames.append((card, dur, None, line))

    # Ad reel, same as Monday/Tuesday: real footage with the platform pitch, then a
    # short second beat with the CTA, then the unchanged silent outro card.
    ad_entries = build_ad_reel(lang=lang)
    ad_pitch = _AD_PITCH_CN if lang == "cn" else _AD_PITCH_EN
    ad_pitch2 = _AD_PITCH2_CN if lang == "cn" else _AD_PITCH2_EN
    first = ad_entries[0]
    ad_entries[0] = (first[0], first[1], first[2], ad_pitch)
    last = ad_entries[-1]
    ad_entries[-1] = (last[0], last[1], last[2], ad_pitch2)
    frames += ad_entries
    frames.append((scene_ad_short(date, lang=lang), 2.5, None, None))
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("6m_breakout" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


def build_1y_vol_peak_short(data, output, lang="en"):
    """Thursday — stocks setting a new N-month volume record TODAY. Unlike Monday/
    Tuesday/Wednesday's always-full pools, this event is genuinely rare: most days
    only turn up 1-3 qualifying stocks (sometimes exactly 1), so both the table and
    the trend-scene count adapt to however many rows actually exist today, rather
    than assuming 5. Purely a volume story (no "bounce back" framing — that's
    Wednesday's price-pullback category; there's no equivalent volume concept)."""
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    tf = _thursday_tf(date)
    vol_key = tf["vol_chg_key"]
    seen, peaks = set(), []
    for r in data["data"]:
        t = r.get("Ticker", "")
        if t in seen:
            continue
        seen.add(t)
        if r.get(tf["vol_day_key"]) == 0:
            peaks.append(r)
    peaks.sort(key=lambda r: r.get(vol_key) or 0, reverse=True)
    rows = peaks[:3]

    if not rows:
        print(f"No {tf['label_en']} volume-record stocks today, skipping Short.")
        return

    window_en, window_cn = tf["window_en"], tf["window_cn"]
    sub_en, sub_cn = "TODAY'S VOLUME SURGE", "今日成交量激增"

    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_vol_peak_cn(rows, vol_key)
        hook_dur = 3.8   # budgeted for the longer of the two hook variants (measured 3.60s)
        hook_text = random.choice(_HOOK_NARRATION_VOL_PEAK_CN).format(window=window_cn)
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines_vol_peak(rows, vol_key)
        hook_dur = 4.0   # budgeted for the longer of the two hook variants (measured 3.82s)
        hook_text = random.choice(_HOOK_NARRATION_VOL_PEAK_EN).format(window=window_en)
        tts_voice = "en-US-ChristopherNeural"

    # Per-row duration by position, not a flat per-day list — this category's row
    # count varies day to day (1-3), so a hardcoded array sized for today's count
    # wouldn't fit tomorrow. Budgets are grounded in the "leads/follows/finally"
    # phrasing's measured worst cases from Tuesday/Wednesday's identical templates.
    n = len(rows)
    def _dur(i):
        if n == 1:
            # "There's only one today — TICKER, volume up N percent." (measured ~4.0s)
            return 4.2
        if i == 0 or i == n - 1:
            return 3.3
        return 2.8
    ticker_durs = [_dur(i) for i in range(n)]

    frames = [
        (scene_hook_generic(date, lang, [f"{tf['label_en'].upper()} VOLUME", "RECORD DAY"],
                            [tf["label_cn"], "成交量创纪录"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="highest"),
         hook_dur, None, hook_text),
    ]
    # One stock at a time (name + volume-change number + its 1Y candlestick trend),
    # same as Monday/Tuesday/Wednesday — replaces the old shared table. Row count
    # (1-3) is whatever qualified today, same row-count-awareness as before.
    for i, (row, dur, line) in enumerate(zip(rows, ticker_durs, ticker_lines)):
        card = scene_stock_card(row, i + 1, lang, vol_key, sub_en, sub_cn)
        frames.append((card, dur, None, line))

    # Ad reel, same as the other weekdays: real footage with the platform pitch, then
    # a short second beat with the CTA, then the unchanged silent outro card.
    ad_entries = build_ad_reel(lang=lang)
    ad_pitch = _AD_PITCH_CN if lang == "cn" else _AD_PITCH_EN
    ad_pitch2 = _AD_PITCH2_CN if lang == "cn" else _AD_PITCH2_EN
    first = ad_entries[0]
    ad_entries[0] = (first[0], first[1], first[2], ad_pitch)
    last = ad_entries[-1]
    ad_entries[-1] = (last[0], last[1], last[2], ad_pitch2)
    frames += ad_entries
    frames.append((scene_ad_short(date, lang=lang), 2.5, None, None))
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("1y_vol_peak" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


_HOOK_NARRATION_SPOTLIGHT_EN = [
    "A new name just joined the index.",
    "Index inclusion means passive funds must buy — meet the newest member.",
]

_HOOK_NARRATION_SPOTLIGHT_CN = [
    "一位新成员刚刚加入指数。",
    "指数纳入意味着被动资金必须买入，认识这位新成员。",
]


def build_index_spotlight_short(data, output, lang="en"):
    """Friday — spotlights one recently-added S&P 500 / Nasdaq-100 member and its
    price since joining. Unlike Monday-Thursday's ranked lists, this is a single-
    stock feature (member chosen at random, matching generate_video.py's landscape
    build), so the same spotlight image is narrated across two frames instead of a
    table across five."""
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    members = _get_verified_members(data)

    if not members:
        print("No new index members found today, skipping Short.")
        return

    member = random.choice(members)
    ticker = member["ticker"]
    index_name = member["index_name"]
    index_cn = "纳斯达克100" if "Nasdaq" in index_name else "标普500"
    bdays = member["bdays_since_join"]
    perf = member["perf_since_join"]

    spotlight_img = scene_member_spotlight_short(member, date, lang)

    # Durations = actually-measured edge-tts speech time at SHORTS_TTS_RATE (see
    # measure_fri.py in scratch), +buffer.
    if lang == "cn":
        hook_dur = 4.2
        hook_text = random.choice(_HOOK_NARRATION_SPOTLIGHT_CN)
        spot1_line = f"{ticker}在{bdays}个交易日前加入{index_cn}。"
        spot1_dur = 3.5
        if perf >= 0:
            spot2_line = f"加入以来上涨{perf:.0f}%。"
        else:
            spot2_line = f"加入以来下跌{abs(perf):.0f}%。"
        spot2_dur = 2.6
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        hook_dur = 4.0
        hook_text = random.choice(_HOOK_NARRATION_SPOTLIGHT_EN)
        spot1_line = f"{ticker} joined the {index_name}, {bdays} trading days ago."
        spot1_dur = 4.0
        if perf >= 0:
            spot2_line = f"It's up {perf:.0f} percent since joining."
        else:
            spot2_line = f"It's down {abs(perf):.0f} percent since joining."
        spot2_dur = 2.7
        tts_voice = "en-US-ChristopherNeural"

    frames = [
        (scene_hook_generic(date, lang, ["NEW INDEX", "MEMBERS"], ["新晋", "指数成分股"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="memberchange"),
         hook_dur, None, hook_text),
        (spotlight_img, spot1_dur, None, spot1_line),
        (spotlight_img, spot2_dur, None, spot2_line),
    ]

    # Ad reel, same as the other weekdays: real footage with the platform pitch, then
    # a short second beat with the CTA, then the unchanged silent outro card. Replaces
    # the old membership-change screenshot cluster (that content is now part of the
    # shared reel's screen recording anyway).
    ad_entries = build_ad_reel(lang=lang)
    ad_pitch = _AD_PITCH_CN if lang == "cn" else _AD_PITCH_EN
    ad_pitch2 = _AD_PITCH2_CN if lang == "cn" else _AD_PITCH2_EN
    first = ad_entries[0]
    ad_entries[0] = (first[0], first[1], first[2], ad_pitch)
    last = ad_entries[-1]
    ad_entries[-1] = (last[0], last[1], last[2], ad_pitch2)
    frames += ad_entries
    frames.append((scene_ad_short(date, lang=lang), 2.5, None, None))
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("index_spotlight" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


BUILDERS = {
    "volume_spikes": build_volume_spikes_short,
    "best_performer": build_best_performer_short,
    "6m_breakout": build_6m_breakout_short,
    "1y_vol_peak": build_1y_vol_peak_short,
    "index_spotlight": build_index_spotlight_short,
}


def main():
    ap = argparse.ArgumentParser(description="Baizora YouTube Shorts Generator")
    ap.add_argument("--type", required=True, choices=list(BUILDERS))
    ap.add_argument("--output", default=None)
    ap.add_argument("--data", default=None)
    ap.add_argument("--lang", default="en", choices=["en", "cn"])
    args = ap.parse_args()

    data_path = Path(args.data) if args.data else DATA_FILE
    with open(data_path) as f:
        data = json.load(f)

    output = args.output or str(SCRIPT_DIR / f"{args.type}_short.mp4")
    Path(output).parent.mkdir(parents=True, exist_ok=True)

    print(f"Building SHORT [{args.type}]  ->  {output}")
    BUILDERS[args.type](data, output, lang=args.lang)


if __name__ == "__main__":
    main()
