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


# ── Scene 2: Condensed top-5 table ─────────────────────────────────────────────────

def scene_top5_table(rows, scan_date, lang, title_en, title_cn, sub_en, sub_cn, value_key,
                      gold_leader=True):
    """Generic condensed top-N scene (N up to 5) — Monday (volume spikes) and Tuesday
    (best performer) always have 5 rows; Thursday's volume-record category is a rare
    event that some days only turns up 1-3 qualifying stocks, so the footer position
    is based on the actual row count rather than a hardcoded 5."""
    img, draw = new_frame_s()

    title = title_en if lang == "en" else title_cn
    f_title = load_headline_font(56) if lang == "en" else load_font_cn(44, bold=True)
    centered_s(draw, 60, title, f_title, GOLD_LIGHT)
    sub = sub_en if lang == "en" else sub_cn
    centered_s(draw, 140, sub, load_font(22, mono=True) if lang == "en" else load_font_cn(20), DIM)
    hline_s(draw, 190)

    row_h = 300
    region_top, region_bottom = 220, 1760
    shown = rows[:5]
    # Monday/Tuesday/Wednesday always have 5 rows filling this region top-down; but
    # Thursday's volume-record category is a rare event that some days only turns up
    # 1-3 qualifying stocks, which would otherwise leave a large dead zone below a
    # table pinned to the top — so sparse tables are vertically centered instead.
    if len(shown) < 4:
        block_h = len(shown) * row_h
        top = region_top + max(0, (region_bottom - region_top - block_h) // 2)
    else:
        top = region_top
    f_rank = load_headline_font(44)
    f_tkr = load_font(52, bold=True)
    f_coy = load_font_cn(24) if lang == "cn" else load_font(24)
    f_pct = load_headline_font(60)

    for i, row in enumerate(shown):
        y = top + i * row_h
        if i % 2 == 0:
            draw.rectangle([40, y, SW - 40, y + row_h - 24], fill=NAVY_MID)

        rank_col = (GOLD_LIGHT if i == 0 else MUTED)
        draw.text((70, y + 30), str(i + 1), font=f_rank, fill=rank_col)

        ticker = row.get("Ticker", "")
        draw.text((160, y + 24), ticker, font=f_tkr, fill=WHITE)

        name = (row.get("CompanyName") or "")
        if len(name) > 26:
            name = name[:23] + "..."
        draw.text((160, y + 90), name, font=f_coy, fill=MUTED)

        v = row.get(value_key)
        c = GOLD_LIGHT if (gold_leader and i == 0) else pct_color(v)
        txt = pct_str(v)
        pw = tw(draw, txt, f_pct)
        draw.text((SW - 70 - pw, y + 46), txt, font=f_pct, fill=c)

    hline_s(draw, top + len(shown) * row_h - 10)
    cta = "Full list at baizora.com" if lang == "en" else "完整榜单请见 baizora.com"
    centered_s(draw, top + len(shown) * row_h + 24, cta, load_font(26, bold=True) if lang == "en" else load_font_cn(24, bold=True), ELEC_BRIGHT)
    return img


# ── Scene 2b: quick trend chart for a top mover ────────────────────────────────────

def scene_trend_short(rows, scan_date, lang="en", row_index=0, pct_key="1YPriceChange",
                       period_label_en="1-YEAR", period_footer_en="PAST 12 MONTHS",
                       period_label_cn="一年", period_footer_cn="过去十二个月",
                       spark_days=None):
    """Generic version of the trend scene — Monday's calls (implicit full 1-year) keep
    working via the defaults; Tuesday and others pass whichever timeframe is in that
    week's rotation so the chart matches the % figure actually being narrated."""
    img, draw = new_frame_s()
    dot_grid_s(draw)
    top_row = rows[row_index]
    ticker = top_row.get("Ticker", "")
    pc = top_row.get(pct_key)
    color = BRIGHT_GREEN if (pc or 0) >= 0 else BRIGHT_RED

    title = f"{ticker} — {period_label_en} TREND" if lang == "en" else f"{ticker} — {period_label_cn}走势"
    f_title = load_headline_font(60) if lang == "en" else load_font_cn(48, bold=True)
    centered_s(draw, 110, title, f_title, GOLD_LIGHT)

    name = (top_row.get("CompanyName") or "")
    centered_s(draw, 220, name, load_font(26) if lang == "en" else load_font_cn(24), MUTED)

    full_spark = top_row.get("Spark1Y") or []
    spark = full_spark[-spark_days:] if spark_days and len(full_spark) > spark_days else full_spark
    region = (110, 340, SW - 110, SH - 480)
    if len(spark) >= 2:
        mn_v, mx_v = min(spark), max(spark)
        if mx_v > mn_v:
            n = len(spark)
            x0, y0, x1, y1 = region
            pad = 0.08
            pts = []
            for i, v in enumerate(spark):
                px = x0 + i / (n - 1) * (x1 - x0)
                py = y1 - ((v - mn_v) / (mx_v - mn_v)) * (y1 - y0) * (1 - 2 * pad) - (y1 - y0) * pad
                pts.append((px, py))
            _glow_line(img, draw, pts, color, width=8, glow_radius=20)

    f_pct = load_headline_font(120)
    pct_y = SH - 440
    pct_text = pct_str(pc)
    centered_s(draw, pct_y, pct_text, f_pct, color)
    # Anton's glyph bbox top isn't flush with 0 (unlike most fonts) — use the actual
    # bbox bottom, not draw-y + th(), or the next line collides with the glyph tail.
    pct_bottom = pct_y + draw.textbbox((0, 0), pct_text, font=f_pct)[3]
    centered_s(draw, pct_bottom + 30, period_footer_en if lang == "en" else period_footer_cn,
               load_font(26, mono=True) if lang == "en" else load_font_cn(24), DIM)
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


# ── Scene 2c/2d: real dashboard screenshots (hero, then results table) ─────────────

_SCREENSHOTS_EN = [SCRIPT_DIR / "EN_screenshot1.png", SCRIPT_DIR / "EN_screenshot2.png"]
_SCREENSHOTS_CN = [SCRIPT_DIR / "CN_screenshot1.png", SCRIPT_DIR / "CN_screenshot2.png"]
_SCREENSHOTS_MEMBERCHANGE_EN = [SCRIPT_DIR / "EN_memberchange1.png", SCRIPT_DIR / "EN_memberchange2.png"]
_SCREENSHOTS_MEMBERCHANGE_CN = [SCRIPT_DIR / "CN_memberchange1.png", SCRIPT_DIR / "CN_memberchange2.png"]


def scene_dashboard_short(scan_date, lang="en", heading="", caption="", index=0, screenshots=None):
    img, draw = new_frame_s()
    dot_grid_s(draw)

    f_head = load_headline_font(52) if lang == "en" else load_font_cn(42, bold=True)
    centered_s(draw, 90, heading, f_head, GOLD_LIGHT)

    if screenshots is not None:
        paths = screenshots
    else:
        paths = _SCREENSHOTS_EN if lang == "en" else _SCREENSHOTS_CN
    p = paths[index]
    if p.exists():
        ss = Image.open(str(p)).convert("RGB")
        iw, ih = ss.size
        max_w = SW - 140
        scale = max_w / iw
        nw, nh = int(iw * scale), int(ih * scale)
        ss = ss.resize((nw, nh), Image.LANCZOS)
        sx, sy = (SW - nw) // 2, 220
        draw.rectangle([sx - 8, sy - 8, sx + nw + 8, sy + nh + 8], outline=ELECTRIC, width=4)
        img.paste(ss, (sx, sy))
        caption_y = sy + nh + 60
    else:
        caption_y = 700

    centered_s(draw, caption_y, caption, load_font(28, bold=True) if lang == "en" else load_font_cn(26, bold=True), MUTED)
    centered_s(draw, caption_y + 60, "baizora.com", load_font(38), ELECTRIC)
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
               load_font(18, mono=True), DIM)
    return img


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
            lines.append(f"And rounding out the top five, {ticker}, also up {v:.0f} percent.")
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
        if n == 1 or i == 0:
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
        if n == 1 or i == 0:
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


def _describe_pct(v):
    if v is None:
        return "unavailable"
    return f"up {v:.1f} percent" if v >= 0 else f"down {abs(v):.1f} percent"


def _describe_pct_cn(v):
    if v is None:
        return "数据暂无"
    return f"上涨{v:.1f}%" if v >= 0 else f"下跌{abs(v):.1f}%"


def build_volume_spikes_short(data, output, lang="en"):
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    rows = sorted(data["data"], key=lambda r: r.get("VolumeChange1D") or -9999, reverse=True)

    table_img = scene_top5_table(
        rows, date, lang, "VOLUME SPIKES", "成交量异动",
        "VS 21-DAY AVERAGE VOLUME", "对比21日平均成交量", "VolumeChange1D",
    )
    # Durations below = actually-measured edge-tts speech time at SHORTS_TTS_RATE (EN)
    # or SHORTS_TTS_VOICE_CN (CN) for this exact wording pattern, +~0.15s buffer each —
    # not estimates. Guessed budgets consistently ran short (e.g. the EN leader line
    # "TICKER leads, up N percent" alone measured 3.02s against a guessed 2.05s slot),
    # which is what caused dropped/cut-off narration. If the narration templates in
    # _narrate_ticker_lines(_cn) change, re-measure rather than re-guess.
    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_cn(rows)
        ticker_durs = [2.9, 3.25, 2.3, 2.55, 2.95]
        hook_dur, hook_text = 3.15, random.choice(_HOOK_NARRATION_CN)
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines(rows)
        ticker_durs = [3.4, 2.75, 2.35, 2.4, 3.55]
        hook_dur, hook_text = 3.1, random.choice(_HOOK_NARRATION_EN)
        tts_voice = "en-US-ChristopherNeural"

    frames = [
        (scene_hook_generic(date, lang, ["TOP VOLUME", "STOCKS TODAY"], ["今日成交量", "最高股票"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="bars"),
         hook_dur, None, hook_text),
    ]
    for dur, line in zip(ticker_durs, ticker_lines):
        frames.append((table_img, dur, None, line))

    head1 = "REAL DASHBOARD, LIVE DATA" if lang == "en" else "真实看板 · 实时数据"
    cap1 = "500+ Stocks  ·  Daily Updates" if lang == "en" else "500+只股票 · 每日更新"
    head2 = "EVERY STOCK, RANKED" if lang == "en" else "全部股票排名"
    cap2 = "7 Timeframes  ·  Free 7-Day Trial" if lang == "en" else "7个时间维度 · 七天免费试用"

    t0, t1 = rows[0], rows[1]
    if lang == "cn":
        trend1_line = f"来看{t0.get('Ticker','')}过去一年的走势，{_describe_pct_cn(t0.get('1YPriceChange'))}。"
        trend2_line = f"再看{t1.get('Ticker','')}，同期{_describe_pct_cn(t1.get('1YPriceChange'))}。"
        cta_line = "欢迎订阅，访问baizora.com。"
        trend1_dur, trend2_dur = 3.9, 3.55
    else:
        trend1_line = f"Here's {t0.get('Ticker','')}'s trend over the past year, {_describe_pct(t0.get('1YPriceChange'))}."
        trend2_line = f"And {t1.get('Ticker','')}, {_describe_pct(t1.get('1YPriceChange'))} over the same period."
        cta_line = "Subscribe, and visit baizora dot com."
        trend1_dur, trend2_dur = 4.0, 3.4

    # Screenshots + ad are 3 distinct, brief (~1s each) sequential scenes — not merged
    # into one screen — but the "subscribe" narration starts on the first screenshot
    # and is allowed to keep speaking across the cut into the second screenshot and the
    # ad card (normal voice-over-a-cut), since ~2.5-2.7s of speech can't fit inside a
    # single 1s scene without either rushing the line or cutting it off.
    frames += [
        (scene_trend_short(rows, date, lang=lang, row_index=0), trend1_dur,
         None, trend1_line),
        (scene_trend_short(rows, date, lang=lang, row_index=1), trend2_dur,
         None, trend2_line),
        (scene_dashboard_short(date, lang=lang, heading=head1, caption=cap1, index=0), 1.0,
         None, cta_line),
        (scene_dashboard_short(date, lang=lang, heading=head2, caption=cap2, index=1), 1.0,
         None, None),
        (scene_ad_short(date, lang=lang), 1.2,
         None, None),
    ]
    encode(frames, output, xfade_frames=3, tts_rate=SHORTS_TTS_RATE, tts_voice=tts_voice)

    cover = cover_path_for("volume_spikes" + ("_cn" if lang == "cn" else ""), date_obj)
    if cover:
        _embed_cover(output, cover)


def build_best_performer_short(data, output, lang="en"):
    date = data["date"]
    date_obj = datetime.date.fromisoformat(date)
    tf = _tuesday_tf(date)
    key = tf["key"]
    rows = sorted(data["data"], key=lambda r: r.get(key) or -9999, reverse=True)

    window_en, window_cn = tf["window_en"], tf["window_cn"]
    table_img = scene_top5_table(
        rows, date, lang,
        f"TOP {tf['label_en'].upper()} WINNERS", tf["title_cn"],
        f"OVER THE PAST {window_en.upper()}", f"过去{window_cn}表现",
        key,
    )

    # Durations = actually-measured edge-tts speech time (same measure-don't-guess
    # approach as Monday). Ticker phrasing here is intentionally shorter than Monday's
    # ("leads" not "leads the pack") because best-performer % figures for longer
    # rotation windows (6-Month, 1-Year) can run into the hundreds of percent, and the
    # longer template overran the 30s budget when tested against real data.
    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_best_cn(rows, key)
        ticker_durs = [3.05, 3.20, 2.60, 2.35, 3.40]
        hook_dur = 2.55
        hook_text = random.choice(_HOOK_NARRATION_BEST_CN).format(window=window_cn)
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines_best(rows, key)
        ticker_durs = [3.40, 3.00, 2.65, 2.45, 3.45]
        hook_dur = 2.60
        hook_text = random.choice(_HOOK_NARRATION_BEST_EN).format(window=window_en)
        tts_voice = "en-US-ChristopherNeural"

    frames = [
        (scene_hook_generic(date, lang, [f"TOP {tf['label_en'].upper()}", "WINNERS"],
                            [tf["label_cn"], "最佳表现股票"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="bull"),
         hook_dur, None, hook_text),
    ]
    for dur, line in zip(ticker_durs, ticker_lines):
        frames.append((table_img, dur, None, line))

    head1 = "REAL DASHBOARD, LIVE DATA" if lang == "en" else "真实看板 · 实时数据"
    cap1 = "500+ Stocks  ·  Daily Updates" if lang == "en" else "500+只股票 · 每日更新"
    head2 = "EVERY STOCK, RANKED" if lang == "en" else "全部股票排名"
    cap2 = "7 Timeframes  ·  Free 7-Day Trial" if lang == "en" else "7个时间维度 · 七天免费试用"

    t0, t1 = rows[0], rows[1]
    period_kwargs = dict(pct_key=key, period_label_en=tf["label_en"].upper(),
                         period_footer_en=f"PAST {window_en.upper()}",
                         period_label_cn=tf["label_cn"], period_footer_cn=f"过去{window_cn}",
                         spark_days=tf["spark_days"])
    if lang == "cn":
        trend1_line = f"{t0.get('Ticker','')}的走势，上涨{t0.get(key) or 0:.0f}%。"
        trend2_line = f"再看{t1.get('Ticker','')}，上涨{t1.get(key) or 0:.0f}%。"
        cta_line = "欢迎订阅，访问baizora.com。"
        trend1_dur, trend2_dur = 3.45, 3.20
    else:
        trend1_line = f"{t0.get('Ticker','')}'s trend, up {t0.get(key) or 0:.0f} percent."
        trend2_line = f"And {t1.get('Ticker','')}, up {t1.get(key) or 0:.0f} percent."
        cta_line = "Subscribe, and visit baizora dot com."
        trend1_dur, trend2_dur = 3.70, 3.25

    frames += [
        (scene_trend_short(rows, date, lang=lang, row_index=0, **period_kwargs), trend1_dur,
         None, trend1_line),
        (scene_trend_short(rows, date, lang=lang, row_index=1, **period_kwargs), trend2_dur,
         None, trend2_line),
        (scene_dashboard_short(date, lang=lang, heading=head1, caption=cap1, index=0), 1.0,
         None, cta_line),
        (scene_dashboard_short(date, lang=lang, heading=head2, caption=cap2, index=1), 1.0,
         None, None),
        (scene_ad_short(date, lang=lang), 1.2,
         None, None),
    ]
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
    rows = breakouts[:5]

    if len(rows) < 2:
        # Same real edge case build_6m_breakout() guards against in generate_video.py —
        # some days have too few (or zero) qualifying breakout stocks to fill the table
        # and the two trend scenes.
        print(f"Not enough {tf['label_en']} breakout stocks today ({len(rows)} found), skipping Short.")
        return

    # Table displays the pullback magnitude (as a negative %, in red) rather than
    # today's price move — that's the headline stat for this category.
    for r in rows:
        r["_drawdown_display"] = -abs(r.get("_drawdown") or 0)

    window_en, window_cn = tf["window_en"], tf["window_cn"]
    label_en, label_cn = tf["label_en"], tf["label_cn"]
    table_img = scene_top5_table(
        rows, date, lang,
        f"{label_en.upper()} HIGH BREAKOUTS", tf["title_cn"],
        f"{tf['min_drawdown']}%+ DECLINE, NOW AT A NEW HIGH", f"跌超{tf['min_drawdown']}%，如今创新高",
        "_drawdown_display", gold_leader=False,
    )

    # Narrating only 3 (not 5) tickers — mentioning the pullback % AND the rotating
    # timeframe (it cycles 1M/3M/6M/9M/1Y weekly, so it must be stated, not implied)
    # makes each line longer, so the full 5-ticker cadence used on Monday/Tuesday
    # doesn't fit the 30s budget here. Durations = actually-measured edge-tts speech
    # time at SHORTS_TTS_RATE (see measure_wed4.py in scratch), +buffer.
    if lang == "cn":
        ticker_lines = _narrate_ticker_lines_pullback_cn(rows, label_cn)
        ticker_durs = [3.83, 3.97, 4.16]
        hook_dur = 4.2
        hook_text = random.choice(_HOOK_NARRATION_PULLBACK_CN).format(
            min_drawdown=tf["min_drawdown"], window=window_cn)
        tts_voice = SHORTS_TTS_VOICE_CN
    else:
        ticker_lines = _narrate_ticker_lines_pullback(rows, label_en.lower())
        ticker_durs = [3.94, 3.99, 4.81]
        hook_dur = 4.3
        hook_text = random.choice(_HOOK_NARRATION_PULLBACK_EN).format(
            min_drawdown=tf["min_drawdown"], window=window_en)
        tts_voice = "en-US-ChristopherNeural"

    frames = [
        (scene_hook_generic(date, lang, [f"{label_en.upper()} HIGH", f"AFTER {tf['min_drawdown']}%+ PULLBACK"],
                            [f"{label_cn}新高", f"回调{tf['min_drawdown']}%以上"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="bounceback"),
         hook_dur, None, hook_text),
    ]
    for dur, line in zip(ticker_durs, ticker_lines):
        frames.append((table_img, dur, None, line))

    head1 = "REAL DASHBOARD, LIVE DATA" if lang == "en" else "真实看板 · 实时数据"
    cap1 = "500+ Stocks  ·  Daily Updates" if lang == "en" else "500+只股票 · 每日更新"
    head2 = "EVERY STOCK, RANKED" if lang == "en" else "全部股票排名"
    cap2 = "7 Timeframes  ·  Free 7-Day Trial" if lang == "en" else "7个时间维度 · 七天免费试用"

    t0, t1 = rows[0], rows[1]
    window_key = f"{tf['label_short']}PriceChange"
    period_kwargs = dict(pct_key=window_key, period_label_en=tf["label_en"].upper(),
                         period_footer_en=f"PAST {window_en.upper()}",
                         period_label_cn=tf["label_cn"], period_footer_cn=f"过去{window_cn}",
                         spark_days=tf["spark_days"])
    if lang == "cn":
        trend1_line = f"{t0.get('Ticker','')}的走势，上涨{t0.get(window_key) or 0:.0f}%。"
        trend2_line = f"再看{t1.get('Ticker','')}，上涨{t1.get(window_key) or 0:.0f}%。"
        cta_line = "欢迎订阅，访问baizora.com。"
        trend1_dur, trend2_dur = 2.60, 2.84
    else:
        trend1_line = f"{t0.get('Ticker','')}'s trend, up {t0.get(window_key) or 0:.0f} percent."
        trend2_line = f"And {t1.get('Ticker','')}, up {t1.get(window_key) or 0:.0f} percent."
        cta_line = "Subscribe, and visit baizora dot com."
        trend1_dur, trend2_dur = 2.53, 2.70

    frames += [
        (scene_trend_short(rows, date, lang=lang, row_index=0, **period_kwargs), trend1_dur,
         None, trend1_line),
        (scene_trend_short(rows, date, lang=lang, row_index=1, **period_kwargs), trend2_dur,
         None, trend2_line),
        (scene_dashboard_short(date, lang=lang, heading=head1, caption=cap1, index=0), 1.0,
         None, cta_line),
        (scene_dashboard_short(date, lang=lang, heading=head2, caption=cap2, index=1), 1.0,
         None, None),
        (scene_ad_short(date, lang=lang), 1.5,
         None, None),
    ]
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
    rows = peaks[:5]

    if not rows:
        print(f"No {tf['label_en']} volume-record stocks today, skipping Short.")
        return

    window_en, window_cn = tf["window_en"], tf["window_cn"]
    table_img = scene_top5_table(
        rows, date, lang,
        f"{tf['label_en'].upper()} VOLUME RECORDS", tf["title_cn"],
        "TODAY'S VOLUME SURGE", "今日成交量激增",
        vol_key,
    )

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
    # count varies day to day (1-5), so a hardcoded array sized for today's count
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
    for dur, line in zip(ticker_durs, ticker_lines):
        frames.append((table_img, dur, None, line))

    head1 = "REAL DASHBOARD, LIVE DATA" if lang == "en" else "真实看板 · 实时数据"
    cap1 = "500+ Stocks  ·  Daily Updates" if lang == "en" else "500+只股票 · 每日更新"
    head2 = "EVERY STOCK, RANKED" if lang == "en" else "全部股票排名"
    cap2 = "7 Timeframes  ·  Free 7-Day Trial" if lang == "en" else "7个时间维度 · 七天免费试用"

    window_key = f"{tf['label_short']}PriceChange"
    period_kwargs = dict(pct_key=window_key, period_label_en=tf["label_en"].upper(),
                         period_footer_en=f"PAST {window_en.upper()}",
                         period_label_cn=tf["label_cn"], period_footer_cn=f"过去{window_cn}",
                         spark_days=tf["spark_days"])

    n_trend = min(2, n)
    trend_frames = []
    for i in range(n_trend):
        t = rows[i]
        if lang == "cn":
            prefix = f"{t.get('Ticker','')}的走势" if i == 0 else f"再看{t.get('Ticker','')}"
            line = f"{prefix}，上涨{t.get(window_key) or 0:.0f}%。"
        else:
            prefix = f"{t.get('Ticker','')}'s trend" if i == 0 else f"And {t.get('Ticker','')}"
            line = f"{prefix}, up {t.get(window_key) or 0:.0f} percent."
        trend_frames.append(
            (scene_trend_short(rows, date, lang=lang, row_index=i, **period_kwargs), 3.3, None, line)
        )
    frames += trend_frames

    cta_line = "欢迎订阅，访问baizora.com。" if lang == "cn" else "Subscribe, and visit baizora dot com."
    frames += [
        (scene_dashboard_short(date, lang=lang, heading=head1, caption=cap1, index=0), 1.0,
         None, cta_line),
        (scene_dashboard_short(date, lang=lang, heading=head2, caption=cap2, index=1), 1.0,
         None, None),
        (scene_ad_short(date, lang=lang), 1.5,
         None, None),
    ]
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

    head1 = "MEMBERSHIP CHANGE NEWS" if lang == "en" else "成分股变动资讯"
    cap1 = "Track Every Addition & Removal" if lang == "en" else "追踪每一次调入调出"
    head2 = "FULL CHANGE HISTORY" if lang == "en" else "完整变动记录"
    cap2 = "Kept Since 2026  ·  Free 7-Day Trial" if lang == "en" else "自2026年起完整保存 · 七天免费试用"

    # Durations = actually-measured edge-tts speech time at SHORTS_TTS_RATE (see
    # measure_fri.py in scratch), +buffer. The CTA explicitly names the "membership
    # change news and records" feature shown in the screenshots (not a generic
    # "subscribe" line), which runs longer than other weekdays' CTA — so the ad
    # cluster (screenshot1+screenshot2+ad) is sized larger to fit it without rushing.
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
        # Split into two clips (not one run-on comma sentence) with a genuine ~1s
        # pause between them — a frame's hold_sec only needs to exceed its own
        # speech duration for the *next* clip's start to shift later by the excess
        # (see generate_narration()'s actual_start/earliest_next placement logic),
        # so ss1_dur = speech + 1.0s produces a clean 1-second beat before the CTA.
        cta_line1 = "查看每一次成分股变动和完整记录。"
        cta_line2 = "欢迎订阅，访问baizora.com。"
        ss1_dur, ss2_dur = 3.8, 2.7
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
        cta_line1 = "See every membership change and full history."
        cta_line2 = "Subscribe, and visit baizora dot com."
        ss1_dur, ss2_dur = 3.6, 2.9
        tts_voice = "en-US-ChristopherNeural"

    frames = [
        (scene_hook_generic(date, lang, ["NEW INDEX", "MEMBERS"], ["新晋", "指数成分股"],
                            "S&P 500  ·  Nasdaq-100", "标普500 · 纳斯达克100", bg_style="memberchange"),
         hook_dur, None, hook_text),
        (spotlight_img, spot1_dur, None, spot1_line),
        (spotlight_img, spot2_dur, None, spot2_line),
        (scene_dashboard_short(date, lang=lang, heading=head1, caption=cap1, index=0,
                               screenshots=_SCREENSHOTS_MEMBERCHANGE_EN if lang == "en" else _SCREENSHOTS_MEMBERCHANGE_CN),
         ss1_dur, None, cta_line1),
        (scene_dashboard_short(date, lang=lang, heading=head2, caption=cap2, index=1,
                               screenshots=_SCREENSHOTS_MEMBERCHANGE_EN if lang == "en" else _SCREENSHOTS_MEMBERCHANGE_CN),
         ss2_dur, None, cta_line2),
        (scene_ad_short(date, lang=lang), 2.0, None, None),
    ]
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
