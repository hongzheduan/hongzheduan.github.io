#!/usr/bin/env python3
"""
Baizora Daily Video Generator
Generates branded 1920x1080 MP4 recap videos from data/latest.json

Usage:
    py generate_video.py --type sp500_movers
    py generate_video.py --type platform_intro --output my_intro.mp4

Video types: sp500_movers, nasdaq_movers, volume_spikes, best_performer, platform_intro
"""

import argparse
import datetime
import json
import random
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Dimensions & FPS ──────────────────────────────────────────────────────────
W, H = 1920, 1080
FPS  = 30

# ── Brand colors (RGB) ────────────────────────────────────────────────────────
NAVY        = (6,  13,  31)
NAVY_MID    = (13, 30,  61)
NAVY_LIGHT  = (22, 40,  71)
ELECTRIC    = (59, 130, 246)
ELEC_BRIGHT = (96, 165, 250)
GOLD        = (245, 158,  11)
GOLD_LIGHT  = (252, 211,  77)
GREEN       = (34,  197,  94)
RED         = (239,  68,  68)
BRIGHT_GREEN = (74,  255, 128)
BRIGHT_RED   = (255,  80,  80)
WHITE       = (255, 255, 255)
MUTED       = (203, 213, 225)
DIM         = (148, 163, 184)
VERY_DIM    = (100, 116, 139)
BORDER      = (40,  60,  95)

SCRIPT_DIR = Path(__file__).parent
FONTS_DIR  = SCRIPT_DIR / "fonts"
ROOT_DIR   = SCRIPT_DIR.parent
DATA_FILE  = ROOT_DIR / "data" / "latest.json"


# ── Font loader ───────────────────────────────────────────────────────────────

def load_font(size: int, bold: bool = False, mono: bool = False,
              serif: bool = False) -> ImageFont.FreeTypeFont:
    """Return best available font for the given style."""
    if serif:
        candidates = [
            FONTS_DIR / "DMSerifDisplay-Regular.ttf",
            "C:/Windows/Fonts/georgia.ttf",
            "C:/Windows/Fonts/times.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        ]
    elif mono and bold:
        # mono used to swallow the bold flag silently — this branch only ever
        # loaded DMMono-Regular/Medium regardless of `bold`, so every caller
        # passing mono=True, bold=True (e.g. the JOINED/date labels in
        # generate_shorts.py) rendered as non-bold with no visible error.
        candidates = [
            FONTS_DIR / "DMMono-Bold.ttf",
            FONTS_DIR / "DMMono-Medium.ttf",
            "C:/Windows/Fonts/consolab.ttf",
            "C:/Windows/Fonts/courbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        ]
    elif mono:
        candidates = [
            FONTS_DIR / "DMMono-Regular.ttf",
            FONTS_DIR / "DMMono-Medium.ttf",
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/cour.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ]
    elif bold:
        candidates = [
            FONTS_DIR / "DMSans-Bold.ttf",
            FONTS_DIR / "DMSans-SemiBold.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/calibrib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    else:
        candidates = [
            FONTS_DIR / "DMSans-Regular.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]

    for c in candidates:
        p = Path(c)
        if p.exists():
            return ImageFont.truetype(str(p), size)

    return ImageFont.load_default()


def load_font_cn(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Return best available CJK-capable font (Microsoft YaHei on Windows, Noto CJK on Linux)."""
    candidates = [
        ("C:/Windows/Fonts/msyhbd.ttc", 0) if bold else ("C:/Windows/Fonts/msyh.ttc", 0),
        ("C:/Windows/Fonts/msyh.ttc",   0),
        ("C:/Windows/Fonts/simsun.ttc", 0),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", 2),
        ("/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",      2),
    ]
    for path, idx in candidates:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size, index=idx)
            except Exception:
                continue
    return load_font(size, bold=bold)


# ── Drawing helpers ───────────────────────────────────────────────────────────

def new_frame():
    img  = Image.new("RGB", (W, H), NAVY)
    draw = ImageDraw.Draw(img)
    return img, draw


def tw(draw, text, font):
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0]


def th(draw, text, font):
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[3] - bb[1]


def centered(draw, y, text, font, fill=WHITE):
    draw.text(((W - tw(draw, text, font)) // 2, y), text, font=font, fill=fill)


def hline(draw, y, x0=60, x1=None, color=BORDER, width=1):
    draw.line([(x0, y), (x1 if x1 else W - 60, y)], fill=color, width=width)


def pct_str(v):
    if v is None:
        return "—"
    return f"+{v:.2f}%" if v > 0 else f"{v:.2f}%"


def pct_color(v):
    if v is None or v == 0:
        return MUTED
    return GREEN if v > 0 else RED


def logo_text(draw, x, y, size=30):
    f = load_font(size, serif=True)
    draw.text((x, y), "Baiz", font=f, fill=WHITE)
    draw.text((x + tw(draw, "Baiz", f), y), "ora", font=f, fill=ELECTRIC)


def footer(draw):
    hline(draw, H - 62)
    f = load_font(20)
    centered(draw, H - 50,
             "Baizora  ·  baizora.com  ·  Data: End of Day US Markets",
             f, VERY_DIM)


def top_bar(draw, title, scan_date):
    draw.rectangle([0, 0, W, 96], fill=NAVY_MID)
    hline(draw, 96, x0=0, x1=W)
    has_cjk = any('一' <= c <= '鿿' for c in title)
    f_title = load_font_cn(32, bold=True) if has_cjk else load_font(36, bold=True)
    draw.text((72, 28), title, font=f_title, fill=WHITE)
    f_d = load_font(20, mono=True)
    dw  = tw(draw, scan_date, f_d)
    draw.text((W - 72 - dw, 38), scan_date, font=f_d, fill=MUTED)


# ── Scenes ────────────────────────────────────────────────────────────────────

def scene_title(line1, line2, scan_date, subtitle=""):
    img, draw = new_frame()

    # subtle dot grid
    for gx in range(80, W, 80):
        for gy in range(80, H, 80):
            draw.ellipse([gx - 1, gy - 1, gx + 1, gy + 1], fill=(20, 35, 65))

    # eyebrow badge
    f_mono = load_font(17, mono=True)
    eyebrow = "◈   DAILY MARKET RECAP"
    ew  = tw(draw, eyebrow, f_mono)
    eh  = th(draw, eyebrow, f_mono)
    ex  = (W - ew) // 2
    ey  = 322
    draw.rectangle([ex - 18, ey - 10, ex + ew + 18, ey + eh + 10], fill=NAVY_LIGHT)
    draw.rectangle([ex - 18, ey - 10, ex + ew + 18, ey + eh + 10], outline=ELECTRIC)
    draw.text((ex, ey), eyebrow, font=f_mono, fill=ELEC_BRIGHT)

    # title lines
    centered(draw, 394, line1, load_font(80, bold=True), WHITE)
    centered(draw, 492, line2, load_font(62, bold=True), ELECTRIC)

    # date / subtitle
    centered(draw, 592, f"Scan Date: {scan_date}", load_font(26), MUTED)
    if subtitle:
        centered(draw, 632, subtitle, load_font(24), DIM)

    hline(draw, 692)

    # logo
    f_s = load_font(28, serif=True)
    lx  = (W - tw(draw, "Baiz", f_s) - tw(draw, "ora", f_s)) // 2
    logo_text(draw, lx, 708, 28)
    centered(draw, 752, "baizora.com", load_font(20), DIM)

    return img


def scene_title_cn(line1, line2, scan_date, subtitle=""):
    img, draw = new_frame()

    # dot grid
    for gx in range(80, W, 80):
        for gy in range(80, H, 80):
            draw.ellipse([gx - 1, gy - 1, gx + 1, gy + 1], fill=(20, 35, 65))

    # eyebrow badge
    f_ey    = load_font_cn(17)
    eyebrow = "◈   每日市场回顾"
    ew = tw(draw, eyebrow, f_ey)
    eh = th(draw, eyebrow, f_ey)
    ex = (W - ew) // 2
    ey = 322
    draw.rectangle([ex - 18, ey - 10, ex + ew + 18, ey + eh + 10], fill=NAVY_LIGHT)
    draw.rectangle([ex - 18, ey - 10, ex + ew + 18, ey + eh + 10], outline=ELECTRIC)
    draw.text((ex, ey), eyebrow, font=f_ey, fill=ELEC_BRIGHT)

    centered(draw, 394, line1, load_font_cn(72, bold=True), WHITE)
    centered(draw, 488, line2, load_font_cn(52, bold=True), ELECTRIC)

    centered(draw, 574, f"扫描日期: {scan_date}", load_font_cn(24), MUTED)
    if subtitle:
        centered(draw, 614, subtitle, load_font_cn(22), DIM)

    hline(draw, 674)

    f_logo = load_font_cn(30, bold=True)
    lw = tw(draw, "贝佐拉", f_logo)
    draw.text(((W - lw) // 2, 690), "贝佐拉", font=f_logo, fill=ELEC_BRIGHT)
    centered(draw, 736, "baizora.com", load_font(20), DIM)

    return img


def _draw_promo_panel(draw, px):
    """Advertising panel in the empty right space of table scenes."""
    py = 102
    pw = W - 50 - px
    ph = H - 70 - py

    draw.rectangle([px, py, px + pw, py + ph], fill=NAVY_LIGHT, outline=BORDER)
    draw.rectangle([px, py, px + pw, py + 52], fill=NAVY_MID)

    f_ey = load_font(13, mono=True)
    f_nm = load_font(19, bold=True)
    f_ds = load_font(14)

    draw.text((px + 14, py + 10), "◈  BAIZORA ANALYTICS", font=f_ey, fill=ELEC_BRIGHT)
    draw.text((px + 14, py + 30), "Comprehensive Market Data", font=f_ds, fill=MUTED)
    hline(draw, py + 54, x0=px + 8, x1=px + pw - 8)

    ITEMS = [
        (ELECTRIC,    "Price & Volume",   "All 7 timeframes · 1D to 1Y"),
        (GOLD,        "Volume Spikes",    "Unusual activity signals"),
        (GREEN,       "1-Year Leaders",   "Top 12-month performers"),
        (ELEC_BRIGHT, "Index Changes",    "S&P 500 & Nasdaq-100 tracked"),
        (MUTED,       "Fundamentals",     "PE · EPS · MarketCap · Vol30D"),
    ]

    item_h = (ph - 70 - 76) // len(ITEMS)
    y = py + 66
    for color, name, desc in ITEMS:
        draw.rectangle([px + 10, y + 6, px + 15, y + item_h - 8], fill=color)
        draw.text((px + 24, y + 6),  name, font=f_nm, fill=WHITE)
        draw.text((px + 24, y + 30), desc, font=f_ds, fill=DIM)
        y += item_h

    hline(draw, py + ph - 56, x0=px + 8, x1=px + pw - 8)
    f_url = load_font(18, bold=True)
    url   = "baizora.com"
    uw    = tw(draw, url, f_url)
    draw.text((px + (pw - uw) // 2, py + ph - 46), url,  font=f_url, fill=ELECTRIC)
    f_tr = load_font(13)
    tr   = "Free 7-Day Trial"
    trw  = tw(draw, tr, f_tr)
    draw.text((px + (pw - trw) // 2, py + ph - 24), tr, font=f_tr, fill=GOLD_LIGHT)


def scene_movers_table(title, rows, scan_date, max_rows=10, cta_text="", tf=None):
    img, draw = new_frame()
    top_bar(draw, title, scan_date)

    tf_hdr = f"{tf['label_short']} CHG%" if tf else "1Y CHG%"
    tf_key = tf["key"] if tf else "1YPriceChange"

    if max_rows == 3:
        COLS = [
            ("#",         None,              80),
            ("TICKER",    "Ticker",         155),
            ("COMPANY",   "CompanyName",    360),
            ("PRICE",     "Price",          175),
            ("1D CHG%",   "PriceChange1D",  215),
            ("VOL(M)",    "VolumeM",        195),
            ("1D VOL%",   "VolumeChange1D", 215),
            (tf_hdr,      tf_key,           345),
        ]
        f_hdr = load_font(20, mono=True)
        f_tkr = load_font(40, mono=True)
        f_coy = load_font(26)
        f_val = load_font(36, mono=True)
        row_h = 250
        dy    = 90
    else:
        COLS = [
            ("#",         None,              70),
            ("TICKER",    "Ticker",         130),
            ("COMPANY",   "CompanyName",    310),
            ("PRICE",     "Price",          130),
            ("1D CHG%",   "PriceChange1D",  145),
            ("VOL(M)",    "VolumeM",        140),
            ("1D VOL%",   "VolumeChange1D", 165),
            (tf_hdr,      tf_key,           150),
        ]
        f_hdr = load_font(17, mono=True)
        f_tkr = load_font(27, mono=True)
        f_coy = load_font(21)
        f_val = load_font(26, mono=True)
        row_h = 70
        dy    = 0

    x = 60
    for hdr, _, cw in COLS:
        draw.text((x, 110), hdr, font=f_hdr, fill=DIM)
        x += cw
    hline(draw, 148)

    for idx, row in enumerate(rows[:max_rows]):
        y = 152 + idx * row_h
        bg_h = row_h - 8 if max_rows == 3 else 62
        if idx % 2 == 0:
            draw.rectangle([60, y - 4, W - 60, y + bg_h], fill=NAVY_MID)
        x = 60
        for hdr, key, cw in COLS:
            if key is None:
                draw.text((x + 10, y + dy + 4), str(idx + 1), font=f_hdr, fill=VERY_DIM)
            elif key == "Ticker":
                off = -4 if max_rows == 3 else 0
                draw.text((x, y + dy + off), row.get(key, ""), font=f_tkr, fill=WHITE)
            elif key == "CompanyName":
                name = row.get(key) or ""
                max_len = 22 if max_rows == 3 else 28
                if len(name) > max_len:
                    name = name[:max_len - 3] + "..."
                off = 4 if max_rows == 3 else 2
                draw.text((x, y + dy + off), name, font=f_coy, fill=MUTED)
            elif key == "Price":
                v = row.get(key)
                draw.text((x, y + dy), f"${v:.2f}" if v else "—", font=f_val, fill=WHITE)
            elif key == "VolumeM":
                v = row.get(key)
                draw.text((x, y + dy), f"{v:.2f}M" if v else "—", font=f_val, fill=WHITE)
            else:
                v = row.get(key)
                draw.text((x, y + dy), pct_str(v), font=f_val, fill=pct_color(v))
            x += cw

    if max_rows == 3 and cta_text:
        cta_y = 152 + 3 * row_h + 20
        hline(draw, cta_y, x0=60, x1=W - 60, color=ELECTRIC)
        centered(draw, cta_y + 18, cta_text, load_font(26, bold=True), ELEC_BRIGHT)

    footer(draw)
    return img


def scene_volume_spikes(rows, scan_date):
    img, draw = new_frame()
    top_bar(draw, "Volume Spikes — Unusual Activity", scan_date)

    COLS = [
        ("#",          None,               80),
        ("TICKER",     "Ticker",          155),
        ("COMPANY",    "CompanyName",     350),
        ("PRICE",      "Price",           175),
        ("1D P CHG%",  "PriceChange1D",   215),
        ("VOL(M)",     "VolumeM",         195),
        ("1D V CHG%",  "VolumeChange1D",  225),
        ("VOL/MA21",   "VolumeVsMA21_1D", 345),
    ]

    f_hdr = load_font(20, mono=True)
    f_tkr = load_font(40, mono=True)
    f_coy = load_font(26)
    f_val = load_font(36, mono=True)

    x = 60
    for hdr, _, cw in COLS:
        draw.text((x, 110), hdr, font=f_hdr, fill=DIM)
        x += cw
    hline(draw, 148)

    row_h = 250
    dy    = 90   # vertical offset — centers text in the row

    for idx, row in enumerate(rows[:3]):
        y = 152 + idx * row_h
        if idx % 2 == 0:
            draw.rectangle([60, y - 4, W - 60, y + row_h - 8], fill=NAVY_MID)
        x = 60
        for hdr, key, cw in COLS:
            if key is None:
                draw.text((x + 10, y + dy + 4), str(idx + 1), font=f_hdr, fill=VERY_DIM)
            elif key == "Ticker":
                draw.text((x, y + dy - 4), row.get(key, ""), font=f_tkr, fill=WHITE)
            elif key == "CompanyName":
                name = row.get(key) or ""
                if len(name) > 22:
                    name = name[:19] + "..."
                draw.text((x, y + dy + 4), name, font=f_coy, fill=MUTED)
            elif key == "Price":
                v = row.get(key)
                draw.text((x, y + dy), f"${v:.2f}" if v else "—", font=f_val, fill=WHITE)
            elif key == "VolumeM":
                v = row.get(key)
                draw.text((x, y + dy), f"{v:.2f}M" if v else "—", font=f_val, fill=WHITE)
            elif key == "VolumeVsMA21_1D":
                v = row.get(key)
                c = GOLD if (v and v >= 3) else (GREEN if (v and v >= 1.5) else WHITE)
                draw.text((x, y + dy), f"{v:.2f}x" if v else "—", font=f_val, fill=c)
            elif key == "VolumeChange1D":
                v = row.get(key)
                c = GOLD if (v and v > 200) else pct_color(v)
                draw.text((x, y + dy), pct_str(v), font=f_val, fill=c)
            else:
                v = row.get(key)
                draw.text((x, y + dy), pct_str(v), font=f_val, fill=pct_color(v))
            x += cw

    cta_y = 152 + 3 * row_h + 20
    hline(draw, cta_y, x0=60, x1=W - 60, color=ELECTRIC)
    centered(draw, cta_y + 18,
             "Want to see the full list? Visit baizora.com — Free 7-day trial available.",
             load_font(26, bold=True), ELEC_BRIGHT)

    footer(draw)
    return img


def scene_volume_spikes_cn(rows, scan_date):
    img, draw = new_frame()

    draw.rectangle([0, 0, W, 96], fill=NAVY_MID)
    hline(draw, 96, x0=0, x1=W)
    draw.text((72, 22), "成交量异动 — 异常交易活动", font=load_font_cn(28, bold=True), fill=WHITE)
    f_d = load_font(20, mono=True)
    dw  = tw(draw, scan_date, f_d)
    draw.text((W - 72 - dw, 38), scan_date, font=f_d, fill=MUTED)

    COLS = [
        ("#",       None,               80),
        ("代码",    "Ticker",          155),
        ("公司",    "CompanyName",     350),
        ("价格",    "Price",           175),
        ("日价涨",  "PriceChange1D",   215),
        ("成交量M", "VolumeM",         195),
        ("日量涨",  "VolumeChange1D",  225),
        ("量/MA21", "VolumeVsMA21_1D", 345),
    ]

    f_hdr = load_font_cn(20)
    f_tkr = load_font(40, mono=True)
    f_coy = load_font_cn(26)
    f_val = load_font(36, mono=True)

    x = 60
    for hdr, _, cw in COLS:
        draw.text((x, 108), hdr, font=f_hdr, fill=DIM)
        x += cw
    hline(draw, 148)

    row_h = 250
    dy    = 90

    for idx, row in enumerate(rows[:3]):
        y = 152 + idx * row_h
        if idx % 2 == 0:
            draw.rectangle([60, y - 4, W - 60, y + row_h - 8], fill=NAVY_MID)
        x = 60
        for hdr, key, cw in COLS:
            if key is None:
                draw.text((x + 10, y + dy + 4), str(idx + 1), font=f_hdr, fill=VERY_DIM)
            elif key == "Ticker":
                draw.text((x, y + dy - 4), row.get(key, ""), font=f_tkr, fill=WHITE)
            elif key == "CompanyName":
                name = row.get(key) or ""
                if len(name) > 22:
                    name = name[:19] + "..."
                draw.text((x, y + dy + 4), name, font=f_coy, fill=MUTED)
            elif key == "Price":
                v = row.get(key)
                draw.text((x, y + dy), f"${v:.2f}" if v else "—", font=f_val, fill=WHITE)
            elif key == "VolumeM":
                v = row.get(key)
                draw.text((x, y + dy), f"{v:.2f}M" if v else "—", font=f_val, fill=WHITE)
            elif key == "VolumeVsMA21_1D":
                v = row.get(key)
                c = GOLD if (v and v >= 3) else (GREEN if (v and v >= 1.5) else WHITE)
                draw.text((x, y + dy), f"{v:.2f}x" if v else "—", font=f_val, fill=c)
            elif key == "VolumeChange1D":
                v = row.get(key)
                c = GOLD if (v and v > 200) else pct_color(v)
                draw.text((x, y + dy), pct_str(v), font=f_val, fill=c)
            else:
                v = row.get(key)
                draw.text((x, y + dy), pct_str(v), font=f_val, fill=pct_color(v))
            x += cw

    cta_y = 152 + 3 * row_h + 20
    hline(draw, cta_y, x0=60, x1=W - 60, color=ELECTRIC)
    centered(draw, cta_y + 18,
             "想查看完整榜单？访问baizora.com — 提供七天免费试用。",
             load_font_cn(26, bold=True), ELEC_BRIGHT)

    footer(draw)
    return img


FEATURES = [
    {
        "num": "01", "accent": ELECTRIC,
        "title": "All Metrics in One View",
        "body": [
            "No tab-switching. Every price & volume metric across",
            "7 timeframes — 1D through 1Y — visible at a glance.",
        ],
        "body_text": (
            "No tab-switching. Every price and volume metric across "
            "7 timeframes — from 1D to 1Y — visible and sortable in one table."
        ),
    },
    {
        "num": "02", "accent": ELEC_BRIGHT,
        "title": "1-Year Sparkline with Key Events",
        "body": [
            "Every ticker includes a 1-year price trend chart.",
            "Max volume & max price-change dates marked directly on the spark.",
        ],
        "body_text": (
            "Every ticker includes a 1-year price trend chart. "
            "The date of peak volume and peak single-day price gain "
            "are pinned directly on the spark."
        ),
    },
    {
        "num": "03", "accent": GOLD,
        "title": "Index Membership Changes",
        "body": [
            "S&P 500 & Nasdaq-100 additions and removals tracked daily.",
            "Know the moment a stock enters or exits a major index.",
        ],
        "body_text": (
            "S&P 500 and Nasdaq-100 additions and removals tracked daily. "
            "Know the moment a stock enters or exits a major index — "
            "dual-listed tickers highlighted."
        ),
    },
    {
        "num": "04", "accent": GREEN,
        "title": "Sort Any Timeframe Instantly",
        "body": [
            "Click any column — price change, volume spike, max day —",
            "to rank every large-cap stock by that metric immediately.",
        ],
        "body_text": (
            "Click any column — price change, volume spike, or max-day move — "
            "to rank every large-cap stock by that metric instantly."
        ),
    },
    {
        "num": "05", "accent": MUTED,
        "title": "Fundamentals at a Glance",
        "body": [
            "PE ratio, Market Cap, EPS, and 30-day Volatility",
            "alongside technical data — no separate lookup needed.",
        ],
        "body_text": (
            "PE ratio, Market Cap, EPS, and 30-day Volatility "
            "shown right alongside every technical metric — "
            "no separate lookup needed."
        ),
    },
]


def scene_platform_feature(feat):
    img, draw = new_frame()
    accent = feat["accent"]

    # dim watermark number
    f_wm  = load_font(260, bold=True)
    wm_w  = tw(draw, feat["num"], f_wm)
    wm_h  = th(draw, feat["num"], f_wm)
    wm_x  = W - wm_w - 60
    wm_y  = (H - wm_h) // 2
    blend = tuple(int(NAVY[c] * 0.93 + accent[c] * 0.07) for c in range(3))
    draw.text((wm_x, wm_y), feat["num"], font=f_wm, fill=blend)

    # eyebrow
    f_mono = load_font(17, mono=True)
    draw.text((80, 80), "◈   WHY BAIZORA", font=f_mono, fill=accent)
    hline(draw, 118, x0=80)

    # feature number
    draw.text((80, 150), feat["num"], font=load_font(52, mono=True), fill=accent)

    # title
    draw.text((80, 224), feat["title"], font=load_font(72, bold=True), fill=WHITE)

    # accent bar
    draw.rectangle([80, 318, 168, 323], fill=accent)

    # body lines
    f_body = load_font(34)
    y = 352
    for line in feat["body"]:
        draw.text((80, y), line, font=f_body, fill=MUTED)
        y += 54

    # bottom logo
    hline(draw, H - 120)
    logo_text(draw, 80, H - 96, 30)
    draw.text((80, H - 50), "baizora.com", font=load_font(22), fill=DIM)

    return img


# ── Platform intro split-screen layout ───────────────────────────────────────

_LP_X    = 80    # left text panel start x
_LP_MAXW = 552   # left text panel max width (to x≈632)
_DIV_X   = 648   # vertical divider x
_RP_X    = 664   # right visual panel start x
_RP_Y    = 108   # right panel top y
_RP_W    = W - 60 - _RP_X   # 1196
_RP_BOT  = H - 68


def _wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, cur = [], ""
    for word in words:
        test = (cur + " " + word).strip()
        if tw(draw, test, font) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _wrap_text_cn(draw, text, font, max_width):
    """Character-by-character wrap for CJK text."""
    lines, cur = [], ""
    for ch in text:
        test = cur + ch
        if tw(draw, test, font) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def _visual_all_metrics(img, draw, data):
    rows = sorted(data["data"], key=lambda r: r.get("PriceChange1D") or -9999, reverse=True)[:6]
    rx, ry = _RP_X, _RP_Y

    f_date   = load_font(18, mono=True)
    date_txt = f"SCAN DATE: {data['date']}"
    dw = tw(draw, date_txt, f_date)
    bx = rx + (_RP_W - dw) // 2 - 12
    draw.rectangle([bx, ry + 14, bx + dw + 24, ry + 44], fill=NAVY_LIGHT, outline=ELECTRIC)
    draw.text((bx + 12, ry + 19), date_txt, font=f_date, fill=ELEC_BRIGHT)

    COLS = [
        ("TICKER", "Ticker",        110),
        ("1D %",   "PriceChange1D", 155),
        ("2W %",   "2WPriceChange", 155),
        ("1M %",   "1MPriceChange", 155),
        ("3M %",   "3MPriceChange", 155),
        ("6M %",   "6MPriceChange", 155),
        ("9M %",   "9MPriceChange", 155),
        ("1Y %",   "1YPriceChange", 156),
    ]

    f_hdr = load_font(15, mono=True)
    f_tkr = load_font(18, mono=True)
    f_val = load_font(17, mono=True)

    hdr_y = ry + 60
    x = rx
    for hdr, _, cw in COLS:
        draw.text((x + 6, hdr_y), hdr, font=f_hdr, fill=DIM)
        x += cw
    line_y = hdr_y + 26
    draw.line([(rx, line_y), (rx + _RP_W, line_y)], fill=BORDER)

    row_h = (_RP_BOT - line_y - 20) // 6
    for idx, row in enumerate(rows):
        row_y = line_y + 10 + idx * row_h
        if idx % 2 == 0:
            draw.rectangle([rx, row_y - 4, rx + _RP_W, row_y + row_h - 8], fill=NAVY_LIGHT)
        x = rx
        for hdr, key, cw in COLS:
            if key == "Ticker":
                draw.text((x + 6, row_y + 4), row.get(key, ""), font=f_tkr, fill=WHITE)
            else:
                v = row.get(key)
                draw.text((x + 6, row_y + 4), pct_str(v), font=f_val, fill=pct_color(v))
            x += cw
    return img, draw


def _visual_sparklines_grid(img, draw, data):
    rows = [r for r in sorted(data["data"],
                              key=lambda r: r.get("PriceChange1D") or -9999, reverse=True)
            if r.get("Spark1Y")][:9]
    rx, ry = _RP_X, _RP_Y

    NCOLS, NROWS = 3, 3
    gap    = 6
    cell_w = (_RP_W - (NCOLS + 1) * gap) // NCOLS
    cell_h = (_RP_BOT - ry - (NROWS + 1) * gap) // NROWS
    info_h = 52

    f_tkr = load_font(17, mono=True)
    f_val = load_font(13, mono=True)

    spark_polys = []
    markers     = []  # (type, x, y, color) — drawn after compositing

    for idx, row in enumerate(rows):
        ci = idx % NCOLS
        ri = idx // NCOLS
        x0 = rx + gap + ci * (cell_w + gap)
        y0 = ry + gap + ri * (cell_h + gap)
        x1 = x0 + cell_w
        y1 = y0 + cell_h
        draw.rectangle([x0, y0, x1, y1], fill=NAVY_MID)

        spark = row.get("Spark1Y") or []
        if len(spark) >= 2:
            sx0, sy0 = x0 + 6, y0 + 6
            sw  = cell_w - 12
            sh  = cell_h - info_h - 12
            mn_v, mx_v = min(spark), max(spark)
            if mx_v > mn_v:
                n_pts = len(spark)
                pad   = 0.06

                def _spt(i, v, _sx0=sx0, _sy0=sy0, _sw=sw, _sh=sh,
                         _mn=mn_v, _mx=mx_v, _n=n_pts, _p=pad):
                    px = _sx0 + round(i / (_n - 1) * _sw)
                    py = _sy0 + _sh - round(
                        ((v - _mn) / (_mx - _mn)) * _sh * (1 - 2*_p) + _sh*_p
                    )
                    return (px, py)

                pts    = [_spt(i, v) for i, v in enumerate(spark)]
                pc1y   = row.get("1YPriceChange") or 0
                line_c = GREEN if pc1y >= 0 else RED
                fill_c = (34, 197, 94, 22) if pc1y >= 0 else (239, 68, 68, 22)
                spark_polys.append((
                    pts + [(pts[-1][0], sy0 + sh), (pts[0][0], sy0 + sh)],
                    fill_c,
                ))
                for j in range(len(pts) - 1):
                    draw.line([pts[j], pts[j + 1]], fill=line_c, width=2)

                # Collect markers (drawn after compositing so they sit on top)
                mp_day = row.get("1YMaxPriceChangeDay") or 0
                mp_idx = max(0, min(n_pts - 1, n_pts - 1 - mp_day))
                mp_pt  = _spt(mp_idx, spark[mp_idx])
                markers.append(("tri",    mp_pt[0], mp_pt[1], GOLD))

                mv_day = row.get("1YMaxVolumeChangeDay") or 0
                mv_idx = max(0, min(n_pts - 1, n_pts - 1 - mv_day))
                mv_pt  = _spt(mv_idx, spark[mv_idx])
                markers.append(("circle", mv_pt[0], mv_pt[1], ELECTRIC))

                markers.append(("dot", pts[-1][0], pts[-1][1], ELEC_BRIGHT))

        iy = y1 - info_h + 6
        draw.text((x0 + 8, iy), row.get("Ticker", ""), font=f_tkr, fill=WHITE)
        pc1d   = row.get("PriceChange1D")
        pc1y_v = row.get("1YPriceChange")
        draw.text((x0 + 8,           iy + 24), f"1D {pct_str(pc1d)}",   font=f_val, fill=pct_color(pc1d))
        draw.text((x0 + cell_w // 2, iy + 24), f"1Y {pct_str(pc1y_v)}", font=f_val, fill=pct_color(pc1y_v))

    if spark_polys:
        ov  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ovd = ImageDraw.Draw(ov)
        for poly, fill_c in spark_polys:
            ovd.polygon(poly, fill=fill_c)
        img  = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
        draw = ImageDraw.Draw(img)

    # Draw markers on top of fill layer
    for mtype, mx, my, mcolor in markers:
        if mtype == "dot":
            draw.ellipse([mx-4, my-4, mx+4, my+4], fill=mcolor)
        elif mtype == "tri":
            s = 5
            draw.polygon([(mx, my - s), (mx - s, my + s//2), (mx + s, my + s//2)],
                         fill=mcolor)
        elif mtype == "circle":
            draw.ellipse([mx-5, my-5, mx+5, my+5], outline=mcolor, width=2)

    return img, draw


def _visual_membership(img, draw, data):
    rx, ry = _RP_X, _RP_Y
    rh = _RP_BOT - ry

    changes_file = ROOT_DIR / "data" / "index_changes.json"
    try:
        entries = json.loads(changes_file.read_text())["entries"]
    except Exception:
        entries = []

    panel_w = (_RP_W - 12) // 2
    panels  = [("S&P 500", ELECTRIC, "sp500"), ("NASDAQ-100", GOLD, "nasdaq100")]

    f_hdr  = load_font(20, bold=True)
    f_date = load_font(14, mono=True)
    f_tkr  = load_font(18, mono=True)
    f_sm   = load_font(11, mono=True)

    for pi, (title, accent, key) in enumerate(panels):
        px = rx + pi * (panel_w + 12)
        draw.rectangle([px, ry, px + panel_w, ry + rh], fill=NAVY_MID, outline=accent)
        draw.rectangle([px, ry, px + panel_w, ry + 46], fill=NAVY_LIGHT)
        draw.text((px + 12, ry + 10), title, font=f_hdr, fill=accent)

        y = ry + 58
        for entry in entries:
            if y >= ry + rh - 24:
                break
            section = entry.get(key, {})
            added   = section.get("added", [])
            removed = section.get("removed", [])
            if not added and not removed:
                continue
            draw.text((px + 12, y), entry.get("date", ""), font=f_date, fill=DIM)
            y += 22
            for tkr in added:
                if y >= ry + rh - 24:
                    break
                draw.text((px + 16, y), f"+ {tkr}", font=f_tkr, fill=GREEN)
                stock = next((r for r in data["data"] if r.get("Ticker") == tkr), None)
                if stock and stock.get("InSP500") and stock.get("InNASDAQ100"):
                    bx = px + 16 + tw(draw, f"+ {tkr}", f_tkr) + 8
                    draw.rectangle([bx, y + 2, bx + 36, y + 22], fill=GOLD)
                    draw.text((bx + 3, y + 3), "DUAL", font=f_sm, fill=NAVY)
                y += 28
            for tkr in removed:
                if y >= ry + rh - 24:
                    break
                draw.text((px + 16, y), f"- {tkr}", font=f_tkr, fill=RED)
                y += 28
            y += 8
    return img, draw


def _visual_sort(img, draw, data):
    rows = sorted(data["data"], key=lambda r: r.get("PriceChange1D") or -9999, reverse=True)[:7]
    rx, ry = _RP_X, _RP_Y

    COLS = [
        ("TICKER",      "Ticker",          110),
        ("1D P CHG% ▼", "PriceChange1D",   196),
        ("2W P CHG%",   "2WPriceChange",   170),
        ("1M P CHG%",   "1MPriceChange",   170),
        ("3M P CHG%",   "3MPriceChange",   170),
        ("VOL(M)",      "VolumeM",         155),
        ("VOL/MA21",    "VolumeVsMA21_1D", 225),
    ]

    f_hdr = load_font(16, mono=True)
    f_tkr = load_font(20, mono=True)
    f_val = load_font(18, mono=True)

    hdr_y = ry + 16
    x = rx
    for hdr, _, cw in COLS:
        if "▼" in hdr:
            draw.rectangle([x - 2, hdr_y - 4, x + cw - 6, hdr_y + 26],
                           fill=NAVY_LIGHT, outline=GREEN)
            draw.text((x + 4, hdr_y), hdr, font=f_hdr, fill=GREEN)
        else:
            draw.text((x + 4, hdr_y), hdr, font=f_hdr, fill=DIM)
        x += cw

    line_y = hdr_y + 34
    draw.line([(rx, line_y), (rx + _RP_W, line_y)], fill=BORDER)

    row_h = (_RP_BOT - line_y - 20) // 7
    for idx, row in enumerate(rows):
        row_y = line_y + 8 + idx * row_h
        if idx % 2 == 0:
            draw.rectangle([rx, row_y - 4, rx + _RP_W, row_y + row_h - 8], fill=NAVY_LIGHT)
        x = rx
        for hdr, key, cw in COLS:
            if key == "Ticker":
                draw.text((x + 4, row_y + 4), row.get(key, ""), font=f_tkr, fill=WHITE)
            elif key == "VolumeM":
                v = row.get(key)
                draw.text((x + 4, row_y + 4), f"{v:.2f}M" if v else "—", font=f_val, fill=WHITE)
            elif key == "VolumeVsMA21_1D":
                v = row.get(key)
                c = GOLD if (v and v >= 3) else (GREEN if (v and v >= 1.5) else WHITE)
                draw.text((x + 4, row_y + 4), f"{v:.2f}x" if v else "—", font=f_val, fill=c)
            else:
                v = row.get(key)
                draw.text((x + 4, row_y + 4), pct_str(v), font=f_val, fill=pct_color(v))
            x += cw
    return img, draw


def _visual_fundamentals(img, draw, data):
    rows = sorted(data["data"], key=lambda r: r.get("PriceChange1D") or -9999, reverse=True)[:7]
    rx, ry = _RP_X, _RP_Y

    COLS = [
        ("TICKER",  "Ticker",        120),
        ("COMPANY", "CompanyName",   300),
        ("P/E",     "PE",            155),
        ("MKT CAP", "MarketCap",     195),
        ("EPS",     "EPS",           175),
        ("VOL 30D", "Volatility30D", 251),
    ]

    f_hdr = load_font(16, mono=True)
    f_tkr = load_font(20, mono=True)
    f_coy = load_font(16)
    f_val = load_font(18, mono=True)

    hdr_y = ry + 16
    x = rx
    for hdr, _, cw in COLS:
        draw.text((x + 4, hdr_y), hdr, font=f_hdr, fill=DIM)
        x += cw
    line_y = hdr_y + 34
    draw.line([(rx, line_y), (rx + _RP_W, line_y)], fill=BORDER)

    row_h = (_RP_BOT - line_y - 20) // 7
    for idx, row in enumerate(rows):
        row_y = line_y + 8 + idx * row_h
        if idx % 2 == 0:
            draw.rectangle([rx, row_y - 4, rx + _RP_W, row_y + row_h - 8], fill=NAVY_LIGHT)
        x = rx
        for hdr, key, cw in COLS:
            if key == "Ticker":
                draw.text((x + 4, row_y + 4), row.get(key, ""), font=f_tkr, fill=WHITE)
            elif key == "CompanyName":
                name = row.get(key) or ""
                if len(name) > 22:
                    name = name[:19] + "..."
                draw.text((x + 4, row_y + 6), name, font=f_coy, fill=MUTED)
            elif key == "PE":
                v = row.get(key)
                draw.text((x + 4, row_y + 4), f"{v:.1f}" if v else "—", font=f_val, fill=WHITE)
            elif key == "MarketCap":
                v = row.get(key)
                draw.text((x + 4, row_y + 4), f"${v:.0f}B" if v else "—", font=f_val, fill=WHITE)
            elif key == "EPS":
                v = row.get(key)
                draw.text((x + 4, row_y + 4), f"${v:.2f}" if v else "—", font=f_val, fill=WHITE)
            elif key == "Volatility30D":
                v = row.get(key)
                draw.text((x + 4, row_y + 4), f"{v*100:.1f}%" if v else "—", font=f_val, fill=WHITE)
            x += cw
    return img, draw


_VISUAL_FNS = {
    "01": _visual_all_metrics,
    "02": _visual_sparklines_grid,
    "03": _visual_membership,
    "04": _visual_sort,
    "05": _visual_fundamentals,
}


def _visual_vol_sort(img, draw, data, tf=None):
    """Multi-period volume table — used in volume spikes promo scene.

    When tf is None: sort by VOL/MA21, show 1D + 2W–6M columns (volume_spikes).
    When tf is provided: sort by tf's vol_chg_key, show all 5 Thursday TF columns
    with the current one highlighted (1y_vol_peak).
    """
    if tf is None:
        rows = sorted(data["data"],
                      key=lambda r: r.get("VolumeVsMA21_1D") or -9999, reverse=True)[:7]
        COLS = [
            ("TICKER",      "Ticker",              110),
            ("VOL/MA21 ▼", "VolumeVsMA21_1D",     196),
            ("1D V%",       "VolumeChange1D",       160),
            ("2W MAX V%",   "2WMaxVolumeChange",    175),
            ("1M MAX V%",   "1MMaxVolumeChange",    175),
            ("3M MAX V%",   "3MMaxVolumeChange",    175),
            ("6M MAX V%",   "6MMaxVolumeChange",    205),
        ]
    else:
        chg_key = tf["vol_chg_key"]
        rows = sorted(data["data"],
                      key=lambda r: r.get(chg_key) or -9999, reverse=True)[:7]
        cw = (1196 - 110) // 5  # 217 per TF column
        COLS = [("TICKER", "Ticker", 110)]
        for i, t in enumerate(THURSDAY_TF_ROTATION):
            lbl = f"{t['label_short']} MAX V%"
            if t["vol_chg_key"] == chg_key:
                lbl += " ▼"
            w = cw if i < 4 else (1196 - 110 - cw * 4)
            COLS.append((lbl, t["vol_chg_key"], w))

    rx, ry = _RP_X, _RP_Y

    f_hdr = load_font(18, mono=True)
    f_tkr = load_font(24, mono=True)
    f_val = load_font(22, mono=True)

    hdr_y = ry + 16
    x = rx
    for hdr, _, cw in COLS:
        if "▼" in hdr:
            draw.rectangle([x - 2, hdr_y - 4, x + cw - 6, hdr_y + 26],
                           fill=NAVY_LIGHT, outline=GOLD)
            draw.text((x + 4, hdr_y), hdr, font=f_hdr, fill=GOLD)
        else:
            draw.text((x + 4, hdr_y), hdr, font=f_hdr, fill=DIM)
        x += cw

    line_y = hdr_y + 34
    draw.line([(rx, line_y), (rx + _RP_W, line_y)], fill=BORDER)

    row_h = (_RP_BOT - line_y - 20) // 7
    for idx, row in enumerate(rows):
        row_y = line_y + 8 + idx * row_h
        if idx % 2 == 0:
            draw.rectangle([rx, row_y - 4, rx + _RP_W, row_y + row_h - 8], fill=NAVY_LIGHT)
        x = rx
        for hdr, key, cw in COLS:
            if key == "Ticker":
                draw.text((x + 4, row_y + 4), row.get(key, ""), font=f_tkr, fill=WHITE)
            elif key == "VolumeVsMA21_1D":
                v = row.get(key)
                c = GOLD if (v and v >= 3) else (GREEN if (v and v >= 1.5) else WHITE)
                draw.text((x + 4, row_y + 4), f"{v:.2f}x" if v else "—", font=f_val, fill=c)
            else:
                v = row.get(key)
                draw.text((x + 4, row_y + 4), pct_str(v), font=f_val, fill=pct_color(v))
            x += cw
    return img, draw


def scene_top3_sparklines(title, rows, scan_date, more_text="", tf=None):
    """3-column full-height sparkline scene showing top 3 rows with large fonts."""
    img, draw = new_frame()
    top_bar(draw, title, scan_date)

    NCOLS   = 3
    margin  = 30
    gap     = 16
    top     = 102
    bot     = H - 80         # reserve bottom strip for "more" message
    cell_w  = (W - 2*margin - (NCOLS - 1)*gap) // NCOLS   # ≈ 609 px
    cell_h  = bot - top                                     # ≈ 898 px
    info_h  = 170            # info block height at top of each cell

    f_tkr = load_font(38, mono=True)
    f_co  = load_font(26)
    f_val = load_font(26, mono=True)

    tf_key        = tf["key"]        if tf else "1YPriceChange"
    tf_label      = tf["label_en"]   if tf else "1 Year"
    tf_spark_days = tf["spark_days"] if tf else None

    spark_polys = []   # (points, fill_color)

    for idx, row in enumerate(rows[:3]):
        x0 = margin + idx * (cell_w + gap)
        y0 = top
        x1 = x0 + cell_w
        y1 = y0 + cell_h

        draw.rectangle([x0, y0, x1, y1], fill=NAVY_MID)

        ticker = row.get("Ticker", "")
        draw.text((x0 + 16, y0 + 14), ticker, font=f_tkr, fill=WHITE)

        cname = _short_name(row.get("CompanyName", ""), ticker)
        if len(cname) > 26:
            cname = cname[:23] + "..."
        draw.text((x0 + 16, y0 + 62), cname, font=f_co, fill=MUTED)

        pc1d  = row.get("PriceChange1D")
        pc_tf = row.get(tf_key)
        draw.text((x0 + 16, y0 + 100),
                  f"Today   {pct_str(pc1d)}", font=f_val, fill=pct_color(pc1d))
        draw.text((x0 + 16, y0 + 134),
                  f"{tf_label:<8}{pct_str(pc_tf)}", font=f_val, fill=pct_color(pc_tf))

        draw.line([(x0 + 8, y0 + info_h), (x1 - 8, y0 + info_h)], fill=BORDER)

        # Sparkline area
        sx0 = x0 + 16
        sy0 = y0 + info_h + 12
        sw  = cell_w - 32
        sh  = cell_h - info_h - 24

        full_spark = row.get("Spark1Y") or []
        spark = full_spark[-tf_spark_days:] if tf_spark_days and len(full_spark) > tf_spark_days else full_spark
        if len(spark) >= 2:
            mn_v, mx_v = min(spark), max(spark)
            if mx_v > mn_v:
                n_pts = len(spark)
                pad   = 0.06

                def spark_pt(i, v, _sx0=sx0, _sy0=sy0, _sw=sw, _sh=sh,
                             _mn=mn_v, _mx=mx_v, _n=n_pts, _p=pad):
                    px = _sx0 + round(i / (_n - 1) * _sw)
                    py = _sy0 + _sh - round(
                        ((v - _mn) / (_mx - _mn)) * _sh * (1 - 2*_p) + _sh*_p
                    )
                    return (px, py)

                pts = [spark_pt(i, v) for i, v in enumerate(spark)]
                lc  = BRIGHT_GREEN if (pc_tf or 0) >= 0 else BRIGHT_RED
                fc  = (*lc, 30)

                spark_polys.append(
                    (pts + [(pts[-1][0], sy0 + sh), (pts[0][0], sy0 + sh)], fc)
                )

                for j in range(len(pts) - 1):
                    draw.line([pts[j], pts[j + 1]], fill=lc, width=3)

                draw.ellipse([pts[-1][0]-6, pts[-1][1]-6,
                               pts[-1][0]+6, pts[-1][1]+6], fill=ELEC_BRIGHT)

    if spark_polys:
        ov  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ovd = ImageDraw.Draw(ov)
        for poly, fc in spark_polys:
            ovd.polygon(poly, fill=fc)
        img  = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
        draw = ImageDraw.Draw(img)

    if more_text:
        hline(draw, H - 68)
        has_cjk = any('一' <= c <= '鿿' for c in more_text)
        f_more  = load_font_cn(24, bold=True) if has_cjk else load_font(24, bold=True)
        centered(draw, H - 56, more_text, f_more, ELEC_BRIGHT)

    return img


def scene_breakout_table(breakouts, scan_date, tf=None):
    """Table for N-month high breakout stocks with custom computed columns."""
    img, draw = new_frame()
    n       = len(breakouts)
    label   = tf["label_en"] if tf else "1-Year"
    high_hdr = tf["high_hdr"] if tf else "1Y HIGH"
    top_bar(draw, f"{label} High Breakouts — Top {n}  ({scan_date})", scan_date)

    COLS = [
        ("#",        None,              80),
        ("TICKER",   "Ticker",         155),
        ("COMPANY",  "CompanyName",    290),
        ("PRICE",    "Price",          175),
        ("1D CHG%",  "PriceChange1D",  215),
        ("PULLBACK", "_drawdown",      210),
        (high_hdr,   "_peak_price",    215),
        ("PEAK AGO", "_months_ago",    200),
    ]

    f_hdr = load_font(20, mono=True)
    f_tkr = load_font(40, mono=True)
    f_coy = load_font(26)
    f_val = load_font(36, mono=True)
    row_h = 250
    dy    = 90

    x = 60
    for hdr, _, cw in COLS:
        draw.text((x, 110), hdr, font=f_hdr, fill=DIM)
        x += cw
    hline(draw, 148)

    for idx, row in enumerate(breakouts[:3]):
        y    = 152 + idx * row_h
        bg_h = row_h - 8
        if idx % 2 == 0:
            draw.rectangle([60, y - 4, W - 60, y + bg_h], fill=NAVY_MID)
        x = 60
        for hdr, key, cw in COLS:
            if key is None:
                draw.text((x + 10, y + dy + 4), str(idx + 1), font=f_hdr, fill=VERY_DIM)
            elif key == "Ticker":
                draw.text((x, y + dy - 4), row.get(key, ""), font=f_tkr, fill=WHITE)
            elif key == "CompanyName":
                name = row.get(key) or ""
                if len(name) > 20:
                    name = name[:19] + "…"
                draw.text((x, y + dy), name, font=f_coy, fill=MUTED)
            elif key == "Price":
                v = row.get(key)
                draw.text((x, y + dy - 4), f"${v:.2f}" if v else "—",
                          font=f_val, fill=WHITE)
            elif key == "PriceChange1D":
                v = row.get(key)
                draw.text((x, y + dy - 4), pct_str(v),
                          font=f_val, fill=pct_color(v))
            elif key == "_drawdown":
                v = row.get(key, 0)
                draw.text((x, y + dy - 4), f"-{v:.1f}%",
                          font=f_val, fill=GOLD_LIGHT)
            elif key == "_peak_price":
                v = row.get(key, 0)
                draw.text((x, y + dy - 4), f"${v:.2f}",
                          font=f_val, fill=MUTED)
            elif key == "_months_ago":
                v = row.get(key, 0)
                draw.text((x, y + dy - 4), f"~{v:.1f}mo",
                          font=f_val, fill=DIM)
            x += cw

    hline(draw, H - 60)
    f_cta = load_font(22, bold=True)
    centered(draw, H - 50,
             "See all breakout candidates at baizora.com — Free 7-day trial.",
             f_cta, ELEC_BRIGHT)
    return img


def scene_breakout_sparklines(breakouts, scan_date, peak_label="1Y HIGH", title=None):
    """3-column sparklines with gold markers showing the 1-year high just crossed."""
    img, draw = new_frame()
    top_bar(draw,
            title or f"1-Year High Breakouts — Price Trend  ({scan_date})", scan_date)

    NCOLS  = 3
    margin = 30
    gap    = 16
    top    = 102
    bot    = H - 80
    cell_w = (W - 2*margin - (NCOLS - 1)*gap) // NCOLS
    cell_h = bot - top
    info_h = 170

    f_tkr = load_font(38, mono=True)
    f_co  = load_font(26)
    f_val = load_font(26, mono=True)
    f_lbl = load_font(15, mono=True)

    spark_polys = []
    post_dots   = []   # (x, y, color, r) drawn after composite

    for idx, row in enumerate(breakouts[:3]):
        x0 = margin + idx * (cell_w + gap)
        y0 = top
        x1 = x0 + cell_w
        y1 = y0 + cell_h

        draw.rectangle([x0, y0, x1, y1], fill=NAVY_MID)

        ticker = row.get("Ticker", "")
        draw.text((x0 + 16, y0 + 14), ticker, font=f_tkr, fill=WHITE)

        cname = _short_name(row.get("CompanyName", ""), ticker)
        if len(cname) > 26:
            cname = cname[:23] + "..."
        draw.text((x0 + 16, y0 + 62), cname, font=f_co, fill=MUTED)

        pc1d     = row.get("PriceChange1D")
        drawdown = row.get("_drawdown", 0)
        draw.text((x0 + 16, y0 + 100),
                  f"Today    {pct_str(pc1d)}", font=f_val, fill=pct_color(pc1d))
        draw.text((x0 + 16, y0 + 134),
                  f"Pullback -{drawdown:.1f}%", font=f_val, fill=GOLD_LIGHT)

        draw.line([(x0 + 8, y0 + info_h), (x1 - 8, y0 + info_h)], fill=BORDER)

        sx0      = x0 + 16
        sy0      = y0 + info_h + 12
        sw       = cell_w - 32
        sh       = cell_h - info_h - 24
        spark    = row.get("Spark1Y") or []
        peak_idx = row.get("_peak_idx", 0)

        if len(spark) >= 2:
            mn_v, mx_v = min(spark), max(spark)
            if mx_v > mn_v:
                n_pts = len(spark)
                pad   = 0.06

                def spark_pt(i, v, _sx0=sx0, _sy0=sy0, _sw=sw, _sh=sh,
                             _mn=mn_v, _mx=mx_v, _n=n_pts, _p=pad):
                    px = _sx0 + round(i / (_n - 1) * _sw)
                    py = _sy0 + _sh - round(
                        ((v - _mn) / (_mx - _mn)) * _sh * (1 - 2*_p) + _sh*_p
                    )
                    return (px, py)

                pts  = [spark_pt(i, v) for i, v in enumerate(spark)]
                pk_x, pk_y = spark_pt(peak_idx, spark[peak_idx])

                # Gold vertical line at peak day
                draw.line([(pk_x, sy0), (pk_x, sy0 + sh)], fill=GOLD, width=1)
                # Gold dashed horizontal line at peak price level
                for ddx in range(0, sw, 8):
                    lx0 = sx0 + ddx
                    lx1 = min(sx0 + ddx + 4, sx0 + sw)
                    draw.line([(lx0, pk_y), (lx1, pk_y)], fill=GOLD, width=1)
                # "PREV HIGH" label
                lbl_x = x1 - tw(draw, peak_label, f_lbl) - 10
                draw.text((lbl_x, pk_y - 20), peak_label, font=f_lbl, fill=GOLD)

                pc1y = row.get("1YPriceChange")
                lc   = BRIGHT_GREEN if (pc1y or 0) >= 0 else BRIGHT_RED
                fc   = (*lc, 30)
                spark_polys.append(
                    (pts + [(pts[-1][0], sy0 + sh), (pts[0][0], sy0 + sh)], fc)
                )
                for j in range(len(pts) - 1):
                    draw.line([pts[j], pts[j + 1]], fill=lc, width=3)

                # Draw dots after composite
                post_dots.append((pk_x, pk_y, GOLD, 6))
                post_dots.append((pts[-1][0], pts[-1][1], ELEC_BRIGHT, 6))

    if spark_polys:
        ov  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ovd = ImageDraw.Draw(ov)
        for poly, fc in spark_polys:
            ovd.polygon(poly, fill=fc)
        img  = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
        draw = ImageDraw.Draw(img)

    for (dx, dy, dc, dr) in post_dots:
        draw.ellipse([dx - dr, dy - dr, dx + dr, dy + dr], fill=dc)

    hline(draw, H - 68)
    f_more = load_font(24, bold=True)
    centered(draw, H - 56,
             "Want to see more? Visit baizora.com for the full S&P 500 & Nasdaq-100 analysis.",
             f_more, ELEC_BRIGHT)
    return img


def scene_breakout_table_cn(breakouts, scan_date, tf=None):
    """CN table for N-month high breakout stocks."""
    img, draw = new_frame()
    n        = len(breakouts)
    title_cn = tf["title_cn"]    if tf else "一年新高突破"
    high_hdr = tf["high_hdr_cn"] if tf else "年高价"
    top_bar(draw, f"{title_cn} — 前{n}名  ({scan_date})", scan_date)

    COLS = [
        ("#",       None,             80),
        ("代码",    "Ticker",        155),
        ("公司",    "CompanyName",   290),
        ("价格",    "Price",         175),
        ("日涨幅",  "PriceChange1D", 215),
        ("回调幅度","_drawdown",     210),
        (high_hdr,  "_peak_price",   215),
        ("距高点",  "_months_ago",   200),
    ]

    f_hdr = load_font_cn(18)
    f_tkr = load_font(40, mono=True)
    f_coy = load_font_cn(24)
    f_val = load_font(36, mono=True)
    row_h = 250
    dy    = 90

    x = 60
    for hdr, _, cw in COLS:
        draw.text((x, 110), hdr, font=f_hdr, fill=DIM)
        x += cw
    hline(draw, 148)

    for idx, row in enumerate(breakouts[:3]):
        y    = 152 + idx * row_h
        bg_h = row_h - 8
        if idx % 2 == 0:
            draw.rectangle([60, y - 4, W - 60, y + bg_h], fill=NAVY_MID)
        x = 60
        for hdr, key, cw in COLS:
            if key is None:
                draw.text((x + 10, y + dy + 4), str(idx + 1), font=f_hdr, fill=VERY_DIM)
            elif key == "Ticker":
                draw.text((x, y + dy - 4), row.get(key, ""), font=f_tkr, fill=WHITE)
            elif key == "CompanyName":
                name = row.get(key) or ""
                if len(name) > 20:
                    name = name[:19] + "…"
                draw.text((x, y + dy), name, font=f_coy, fill=MUTED)
            elif key == "Price":
                v = row.get(key)
                draw.text((x, y + dy - 4), f"${v:.2f}" if v else "—",
                          font=f_val, fill=WHITE)
            elif key == "PriceChange1D":
                v = row.get(key)
                draw.text((x, y + dy - 4), pct_str(v),
                          font=f_val, fill=pct_color(v))
            elif key == "_drawdown":
                v = row.get(key, 0)
                draw.text((x, y + dy - 4), f"-{v:.1f}%",
                          font=f_val, fill=GOLD_LIGHT)
            elif key == "_peak_price":
                v = row.get(key, 0)
                draw.text((x, y + dy - 4), f"${v:.2f}",
                          font=f_val, fill=MUTED)
            elif key == "_months_ago":
                v = row.get(key, 0)
                draw.text((x, y + dy - 4), f"约{round(v)}个月前",
                          font=load_font_cn(32), fill=DIM)
            x += cw

    hline(draw, H - 60)
    f_cta = load_font_cn(20, bold=True)
    centered(draw, H - 50,
             "访问baizora.com查看所有符合条件的突破股票 — 提供七天免费试用。",
             f_cta, ELEC_BRIGHT)
    return img


def _visual_1y_sort(img, draw, data, tf):
    """Multi-timeframe price table sorted by tf's key — used in extreme_1y promo scene."""
    rows = sorted(data["data"],
                  key=lambda r: r.get(tf["key"]) or -9999, reverse=True)[:7]
    rx, ry = _RP_X, _RP_Y

    _PRICE_COLS = [
        ("1Y P CHG%", "1YPriceChange", 200),
        ("9M P CHG%", "9MPriceChange", 172),
        ("6M P CHG%", "6MPriceChange", 172),
        ("3M P CHG%", "3MPriceChange", 172),
        ("1M P CHG%", "1MPriceChange", 172),
        ("2W P CHG%", "2WPriceChange", 198),
    ]
    COLS = [("TICKER", "Ticker", 110)] + [
        (hdr + " ▼" if key == tf["key"] else hdr, key, cw)
        for hdr, key, cw in _PRICE_COLS
    ]

    f_hdr = load_font(18, mono=True)
    f_tkr = load_font(24, mono=True)
    f_val = load_font(22, mono=True)

    hdr_y = ry + 16
    x = rx
    for hdr, _, cw in COLS:
        if "▼" in hdr:
            draw.rectangle([x - 2, hdr_y - 4, x + cw - 6, hdr_y + 26],
                           fill=NAVY_LIGHT, outline=GREEN)
            draw.text((x + 4, hdr_y), hdr, font=f_hdr, fill=GREEN)
        else:
            draw.text((x + 4, hdr_y), hdr, font=f_hdr, fill=DIM)
        x += cw

    line_y = hdr_y + 34
    draw.line([(rx, line_y), (rx + _RP_W, line_y)], fill=BORDER)

    row_h = (_RP_BOT - line_y - 20) // 7
    for idx, row in enumerate(rows):
        row_y = line_y + 8 + idx * row_h
        if idx % 2 == 0:
            draw.rectangle([rx, row_y - 4, rx + _RP_W, row_y + row_h - 8], fill=NAVY_LIGHT)
        x = rx
        for hdr, key, cw in COLS:
            if key == "Ticker":
                draw.text((x + 4, row_y + 4), row.get(key, ""), font=f_tkr, fill=WHITE)
            else:
                v = row.get(key)
                draw.text((x + 4, row_y + 4), pct_str(v), font=f_val, fill=pct_color(v))
            x += cw
    return img, draw


def scene_1y_sort_promo(data, date, tf=None):
    """10-second promo scene for best_performer: multi-timeframe price sort table."""
    explicit_tf = tf is not None
    if not explicit_tf:
        tf = TUESDAY_TF_ROTATION[-1]  # default to 1Y for sort; title stays generic
    img, draw = new_frame()
    accent = GREEN

    f_wm  = load_font(200, bold=True)
    wm_w  = tw(draw, "04", f_wm)
    wm_h  = th(draw, "04", f_wm)
    blend = tuple(int(NAVY[c] * 0.93 + accent[c] * 0.07) for c in range(3))
    draw.text((_DIV_X - wm_w - 24, (H - wm_h) // 2), "04", font=f_wm, fill=blend)

    draw.text((_LP_X, 70), "◈   BAIZORA PLATFORM", font=load_font(20, mono=True), fill=accent)
    draw.line([(_LP_X, 106), (_DIV_X, 106)], fill=BORDER)

    f_title    = load_font(40, bold=True)
    title_text = (f"Best {tf['label_en']} Performers — Every Timeframe"
                  if explicit_tf else "Best Performers — Every Timeframe")
    title_lines = _wrap_text(draw, title_text, f_title, _LP_MAXW)
    ty          = 132
    lh_title    = th(draw, "Ag", f_title) + 10
    for line in title_lines:
        draw.text((_LP_X, ty), line, font=f_title, fill=WHITE)
        ty += lh_title

    bar_y = ty + 14
    draw.rectangle([_LP_X, bar_y, _LP_X + 80, bar_y + 5], fill=accent)

    body_subject = (f"today's best {tf['label_en'].lower()} performers"
                    if explicit_tf else "today's best performers")
    body = (
        f"On Baizora, see how {body_subject} compare across every timeframe — "
        "from 2 weeks to 1 year. Sort by any column to instantly find the leaders "
        "across the full S&P 500 and Nasdaq-100 universe."
    )
    f_body     = load_font(26)
    body_lines = _wrap_text(draw, body, f_body, _LP_MAXW)
    by         = bar_y + 22
    lh_body    = th(draw, "Ag", f_body) + 8
    for line in body_lines:
        draw.text((_LP_X, by), line, font=f_body, fill=MUTED)
        by += lh_body

    draw.line([(_DIV_X, 70), (_DIV_X, H - 68)], fill=BORDER)
    draw.line([(_LP_X, H - 96), (_DIV_X, H - 96)], fill=BORDER)
    logo_text(draw, _LP_X, H - 74, 26)

    draw.rectangle([_RP_X - 4, _RP_Y - 8, W - 60, _RP_BOT + 8],
                   fill=NAVY_MID, outline=BORDER)
    img, draw = _visual_1y_sort(img, draw, data, tf)

    return img


def scene_movers_table_cn(title, rows, scan_date, cta_text="", tf=None):
    """CN 3-row movers table with CJK headers and large fonts."""
    img, draw = new_frame()
    top_bar(draw, title, scan_date)

    tf_hdr = f"{tf['label_cn']}涨幅" if tf else "年涨幅"
    tf_key = tf["key"] if tf else "1YPriceChange"

    COLS = [
        ("#",       None,              80),
        ("代码",    "Ticker",         155),
        ("公司",    "CompanyName",    360),
        ("价格",    "Price",          175),
        ("日涨幅",  "PriceChange1D",  215),
        ("成交量M", "VolumeM",        195),
        ("日量涨",  "VolumeChange1D", 215),
        (tf_hdr,    tf_key,           345),
    ]

    f_hdr = load_font_cn(20)
    f_tkr = load_font(40, mono=True)
    f_coy = load_font_cn(24)
    f_val = load_font(36, mono=True)
    row_h = 250
    dy    = 90

    x = 60
    for hdr, _, cw in COLS:
        draw.text((x, 110), hdr, font=f_hdr, fill=DIM)
        x += cw
    hline(draw, 148)

    for idx, row in enumerate(rows[:3]):
        y = 152 + idx * row_h
        if idx % 2 == 0:
            draw.rectangle([60, y - 4, W - 60, y + row_h - 8], fill=NAVY_MID)
        x = 60
        for hdr, key, cw in COLS:
            if key is None:
                draw.text((x + 10, y + dy + 4), str(idx + 1), font=f_hdr, fill=VERY_DIM)
            elif key == "Ticker":
                draw.text((x, y + dy - 4), row.get(key, ""), font=f_tkr, fill=WHITE)
            elif key == "CompanyName":
                name = row.get(key) or ""
                if len(name) > 22:
                    name = name[:19] + "..."
                draw.text((x, y + dy + 4), name, font=f_coy, fill=MUTED)
            elif key == "Price":
                v = row.get(key)
                draw.text((x, y + dy), f"${v:.2f}" if v else "—", font=f_val, fill=WHITE)
            elif key == "VolumeM":
                v = row.get(key)
                draw.text((x, y + dy), f"{v:.2f}M" if v else "—", font=f_val, fill=WHITE)
            else:
                v = row.get(key)
                draw.text((x, y + dy), pct_str(v), font=f_val, fill=pct_color(v))
            x += cw

    if cta_text:
        cta_y = 152 + 3 * row_h + 20
        hline(draw, cta_y, x0=60, x1=W - 60, color=ELECTRIC)
        centered(draw, cta_y + 18, cta_text, load_font_cn(26, bold=True), ELEC_BRIGHT)

    footer(draw)
    return img


def scene_1y_sort_promo_cn(data, date, tf=None):
    """CN 10-second promo scene for best_performer_cn: multi-timeframe price sort table."""
    explicit_tf = tf is not None
    if not explicit_tf:
        tf = TUESDAY_TF_ROTATION[-1]  # default to 1Y for sort; title stays generic
    img, draw = new_frame()
    accent = GREEN

    f_wm  = load_font(200, bold=True)
    wm_w  = tw(draw, "04", f_wm)
    wm_h  = th(draw, "04", f_wm)
    blend = tuple(int(NAVY[c] * 0.93 + accent[c] * 0.07) for c in range(3))
    draw.text((_DIV_X - wm_w - 24, (H - wm_h) // 2), "04", font=f_wm, fill=blend)

    draw.text((_LP_X, 70), "◈   贝佐拉平台", font=load_font_cn(26), fill=accent)
    draw.line([(_LP_X, 106), (_DIV_X, 106)], fill=BORDER)

    f_title    = load_font_cn(40, bold=True)
    title_text = (f"{tf['label_cn']}领涨股 — 各时间维度表现"
                  if explicit_tf else "各时间维度的领涨表现")
    title_lines = _wrap_text_cn(draw, title_text, f_title, _LP_MAXW)
    ty          = 132
    lh_title    = th(draw, "贝", f_title) + 10
    for line in title_lines:
        draw.text((_LP_X, ty), line, font=f_title, fill=WHITE)
        ty += lh_title

    bar_y = ty + 14
    draw.rectangle([_LP_X, bar_y, _LP_X + 80, bar_y + 5], fill=accent)

    body_subject = f"{tf['label_cn']}领涨股" if explicit_tf else "领涨股"
    body = (
        f"在贝佐拉，可查看{body_subject}在各时间维度的表现——从两周到一年。"
        "按任意列排序，即时发现S&P 500和纳斯达克100全市场的领涨股。"
    )
    f_body     = load_font_cn(26)
    body_lines = _wrap_text_cn(draw, body, f_body, _LP_MAXW)
    by         = bar_y + 22
    lh_body    = th(draw, "贝", f_body) + 8
    for line in body_lines:
        draw.text((_LP_X, by), line, font=f_body, fill=MUTED)
        by += lh_body

    draw.line([(_DIV_X, 70), (_DIV_X, H - 68)], fill=BORDER)
    draw.line([(_LP_X, H - 96), (_DIV_X, H - 96)], fill=BORDER)
    draw.text((_LP_X, H - 74), "贝佐拉", font=load_font_cn(26, bold=True), fill=ELEC_BRIGHT)

    draw.rectangle([_RP_X - 4, _RP_Y - 8, W - 60, _RP_BOT + 8],
                   fill=NAVY_MID, outline=BORDER)
    img, draw = _visual_1y_sort(img, draw, data, tf)

    return img


def scene_vol_sort_promo_cn(data, date, tf=None):
    """CN promo scene for volume_spikes_cn / 1y_vol_peak_cn: multi-period volume sort table."""
    img, draw = new_frame()
    accent = GOLD

    f_wm  = load_font(200, bold=True)
    wm_w  = tw(draw, "04", f_wm)
    wm_h  = th(draw, "04", f_wm)
    blend = tuple(int(NAVY[c] * 0.93 + accent[c] * 0.07) for c in range(3))
    draw.text((_DIV_X - wm_w - 24, (H - wm_h) // 2), "04", font=f_wm, fill=blend)

    draw.text((_LP_X, 70), "◈   贝佐拉平台", font=load_font_cn(26), fill=accent)
    draw.line([(_LP_X, 106), (_DIV_X, 106)], fill=BORDER)

    f_title = load_font_cn(40, bold=True)
    if tf:
        title_text = "成交量记录 — 各时间维度"
        body = (
            "在贝佐拉，可查看股票在各时间维度的成交量表现——从一个月到一年。"
            "按任意列排序，即时发现S&P 500和纳斯达克100全市场最大成交量异动。"
        )
    else:
        title_text = "各时间维度的成交量异动"
        body = (
            "在贝佐拉，可轻松查看每个时间维度的成交量数据——从一天到一年。"
            "按任意列排序，即时发现S&P 500和纳斯达克100全市场最大成交量异动。"
        )
    title_lines = _wrap_text_cn(draw, title_text, f_title, _LP_MAXW)
    ty          = 132
    lh_title    = th(draw, "贝", f_title) + 10
    for line in title_lines:
        draw.text((_LP_X, ty), line, font=f_title, fill=WHITE)
        ty += lh_title

    bar_y = ty + 14
    draw.rectangle([_LP_X, bar_y, _LP_X + 80, bar_y + 5], fill=accent)

    f_body     = load_font_cn(26)
    body_lines = _wrap_text_cn(draw, body, f_body, _LP_MAXW)
    by         = bar_y + 22
    lh_body    = th(draw, "贝", f_body) + 8
    for line in body_lines:
        draw.text((_LP_X, by), line, font=f_body, fill=MUTED)
        by += lh_body

    draw.line([(_DIV_X, 70), (_DIV_X, H - 68)], fill=BORDER)

    draw.line([(_LP_X, H - 96), (_DIV_X, H - 96)], fill=BORDER)
    draw.text((_LP_X, H - 74), "贝佐拉", font=load_font_cn(26, bold=True), fill=ELEC_BRIGHT)

    draw.rectangle([_RP_X - 4, _RP_Y - 8, W - 60, _RP_BOT + 8],
                   fill=NAVY_MID, outline=BORDER)
    img, draw = _visual_vol_sort(img, draw, data, tf)

    return img


def scene_vol_sort_promo(data, date, tf=None):
    """Promo scene for volume_spikes / 1y_vol_peak: multi-period volume sort table."""
    img, draw = new_frame()

    accent = GOLD

    # Left panel watermark
    f_wm  = load_font(200, bold=True)
    wm_w  = tw(draw, "04", f_wm)
    wm_h  = th(draw, "04", f_wm)
    blend = tuple(int(NAVY[c] * 0.93 + accent[c] * 0.07) for c in range(3))
    draw.text((_DIV_X - wm_w - 24, (H - wm_h) // 2), "04", font=f_wm, fill=blend)

    # Left panel header
    draw.text((_LP_X, 70), "◈   BAIZORA PLATFORM", font=load_font(20, mono=True), fill=accent)
    draw.line([(_LP_X, 106), (_DIV_X, 106)], fill=BORDER)

    # Title + body vary by context
    f_title = load_font(40, bold=True)
    if tf:
        title_text = "Volume Records — Across All Timeframes"
        body = (
            "On Baizora, see how today's volume record stocks compare "
            "across every timeframe — from 1 month to 1 year. Sort by any column to find "
            "the biggest volume movers in the S&P 500 and Nasdaq-100."
        )
    else:
        title_text = "Volume Spikes Across All Timeframes"
        body = (
            "On Baizora, access volume spike data for every timeframe — "
            "from 1 day to 1 year. Sort by any column to instantly find "
            "the biggest volume spikes across the full S&P 500 and Nasdaq-100 universe."
        )
    title_lines = _wrap_text(draw, title_text, f_title, _LP_MAXW)
    ty          = 132
    lh_title    = th(draw, "Ag", f_title) + 10
    for line in title_lines:
        draw.text((_LP_X, ty), line, font=f_title, fill=WHITE)
        ty += lh_title

    bar_y = ty + 14
    draw.rectangle([_LP_X, bar_y, _LP_X + 80, bar_y + 5], fill=accent)

    f_body     = load_font(26)
    body_lines = _wrap_text(draw, body, f_body, _LP_MAXW)
    by         = bar_y + 22
    lh_body    = th(draw, "Ag", f_body) + 8
    for line in body_lines:
        draw.text((_LP_X, by), line, font=f_body, fill=MUTED)
        by += lh_body

    # Vertical divider
    draw.line([(_DIV_X, 70), (_DIV_X, H - 68)], fill=BORDER)

    # Bottom logo
    draw.line([(_LP_X, H - 96), (_DIV_X, H - 96)], fill=BORDER)
    logo_text(draw, _LP_X, H - 74, 26)

    # Right panel
    draw.rectangle([_RP_X - 4, _RP_Y - 8, W - 60, _RP_BOT + 8],
                   fill=NAVY_MID, outline=BORDER)
    img, draw = _visual_vol_sort(img, draw, data, tf)

    return img


def scene_platform_feature_v2(feat, data):
    img, draw = new_frame()
    accent = feat["accent"]

    # ── Left panel watermark ────────────────────────────────────────────────
    f_wm  = load_font(200, bold=True)
    wm_w  = tw(draw, feat["num"], f_wm)
    wm_h  = th(draw, feat["num"], f_wm)
    blend = tuple(int(NAVY[c] * 0.93 + accent[c] * 0.07) for c in range(3))
    draw.text((_DIV_X - wm_w - 24, (H - wm_h) // 2), feat["num"], font=f_wm, fill=blend)

    # ── Left panel text ─────────────────────────────────────────────────────
    draw.text((_LP_X, 70), "◈   WHY BAIZORA", font=load_font(20, mono=True), fill=accent)
    draw.line([(_LP_X, 106), (_DIV_X, 106)], fill=BORDER)

    draw.text((_LP_X, 132), feat["num"], font=load_font(44, mono=True), fill=accent)

    f_title     = load_font(40, bold=True)
    title_lines = _wrap_text(draw, feat["title"], f_title, _LP_MAXW)
    ty          = 196
    lh_title    = th(draw, "Ag", f_title) + 10
    for line in title_lines:
        draw.text((_LP_X, ty), line, font=f_title, fill=WHITE)
        ty += lh_title

    bar_y = ty + 14
    draw.rectangle([_LP_X, bar_y, _LP_X + 80, bar_y + 5], fill=accent)

    f_body     = load_font(26)
    body_lines = _wrap_text(draw, feat["body_text"], f_body, _LP_MAXW)
    by         = bar_y + 22
    lh_body    = th(draw, "Ag", f_body) + 8
    for line in body_lines:
        draw.text((_LP_X, by), line, font=f_body, fill=MUTED)
        by += lh_body

    # ── Vertical divider ────────────────────────────────────────────────────
    draw.line([(_DIV_X, 70), (_DIV_X, H - 68)], fill=BORDER)

    # ── Bottom logo ─────────────────────────────────────────────────────────
    draw.line([(_LP_X, H - 96), (_DIV_X, H - 96)], fill=BORDER)
    logo_text(draw, _LP_X, H - 74, 26)

    # ── Right panel card background ─────────────────────────────────────────
    draw.rectangle([_RP_X - 4, _RP_Y - 8, W - 60, _RP_BOT + 8],
                   fill=NAVY_MID, outline=BORDER)

    # ── Right panel visual ──────────────────────────────────────────────────
    img, draw = _VISUAL_FNS[feat["num"]](img, draw, data)

    return img


def scene_platform_feature_v2_cn(feat, data):
    """CN version of split-screen feature scene — left panel in Chinese."""
    img, draw = new_frame()
    accent = feat["accent"]

    # ── Left panel watermark ────────────────────────────────────────────────
    f_wm  = load_font(200, bold=True)
    wm_w  = tw(draw, feat["num"], f_wm)
    wm_h  = th(draw, feat["num"], f_wm)
    blend = tuple(int(NAVY[c] * 0.93 + accent[c] * 0.07) for c in range(3))
    draw.text((_DIV_X - wm_w - 24, (H - wm_h) // 2), feat["num"], font=f_wm, fill=blend)

    # ── Left panel text ─────────────────────────────────────────────────────
    draw.text((_LP_X, 70), "◈   为什么选择贝佐拉",
              font=load_font_cn(26), fill=accent)
    draw.line([(_LP_X, 106), (_DIV_X, 106)], fill=BORDER)

    draw.text((_LP_X, 132), feat["num"], font=load_font(44, mono=True), fill=accent)

    f_title     = load_font_cn(38, bold=True)
    title_lines = _wrap_text_cn(draw, feat["title"], f_title, _LP_MAXW)
    ty          = 196
    lh_title    = th(draw, "贝", f_title) + 10
    for line in title_lines:
        draw.text((_LP_X, ty), line, font=f_title, fill=WHITE)
        ty += lh_title

    bar_y = ty + 14
    draw.rectangle([_LP_X, bar_y, _LP_X + 80, bar_y + 5], fill=accent)

    f_body     = load_font_cn(24)
    body_lines = _wrap_text_cn(draw, feat["body_text"], f_body, _LP_MAXW)
    by         = bar_y + 22
    lh_body    = th(draw, "贝", f_body) + 8
    for line in body_lines:
        draw.text((_LP_X, by), line, font=f_body, fill=MUTED)
        by += lh_body

    # ── Vertical divider ────────────────────────────────────────────────────
    draw.line([(_DIV_X, 70), (_DIV_X, H - 68)], fill=BORDER)

    # ── Bottom 贝佐拉 brand ─────────────────────────────────────────────────
    draw.line([(_LP_X, H - 96), (_DIV_X, H - 96)], fill=BORDER)
    f_brand = load_font_cn(26, bold=True)
    draw.text((_LP_X, H - 74), "贝佐拉", font=f_brand, fill=ELEC_BRIGHT)

    # ── Right panel card background ─────────────────────────────────────────
    draw.rectangle([_RP_X - 4, _RP_Y - 8, W - 60, _RP_BOT + 8],
                   fill=NAVY_MID, outline=BORDER)

    # ── Right panel visual (same data panels as EN version) ─────────────────
    img, draw = _VISUAL_FNS[feat["num"]](img, draw, data)

    return img


def scene_outro(scan_date):
    img, draw = new_frame()

    f_big  = load_font(96, serif=True)
    baiz_w = tw(draw, "Baiz", f_big)
    ora_w  = tw(draw, "ora",  f_big)
    lx     = (W - baiz_w - ora_w) // 2
    draw.text((lx,           310), "Baiz", font=f_big, fill=WHITE)
    draw.text((lx + baiz_w,  310), "ora",  font=f_big, fill=ELECTRIC)

    centered(draw, 432, "US Large-Cap Price & Volume Analytics", load_font(28), MUTED)
    hline(draw, 496)
    centered(draw, 518, "Start your free 7-day trial", load_font(28, bold=True), GOLD_LIGHT)
    centered(draw, 564, "baizora.com", load_font(30), ELECTRIC)
    centered(draw, 620, f"Daily Scan: {scan_date}", load_font(20, mono=True), DIM)

    # Disclaimer
    centered(draw, 688,
             "For informational purposes only. Not financial advice. Past performance does not guarantee future results.",
             load_font(17), VERY_DIM)

    return img


def scene_outro_cn(scan_date):
    img, draw = new_frame()

    f_big   = load_font_cn(88, bold=True)
    brand_w = tw(draw, "贝佐拉", f_big)
    lx      = (W - brand_w) // 2
    draw.text((lx, 310), "贝佐拉", font=f_big, fill=ELEC_BRIGHT)

    centered(draw, 432, "美股大盘价格与成交量分析平台", load_font_cn(26), MUTED)
    hline(draw, 496)
    centered(draw, 518, "开始七天免费试用", load_font_cn(26, bold=True), GOLD_LIGHT)
    centered(draw, 564, "baizora.com", load_font(30), ELECTRIC)
    centered(draw, 620, f"每日扫描：{scan_date}", load_font_cn(20), DIM)

    centered(draw, 688,
             "仅供参考，不构成投资建议。过往表现不代表未来结果。",
             load_font_cn(17), VERY_DIM)

    return img


def scene_screenshot(path):
    """Load a website screenshot, scale to fit 1920×1080, return as a video frame."""
    img, _ = new_frame()
    p = Path(path)
    if p.exists():
        ss = Image.open(str(p)).convert("RGB")
        iw, ih = ss.size
        scale = min(W / iw, H / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        ss = ss.resize((nw, nh), Image.LANCZOS)
        img.paste(ss, ((W - nw) // 2, (H - nh) // 2))
    return img


_SS_EN = str(SCRIPT_DIR / "baizora_homepage_Screenshot_2.png")
_SS_CN = str(SCRIPT_DIR / "baizora_homepage_Screenshot_cn_2.png")
_SS_MEMBERSHIP_NEWS   = str(SCRIPT_DIR / "membership_news_screenshot.png")
_SS_MEMBERSHIP_CHANGE = str(SCRIPT_DIR / "membership_change_screenshot.png")


# ── Sparklines scene ─────────────────────────────────────────────────────────

def scene_sparklines(title, rows, scan_date, line_color=None):
    """5×2 grid: ticker info on the left, 1-year sparkline on the right.

    line_color: optional RGB tuple to override the default green/red coloring.
    """
    img, draw = new_frame()
    top_bar(draw, title, scan_date)

    NCOLS, NROWS = 2, 5
    mgx  = 14
    mgy  = 6
    content_top = 102
    content_bot = H - 65
    cw   = (W - 3 * mgx) // NCOLS
    ch   = (content_bot - content_top - (NROWS - 1) * mgy) // NROWS
    info_w = 220

    f_tkr = load_font(22, mono=True)
    f_co  = load_font(16)
    f_val = load_font(17, mono=True)

    spark_polys = []   # list of (points, fill_color)

    for idx, row in enumerate(rows[:10]):
        ci = idx % NCOLS
        ri = idx // NCOLS
        x0 = mgx + ci * (cw + mgx)
        y0 = content_top + ri * (ch + mgy)
        x1 = x0 + cw
        y1 = y0 + ch

        draw.rectangle([x0, y0, x1, y1], fill=NAVY_MID)

        ticker = row.get("Ticker", "")
        draw.text((x0 + 10, y0 + 8),  ticker, font=f_tkr, fill=WHITE)

        cname = _short_name(row.get("CompanyName", ""), ticker)
        if len(cname) > 22:
            cname = cname[:19] + "..."
        draw.text((x0 + 10, y0 + 34), cname, font=f_co, fill=MUTED)

        pc1d = row.get("PriceChange1D")
        draw.text((x0 + 10, y1 - 44),
                  f"Today   {pct_str(pc1d)}", font=f_val, fill=pct_color(pc1d))

        pc1y = row.get("1YPriceChange")
        draw.text((x0 + 10, y1 - 24),
                  f"1 Year  {pct_str(pc1y)}", font=f_val, fill=pct_color(pc1y))

        draw.line([(x0 + info_w, y0 + 8), (x0 + info_w, y1 - 8)],
                  fill=BORDER, width=1)

        sx0 = x0 + info_w + 8
        sy0 = y0 + 10
        sw  = x1 - sx0 - 8
        sh  = ch - 20

        spark = row.get("Spark1Y") or []
        if len(spark) >= 2:
            mn_v, mx_v = min(spark), max(spark)
            if mx_v > mn_v:
                n_pts = len(spark)
                pad   = 0.07

                def spark_pt(i, v):
                    px = sx0 + round(i / (n_pts - 1) * sw)
                    py = sy0 + sh - round(
                        ((v - mn_v) / (mx_v - mn_v)) * sh * (1 - 2*pad) + sh*pad
                    )
                    return (px, py)

                pts = [spark_pt(i, v) for i, v in enumerate(spark)]

                if line_color:
                    lc = line_color
                    fc = (*line_color, 35)
                else:
                    lc = GREEN if (pc1y or 0) >= 0 else RED
                    fc = (59, 130, 246, 28)

                spark_polys.append(
                    (pts + [(pts[-1][0], sy0 + sh), (pts[0][0], sy0 + sh)], fc)
                )

                for j in range(len(pts) - 1):
                    draw.line([pts[j], pts[j+1]], fill=lc, width=2)

                draw.ellipse([pts[-1][0]-4, pts[-1][1]-4,
                               pts[-1][0]+4, pts[-1][1]+4], fill=ELEC_BRIGHT)

    if spark_polys:
        ov  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ovd = ImageDraw.Draw(ov)
        for poly, fc in spark_polys:
            ovd.polygon(poly, fill=fc)
        img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")

    draw = ImageDraw.Draw(img)
    footer(draw)
    return img


# ── Subtitle renderer ────────────────────────────────────────────────────────

def burn_subtitle(img: Image.Image, text: str) -> Image.Image:
    """Overlay a centered subtitle bar near the bottom of the frame."""
    bar_y0, bar_y1 = 936, 990

    # Semi-transparent navy overlay via RGBA composite
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle(
        [0, bar_y0, W, bar_y1], fill=(6, 13, 31, 210)
    )
    base = img.convert("RGBA")
    base = Image.alpha_composite(base, overlay).convert("RGB")

    draw = ImageDraw.Draw(base)
    has_cjk = any('一' <= c <= '鿿' for c in text)
    f    = load_font_cn(27) if has_cjk else load_font(27)
    draw.text(((W - tw(draw, text, f)) // 2, bar_y0 + 10),
              text, font=f, fill=WHITE)
    return base


# ── Narration helpers ─────────────────────────────────────────────────────────

def _short_name(company_name, ticker=""):
    """Strip legal suffixes so company names sound natural in TTS."""
    name = (company_name or ticker or "").strip()
    for s in [" Corporation", " Corp.", " Corp", " Incorporated", " Inc.",
              " Inc", " Limited", " Ltd.", " Ltd", " PLC", " N.V.", " S.A.",
              " Holdings", " Group Inc", " Group", ", Inc", ", LLC",
              " International", " Technologies", " Solutions", " Systems"]:
        name = name.replace(s, "")
    return name.strip().rstrip(",").strip() or ticker


def _narrate_movers(rows, mode):
    """Name the top 3 tickers confidently — ticker symbol only, no company name."""
    top = rows[:3]
    parts = []
    for r in top:
        ticker = r.get("Ticker", "")
        v      = r.get("PriceChange1D") or 0
        parts.append(f"{ticker}, {'up' if v >= 0 else 'down'} {abs(v):.1f} percent")
    lead = ("Today's top three gainers are"
            if mode == "gainers" else "The biggest decliners today are")
    if len(parts) >= 3:
        return f"{lead}: {parts[0]}, {parts[1]}, and {parts[2]}."
    elif parts:
        return lead + ": " + " and ".join(parts) + "."
    return ""


def _narrate_volume(rows):
    top = rows[:3]
    parts = []
    for r in top:
        ticker = r.get("Ticker", "")
        v      = r.get("VolumeChange1D") or 0
        parts.append(f"{ticker}, volume up {abs(v):.0f} percent")
    if len(parts) >= 3:
        return (f"The three biggest volume spikes today: "
                f"{parts[0]}, {parts[1]}, and {parts[2]}. "
                f"Now let's look at their price charts.")
    elif parts:
        return ("Today's top volume spikes: " + " and ".join(parts) + ". "
                "Now let's look at their price charts.")
    return ""


def _narrate_volume_cn(rows):
    top = rows[:3]
    parts = []
    for r in top:
        ticker = r.get("Ticker", "")
        v      = r.get("VolumeChange1D") or 0
        parts.append(f"{ticker}成交量上涨{abs(v):.0f}%")
    if len(parts) >= 3:
        return f"今日成交量异动前三名：{parts[0]}，{parts[1]}，以及{parts[2]}。下面来看它们的价格走势。"
    elif parts:
        return "今日成交量异动：" + "，".join(parts) + "。下面来看价格走势。"
    return ""


# ── Background music generator ────────────────────────────────────────────────

def generate_music(duration_sec, output_wav):
    """
    Synthesize a beat-based electronic background track:
    kick / snare / hi-hat rhythm + bass line + pad chords (Am-F-C-G loop).
    """
    import numpy as np
    import wave as _wave

    sr   = 44100
    bpm  = 88
    beat = 60.0 / bpm          # ~0.682 s per beat
    bar  = beat * 4
    n    = int(duration_sec * sr)
    dt   = 1.0 / sr
    audio = np.zeros(n)

    # ── Kick: frequency-swept sine with exponential decay ────────────────────
    _klen = int(0.42 * sr)
    _tk   = np.linspace(0, 0.42, _klen)
    _fk   = 80 * np.exp(-_tk * 20) + 38
    _kick = np.exp(-_tk * 5.5) * np.sin(2*np.pi * np.cumsum(_fk) * dt)

    # ── Snare: short tone + noise ─────────────────────────────────────────────
    np.random.seed(7)
    _slen  = int(0.20 * sr)
    _ts    = np.linspace(0, 0.20, _slen)
    _snare = np.exp(-_ts * 13) * (0.38*np.sin(2*np.pi*210*_ts)
                                   + 0.62*np.random.randn(_slen)) * 0.50

    # ── Hi-hat: tiny noise burst ──────────────────────────────────────────────
    _hlen = int(0.055 * sr)
    _th   = np.linspace(0, 0.055, _hlen)
    _hat  = np.exp(-_th * 65) * np.random.randn(_hlen) * 0.10

    def place(buf, t_sec):
        s = int(t_sec * sr); e = min(s + len(buf), n)
        if e > s: audio[s:e] += buf[:e-s]

    bars = int(duration_sec / bar) + 2
    for b in range(bars):
        t0 = b * bar
        place(_kick * 0.90, t0)              # beat 1 kick
        place(_kick * 0.70, t0 + 2*beat)    # beat 3 kick
        place(_snare,        t0 +   beat)    # beat 2 snare
        place(_snare,        t0 + 3*beat)    # beat 4 snare
        for ei in range(8):                  # 8th-note hi-hats
            place(_hat * (0.80 if ei%2==0 else 0.45), t0 + ei*beat*0.5)

    # ── Bass line: Am - F - C - G, one note per bar ───────────────────────────
    roots = [110.00, 87.31, 130.81, 98.00]   # A2, F2, C3, G2
    for b in range(bars):
        t0 = b * bar; freq = roots[b % 4]
        seg_n = int(bar * sr)
        t_seg = np.linspace(0, bar, seg_n)
        env_b = np.minimum(t_seg / 0.015, 1.0) * np.exp(-t_seg * 0.9)
        place(env_b * np.sin(2*np.pi*freq*t_seg) * 0.26, t0)

    # ── Pad chords ────────────────────────────────────────────────────────────
    chords = [
        [(110,0.09),(130.81,0.07),(164.81,0.06),(220,0.05),(261.63,0.03)],   # Am
        [(87.31,0.09),(103.83,0.07),(130.81,0.06),(174.61,0.05),(207.65,0.03)], # Fm
        [(130.81,0.09),(164.81,0.07),(196,0.06),(261.63,0.05),(329.63,0.03)], # C
        [(98,0.09),(123.47,0.07),(146.83,0.06),(196,0.05),(246.94,0.03)],     # G
    ]
    for b in range(bars):
        t0 = b * bar
        seg_n = min(int(bar * sr), n - int(t0 * sr))
        if seg_n <= 0: continue
        t_seg = np.linspace(0, bar, seg_n)
        pad = np.zeros(seg_n)
        for freq, amp in chords[b % 4]:
            pad += amp * (1 + 0.04*np.sin(2*np.pi*0.18*t_seg)) * np.sin(2*np.pi*freq*t_seg)
        fd = min(int(0.04*sr), seg_n//4)
        pad[:fd] *= np.linspace(0,1,fd); pad[-fd:] *= np.linspace(1,0,fd)
        place(pad, t0)

    # Master fade in/out
    fade = min(int(1.2*sr), n//5)
    audio[:fade] *= np.linspace(0,1,fade); audio[-fade:] *= np.linspace(1,0,fade)
    peak = np.max(np.abs(audio))
    if peak > 0: audio = audio / peak * 0.58

    mono16 = (audio * 32767).astype(np.int16)
    shift  = int(0.004 * sr); right = np.roll(mono16, shift); right[:shift] = 0
    stereo = np.column_stack([mono16, right])
    with _wave.open(output_wav, "w") as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(sr)
        wf.writeframes(stereo.tobytes())


# ── TTS narration generator ───────────────────────────────────────────────────

def generate_narration(scene_scripts, total_sec, output_wav, ffmpeg_path,
                        voice="en-US-ChristopherNeural", rate="+20%"):
    """
    scene_scripts : list of (preferred_start_sec, narration_text)
    Strategy: generate every TTS clip first, measure its length, then place
    them sequentially — each clip starts at max(preferred_start, prev_end + gap).
    This guarantees zero overlap even when a clip is longer than its scene.
    Primary:  edge-tts  (en-US-ChristopherNeural)
    Fallback: Windows SAPI pyttsx3 / Microsoft David Desktop
    """
    import asyncio
    import numpy as np
    import wave as _wave

    sr    = 44100
    n     = int(total_sec * sr)
    audio = np.zeros(n)
    GAP   = 0.25   # minimum silence between consecutive narrations (seconds)

    async def _edge(text, mp3):
        try:
            import edge_tts
        except ImportError:
            import subprocess as _sp, sys as _sys
            _sp.run([_sys.executable, "-m", "pip", "install", "edge-tts"], check=True)
            import edge_tts
        await edge_tts.Communicate(text, voice, rate=rate).save(mp3)

    def _sapi(text, wav):
        import pyttsx3
        eng = pyttsx3.init()
        for v in eng.getProperty("voices"):
            if "david" in v.name.lower():
                eng.setProperty("voice", v.id)
                break
        eng.setProperty("rate", 155)
        eng.setProperty("volume", 0.95)
        eng.save_to_file(text, wav)
        eng.runAndWait()

    def _make_clip(text, tmp_dir, i):
        """Return float64 numpy array for text, or None on failure."""
        mp3  = str(Path(tmp_dir) / f"tts_{i}.mp3")
        sapi = str(Path(tmp_dir) / f"tts_{i}_sapi.wav")
        final = str(Path(tmp_dir) / f"tts_{i}_44k.wav")
        try:
            asyncio.run(_edge(text, mp3))
            subprocess.run([ffmpeg_path, "-y", "-i", mp3,
                            "-ar", str(sr), "-ac", "1", final],
                           capture_output=True, check=True)
            print(f"    [edge-tts] scene {i}")
        except Exception as e1:
            print(f"    [edge-tts {e1.__class__.__name__}] -> SAPI fallback...")
            try:
                _sapi(text, sapi)
                subprocess.run([ffmpeg_path, "-y", "-i", sapi,
                                "-ar", str(sr), "-ac", "1", final],
                               capture_output=True, check=True)
                print(f"    [SAPI] scene {i}")
            except Exception as e2:
                print(f"    [SAPI failed: {e2}] skipping scene {i}")
                return None
        if not Path(final).exists():
            return None
        with _wave.open(final) as wf:
            raw = wf.readframes(wf.getnframes())
        return np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32767

    with tempfile.TemporaryDirectory() as tmp:
        # Phase 1 — generate all clips and measure their lengths
        clips = []   # list of (preferred_start_sec, np_array | None)
        for i, (pref_start, text) in enumerate(scene_scripts):
            clip = _make_clip(text, tmp, i) if text else None
            clips.append((pref_start, clip))

        # Phase 2 — place clips sequentially; never overlap
        earliest_next = 0.0
        for i, (pref_start, clip) in enumerate(clips):
            if clip is None:
                continue
            actual_start   = max(pref_start, earliest_next)
            clip_dur       = len(clip) / sr
            earliest_next  = actual_start + clip_dur + GAP
            s = int(actual_start * sr); e = min(s + len(clip), n)
            if e <= s:
                print(f"    [narration] WARNING: scene {i} narration dropped entirely — "
                      f"cumulative speech ({actual_start:.1f}s) ran past the video's "
                      f"{total_sec:.1f}s length. Shorten earlier lines or lengthen scenes.")
            elif e - s < len(clip):
                print(f"    [narration] WARNING: scene {i} narration cut off "
                      f"({(len(clip) - (e - s)) / sr:.1f}s trimmed off the end) — "
                      f"cumulative speech ran past the video's {total_sec:.1f}s length.")
            if e > s:
                audio[s:e] += clip[:e-s] * 0.90

    audio  = np.tanh(audio)
    mono16 = (audio * 32767).astype(np.int16)
    stereo = np.column_stack([mono16, mono16])
    with _wave.open(output_wav, "w") as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(sr)
        wf.writeframes(stereo.tobytes())


# ── Encoder ───────────────────────────────────────────────────────────────────

def get_ffmpeg():
    import shutil as _shutil
    sys_ff = _shutil.which("ffmpeg")
    if sys_ff:
        return sys_ff
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise RuntimeError(
            "ffmpeg not found. Install it or run: pip install imageio[ffmpeg]"
        )


def load_video_clip_frames(path, fit_w=None, max_h=None):
    """Decodes an existing mp4 (e.g. a pre-rendered ad reel) into a list of RGB PIL
    Images at the project's FPS, scaled to "contain" within fit_w wide and (if given)
    max_h tall — aspect preserved, whichever dimension is more constraining wins.
    Returns (frames, width, height, duration_sec) — duration is derived from the
    actual decoded frame count, not the container's metadata, so it lines up exactly
    with how many frames get written when the list is passed to encode()."""
    import re
    ffmpeg = get_ffmpeg()
    probe = subprocess.run([ffmpeg, "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Video:.* (\d+)x(\d+)", probe)
    sw, sh = int(m.group(1)), int(m.group(2))
    fit_w = fit_w or sw
    fit_h = round(sh * fit_w / sw / 2) * 2
    if max_h and fit_h > max_h:
        fit_h = max_h - (max_h % 2)
        fit_w = round(sw * fit_h / sh / 2) * 2
    cmd = [ffmpeg, "-i", str(path), "-vf", f"scale={fit_w}:{fit_h}",
           "-r", str(FPS), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    frame_size = fit_w * fit_h * 3
    n = len(raw) // frame_size
    frames = [Image.frombytes("RGB", (fit_w, fit_h), raw[i * frame_size:(i + 1) * frame_size])
              for i in range(n)]
    return frames, fit_w, fit_h, n / FPS


def encode(frames, output, xfade_frames=30, tts_voice="en-US-ChristopherNeural", tts_rate="+20%"):
    """
    frames: list of (Image, hold_sec [, subtitle [, narration]])
      Image can also be a list of Images (one per output frame) to splice in a
      pre-rendered clip via load_video_clip_frames() instead of holding one
      static frame for hold_sec.
      subtitle   (str) — burned into frame as an overlay bar
      narration  (str) — spoken via TTS, placed at scene start
    Output: MP4 with video + background music + TTS narration mixed.
    """
    ffmpeg    = get_ffmpeg()
    total_sec = sum(f[1] for f in frames) + (len(frames) - 1) * xfade_frames / FPS

    # Build narration timeline: (start_sec, text)
    scene_scripts = []
    t_cursor = 0.0
    for i, ft in enumerate(frames):
        narr = ft[3] if len(ft) > 3 else None
        if narr:
            scene_scripts.append((t_cursor + 0.55, narr))
        t_cursor += ft[1] + (xfade_frames / FPS if i < len(frames) - 1 else 0)

    with tempfile.TemporaryDirectory() as tmp:
        frame_dir = Path(tmp) / "frames"
        frame_dir.mkdir()
        idx = 0

        def save(img, subtitle=None):
            nonlocal idx
            out = burn_subtitle(img, subtitle) if subtitle else img
            out.save(str(frame_dir / f"{idx:06d}.png"))
            idx += 1

        for i, ft in enumerate(frames):
            img      = ft[0]
            hold_sec = ft[1]
            subtitle = ft[2] if len(ft) > 2 else None
            if isinstance(img, list):
                # Spliced-in clip (load_video_clip_frames) — one distinct image per
                # output frame rather than one static image held for hold_sec.
                n = int(hold_sec * FPS)
                seq = (img + [img[-1]] * n)[:n]
                for fr in seq:
                    save(fr, subtitle)
                cur_last = seq[-1]
            else:
                for _ in range(int(hold_sec * FPS)):
                    save(img, subtitle)
                cur_last = img
            if i < len(frames) - 1:
                next_img = frames[i + 1][0]
                next_first = next_img[0] if isinstance(next_img, list) else next_img
                next_sub = frames[i + 1][2] if len(frames[i + 1]) > 2 else None
                for t in range(xfade_frames):
                    blend = Image.blend(cur_last, next_first, t / xfade_frames)
                    save(blend, subtitle if t < xfade_frames // 2 else next_sub)

        print(f"  Rendering {idx} frames ({total_sec:.1f}s)...")

        music_wav = str(Path(tmp) / "music.wav")
        narr_wav  = str(Path(tmp) / "narration.wav")

        print("  Generating background music...")
        generate_music(total_sec + 0.5, music_wav)

        print("  Generating narration (TTS)...")
        generate_narration(scene_scripts, total_sec + 0.5, narr_wav, ffmpeg,
                           voice=tts_voice, rate=tts_rate)

        # Mix: narration full volume, music at 18 % under it
        cmd = [
            ffmpeg, "-y",
            "-framerate", str(FPS),
            "-i", str(frame_dir / "%06d.png"),
            "-i", music_wav,
            "-i", narr_wav,
            "-filter_complex",
            "[1:a]volume=0.18[music];[2:a]volume=1.0[narr];"
            "[music][narr]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast",
            "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart",
            output,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print("ffmpeg stderr:\n", res.stderr[-3000:])
            raise RuntimeError(f"ffmpeg failed (exit {res.returncode})")

    print(f"  Saved -> {output}")


# ── Video builders ─────────────────────────────────────────────────────────────

def build_sp500_movers(data, output):
    sp500   = [r for r in data["data"] if r.get("InSP500")]
    date    = data["date"]
    gainers = sorted(sp500, key=lambda r: r.get("PriceChange1D") or -9999, reverse=True)[:10]

    encode([
        (scene_title("S&P 500", "Top Movers Today", date,
                     "Biggest single-day price changes in the S&P 500"), 4,
         "S&P 500 top gainers — powered by Baizora",
         f"S&P 500 top movers for {date}, from Baizora."),
        (scene_movers_table(f"S&P 500 — Top 10 Gainers  ({date})", gainers, date), 14,
         "Ranked by today's 1-day price gain — price, volume, and 1-year return shown",
         f"{_narrate_movers(gainers, 'gainers')}"),
        (scene_sparklines(f"S&P 500 Gainers — 1-Year Trend  ({date})", gainers, date), 12,
         "1-year price trend for each top gainer — bright dot marks today",
         "One-year price charts for today's top S&P 500 gainers. "
         "Bright dot marks today's price. "
         "Want to know more about short and mid term price and volume data? "
         "Visit baizora dot com."),
        (scene_screenshot(_SS_EN), 2),
        (scene_outro(date), 5,
         "For informational purposes only. Not financial advice. | baizora.com"),
    ], output)


def build_nasdaq_movers(data, output):
    ndq     = [r for r in data["data"] if r.get("InNASDAQ100")]
    date    = data["date"]
    gainers = sorted(ndq, key=lambda r: r.get("PriceChange1D") or -9999, reverse=True)[:10]

    encode([
        (scene_title("Nasdaq-100", "Top Movers Today", date,
                     "Biggest single-day price changes in the Nasdaq-100"), 4,
         "Nasdaq-100 top gainers — powered by Baizora",
         f"Nasdaq-100 top movers for {date}, from Baizora."),
        (scene_movers_table(f"Nasdaq-100 — Top 10 Gainers  ({date})", gainers, date), 14,
         "Ranked by today's 1-day price gain — price, volume, and 1-year return shown",
         f"{_narrate_movers(gainers, 'gainers')}"),
        (scene_sparklines(f"Nasdaq-100 Gainers — 1-Year Trend  ({date})", gainers, date), 12,
         "1-year price trend for each top gainer — bright dot marks today",
         "One-year price charts for today's Nasdaq-100 top gainers. "
         "Bright dot marks today's price. "
         "Want to know more about short and mid term price and volume data? "
         "Visit baizora dot com."),
        (scene_screenshot(_SS_EN), 2),
        (scene_outro(date), 5,
         "For informational purposes only. Not financial advice. | baizora.com"),
    ], output)


_VOLUME_OPENERS_EN = [
    "Something caught the market's attention today — and volume was the tell.",
    "When volume spikes this sharply, it usually means something is happening. Here's what stood out today.",
    "Which large-cap stocks saw trading activity far outside the norm today? Let's find out.",
    "Unusual volume is often the first clue before a major move. Today's biggest spikes across the S&P 500 and Nasdaq-100.",
    "Every day the market leaves clues in the volume data. Today, these stocks stood out.",
    "Is smart money moving? Today's largest volume surges in large-cap stocks might offer a hint.",
    "What was the market reacting to today? Here are the stocks where volume told the story.",
    "Volume doesn't lie. Today, these S&P 500 and Nasdaq-100 stocks saw trading activity well above their 21-day average.",
    "When a stock's volume spikes beyond three times its average, something is usually going on. Today's standouts, from Baizora.",
    "The quietest stocks can suddenly roar — today, these large-cap names made noise in the volume data.",
]

_VOLUME_OPENERS_CN = [
    "今天，哪些股票的成交量让市场侧目？",
    "当成交量突然暴增，往往意味着有事情正在发生。今天，这些股票引发了关注。",
    "今天的大盘里，有几只股票的成交量远超寻常——背后究竟发生了什么？",
    "是什么让这些股票今天的交易量远超平均水平？让我们来看看。",
    "聪明的资金在悄悄移动吗？今天成交量最异常的大盘股就是这些。",
    "市场上有些信号，只有看成交量才能发现。今天，这些股票的数据值得关注。",
    "今日盘后，有几只大盘股的成交量异常突出——这是偶然，还是有所预兆？",
    "成交量的背后，往往藏着市场情绪的变化。今天这些股票告诉了我们什么？",
    "如果市场在说话，今天说话最响亮的，是这几只股票的成交量。",
    "今天的S&P 500和纳斯达克100中，出现了一些不寻常的交易量信号。",
]

_BREAKOUT_OPENERS_EN = [
    "These stocks spent months under pressure — and today, they finally broke through their one-year high.",
    "Breaking a one-year high after a real pullback is one of the cleanest signals in the market.",
    "What happens when a stock corrects over twenty percent, then climbs back to a new one-year high? You're looking at it.",
    "These stocks peaked, pulled back hard, and today they crossed above their one-year high for the first time.",
    "The setup: a peak, a twenty-percent pullback, and then a breakout to a new one-year high. Here are today's names.",
    "Not all breakouts are equal. These stocks had a real correction first — then came back to set a one-year high.",
    "Some traders wait all year for exactly this setup. Here are the large-caps triggering it right now.",
    "If a stock can fall over twenty percent and still come back to a new one-year high, the market is saying something.",
    "Months of selling pressure, then today — a one-year high breakout. Here are the names making the move.",
    "Today's rare signal: large-cap stocks crossing a one-year high after a twenty-percent-plus pullback.",
]

_BREAKOUT_OPENERS_CN = [
    "这些股票在年内高点受压已久——今天，它们终于突破了。",
    "一年新高突破，叠加真实的回调，是市场中最清晰的信号之一。",
    "一只股票回调超过二十个百分点，又重新创下一年新高，这意味着什么？答案就在眼前。",
    "这些股票曾经历大幅回调，如今在过去两周内首次突破了一年高点。",
    "模式很简单：高点，回调，然后突破。今天触发这个信号的大盘股就是它们。",
    "不是所有突破都一样。这些股票经历了真实的深度回调，然后强势回归。",
    "有些交易者等待这种信号等了整整一年。今天，大盘股中出现了。",
    "一只股票能跌超二十个百分点后重创一年新高，市场在告诉我们一些事情。",
    "多个月的抛压，然后今天——一年新高突破。这就是今日的名单。",
    "今日罕见信号：大盘股在经历二十个百分点以上的真实回调后，突破一年高点。",
]


def _compute_breakouts(all_rows, tf, lookback_days=10):
    """Return enriched rows for stocks whose N-month peak was first crossed in the
    past `lookback_days` trading days (default 10 = 2 weeks, the long-form video's
    behavior, unchanged). generate_shorts.py's Wednesday Short passes 5 (1 week)
    instead — that category runs weekly, and a 2-week lookback risked re-selecting
    the same breakout ticker two weeks running.

    Criteria:
      - Previous high set in the older half of the target spark window
      - From that peak until `lookback_days` trading days ago: no day reached 98%
        of peak (true resistance)
      - Today's price at or above the previous peak
      - Pullback from peak to trough >= tf["min_drawdown"]
    """
    spark_days   = tf.get("spark_days")   # None = full 1Y
    min_drawdown = tf.get("min_drawdown", 10)
    seen, out = set(), []
    for row in all_rows:
        ticker = row.get("Ticker", "")
        if ticker in seen:
            continue
        seen.add(ticker)
        full_spark = row.get("Spark1Y")
        if not full_spark or len(full_spark) < 30:
            continue

        # Slice to target window; keep full_spark for price calibration
        spark  = full_spark[-spark_days:] if spark_days and len(full_spark) > spark_days else full_spark
        offset = len(full_spark) - len(spark)   # days trimmed from start
        if len(spark) < 15:
            continue

        price     = row.get("Price") or 0
        change_1y = row.get("1YPriceChange") or 0
        s0, s1    = full_spark[0], full_spark[-1]
        if abs(s0 - s1) < 0.001:
            continue
        price_1y_ago = price / (1 + change_1y / 100)
        R            = (price_1y_ago - price) / (s0 - s1)
        min_price    = price - s1 * R

        def actual(s): return min_price + s * R

        n, half  = len(spark), len(spark) // 2
        peak_val = max(spark[:half])
        peak_idx = spark[:half].index(peak_val)

        # Strict: from peak until the lookback cutoff, no day hit 98% of peak
        before_cutoff = spark[peak_idx + 1 : -lookback_days]
        if before_cutoff and max(before_cutoff) >= peak_val * 0.98:
            continue

        # Today must be at or above the previous peak
        if spark[-1] < peak_val * 0.98:
            continue

        peak_price      = actual(peak_val)
        full_peak_idx   = offset + peak_idx
        months_ago      = (len(full_spark) - 1 - full_peak_idx) / 21
        post_peak       = spark[peak_idx:-lookback_days]
        trough_val      = min(post_peak) if post_peak else peak_val
        drawdown        = (peak_price - actual(trough_val)) / peak_price * 100 if peak_price else 0

        if drawdown >= min_drawdown:
            enriched = dict(row)
            enriched["_peak_price"] = peak_price
            enriched["_drawdown"]   = drawdown
            enriched["_months_ago"] = months_ago
            enriched["_peak_idx"]   = full_peak_idx   # index into full Spark1Y for sparkline
            out.append(enriched)
    return out


def _compute_6m_breakouts(all_rows):
    """Legacy wrapper — uses 1Y window with 20% drawdown (original Wednesday behaviour)."""
    return _compute_breakouts(all_rows, WEDNESDAY_TF_ROTATION[-1])


def _narrate_breakout(breakouts, tf=None):
    label = tf["label_en"].lower() if tf else "one-year"
    parts = []
    for b in breakouts[:3]:
        ticker    = b.get("Ticker", "")
        chg       = b.get("PriceChange1D") or 0
        pullback  = b.get("_drawdown", 0)
        direction = "up" if chg >= 0 else "down"
        parts.append(f"{ticker} {direction} {abs(chg):.1f} percent today, after a {pullback:.0f} percent pullback")
    n = len(parts)
    if n >= 3:
        return (f"Recent {label} high breakouts — all first crossed within the past two weeks: "
                f"{parts[0]}. {parts[1]}. And {parts[2]}.")
    elif n == 2:
        return (f"Recent {label} high breakouts — both first crossed within the past two weeks: "
                f"{parts[0]}. And {parts[1]}.")
    elif n == 1:
        return (f"A recent {label} high breakout, first crossed within the past two weeks: {parts[0]}.")
    return ""


def build_6m_breakout(data, output):
    date      = data["date"]
    tf        = _wednesday_tf(date)
    breakouts = _compute_breakouts(data["data"], tf)
    breakouts.sort(key=lambda x: x.get("PriceChange1D") or -9999, reverse=True)
    top       = breakouts[:3]

    if not top:
        print(f"No {tf['label_en']} breakout stocks found today, skipping.")
        return

    label    = tf["label_en"]
    window   = tf["window_en"]
    n        = len(top)
    subtitle = (f"Top {n}" if n > 1 else "Today's") + " — Sorted by 1D Price Change"
    spark_narr = (
        f"Here {'are' if n > 1 else 'is'} the one-year price chart{'s' if n > 1 else ''} "
        f"for {'these' if n > 1 else 'this'} recent breakout{'s' if n > 1 else ''}. "
        f"The gold marker shows the {label.lower()} high that was crossed in the past two weeks, "
        "and the blue dot marks today's price."
    )

    encode([
        (scene_title(f"{label} High Breakouts", "S&P 500  ·  Nasdaq-100", date,
                     f"First crossed in the past 2 weeks · {tf['min_drawdown']}%+ real pullback"), 4,
         f"Large-cap stocks breaking above their {label.lower()} high for the first time in the past 2 weeks",
         random.choice(_BREAKOUT_OPENERS_EN) +
         " Every Wednesday on this channel, we track large-caps breaking above their multi-month highs."
         " Subscribe to follow these breakouts every week."),
        (scene_breakout_table(top, date, tf=tf), 24,
         subtitle,
         _narrate_breakout(top, tf=tf)),
        (scene_breakout_sparklines(top, date,
                                   peak_label=tf["high_hdr"]), 12,
         f"1-year price trend — gold marker shows the {label.lower()} high just crossed | baizora.com",
         spark_narr),
        (scene_1y_sort_promo(data, date), 5,
         "Sort by any timeframe — 2W through 1Y — to find price leaders across S&P 500 & Nasdaq-100",
         "On Baizora, you can see how today's breakout stocks compare across every timeframe — "
         "from two weeks to one year. Sort by any column to find the leaders instantly. "
         "Visit baizora dot com."),
        (scene_screenshot(_SS_EN), 2),
        (scene_outro(date), 5,
         "For informational purposes only. Not financial advice. | baizora.com"),
    ], output)


def _narrate_breakout_cn(breakouts, tf=None):
    label_cn = tf["label_cn"] if tf else "一年"
    parts = []
    for b in breakouts[:3]:
        ticker    = b.get("Ticker", "")
        chg       = b.get("PriceChange1D") or 0
        pullback  = b.get("_drawdown", 0)
        direction = "今日上涨" if chg >= 0 else "今日下跌"
        parts.append(f"{ticker}{direction}{abs(chg):.1f}%，此前回调{pullback:.0f}%")
    n = len(parts)
    if n >= 3:
        return (f"近期{label_cn}新高突破——均在过去两周内首次突破："
                f"{parts[0]}。{parts[1]}。{parts[2]}。")
    elif n == 2:
        return (f"近期{label_cn}新高突破——均在过去两周内首次突破："
                f"{parts[0]}。{parts[1]}。")
    elif n == 1:
        return f"近期{label_cn}新高突破，过去两周内首次突破：{parts[0]}。"
    return ""


def build_6m_breakout_cn(data, output):
    date      = data["date"]
    tf        = _wednesday_tf(date)
    breakouts = _compute_breakouts(data["data"], tf)
    breakouts.sort(key=lambda x: x.get("PriceChange1D") or -9999, reverse=True)
    top       = breakouts[:3]

    if not top:
        print(f"今日无{tf['label_cn']}新高突破股票，跳过。")
        return

    label_cn   = tf["label_cn"]
    window_cn  = tf["window_cn"]
    title_cn   = tf["title_cn"]
    n          = len(top)
    spark_narr = (
        f"以下是今日{'前' + str(n) + '只' if n > 1 else ''}突破{label_cn}新高的股票年度走势图。"
        f"金色标记为此前{label_cn}高点，蓝色圆点为今日价格。"
    )

    encode([
        (scene_title_cn(title_cn, "S&P 500  ·  纳斯达克100", date,
                        f"过去两周内首次突破 · 真实回调超{tf['min_drawdown']}%"), 4,
         f"大盘股在经历{tf['min_drawdown']}%以上真实回调后，过去两周内首次突破{label_cn}高点",
         random.choice(_BREAKOUT_OPENERS_CN) +
         "本频道每周三追踪突破多月高点的大盘股。订阅我们，每周跟进突破机会。"),
        (scene_breakout_table_cn(top, date, tf=tf), 27,
         f"按今日涨幅排序——在过去两周内突破{label_cn}高点",
         _narrate_breakout_cn(top, tf=tf)),
        (scene_breakout_sparklines(top, date,
                                   peak_label=tf["peak_label_cn"],
                                   title=f"{title_cn} — 年度走势  ({date})"), 12,
         f"年度价格走势 — 金色标记为突破的{label_cn}高点 | baizora.com",
         spark_narr),
        (scene_1y_sort_promo_cn(data, date), 5,
         "按任意时间维度排序 — 2周至1年 — 即时筛选S&P 500和纳斯达克100领涨股",
         f"在贝佐拉，可查看这些突破股票在每个时间维度的表现——从两周到一年。"
         "按任意列排序，即时发现全市场领涨股。访问baizora.com。"),
        (scene_screenshot(_SS_CN), 2),
        (scene_outro_cn(date), 5,
         "仅供参考，不构成投资建议 | baizora.com"),
    ], output, tts_voice="zh-CN-YunxiNeural")


def build_volume_spikes(data, output):
    date   = data["date"]
    spikes = sorted(data["data"],
                    key=lambda r: r.get("VolumeChange1D") or -9999, reverse=True)[:10]

    encode([
        (scene_title("Volume Spikes", "S&P 500  ·  Nasdaq-100", date,
                     "Unusual Activity — Highest 1-Day Volume Surge vs 21-Day Average"), 4,
         "Unusual volume can signal institutional activity, earnings reactions, or breaking news",
         random.choice(_VOLUME_OPENERS_EN) +
         " Every Monday on this channel, we cover unusual volume activity across the S&P 500 and Nasdaq-100."
         " Subscribe so you never miss a week."),
        (scene_volume_spikes(spikes, date), 24,
         "VOL/MA21 = today's volume vs 21-day average  |  values above 3x highlighted in gold",
         f"{_narrate_volume(spikes)}"),
        (scene_top3_sparklines(
            f"Volume Spike Leaders — 1-Year Trend  ({date})", spikes, date,
            "Want to see more? Visit baizora.com for the full S&P 500 & Nasdaq-100 analysis."), 5,
         "Top 3 volume spike leaders — 1-year trend | baizora.com for the full list",
         "Here are the one-year price trends for the top three volume spike stocks today."),
        (scene_vol_sort_promo(data, date), 5,
         "Sort by any period — 1D through 1Y — to find volume spikes across S&P 500 & Nasdaq-100",
         "On Baizora, access volume spike data across every timeframe — sort by any column. "
         "Visit baizora dot com."),
        (scene_screenshot(_SS_EN), 2),
        (scene_outro(date), 5,
         "For informational purposes only. Not financial advice. | baizora.com"),
    ], output)


_VOL_PEAK_OPENERS_EN = [
    "When a stock records its biggest trading day of the past {window}, the market is paying attention.",
    "Volume is the market's heartbeat — and today, these stocks are beating harder than any day in the past {window}.",
    "What does it look like when a stock sees its highest trading volume in {window}? This.",
    "Today these large-caps aren't just busy — they're having their busiest trading day in {window}.",
    "Unusual volume is interesting. Record-breaking volume over {window} is something else entirely.",
    "Something happened today that hasn't happened in {window} for these stocks — their volume broke the record.",
    "The biggest trading days tell stories. Today's {window} volume records in the S&P 500 and Nasdaq-100.",
    "Not every high-volume day is equal. These are the stocks setting their {window} volume record right now.",
    "When volume breaks a {window} record, institutions are moving. Here are today's examples.",
    "Today's standout signal: large-cap stocks recording their highest single-day volume of the past {window}.",
]


def _narrate_vol_peak(rows, tf=None):
    key    = tf["vol_chg_key"] if tf else "1YMaxVolumeChange"
    label  = tf["label_en"].lower() if tf else "1-year"
    window = tf["window_en"] if tf else "twelve months"
    top = rows[:3]
    parts = []
    for r in top:
        ticker  = r.get("Ticker", "")
        vol_chg = r.get(key) or 0
        parts.append(f"{ticker} with a volume surge of {abs(vol_chg):.0f} percent")
    n = len(parts)
    if n >= 3:
        return (f"Today's {label} volume records: {parts[0]}, {parts[1]}, and {parts[2]}. "
                f"Now let's look at their price charts.")
    elif n == 2:
        return (f"Today's {label} volume records: {parts[0]} and {parts[1]}. "
                f"Now let's look at their price charts.")
    elif n == 1:
        return (f"Today's {label} volume record: {parts[0]}. "
                f"Now let's look at the price chart.")
    return ""


def build_1y_vol_peak(data, output):
    date  = data["date"]
    tf    = _thursday_tf(date)
    seen  = set()
    peaks = []
    for r in data["data"]:
        t = r.get("Ticker", "")
        if t in seen:
            continue
        seen.add(t)
        if r.get(tf["vol_day_key"]) == 0:
            peaks.append(r)
    peaks.sort(key=lambda r: r.get(tf["vol_chg_key"]) or 0, reverse=True)
    top = peaks[:3]

    if not top:
        print(f"No {tf['label_en']} volume peak stocks found today, skipping.")
        return

    label  = tf["label_en"]
    window = tf["window_en"]
    encode([
        (scene_title(tf["title_en"], "S&P 500  ·  Nasdaq-100", date,
                     tf["subtitle_en"]), 4,
         f"Large-cap stocks setting a new {label.lower()} volume record today",
         random.choice(_VOL_PEAK_OPENERS_EN).format(window=window) +
         f" Every Thursday on this channel, we rotate through different timeframes to find"
         f" stocks recording their biggest single-day volume — this week, the past {window}."
         " Subscribe so you never miss this signal."),
        (scene_volume_spikes(top, date), 24,
         "VOL/MA21 = today's volume vs 21-day average  |  values above 3x highlighted in gold",
         _narrate_vol_peak(top, tf)),
        (scene_top3_sparklines(
            f"{label} Volume Records — Price Trend  ({date})", top, date,
            "Want to see more? Visit baizora.com for the full S&P 500 & Nasdaq-100 analysis."), 5,
         f"{label} volume record stocks — 1-year price trend | baizora.com",
         f"Here are the one-year price trends for today's {label.lower()} record-volume stocks."),
        (scene_vol_sort_promo(data, date, tf), 5,
         f"Sort by any period — 1M through 1Y — to compare {label} volume records across S&P 500 & Nasdaq-100",
         f"On Baizora, see how today's {label.lower()} volume record stocks compare across every timeframe — "
         "from 1 month to 1 year. Sort by any column to find the biggest volume movers. "
         "Visit baizora dot com."),
        (scene_screenshot(_SS_EN), 2),
        (scene_outro(date), 5,
         "For informational purposes only. Not financial advice. | baizora.com"),
    ], output)


_VOL_PEAK_OPENERS_CN = [
    "当一只股票创下过去{window}最大单日成交量，市场正在释放重要信号。",
    "成交量是市场的心跳——今天，这些股票的心跳比过去{window}都要强劲。",
    "什么样的成交量算是真正的异动？突破{window}记录，就是答案。",
    "今天，这些大盘股不只是交易活跃——而是创下了过去{window}的最高成交量。",
    "普通的大成交量值得关注，创{window}纪录的成交量则意味着完全不同的事情。",
    "今天发生了一件{window}以来从未有过的事——这些股票的成交量突破了历史记录。",
    "最大的成交日往往在讲述一个故事。今天，这些S&P 500和纳斯达克100股票刷新了{window}成交量记录。",
    "不是所有的大成交量都相同。这些股票正在创下过去{window}的成交量记录。",
    "当成交量打破{window}纪录，机构资金正在行动。今天的案例就在这里。",
    "今日最值得关注的信号：这些大盘股正在创下过去{window}的最大单日成交量。",
]


def _narrate_vol_peak_cn(rows, tf=None):
    key      = tf["vol_chg_key"] if tf else "1YMaxVolumeChange"
    label_cn = tf["label_cn"] if tf else "年度"
    window_cn = tf["window_cn"] if tf else "十二个月"
    top = rows[:3]
    parts = []
    for r in top:
        ticker  = r.get("Ticker", "")
        vol_chg = r.get(key) or 0
        parts.append(f"{ticker}，成交量放大{abs(vol_chg):.0f}%")
    n = len(parts)
    if n >= 3:
        return (f"今日{label_cn}成交量记录：{parts[0]}；{parts[1]}；{parts[2]}。"
                f"下面来看它们的价格走势。")
    elif n == 2:
        return (f"今日{label_cn}成交量记录：{parts[0]}；{parts[1]}。"
                f"下面来看它们的价格走势。")
    elif n == 1:
        return (f"今日{label_cn}成交量记录：{parts[0]}。"
                f"下面来看价格走势。")
    return ""


def build_1y_vol_peak_cn(data, output):
    date  = data["date"]
    tf    = _thursday_tf(date)
    seen  = set()
    peaks = []
    for r in data["data"]:
        t = r.get("Ticker", "")
        if t in seen:
            continue
        seen.add(t)
        if r.get(tf["vol_day_key"]) == 0:
            peaks.append(r)
    peaks.sort(key=lambda r: r.get(tf["vol_chg_key"]) or 0, reverse=True)
    top = peaks[:3]

    if not top:
        print(f"今日无{tf['label_cn']}成交量记录股票，跳过。")
        return

    label_cn  = tf["label_cn"]
    window_cn = tf["window_cn"]
    encode([
        (scene_title_cn(tf["title_cn"], "S&P 500  ·  纳斯达克100", date,
                        tf["subtitle_cn"]), 6,
         f"S&P 500 + 纳斯达克100 大盘股创{label_cn}成交量记录 — 贝佐拉",
         random.choice(_VOL_PEAK_OPENERS_CN).format(window=window_cn) +
         f"本频道每周四轮换不同时间维度，报道创下阶段最大单日成交量的大盘股——本周聚焦过去{window_cn}。"
         "订阅我们，不错过任何重要信号。"),
        (scene_volume_spikes_cn(top, date), 24,
         "量/MA21 = 今日成交量 / 21日均量  |  超过3倍的用金色高亮显示",
         _narrate_vol_peak_cn(top, tf)),
        (scene_top3_sparklines(
            f"{label_cn}成交量记录 — 年度价格走势  ({date})", top, date,
            "想了解更多？访问baizora.com获取S&P 500和纳斯达克100完整分析。"), 12,
         f"{label_cn}成交量记录前三股票的一年走势 | 更多数据请访问baizora.com",
         f"这是今日创{label_cn}成交量记录的前三名股票的年度走势图。"
         "每条曲线展示了过去一年的完整价格轨迹，帮助您判断成交量异动背后的价格趋势。"),
        (scene_vol_sort_promo_cn(data, date, tf), 5,
         "按任意时间维度排序 — 1月至1年 — 即时发现S&P 500和纳斯达克100全市场最大成交量异动",
         "在贝佐拉，可查看股票在各时间维度的成交量表现——从一个月到一年。按任意列排序。访问baizora.com。"),
        (scene_screenshot(_SS_CN), 2),
        (scene_outro_cn(date), 5,
         "仅供参考，不构成投资建议 | baizora.com"),
    ], output, tts_voice="zh-CN-YunxiNeural")


# ── Index Spotlight (new member performance) ──────────────────────────────────

_SPOTLIGHT_OPENERS_EN = [
    "When a stock joins the S&P 500 or Nasdaq-100, something shifts — and not just in the portfolio.",
    "Index membership doesn't just recognize the past. It can shape what comes next.",
    "A new index member isn't just a label — it's a guarantee that trillions in passive money need to own this stock.",
    "The moment a stock joins a major index, every fund that tracks it has to buy. That's not speculation — that's scheduled demand.",
    "Joining the S&P 500 or Nasdaq-100 is more than a milestone. Here's how this one is writing its next chapter.",
    "What happens after a large-cap stock earns its place in the index? The data might surprise you.",
    "Index additions are often signals before the market has fully priced in what comes next.",
    "Passive funds don't predict the future — but when they all buy the same stock, they can help create it.",
    "There's a reason investors pay attention when a stock joins the S&P 500 or Nasdaq-100. Here's one to watch.",
    "Not every index addition plays out the same way. Here's how this recent member has done since joining.",
]


def _parse_date(s):
    """Parse a date string in YYYY-MM-DD or MM/DD/YYYY format."""
    s = s.strip()
    if '/' in s:
        try:
            return datetime.datetime.strptime(s, "%m/%d/%Y").date()
        except ValueError:
            pass
    return datetime.date.fromisoformat(s)


def _price_from_spark(row, spark_idx):
    spark = row.get("Spark1Y") or []
    if len(spark) < 2:
        return None
    price = row.get("Price") or 0
    pc1y  = row.get("1YPriceChange") or 0
    denom = 1 + pc1y / 100
    if abs(denom) < 1e-9:
        return price
    price_1y_ago = price / denom
    sd = spark[0] - spark[-1]
    if abs(sd) < 1e-9:
        return price
    R         = (price_1y_ago - price) / sd
    min_price = price - spark[-1] * R
    return min_price + spark[spark_idx] * R


def _get_new_members(data):
    changes_file = ROOT_DIR / "data" / "index_changes.json"
    if not changes_file.exists():
        return []
    ic         = json.load(open(changes_file))
    scan_date  = data["date"]
    ticker_map = {r["Ticker"]: r for r in data["data"]}

    seen = {}
    for entry in ic["entries"]:
        jdate = entry["date"]
        for idx_key in ("nasdaq100", "sp500"):
            for t in entry[idx_key].get("added", []):
                if t not in seen or jdate > seen[t]["join_date"]:
                    seen[t] = {"ticker": t, "join_date": jdate, "index": idx_key}

    members = []
    for t, info in seen.items():
        if t not in ticker_map:
            continue
        row   = ticker_map[t]
        spark = row.get("Spark1Y") or []
        if len(spark) < 2:
            continue
        try:
            d1 = _parse_date(info["join_date"])
        except ValueError:
            print(f"  [skip] bad join date for {t}: {info['join_date']!r}")
            continue
        d2 = datetime.date.fromisoformat(scan_date)
        if not (0 < (d2 - d1).days <= 730):
            print(f"  [skip] {t} join date out of range: {info['join_date']} ({(d2-d1).days}d)")
            continue
        bdays = 0
        cur   = d1
        while cur < d2:
            cur += datetime.timedelta(days=1)
            if cur.weekday() < 5:
                bdays += 1
        spark_idx = max(0, min(len(spark) - 1, len(spark) - 1 - bdays))
        jpr       = _price_from_spark(row, spark_idx)
        if not jpr or jpr <= 0:
            continue
        cpr    = row.get("Price") or 0
        perf   = (cpr - jpr) / jpr * 100
        pc1y   = row.get("1YPriceChange") or 0
        denom  = 1 + pc1y / 100
        p1yago = cpr / denom if abs(denom) > 1e-9 else cpr
        sd     = spark[0] - spark[-1]
        if abs(sd) > 1e-9:
            R         = (p1yago - cpr) / sd
            base_price = cpr - spark[-1] * R
            post_actual = [base_price + spark[i] * R for i in range(spark_idx, len(spark))]
            max_price   = max(post_actual)
            trough_price = min(post_actual)
            max_gain_idx = spark_idx + post_actual.index(max_price)
            max_loss_idx = spark_idx + post_actual.index(trough_price)
        else:
            max_price, trough_price = jpr, jpr
            max_gain_idx = max_loss_idx = spark_idx
        max_gain = (max_price - jpr) / jpr * 100
        max_loss = (trough_price - jpr) / jpr * 100
        members.append({
            "ticker":              t,
            "row":                 row,
            "join_date":           info["join_date"],
            "index_name":          "Nasdaq-100" if info["index"] == "nasdaq100" else "S&P 500",
            "bdays_since_join":    bdays,
            "spark_idx":           spark_idx,
            "join_price":          jpr,
            "perf_since_join":     perf,
            "max_gain_since_join": max_gain,
            "max_loss_since_join": max_loss,
            "max_gain_idx":        max_gain_idx,
            "max_loss_idx":        max_loss_idx,
        })
    return members


def scene_index_spotlight(member, scan_date):
    img, draw = new_frame()
    row    = member["row"]
    ticker = member["ticker"]
    cname  = row.get("CompanyName", ticker)
    idx    = member["index_name"]
    jdate  = member["join_date"]
    bdays  = member["bdays_since_join"]
    perf     = member["perf_since_join"]
    max_gain = member.get("max_gain_since_join", perf)
    jp       = member["join_price"]
    cp       = row.get("Price") or 0
    pc1d     = row.get("PriceChange1D")
    sector   = row.get("Sector", "")

    top_bar(draw, f"Index Spotlight — {ticker}  ({scan_date})", scan_date)

    LP_X = 72
    f_lbl  = load_font(17, mono=True)
    f_sml  = load_font(22)
    f_med  = load_font(30)
    f_cname = load_font(44, bold=True)
    f_tkr  = load_font(68, mono=True)

    # Company name (truncated)
    cname_s = cname if len(cname) <= 28 else cname[:25] + "..."
    draw.text((LP_X, 114), "COMPANY", font=f_lbl, fill=DIM)
    draw.text((LP_X, 138), cname_s, font=f_cname, fill=WHITE)

    draw.text((LP_X, 200), ticker, font=f_tkr, fill=WHITE)

    # Index badge pill
    f_badge   = load_font(20, mono=True)
    badge_txt = idx
    bw        = tw(draw, badge_txt, f_badge) + 24
    draw.rectangle([LP_X, 286, LP_X + bw, 318], fill=ELECTRIC)
    draw.text((LP_X + 12, 293), badge_txt, font=f_badge, fill=WHITE)

    if sector:
        draw.text((LP_X, 342), "SECTOR", font=f_lbl, fill=DIM)
        draw.text((LP_X, 364), sector, font=f_med, fill=MUTED)

    jdate_fmt = datetime.date.fromisoformat(jdate).strftime("%b %d, %Y")
    draw.text((LP_X, 416), "JOINED", font=f_lbl, fill=DIM)
    draw.text((LP_X, 438), f"{bdays} trading days ago joined {idx}", font=f_sml, fill=WHITE)
    draw.text((LP_X, 476), jdate_fmt, font=load_font(20), fill=DIM)

    # Vertical divider
    draw.line([(960, 110), (960, H - 68)], fill=BORDER)

    # Right panel — performance hero
    RP_X = 1000
    draw.text((RP_X, 114), "PERFORMANCE SINCE JOINING", font=f_lbl, fill=DIM)

    perf_color = GREEN if perf >= 0 else RED
    sign       = "+" if perf >= 0 else ""
    # Scale font for very large numbers
    perf_str   = f"{sign}{perf:.1f}%"
    f_perf     = load_font(90 if abs(perf) < 1000 else 60, bold=True)
    draw.text((RP_X, 142), perf_str, font=f_perf, fill=perf_color)

    hline(draw, 308, x0=RP_X, x1=W - 60)

    f_mv = load_font(30, mono=True)
    draw.text((RP_X, 326), "PRICE AT JOIN", font=f_lbl, fill=DIM)
    draw.text((RP_X, 348), f"${jp:,.2f}", font=f_mv, fill=MUTED)

    draw.text((RP_X, 402), "CURRENT PRICE", font=f_lbl, fill=DIM)
    draw.text((RP_X, 424), f"${cp:,.2f}", font=f_mv, fill=WHITE)

    draw.text((RP_X, 478), "TODAY", font=f_lbl, fill=DIM)
    draw.text((RP_X, 500), pct_str(pc1d), font=f_mv, fill=pct_color(pc1d))

    mg_sign = "+" if max_gain >= 0 else ""
    mg_str  = f"{mg_sign}{max_gain:.1f}%"
    draw.text((RP_X, 554), "PEAK GAIN SINCE JOIN", font=f_lbl, fill=DIM)
    draw.text((RP_X, 576), mg_str, font=load_font(30, mono=True), fill=GOLD_LIGHT)

    hline(draw, H - 68)
    centered(draw, H - 56,
             "Track all S&P 500 & Nasdaq-100 index changes at baizora.com",
             load_font(22, bold=True), ELEC_BRIGHT)
    return img


def scene_index_spotlight_cn(member, scan_date):
    """CN version of the spotlight card — all labels in Chinese."""
    img, draw = new_frame()
    row    = member["row"]
    ticker = member["ticker"]
    cname  = row.get("CompanyName", ticker)
    idx    = member["index_name"]
    idx_cn = "纳斯达克100" if "Nasdaq" in idx else "标普500"
    jdate  = member["join_date"]
    bdays  = member["bdays_since_join"]
    perf     = member["perf_since_join"]
    max_gain = member.get("max_gain_since_join", perf)
    jp       = member["join_price"]
    cp       = row.get("Price") or 0
    pc1d     = row.get("PriceChange1D")
    sector   = row.get("Sector", "")

    top_bar(draw, f"指数聚焦 — {ticker}  ({scan_date})", scan_date)

    LP_X   = 72
    f_lbl    = load_font_cn(17)
    f_sml    = load_font_cn(22)
    f_med    = load_font(30)
    f_med_cn = load_font_cn(30)
    f_cname  = load_font(44, bold=True)
    f_tkr    = load_font(68, mono=True)

    cname_s = cname if len(cname) <= 28 else cname[:25] + "..."
    draw.text((LP_X, 114), "公司", font=f_lbl, fill=DIM)
    draw.text((LP_X, 138), cname_s, font=f_cname, fill=WHITE)

    draw.text((LP_X, 200), ticker, font=f_tkr, fill=WHITE)

    f_badge   = load_font_cn(20)
    bw        = tw(draw, idx_cn, f_badge) + 24
    draw.rectangle([LP_X, 286, LP_X + bw, 318], fill=ELECTRIC)
    draw.text((LP_X + 12, 293), idx_cn, font=f_badge, fill=WHITE)

    if sector:
        draw.text((LP_X, 342), "行业", font=f_lbl, fill=DIM)
        draw.text((LP_X, 364), sector, font=f_med, fill=MUTED)

    _d = datetime.date.fromisoformat(jdate)
    jdate_fmt = f"{_d.year}年{_d.month:02d}月{_d.day:02d}日"
    draw.text((LP_X, 416), "纳入日期", font=f_lbl, fill=DIM)
    draw.text((LP_X, 438), jdate_fmt, font=f_med_cn, fill=WHITE)
    draw.text((LP_X, 496), f"{bdays}个交易日前", font=f_sml, fill=DIM)

    draw.line([(960, 110), (960, H - 68)], fill=BORDER)

    RP_X = 1000
    draw.text((RP_X, 114), "加入后涨幅", font=f_lbl, fill=DIM)

    perf_color = GREEN if perf >= 0 else RED
    sign       = "+" if perf >= 0 else ""
    perf_str   = f"{sign}{perf:.1f}%"
    f_perf     = load_font(90 if abs(perf) < 1000 else 60, bold=True)
    draw.text((RP_X, 142), perf_str, font=f_perf, fill=perf_color)

    hline(draw, 308, x0=RP_X, x1=W - 60)

    f_mv = load_font(30, mono=True)
    draw.text((RP_X, 326), "纳入价格", font=f_lbl, fill=DIM)
    draw.text((RP_X, 348), f"${jp:,.2f}", font=f_mv, fill=MUTED)

    draw.text((RP_X, 402), "当前价格", font=f_lbl, fill=DIM)
    draw.text((RP_X, 424), f"${cp:,.2f}", font=f_mv, fill=WHITE)

    draw.text((RP_X, 478), "今日", font=f_lbl, fill=DIM)
    draw.text((RP_X, 500), pct_str(pc1d), font=f_mv, fill=pct_color(pc1d))

    mg_sign = "+" if max_gain >= 0 else ""
    mg_str  = f"{mg_sign}{max_gain:.1f}%"
    draw.text((RP_X, 554), "加入后最高涨幅", font=f_lbl, fill=DIM)
    draw.text((RP_X, 576), mg_str, font=load_font(30, mono=True), fill=GOLD_LIGHT)

    hline(draw, H - 68)
    centered(draw, H - 56, "在baizora.com追踪标普500和纳斯达克100全部成分股变动",
             load_font_cn(20, bold=True), ELEC_BRIGHT)
    return img


def scene_sparkline_intro(member, scan_date):
    """Hold frame shown before the chart appears — narration plays here, chart follows silently."""
    img, draw = new_frame()
    row    = member["row"]
    ticker = member["ticker"]
    cname  = row.get("CompanyName", ticker)
    idx    = member["index_name"]
    perf   = member["perf_since_join"]

    top_bar(draw, f"Index Spotlight — {ticker} — Price Since Joining  ({scan_date})", scan_date)

    f_lbl  = load_font(20, mono=True)
    f_sub  = load_font(26)
    f_ann  = load_font(32, bold=True)

    cname_s = cname if len(cname) <= 32 else cname[:29] + "..."
    centered(draw, H // 2 - 80, cname_s, f_sub, MUTED)
    centered(draw, H // 2 - 36, ticker, load_font(52, mono=True), WHITE)

    sign    = "+" if perf >= 0 else ""
    if perf > 0:
        perf_label = f"{sign}{perf:.1f}% since joining {idx}"
        ann_col = GREEN
    else:
        perf_label = f"Has not gained since joining {idx}"
        ann_col = RED
    centered(draw, H // 2 + 44, perf_label, f_ann, ann_col)

    centered(draw, H // 2 + 100, "ONE-YEAR PRICE CHART", load_font(18, mono=True), DIM)

    hline(draw, H - 68)
    centered(draw, H - 56,
             "Triangle = join date  ·  Circle = today  ·  baizora.com",
             load_font(20, bold=True), ELEC_BRIGHT)
    return img


def scene_spotlight_sparkline(member, scan_date):
    """Full-width sparkline with gold triangle at join date and ELEC_BRIGHT circle at today."""
    img, draw = new_frame()
    row       = member["row"]
    ticker    = member["ticker"]
    idx       = member["index_name"]
    jdate     = member["join_date"]
    spark_idx = member["spark_idx"]
    perf      = member["perf_since_join"]
    jp        = member["join_price"]
    cp        = row.get("Price") or 0

    top_bar(draw,
            f"Index Spotlight — {ticker} — Price Since Joining  ({scan_date})", scan_date)

    spark = row.get("Spark1Y") or []
    if len(spark) < 2:
        return img

    margin = 90
    sx0    = margin
    sy0    = 120
    sw     = W - 2 * margin
    sh     = H - sy0 - 110
    pad    = 0.08
    n_pts  = len(spark)
    mn_v, mx_v = min(spark), max(spark)
    if mx_v <= mn_v:
        return img

    def spark_pt(i, v):
        px = sx0 + round(i / (n_pts - 1) * sw)
        py = sy0 + sh - round(((v - mn_v) / (mx_v - mn_v)) * sh * (1 - 2*pad) + sh*pad)
        return (px, py)

    pts      = [spark_pt(i, v) for i, v in enumerate(spark)]
    join_pt  = pts[spark_idx]
    today_pt = pts[-1]

    # Gold vertical line at join date
    draw.line([(join_pt[0], sy0), (join_pt[0], sy0 + sh)], fill=GOLD, width=1)

    # Pre-join sparkline (muted gray)
    pre_pts = pts[:spark_idx + 1]
    for j in range(len(pre_pts) - 1):
        draw.line([pre_pts[j], pre_pts[j + 1]], fill=VERY_DIM, width=2)

    # Post-join sparkline (colored)
    post_color = BRIGHT_GREEN if perf >= 0 else BRIGHT_RED
    post_pts   = pts[spark_idx:]

    # Fill polygon under post-join portion
    fill_col = (*post_color, 28)
    fill_poly = post_pts + [(today_pt[0], sy0 + sh), (join_pt[0], sy0 + sh)]
    ov  = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ovd = ImageDraw.Draw(ov)
    ovd.polygon(fill_poly, fill=fill_col)
    img  = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    draw = ImageDraw.Draw(img)

    for j in range(len(post_pts) - 1):
        draw.line([post_pts[j], post_pts[j + 1]], fill=post_color, width=3)

    f_lbl = load_font(18, mono=True)

    # Gold upward triangle at join date
    tx, ty = join_pt
    r = 13
    draw.polygon([(tx, ty - r), (tx - r, ty + r), (tx + r, ty + r)], fill=GOLD)
    # Join price label (above triangle)
    jp_lbl = f"${jp:,.2f}  {jdate}"
    jlw    = tw(draw, jp_lbl, f_lbl)
    lx     = max(sx0, min(tx - jlw // 2, sx0 + sw - jlw))
    label_y = ty + r + 6
    draw.text((lx, label_y), jp_lbl, font=f_lbl, fill=GOLD)

    # ELEC_BRIGHT circle at today
    cx, cy = today_pt
    cr     = 10
    draw.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=ELEC_BRIGHT)
    # Today label (left of circle to avoid right edge)
    td_lbl = f"TODAY  ${cp:,.2f}"
    tlw    = tw(draw, td_lbl, f_lbl)
    draw.text((cx - tlw - 14, cy - 12), td_lbl, font=f_lbl, fill=ELEC_BRIGHT)

    # Performance annotation top-center
    sign     = "+" if perf >= 0 else ""
    perf_str = f"{sign}{perf:.1f}% since joining {idx}"
    f_ann    = load_font(26, bold=True)
    ann_col  = GREEN if perf >= 0 else RED
    centered(draw, sy0 + 10, perf_str, f_ann, ann_col)

    hline(draw, H - 68)
    centered(draw, H - 56,
             f"Triangle = join date  ·  Circle = today  ·  baizora.com",
             load_font(20, bold=True), ELEC_BRIGHT)
    return img


def scene_index_changes_promo(date):
    """Promo scene — centered text layout, emphasizes membership news & history."""
    img, draw = new_frame()
    accent = ELECTRIC

    top_bar(draw, f"Index Membership News & History  ({date})", date)

    cx = W // 2
    y  = 180

    f_eyebrow = load_font(20, mono=True)
    draw.text((cx - tw(draw, "◈   BAIZORA PLATFORM", f_eyebrow) // 2, y),
              "◈   BAIZORA PLATFORM", font=f_eyebrow, fill=accent)
    y += 44

    f_title = load_font(52, bold=True)
    for line in _wrap_text(draw, "Index Changes — News & Price History", f_title, W - 240):
        draw.text((cx - tw(draw, line, f_title) // 2, y), line, font=f_title, fill=WHITE)
        y += th(draw, "Ag", f_title) + 12
    y += 46

    bullets = [
        "◆  Announcements typically come 1+ week before actual inclusion",
        "◆  Curated feed — no noise, only what matters",
        "◆  Full price history tracked from the day they join",
    ]
    f_bullet = load_font(26)
    for b in bullets:
        draw.text((_LP_X + 80, y), b, font=f_bullet, fill=MUTED)
        y += th(draw, "Ag", f_bullet) + 14
    y += 24

    f_cta = load_font(32, bold=True)
    cta   = "baizora.com — 7-day free trial, totally free to start"
    draw.text((cx - tw(draw, cta, f_cta) // 2, y), cta, font=f_cta, fill=ELEC_BRIGHT)

    hline(draw, H - 68)
    centered(draw, H - 56, "For informational purposes only. Not financial advice.",
             load_font(18), DIM)

    return img


def scene_promo_with_change_ss(date):
    """Left half: promo text. Right half: membership_change screenshot."""
    img, draw = new_frame()
    divx = 940

    top_bar(draw, f"Index Membership Change Tracker  ({date})", date)

    cx_left = divx // 2
    y = 180

    f_eyebrow = load_font(18, mono=True)
    eyebrow = "◈   BAIZORA PLATFORM"
    draw.text((cx_left - tw(draw, eyebrow, f_eyebrow) // 2, y),
              eyebrow, font=f_eyebrow, fill=ELECTRIC)
    y += 44

    f_title = load_font(44, bold=True)
    for line in _wrap_text(draw, "Daily Index Membership Tracking", f_title, divx - 80):
        draw.text((cx_left - tw(draw, line, f_title) // 2, y), line, font=f_title, fill=WHITE)
        y += th(draw, "Ag", f_title) + 12
    y += 36

    bullets = [
        "◆  Every S&P 500 & Nasdaq-100 change logged daily",
        "◆  Price history tracked from day of inclusion",
        "◆  See how each new member performs over time",
    ]
    f_bullet = load_font(22)
    for b in bullets:
        draw.text((cx_left - tw(draw, b, f_bullet) // 2, y), b, font=f_bullet, fill=MUTED)
        y += th(draw, "Ag", f_bullet) + 14
    y += 20

    f_cta = load_font(26, bold=True)
    cta = "baizora.com — 7-day free trial"
    draw.text((cx_left - tw(draw, cta, f_cta) // 2, y), cta, font=f_cta, fill=ELEC_BRIGHT)

    draw.line([(divx, 90), (divx, H - 48)], fill=BORDER)

    p = Path(_SS_MEMBERSHIP_CHANGE)
    if p.exists():
        ss = Image.open(str(p)).convert("RGB")
        iw, ih = ss.size
        max_w, max_h = W - divx - 20, H - 120
        scale = min(max_w / iw, max_h / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        ss = ss.resize((nw, nh), Image.LANCZOS)
        img.paste(ss, (divx + (W - divx - nw) // 2, (H - nh) // 2))

    hline(draw, H - 68)
    centered(draw, H - 56, "For informational purposes only. Not financial advice.",
             load_font(18), DIM)
    return img


def scene_outro_with_homepage(scan_date):
    """Left half: homepage screenshot. Right half: outro branding."""
    img, draw = new_frame()
    divx = 960

    p = Path(_SS_EN)
    if p.exists():
        ss = Image.open(str(p)).convert("RGB")
        iw, ih = ss.size
        scale = min(divx / iw, H / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        ss = ss.resize((nw, nh), Image.LANCZOS)
        img.paste(ss, ((divx - nw) // 2, (H - nh) // 2))

    draw.line([(divx, 80), (divx, H - 40)], fill=BORDER)

    rx_cx = divx + (W - divx) // 2
    f_big = load_font(80, serif=True)
    baiz_w = tw(draw, "Baiz", f_big)
    ora_w  = tw(draw, "ora",  f_big)
    lx = divx + ((W - divx) - baiz_w - ora_w) // 2
    draw.text((lx,          310), "Baiz", font=f_big, fill=WHITE)
    draw.text((lx + baiz_w, 310), "ora",  font=f_big, fill=ELECTRIC)

    f_sub = load_font(22)
    for label, y, col in [
        ("US Large-Cap Price & Volume Analytics", 418, MUTED),
        ("Start your free 7-day trial",           470, GOLD_LIGHT),
        ("baizora.com",                            516, ELECTRIC),
        (f"Daily Scan: {scan_date}",               560, DIM),
    ]:
        draw.text((rx_cx - tw(draw, label, f_sub) // 2, y), label, font=f_sub, fill=col)

    return img


def _narrate_spotlight_spark(member):
    """Short narration for the sparkline intro scene."""
    perf = member["perf_since_join"]
    if perf > 0:
        sign = "+"
        perf_part = f"up {sign}{perf:.1f}% since then"
    else:
        perf_part = "has not gained yet since joining"
    return (
        f"Here's the one-year price chart. "
        f"The gold triangle marks the join date — {perf_part}."
    )


def _narrate_spotlight(member):
    """~35-word narration for the 16s spotlight card scene."""
    row       = member["row"]
    ticker    = member["ticker"]
    cname     = row.get("CompanyName", ticker)
    idx       = member["index_name"]
    bdays     = member["bdays_since_join"]
    perf      = member["perf_since_join"]
    max_gain  = member.get("max_gain_since_join", perf)
    jp        = member["join_price"]
    cp        = row.get("Price") or 0
    pc1d      = row.get("PriceChange1D") or 0
    mg_sign   = "+" if max_gain >= 0 else ""
    today_dir = "up" if pc1d >= 0 else "down"
    if perf > 0:
        sign = "+"
        perf_part = f"currently up {sign}{perf:.1f}% from ${jp:,.2f} to ${cp:,.2f}."
        extra = ""
    else:
        perf_part = f"has not gained yet — currently at ${cp:,.2f}, from the join price of ${jp:,.2f}."
        extra = (
            " Interestingly, unlike most index additions, it hasn't moved up —"
            " could this be an early entry opportunity?"
        )
    return (
        f"{cname} joined the {idx} {bdays} trading days ago. "
        f"At its peak, it surged {mg_sign}{max_gain:.1f}% since joining — "
        f"{perf_part}"
        f" Today, {ticker} is {today_dir} {abs(pc1d):.1f}%."
        + extra
    )


def _narrate_spotlight_change_log():
    return (
        "Baizora tracks every S&P 500 and Nasdaq-100 membership change "
        "and records the complete price history for every new member."
    )


def _narrate_spotlight_news():
    return (
        "Index changes are typically announced more than a week before they happen. "
        "Baizora's curated news feed cuts through the noise, "
        "so you can act before the crowd. "
        "Start your free seven-day trial at baizora dot com."
    )


def _get_verified_members(data):
    """
    Read data/verified_new_member.txt for manually curated new members.
    Falls back to _get_new_members if the file is missing or empty.

    File format (blocks separated by blank lines):
        2026-05-18
        Nasdaq-100
        + LITE Lumentum Holdings Inc.

        2026-03-23
        S&P 500
        + VRT Vertiv Holdings Co
        + COHR Coherent Corp.
    """
    verified_file = SCRIPT_DIR / "verified_new_member.txt"

    if not verified_file.exists():
        return _get_new_members(data)

    # Parse blocks: date / index / "+ TICKER Name" lines
    verified = []  # list of (ticker, idx_key, join_date)
    lines = verified_file.read_text().splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].strip():
            i += 1
            continue
        date_str = lines[i].strip()
        i += 1
        if i >= len(lines):
            break
        idx_line = lines[i].strip()
        i += 1
        idx_key = "nasdaq100" if "nasdaq" in idx_line.lower() else "sp500"
        while i < len(lines) and lines[i].strip().startswith("+"):
            parts = lines[i].strip().split()
            if len(parts) >= 2:
                verified.append((parts[1].upper(), idx_key, date_str))
            i += 1

    if not verified:
        return _get_new_members(data)

    # A ticker can legitimately appear in more than one block (e.g. joining the
    # Nasdaq-100 and the S&P 500 on different dates) — left as-is, that silently
    # doubles its odds in the Friday spotlight's random.choice() pick versus every
    # single-appearance ticker. Keep only the most recent join per ticker so every
    # candidate gets equal weight (date strings are ISO "YYYY-MM-DD", so a plain
    # string comparison is enough to find the latest).
    latest_by_ticker = {}
    for t, idx_key, jdate_str in verified:
        if t not in latest_by_ticker or jdate_str > latest_by_ticker[t][1]:
            latest_by_ticker[t] = (idx_key, jdate_str)
    verified = [(t, idx_key, jdate_str) for t, (idx_key, jdate_str) in latest_by_ticker.items()]

    scan_date  = data["date"]
    ticker_map = {r["Ticker"]: r for r in data["data"]}

    members = []
    for t, idx_key, jdate_str in verified:
        if t not in ticker_map:
            continue
        row   = ticker_map[t]
        spark = row.get("Spark1Y") or []
        if len(spark) < 2:
            continue
        index_name = "Nasdaq-100" if idx_key == "nasdaq100" else "S&P 500"
        try:
            d1 = _parse_date(jdate_str)
        except ValueError:
            print(f"  [skip] bad join date for {t}: {jdate_str!r}")
            continue
        d2 = datetime.date.fromisoformat(scan_date)
        if not (0 < (d2 - d1).days <= 730):
            print(f"  [skip] {t} join date out of range: {jdate_str} ({(d2-d1).days}d)")
            continue
        bdays, cur = 0, d1
        while cur < d2:
            cur += datetime.timedelta(days=1)
            if cur.weekday() < 5:
                bdays += 1
        spark_idx = max(0, min(len(spark) - 1, len(spark) - 1 - bdays))
        jpr = _price_from_spark(row, spark_idx)
        if not jpr or jpr <= 0:
            continue
        cpr    = row.get("Price") or 0
        perf   = (cpr - jpr) / jpr * 100
        pc1y   = row.get("1YPriceChange") or 0
        denom  = 1 + pc1y / 100
        p1yago = cpr / denom if abs(denom) > 1e-9 else cpr
        sd     = spark[0] - spark[-1]
        if abs(sd) > 1e-9:
            R         = (p1yago - cpr) / sd
            base_price = cpr - spark[-1] * R
            post_actual = [base_price + spark[i] * R for i in range(spark_idx, len(spark))]
            max_price   = max(post_actual)
            trough_price = min(post_actual)
            # post_actual[0] is the join day itself, so both indices are relative
            # to spark_idx -- add it back to get the absolute Spark1Y index the
            # chart marker needs to be drawn at.
            max_gain_idx = spark_idx + post_actual.index(max_price)
            max_loss_idx = spark_idx + post_actual.index(trough_price)
        else:
            max_price, trough_price = jpr, jpr
            max_gain_idx = max_loss_idx = spark_idx
        max_gain = (max_price - jpr) / jpr * 100
        max_loss = (trough_price - jpr) / jpr * 100
        members.append({
            "ticker":              t,
            "row":                 row,
            "join_date":           jdate_str,
            "index_name":          index_name,
            "bdays_since_join":    bdays,
            "spark_idx":           spark_idx,
            "join_price":          jpr,
            "perf_since_join":     perf,
            "max_gain_since_join": max_gain,
            "max_loss_since_join": max_loss,
            "max_gain_idx":        max_gain_idx,
            "max_loss_idx":        max_loss_idx,
        })
    return members


def build_index_spotlight(data, output):
    members = _get_verified_members(data)
    if not members:
        print("No new index members found, skipping.")
        return

    member = random.choice(members)
    date   = data["date"]
    ticker = member["ticker"]
    idx    = member["index_name"]

    card_dur = 36 if member["perf_since_join"] <= 0 else 28

    encode([
        (scene_title("Index Spotlight", idx, date,
                     f"New member performance — {ticker}"), 4,
         f"Tracking {ticker} since joining the {idx}",
         random.choice(_SPOTLIGHT_OPENERS_EN) +
         " Every Friday on this channel, we spotlight a new S&P 500 or Nasdaq-100 member"
         " and track how it has performed since joining. Subscribe to follow along each week."),
        (scene_index_spotlight(member, date), card_dur,
         f"{ticker} — joined {idx} on {member['join_date']}",
         _narrate_spotlight(member) + " " + _narrate_spotlight_spark(member)),
        (scene_spotlight_sparkline(member, date), 9 if member["perf_since_join"] <= 0 else 8),
        (scene_promo_with_change_ss(date), 10,
         "Index membership changes — full price history — baizora.com",
         _narrate_spotlight_change_log()),
        (scene_screenshot(_SS_MEMBERSHIP_NEWS), 10,
         "Index membership news feed — baizora.com",
         _narrate_spotlight_news()),
        (scene_outro_with_homepage(date), 5,
         "For informational purposes only. Not financial advice. | baizora.com"),
    ], output)


_SPOTLIGHT_OPENERS_CN = [
    "当一只股票加入标普500或纳斯达克100，市场格局随之改变——不只是在投资组合层面。",
    "纳入指数不只是对过去的认可，它可能深刻影响接下来的走势。",
    "新成员不只是一个标签——它意味着数万亿被动资金必须买入这只股票。",
    "一旦加入主要指数，所有跟踪该指数的基金都必须买入。这不是预测，是已知的需求。",
    "加入标普500或纳斯达克100不只是一个里程碑。来看看这只股票的后续表现。",
    "大盘股获得指数席位后会发生什么？数据或许会让你意外。",
    "指数纳入往往是市场尚未充分定价的先行信号。",
    "被动基金不预测未来——但当它们同时买入一只股票时，往往能推动趋势的形成。",
    "投资者关注指数新成员是有原因的。这是一只值得追踪的股票。",
    "每一次指数纳入的走势都不尽相同。来看看这位近期新成员加入后的表现。",
]


def _narrate_spotlight_spark_cn(member):
    """短旁白，适配走势图前置等待帧场景。"""
    perf = member["perf_since_join"]
    if perf > 0:
        sign = "+"
        perf_part = f"自加入以来上涨{sign}{perf:.1f}%"
    else:
        perf_part = "自加入以来尚未上涨"
    return f"这是一年期价格走势图。金色三角标记纳入日期——{perf_part}。"


def _narrate_spotlight_cn(member):
    """~35字旁白，适配16秒个股卡片场景。"""
    row       = member["row"]
    ticker    = member["ticker"]
    cname     = row.get("CompanyName", ticker)
    idx_cn    = "纳斯达克100" if "Nasdaq" in member["index_name"] else "标普500"
    bdays     = member["bdays_since_join"]
    perf      = member["perf_since_join"]
    max_gain  = member.get("max_gain_since_join", perf)
    jp        = member["join_price"]
    cp        = row.get("Price") or 0
    pc1d      = row.get("PriceChange1D") or 0
    mg_sign   = "+" if max_gain >= 0 else ""
    today_dir = "上涨" if pc1d >= 0 else "下跌"
    if perf > 0:
        sign = "+"
        perf_part = f"目前上涨{sign}{perf:.1f}%，从{jp:,.2f}到{cp:,.2f}美元。"
        extra = ""
    else:
        perf_part = f"目前尚未上涨——当前价格{cp:,.2f}美元，纳入价格为{jp:,.2f}美元。"
        extra = "有趣的是，与多数指数新成员不同，它加入后尚未上涨——这或许是个提前布局的机会？"
    return (
        f"{cname}于{bdays}个交易日前加入{idx_cn}。"
        f"加入后最高涨幅达{mg_sign}{max_gain:.1f}%，"
        f"{perf_part}"
        f"今日{ticker}{today_dir}{abs(pc1d):.1f}%。"
        + extra
    )


def _narrate_spotlight_change_log_cn():
    return (
        "贝佐拉追踪标普500和纳斯达克100的每一次成分股变动，"
        "完整记录每只新成员的价格走势。"
    )


def _narrate_spotlight_news_cn():
    return (
        "成分股变动通常提前一周以上公告。"
        "贝佐拉精选资讯，过滤噪音，让您抢先掌握动向。"
        "立即前往baizora.com，开始七天免费体验。"
    )


def scene_index_changes_promo_cn(date):
    """CN版推广场景——居中文字布局。"""
    img, draw = new_frame()
    accent = ELECTRIC

    top_bar(draw, f"成分股变动资讯与价格走势  ({date})", date)

    cx = W // 2
    y  = 180

    label = "◈   贝佐拉平台"
    f_label = load_font_cn(26)
    draw.text((cx - tw(draw, label, f_label) // 2, y), label, font=f_label, fill=accent)
    y += 44

    f_title = load_font_cn(52, bold=True)
    for line in _wrap_text(draw, "成分股变动 — 资讯与价格走势", f_title, W - 240):
        draw.text((cx - tw(draw, line, f_title) // 2, y), line, font=f_title, fill=WHITE)
        y += th(draw, "一", f_title) + 18
    y += 36

    bullets_cn = [
        "◆  成分股变动通常提前一周以上公告",
        "◆  精选资讯，过滤噪音，只保留关键信息",
        "◆  从纳入之日起完整追踪价格走势",
    ]
    f_bullet = load_font_cn(26)
    for b in bullets_cn:
        draw.text((_LP_X + 80, y), b, font=f_bullet, fill=MUTED)
        y += th(draw, "一", f_bullet) + 14
    y += 24

    f_cta = load_font_cn(32, bold=True)
    cta   = "baizora.com — 七天免费体验"
    draw.text((cx - tw(draw, cta, f_cta) // 2, y), cta, font=f_cta, fill=ELEC_BRIGHT)

    hline(draw, H - 68)
    centered(draw, H - 56, "仅供参考，不构成投资建议 | baizora.com",
             load_font_cn(18), DIM)

    return img


def scene_promo_with_change_ss_cn(date):
    """左半部分：中文推广文字。右半部分：membership_change 截图。"""
    img, draw = new_frame()
    divx = 940

    top_bar(draw, f"成分股变动日常追踪  ({date})", date)

    cx_left = divx // 2
    y = 180

    label = "◈   贝佐拉平台"
    f_label = load_font_cn(18)
    draw.text((cx_left - tw(draw, label, f_label) // 2, y), label, font=f_label, fill=ELECTRIC)
    y += 44

    f_title = load_font_cn(44, bold=True)
    for line in _wrap_text(draw, "每日指数成分股变动追踪", f_title, divx - 80):
        draw.text((cx_left - tw(draw, line, f_title) // 2, y), line, font=f_title, fill=WHITE)
        y += th(draw, "一", f_title) + 18
    y += 30

    bullets_cn = [
        "◆  标普500和纳斯达克100每日变动全记录",
        "◆  从纳入之日起完整追踪价格走势",
        "◆  清晰查看每只新成员纳入后的表现",
    ]
    f_bullet = load_font_cn(20)
    for b in bullets_cn:
        draw.text((cx_left - tw(draw, b, f_bullet) // 2, y), b, font=f_bullet, fill=MUTED)
        y += th(draw, "一", f_bullet) + 14
    y += 20

    f_cta = load_font_cn(26, bold=True)
    cta = "baizora.com — 七天免费体验"
    draw.text((cx_left - tw(draw, cta, f_cta) // 2, y), cta, font=f_cta, fill=ELEC_BRIGHT)

    draw.line([(divx, 90), (divx, H - 48)], fill=BORDER)

    p = Path(_SS_MEMBERSHIP_CHANGE)
    if p.exists():
        ss = Image.open(str(p)).convert("RGB")
        iw, ih = ss.size
        max_w, max_h = W - divx - 20, H - 120
        scale = min(max_w / iw, max_h / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        ss = ss.resize((nw, nh), Image.LANCZOS)
        img.paste(ss, (divx + (W - divx - nw) // 2, (H - nh) // 2))

    hline(draw, H - 68)
    centered(draw, H - 56, "仅供参考，不构成投资建议 | baizora.com",
             load_font_cn(18), DIM)
    return img


def scene_outro_cn_with_homepage(scan_date):
    """左半部分：中文主页截图。右半部分：中文结尾品牌。"""
    img, draw = new_frame()
    divx = 960

    p = Path(_SS_CN)
    if p.exists():
        ss = Image.open(str(p)).convert("RGB")
        iw, ih = ss.size
        scale = min(divx / iw, H / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        ss = ss.resize((nw, nh), Image.LANCZOS)
        img.paste(ss, ((divx - nw) // 2, (H - nh) // 2))

    draw.line([(divx, 80), (divx, H - 40)], fill=BORDER)

    rx_cx = divx + (W - divx) // 2
    f_big = load_font_cn(72, bold=True)
    brand_w = tw(draw, "贝佐拉", f_big)
    draw.text((divx + ((W - divx) - brand_w) // 2, 310), "贝佐拉", font=f_big, fill=ELEC_BRIGHT)

    f_sub = load_font_cn(20)
    for label, y, col in [
        ("美股大盘价格与成交量分析平台", 418, MUTED),
        ("开始七天免费试用",              468, GOLD_LIGHT),
        ("baizora.com",                  514, ELECTRIC),
        (f"每日扫描：{scan_date}",         558, DIM),
    ]:
        draw.text((rx_cx - tw(draw, label, f_sub) // 2, y), label, font=f_sub, fill=col)

    return img


def build_index_spotlight_cn(data, output):
    members = _get_verified_members(data)
    if not members:
        print("未找到新成员，跳过。")
        return

    member = random.choice(members)
    date   = data["date"]
    ticker = member["ticker"]
    idx_cn = "纳斯达克100" if "Nasdaq" in member["index_name"] else "标普500"

    encode([
        (scene_title_cn("指数聚焦", idx_cn, date,
                        f"新成员表现追踪 — {ticker}"), 4,
         f"追踪{ticker}自加入{idx_cn}后的表现",
         random.choice(_SPOTLIGHT_OPENERS_CN) +
         "本频道每周五聚焦一只新晋指数成员，追踪其纳入后的完整表现。订阅我们，每周跟进。"),
        (scene_index_spotlight_cn(member, date), 30 if member["perf_since_join"] <= 0 else 20,
         f"{ticker} — 于{member['join_date']}加入{idx_cn}",
         _narrate_spotlight_cn(member) + " " + _narrate_spotlight_spark_cn(member)),
        (scene_spotlight_sparkline(member, date), 9),
        (scene_promo_with_change_ss_cn(date), 10,
         "成分股变动记录与完整价格走势 — baizora.com",
         _narrate_spotlight_change_log_cn()),
        (scene_screenshot(_SS_MEMBERSHIP_NEWS), 10,
         "成分股变动资讯 — baizora.com",
         _narrate_spotlight_news_cn()),
        (scene_outro_cn_with_homepage(date), 5,
         "仅供参考，不构成投资建议 | baizora.com"),
    ], output, tts_voice="zh-CN-YunxiNeural")


TUESDAY_TF_ROTATION = [
    {
        "key": "3MPriceChange",  "label_en": "3-Month",   "label_short": "3M",
        "window_en": "three months",  "label_cn": "三个月", "window_cn": "三个月",
        "title_cn": "三个月最强大盘股", "rank_cn": "三个月涨幅前三", "spark_days": 63,
    },
    {
        "key": "6MPriceChange",  "label_en": "6-Month",   "label_short": "6M",
        "window_en": "six months",    "label_cn": "六个月", "window_cn": "六个月",
        "title_cn": "六个月最强大盘股", "rank_cn": "六个月涨幅前三", "spark_days": 126,
    },
    {
        "key": "9MPriceChange",  "label_en": "9-Month",   "label_short": "9M",
        "window_en": "nine months",   "label_cn": "九个月", "window_cn": "九个月",
        "title_cn": "九个月最强大盘股", "rank_cn": "九个月涨幅前三", "spark_days": 189,
    },
    {
        "key": "1YPriceChange",  "label_en": "1-Year",    "label_short": "1Y",
        "window_en": "twelve months", "label_cn": "一年",  "window_cn": "十二个月",
        "title_cn": "一年最强大盘股",  "rank_cn": "一年涨幅前三",  "spark_days": None,
    },
]


def _tuesday_tf(date_str):
    """Pick Tuesday TF rotation slot: 3M->6M->9M->1Y, cycling by ISO week number."""
    d = datetime.date.fromisoformat(date_str)
    return TUESDAY_TF_ROTATION[d.isocalendar()[1] % 4]


WEDNESDAY_TF_ROTATION = [
    {
        "label_en": "3-Month",  "label_short": "3M",  "window_en": "three months",
        "label_cn": "三个月",    "window_cn": "三个月",   "spark_days": 63,
        "high_hdr": "3M HIGH",  "high_hdr_cn": "三月高价",  "peak_label_cn": "三月高点",
        "title_cn": "三月新高突破",  "min_drawdown": 10,
    },
    {
        "label_en": "6-Month",  "label_short": "6M",  "window_en": "six months",
        "label_cn": "六个月",    "window_cn": "六个月",   "spark_days": 126,
        "high_hdr": "6M HIGH",  "high_hdr_cn": "六月高价",  "peak_label_cn": "六月高点",
        "title_cn": "六月新高突破",  "min_drawdown": 10,
    },
    {
        "label_en": "9-Month",  "label_short": "9M",  "window_en": "nine months",
        "label_cn": "九个月",    "window_cn": "九个月",   "spark_days": 189,
        "high_hdr": "9M HIGH",  "high_hdr_cn": "九月高价",  "peak_label_cn": "九月高点",
        "title_cn": "九月新高突破",  "min_drawdown": 10,
    },
    {
        "label_en": "1-Year",   "label_short": "1Y",  "window_en": "twelve months",
        "label_cn": "一年",      "window_cn": "十二个月", "spark_days": None,
        "high_hdr": "1Y HIGH",  "high_hdr_cn": "年高价",    "peak_label_cn": "年高点",
        "title_cn": "一年新高突破",  "min_drawdown": 10,
    },
]


def _wednesday_tf(date_str):
    """Pick Wednesday TF rotation: 3M->6M->9M->1Y, cycling by ISO week number."""
    d = datetime.date.fromisoformat(date_str)
    return WEDNESDAY_TF_ROTATION[d.isocalendar()[1] % 4]


THURSDAY_TF_ROTATION = [
    {
        "label_en": "3-Month",  "label_short": "3M",  "window_en": "three months",
        "label_cn": "三个月",    "window_cn": "三个月",
        "vol_day_key": "3MMaxVolumeChangeDay",  "vol_chg_key": "3MMaxVolumeChange",
        "spark_days": 63,
        "title_en": "3-Month Volume Records",
        "title_cn": "三月成交量记录",
        "subtitle_en": "Stocks recording their highest single-day volume of the past 3 months",
        "subtitle_cn": "大盘股创下过去三个月最大单日成交量 — 贝佐拉",
    },
    {
        "label_en": "6-Month",  "label_short": "6M",  "window_en": "six months",
        "label_cn": "六个月",    "window_cn": "六个月",
        "vol_day_key": "6MMaxVolumeChangeDay",  "vol_chg_key": "6MMaxVolumeChange",
        "spark_days": 126,
        "title_en": "6-Month Volume Records",
        "title_cn": "半年成交量记录",
        "subtitle_en": "Stocks recording their highest single-day volume of the past 6 months",
        "subtitle_cn": "大盘股创下过去六个月最大单日成交量 — 贝佐拉",
    },
    {
        "label_en": "9-Month",  "label_short": "9M",  "window_en": "nine months",
        "label_cn": "九个月",    "window_cn": "九个月",
        "vol_day_key": "9MMaxVolumeChangeDay",  "vol_chg_key": "9MMaxVolumeChange",
        "spark_days": 189,
        "title_en": "9-Month Volume Records",
        "title_cn": "九月成交量记录",
        "subtitle_en": "Stocks recording their highest single-day volume of the past 9 months",
        "subtitle_cn": "大盘股创下过去九个月最大单日成交量 — 贝佐拉",
    },
    {
        "label_en": "1-Year",   "label_short": "1Y",  "window_en": "twelve months",
        "label_cn": "一年",      "window_cn": "十二个月",
        "vol_day_key": "1YMaxVolumeChangeDay",  "vol_chg_key": "1YMaxVolumeChange",
        "spark_days": None,
        "title_en": "1-Year Volume Records",
        "title_cn": "年度成交量记录",
        "subtitle_en": "Stocks recording their highest single-day volume of the past year",
        "subtitle_cn": "大盘股创下过去一年最大单日成交量 — 贝佐拉",
    },
]


def _thursday_tf(date_str):
    """Pick Thursday TF rotation: 3M->6M->9M->1Y, cycling by ISO week number."""
    d = datetime.date.fromisoformat(date_str)
    return THURSDAY_TF_ROTATION[d.isocalendar()[1] % 4]


_TF_OPENERS_EN = [
    "Which large-cap stocks have delivered the strongest returns over the past {window}? The answer might surprise you.",
    "A lot can happen in {window}. Here are the stocks that made the most of it.",
    "Past performance doesn't predict the future — but it does reveal who's been winning. Today's top {window} performers.",
    "If you had bought these stocks {window} ago, here's where you'd be today.",
    "The market always has winners. Over the last {window}, these large-cap stocks led the pack.",
    "Momentum leaves a trail. Here are the S&P 500 and Nasdaq-100 stocks with the strongest trailing-{window} gains.",
    "What does {window} of outperformance look like? These stocks have the answer.",
    "Not all large-caps are created equal. Over the past {window}, these names stood far above the rest.",
    "Sometimes the best signal is simply who has been winning — consistently, over time. Today's {window} leaders.",
    "The market rewards some stocks more than others. Here's who's been at the top over the last {window}.",
]


def build_extreme_1y(data, output):
    date    = data["date"]
    tf      = _tuesday_tf(date)
    gainers = sorted(data["data"],
                     key=lambda r: r.get(tf["key"]) or -9999, reverse=True)[:10]

    def _fmt_gain(v):
        v = abs(v)
        if v >= 200:
            return f"{round(v / 100):.0f} times"
        return f"{v:.0f} percent"

    def _narrate_tf(rows):
        top = rows[:3]
        parts = []
        for r in top:
            ticker = r.get("Ticker", "")
            v      = r.get(tf["key"]) or 0
            parts.append(f"{ticker} up {_fmt_gain(v)}")
        if len(parts) >= 2:
            return (f"Top {tf['label_en'].lower()} performers: "
                    + ", ".join(parts[:-1]) + f", and {parts[-1]}.")
        elif parts:
            return f"Top {tf['label_en'].lower()} performer: {parts[0]}."
        return ""

    label  = tf["label_en"]
    window = tf["window_en"]
    opener = (random.choice(_TF_OPENERS_EN).format(window=window) +
              " On this channel, every Tuesday, we cover the best performers across different timeframes. "
              "Subscribe so you never miss an update.")

    encode([
        (scene_title(f"{label} Best Performers", "S&P 500  ·  Nasdaq-100", date,
                     f"Large-Cap Leaders — Trailing {label}"), 4,
         f"Best large-cap stocks over the past {window} — S&P 500 + Nasdaq-100",
         opener),
        (scene_movers_table(f"Top 3 Gainers — {label}  ({date})", gainers, date,
                            max_rows=3,
                            cta_text=f"Want to see all top {label.lower()} performers? Visit baizora.com — Free 7-day trial.",
                            tf=tf), 17,
         f"S&P 500 + Nasdaq-100 stocks — highest trailing {window} price appreciation",
         f"{_narrate_tf(gainers)}"),
        (scene_top3_sparklines(
            f"{label} Leaders — Price Trend  ({date})", gainers, date,
            "Want to see more? Visit baizora.com for the full S&P 500 & Nasdaq-100 analysis.", tf=tf), 5,
         f"Top 3 {label.lower()} leaders — trailing {window} price trend",
         f"Here are the {window} price charts for today's top three performers."),
        (scene_1y_sort_promo(data, date, tf), 5,
         "Sort by any timeframe — 2W through 1Y — to find price leaders across S&P 500 & Nasdaq-100",
         f"On Baizora, you can see how the top {label.lower()} performers compare across every timeframe — "
         "from two weeks to one year. Sort by any column to find the leaders instantly. "
         "Visit baizora dot com."),
        (scene_screenshot(_SS_EN), 2),
        (scene_outro(date), 5,
         "For informational purposes only. Not financial advice. | baizora.com"),
    ], output)


FEATURE_SUBS = [
    "All price and volume metrics across 7 timeframes — no switching between tabs or dashboards",
    "1-year sparklines with max volume and max price-change dates pinned directly on the chart",
    "S&P 500 and Nasdaq-100 index composition changes tracked and flagged every trading day",
    "Sort by any column — price change, volume spike, or max-day — across the full universe instantly",
    "PE ratio, Market Cap, EPS, and 30-day Volatility visible alongside every technical metric",
]

FEATURE_NARRATIONS = [
    "Feature one: all metrics in one view. "
    "No tab-switching. Every price and volume metric across seven timeframes — "
    "from one day to one year — visible and sortable in a single table.",
    "Feature two: one-year sparklines with key events marked. "
    "Every stock includes a one-year price trend chart. "
    "The date of peak volume and peak single-day price gain are pinned directly on the spark.",
    "Feature three: index membership changes tracked daily. "
    "Baizora flags every addition and removal from the S&P 500 and Nasdaq 100 the moment it happens. "
    "Know exactly when a stock enters or exits a major index.",
    "Feature four: sort any timeframe instantly. "
    "Click any column — price change, volume spike, or maximum move day — "
    "to rank the entire large-cap universe by that metric in one click.",
    "Feature five: fundamentals at a glance. "
    "P-E ratio, market cap, earnings per share, and thirty-day volatility "
    "are shown right next to every technical metric. No separate lookup needed.",
]

FEATURES_CN = [
    {
        "num": "01", "accent": ELECTRIC,
        "title": "所有指标一览无余",
        "body_text": "无需切换标签页。从一天到一年，七个时间维度的全部价格和成交量数据，在同一张表格中可见可排序。",
    },
    {
        "num": "02", "accent": ELEC_BRIGHT,
        "title": "一年趋势图标注关键事件",
        "body_text": "每支股票均附有一年价格走势图。最大单日涨幅日和最大成交量日直接标注在图上。",
    },
    {
        "num": "03", "accent": GOLD,
        "title": "指数成分股变动每日追踪",
        "body_text": "S&P 500和纳斯达克100成分股调整实时标记。第一时间掌握个股进出主要指数的时机。",
    },
    {
        "num": "04", "accent": GREEN,
        "title": "一键按任意维度排序",
        "body_text": "点击任意列——价格变化、成交量异动或最大涨幅日——即可对全部大盘股按该指标即时排序。",
    },
    {
        "num": "05", "accent": MUTED,
        "title": "基本面数据一目了然",
        "body_text": "市盈率、市值、每股收益和三十日波动率紧邻每个技术指标显示，无需单独查询。",
    },
]

FEATURE_SUBS_CN = [
    "七个时间维度的完整价量数据，无需切换标签页",
    "一年趋势图标注最大量日和最大涨幅日",
    "每日追踪S&P 500和纳斯达克100成分股变动",
    "一键按任意列排序，即时筛选全市场",
    "市盈率、市值、每股收益和30日波动率一目了然",
]

FEATURE_NARRATIONS_CN = [
    "功能一：所有指标一览无余。无需切换标签页。从一天到一年，七个时间维度的全部价格和成交量数据，在同一张表格中可见可排序。",
    "功能二：一年趋势图标注关键事件。每支股票均附有一年价格走势图。最大单日涨幅日和最大成交量日直接标注在图上。",
    "功能三：指数成分股变动每日追踪。贝佐拉在第一时间标记S&P 500和纳斯达克100的每一次成分股调整。精准掌握个股进出主要指数的时机。",
    "功能四：一键按任意时间维度排序。点击任意列——价格变化、成交量异动或最大涨幅日——即可对全部大盘股按该指标即时排序。",
    "功能五：基本面数据一目了然。市盈率、市值、每股收益和三十日波动率紧邻每个技术指标显示，无需单独查询。",
]


def build_platform_intro(data, output):
    date   = data["date"]
    frames = [
        (scene_title("Introducing", "Baizora", date,
                     "US Large-Cap Price & Volume Analytics"), 8,
         "Baizora delivers comprehensive US large-cap market analytics in one platform",
         "What makes Baizora different? Here are the five features that set us apart "
         "from every other market analytics platform."),
    ]
    items = list(zip(FEATURES, FEATURE_SUBS, FEATURE_NARRATIONS))
    for i, (feat, sub, narr) in enumerate(items):
        if i == len(items) - 1:
            narr = (narr + " Want to know more about short and mid term "
                    "price and volume data? Visit baizora dot com.")
        frames.append((scene_platform_feature_v2(feat, data), 14, sub, narr))
    frames.append((scene_screenshot(_SS_EN), 2))
    frames.append((scene_outro(date), 5,
                   "For informational purposes only. Not financial advice. | baizora.com"))
    encode(frames, output)


_TF_OPENERS_CN = [
    "过去{window}，哪些大盘股的涨幅最为惊人？",
    "如果{window}前买入这些股票，今天的收益会让你惊讶。",
    "市场总是在奖励赢家——过去{window}，这些股票遥遥领先。",
    "在S&P 500和纳斯达克100中，谁是过去{window}真正的赢家？",
    "强势的股票会持续强势吗？先来看看过去{window}的领涨榜。",
    "{window}的时间能发生很多事。这些大盘股把握住了机会。",
    "动能会留下痕迹。这是S&P 500和纳斯达克100过去{window}涨幅最大的股票。",
    "不是所有大盘股都一样。过去{window}，这些名字远超其他股票。",
    "今天，让我们来看看{window}里表现最突出的大盘股。",
    "有时候，最好的信号就是谁一直在赢。以下是今天的{window}领涨榜。",
]


def build_extreme_1y_cn(data, output):
    date    = data["date"]
    tf      = _tuesday_tf(date)
    gainers = sorted(data["data"],
                     key=lambda r: r.get(tf["key"]) or -9999, reverse=True)[:10]

    def _fmt_gain_cn(v):
        v = abs(v)
        if v >= 200:
            return f"{round(v / 100):.0f}倍"
        return f"{v:.0f}%"

    def _narrate_tf_cn(rows):
        top = rows[:3]
        parts = []
        for r in top:
            ticker = r.get("Ticker", "")
            v      = r.get(tf["key"]) or 0
            parts.append(f"{ticker}上涨{_fmt_gain_cn(v)}")
        label_cn = tf["label_cn"]
        if len(parts) >= 2:
            return f"{label_cn}领涨榜前三名：" + "，".join(parts) + "。"
        elif parts:
            return f"{label_cn}领涨榜第一名：{parts[0]}。"
        return ""

    label_cn  = tf["label_cn"]
    window_cn = tf["window_cn"]
    opener_cn = (random.choice(_TF_OPENERS_CN).format(window=window_cn) +
                 "本频道每周二都会报道不同时间维度下表现最强的大盘股。订阅我们，每周不错过。")

    encode([
        (scene_title_cn(tf["title_cn"], "S&P 500  ·  纳斯达克100", date,
                        f"大盘股{label_cn}领涨榜 — 贝佐拉"), 4,
         f"S&P 500 + 纳斯达克100 大盘股{label_cn}领涨榜 — 贝佐拉",
         opener_cn),
        (scene_movers_table_cn(f"{tf['rank_cn']}  ({date})", gainers, date,
                               cta_text="想查看完整榜单？访问baizora.com — 提供七天免费试用。",
                               tf=tf), 22,
         f"S&P 500 + 纳斯达克100 — 过去{window_cn}涨幅最大的大盘股",
         f"{_narrate_tf_cn(gainers)}"
         f"这些大盘股来自S&P 500和纳斯达克100，过去{window_cn}涨幅遥遥领先全市场。"
         "想查看完整榜单，访问baizora.com，提供七天免费试用。"),
        (scene_top3_sparklines(
            f"{label_cn}领涨股 — 走势图  ({date})", gainers, date,
            "想了解更多？访问baizora.com获取S&P 500和纳斯达克100完整分析。", tf=tf), 7,
         f"{label_cn}涨幅前三股票的走势 | 更多数据请访问baizora.com",
         f"这是今日{label_cn}涨幅前三名股票的年度走势图。"
         "绿色曲线代表上涨趋势，红色代表下跌趋势。"),
        (scene_1y_sort_promo_cn(data, date, tf), 6,
         "按任意时间维度排序 — 2周至1年 — 即时筛选S&P 500和纳斯达克100领涨股",
         "在贝佐拉，可查看领涨股在一年内各时间维度的表现——从两周到一年。"
         "按任意列排序，即时发现全市场领涨股。访问baizora.com。"),
        (scene_screenshot(_SS_CN), 2),
        (scene_outro_cn(date), 5,
         "仅供参考，不构成投资建议 | baizora.com"),
    ], output, tts_voice="zh-CN-YunxiNeural")


def build_volume_spikes_cn(data, output):
    date   = data["date"]
    spikes = sorted(data["data"],
                    key=lambda r: r.get("VolumeChange1D") or -9999, reverse=True)[:10]

    encode([
        (scene_title_cn("今日成交量异动", "S&P 500  ·  纳斯达克100", date,
                        "大盘股异常交易活动 — 贝佐拉"), 6,
         "S&P 500 + 纳斯达克100 大盘股异常交易活动 — 贝佐拉",
         random.choice(_VOLUME_OPENERS_CN) +
         "本频道每周一都会报道S&P 500和纳斯达克100的成交量异动。订阅我们，每周不错过。"),
        (scene_volume_spikes_cn(spikes, date), 16,
         "量/MA21 = 今日成交量 / 21日均量  |  超过3倍的用金色高亮显示",
         _narrate_volume_cn(spikes)),
        (scene_top3_sparklines(
            f"成交量异动领涨股 — 年度走势  ({date})", spikes, date,
            "想了解更多？访问baizora.com获取S&P 500和纳斯达克100完整分析。"), 7,
         "成交量异动前三股票的一年走势 | 更多数据请访问baizora.com",
         "这是今日成交量异动前三名股票的年度走势图。"
         "每条曲线展示了过去一年的完整价格轨迹，帮助您判断成交量异动背后的价格趋势。"),
        (scene_vol_sort_promo_cn(data, date), 5,
         "按任意时间维度排序 — 1天至1年 — 即时筛选S&P 500和纳斯达克100成交量异动",
         "在贝佐拉，可查看各时间维度的成交量数据——按任意列排序。访问baizora.com。"),
        (scene_screenshot(_SS_CN), 2),
        (scene_outro_cn(date), 5,
         "仅供参考，不构成投资建议 | baizora.com"),
    ], output, tts_voice="zh-CN-YunxiNeural")


def build_platform_intro_cn(data, output):
    date   = data["date"]
    frames = [
        (scene_title_cn("隆重介绍", "贝佐拉", date,
                        "美股大盘价格与成交量分析平台"), 8,
         "贝佐拉 — 全面的美股大盘价量分析平台",
         "贝佐拉有什么独特之处？以下是区别于其他平台的五大核心功能。"),
    ]
    items = list(zip(FEATURES_CN, FEATURE_SUBS_CN, FEATURE_NARRATIONS_CN))
    for i, (feat, sub, narr) in enumerate(items):
        if i == len(items) - 1:
            narr = narr + "想了解更多关于短中期价格和成交量的分析数据？访问baizora.com。"
        frames.append((scene_platform_feature_v2_cn(feat, data), 14, sub, narr))
    frames.append((scene_screenshot(_SS_CN), 2))
    frames.append((scene_outro_cn(date), 5,
                   "仅供参考，不构成投资建议 | baizora.com"))
    encode(frames, output, tts_voice="zh-CN-YunxiNeural")


# ── Entry point ───────────────────────────────────────────────────────────────

BUILDERS = {
    "sp500_movers":       build_sp500_movers,
    "nasdaq_movers":      build_nasdaq_movers,
    "volume_spikes":      build_volume_spikes,
    "best_performer":     build_extreme_1y,
    "best_performer_cn":  build_extreme_1y_cn,
    "platform_intro":     build_platform_intro,
    "platform_intro_cn":  build_platform_intro_cn,
    "volume_spikes_cn":   build_volume_spikes_cn,
    "6m_breakout":        build_6m_breakout,
    "6m_breakout_cn":     build_6m_breakout_cn,
    "1y_vol_peak":        build_1y_vol_peak,
    "1y_vol_peak_cn":     build_1y_vol_peak_cn,
    "index_spotlight":    build_index_spotlight,
    "index_spotlight_cn": build_index_spotlight_cn,
}


def main():
    ap = argparse.ArgumentParser(description="Baizora Daily Video Generator")
    ap.add_argument("--type",   required=True, choices=list(BUILDERS),
                    help="Which video to generate")
    ap.add_argument("--output", default=None,
                    help="Output MP4 path (default: video/<type>.mp4)")
    ap.add_argument("--data",   default=None,
                    help="Path to latest.json (default: data/latest.json)")
    args = ap.parse_args()

    data_path = Path(args.data) if args.data else DATA_FILE
    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    with open(data_path) as f:
        data = json.load(f)

    output = args.output or str(SCRIPT_DIR / f"{args.type}.mp4")
    Path(output).parent.mkdir(parents=True, exist_ok=True)

    print(f"Building [{args.type}]  ->  {output}")
    BUILDERS[args.type](data, output)


if __name__ == "__main__":
    main()
